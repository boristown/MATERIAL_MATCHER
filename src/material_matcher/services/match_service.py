from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timedelta
import json
from pathlib import Path
import time
from typing import Any
import uuid

from material_matcher.domain.errors import DomainError
from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.ingestion.reader import detect_layout
from material_matcher.matching.engine import RowResult, match_rows, match_rows_indexed, summarize
from material_matcher.services.result_export_service import ResultExportService
from material_matcher.services.task_service import task_time_fields
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.vector.service import VectorIndexService


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class MatchService:
    def __init__(self, metadata: MetadataRepository, files: FileRepository, settings: Settings, indexes: VectorIndexService | None = None) -> None:
        self.meta = metadata
        self.files = files
        self.settings = settings
        self.indexes = indexes or VectorIndexService(metadata, files, settings)
        self.result_exporter = ResultExportService(metadata, files, settings)
        self._progress_window: dict[str, list[tuple[float, str, int, int]]] = {}

    def observe_progress(self, task_id: str, kind: str, done: int, total: int, *, now: float | None = None) -> None:
        """Feed a sliding-window throughput sample for progress ETA estimation."""
        sample = (time.monotonic() if now is None else now, kind, int(done), int(total))
        window = self._progress_window.setdefault(task_id, [])
        window.append(sample)
        if len(window) > 480:
            del window[: len(window) - 480]

    def progress_estimate(self, task_id: str, phase: str, *, now: float | None = None) -> dict[str, object] | None:
        window = self._progress_window.get(task_id)
        if not window:
            return None
        current = time.monotonic() if now is None else now
        kind = "index" if phase == "INDEX" else "query"
        samples = [item for item in window if item[1] == kind and current - item[0] <= 900.0]
        samples = samples[-120:]
        if len(samples) < 2:
            return None
        (_, _, done_first, _), (t_last, _, done_last, total_last) = samples[0], samples[-1]
        elapsed = t_last - samples[0][0]
        if elapsed <= 0 or done_last <= done_first or total_last <= 0:
            return None
        rate_per_minute = (done_last - done_first) / elapsed * 60.0
        remaining_rows = max(0, total_last - done_last)
        phase_remaining = remaining_rows / rate_per_minute * 60.0
        if phase in {"RERANK", "RETRIEVE"}:
            whole_remaining = phase_remaining * (100.0 / 63.0) + 240.0
        elif phase == "INDEX":
            whole_remaining = phase_remaining * (100.0 / 27.0)
        else:
            whole_remaining = phase_remaining
        return {
            "kind": kind,
            "phase": phase,
            "phase_done": done_last,
            "phase_total": total_last,
            "rows_per_minute": round(rate_per_minute, 1),
            "phase_remaining_seconds": round(phase_remaining),
            "eta_seconds": round(whole_remaining),
            "eta_at": (datetime.now().astimezone() + timedelta(seconds=round(whole_remaining))).isoformat(timespec="seconds") if phase in {"INDEX", "RETRIEVE", "RERANK"} else None,
            "window_seconds": 900,
        }

    def _set_runtime(self, task_id: str, execution_mode: str, phase: str, index_id: str | None = None) -> None:
        with self.meta.connect() as connection:
            connection.execute(
                "INSERT INTO task_runtime(task_id,execution_mode,current_phase,index_id,updated_at) VALUES(?,?,?,?,?) "
                "ON CONFLICT(task_id) DO UPDATE SET execution_mode=excluded.execution_mode,current_phase=excluded.current_phase,index_id=COALESCE(excluded.index_id,task_runtime.index_id),updated_at=excluded.updated_at",
                (task_id, execution_mode, phase, index_id, _now()),
            )

    def runtime_status(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM task_runtime WHERE task_id=?", (task_id,)).fetchone()
        return dict(row) if row is not None else {"task_id": task_id, "execution_mode": "unknown", "current_phase": "WAITING", "index_id": None}

    def _catalog(self, version_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT c.name, v.* FROM catalog_versions v JOIN catalogs c ON c.catalog_id=v.catalog_id WHERE v.version_id=?", (version_id,)).fetchone()
        if row is None:
            raise DomainError("CATALOG_NOT_FOUND", "集团码目录版本不存在", status_code=404)
        return dict(row)

    def _draft_context(self, draft_id: str) -> tuple[dict[str, object], MatchingConfig, dict[str, object], dict[str, object]]:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT * FROM task_drafts WHERE draft_id=?", (draft_id,)).fetchone()
        if row is None:
            raise DomainError("TASK_DRAFT_NOT_FOUND", "任务草稿不存在", status_code=404)
        draft = dict(row)
        config = MatchingConfig.model_validate(json.loads(str(draft["config_document"] or "{}")))
        if not draft.get("source_file_id") or not draft.get("catalog_version_id") or not config.rules:
            raise DomainError("TASK_DRAFT_INCOMPLETE", "请先完成数据选择和匹配规则配置", status_code=422)
        source = self.files.get(str(draft["source_file_id"]))
        catalog = self._catalog(str(draft["catalog_version_id"]))
        target = self.files.get(str(catalog["source_file_id"]))
        return draft, config, source, {**catalog, "file": target}

    def _use_vector(self, config: MatchingConfig, target_path: Path) -> bool:
        if config.retrieval.mode == "vector":
            return True
        if config.retrieval.mode == "scan":
            return False
        if any(rule.matcher == "semantic" or (rule.matcher == "hybrid" and bool(rule.matcher_options.get("include_semantic"))) for rule in config.rules):
            return True
        return detect_layout(target_path).row_count_estimate > self.settings.baseline_max_target_rows

    def _run_rows(self, *, source: dict[str, object], target: dict[str, object], catalog: dict[str, object], config: MatchingConfig, max_source_rows: int | None = None, on_progress=None, on_index_progress=None, on_index_ready=None, on_batch=None) -> list[RowResult]:
        source_path = Path(str(source["stored_path"]))
        target_path = Path(str(target["stored_path"]))
        if not self._use_vector(config, target_path):
            return match_rows(source_path, target_path, config=config, group_code_column=str(catalog["group_code_column"]), max_target_rows=self.settings.baseline_max_target_rows, max_source_rows=max_source_rows, on_progress=on_progress, on_batch=on_batch)
        index, provider, index_info = self.indexes.ensure_index(catalog_version_id=str(catalog["version_id"]), target_file=target, group_code_column=str(catalog["group_code_column"]), config=config, on_progress=on_index_progress)
        if on_index_ready:
            on_index_ready(str(index_info.get("index_id") or index.metadata.get("fingerprint") or ""))
        cache = EmbeddingCache(self.settings.embedding_cache_dir, provider)
        return match_rows_indexed(source_path, index=index, provider=provider, cache=cache, config=config, group_code_column=str(catalog["group_code_column"]), query_batch_size=self.settings.query_batch_size, max_source_rows=max_source_rows, on_progress=on_progress, scan_workers=self.settings.index_scan_workers, on_batch=on_batch)

    def dry_run(self, draft_id: str, sample_rows: int = 100) -> dict[str, object]:
        _, config, source, catalog = self._draft_context(draft_id)
        rows = self._run_rows(source=source, target=dict(catalog["file"]), catalog=catalog, config=config, max_source_rows=sample_rows)
        return {"summary": summarize(rows), "rows": [self._row_response(row) for row in rows]}

    @staticmethod
    def _row_response(row: RowResult) -> dict[str, object]:
        return {"source_row_id": row.source_row_id, "source_row_number": row.source_row_number, "source_id": row.source_id, "status": row.status, "final_group_code": row.final_group_code, "first_score": row.first_score, "second_score": row.second_score, "score_gap": row.score_gap, "critical_conflict": row.critical_conflict, "candidates": [asdict(candidate) for candidate in row.candidates]}

    def claim_next_task(self) -> str | None:
        with self.meta.connect() as connection:
            row = connection.execute("SELECT task_id FROM tasks WHERE status IN ('PENDING','RECOVERING') ORDER BY created_at LIMIT 1").fetchone()
            if row is None:
                return None
            task_id = str(row["task_id"])
            updated = connection.execute("UPDATE tasks SET status='PREPARING', started_at=COALESCE(started_at,created_at), error_code=NULL, error_message=NULL WHERE task_id=? AND status IN ('PENDING','RECOVERING')", (task_id,)).rowcount
        return task_id if updated else None

    def _persist_rows(self, task_id: str, batch: list[RowResult]) -> None:
        now = _now()
        with self.meta.connect() as connection:
            for item in batch:
                connection.execute("""INSERT OR REPLACE INTO match_items(task_id,source_row_id,source_row_number,source_id,source_payload,original_status,current_status,top1_group_code,top1_score,second_score,score_gap,critical_conflict,final_group_code,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (task_id, item.source_row_id, item.source_row_number, item.source_id, _json(item.source_payload), item.status, item.status, item.candidates[0].group_code if item.candidates else None, item.first_score, item.second_score, item.score_gap, 1 if item.critical_conflict else 0, item.final_group_code, now, now))
                for candidate in item.candidates:
                    connection.execute("""INSERT OR REPLACE INTO match_candidates(task_id,source_row_id,rank,target_row_number,target_group_code,target_payload,score,field_scores,critical_conflict) VALUES(?,?,?,?,?,?,?,?,?)""", (task_id, item.source_row_id, candidate.rank, candidate.target_row_number, candidate.group_code, _json(candidate.target_payload), candidate.score, _json(candidate.field_scores), 1 if candidate.critical_conflict else 0))

    def live_counts(self, task_id: str) -> dict[str, int]:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT current_status, COUNT(*) AS n FROM match_items WHERE task_id=? GROUP BY current_status", (task_id,)).fetchall()
        counts = {str(row["current_status"]): int(row["n"]) for row in rows}
        return {"matched": counts.get("MATCHED", 0), "review": counts.get("REVIEW", 0), "confirmed": counts.get("CONFIRMED", 0), "unmatched": counts.get("UNMATCHED", 0), "matched_group_codes": counts.get("MATCHED", 0) + counts.get("CONFIRMED", 0)}

    def execute_task(self, task_id: str) -> None:
        try:
            with self.meta.connect() as connection:
                row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if row is None:
                raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
            task = dict(row)
            compute_started_at = _now()
            with self.meta.connect() as connection:
                connection.execute(
                    """INSERT INTO task_compute_lifecycle(task_id,compute_started_at,compute_completed_at)
                       VALUES(?,?,NULL)
                       ON CONFLICT(task_id) DO UPDATE SET
                         compute_started_at=excluded.compute_started_at,
                         compute_completed_at=NULL""",
                    (task_id, compute_started_at),
                )
            config = MatchingConfig.model_validate(json.loads(str(task["config_snapshot"])))
            source = self.files.get(str(task["source_file_id"]))
            catalog = self._catalog(str(task["catalog_version_id"]))
            target = self.files.get(str(catalog["source_file_id"]))
            with self.meta.connect() as connection:
                connection.execute("DELETE FROM match_candidates WHERE task_id=?", (task_id,))
                connection.execute("DELETE FROM match_items WHERE task_id=?", (task_id,))
                connection.execute("UPDATE tasks SET status='RUNNING', progress=2, processed_rows=0, total_rows=0 WHERE task_id=?", (task_id,))
            vector_mode = self._use_vector(config, Path(str(target["stored_path"])))
            execution_mode = "vector" if vector_mode else "scan"
            self._set_runtime(task_id, execution_mode, "INDEX" if vector_mode else "RETRIEVE")

            def index_progress(done: int, total: int) -> None:
                pct = 3.0 + 27.0 * (done / max(total, 1)); self.observe_progress(task_id, "index", done, total)
                with self.meta.connect() as connection: connection.execute("UPDATE tasks SET progress=? WHERE task_id=?", (min(30.0, pct), task_id))

            def progress(done: int, total: int) -> None:
                self.observe_progress(task_id, "query", done, total)
                if done == 1: self._set_runtime(task_id, execution_mode, "RERANK")
                base = 32.0 if vector_mode else 5.0; span = 63.0 if vector_mode else 90.0; pct = base + span * (done / max(total, 1))
                with self.meta.connect() as connection: connection.execute("UPDATE tasks SET processed_rows=?, total_rows=?, progress=? WHERE task_id=?", (done, total, min(95.0, pct), task_id))

            def index_ready(index_id: str) -> None: self._set_runtime(task_id, execution_mode, "RETRIEVE", index_id or None)
            persisted = [0]

            def persist_batch(batch: list[RowResult]) -> None:
                self._persist_rows(task_id, batch); persisted[0] += len(batch)

            rows = self._run_rows(source=source, target=target, catalog=catalog, config=config, on_progress=progress, on_index_progress=index_progress, on_index_ready=index_ready if vector_mode else None, on_batch=persist_batch)
            self._set_runtime(task_id, execution_mode, "PERSIST")
            if persisted[0] < len(rows): self._persist_rows(task_id, rows[persisted[0]:])
            with self.meta.connect() as connection:
                review_count = connection.execute("SELECT COUNT(*) FROM match_items WHERE task_id=? AND current_status='REVIEW'", (task_id,)).fetchone()[0]
                stage = "REVIEW" if review_count else "RESULT"
                now = _now()
                connection.execute("UPDATE tasks SET status='COMPLETED', stage=?, progress=100, processed_rows=?, total_rows=?, finished_at=? WHERE task_id=?", (stage, len(rows), len(rows), now, task_id))
                connection.execute(
                    "UPDATE task_compute_lifecycle SET compute_completed_at=? WHERE task_id=?",
                    (now, task_id),
                )
            self._set_runtime(task_id, execution_mode, "DONE"); self._progress_window.pop(task_id, None)
        except Exception as exc:
            code = exc.code if isinstance(exc, DomainError) else "INTERNAL_ERROR"; message = exc.message if isinstance(exc, DomainError) else str(exc)
            with self.meta.connect() as connection: connection.execute("UPDATE tasks SET status='FAILED', error_code=?, error_message=?, finished_at=? WHERE task_id=?", (code, message, _now(), task_id))
            current_mode = self.runtime_status(task_id).get("execution_mode", "unknown"); self._set_runtime(task_id, str(current_mode), "FAILED")
            if isinstance(exc, DomainError): return
            raise

    def summary(self, task_id: str) -> dict[str, object]:
        with self.meta.connect() as connection:
            rows = connection.execute("SELECT current_status, COUNT(*) count FROM match_items WHERE task_id=? GROUP BY current_status", (task_id,)).fetchall()
            task_row = connection.execute(
                """SELECT t.*,l.compute_started_at,l.compute_completed_at
                   FROM tasks t
                   LEFT JOIN task_compute_lifecycle l ON l.task_id=t.task_id
                   WHERE t.task_id=?""",
                (task_id,),
            ).fetchone()
            preview_rows = connection.execute(
                """SELECT
                    m.source_row_id,m.source_row_number,m.source_id,m.current_status,
                    m.top1_group_code,m.top1_score,m.final_group_code,m.created_at,m.updated_at,
                    (SELECT c.target_row_number FROM match_candidates c
                     WHERE c.task_id=m.task_id AND c.source_row_id=m.source_row_id
                       AND m.final_group_code IS NOT NULL AND c.target_group_code=m.final_group_code
                     ORDER BY c.rank LIMIT 1) AS target_row_number,
                    (SELECT c.score FROM match_candidates c
                     WHERE c.task_id=m.task_id AND c.source_row_id=m.source_row_id
                       AND m.final_group_code IS NOT NULL AND c.target_group_code=m.final_group_code
                     ORDER BY c.rank LIMIT 1) AS selected_score,
                    (SELECT r.operator FROM reviews r
                     WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id
                     ORDER BY r.created_at DESC LIMIT 1) AS last_operator,
                    (SELECT r.created_at FROM reviews r
                     WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id
                     ORDER BY r.created_at DESC LIMIT 1) AS last_operation_time
                FROM match_items m
                WHERE m.task_id=?
                ORDER BY COALESCE(m.source_row_number, 2147483647), CAST(m.source_row_id AS INTEGER)
                LIMIT 50""",
                (task_id,),
            ).fetchall()
        counts = {str(row["current_status"]): int(row["count"]) for row in rows}
        task = dict(task_row) if task_row is not None else {}
        business_rows: list[dict[str, object]] = []
        for row in preview_rows:
            item = dict(row)
            status = str(item.get("current_status") or "")
            operator = item.get("last_operator")
            if status == "MATCHED":
                method = "自动匹配"
            elif status == "CONFIRMED":
                method = "人工匹配"
            elif status == "REVIEW":
                method = "待人工处理"
            elif operator:
                method = "人工标记未匹配"
            else:
                method = "自动判定未匹配"
            item["similarity"] = item.get("selected_score") if item.get("selected_score") is not None else item.get("top1_score")
            item["match_method"] = method
            if not item.get("last_operation_time"):
                item["last_operation_time"] = item.get("updated_at")
            item.pop("selected_score", None)
            business_rows.append(item)
        return {
            **task_time_fields(self.meta, task),
            "pending_review": counts.get("REVIEW", 0),
            "confirmed": counts.get("CONFIRMED", 0),
            "unmatched": counts.get("UNMATCHED", 0),
            "automatic_matched": counts.get("MATCHED", 0),
            "created_by": self.result_exporter._task_actor(task_id, task, "created") or None,
            "started_by": self.result_exporter._task_actor(task_id, task, "started") or None,
            "preview_rows": business_rows,
        }

    def workbench_items(self, task_id: str, *, first_score_min: float|None=None, first_score_max:float|None=None, second_score_min:float|None=None, second_score_max:float|None=None, gap_min:float|None=None, gap_max:float|None=None, critical_conflict:bool|None=None, q:str|None=None, page:int=1, page_size:int=50) -> dict[str, object]:
        conditions=["task_id=?","current_status='REVIEW'"]; params:list[object]=[task_id]
        if q and q.strip():
            like=f"%{q.strip()}%"; conditions.append("(source_id LIKE ? OR source_payload LIKE ? OR top1_group_code LIKE ?)"); params.extend([like,like,like])
        for column,low,high in (("top1_score",first_score_min,first_score_max),("second_score",second_score_min,second_score_max),("score_gap",gap_min,gap_max)):
            if low is not None: conditions.append(f"{column}>=?"); params.append(low)
            if high is not None: conditions.append(f"{column}<=?"); params.append(high)
        if critical_conflict is not None: conditions.append("critical_conflict=?"); params.append(1 if critical_conflict else 0)
        where=" AND ".join(conditions)
        with self.meta.connect() as connection:
            total=int(connection.execute(f"SELECT COUNT(*) FROM match_items WHERE {where}",params).fetchone()[0]); rows=connection.execute(f"SELECT * FROM match_items WHERE {where} ORDER BY top1_score DESC, source_row_id LIMIT ? OFFSET ?",(*params,page_size,(page-1)*page_size)).fetchall()
        return {"total":total,"page":page,"page_size":page_size,"items":[self._decode_item(row) for row in rows]}

    @staticmethod
    def _decode_item(row: Any) -> dict[str, object]:
        result=dict(row); result["source_payload"]=json.loads(str(result["source_payload"])); result["critical_conflict"]=bool(result["critical_conflict"]); return result

    def candidates(self, task_id: str, source_row_id: str) -> list[dict[str, object]]:
        with self.meta.connect() as connection: rows=connection.execute("SELECT * FROM match_candidates WHERE task_id=? AND source_row_id=? ORDER BY rank",(task_id,source_row_id)).fetchall()
        result=[]
        for row in rows:
            item=dict(row); item["target_payload"]=json.loads(str(item["target_payload"])); item["field_scores"]=json.loads(str(item["field_scores"])); item["critical_conflict"]=bool(item["critical_conflict"]); result.append(item)
        return result

    def confirm(self, task_id: str, source_row_id: str, target_group_code: str, comment: str="", operator: str="system") -> dict[str, object]:
        candidates=self.candidates(task_id,source_row_id)
        if target_group_code not in {str(item["target_group_code"]) for item in candidates}: raise DomainError("CANDIDATE_NOT_FOUND","所选候选不存在",status_code=404)
        return self._review_action(task_id,source_row_id,"CONFIRM_CANDIDATE",target_group_code,comment,operator)

    def reject(self, task_id: str, source_row_id: str, comment: str="", operator: str="system") -> dict[str, object]: return self._review_action(task_id,source_row_id,"REJECT_ALL",None,comment,operator)

    def _review_action(self,task_id:str,source_row_id:str,action:str,group_code:str|None,comment:str,operator:str="system")->dict[str,object]:
        with self.meta.connect() as connection:
            row=connection.execute("SELECT * FROM match_items WHERE task_id=? AND source_row_id=?",(task_id,source_row_id)).fetchone()
            if row is None: raise DomainError("MATCH_ITEM_NOT_FOUND","待处理记录不存在",status_code=404)
            if row["current_status"] != "REVIEW": raise DomainError("TASK_STATE_CONFLICT","该记录已经处理",status_code=409)
            new_status="CONFIRMED" if action=="CONFIRM_CANDIDATE" else "UNMATCHED"; now=_now()
            connection.execute("UPDATE match_items SET current_status=?, final_group_code=?, updated_at=? WHERE task_id=? AND source_row_id=?",(new_status,group_code,now,task_id,source_row_id)); connection.execute("INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?,?)",(uuid.uuid4().hex,task_id,source_row_id,str(row["original_status"]),group_code,action,operator or "system",comment,now)); connection.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,"match_item",f"{task_id}:{source_row_id}",action,_json({"selected_group_code":group_code,"comment":comment,"operator":operator}),now))
        return {"source_row_id":source_row_id,"status":new_status,"final_group_code":group_code}

    def batch_confirm_top1(self,task_id:str,source_row_ids:list[str],operator:str="system")->dict[str,object]: return self._batch(task_id,source_row_ids,confirm=True,operator=operator)
    def batch_reject(self,task_id:str,source_row_ids:list[str],operator:str="system")->dict[str,object]: return self._batch(task_id,source_row_ids,confirm=False,operator=operator)
    def _batch(self,task_id:str,ids:list[str],*,confirm:bool,operator:str="system")->dict[str,object]:
        success=[]; failed=[]
        for source_row_id in ids:
            try:
                if confirm:
                    candidates=self.candidates(task_id,source_row_id)
                    if not candidates: raise DomainError("NO_CANDIDATE","没有可确认候选",status_code=409)
                    self.confirm(task_id,source_row_id,str(candidates[0]["target_group_code"]),operator=operator); success.append(source_row_id)
                else: self.reject(task_id,source_row_id,operator=operator); success.append(source_row_id)
            except DomainError as exc: failed.append({"source_row_id":source_row_id,"code":exc.code,"message":exc.message})
        return {"success":success,"failed":failed}

    def re_decide(self, task_id: str, success_threshold: int, review_threshold: int, mode: str = "apply") -> dict[str, object]:
        """Re-evaluate persisted scores without rerunning embedding/recall."""
        if mode not in {"preview", "apply"}: raise DomainError("INVALID_REDECIDE_MODE", "重判模式仅支持 preview 或 apply", status_code=422)
        if not 0 <= review_threshold < success_threshold <= 100: raise DomainError("INVALID_THRESHOLDS", "阈值不合法:需满足 0 ≤ 人工下限 < 自动阈值 ≤ 100", status_code=422)
        with self.meta.connect() as connection:
            task=connection.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
            if task is None: raise DomainError("TASK_NOT_FOUND","任务不存在",status_code=404)
            if task["status"] != "COMPLETED": raise DomainError("TASK_STATE_CONFLICT","任务尚未完成比对,不能调整阈值",status_code=409)
            if task["result_file_id"]: raise DomainError("TASK_STATE_CONFLICT","最终结果已生成;调整阈值请先联系管理员重置结果或新建任务",status_code=409)
            rows=connection.execute("""SELECT m.source_row_id,m.current_status,m.final_group_code,m.top1_score,m.second_score,m.top1_group_code,m.critical_conflict,c2.target_group_code AS second_group_code FROM match_items m LEFT JOIN match_candidates c2 ON c2.task_id=m.task_id AND c2.source_row_id=m.source_row_id AND c2.rank=2 WHERE m.task_id=? AND m.current_status IN ('MATCHED','REVIEW','UNMATCHED') AND NOT EXISTS(SELECT 1 FROM reviews r WHERE r.task_id=m.task_id AND r.source_row_id=m.source_row_id)""",(task_id,)).fetchall()
            before={"matched":0,"review":0,"unmatched":0}; after={"matched":0,"review":0,"unmatched":0}; changes=[]; critical_protected=0; ambiguity_protected=0; protected_rows:set[str]=set()
            for row in rows:
                old=str(row["current_status"]); before["matched" if old=="MATCHED" else ("review" if old=="REVIEW" else "unmatched")]+=1; score=float(row["top1_score"] or 0.0)
                if score > float(success_threshold): new,final="MATCHED",row["top1_group_code"]
                elif score > float(review_threshold): new,final="REVIEW",None
                else: new,final="UNMATCHED",None
                if new=="MATCHED":
                    critical=bool(row["critical_conflict"]); second_group=row["second_group_code"]; ambiguous=second_group is not None and row["top1_group_code"] is not None and float(row["second_score"] or 0.0)==score and str(second_group)!=str(row["top1_group_code"])
                    if critical: critical_protected+=1; protected_rows.add(str(row["source_row_id"]))
                    if ambiguous: ambiguity_protected+=1; protected_rows.add(str(row["source_row_id"]))
                    if critical or ambiguous: new,final="REVIEW",None
                after["matched" if new=="MATCHED" else ("review" if new=="REVIEW" else "unmatched")]+=1
                if new != old or (new=="MATCHED" and final != row["final_group_code"]): changes.append((new,final,str(row["source_row_id"])))
            if mode=="apply":
                now=_now()
                for new,final,source_row_id in changes: connection.execute("UPDATE match_items SET current_status=?, final_group_code=?, updated_at=? WHERE task_id=? AND source_row_id=?",(new,final,now,task_id,source_row_id))
                unresolved=int(connection.execute("SELECT COUNT(*) FROM match_items WHERE task_id=? AND current_status='REVIEW'",(task_id,)).fetchone()[0]); connection.execute("UPDATE tasks SET stage=? WHERE task_id=?",("REVIEW" if unresolved else "RESULT",task_id)); connection.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?)",(uuid.uuid4().hex,"task",task_id,"REDECIDE_THRESHOLDS",_json({"success_threshold":success_threshold,"review_threshold":review_threshold,"affected_rows":len(changes)}),now))
        return {"task_id":task_id,"mode":mode,"success_threshold":success_threshold,"review_threshold":review_threshold,"before":before,"after":after,"matched_delta":after["matched"]-before["matched"],"review_delta":after["review"]-before["review"],"review_reduction":before["review"]-after["review"],"unmatched_delta":after["unmatched"]-before["unmatched"],"affected_rows":len(changes),"critical_conflict_protected":critical_protected,"ambiguity_protected":ambiguity_protected,"protected_rows":len(protected_rows),"summary":self.summary(task_id)}

    def _effective_decision(self, task_id: str, task: Any) -> dict[str, object]:
        snapshot=json.loads(str(task["config_snapshot"])) if task["config_snapshot"] else {}; decision=snapshot.get("decision",{}) if isinstance(snapshot,dict) else {}
        with self.meta.connect() as connection: row=connection.execute("SELECT payload FROM audit_events WHERE entity_type='task' AND entity_id=? AND action='REDECIDE_THRESHOLDS' ORDER BY created_at DESC LIMIT 1",(task_id,)).fetchone()
        if row is not None:
            try:
                applied=json.loads(str(row["payload"])); decision={**decision,**{key:applied[key] for key in ("success_threshold","review_threshold") if key in applied}}
            except (json.JSONDecodeError,TypeError): pass
        return decision

    def finalize(self,task_id:str,allow_unresolved_review:bool=False)->dict[str,object]:
        with self.meta.connect() as connection:
            task_row=connection.execute("SELECT * FROM tasks WHERE task_id=?",(task_id,)).fetchone()
            if task_row is None: raise DomainError("TASK_NOT_FOUND","任务不存在",status_code=404)
            task=dict(task_row)
            if task["status"] != "COMPLETED" or task["stage"] not in {"REVIEW","RESULT"}: raise DomainError("TASK_STATE_CONFLICT","比对计算尚未完成，暂不能生成最终结果",status_code=409)
            if task["result_file_id"]: return {"task_id":task_id,"result_file_id":task["result_file_id"],"unresolved_review":0,"summary":self.summary(task_id)}
            unresolved=int(connection.execute("SELECT COUNT(*) FROM match_items WHERE task_id=? AND current_status='REVIEW'",(task_id,)).fetchone()[0])
        if unresolved and not allow_unresolved_review: raise DomainError("TASK_STATE_CONFLICT",f"仍有 {unresolved} 条待人工处理记录，请确认是否保留为空后继续生成",status_code=409,details={"unresolved_review":unresolved})
        file_record=self.result_exporter.export_task(task_id,task,unresolved_review=unresolved)
        with self.meta.connect() as connection: connection.execute("UPDATE tasks SET result_file_id=?, stage='RESULT', status='COMPLETED' WHERE task_id=?",(file_record["file_id"],task_id))
        return {"task_id":task_id,"result_file_id":file_record["file_id"],"unresolved_review":unresolved,"summary":self.summary(task_id)}
