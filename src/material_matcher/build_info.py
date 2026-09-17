from __future__ import annotations

from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

from material_matcher import __version__

PRODUCT_NAME = "物料集团码智能匹配平台"
DEPLOYMENT_NATIVE_SOURCE = "native-source"
DEPLOYMENT_DOCKER_SOURCE = "docker-source"


def _manifest_candidates() -> list[Path]:
    candidates: list[Path] = []
    configured = os.getenv("MATERIAL_MATCHER_RELEASE_MANIFEST", "").strip()
    if configured:
        candidates.append(Path(configured))
    for parent in Path(__file__).resolve().parents:
        candidates.append(parent / "release-manifest.json")
    return candidates


@lru_cache(maxsize=1)
def _release_manifest() -> dict[str, Any]:
    for path in _manifest_candidates():
        if not path.is_file():
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("product") == "MATERIAL_MATCHER_RELEASE":
            return payload
    return {}


def build_about_payload() -> dict[str, str]:
    manifest = _release_manifest()
    deployment_mode = os.getenv("MATERIAL_MATCHER_DEPLOYMENT_MODE", "").strip() or str(
        manifest.get("deployment_mode") or DEPLOYMENT_NATIVE_SOURCE
    )
    return {
        "product_name": PRODUCT_NAME,
        "version": __version__,
        "build_time": os.getenv("MATERIAL_MATCHER_BUILD_TIME", "").strip()
        or str(manifest.get("build_time") or manifest.get("created_at") or ""),
        "git_commit": os.getenv("MATERIAL_MATCHER_GIT_COMMIT", "").strip()
        or str(manifest.get("git_commit") or ""),
        "deployment_mode": deployment_mode,
    }
