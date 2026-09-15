from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
import hashlib
import logging
import os
from pathlib import Path
import re
from typing import Any
import uuid

from fastapi import FastAPI, File, Form, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from material_matcher import __version__
from material_matcher.domain.errors import DomainError
from material_matcher.embedding.providers import embedding_runtime_status
from material_matcher.ingestion.inspector import inspect_tabular_file
from material_matcher.security.session import SessionStore
from material_matcher.security.users import ROLES, UserService
from material_matcher.services.benchmark_service import BenchmarkService
from material_matcher.services.business_evaluation_service import BusinessEvaluationService
from material_matcher.services.catalog_service import CatalogService
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.services.match_service import MatchService
from material_matcher.services.profile_service import ProfileService
from material_matcher.services.task_service import TaskService
from material_matcher.services.text_profile_service import TextProfileService
from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.storage.metadata import MetadataRepository
from material_matcher.tasks.worker import TaskWorker

logger = logging.getLogger("material_matcher")
COOKIE_NAME = "mm_session"
_ALLOWED_ROLES = {"source", "target", "supplement"}
_ALLOWED_SUFFIXES = {".xlsx", ".xlsm", ".csv"}


class LoginRequest(BaseModel):
    username: str
    password: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=10, max_length=200)


class UserCreate(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=10, max_length=200)
    role: str = Field(pattern="^(admin|operator|reviewer|viewer)$")


class UserUpdate(BaseModel):
    role: str | None = Field(default=None, pattern="^(admin|operator|reviewer|viewer)$")
    enabled: bool | None = None


class UserPasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=200)
    must_change_password: bool = True


class DraftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)


class DraftData(BaseModel):
    source_file_id: str
    catalog_version_id: str
    template_profile_id: str | None = None
    template_profile_version: int | None = None


class CatalogCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_file_id: str
    group_code_column: str = Field(min_length=1, max_length=200)


class CatalogVersionCreate(BaseModel):
    source_file_id: str
    group_code_column: str = Field(min_length=1, max_length=200)
    activate: bool = False


class DictionaryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    mapping: dict[str, str] = Field(min_length=1)
    case_sensitive: bool = True


class DictionaryVersionCreate(BaseModel):
    mapping: dict[str, str] = Field(min_length=1)
    case_sensitive: bool = True


class ProfileCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    document: dict[str, object] | None = None


class UploadInit(BaseModel):
    role: str
    original_name: str
    total_size: int = Field(gt=0)
    sha256: str | None = None


class DryRunRequest(BaseModel):
    sample_rows: int = Field(default=100, ge=1, le=1000)


class TextProfileRequest(BaseModel):
    sample_rows: int = Field(default=4096, ge=64, le=50_000)
    scan_limit: int = Field(default=100_000, ge=64, le=2_000_000)


class ConfirmRequest(BaseModel):
    target_id: str
    comment: str = Field(default="", max_length=500)


class RejectRequest(BaseModel):
    comment: str = Field(default="", max_length=500)


class BatchRequest(BaseModel):
    source_row_ids: list[str] = Field(min_length=1, max_length=1000)


class FinalizeRequest(BaseModel):
    allow_unresolved_review: bool = False


class BusinessEvaluationRequest(BaseModel):
    truth_file_id: str = Field(min_length=1)
    key_column: str = Field(min_length=1, max_length=200)
    expected_group_code_column: str = Field(min_length=1, max_length=200)
    key_mode: str = Field(default="source_id", pattern="^(source_id|source_row_id)$")


class EmbeddingBenchmarkRequest(BaseModel):
    sample_count: int = Field(default=1000, ge=16, le=50_000)
    batch_size: int | None = Field(default=None, ge=1, le=2048)


class VectorBenchmarkRequest(BaseModel):
    target_rows: int = Field(default=10_000, ge=100, le=100_000)
    query_count: int = Field(default=100, ge=1, le=5_000)
    dimensions: int = Field(default=128, ge=16, le=2048)
    top_k: int = Field(default=50, ge=1, le=1000)


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _reviewer_mutation_allowed(path: str) -> bool:
    return bool(
        re.fullmatch(r"/api/tasks/[^/]+/items/[^/]+/(confirm|reject)", path)
        or re.fullmatch(r"/api/tasks/[^/]+/workbench/(batch-confirm-top1|batch-reject)", path)
        or re.fullmatch(r"/api/tasks/[^/]+/finalize", path)
        or re.fullmatch(r"/api/tasks/[^/]+/evaluations", path)
    )


def create_app(settings: Settings | None = None) -> FastAPI:
    cfg = settings or Settings.load()
    cfg.ensure_dirs()
    metadata = MetadataRepository(cfg.data_dir / "meta" / "material_matcher.db")
    files = FileRepository(cfg.data_dir, metadata)
    catalogs = CatalogService(metadata, files)
    dictionaries = DictionaryService(metadata)
    users = UserService(metadata)
    users.ensure_bootstrap_admin(cfg.admin_password)
    tasks = TaskService(metadata)
    profiles = ProfileService(metadata)
    matches = MatchService(metadata, files, cfg)
    benchmarks = BenchmarkService(metadata, cfg)
    evaluations = BusinessEvaluationService(metadata, files)
    text_profiles = TextProfileService(metadata, files, cfg, matches.indexes)
    worker = TaskWorker(matches, cfg.worker_poll_seconds)
    sessions = SessionStore(cfg.session_ttl_seconds)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if cfg.worker_enabled:
            worker.start()
        try:
            yield
        finally:
            worker.stop()

    app = FastAPI(title="MATERIAL_MATCHER", version=__version__, docs_url="/api/docs", redoc_url=None, lifespan=lifespan)

    def get_catalog_version(version_id: str) -> dict[str, object]:
        return catalogs.version(version_id)

    @app.exception_handler(DomainError)
    async def domain_error_handler(request: Request, exc: DomainError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.code, "message": exc.message, "details": exc.details, "request_id": request_id}})

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        del exc
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        return JSONResponse(status_code=422, content={"error": {"code": "INVALID_REQUEST", "message": "提交内容不完整或格式不正确，请检查后重试", "details": {}, "request_id": request_id}})

    @app.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = getattr(request.state, "request_id", uuid.uuid4().hex[:12])
        logger.exception("request failed id=%s", request_id, exc_info=exc)
        return JSONResponse(status_code=500, content={"error": {"code": "INTERNAL_ERROR", "message": "系统处理失败，请联系管理员并提供请求编号", "details": {}, "request_id": request_id}})

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Response:
        request.state.request_id = uuid.uuid4().hex[:12]
        public_paths = {"/api/health", "/api/health/ready", "/api/auth/login", "/api/docs", "/api/openapi.json"}
        path = request.url.path
        if path.startswith("/api/") and path not in public_paths:
            session = sessions.get(request.cookies.get(COOKIE_NAME))
            if session is None:
                return JSONResponse(status_code=401, content={"error": {"code": "AUTH_REQUIRED", "message": "登录已失效，请重新登录", "details": {}, "request_id": request.state.request_id}})
            try:
                principal = users.get(session.username)
            except DomainError:
                sessions.revoke(request.cookies.get(COOKIE_NAME))
                return JSONResponse(status_code=401, content={"error": {"code": "AUTH_REQUIRED", "message": "账号已失效，请重新登录", "details": {}, "request_id": request.state.request_id}})
            if not principal["enabled"]:
                sessions.revoke_user(session.username)
                return JSONResponse(status_code=401, content={"error": {"code": "AUTH_REQUIRED", "message": "账号已停用", "details": {}, "request_id": request.state.request_id}})
            request.state.username = session.username
            request.state.role = str(principal["role"])
            if principal["must_change_password"] and path not in {"/api/auth/me", "/api/auth/change-password", "/api/auth/logout"}:
                return JSONResponse(status_code=403, content={"error": {"code": "PASSWORD_CHANGE_REQUIRED", "message": "管理员已重置密码，请先修改密码", "details": {}, "request_id": request.state.request_id}})
            if request.method.upper() not in {"GET", "HEAD", "OPTIONS"} and path not in {"/api/auth/logout", "/api/auth/change-password"}:
                role = str(principal["role"])
                allowed = role == "admin" or (role == "operator" and not path.startswith("/api/users")) or (role == "reviewer" and _reviewer_mutation_allowed(path))
                if not allowed:
                    return JSONResponse(status_code=403, content={"error": {"code": "PERMISSION_DENIED", "message": "当前账号没有执行此操作的权限", "details": {"role": role}, "request_id": request.state.request_id}})
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "version": __version__}

    @app.get("/api/health/ready")
    def ready() -> dict[str, object]:
        with metadata.connect() as connection:
            admin_count = int(connection.execute("SELECT COUNT(*) AS count FROM users WHERE role='admin' AND enabled=1").fetchone()["count"])
        checks = {
            "admin_account": admin_count > 0,
            "database": os.access(metadata.db_path, os.R_OK | os.W_OK),
            "data_dir": os.access(cfg.data_dir, os.W_OK),
            "tmp_dir": os.access(cfg.data_dir / "tmp", os.W_OK),
        }
        return {"status": "ready" if all(checks.values()) else "not_ready", "checks": checks}

    @app.post("/api/auth/login")
    def login(payload: LoginRequest, response: Response) -> dict[str, object]:
        principal = users.authenticate(payload.username, payload.password)
        session = sessions.create(str(principal["username"]), str(principal["role"]))
        response.set_cookie(COOKIE_NAME, session.token, httponly=True, samesite="strict", secure=False, max_age=cfg.session_ttl_seconds, path="/")
        return {"ok": True, "expires_at": datetime.fromtimestamp(session.expires_at).astimezone().isoformat(), "user": principal}

    @app.get("/api/auth/me")
    def auth_me(request: Request) -> dict[str, object]:
        return users.get(str(request.state.username))

    @app.post("/api/auth/change-password")
    def change_password(request: Request, payload: ChangePasswordRequest, response: Response) -> dict[str, object]:
        username = str(request.state.username)
        users.authenticate(username, payload.current_password)
        user = users.set_password(username, payload.new_password, must_change_password=False)
        sessions.revoke_user(username)
        response.delete_cookie(COOKIE_NAME, path="/")
        return {"ok": True, "user": user, "relogin_required": True}

    @app.post("/api/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        sessions.revoke(request.cookies.get(COOKIE_NAME)); response.delete_cookie(COOKIE_NAME, path="/"); return {"ok": True}

    @app.get("/api/users")
    def list_users(request: Request) -> list[dict[str, object]]:
        if str(request.state.role) != "admin": raise DomainError("PERMISSION_DENIED", "仅管理员可查看账号", status_code=403)
        return users.list()

    @app.post("/api/users")
    def create_user(request: Request, payload: UserCreate) -> dict[str, object]:
        if str(request.state.role) != "admin": raise DomainError("PERMISSION_DENIED", "仅管理员可创建账号", status_code=403)
        return users.create(payload.username, payload.password, payload.role)

    @app.patch("/api/users/{username}")
    def update_user(username: str, request: Request, payload: UserUpdate) -> dict[str, object]:
        if str(request.state.role) != "admin": raise DomainError("PERMISSION_DENIED", "仅管理员可修改账号", status_code=403)
        result = users.update(username, role=payload.role, enabled=payload.enabled)
        sessions.revoke_user(username)
        return result

    @app.post("/api/users/{username}/reset-password")
    def reset_user_password(username: str, request: Request, payload: UserPasswordReset) -> dict[str, object]:
        if str(request.state.role) != "admin": raise DomainError("PERMISSION_DENIED", "仅管理员可重置密码", status_code=403)
        result = users.set_password(username, payload.password, must_change_password=payload.must_change_password)
        sessions.revoke_user(username)
        return result

    @app.post("/api/files/upload")
    async def upload_file(role: str = Form(...), file: UploadFile = File(...)) -> dict[str, object]:
        if role not in _ALLOWED_ROLES:
            raise DomainError("INVALID_FILE_ROLE", "文件用途不正确", status_code=422)
        suffix = Path(file.filename or "").suffix.lower()
        if suffix == ".xls": raise DomainError("UNSUPPORTED_FILE", "暂不支持 .xls，请先转换为 .xlsx", status_code=400)
        if suffix not in _ALLOWED_SUFFIXES: raise DomainError("UNSUPPORTED_FILE", "仅支持 .xlsx / .xlsm / .csv", status_code=400)
        record = files.save_stream(file.filename or "upload", role, file.file, cfg.max_upload_bytes)
        try:
            inspection = inspect_tabular_file(Path(str(record["stored_path"])))
        except Exception as exc:
            raise DomainError("FILE_PARSE_FAILED", "表格无法解析，请确认文件格式和内容", status_code=400) from exc
        return {"file": record, "inspection": inspection}

    @app.get("/api/files")
    def list_files() -> list[dict[str, object]]: return files.list()

    @app.get("/api/files/{file_id}/inspection")
    def inspect_file(file_id: str) -> dict[str, object]:
        record = files.get(file_id); return {"file": record, "inspection": inspect_tabular_file(Path(str(record["stored_path"])))}

    @app.post("/api/uploads/init")
    def init_upload(payload: UploadInit) -> dict[str, object]:
        if payload.role not in _ALLOWED_ROLES: raise DomainError("INVALID_FILE_ROLE", "文件用途不正确", status_code=422)
        if payload.total_size > cfg.max_total_upload_bytes: raise DomainError("FILE_TOO_LARGE", "文件超过系统允许的最大容量", status_code=413)
        suffix = Path(payload.original_name).suffix.lower()
        if suffix == ".xls": raise DomainError("UNSUPPORTED_FILE", "暂不支持 .xls，请先转换为 .xlsx", status_code=400)
        if suffix not in _ALLOWED_SUFFIXES: raise DomainError("UNSUPPORTED_FILE", "仅支持 .xlsx / .xlsm / .csv", status_code=400)
        upload_id = uuid.uuid4().hex; temporary_path = cfg.data_dir / "tmp" / f"upload-{upload_id}{suffix}.part"
        with metadata.connect() as connection:
            connection.execute("INSERT INTO upload_sessions VALUES(?,?,?,?,?,?,?,?,?)", (upload_id, payload.role, payload.original_name, payload.total_size, payload.sha256, 0, 0, str(temporary_path), _now()))
        return {"upload_id": upload_id, "chunk_size": cfg.chunk_size_bytes, "next_chunk": 0}

    @app.put("/api/uploads/{upload_id}/chunks/{index}")
    async def upload_chunk(upload_id: str, index: int, request: Request) -> dict[str, int]:
        with metadata.connect() as connection: row = connection.execute("SELECT * FROM upload_sessions WHERE upload_id=?", (upload_id,)).fetchone()
        if row is None: raise DomainError("UPLOAD_NOT_FOUND", "分块上传任务不存在", status_code=404)
        data = await request.body()
        if index != row["next_chunk"]: raise DomainError("UPLOAD_CHUNK_ORDER", "分块顺序不正确", status_code=409, details={"next_chunk": row["next_chunk"]})
        if len(data) > cfg.chunk_size_bytes: raise DomainError("UPLOAD_CHUNK_TOO_LARGE", "单个分块超过允许大小", status_code=413)
        received_bytes = int(row["received_bytes"]) + len(data)
        if received_bytes > int(row["expected_size"]): raise DomainError("UPLOAD_SIZE_MISMATCH", "上传数据超过预期文件大小", status_code=409)
        path=Path(str(row["tmp_path"])); path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as output: output.write(data)
        with metadata.connect() as connection: connection.execute("UPDATE upload_sessions SET received_bytes=?, next_chunk=? WHERE upload_id=?", (received_bytes, index + 1, upload_id))
        return {"received_bytes": received_bytes, "next_chunk": index + 1}

    @app.post("/api/uploads/{upload_id}/complete")
    def complete_upload(upload_id: str) -> dict[str, object]:
        with metadata.connect() as connection: row=connection.execute("SELECT * FROM upload_sessions WHERE upload_id=?",(upload_id,)).fetchone()
        if row is None: raise DomainError("UPLOAD_NOT_FOUND", "分块上传任务不存在", status_code=404)
        path=Path(str(row["tmp_path"]))
        if row["received_bytes"] != row["expected_size"]: raise DomainError("UPLOAD_SIZE_MISMATCH", "上传文件大小与预期不一致", status_code=409)
        if row["expected_sha256"] and _sha256_file(path).lower() != str(row["expected_sha256"]).lower(): raise DomainError("UPLOAD_HASH_MISMATCH", "上传文件校验失败", status_code=409)
        with path.open("rb") as stream: record=files.save_stream(str(row["original_name"]),str(row["role"]),stream,cfg.max_total_upload_bytes)
        path.unlink(missing_ok=True)
        with metadata.connect() as connection: connection.execute("DELETE FROM upload_sessions WHERE upload_id=?",(upload_id,))
        return {"file":record,"inspection":inspect_tabular_file(Path(str(record["stored_path"])))}

    @app.post("/api/catalogs")
    def create_catalog(payload: CatalogCreate) -> dict[str, object]:
        return catalogs.create(payload.name, payload.source_file_id, payload.group_code_column)

    @app.get("/api/catalogs")
    def list_catalogs() -> list[dict[str, object]]:
        return catalogs.list_versions()

    @app.get("/api/catalogs/versions/{version_id}")
    def get_catalog(version_id: str) -> dict[str, object]:
        return catalogs.version(version_id)

    @app.get("/api/catalogs/{catalog_id}/versions")
    def catalog_versions(catalog_id: str) -> list[dict[str, object]]:
        return catalogs.versions(catalog_id)

    @app.post("/api/catalogs/{catalog_id}/versions")
    def create_catalog_version(catalog_id: str, payload: CatalogVersionCreate) -> dict[str, object]:
        return catalogs.add_version(catalog_id, source_file_id=payload.source_file_id, group_code_column=payload.group_code_column, activate=payload.activate)

    @app.post("/api/catalogs/{catalog_id}/versions/{version_id}/activate")
    def activate_catalog_version(catalog_id: str, version_id: str) -> dict[str, object]:
        return catalogs.activate(catalog_id, version_id)

    @app.get("/api/dictionaries")
    def list_dictionaries() -> list[dict[str, object]]:
        return dictionaries.list()

    @app.post("/api/dictionaries")
    def create_dictionary(payload: DictionaryCreate) -> dict[str, object]:
        return dictionaries.create(payload.name, {"mapping": payload.mapping, "case_sensitive": payload.case_sensitive})

    @app.get("/api/dictionaries/{dictionary_id}")
    def get_dictionary(dictionary_id: str) -> dict[str, object]:
        return dictionaries.get(dictionary_id)

    @app.get("/api/dictionaries/{dictionary_id}/versions")
    def dictionary_versions(dictionary_id: str) -> list[dict[str, object]]:
        return dictionaries.versions(dictionary_id)

    @app.post("/api/dictionaries/{dictionary_id}/versions")
    def create_dictionary_version(dictionary_id: str, payload: DictionaryVersionCreate) -> dict[str, object]:
        return dictionaries.add_version(dictionary_id, {"mapping": payload.mapping, "case_sensitive": payload.case_sensitive})

    @app.get("/api/profiles")
    def list_profiles() -> list[dict[str, object]]: return profiles.list()

    @app.post("/api/profiles")
    def create_profile(payload: ProfileCreate) -> dict[str, object]: return profiles.create(payload.name, payload.document)

    @app.get("/api/profiles/{profile_id}")
    def get_profile(profile_id: str) -> dict[str, object]: return profiles.get(profile_id)

    @app.put("/api/profiles/{profile_id}/draft")
    async def save_profile_draft(profile_id: str, request: Request) -> dict[str, object]:
        document = await request.json()
        if not isinstance(document, dict): raise DomainError("INVALID_PROFILE", "匹配方案格式不正确", status_code=422)
        return profiles.save_draft(profile_id, document)

    @app.post("/api/profiles/{profile_id}/validate")
    def validate_profile(profile_id: str) -> dict[str, object]: return profiles.validate(profile_id)

    @app.post("/api/profiles/{profile_id}/publish")
    def publish_profile(profile_id: str) -> dict[str, object]: return profiles.publish(profile_id)

    @app.get("/api/profiles/{profile_id}/versions")
    def profile_versions(profile_id: str) -> list[dict[str, object]]: return profiles.versions(profile_id)

    @app.post("/api/profiles/{profile_id}/rollback/{version_no}")
    def rollback_profile(profile_id: str, version_no: int) -> dict[str, object]: return profiles.rollback(profile_id, version_no)

    @app.post("/api/task-drafts")
    def create_draft(payload: DraftCreate) -> dict[str, object]: return tasks.create_draft(payload.name)

    @app.get("/api/task-drafts")
    def list_drafts() -> list[dict[str, object]]: return tasks.list_drafts()

    @app.get("/api/task-drafts/{draft_id}")
    def get_draft(draft_id: str) -> dict[str, object]: return tasks.get_draft(draft_id)

    @app.put("/api/task-drafts/{draft_id}/data")
    def save_draft_data(draft_id: str, payload: DraftData) -> dict[str, object]:
        files.get(payload.source_file_id); get_catalog_version(payload.catalog_version_id); return tasks.save_data(draft_id,payload.model_dump())

    @app.put("/api/task-drafts/{draft_id}/rules")
    async def save_draft_rules(draft_id: str, request: Request) -> dict[str, object]:
        document=await request.json()
        if not isinstance(document,dict): raise DomainError("INVALID_PROFILE","匹配规则格式不正确",status_code=422)
        return tasks.save_rules(draft_id,document)

    @app.post("/api/task-drafts/{draft_id}/dry-run")
    def dry_run(draft_id: str, payload: DryRunRequest) -> dict[str, object]: return matches.dry_run(draft_id,payload.sample_rows)

    @app.post("/api/task-drafts/{draft_id}/text-profile")
    def text_profile(draft_id: str, payload: TextProfileRequest) -> dict[str, object]: return text_profiles.profile_draft(draft_id, sample_rows=payload.sample_rows, scan_limit=payload.scan_limit)

    @app.post("/api/task-drafts/{draft_id}/start",status_code=202)
    def start_task(draft_id: str) -> dict[str, object]:
        task=tasks.start(draft_id); worker.notify(); return task

    @app.get("/api/tasks")
    def list_tasks() -> list[dict[str, object]]: return tasks.list_tasks()

    @app.get("/api/tasks/{task_id}")
    def get_task(task_id: str) -> dict[str, object]: return tasks.get_task(task_id)

    @app.get("/api/tasks/{task_id}/progress")
    def get_progress(task_id: str) -> dict[str, object]:
        task=tasks.get_task(task_id); status=str(task["status"]); stage=str(task["stage"])
        runtime=matches.runtime_status(task_id); mode=str(runtime.get("execution_mode") or "unknown"); phase=str(runtime.get("current_phase") or "WAITING")
        prepare="DONE" if status not in {"PENDING","PREPARING","RECOVERING"} else "RUNNING" if status in {"PREPARING","RECOVERING"} else "WAITING"
        failed=status=="FAILED" or phase=="FAILED"; completed=status=="COMPLETED" or phase=="DONE"; vector_mode=mode=="vector"
        if not vector_mode: embedding_status="SKIPPED"
        elif failed: embedding_status="FAILED"
        elif phase=="INDEX": embedding_status="RUNNING"
        elif phase in {"RETRIEVE","RERANK","PERSIST","DONE"} or completed: embedding_status="DONE"
        else: embedding_status="WAITING"

        def phase_status(active: str, done_after: set[str]) -> str:
            if failed: return "FAILED"
            if completed or phase in done_after: return "DONE"
            if phase==active: return "RUNNING"
            return "WAITING"

        retrieve_status=phase_status("RETRIEVE", {"RERANK","PERSIST","DONE"}); rerank_status=phase_status("RERANK", {"PERSIST","DONE"}); result_status=phase_status("PERSIST", {"DONE"})
        return {
            "task_id":task_id,"stage":stage,"status":status,"progress":task["progress"],"processed_rows":task["processed_rows"],"total_rows":task["total_rows"],
            "error_code":task.get("error_code"),"error_message":task.get("error_message"),"execution_mode":mode,"current_phase":phase,"index_id":runtime.get("index_id"),
            "steps":[{"key":"prepare","label":"数据准备","status":prepare},{"key":"embedding","label":"向量化 / 索引准备","status":embedding_status},{"key":"retrieve","label":"候选召回","status":retrieve_status},{"key":"rerank","label":"精细评分","status":rerank_status},{"key":"prepare_result","label":"结果持久化","status":result_status}],
        }

    @app.get("/api/tasks/{task_id}/runtime")
    def task_runtime(task_id: str) -> dict[str, object]: tasks.get_task(task_id); return matches.runtime_status(task_id)

    @app.get("/api/tasks/{task_id}/workbench/summary")
    def workbench_summary(task_id: str) -> dict[str,int]: tasks.get_task(task_id); return matches.summary(task_id)

    @app.get("/api/tasks/{task_id}/workbench/items")
    def workbench_items(task_id:str, first_score_min:float|None=None, first_score_max:float|None=None, second_score_min:float|None=None, second_score_max:float|None=None, gap_min:float|None=None, gap_max:float|None=None, critical_conflict:bool|None=None, page:int=Query(1,ge=1), page_size:int=Query(50,ge=1,le=200))->dict[str,object]:
        tasks.get_task(task_id); return matches.workbench_items(task_id,first_score_min=first_score_min,first_score_max=first_score_max,second_score_min=second_score_min,second_score_max=second_score_max,gap_min=gap_min,gap_max=gap_max,critical_conflict=critical_conflict,page=page,page_size=page_size)

    @app.get("/api/tasks/{task_id}/items/{source_row_id}/candidates")
    def item_candidates(task_id:str,source_row_id:str)->dict[str,object]: return {"candidates":matches.candidates(task_id,source_row_id)}

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/confirm")
    def confirm_item(task_id:str,source_row_id:str,payload:ConfirmRequest)->dict[str,object]: return matches.confirm(task_id,source_row_id,payload.target_id,payload.comment)

    @app.post("/api/tasks/{task_id}/items/{source_row_id}/reject")
    def reject_item(task_id:str,source_row_id:str,payload:RejectRequest)->dict[str,object]: return matches.reject(task_id,source_row_id,payload.comment)

    @app.post("/api/tasks/{task_id}/workbench/batch-confirm-top1")
    def batch_confirm(task_id:str,payload:BatchRequest)->dict[str,object]: return matches.batch_confirm_top1(task_id,payload.source_row_ids)

    @app.post("/api/tasks/{task_id}/workbench/batch-reject")
    def batch_reject(task_id:str,payload:BatchRequest)->dict[str,object]: return matches.batch_reject(task_id,payload.source_row_ids)

    @app.post("/api/tasks/{task_id}/finalize")
    def finalize(task_id:str,payload:FinalizeRequest)->dict[str,object]: return matches.finalize(task_id,payload.allow_unresolved_review)

    @app.get("/api/tasks/{task_id}/exports")
    def exports(task_id:str)->dict[str,object]:
        task=tasks.get_task(task_id); file_id=task.get("result_file_id"); return {"final_result":({"file_id":file_id,"download_url":f"/api/tasks/{task_id}/result"} if file_id else None)}

    @app.get("/api/tasks/{task_id}/result")
    def result_file(task_id:str):
        task=tasks.get_task(task_id); file_id=task.get("result_file_id")
        if not file_id: raise DomainError("TASK_STATE_CONFLICT","任务尚未生成最终结果",status_code=409)
        record=files.get(str(file_id)); return FileResponse(Path(str(record["stored_path"])),filename=str(record["original_name"]),media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

    @app.post("/api/tasks/{task_id}/evaluations")
    def create_evaluation(task_id: str, payload: BusinessEvaluationRequest) -> dict[str, object]:
        return evaluations.evaluate(task_id, truth_file_id=payload.truth_file_id, key_column=payload.key_column, expected_group_code_column=payload.expected_group_code_column, key_mode=payload.key_mode)

    @app.get("/api/tasks/{task_id}/evaluations")
    def list_evaluations(task_id: str, limit: int = Query(20, ge=1, le=200)) -> list[dict[str, object]]: return evaluations.list_for_task(task_id, limit)

    @app.get("/api/evaluations/{run_id}")
    def get_evaluation(run_id: str, include_items: bool = False, only_errors: bool = False, limit: int = Query(200, ge=1, le=2000)) -> dict[str, object]:
        return evaluations.get(run_id, include_items=include_items, only_errors=only_errors, limit=limit)

    @app.get("/api/indexes")
    def list_indexes(limit:int=Query(50,ge=1,le=200))->dict[str,object]:
        versions=matches.indexes.list_versions()[:limit]; return {"total":len(versions),"items":versions}

    @app.get("/api/system/vector-status")
    def vector_status() -> dict[str, object]:
        runtime=embedding_runtime_status(cfg); versions=matches.indexes.list_versions(); counts={"READY":0,"BUILDING":0,"FAILED":0}
        for version in versions:
            status=str(version.get("status") or ""); counts[status]=counts.get(status,0)+1
        return {"embedding":runtime,"indexes":{"counts":counts,"latest":versions[0] if versions else None,"index_dir":str(cfg.index_dir)},"cache_dir":str(cfg.embedding_cache_dir)}

    @app.get("/api/system/benchmarks")
    def list_benchmarks(limit:int=Query(20,ge=1,le=200))->list[dict[str,object]]: return benchmarks.list_runs(limit)

    @app.post("/api/system/benchmarks/embedding")
    def benchmark_embedding(payload:EmbeddingBenchmarkRequest)->dict[str,object]: return benchmarks.run_embedding(sample_count=payload.sample_count,batch_size=payload.batch_size)

    @app.post("/api/system/benchmarks/vector")
    def benchmark_vector(payload:VectorBenchmarkRequest)->dict[str,object]: return benchmarks.run_vector_kernel(target_rows=payload.target_rows,query_count=payload.query_count,dimensions=payload.dimensions,top_k=payload.top_k)

    @app.get("/api/system/info")
    def system_info() -> dict[str, object]:
        return {
            "version":__version__,"data_dir":str(cfg.data_dir),"database":str(metadata.db_path),"max_upload_bytes":cfg.max_upload_bytes,
            "max_total_upload_bytes":cfg.max_total_upload_bytes,"chunk_size_bytes":cfg.chunk_size_bytes,"baseline_max_target_rows":cfg.baseline_max_target_rows,
            "embedding":{"provider":cfg.embedding_provider,"model_id":cfg.embedding_model_id,"dimensions":cfg.embedding_dimensions,"max_length":cfg.embedding_max_length,"precision":cfg.embedding_precision},
            "authorization":{"roles":list(ROLES)},
            "index_dir":str(cfg.index_dir),"embedding_cache_dir":str(cfg.embedding_cache_dir),
        }

    app.state.meta=metadata; app.state.files=files; app.state.catalogs=catalogs; app.state.dictionaries=dictionaries; app.state.users=users; app.state.tasks=tasks; app.state.profiles=profiles; app.state.matches=matches; app.state.benchmarks=benchmarks; app.state.evaluations=evaluations; app.state.text_profiles=text_profiles; app.state.worker=worker
    return app
