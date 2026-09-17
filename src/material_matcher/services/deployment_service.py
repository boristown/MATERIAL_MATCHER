from __future__ import annotations

import json
import os
from pathlib import Path
import platform
from typing import Any

from material_matcher import __version__
from material_matcher.embedding.providers import embedding_runtime_status


def _normalize_arch(value: str) -> str:
    value = value.lower().strip()
    if value in {"x86_64", "amd64"}:
        return "x86_64"
    if value in {"aarch64", "arm64"}:
        return "aarch64"
    return value


def _check_path(path: Path, *, write: bool = False) -> dict[str, object]:
    exists = path.exists()
    ok = exists and (not write or os.access(path, os.W_OK))
    return {"ok": ok, "path": str(path), "exists": exists, "writable": os.access(path, os.W_OK) if exists else False}


def _release_manifest_path(web_dist_dir: Path) -> Path:
    configured = os.getenv("MATERIAL_MATCHER_RELEASE_MANIFEST", "").strip()
    if configured:
        return Path(configured)
    if web_dist_dir.name == "web-dist":
        return web_dist_dir.parent / "release-manifest.json"
    # Backward-compatible lookup for the historical release/web/dist layout.
    return web_dist_dir.parent.parent / "release-manifest.json"


def deployment_diagnostics(
    settings: object,
    *,
    require_frontend: bool = False,
    require_embedding: bool = False,
    require_release_manifest: bool = False,
) -> dict[str, Any]:
    data_dir = Path(getattr(settings, "data_dir"))
    config_dir = Path(getattr(settings, "config_dir"))
    log_dir = Path(getattr(settings, "log_dir"))
    web_dist_dir = Path(getattr(settings, "web_dist_dir"))

    checks: dict[str, dict[str, object]] = {
        "data_dir": _check_path(data_dir, write=True),
        "tmp_dir": _check_path(data_dir / "tmp", write=True),
        "config_dir": _check_path(config_dir, write=False),
        "log_dir": _check_path(log_dir, write=True),
    }

    frontend_ok = (web_dist_dir / "index.html").is_file()
    checks["frontend"] = {
        "ok": frontend_ok if require_frontend else True,
        "ready": frontend_ok,
        "required": require_frontend,
        "dist_dir": str(web_dist_dir),
    }

    embedding = embedding_runtime_status(settings)
    checks["embedding"] = {
        "ok": bool(embedding.get("ready")) if require_embedding else True,
        "ready": bool(embedding.get("ready")),
        "required": require_embedding,
        "details": embedding,
    }

    release_manifest_path = _release_manifest_path(web_dist_dir)
    release_manifest: dict[str, object] | None = None
    release_error: str | None = None
    if release_manifest_path.is_file():
        try:
            release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
            manifest_version = str(release_manifest.get("release_version") or "")
            manifest_arch = _normalize_arch(str(release_manifest.get("target_arch") or ""))
            current_arch = _normalize_arch(platform.machine())
            release_ok = (
                release_manifest.get("product") == "MATERIAL_MATCHER_RELEASE"
                and release_manifest.get("format_version") == 1
                and manifest_version == __version__
                and manifest_arch == current_arch
            )
        except Exception as exc:  # diagnostic path must report rather than mask the root cause
            release_ok = False
            release_error = str(exc)
    else:
        release_ok = False

    checks["release_manifest"] = {
        "ok": release_ok if require_release_manifest else True,
        "ready": release_ok,
        "required": require_release_manifest,
        "path": str(release_manifest_path),
        "runtime_version": __version__,
        "runtime_arch": _normalize_arch(platform.machine()),
        "manifest": release_manifest,
        "error": release_error,
    }

    failed = [name for name, check in checks.items() if not bool(check.get("ok"))]
    return {
        "ok": not failed,
        "version": __version__,
        "failed_checks": failed,
        "checks": checks,
    }
