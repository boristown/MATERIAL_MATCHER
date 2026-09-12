from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


DEFAULT_CONFIG_DIR = Path("/etc/material_matcher")
DEFAULT_DATA_DIR = Path("/var/lib/material_matcher")
DEFAULT_LOG_DIR = Path("/var/log/material_matcher")
DEFAULT_APP_DIR = Path("/opt/material_matcher")


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    admin_password: str
    config_dir: Path
    data_dir: Path
    log_dir: Path
    app_dir: Path
    web_root: Path
    session_ttl_seconds: int = 8 * 60 * 60

    @classmethod
    def load(cls) -> "Settings":
        config_dir = Path(os.getenv("MATERIAL_MATCHER_CONFIG_DIR", DEFAULT_CONFIG_DIR))
        server_env = _read_env_file(config_dir / "server.env")
        password_env = _read_env_file(config_dir / "secret" / "admin_password.env")

        host = os.getenv("MATERIAL_MATCHER_HOST", server_env.get("MATERIAL_MATCHER_HOST", "0.0.0.0"))
        port = int(os.getenv("MATERIAL_MATCHER_PORT", server_env.get("MATERIAL_MATCHER_PORT", "17843")))
        password = os.getenv("MATERIAL_MATCHER_ADMIN_PASSWORD", password_env.get("MATERIAL_MATCHER_ADMIN_PASSWORD", ""))

        app_dir = Path(os.getenv("MATERIAL_MATCHER_APP_DIR", DEFAULT_APP_DIR))
        data_dir = Path(os.getenv("MATERIAL_MATCHER_DATA_DIR", DEFAULT_DATA_DIR))
        log_dir = Path(os.getenv("MATERIAL_MATCHER_LOG_DIR", DEFAULT_LOG_DIR))
        web_root = Path(os.getenv("MATERIAL_MATCHER_WEB_ROOT", app_dir / "web"))

        return cls(
            host=host,
            port=port,
            admin_password=password,
            config_dir=config_dir,
            data_dir=data_dir,
            log_dir=log_dir,
            app_dir=app_dir,
            web_root=web_root,
        )
