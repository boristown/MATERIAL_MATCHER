from __future__ import annotations

from fastapi import Depends, FastAPI, File, Header, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .excel_inspector import inspect_excel
from .plugins import registry
from .security import SessionStore, verify_admin_password
from .settings import Settings


MAX_INSPECT_BYTES = 50 * 1024 * 1024


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    expires_at: float


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime = settings or Settings.load()
    sessions = SessionStore(runtime.session_ttl_seconds)
    app = FastAPI(title="MATERIAL_MATCHER", version=__version__, docs_url="/api/docs", redoc_url=None)

    def require_admin(authorization: str | None = Header(default=None)) -> str:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="请先登录")
        token = authorization.removeprefix("Bearer ").strip()
        if not sessions.validate(token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="登录已失效，请重新登录")
        return token

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
    async def inspect_excel_file(
        file: UploadFile = File(...),
        _: str = Depends(require_admin),
    ) -> dict[str, object]:
        filename = file.filename or ""
        if not filename.lower().endswith((".xlsx", ".xlsm")):
            raise HTTPException(status_code=400, detail="当前仅支持 .xlsx / .xlsm 文件")
        payload = await file.read(MAX_INSPECT_BYTES + 1)
        if len(payload) > MAX_INSPECT_BYTES:
            raise HTTPException(status_code=413, detail="样表超过 50MB，请使用更小的配置样表")
        try:
            inspection = inspect_excel(payload)
        except Exception as exc:
            raise HTTPException(status_code=400, detail=f"无法解析 Excel：{exc}") from exc
        return inspection.to_dict()

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
