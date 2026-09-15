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

    PASS means the current installation contains concrete evidence for a gate.
    BLOCKED means the implementation exists but the required external input or
    target environment is absent. FAIL is reserved for a present-but-invalid
    condition. This prevents development/CI machines from being reported as
    production-ready merely because synthetic tests pass.
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
        gates.append(self._gate(
            "security_governance",
            "PASS" if enabled_admins > 0 else "FAIL",
            "持久化账号与RBAC已启用" if enabled_admins > 0 else "没有启用的管理员账号",
            {"enabled_admins": enabled_admins, "roles": ["admin", "operator", "reviewer", "viewer"]},
        ))

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

        evaluation = self._latest_evaluation()
        gates.append(self._gate(
            "business_gold_evaluation",
            "PASS" if evaluation is not None else "BLOCKED",
            "已有真实任务金标验收记录；阈值是否达标应由项目验收标准判定" if evaluation else "尚未导入客户历史正确集团码/人工金标进行验收",
            {"latest_evaluation": evaluation},
        ))

        scale_task = self._production_scale_task()
        gates.append(self._gate(
            "million_scale_end_to_end",
            "PASS" if scale_task is not None else "BLOCKED",
            "已检测到至少10万Source × 100万Target的正式完成任务" if scale_task else "尚无满足10万Source × 100万Target门槛的正式完成任务，synthetic benchmark不计入",
            {"task": scale_task},
        ))

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
            "schema_version": 1,
            "code_ready": fail_count == 0,
            "production_ready": fail_count == 0 and blocked_count == 0,
            "summary": {"pass": pass_count, "blocked": blocked_count, "fail": fail_count, "total": len(gates)},
            "gates": gates,
            "semantics": {
                "PASS": "有当前环境的具体证据",
                "BLOCKED": "代码路径已具备，但缺外部数据/模型/目标机器/正式介质证据",
                "FAIL": "已发现实际配置或实现缺陷",
            },
        }
