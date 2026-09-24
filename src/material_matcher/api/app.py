from __future__ import annotations

from pathlib import Path
import re
from typing import Literal

from fastapi import FastAPI, File, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, model_validator

from material_matcher.api import _legacy_app
from material_matcher.api._legacy_app import COOKIE_NAME, create_app as _legacy_create_app
from material_matcher.domain.errors import DomainError
from material_matcher.services.business_evaluation_service import BusinessEvaluationService
from material_matcher.services.decision_calibration_service import DecisionCalibrationService
from material_matcher.services.review_workbench_service import ReviewWorkbenchService
from material_matcher.services.task_input_asset_service import TaskInputAssetService
from material_matcher.services.versioned_result_service import VersionedResultService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository


_ORIGINAL_REVIEWER_MUTATION_ALLOWED = _legacy_app._reviewer_mutation_allowed


class ReDecideRequest(BaseModel):
    success_threshold: float = Field(gt=0, le=100)
    mode: Literal["preview", "apply"] = "apply"


class CalibrationScenario(BaseModel):
    success_threshold: float = Field(gt=0, le=100)


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


class ReviewFilter(BaseModel):
    status: Literal["ALL", "MATCHED", "REVIEW", "CONFIRMED", "UNMATCHED"] = "REVIEW"
    q: str | None = Field(default=None, max_length=500)
    first_score_min: float | None = Field(default=None, ge=0, le=100)
    first_score_max: float | None = Field(default=None, ge=0, le=100)
    second_score_min: float | None = Field(default=None, ge=0, le=100)
    second_score_max: float | None = Field(default=None, ge=0, le=100)
    gap_min: float | None = Field(default=None, ge=-100, le=100)
    gap_max: float | None = Field(default=None, ge=-100, le=100)
    critical_conflict: bool | None = None


class SelectionItem(BaseModel):
    source_row_id: str = Field(min_length=1, max_length=200)
    expected_version: str | None = Field(default=None, max_length=120)


class ReviewSelection(BaseModel):
    mode: Literal["explicit", "filter"]
    items: list[SelectionItem] | None = Field(default=None, max_length=100_000)
    filter: ReviewFilter | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "ReviewSelection":
        if self.mode == "explicit" and not self.items:
            raise ValueError("explicit selection requires items")
        if self.mode == "filter" and self.filter is None:
            raise ValueError("filter selection requires filter")
        return self


class BulkReviewRequest(BaseModel):
    action: Literal["CONFIRM_TOP1", "MARK_UNMATCHED", "CANCEL_MATCH", "CANCEL_UNMATCHED", "RESTORE_ALGORITHM"]
    selection: ReviewSelection
    comment: str = Field(default="", max_length=500)
    operation_id: str | None = Field(default=None, min_length=1, max_length=120)


class ReviewDecision(BaseModel):
    source_row_id: str = Field(min_length=1, max_length=200)
    target_group_code: str | None = Field(default=None, max_length=500)
    target_rank: int | None = Field(default=None, ge=1, le=5)
    unmatched: bool = False
    expected_version: str = Field(min_length=1, max_length=120)
    operation: Literal["MATCH", "REMATCH"] = "MATCH"

    @model_validator(mode="after")
    def validate_choice(self) -> "ReviewDecision":
        choices = int(self.target_group_code is not None) + int(self.target_rank is not None) + int(self.unmatched)
        if choices != 1:
            raise ValueError("exactly one target_group_code, target_rank or unmatched is required")
        if self.unmatched and self.operation == "REMATCH":
            raise ValueError("unmatched cannot use REMATCH")
        return self


class ReviewDecisionsRequest(BaseModel):
    decisions: list[ReviewDecision] = Field(min_length=1, max_length=100_000)
    comment: str = Field(default="", max_length=500)
    operation_id: str | None = Field(default=None, min_length=1, max_length=120)


class LegacyBatchRequest(BaseModel):
    source_row_ids: list[str] = Field(min_length=1, max_length=100_000)


class LegacyDecisionRequest(BaseModel):
    target_id: str = Field(min_length=1, max_length=500)
    comment: str = Field(default="", max_length=500)
    expected_version: str | None = Field(default=None, max_length=120)


class LegacyCommentRequest(BaseModel):
    comment: str = Field(default="", max_length=500)
    expected_version: str | None = Field(default=None, max_length=120)


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


def _legacy_summary(result: dict[str, object]) -> dict[str, int]:
    counts = result.get("after") if isinstance(result.get("after"), dict) else {}
    return {
        "automatic_matched": int(counts.get("matched", 0)),
        "pending_review": int(counts.get("review", 0)),
        "unmatched": int(counts.get("unmatched", 0)),
        "confirmed": int(counts.get("confirmed", 0)),
    }


def _single_threshold_payload(value: object) -> object:
    """Hide removed dual-threshold compatibility fields from public APIs."""
    if isinstance(value, dict):
        return {
            key: _single_threshold_payload(item)
            for key, item in value.items()
            if key not in {"review_threshold", "single_threshold"}
        }
    if isinstance(value, list):
        return [_single_threshold_payload(item) for item in value]
    return value


def _reviewer_mutation_allowed(path: str) -> bool:
    return bool(
        _ORIGINAL_REVIEWER_MUTATION_ALLOWED(path)
        or re.fullmatch(r"/api/tasks/[^/]+/workbench/(bulk|decisions|selection-count)", path)
    )


def _selection_dict(selection: ReviewSelection) -> dict[str, object]:
    return selection.model_dump(exclude_none=True)


def _require_explicit_versions(selection: ReviewSelection) -> None:
    if selection.mode != "explicit":
        return
    missing = [item.source_row_id for item in (selection.items or []) if item.expected_version is None]
    if missing:
        raise DomainError(
            "EXPECTED_VERSION_REQUIRED",
            "显式批量操作必须携带 expected_version，请刷新列表后重试",
            status_code=422,
            details={"source_row_ids": missing[:20], "missing_count": len(missing)},
        )


def _legacy_batch_result(result: dict[str, object], requested: list[str]) -> dict[str, object]:
    details = result.get("details") if isinstance(result.get("details"), list) else []
    failed_ids = {
        str(detail.get("source_row_id"))
        for detail in details
        if isinstance(detail, dict) and detail.get("type") in {"conflict", "error"}
    }
    return {
        "success": [source_row_id for source_row_id in requested if source_row_id not in failed_ids],
        "failed": [detail for detail in details if isinstance(detail, dict) and detail.get("type") in {"conflict", "error"}],
        "counts": {
            "success": int(result.get("success") or 0),
            "skipped": int(result.get("skipped") or 0),
            "conflicts": int(result.get("conflicts") or 0),
            "errors": int(result.get("errors") or 0),
        },
        "operation_id": result.get("batch_operation_id"),
    }


def _legacy_single_result(reviews: ReviewWorkbenchService, task_id: str, source_row_id: str, result: dict[str, object]) -> dict[str, object]:
    details = result.get("details") if isinstance(result.get("details"), list) else []
    failure = next(
        (detail for detail in details if isinstance(detail, dict) and detail.get("type") in {"conflict", "error"}),
        None,
    )
    if failure is not None:
        kind = str(failure.get("type"))
        raise DomainError(
            str(failure.get("code") or "REVIEW_OPERATION_FAILED"),
            str(failure.get("message") or "人工处理失败"),
            status_code=409 if kind == "conflict" else 422,
            details={key: value for key, value in failure.items() if key not in {"code", "message"}},
        )
    item = reviews.get_item(task_id, source_row_id)
    return {
        "source_row_id": source_row_id,
        "status": item.get("current_status"),
        "final_group_code": item.get("final_group_code"),
        "version": item.get("version"),
        "operation_id": result.get("batch_operation_id"),
        "idempotent": int(result.get("success") or 0) == 0 and int(result.get("skipped") or 0) > 0,
    }


def _require_expected_version(value: str | None) -> str:
    if not value:
        raise DomainError(
            "EXPECTED_VERSION_REQUIRED",
            "该操作必须携带 expected_version，请刷新记录后重试",
            status_code=422,
        )
    return value


def create_app(settings: Settings | None = None) -> FastAPI:
    """Build the legacy application, then attach calibrated and scalable review APIs."""

    cfg = settings or Settings.load()
    # The legacy auth middleware resolves this module global at request time.
    # Extend its reviewer mutation allow-list without rewriting the legacy app.
    _legacy_app._reviewer_mutation_allowed = _reviewer_mutation_allowed
    app = _legacy_create_app(cfg)
    metadata = MetadataRepository(cfg.metadata_db_path)
    files = FileRepository(cfg.data_dir, metadata)
    calibration = DecisionCalibrationService(metadata)
    versioned_results = VersionedResultService(metadata, files, cfg)
    evaluations = BusinessEvaluationService(metadata, files)
    reviews = ReviewWorkbenchService(metadata)
    task_input_assets = TaskInputAssetService(metadata, files)

    def legacy_expected_version(task_id: str, source_row_id: str, operator: str) -> str:
        # Compatibility for pre-version STEP3 clients: only the account that made
        # the latest manual decision may omit expected_version. A different user
        # gets an explicit conflict, and the resolved token is still checked in
        # the following transactional update.
        with metadata.connect() as connection:
            item = connection.execute(
                "SELECT updated_at FROM match_items WHERE task_id=? AND source_row_id=?",
                (task_id, source_row_id),
            ).fetchone()
            if item is None:
                raise DomainError("MATCH_ITEM_NOT_FOUND", "匹配记录不存在", status_code=404)
            latest = connection.execute(
                """SELECT operator,operation_type FROM match_operation_logs
                   WHERE task_id=? AND source_row_id=?
                   ORDER BY operated_at DESC,rowid DESC LIMIT 1""",
                (task_id, source_row_id),
            ).fetchone()
            if latest is None:
                latest = connection.execute(
                    """SELECT operator,action AS operation_type FROM reviews
                       WHERE task_id=? AND source_row_id=?
                       ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                    (task_id, source_row_id),
                ).fetchone()
            if latest is None or str(latest["operation_type"]) in {"CANCEL_MATCH", "CANCEL_UNMATCHED", "RESTORE_ALGORITHM"}:
                raise DomainError("TASK_STATE_CONFLICT", "当前记录没有可修改的人工判断", status_code=409)
            latest_operator = str(latest["operator"] or "system")
            if latest_operator != (operator or "system"):
                raise DomainError(
                    "VERSION_CONFLICT",
                    "记录已被其他用户修改，请刷新后重试",
                    status_code=409,
                    details={"latest_operator": latest_operator},
                )
            return str(item["updated_at"] or "")

    _drop_route(app, "/api/task-drafts/{draft_id}/start", "POST")
    _drop_route(app, "/api/tasks/{task_id}/re-decide", "POST")
    _drop_route(app, "/api/tasks/{task_id}/finalize", "POST")
    _drop_route(app, "/api/tasks/{task_id}/result", "GET")
    _drop_route(app, "/api/tasks/{task_id}", "GET")
    _drop_route(app, "/api/tasks/{task_id}/evaluations", "POST")
    _drop_route(app, "/api/tasks/{task_id}/workbench/items", "GET")
    _drop_route(app, "/api/tasks/{task_id}/workbench/batch-confirm-top1", "POST")
    _drop_route(app, "/api/tasks/{task_id}/workbench/batch-reject", "POST")
    _drop_route(app, "/api/tasks/{task_id}/manual-review/import", "POST")
    for action_path in ("confirm", "match", "reject", "mark-unmatched", "rematch", "cancel", "cancel-match", "cancel-unmatched"):
        _drop_route(app, f"/api/tasks/{{task_id}}/items/{{source_row_id}}/{action_path}", "POST")

    def _run_input_freeze(task_id: str, draft_id: str) -> None:
        # Heavy work (full-file verification + hashing) happens off the request
        # path so the UI can show a queued task immediately (issue #186).
        try:
            frozen = task_input_assets.freeze_draft(draft_id)
        except Exception as exc:  # noqa: BLE001 - surfaced via task status
            app.state.tasks.fail_freeze(task_id, getattr(exc, "message", None) or str(exc))
            return
        try:
            app.state.tasks.attach_frozen_inputs(task_id, draft_id, frozen)
        except Exception as exc:  # noqa: BLE001
            app.state.tasks.fail_freeze(task_id, getattr(exc, "message", None) or str(exc))
            return
        app.state.worker.notify()

    import os as _os

    if _os.environ.get("MATERIAL_MATCHER_SYNC_FREEZE") == "1":
        class _InlineFreezer:
            def submit(self, fn, *args, **kwargs):  # noqa: ANN001
                return fn(*args, **kwargs)

        app.state.input_freezer = _InlineFreezer()
    else:
        from concurrent.futures import ThreadPoolExecutor

        app.state.input_freezer = ThreadPoolExecutor(max_workers=1, thread_name_prefix="input-freeze")
        app.state.tasks.abandon_freezes()
    from concurrent.futures import ThreadPoolExecutor as _TPE

    app.state.result_exporter = _TPE(max_workers=1, thread_name_prefix="result-export")

    @app.post("/api/task-drafts/{draft_id}/start", status_code=202)
    def start_task_with_frozen_inputs(draft_id: str, request: Request) -> dict[str, object]:
        # The task row is created as FREEZING right away; the worker only claims
        # PENDING rows, so it is safely invisible to scheduling until frozen.
        # A single-worker executor serialises freezes (SQLite write lock).
        task_input_assets.validate_for_freeze(draft_id)
        task = app.state.tasks.start(
            draft_id,
            actor=str(request.state.username),
            initial_status="FREEZING",
        )
        app.state.input_freezer.submit(_run_input_freeze, str(task["task_id"]), draft_id)
        return app.state.tasks.get_task(str(task["task_id"]))

    @app.get("/api/tasks/{task_id}")
    def task_detail(task_id: str) -> dict[str, object]:
        from material_matcher.services.versioned_result_service import export_state

        task = dict(app.state.tasks.get_task(task_id))
        exporting, error = export_state(task_id)
        task["exporting"] = exporting
        if error:
            task["export_error"] = error
        return task

    @app.get("/api/tasks/{task_id}/input-assets")
    def task_input_asset_summary(task_id: str) -> dict[str, object]:
        return task_input_assets.describe(task_id)

    @app.get("/api/tasks/{task_id}/input-files/{asset_role}")
    def task_input_file(task_id: str, asset_role: Literal["source", "target"]) -> FileResponse:
        download = task_input_assets.download(task_id, asset_role)
        return FileResponse(
            path=Path(download["path"]),
            filename=str(download["filename"]),
            media_type=str(download["media_type"]),
        )

    @app.get("/api/tasks/{task_id}/input-files/targets/{profile_id}")
    def composite_task_target_file(task_id: str, profile_id: str) -> FileResponse:
        download = task_input_assets.download_target(task_id, profile_id)
        return FileResponse(
            path=Path(download["path"]),
            filename=str(download["filename"]),
            media_type=str(download["media_type"]),
        )

    @app.get("/api/tasks/{task_id}/calibration")
    def calibration_statistics(task_id: str) -> dict[str, object]:
        return _single_threshold_payload(calibration.statistics(task_id))  # type: ignore[return-value]

    @app.post("/api/tasks/{task_id}/calibration/batch-preview")
    def calibration_batch_preview(task_id: str, payload: BatchCalibrationRequest) -> dict[str, object]:
        scenarios = [
            {"success_threshold": scenario.success_threshold, "review_threshold": 0.0}
            for scenario in payload.scenarios
        ]
        return _single_threshold_payload(calibration.batch_preview(task_id, scenarios))  # type: ignore[return-value]

    @app.post("/api/tasks/{task_id}/re-decide")
    def re_decide(task_id: str, payload: ReDecideRequest, request: Request) -> dict[str, object]:
        result = calibration.re_decide(
            task_id,
            payload.success_threshold,
            0.0,
            payload.mode,
            operator=str(getattr(request.state, "username", "system")),
            single_threshold=True,
        )
        result["summary"] = _legacy_summary(result)
        return _single_threshold_payload(result)  # type: ignore[return-value]

    @app.get("/api/tasks/{task_id}/decision-revisions")
    def decision_revisions(task_id: str) -> list[dict[str, object]]:
        return _single_threshold_payload(calibration.revisions(task_id))  # type: ignore[return-value]

    @app.post("/api/tasks/{task_id}/decision-revisions/{revision_no}/rollback")
    def rollback_decision(task_id: str, revision_no: int, request: Request) -> dict[str, object]:
        result = calibration.rollback(
            task_id,
            revision_no,
            operator=str(getattr(request.state, "username", "system")),
        )
        return _single_threshold_payload(result)  # type: ignore[return-value]

    @app.get("/api/tasks/{task_id}/workbench/items")
    def workbench_items(
        task_id: str,
        status: str = Query("REVIEW"),
        q: str | None = Query(default=None, max_length=500),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
        include_candidates: int = Query(0, ge=0, le=5),
        first_score_min: float | None = Query(default=None, ge=0, le=100),
        first_score_max: float | None = Query(default=None, ge=0, le=100),
        second_score_min: float | None = Query(default=None, ge=0, le=100),
        second_score_max: float | None = Query(default=None, ge=0, le=100),
        gap_min: float | None = Query(default=None, ge=-100, le=100),
        gap_max: float | None = Query(default=None, ge=-100, le=100),
        critical_conflict: bool | None = None,
    ) -> dict[str, object]:
        return reviews.list_items(
            task_id,
            status=status,
            q=q,
            page=page,
            page_size=page_size,
            include_candidates=include_candidates,
            first_score_min=first_score_min,
            first_score_max=first_score_max,
            second_score_min=second_score_min,
            second_score_max=second_score_max,
            gap_min=gap_min,
            gap_max=gap_max,
            critical_conflict=critical_conflict,
        )

    @app.post("/api/tasks/{task_id}/workbench/selection-count")
    def workbench_selection_count(task_id: str, payload: ReviewSelection) -> dict[str, object]:
        return reviews.selection_count(task_id, _selection_dict(payload))

    @app.post("/api/tasks/{task_id}/workbench/bulk")
    def workbench_bulk(task_id: str, payload: BulkReviewRequest, request: Request) -> dict[str, object]:
        _require_explicit_versions(payload.selection)
        return reviews.bulk_action(
            task_id,
            action=payload.action,
            selection=_selection_dict(payload.selection),
            operator=str(request.state.username),
            comment=payload.comment,
            operation_id=payload.operation_id,
        )

    @app.post("/api/tasks/{task_id}/workbench/decisions")
    def workbench_decisions(task_id: str, payload: ReviewDecisionsRequest, request: Request) -> dict[str, object]:
        return reviews.submit_decisions(
            task_id,
            [decision.model_dump(exclude_none=True) for decision in payload.decisions],
            operator=str(request.state.username),
            comment=payload.comment,
            operation_id=payload.operation_id,
        )

    # Per-row compatibility endpoints now share the same conflict rules. First-time
    # legacy MATCH/UNMATCHED writes may omit a version, but they never replace an
    # existing different manual result. Destructive rematch/cancel operations require
    # the version returned by the list API so reviewer A cannot overwrite reviewer B.
    def _legacy_match(task_id: str, source_row_id: str, payload: LegacyDecisionRequest, request: Request, *, rematch: bool = False) -> dict[str, object]:
        expected = (
            payload.expected_version
            or (legacy_expected_version(task_id, source_row_id, str(request.state.username)) if rematch else None)
        )
        decision: dict[str, object] = {
            "source_row_id": source_row_id,
            "target_group_code": payload.target_id,
            "operation": "REMATCH" if rematch else "MATCH",
        }
        if expected is not None:
            decision["expected_version"] = expected
        result = reviews.submit_decisions(
            task_id,
            [decision],
            operator=str(request.state.username),
            comment=payload.comment,
            require_expected_version=rematch,
        )
        return _legacy_single_result(reviews, task_id, source_row_id, result)

    def _legacy_unmatched(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        decision: dict[str, object] = {"source_row_id": source_row_id, "unmatched": True, "operation": "MATCH"}
        if payload.expected_version is not None:
            decision["expected_version"] = payload.expected_version
        result = reviews.submit_decisions(
            task_id,
            [decision],
            operator=str(request.state.username),
            comment=payload.comment,
            require_expected_version=False,
        )
        return _legacy_single_result(reviews, task_id, source_row_id, result)

    def _legacy_cancel(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request, action: str) -> dict[str, object]:
        expected = payload.expected_version or legacy_expected_version(
            task_id, source_row_id, str(request.state.username)
        )
        result = reviews.bulk_action(
            task_id,
            action=action,
            selection={"mode": "explicit", "items": [{"source_row_id": source_row_id, "expected_version": expected}]},
            operator=str(request.state.username),
            comment=payload.comment,
        )
        return _legacy_single_result(reviews, task_id, source_row_id, result)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/confirm")
    def confirm_item(task_id: str, source_row_id: str, payload: LegacyDecisionRequest, request: Request) -> dict[str, object]:
        return _legacy_match(task_id, source_row_id, payload, request)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/match")
    def match_item(task_id: str, source_row_id: str, payload: LegacyDecisionRequest, request: Request) -> dict[str, object]:
        return _legacy_match(task_id, source_row_id, payload, request)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/reject")
    def reject_item(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        return _legacy_unmatched(task_id, source_row_id, payload, request)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/mark-unmatched")
    def mark_unmatched_item(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        return _legacy_unmatched(task_id, source_row_id, payload, request)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/rematch")
    def rematch_item(task_id: str, source_row_id: str, payload: LegacyDecisionRequest, request: Request) -> dict[str, object]:
        return _legacy_match(task_id, source_row_id, payload, request, rematch=True)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/cancel")
    def cancel_item(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        return _legacy_cancel(task_id, source_row_id, payload, request, "RESTORE_ALGORITHM")

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/cancel-match")
    def cancel_match_item(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        return _legacy_cancel(task_id, source_row_id, payload, request, "CANCEL_MATCH")

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/cancel-unmatched")
    def cancel_unmatched_item(task_id: str, source_row_id: str, payload: LegacyCommentRequest, request: Request) -> dict[str, object]:
        return _legacy_cancel(task_id, source_row_id, payload, request, "CANCEL_UNMATCHED")

    # Compatibility adapters for the existing STEP3 UI. New clients should use
    # /workbench/bulk so selecting all filtered rows never sends thousands of IDs.
    @app.post("/api/tasks/{task_id}/workbench/batch-confirm-top1")
    def legacy_batch_confirm(task_id: str, payload: LegacyBatchRequest, request: Request) -> dict[str, object]:
        result = reviews.bulk_action(
            task_id,
            action="CONFIRM_TOP1",
            selection={"mode": "explicit", "ids": payload.source_row_ids},
            operator=str(request.state.username),
        )
        return _legacy_batch_result(result, payload.source_row_ids)

    @app.post("/api/tasks/{task_id}/workbench/batch-reject")
    def legacy_batch_reject(task_id: str, payload: LegacyBatchRequest, request: Request) -> dict[str, object]:
        result = reviews.bulk_action(
            task_id,
            action="MARK_UNMATCHED",
            selection={"mode": "explicit", "ids": payload.source_row_ids},
            operator=str(request.state.username),
        )
        return _legacy_batch_result(result, payload.source_row_ids)

    @app.post("/api/tasks/{task_id}/manual-review/import")
    async def import_manual_review(task_id: str, request: Request, file: UploadFile = File(...)) -> dict[str, object]:
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in {".xlsx", ".xlsm"}:
            raise DomainError("UNSUPPORTED_FILE", "人工匹配结果仅支持 .xlsx / .xlsm", status_code=400)
        return reviews.import_workbook(
            task_id,
            file.file,
            operator=str(request.state.username),
            filename=file.filename or "",
        )

    @app.post("/api/tasks/{task_id}/finalize", status_code=202)
    def finalize(task_id: str, payload: FinalizeRequest) -> dict[str, object]:
        from material_matcher.services.versioned_result_service import _EXPORTING

        ready = versioned_results.finalize_ready(task_id, allow_unresolved_review=payload.allow_unresolved_review)
        if ready is not None:
            return ready
        if task_id in _EXPORTING:
            return {"task_id": task_id, "status": "EXPORTING"}
        app.state.result_exporter.submit(_run_result_export, task_id)
        return {"task_id": task_id, "status": "EXPORTING"}

    def _run_result_export(task_id: str) -> None:
        try:
            versioned_results.finalize(task_id, allow_unresolved_review=True)
        except Exception:  # noqa: BLE001 - recorded by the service registry
            pass

    @app.get("/api/tasks/{task_id}/result")
    def result_file_export_aware(task_id: str) -> FileResponse:
        from material_matcher.services.versioned_result_service import export_state

        task = app.state.tasks.get_task(task_id)
        file_id = task.get("result_file_id")
        if not file_id:
            exporting, _error = export_state(task_id)
            if exporting:
                raise DomainError("RESULT_EXPORT_IN_PROGRESS", "正式结果正在后台生成，请稍候片刻再下载", status_code=409)
            file_id = versioned_results.finalize(task_id, allow_unresolved_review=True).get("result_file_id")
        record = files.get(str(file_id))
        return FileResponse(
            Path(str(record["stored_path"])),
            filename=str(record["original_name"]),
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

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

    app.state.review_workbench = reviews
    return app
