from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
import platform
from typing import Any

from material_matcher.embedding.providers import embedding_runtime_status
from material_matcher.services.deployment_service import deployment_diagnostics
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository


class AcceptanceService:
    """Generate evidence-based production acceptance gates.

    PASS means the current installation contains concrete evidence and, where
    applicable, that evidence meets explicitly configured acceptance criteria.
    BLOCKED means the code path exists but external inputs, target environment,
    or project acceptance thresholds are still missing. FAIL is reserved for a
    present-but-invalid condition or measured evidence below an explicit gate.
    """

    def __init__(self, metadata: MetadataRepository, settings: Settings) -> None:
        self.meta = metadata
        self.settings = settings

    @staticmethod
    def _gate(name: str, status: str, message: str, evidence: dict[str, Any] | None = None) -> dict[str, Any]:
        return {"name": name, "status": status, "message": message, "evidence": evidence or {}}

    @staticmethod
    def _parse_json(value: object) -> dict[str, Any]:
        if not value:
            return {}
        try:
            parsed = json.loads(str(value))
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _duration_seconds(started_at: object, finished_at: object) -> float | None:
        if not started_at or not finished_at:
            return None
        try:
            start = datetime.fromisoformat(str(started_at))
            finish = datetime.fromisoformat(str(finished_at))
            return max(0.0, (finish - start).total_seconds())
        except Exception:
            return None

    def _os_release(self) -> dict[str, str]:
        values: dict[str, str] = {}
        path = Path("/etc/os-release")
        if path.is_file():
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
                if "=" not in line:
                    continue
                key, raw = line.split("=", 1)
                values[key.strip()] = raw.strip().strip('"')
        return values

    def _latest_successful_benchmark(self, kind: str) -> dict[str, Any] | None:
        with self.meta.connect() as connection:
            row = connection.execute(
                "SELECT * FROM benchmark_runs WHERE kind=? AND status='SUCCESS' ORDER BY started_at DESC LIMIT 1",
                (kind,),
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        result["parameters"] = self._parse_json(result.get("parameters"))
        result["metrics"] = self._parse_json(result.get("metrics"))
        return result

    def _latest_evaluation(self) -> dict[str, Any] | None:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM evaluation_runs ORDER BY created_at DESC LIMIT 1").fetchone()
        if row is None:
            return None
        result = dict(row)
        result["metrics"] = self._parse_json(result.get("metrics"))
        return result

    def _production_scale_task(self) -> dict[str, Any] | None:
        with self.meta.connect() as connection:
            rows = connection.execute(
                """
                SELECT t.task_id,t.name,t.status,t.total_rows,t.started_at,t.finished_at,
                       r.execution_mode,r.index_id,i.metadata AS index_metadata
                FROM tasks t
                LEFT JOIN task_runtime r ON r.task_id=t.task_id
                LEFT JOIN index_versions i ON i.index_id=r.index_id
                WHERE t.status='COMPLETED'
                ORDER BY t.finished_at DESC
                """
            ).fetchall()
        for row in rows:
            item = dict(row)
            metadata = self._parse_json(item.get("index_metadata"))
            target_rows = int(
                metadata.get("stats", {}).get("row_count")
                or metadata.get("index_metadata", {}).get("row_count")
                or 0
            )
            source_rows = int(item.get("total_rows") or 0)
            if source_rows >= 100_000 and target_rows >= 1_000_000:
                return {
                    "task_id": item["task_id"],
                    "name": item["name"],
                    "execution_mode": item.get("execution_mode"),
                    "index_id": item.get("index_id"),
                    "source_rows": source_rows,
                    "target_rows": target_rows,
                    "duration_seconds": self._duration_seconds(item.get("started_at"), item.get("finished_at")),
                    "started_at": item.get("started_at"),
                    "finished_at": item.get("finished_at"),
                }
        return None

    def _policy_gate(self) -> tuple[dict[str, Any], bool]:
        thresholds = self.settings.acceptance_thresholds
        required = {
            "min_truth_rows": thresholds["min_truth_rows"],
            "min_truth_coverage": thresholds["min_truth_coverage"],
            "min_top1_accuracy": thresholds["min_top1_accuracy"],
            "min_final_accuracy": thresholds["min_final_accuracy"],
            "max_review_rate": thresholds["max_review_rate"],
            "min_candidate_recall_at_5": thresholds["min_candidate_recall_at_5"],
            "min_automatic_precision": thresholds["min_automatic_precision"],
            "max_no_match_false_positive_rate": thresholds["max_no_match_false_positive_rate"],
            "max_scale_hours": thresholds["max_scale_hours"],
        }
        missing = [name for name, value in required.items() if value is None]
        invalid: list[str] = []
        if thresholds["min_truth_rows"] is not None and int(thresholds["min_truth_rows"]) <= 0:
            invalid.append("min_truth_rows")
        ratio_names = (
            "min_truth_coverage",
            "min_top1_accuracy",
            "min_final_accuracy",
            "max_review_rate",
            "min_candidate_recall_at_5",
            "min_automatic_precision",
            "max_no_match_false_positive_rate",
        )
        for name in ratio_names:
            value = thresholds[name]
            if value is not None and not 0.0 <= float(value) <= 1.0:
                invalid.append(name)
        if thresholds["max_scale_hours"] is not None and float(thresholds["max_scale_hours"]) <= 0.0:
            invalid.append("max_scale_hours")
        if invalid:
            return self._gate(
                "acceptance_policy",
                "FAIL",
                "生产验收阈值配置非法，请修正后重新验收",
                {"thresholds": thresholds, "invalid": invalid},
            ), False
        if missing:
            return self._gate(
                "acceptance_policy",
                "BLOCKED",
                "尚未显式配置项目生产验收阈值；系统不会使用内置拍脑袋阈值替代业务签字标准",
                {"thresholds": thresholds, "missing": missing},
            ), False
        return self._gate(
            "acceptance_policy",
            "PASS",
            "生产验收阈值已显式配置",
            {"thresholds": thresholds},
        ), True

    @staticmethod
    def _metric(metrics: dict[str, Any], name: str, *fallbacks: str) -> float | None:
        for key in (name, *fallbacks):
            value = metrics.get(key)
            if value is not None:
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return None
        return None

    def _business_evaluation_gate(self, policy_ready: bool) -> dict[str, Any]:
        evaluation = self._latest_evaluation()
        thresholds = self.settings.acceptance_thresholds
        if evaluation is None:
            return self._gate(
                "business_gold_evaluation",
                "BLOCKED",
                "尚未导入客户历史正确集团码/人工金标进行验收",
                {"thresholds": thresholds},
            )
        if not policy_ready:
            return self._gate(
                "business_gold_evaluation",
                "BLOCKED",
                "已有真实金标结果，但项目验收阈值尚未完整配置，不能判定PASS",
                {"latest_evaluation": evaluation, "thresholds": thresholds},
            )
        metrics = evaluation.get("metrics") or {}
        recall_at = metrics.get("candidate_recall_at") if isinstance(metrics.get("candidate_recall_at"), dict) else {}
        recall5 = self._metric(metrics, "candidate_recall_at_5")
        if recall5 is None and recall_at.get("5") is not None:
            recall5 = float(recall_at["5"])
        automatic_precision = self._metric(metrics, "automatic_match_precision", "automatic_accuracy")
        no_match_fpr = self._metric(metrics, "no_match_false_positive_rate")
        missing_evidence: list[str] = []
        if recall5 is None:
            missing_evidence.append("candidate_recall_at_5")
        if automatic_precision is None:
            missing_evidence.append("automatic_match_precision")
        if no_match_fpr is None:
            missing_evidence.append("no_match_false_positive_rate")
        if missing_evidence:
            return self._gate(
                "business_gold_evaluation",
                "BLOCKED",
                "最新真实金标缺少本版正式验收所需指标，请使用含显式 NO_MATCH 金标重新验收",
                {"latest_evaluation": evaluation, "thresholds": thresholds, "missing_metrics": missing_evidence},
            )
        checks = {
            "truth_rows": int(metrics.get("truth_rows") or 0) >= int(thresholds["min_truth_rows"]),
            "truth_coverage": float(metrics.get("truth_coverage") or 0.0) >= float(thresholds["min_truth_coverage"]),
            "top1_accuracy": float(metrics.get("top1_accuracy") or 0.0) >= float(thresholds["min_top1_accuracy"]),
            "candidate_recall_at_5": recall5 >= float(thresholds["min_candidate_recall_at_5"]),
            "automatic_match_precision": automatic_precision >= float(thresholds["min_automatic_precision"]),
            "final_accuracy": float(metrics.get("final_accuracy") or 0.0) >= float(thresholds["min_final_accuracy"]),
            "review_rate": float(metrics.get("review_rate") or 0.0) <= float(thresholds["max_review_rate"]),
            "no_match_false_positive_rate": no_match_fpr <= float(thresholds["max_no_match_false_positive_rate"]),
        }
        passed = all(checks.values())
        return self._gate(
            "business_gold_evaluation",
            "PASS" if passed else "FAIL",
            "真实业务金标指标达到项目验收阈值" if passed else "真实业务金标指标低于项目验收阈值",
            {"latest_evaluation": evaluation, "thresholds": thresholds, "checks": checks},
        )

    def _million_scale_gate(self, policy_ready: bool) -> dict[str, Any]:
        scale_task = self._production_scale_task()
        thresholds = self.settings.acceptance_thresholds
        if scale_task is None:
            return self._gate(
                "million_scale_end_to_end",
                "BLOCKED",
                "尚无满足10万Source × 100万Target门槛的正式完成任务，synthetic benchmark不计入",
                {"task": None, "max_scale_hours": thresholds["max_scale_hours"]},
            )
        if not policy_ready:
            return self._gate(
                "million_scale_end_to_end",
                "BLOCKED",
                "已有百万级正式任务，但尚未配置最大允许端到端耗时，不能判定PASS",
                {"task": scale_task, "max_scale_hours": thresholds["max_scale_hours"]},
            )
        duration = scale_task.get("duration_seconds")
        if duration is None:
            return self._gate(
                "million_scale_end_to_end",
                "FAIL",
                "百万级任务缺少完整起止时间，无法形成性能验收证据",
                {"task": scale_task, "max_scale_hours": thresholds["max_scale_hours"]},
            )
        max_seconds = float(thresholds["max_scale_hours"]) * 3600.0
        passed = float(duration) <= max_seconds
        return self._gate(
            "million_scale_end_to_end",
            "PASS" if passed else "FAIL",
            "百万级正式任务规模与端到端耗时均达到项目门槛" if passed else "百万级正式任务已完成，但端到端耗时超过项目门槛",
            {"task": scale_task, "max_scale_hours": thresholds["max_scale_hours"], "duration_hours": round(float(duration) / 3600.0, 6)},
        )

    def report(self) -> dict[str, Any]:
        gates: list[dict[str, Any]] = []

        diagnostics = deployment_diagnostics(
            self.settings,
            require_frontend=False,
            require_embedding=False,
            require_release_manifest=False,
        )
        base_failed = [name for name in diagnostics.get("failed_checks", []) if name in {"data_dir", "tmp_dir", "config_dir", "log_dir"}]
        gates.append(self._gate(
            "runtime_directories",
            "FAIL" if base_failed else "PASS",
            "运行目录存在且权限可用" if not base_failed else "运行目录或权限不满足部署要求",
            {"failed": base_failed},
        ))

        with self.meta.connect() as connection:
            enabled_admins = int(connection.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND enabled=1").fetchone()["count"])
            ready_admins = int(connection.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND enabled=1 AND must_change_password=0").fetchone()["count"])
        if enabled_admins == 0:
            security_status = "FAIL"
            security_message = "没有启用的管理员账号"
        elif ready_admins == 0:
            security_status = "BLOCKED"
            security_message = "管理员账号仍处于强制改密状态，请先完成首次密码轮换"
        else:
            security_status = "PASS"
            security_message = "持久化账号与服务端RBAC已启用，至少一个管理员已完成密码轮换"
        gates.append(self._gate(
            "security_governance",
            security_status,
            security_message,
            {"enabled_admins": enabled_admins, "ready_admins": ready_admins, "roles": ["admin", "operator", "reviewer", "viewer"]},
        ))

        policy_gate, policy_ready = self._policy_gate()
        gates.append(policy_gate)

        frontend_ready = bool(diagnostics["checks"]["frontend"].get("ready"))
        release_ready = bool(diagnostics["checks"]["release_manifest"].get("ready"))
        gates.append(self._gate(
            "offline_release",
            "PASS" if frontend_ready and release_ready else "BLOCKED",
            "正式前端与release-manifest已在当前安装中验证" if frontend_ready and release_ready else "当前环境不是完整正式Release；请使用离线构建产物在目标机执行验收",
            {"frontend_ready": frontend_ready, "release_manifest_ready": release_ready},
        ))

        embedding = embedding_runtime_status(self.settings)
        embedding_benchmark = self._latest_successful_benchmark("embedding")
        embedding_pass = bool(embedding.get("ready")) and embedding_benchmark is not None
        gates.append(self._gate(
            "production_embedding",
            "PASS" if embedding_pass else "BLOCKED",
            "正式Embedding模型已就绪且存在成功吞吐基准" if embedding_pass else "缺正式Embedding模型/runtime或尚未运行正式Embedding基准",
            {"runtime": embedding, "latest_benchmark": embedding_benchmark},
        ))

        vector_benchmark = self._latest_successful_benchmark("vector_kernel")
        gates.append(self._gate(
            "vector_recall_guard",
            "PASS" if vector_benchmark is not None else "BLOCKED",
            "已有可重复的BBQ吞吐与float32 reference Recall基线" if vector_benchmark else "尚未运行BBQ Recall基准",
            {"latest_benchmark": vector_benchmark},
        ))

        gates.append(self._business_evaluation_gate(policy_ready))
        gates.append(self._million_scale_gate(policy_ready))

        os_release = self._os_release()
        os_text = " ".join([os_release.get("ID", ""), os_release.get("NAME", ""), os_release.get("PRETTY_NAME", ""), os_release.get("VERSION", "")]).lower()
        kylin = "kylin" in os_text or "麒麟" in os_text
        version10 = "10" in os_text
        gates.append(self._gate(
            "kylin_v10_host",
            "PASS" if kylin and version10 else "BLOCKED",
            "当前验收环境识别为银河麒麟V10" if kylin and version10 else "当前机器不是可识别的银河麒麟V10目标环境",
            {"os_release": os_release, "machine": platform.machine(), "platform": platform.platform()},
        ))

        fail_count = sum(gate["status"] == "FAIL" for gate in gates)
        blocked_count = sum(gate["status"] == "BLOCKED" for gate in gates)
        pass_count = sum(gate["status"] == "PASS" for gate in gates)
        return {
            "schema_version": 3,
            "code_ready": fail_count == 0,
            "production_ready": fail_count == 0 and blocked_count == 0,
            "summary": {"pass": pass_count, "blocked": blocked_count, "fail": fail_count, "total": len(gates)},
            "gates": gates,
            "semantics": {
                "PASS": "有当前环境的具体证据，并满足已配置的验收阈值",
                "BLOCKED": "代码路径已具备，但缺外部数据/模型/目标机器/正式介质或项目阈值",
                "FAIL": "已发现实际配置/实现缺陷，或实测指标低于显式验收阈值",
            },
        }
