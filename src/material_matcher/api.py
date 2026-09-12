from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import __version__
from .excel_inspector import inspect_excel
from .matching import MatchConfig, run_matching, write_result_xlsx
from .plugins import registry
from .profile import ProfileDocument
from .security import SessionStore, verify_admin_password
from .settings import Settings
from .storage import RuntimeStorage


MAX_UPLOAD_BYTES = 120 * 1024 * 1024


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: float


class MappingPayload(BaseModel):
    source_header: str
    target_header: str
    weight: float = Field(default=1.0, ge=0)
    method: str = "hybrid"
    name: str = ""
    critical: bool = False


class MatchConfigPayload(BaseModel):
    source_sheet: str | None = None
    source_header_row: int = Field(default=1, ge=1)
    target_sheet: str | None = None
    target_header_row: int = Field(default=1, ge=1)
    source_id_column: str
    group_code_column: str
    mappings: list[MappingPayload]
    threshold: float = Field(default=0.85, ge=0, le=1)
    review_threshold: float | None = Field(default=None, ge=0, le=1)
    top_n: int = Field(default=5, ge=1, le=50)
    candidate_limit: int = Field(default=400, ge=20, le=5000)


class DryRunRequest(BaseModel):
    source_file_id: str
    target_file_id: str
    config: MatchConfigPayload
    sample_rows: int = Field(default=30, ge=1, le=100)
    target_sample_rows: int = Field(default=10000, ge=100, le=50000)


class PublishProfileRequest(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    config: MatchConfigPayload
    description: str = ""


class CreateTaskRequest(BaseModel):
    profile_name: str
    source_file_id: str
    target_file_id: str


class CleanupRequest(BaseModel):
    older_than_hours: int | None = Field(default=None, ge=1, le=24 * 365)


def _profile_document(name: str, description: str, config: MatchConfigPayload) -> dict[str, Any]:
    cfg = config.model_dump()
    logical_fields: dict[str, Any] = {
        "source_id": {"source": {"aliases": [config.source_id_column], "required": True}},
        "group_code": {"target": {"aliases": [config.group_code_column], "required": True}},
    }
    match_rules: list[dict[str, Any]] = []
    for index, mapping in enumerate(config.mappings, start=1):
        field_name = f"field_{index}"
        logical_fields[field_name] = {
            "source": {"aliases": [part.strip() for part in mapping.source_header.split(" + ")]},
            "target": {"aliases": [part.strip() for part in mapping.target_header.split(" + ")]},
        }
        match_rules.append(
            {
                "id": mapping.name or field_name,
                "source_fields": [mapping.source_header],
                "target_fields": [mapping.target_header],
                "method": mapping.method,
                "weight": mapping.weight,
                "critical": mapping.critical,
            }
        )
    document = {
        "profile": {"name": name, "version": 1, "status": "published", "description": description},
        "source": {
            "adapter": "excel",
            "options": {"sheet": config.source_sheet, "header_row": config.source_header_row},
            "id_column": config.source_id_column,
        },
        "target": {
            "adapter": "excel",
            "options": {"sheet": config.target_sheet, "header_row": config.target_header_row},
            "result_code_column": config.group_code_column,
        },
        "logical_fields": logical_fields,
        "match_rules": match_rules,
        "scoring": {"missing_field_strategy": "dynamic_weight"},
        "decision": {
            "mode": "bands" if config.review_threshold is not None else "single_threshold",
            "success_threshold": config.threshold,
            "review_threshold": config.review_threshold,
            "matched_if": "gt",
        },
        "retrieval": {"backend": "auto", "candidate_limit": config.candidate_limit},
        "output": {"format": "xlsx", "top_n": config.top_n},
        # Transitional executable representation. The engine consumes the same
        # data-driven rules while the full profile compiler is implemented.
        "runtime": {"match_config": cfg},
    }
    ProfileDocument.model_validate(document)
    MatchConfig.from_dict(cfg)
    return document


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or Settings.load()
    sessions = SessionStore(runtime.session_ttl_seconds)
    storage = RuntimeStorage(runtime.data_dir, runtime.config_dir)
    app = FastAPI(title="MATERIAL_MATCHER", version=__version__, docs_url="/api/docs", redoc_url=None)

    def require_admin(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        token = authorization.removeprefix("Bearer ").strip()
        if not sessions.validate(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
        return token

    def upload_or_404(file_id: str):
        try:
            return storage.get_upload(file_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="上传文件不存在或已清理") from exc

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/health/ready")
    def ready() -> dict[str, object]:
        checks = {
            "admin_password_configured": bool(runtime.admin_password),
            "config_dir": str(runtime.config_dir),
            "data_dir": str(runtime.data_dir),
            "web_root_exists": runtime.web_root.exists(),
        }
        is_ready = bool(runtime.admin_password)
        return {"status": "ready" if is_ready else "not_ready", "checks": checks}

    @app.post("/api/auth/login", response_model=LoginResponse)
    def login(payload: LoginRequest) -> LoginResponse:
        if payload.username != "admin" or not verify_admin_password(runtime.admin_password, payload.password):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="用户名或密码错误")
        session = sessions.create()
        return LoginResponse(token=session.token, expires_at=session.expires_at)

    @app.post("/api/auth/logout")
    def logout(token: str = Depends(require_admin)) -> dict[str, bool]:
        sessions.revoke(token)
        return {"ok": True}

    @app.get("/api/system/info")
    def system_info(_: str = Depends(require_admin)) -> dict[str, object]:
        return {
            "version": __version__,
            "host": runtime.host,
            "port": runtime.port,
            "config_dir": str(runtime.config_dir),
            "data_dir": str(runtime.data_dir),
            "log_dir": str(runtime.log_dir),
            "plugins": registry.list_plugins(),
        }

    @app.post("/api/excel/inspect")
    async def inspect_excel_file(file: UploadFile = File(...), _: str = Depends(require_admin)) -> dict[str, object]:
        filename = file.filename or ""
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(status_code=400, detail="当前仅支持 .xlsx / .xlsm 文件")
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="文件超过 120MB，请使用配置样表或分批导入")
        try:
            return inspect_excel(payload).to_dict()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"无法解析 Excel：{exc}") from exc

    @app.post("/api/files/upload")
    async def upload_excel(role: str, file: UploadFile = File(...), _: str = Depends(require_admin)) -> dict[str, Any]:
        filename = file.filename or "upload.xlsx"
        if role not in {"source", "target", "supplement"}:
            raise HTTPException(status_code=400, detail="role 必须为 source / target / supplement")
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(status_code=400, detail="当前向导仅支持 .xlsx / .xlsm")
        payload = await file.read(MAX_UPLOAD_BYTES + 1)
        if len(payload) > MAX_UPLOAD_BYTES:
            raise HTTPException(status_code=413, detail="文件超过 120MB")
        try:
            inspection = inspect_excel(payload).to_dict()
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"无法解析 Excel：{exc}") from exc
        record = storage.save_upload(filename, payload, role)
        return {"file": record.__dict__, "inspection": inspection}

    @app.get("/api/files")
    def list_files(_: str = Depends(require_admin)) -> list[dict[str, Any]]:
        return storage.list_uploads()

    @app.delete("/api/files/{file_id}")
    def delete_file(file_id: str, _: str = Depends(require_admin)) -> dict[str, bool]:
        return {"deleted": storage.delete_upload(file_id)}

    @app.post("/api/files/cleanup")
    def cleanup_files(payload: CleanupRequest, _: str = Depends(require_admin)) -> dict[str, int]:
        seconds = payload.older_than_hours * 3600 if payload.older_than_hours is not None else None
        return storage.cleanup_uploads(seconds)

    @app.post("/api/wizard/dry-run")
    def dry_run(payload: DryRunRequest, _: str = Depends(require_admin)) -> dict[str, Any]:
        source = upload_or_404(payload.source_file_id)
        target = upload_or_404(payload.target_file_id)
        try:
            result = run_matching(
                Path(source.path),
                Path(target.path),
                payload.config.model_dump(),
                max_source_rows=payload.sample_rows,
                max_target_rows=payload.target_sample_rows,
            )
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"试跑失败：{exc}") from exc
        previews = []
        for item in result["rows"][:20]:
            previews.append(
                {
                    "source_id": item["source_id"],
                    "status": item["status"],
                    "matched_group_code": item["matched_group_code"],
                    "score": item["score"],
                    "candidates": [
                        {"rank": c["rank"], "group_code": c["group_code"], "score": c["score"]}
                        for c in item["candidates"]
                    ],
                }
            )
        return {"summary": result["summary"], "rows": previews}

    @app.post("/api/profiles/publish")
    def publish_profile(payload: PublishProfileRequest, _: str = Depends(require_admin)) -> dict[str, Any]:
        try:
            document = _profile_document(payload.name, payload.description, payload.config)
            return storage.publish_profile(payload.name, document)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"配置无法发布：{exc}") from exc

    @app.get("/api/profiles")
    def list_profiles(_: str = Depends(require_admin)) -> list[dict[str, Any]]:
        return storage.list_profiles()

    @app.get("/api/profiles/{name}/versions")
    def profile_versions(name: str, _: str = Depends(require_admin)) -> list[dict[str, Any]]:
        return storage.profile_versions(name)

    @app.post("/api/profiles/{name}/rollback/{version}")
    def rollback_profile(name: str, version: str, _: str = Depends(require_admin)) -> dict[str, Any]:
        try:
            document = storage.load_profile_document(name, version)
            return storage.publish_profile(name, document)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="配置版本不存在") from exc

    def execute_task(task_id: str) -> None:
        try:
            task = storage.get_task(task_id)
            task["status"] = "RUNNING"
            storage.save_task(task)
            source = storage.get_upload(task["source_file_id"])
            target = storage.get_upload(task["target_file_id"])
            profile = storage.load_profile_document(task["profile_name"])
            config = profile.get("runtime", {}).get("match_config")
            if not isinstance(config, dict):
                raise ValueError("该配置缺少可执行 match_config")
            result = run_matching(Path(source.path), Path(target.path), config)
            output_path = storage.result_path(task_id)
            write_result_xlsx(result, output_path)
            task["status"] = "COMPLETED"
            task["summary"] = result["summary"]
            task["result_path"] = str(output_path)
            storage.save_task(task)
        except Exception as exc:
            try:
                task = storage.get_task(task_id)
                task["status"] = "FAILED"
                task["error"] = str(exc)
                storage.save_task(task)
            except Exception:
                pass

    @app.post("/api/tasks")
    def create_task(payload: CreateTaskRequest, background: BackgroundTasks, _: str = Depends(require_admin)) -> dict[str, Any]:
        upload_or_404(payload.source_file_id)
        upload_or_404(payload.target_file_id)
        try:
            storage.load_profile_document(payload.profile_name)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="匹配方案不存在") from exc
        task = storage.create_task(payload.model_dump())
        background.add_task(execute_task, task["task_id"])
        return task

    @app.get("/api/tasks")
    def list_tasks(_: str = Depends(require_admin)) -> list[dict[str, Any]]:
        return storage.list_tasks()

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str, _: str = Depends(require_admin)) -> dict[str, Any]:
        try:
            return storage.get_task(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc

    @app.get("/api/tasks/{task_id}/result")
    def task_result(task_id: str, _: str = Depends(require_admin)):
        try:
            task = storage.get_task(task_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail="任务不存在") from exc
        path = Path(task.get("result_path", ""))
        if task.get("status") != "COMPLETED" or not path.exists():
            raise HTTPException(status_code=409, detail="任务尚未生成结果")
        return FileResponse(path, filename=f"material_matcher_{task_id}.xlsx")

    index_file = runtime.web_root / "index.html"
    assets_dir = runtime.web_root / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/", include_in_schema=False)
    def root():
        if index_file.is_file():
            return FileResponse(index_file)
        return {
            "name": "MATERIAL_MATCHER",
            "version": __version__,
            "message": "Web UI 尚未构建，请访问 /api/docs 或构建 web/dist。",
        }

    return app


app = create_app()
