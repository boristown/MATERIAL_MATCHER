from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from material_matcher.api._legacy_app import create_app as _legacy_create_app
from material_matcher.domain.errors import DomainError
from material_matcher.services.business_evaluation_service import BusinessEvaluationService
from material_matcher.services.decision_calibration_service import DecisionCalibrationService
from material_matcher.services.versioned_result_service import VersionedResultService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


class ReDecideRequest(BaseModel):
    success_threshold: float = Field(ge=0, le=100)
    review_threshold: float = Field(ge=0, le=100)
    mode: Literal["preview", "apply"] = "apply"


class CalibrationScenario(BaseModel):
    success_threshold: float = Field(ge=0, le=100)
    review_threshold: float = Field(ge=0, le=100)


class BatchCalibrationRequest(BaseModel):
    scenarios: list[CalibrationScenario] = Field(min_length=1, max_length=100)


class FinalizeRequest(BaseModel):
    allow_unresolved_review: bool = False


class BusinessEvaluationRequest(BaseModel):
    truth_file_id: str = Field(min_length=1)
    key_column: str = Field(min_length=1, max_length=200)
    expected_group_code_column: str = Field(min_length=1, max_length=200)
    expected_result_column: str | None = Field(default=None, max_length=200)
    key_mode: Literal["source_id", "source_row_id"] = "source_id"


def _drop_route(app: FastAPI, path: str, method: str) -> None:
    method = method.upper()
    app.router.routes[:] = [
        route
        for route in app.router.routes
        if not (
            getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        )
    ]


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the legacy application, then attach calibrated decision APIs.

    Keeping the pre-existing route module intact makes this change easy to
    review while allowing the calibration subsystem to remain independent from
    MatchService and the core matcher.
    """

    cfg = settings or Settings.load()
    app = _legacy_create_app(cfg)
    metadata = MetadataRepository(cfg.metadata_db_path)
    files = FileRepository(cfg.data_dir, metadata)
    calibration = DecisionCalibrationService(metadata)
    versioned_results = VersionedResultService(metadata, files, cfg)
    evaluations = BusinessEvaluationService(metadata, files)

    _drop_route(app, "/api/tasks/{task_id}/re-decide", "POST")
    _drop_route(app, "/api/tasks/{task_id}/finalize", "POST")
    _drop_route(app, "/api/tasks/{task_id}/evaluations", "POST")

    @app.get("/api/tasks/{task_id}/calibration")
    def calibration_statistics(task_id: str) -> dict[str, object]:
        return calibration.statistics(task_id)

    @app.post("/api/tasks/{task_id}/calibration/batch-preview")
    def calibration_batch_preview(task_id: str, payload: BatchCalibrationRequest) -> dict[str, object]:
        return calibration.batch_preview(task_id, [scenario.model_dump() for scenario in payload.scenarios])

    @app.post("/api/tasks/{task_id}/re-decide")
    def re_decide(task_id: str, payload: ReDecideRequest, request: Request) -> dict[str, object]:
        return calibration.re_decide(
            task_id,
            payload.success_threshold,
            payload.review_threshold,
            payload.mode,
            operator=str(getattr(request.state, "username", "system")),
        )

    @app.get("/api/tasks/{task_id}/decision-revisions")
    def decision_revisions(task_id: str) -> list[dict[str, object]]:
        return calibration.revisions(task_id)

    @app.post("/api/tasks/{task_id}/decision-revisions/{revision_no}/rollback")
    def rollback_decision(task_id: str, revision_no: int, request: Request) -> dict[str, object]:
        return calibration.rollback(
            task_id,
            revision_no,
            operator=str(getattr(request.state, "username", "system")),
        )

    @app.post("/api/tasks/{task_id}/finalize")
    def finalize(task_id: str, payload: FinalizeRequest) -> dict[str, object]:
        return versioned_results.finalize(task_id, allow_unresolved_review=payload.allow_unresolved_review)

    @app.get("/api/tasks/{task_id}/result-revisions")
    def result_revisions(task_id: str) -> list[dict[str, object]]:
        return calibration.result_revisions(task_id)

    @app.get("/api/tasks/{task_id}/result-revisions/{revision_no}")
    def result_revision_file(task_id: str, revision_no: int) -> FileResponse:
        revision = next((item for item in calibration.result_revisions(task_id) if int(item["revision_no"]) == revision_no), None)
        if revision is None:
            raise DomainError("RESULT_REVISION_NOT_FOUND", "正式结果版本不存在", status_code=404)
        record = files.get(str(revision["file_id"]))
        return FileResponse(
            Path(str(record["stored_path"])),
            filename=str(record["original_name"]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

    @app.post("/api/tasks/{task_id}/evaluations")
    def create_evaluation(task_id: str, payload: BusinessEvaluationRequest) -> dict[str, object]:
        return evaluations.evaluate(
            task_id,
            truth_file_id=payload.truth_file_id,
            key_column=payload.key_column,
            expected_group_code_column=payload.expected_group_code_column,
            expected_result_column=payload.expected_result_column,
            key_mode=payload.key_mode,
        )

    return app
