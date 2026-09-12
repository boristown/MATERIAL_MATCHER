from __future__ import annotations

from pathlib import Path

from fastapi import Depends, FastAPI, Header, HTTPException, status
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__
from .plugins import registry
from .security import SessionStore, verify_admin_password
from .settings import Settings


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
