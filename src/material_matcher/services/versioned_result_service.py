from __future__ import annotations

from material_matcher.domain.errors import DomainError
from material_matcher.services.decision_calibration_service import DecisionCalibrationService
from material_matcher.services.result_export_service import ResultExportService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


class VersionedResultService:
    """Generate immutable formal result revisions for a completed task."""

    def __init__(self, metadata: MetadataRepository, files: FileRepository, settings: Settings) -> None:
        self.meta = metadata
        self.files = files
        self.exporter = ResultExportService(metadata, files, settings)
        self.calibration = DecisionCalibrationService(metadata)

    def finalize(self, task_id: str, *, allow_unresolved_review: bool = False) -> dict[str, object]:
        with self.meta.connect() as connection:
            task_row = connection.execute("SELECT * FROM tasks WHERE task_id=?", (task_id,)).fetchone()
            if task_row is None:
                raise DomainError("TASK_NOT_FOUND", "任务不存在", status_code=404)
            task = dict(task_row)
            if task["status"] != "COMPLETED" or task["stage"] not in {"REVIEW", "RESULT"}:
                raise DomainError("TASK_STATE_CONFLICT", "比对计算尚未完成，暂不能生成最终结果", status_code=409)
            unresolved = int(connection.execute(
                "SELECT COUNT(*) FROM match_items WHERE task_id=? AND current_status='REVIEW'",
                (task_id,),
            ).fetchone()[0])
        if unresolved and not allow_unresolved_review:
            raise DomainError(
                "TASK_STATE_CONFLICT",
                f"仍有 {unresolved} 条待人工处理记录，请确认是否保留为空后继续生成",
                status_code=409,
                details={"unresolved_review": unresolved},
            )

        current = self.calibration.latest_result_for_current_decision(task_id)
        if current is not None:
            return {
                "task_id": task_id,
                "result_file_id": current["file_id"],
                "result_revision": current["revision_no"],
                "decision_revision": current["decision_revision_no"],
                "unresolved_review": unresolved,
                "reused": True,
            }

        file_record = self.exporter.export_task(task_id, task, unresolved_review=unresolved)
        revision = self.calibration.record_result_revision(task_id, str(file_record["file_id"]))
        with self.meta.connect() as connection:
            connection.execute(
                "UPDATE tasks SET result_file_id=?, stage='RESULT', status='COMPLETED' WHERE task_id=?",
                (file_record["file_id"], task_id),
            )
        return {
            "task_id": task_id,
            "result_file_id": file_record["file_id"],
            "result_revision": revision["revision_no"],
            "decision_revision": revision["decision_revision_no"],
            "unresolved_review": unresolved,
            "reused": False,
        }
