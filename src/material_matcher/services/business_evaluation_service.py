from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Iterable
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.ingestion.reader import iter_tabular_rows
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _ratio(value: int, total: int) -> float:
    return round(value / total, 6) if total else 0.0


def _optional_ratio(value: int, total: int) -> float | None:
    return round(value / total, 6) if total else None


def _chunks(values: list[str], size: int = 500) -> Iterable[list[str]]:
    for start in range(0, len(values), size):
        yield values[start : start + size]


class BusinessEvaluationService:
    """Evaluate frozen task results against an explicit business truth file."""

    def __init__(self, metadata: MetadataRepository, files: FileRepository) -> None:
        self.meta = metadata
        self.files = files

    def _task(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        return dict(row)

    @staticmethod
    def _configured_top_n(task: dict[str, object]) -> int:
        try:
            document = json.loads(str(task.get("config_snapshot") or "{}"))
            return max(1, int(document.get("decision", {}).get("top_n", 1)))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 1

    def _truth(
        self,
        file_id: str,
        key_column: str,
        expected_column: str,
        expected_result_column: str | None,
    ) -> dict[str, tuple[str, str]]:
        record = self.files.get(file_id)
        if record.get("role") != "supplement":
            raise DomainError("INVALID_FILE_ROLE", "准确率验收文件必须使用 supplement 文件", status_code=422)
        truth: dict[str, tuple[str, str]] = {}
        explicit_mode = bool(expected_result_column)
        for row in iter_tabular_rows(Path(str(record["stored_path"]))):
            key = str(row.get(key_column) or "").strip()
            expected = str(row.get(expected_column) or "").strip()
            raw_result = str(row.get(str(expected_result_column)) or "").strip().upper() if explicit_mode else "MATCH"
            if not key and not expected and (not explicit_mode or not raw_result):
                continue
            if not key:
                raise DomainError(
                    "EVALUATION_LABEL_INCOMPLETE",
                    "验收文件存在源记录标识为空的行",
                    status_code=422,
                    details={"key_column": key_column},
                )
            if not explicit_mode:
                if not expected:
                    raise DomainError(
                        "EVALUATION_LABEL_INCOMPLETE",
                        "旧版金标格式要求正确集团码不能为空；如需表达无匹配结果，请增加 expected_result 列并显式填写 NO_MATCH",
                        status_code=422,
                        details={"key": key, "expected_column": expected_column},
                    )
                expected_result = "MATCH"
            else:
                if raw_result not in {"MATCH", "NO_MATCH"}:
                    raise DomainError(
                        "EVALUATION_RESULT_INVALID",
                        "expected_result 仅支持 MATCH 或 NO_MATCH，且不得留空",
                        status_code=422,
                        details={"key": key, "expected_result": raw_result},
                    )
                expected_result = raw_result
                if expected_result == "MATCH" and not expected:
                    raise DomainError(
                        "EVALUATION_LABEL_INCOMPLETE",
                        "expected_result=MATCH 时 expected_group_code 不能为空",
                        status_code=422,
                        details={"key": key, "expected_column": expected_column},
                    )
                if expected_result == "NO_MATCH" and expected:
                    raise DomainError(
                        "EVALUATION_NO_MATCH_HAS_GROUP_CODE",
                        "expected_result=NO_MATCH 时 expected_group_code 必须为空",
                        status_code=422,
                        details={"key": key, "expected_group_code": expected},
                    )
            label = (expected_result, expected)
            previous = truth.get(key)
            if previous is not None and previous != label:
                raise DomainError(
                    "EVALUATION_LABEL_CONFLICT",
                    f"验收文件中标识“{key}”存在冲突金标",
                    status_code=422,
                    details={"key": key, "first": previous, "second": label},
                )
            truth[key] = label
        if not truth:
            raise DomainError("EVALUATION_LABEL_EMPTY", "验收文件没有可用的标注数据", status_code=422)
        return truth

    def _task_items(self, task_id: str, key_mode: str, keys: list[str]) -> dict[str, dict[str, object]]:
        column = "source_id" if key_mode == "source_id" else "source_row_id"
        found: dict[str, dict[str, object]] = {}
        for batch in _chunks(keys):
            placeholders = ",".join("?" for _ in batch)
            with self.meta.connect() as connection:
                rows = connection.execute(
                    f"SELECT * FROM match_items WHERE task_id=? AND {column} IN ({placeholders})",
                    (task_id, *batch),
                ).fetchall()
            for row in rows:
                item = dict(row)
                key = str(item[column])
                if key in found:
                    raise DomainError(
                        "EVALUATION_TASK_KEY_AMBIGUOUS",
                        f"任务结果中标识“{key}”不唯一，请改用 source_row_id 验收",
                        status_code=422,
                        details={"key": key, "key_mode": key_mode},
                    )
                found[key] = item
        return found

    def _candidate_ranks(self, task_id: str, source_row_ids: list[str]) -> dict[str, dict[str, int]]:
        result: dict[str, dict[str, int]] = {}
        for batch in _chunks(source_row_ids):
            placeholders = ",".join("?" for _ in batch)
            with self.meta.connect() as connection:
                rows = connection.execute(
                    f"SELECT source_row_id,rank,target_group_code FROM match_candidates WHERE task_id=? AND source_row_id IN ({placeholders}) ORDER BY source_row_id,rank",
                    (task_id, *batch),
                ).fetchall()
            for row in rows:
                per_row = result.setdefault(str(row["source_row_id"]), {})
                code = str(row["target_group_code"])
                per_row.setdefault(code, int(row["rank"]))
        return result

    def evaluate(
        self,
        task_id: str,
        *,
        truth_file_id: str,
        key_column: str,
        expected_group_code_column: str,
        key_mode: str = "source_id",
        expected_result_column: str | None = None,
    ) -> dict[str, object]:
        if key_mode not in {"source_id", "source_row_id"}:
            raise DomainError("EVALUATION_KEY_MODE_INVALID", "验收键模式仅支持 source_id 或 source_row_id", status_code=422)
        task = self._task(task_id)
        if task.get("status") != "COMPLETED":
            raise DomainError("TASK_STATE_CONFLICT", "只有计算完成的任务才能进行准确率验收", status_code=409)

        configured_top_n = self._configured_top_n(task)
        recall_ks = [1, 3, 5, 10]
        truth = self._truth(truth_file_id, key_column, expected_group_code_column, expected_result_column)
        items = self._task_items(task_id, key_mode, list(truth))
        candidate_ranks = self._candidate_ranks(task_id, [str(item["source_row_id"]) for item in items.values()])

        evaluated = 0
        positive_evaluated = 0
        no_match_evaluated = 0
        positive_top1_correct = 0
        final_correct = 0
        automatic_rows = 0
        automatic_correct = 0
        current_automatic_rows = 0
        current_automatic_correct = 0
        review_rows = 0
        current_review_rows = 0
        unmatched_rows = 0
        resolved_rows = 0
        human_changed_rows = 0
        no_match_true_negative = 0
        no_match_false_positive = 0
        candidate_hits = {k: 0 for k in recall_ks}
        details: list[dict[str, object]] = []

        for key, (expected_result, expected) in truth.items():
            item = items.get(key)
            if item is None:
                details.append({
                    "truth_key": key,
                    "expected_result": expected_result,
                    "expected_group_code": expected,
                    "matched_task_row": False,
                })
                continue
            evaluated += 1
            top1 = str(item.get("top1_group_code") or "")
            final = str(item.get("final_group_code") or "")
            original_status = str(item.get("original_status") or "")
            current_status = str(item.get("current_status") or "")
            is_positive = expected_result == "MATCH"

            if is_positive:
                positive_evaluated += 1
                top1_ok = top1 == expected
                final_ok = final == expected
                positive_top1_correct += int(top1_ok)
                ranks = candidate_ranks.get(str(item["source_row_id"]), {})
                expected_rank = ranks.get(expected)
                for k in candidate_hits:
                    if expected_rank is not None and expected_rank <= k:
                        candidate_hits[k] += 1
            else:
                no_match_evaluated += 1
                top1_ok = False
                final_ok = current_status == "UNMATCHED" and not final
                expected_rank = None
                if final_ok:
                    no_match_true_negative += 1
                if current_status in {"MATCHED", "CONFIRMED"} or bool(final):
                    no_match_false_positive += 1

            final_correct += int(final_ok)
            # Legacy workload metrics describe the task's original decision before
            # manual review and are kept stable for existing reports.
            if original_status == "MATCHED":
                automatic_rows += 1
                automatic_correct += int(is_positive and top1 == expected)
            if original_status == "REVIEW":
                review_rows += 1
            if original_status == "UNMATCHED":
                unmatched_rows += 1

            # Formal calibration metrics describe the current global decision. A
            # manually CONFIRMED row is deliberately not counted as automatic.
            if current_status == "MATCHED":
                current_automatic_rows += 1
                current_automatic_correct += int(is_positive and top1 == expected)
            if current_status == "REVIEW":
                current_review_rows += 1

            # Preserve the legacy definition for positive truth (a selected group
            # code means resolved) while allowing explicit NO_MATCH truth to be
            # resolved by a correct UNMATCHED decision without inventing a code.
            if final or (not is_positive and current_status == "UNMATCHED"):
                resolved_rows += 1
            if final and final != top1:
                human_changed_rows += 1

            details.append({
                "truth_key": key,
                "expected_result": expected_result,
                "expected_group_code": expected,
                "matched_task_row": True,
                "source_row_id": item["source_row_id"],
                "source_id": item["source_id"],
                "original_status": original_status,
                "current_status": current_status,
                "top1_group_code": item.get("top1_group_code"),
                "final_group_code": item.get("final_group_code"),
                "top1_score": item.get("top1_score"),
                "top1_correct": top1_ok,
                "final_correct": final_ok,
                "expected_candidate_rank": expected_rank,
            })

        positive_top1_accuracy = _ratio(positive_top1_correct, positive_evaluated)
        legacy_automatic_accuracy = _ratio(automatic_correct, automatic_rows)
        automatic_match_precision = _ratio(current_automatic_correct, current_automatic_rows)
        metrics = {
            "truth_rows": len(truth),
            "evaluated_rows": evaluated,
            "truth_coverage": _ratio(evaluated, len(truth)),
            "positive_truth_rows": positive_evaluated,
            "no_match_truth_rows": no_match_evaluated,
            "top1_correct": positive_top1_correct,
            "top1_accuracy": positive_top1_accuracy,
            "positive_top1_accuracy": positive_top1_accuracy,
            "final_correct": final_correct,
            "final_accuracy": _ratio(final_correct, evaluated),
            "human_accuracy_gain": _ratio(final_correct - positive_top1_correct - no_match_true_negative, evaluated),
            "automatic_rows": automatic_rows,
            "automatic_correct": automatic_correct,
            "automatic_accuracy": legacy_automatic_accuracy,
            "automatic_match_rows": current_automatic_rows,
            "automatic_match_correct": current_automatic_correct,
            "automatic_match_precision": automatic_match_precision,
            "review_rows": review_rows,
            "review_rate": _ratio(review_rows, evaluated),
            "current_review_rows": current_review_rows,
            "current_review_rate": _ratio(current_review_rows, evaluated),
            "unmatched_rows": unmatched_rows,
            "unmatched_rate": _ratio(unmatched_rows, evaluated),
            "resolved_rows": resolved_rows,
            "resolved_rate": _ratio(resolved_rows, evaluated),
            "human_changed_rows": human_changed_rows,
            "candidate_top_n": configured_top_n,
            "candidate_recall_at": {str(k): _ratio(value, positive_evaluated) for k, value in candidate_hits.items()},
            "candidate_recall_at_5": _ratio(candidate_hits[5], positive_evaluated),
            "candidate_recall_at_10": _ratio(candidate_hits[10], positive_evaluated),
            "no_match_true_negative": no_match_true_negative,
            "no_match_false_positive": no_match_false_positive,
            "no_match_true_negative_rate": _optional_ratio(no_match_true_negative, no_match_evaluated),
            "no_match_false_positive_rate": _optional_ratio(no_match_false_positive, no_match_evaluated),
        }
        run_id = uuid.uuid4().hex
        created_at = _now()
        with self.meta.connect() as connection:
            connection.execute(
                "INSERT INTO evaluation_runs(run_id,task_id,truth_file_id,key_mode,key_column,expected_column,expected_result_column,metrics,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    run_id,
                    task_id,
                    truth_file_id,
                    key_mode,
                    key_column,
                    expected_group_code_column,
                    expected_result_column,
                    json.dumps(metrics, ensure_ascii=False, separators=(",", ":")),
                    created_at,
                ),
            )
            connection.executemany(
                "INSERT INTO evaluation_items(run_id,truth_key,expected_result,expected_group_code,matched_task_row,source_row_id,source_id,original_status,current_status,top1_group_code,final_group_code,top1_score,top1_correct,final_correct,expected_candidate_rank) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        run_id,
                        item["truth_key"],
                        item["expected_result"],
                        item["expected_group_code"],
                        1 if item.get("matched_task_row") else 0,
                        item.get("source_row_id"),
                        item.get("source_id"),
                        item.get("original_status"),
                        item.get("current_status"),
                        item.get("top1_group_code"),
                        item.get("final_group_code"),
                        item.get("top1_score"),
                        1 if item.get("top1_correct") else 0,
                        1 if item.get("final_correct") else 0,
                        item.get("expected_candidate_rank"),
                    )
                    for item in details
                ],
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "evaluation",
                    run_id,
                    "BUSINESS_ACCURACY_EVALUATED",
                    json.dumps({"task_id": task_id, "metrics": metrics}, ensure_ascii=False, separators=(",", ":")),
                    created_at,
                ),
            )
        return self.get(run_id)

    def get(self, run_id: str, *, include_items: bool = False, only_errors: bool = False, limit: int = 200) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM evaluation_runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise DomainError("EVALUATION_NOT_FOUND", "准确率验收记录不存在", status_code=404)
        result = dict(row)
        result["metrics"] = json.loads(str(result["metrics"]))
        if include_items:
            where = "run_id=?"
            params: list[object] = [run_id]
            if only_errors:
                where += " AND (matched_task_row=0 OR final_correct=0 OR top1_correct=0)"
            with self.meta.connect() as connection:
                rows = connection.execute(
                    f"SELECT * FROM evaluation_items WHERE {where} ORDER BY matched_task_row, final_correct, top1_correct, truth_key LIMIT ?",
                    (*params, max(1, min(2000, int(limit)))),
                ).fetchall()
            result["items"] = [dict(item) for item in rows]
        return result

    def list_for_task(self, task_id: str, limit: int = 20) -> list[dict[str, object]]:
        self._task(task_id)
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM evaluation_runs WHERE task_id=? ORDER BY created_at DESC LIMIT ?",
                (task_id, max(1, min(200, int(limit)))),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(str(item["metrics"]))
            result.append(item)
        return result
