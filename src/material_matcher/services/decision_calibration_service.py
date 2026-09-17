from __future__ import annotations

from datetime import datetime
import json
from typing import Any, Iterable
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.storage.metadata import MetadataRepository


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class DecisionCalibrationService:
    """Fast threshold calibration over persisted match decisions.

    The service never invokes embedding, candidate retrieval or reranking. All
    previews are SQL aggregations over match_items / match_candidates and apply
    uses one set-based UPDATE for every non-human-reviewed row.
    """

    def __init__(self, metadata: MetadataRepository) -> None:
        self.meta = metadata

    @staticmethod
    def _validate(success_threshold: float, review_threshold: float) -> tuple[float, float]:
        success = float(success_threshold)
        review = float(review_threshold)
        if not 0 <= review < success <= 100:
            raise DomainError(
                "INVALID_THRESHOLDS",
                "阈值不合法:需满足 0 ≤ 人工下限 < 自动阈值 ≤ 100",
                status_code=422,
            )
        return success, review

    @staticmethod
    def _counts_from_rows(rows: Iterable[Any]) -> dict[str, int]:
        raw = {str(row["current_status"]): int(row["n"]) for row in rows}
        return {
            "matched": raw.get("MATCHED", 0),
            "review": raw.get("REVIEW", 0),
            "unmatched": raw.get("UNMATCHED", 0),
            "confirmed": raw.get("CONFIRMED", 0),
        }

    @staticmethod
    def _task(connection: Any, task_id: str) -> Any:
        task = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
        if task is None:
            raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
        if str(task["status"]) != "COMPLETED":
            raise DomainError("TASK_STATE_CONFLICT", "任务尚未完成比对,不能调整阈值", status_code=409)
        return task

    @staticmethod
    def _full_counts(connection: Any, task_id: str) -> dict[str, int]:
        rows = connection.execute(
            "SELECT current_status,COUNT(*) AS n FROM match_items WHERE task_id=? GROUP BY current_status",
            (task_id,),
        ).fetchall()
        return DecisionCalibrationService._counts_from_rows(rows)

    @staticmethod
    def _transition_rows(connection: Any, task_id: str, success: float, review: float) -> list[Any]:
        return connection.execute(
            """
            WITH thresholds(success_threshold,review_threshold) AS (VALUES(?,?)),
            classified AS (
              SELECT m.current_status AS old_status,
                     CASE
                       WHEN m.top1_score > t.success_threshold
                            AND m.critical_conflict=0
                            AND NOT EXISTS(
                              SELECT 1 FROM match_candidates c2
                              WHERE c2.task_id=m.task_id AND c2.source_row_id=m.source_row_id AND c2.rank=2
                                AND c2.target_group_code<>m.top1_group_code
                                AND ABS(COALESCE(m.second_score,0)-COALESCE(m.top1_score,0)) < 0.000001
                            ) THEN 'MATCHED'
                       WHEN m.top1_score > t.review_threshold THEN 'REVIEW'
                       ELSE 'UNMATCHED'
                     END AS new_status
              FROM match_items m CROSS JOIN thresholds t
              WHERE m.task_id=?
                AND m.current_status IN ('MATCHED','REVIEW','UNMATCHED')
                AND NOT EXISTS(
                  SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id
                )
            )
            SELECT old_status,new_status,COUNT(*) AS n
            FROM classified
            GROUP BY old_status,new_status
            """,
            (success, review, task_id),
        ).fetchall()

    @staticmethod
    def _preview_from_connection(connection: Any, task_id: str, success: float, review: float) -> dict[str, object]:
        before = DecisionCalibrationService._full_counts(connection, task_id)
        transitions_raw = DecisionCalibrationService._transition_rows(connection, task_id, success, review)
        after = dict(before)
        transitions: dict[str, int] = {}
        affected = 0
        for row in transitions_raw:
            old = str(row["old_status"])
            new = str(row["new_status"])
            n = int(row["n"])
            key = f"{old}->{new}"
            transitions[key] = n
            if old != new:
                affected += n
                before_key = "matched" if old == "MATCHED" else "review" if old == "REVIEW" else "unmatched"
                after_key = "matched" if new == "MATCHED" else "review" if new == "REVIEW" else "unmatched"
                after[before_key] -= n
                after[after_key] += n
        protected = int(connection.execute(
            """SELECT COUNT(*) FROM match_items m
               WHERE m.task_id=? AND EXISTS(
                 SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id
               )""",
            (task_id,),
        ).fetchone()[0])
        critical_protected = int(connection.execute(
            """SELECT COUNT(*) FROM match_items m
               WHERE m.task_id=? AND m.current_status IN ('MATCHED','REVIEW','UNMATCHED')
                 AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id)
                 AND m.top1_score>? AND m.critical_conflict=1""",
            (task_id, success),
        ).fetchone()[0])
        ambiguity_protected = int(connection.execute(
            """SELECT COUNT(*) FROM match_items m
               WHERE m.task_id=? AND m.current_status IN ('MATCHED','REVIEW','UNMATCHED')
                 AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id)
                 AND m.top1_score>?
                 AND EXISTS(
                   SELECT 1 FROM match_candidates c2
                   WHERE c2.task_id=m.task_id AND c2.source_row_id=m.source_row_id AND c2.rank=2
                     AND c2.target_group_code<>m.top1_group_code
                     AND ABS(COALESCE(m.second_score,0)-COALESCE(m.top1_score,0)) < 0.000001
                 )""",
            (task_id, success),
        ).fetchone()[0])
        return {
            "task_id": task_id,
            "mode": "preview",
            "success_threshold": success,
            "review_threshold": review,
            "before": before,
            "after": after,
            "matched_delta": after["matched"] - before["matched"],
            "review_delta": after["review"] - before["review"],
            "unmatched_delta": after["unmatched"] - before["unmatched"],
            "affected_rows": affected,
            "transitions": transitions,
            "human_protected": protected,
            "critical_conflict_protected": critical_protected,
            "ambiguity_protected": ambiguity_protected,
        }

    def preview(self, task_id: str, success_threshold: float, review_threshold: float) -> dict[str, object]:
        success, review = self._validate(success_threshold, review_threshold)
        with self.meta.connect() as connection:
            self._task(connection, task_id)
            return self._preview_from_connection(connection, task_id, success, review)

    def batch_preview(self, task_id: str, scenarios: list[dict[str, float]]) -> dict[str, object]:
        if not scenarios:
            raise DomainError("CALIBRATION_SCENARIOS_EMPTY", "至少需要一个阈值组合", status_code=422)
        if len(scenarios) > 100:
            raise DomainError("CALIBRATION_SCENARIOS_TOO_MANY", "一次最多预览100组阈值", status_code=422)
        normalized: list[tuple[int, float, float]] = []
        for index, item in enumerate(scenarios):
            success, review = self._validate(item["success_threshold"], item["review_threshold"])
            normalized.append((index, success, review))
        values_sql = ",".join("(?,?,?)" for _ in normalized)
        params: list[object] = []
        for row in normalized:
            params.extend(row)
        params.append(task_id)
        with self.meta.connect() as connection:
            self._task(connection, task_id)
            before = self._full_counts(connection, task_id)
            rows = connection.execute(
                f"""
                WITH scenarios(idx,success_threshold,review_threshold) AS (VALUES {values_sql}),
                classified AS (
                  SELECT s.idx,m.current_status AS old_status,
                         CASE
                           WHEN m.top1_score>s.success_threshold AND m.critical_conflict=0
                                AND NOT EXISTS(
                                  SELECT 1 FROM match_candidates c2
                                  WHERE c2.task_id=m.task_id AND c2.source_row_id=m.source_row_id AND c2.rank=2
                                    AND c2.target_group_code<>m.top1_group_code
                                    AND ABS(COALESCE(m.second_score,0)-COALESCE(m.top1_score,0)) < 0.000001
                                ) THEN 'MATCHED'
                           WHEN m.top1_score>s.review_threshold THEN 'REVIEW'
                           ELSE 'UNMATCHED'
                         END AS new_status
                  FROM scenarios s
                  JOIN match_items m ON m.task_id=?
                  WHERE m.current_status IN ('MATCHED','REVIEW','UNMATCHED')
                    AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id)
                )
                SELECT idx,old_status,new_status,COUNT(*) AS n
                FROM classified
                GROUP BY idx,old_status,new_status
                ORDER BY idx
                """,
                params,
            ).fetchall()
        grouped: dict[int, list[Any]] = {index: [] for index, _, _ in normalized}
        for row in rows:
            grouped[int(row["idx"])].append(row)
        results: list[dict[str, object]] = []
        for index, success, review in normalized:
            after = dict(before)
            transitions: dict[str, int] = {}
            affected = 0
            for row in grouped[index]:
                old, new, n = str(row["old_status"]), str(row["new_status"]), int(row["n"])
                transitions[f"{old}->{new}"] = n
                if old != new:
                    affected += n
                    old_key = "matched" if old == "MATCHED" else "review" if old == "REVIEW" else "unmatched"
                    new_key = "matched" if new == "MATCHED" else "review" if new == "REVIEW" else "unmatched"
                    after[old_key] -= n
                    after[new_key] += n
            results.append({
                "success_threshold": success,
                "review_threshold": review,
                "before": before,
                "after": after,
                "matched_delta": after["matched"] - before["matched"],
                "review_delta": after["review"] - before["review"],
                "unmatched_delta": after["unmatched"] - before["unmatched"],
                "affected_rows": affected,
                "transitions": transitions,
            })
        return {"task_id": task_id, "scenarios": results}

    @staticmethod
    def _base_thresholds(task: Any) -> tuple[float, float]:
        try:
            document = json.loads(str(task["config_snapshot"] or "{}"))
            decision = document.get("decision", {}) if isinstance(document, dict) else {}
            return float(decision.get("success_threshold", 88)), float(decision.get("review_threshold", 75))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 88.0, 75.0

    def current_revision_no(self, task_id: str, connection: Any | None = None) -> int:
        if connection is not None:
            row = connection.execute("SELECT COALESCE(MAX(revision_no),0) AS n FROM decision_revisions WHERE task_id=?", (task_id,)).fetchone()
            return int(row["n"])
        with self.meta.connect() as conn:
            row = conn.execute("SELECT COALESCE(MAX(revision_no),0) AS n FROM decision_revisions WHERE task_id=?", (task_id,)).fetchone()
            return int(row["n"])

    def current_thresholds(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            task = self._task(connection, task_id)
            row = connection.execute(
                "SELECT revision_no,success_threshold,review_threshold,operator,created_at FROM decision_revisions WHERE task_id=? ORDER BY revision_no DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if row is not None:
                return dict(row)
            success, review = self._base_thresholds(task)
            return {"revision_no": 0, "success_threshold": success, "review_threshold": review, "operator": None, "created_at": None}

    @staticmethod
    def _ensure_result_snapshot(connection: Any, task_id: str, task: Any, decision_revision_no: int) -> None:
        file_id = task["result_file_id"]
        if not file_id:
            return
        exists = connection.execute("SELECT 1 FROM result_revisions WHERE task_id=? AND file_id=?", (task_id, file_id)).fetchone()
        if exists is not None:
            return
        next_no = int(connection.execute("SELECT COALESCE(MAX(revision_no),0)+1 FROM result_revisions WHERE task_id=?", (task_id,)).fetchone()[0])
        connection.execute(
            "INSERT INTO result_revisions(task_id,revision_no,decision_revision_no,file_id,created_at) VALUES(?,?,?,?,?)",
            (task_id, next_no, decision_revision_no, file_id, _now()),
        )

    def apply(
        self,
        task_id: str,
        success_threshold: float,
        review_threshold: float,
        *,
        operator: str = "system",
        rollback_of_revision: int | None = None,
    ) -> dict[str, object]:
        success, review = self._validate(success_threshold, review_threshold)
        now = _now()
        with self.meta.connect() as connection:
            task = self._task(connection, task_id)
            preview = self._preview_from_connection(connection, task_id, success, review)
            previous_revision = self.current_revision_no(task_id, connection)
            self._ensure_result_snapshot(connection, task_id, task, previous_revision)
            revision_no = previous_revision + 1
            connection.execute(
                """
                UPDATE match_items
                SET current_status = CASE
                      WHEN top1_score>? AND critical_conflict=0
                           AND NOT EXISTS(
                             SELECT 1 FROM match_candidates c2
                             WHERE c2.task_id=match_items.task_id AND c2.source_row_id=match_items.source_row_id AND c2.rank=2
                               AND c2.target_group_code<>match_items.top1_group_code
                               AND ABS(COALESCE(match_items.second_score,0)-COALESCE(match_items.top1_score,0)) < 0.000001
                           ) THEN 'MATCHED'
                      WHEN top1_score>? THEN 'REVIEW'
                      ELSE 'UNMATCHED'
                    END,
                    final_group_code = CASE
                      WHEN top1_score>? AND critical_conflict=0
                           AND NOT EXISTS(
                             SELECT 1 FROM match_candidates c2
                             WHERE c2.task_id=match_items.task_id AND c2.source_row_id=match_items.source_row_id AND c2.rank=2
                               AND c2.target_group_code<>match_items.top1_group_code
                               AND ABS(COALESCE(match_items.second_score,0)-COALESCE(match_items.top1_score,0)) < 0.000001
                           ) THEN top1_group_code
                      ELSE NULL
                    END,
                    updated_at=?
                WHERE task_id=?
                  AND current_status IN ('MATCHED','REVIEW','UNMATCHED')
                  AND NOT EXISTS(
                    SELECT 1 FROM reviews r WHERE r.task_id=match_items.task_id AND r.source_row_id=match_items.source_row_id
                  )
                """,
                (success, review, success, now, task_id),
            )
            unresolved = int(connection.execute(
                "SELECT COUNT(*) FROM match_items WHERE task_id=? AND current_status='REVIEW'",
                (task_id,),
            ).fetchone()[0])
            connection.execute("UPDATE tasks SET stage=? WHERE task_id=?", ("REVIEW" if unresolved else "RESULT", task_id))
            connection.execute(
                """INSERT INTO decision_revisions(
                   task_id,revision_no,success_threshold,review_threshold,operator,
                   before_counts,after_counts,transitions,rollback_of_revision,created_at
                   ) VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (
                    task_id,
                    revision_no,
                    success,
                    review,
                    operator or "system",
                    _json(preview["before"]),
                    _json(preview["after"]),
                    _json(preview["transitions"]),
                    rollback_of_revision,
                    now,
                ),
            )
            connection.execute(
                "INSERT INTO audit_events VALUES(?,?,?,?,?,?)",
                (
                    uuid.uuid4().hex,
                    "task",
                    task_id,
                    "REDECIDE_THRESHOLDS",
                    _json({
                        "revision_no": revision_no,
                        "success_threshold": success,
                        "review_threshold": review,
                        "operator": operator or "system",
                        "before": preview["before"],
                        "after": preview["after"],
                        "transitions": preview["transitions"],
                        "rollback_of_revision": rollback_of_revision,
                    }),
                    now,
                ),
            )
        return {**preview, "mode": "apply", "revision_no": revision_no, "operator": operator or "system"}

    def re_decide(
        self,
        task_id: str,
        success_threshold: float,
        review_threshold: float,
        mode: str = "apply",
        *,
        operator: str = "system",
    ) -> dict[str, object]:
        if mode == "preview":
            return self.preview(task_id, success_threshold, review_threshold)
        if mode == "apply":
            return self.apply(task_id, success_threshold, review_threshold, operator=operator)
        raise DomainError("INVALID_REDECIDE_MODE", "重判模式仅支持 preview 或 apply", status_code=422)

    def revisions(self, task_id: str) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            self._task(connection, task_id)
            rows = connection.execute(
                "SELECT * FROM decision_revisions WHERE task_id=? ORDER BY revision_no DESC",
                (task_id,),
            ).fetchall()
        result: list[dict[str, object]] = []
        for row in rows:
            item = dict(row)
            for key in ("before_counts", "after_counts", "transitions"):
                item[key] = json.loads(str(item[key]))
            result.append(item)
        return result

    def rollback(self, task_id: str, revision_no: int, *, operator: str = "system") -> dict[str, object]:
        with self.meta.connect() as connection:
            self._task(connection, task_id)
            row = connection.execute(
                "SELECT success_threshold,review_threshold FROM decision_revisions WHERE task_id=? AND revision_no=?",
                (task_id, revision_no),
            ).fetchone()
        if row is None:
            raise DomainError("DECISION_REVISION_NOT_FOUND", "阈值版本不存在", status_code=404)
        return self.apply(
            task_id,
            float(row["success_threshold"]),
            float(row["review_threshold"]),
            operator=operator,
            rollback_of_revision=revision_no,
        )

    @staticmethod
    def _histogram(connection: Any, task_id: str, column: str) -> list[dict[str, int]]:
        rows = connection.execute(
            f"""SELECT CASE
                    WHEN {column}<0 THEN 0
                    WHEN {column}>=100 THEN 90
                    ELSE CAST({column}/10 AS INTEGER)*10
                  END AS bucket_start,
                  COUNT(*) AS n
               FROM match_items WHERE task_id=?
               GROUP BY bucket_start ORDER BY bucket_start""",
            (task_id,),
        ).fetchall()
        counts = {int(row["bucket_start"]): int(row["n"]) for row in rows}
        return [
            {"min": start, "max": start + 10, "count": counts.get(start, 0)}
            for start in range(0, 100, 10)
        ]

    def statistics(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            task = self._task(connection, task_id)
            counts = self._full_counts(connection, task_id)
            top1_histogram = self._histogram(connection, task_id, "top1_score")
            score_gap_histogram = self._histogram(connection, task_id, "score_gap")
            latest = connection.execute(
                "SELECT revision_no,success_threshold,review_threshold,operator,created_at FROM decision_revisions WHERE task_id=? ORDER BY revision_no DESC LIMIT 1",
                (task_id,),
            ).fetchone()
            if latest is None:
                success, review = self._base_thresholds(task)
                current = {"revision_no": 0, "success_threshold": success, "review_threshold": review, "operator": None, "created_at": None}
            else:
                current = dict(latest)
        return {
            "task_id": task_id,
            "current": current,
            "counts": counts,
            "top1_score_histogram": top1_histogram,
            "top1_top2_gap_histogram": score_gap_histogram,
        }

    def record_result_revision(self, task_id: str, file_id: str) -> dict[str, object]:
        now = _now()
        with self.meta.connect() as connection:
            task = self._task(connection, task_id)
            decision_revision = self.current_revision_no(task_id, connection)
            self._ensure_result_snapshot(connection, task_id, task, decision_revision)
            existing = connection.execute(
                "SELECT * FROM result_revisions WHERE task_id=? AND file_id=?",
                (task_id, file_id),
            ).fetchone()
            if existing is not None:
                return dict(existing)
            revision_no = int(connection.execute(
                "SELECT COALESCE(MAX(revision_no),0)+1 FROM result_revisions WHERE task_id=?",
                (task_id,),
            ).fetchone()[0])
            connection.execute(
                "INSERT INTO result_revisions(task_id,revision_no,decision_revision_no,file_id,created_at) VALUES(?,?,?,?,?)",
                (task_id, revision_no, decision_revision, file_id, now),
            )
            return {
                "task_id": task_id,
                "revision_no": revision_no,
                "decision_revision_no": decision_revision,
                "file_id": file_id,
                "created_at": now,
            }

    def result_revisions(self, task_id: str) -> list[dict[str, object]]:
        with self.meta.connect() as connection:
            self._task(connection, task_id)
            rows = connection.execute(
                "SELECT * FROM result_revisions WHERE task_id=? ORDER BY revision_no DESC",
                (task_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def latest_result_for_current_decision(self, task_id: str) -> dict[str, object] | None:
        with self.meta.connect() as connection:
            task = self._task(connection, task_id)
            decision_revision = self.current_revision_no(task_id, connection)
            self._ensure_result_snapshot(connection, task_id, task, decision_revision)
            row = connection.execute(
                "SELECT * FROM result_revisions WHERE task_id=? AND decision_revision_no=? ORDER BY revision_no DESC LIMIT 1",
                (task_id, decision_revision),
            ).fetchone()
            return dict(row) if row is not None else None
