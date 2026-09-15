from __future__ import annotations

import json
from pathlib import Path
import platform

from material_matcher import __version__
from material_matcher.services.deployment_service import deployment_diagnostics
from material_matcher.settings import Settings


def _arch() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "aarch64"
    return value


def _settings(tmp_path: Path) -> Settings:
    data = tmp_path / "data"
    config = tmp_path / "etc"
    log = tmp_path / "log"
    dist = tmp_path / "release/web/dist"
    for path in (data / "tmp", config, log, dist):
        path.mkdir(parents=True, exist_ok=True)
    (dist / "index.html").write_text("<html>ok</html>", encoding="utf-8")
    (tmp_path / "release/release-manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "product": "MATERIAL_MATCHER_RELEASE",
                "release_version": __version__,
                "target_arch": _arch(),
                "python_version": platform.python_version(),
                "source_tree_sha256": "a" * 64,
                "web_tree_sha256": "b" * 64,
            }
        ),
        encoding="utf-8",
    )
    return Settings(
        data_dir=data,
        config_dir=config,
        log_dir=log,
        admin_password="test-password",
        worker_enabled=False,
        web_dist_dir=dist,
        embedding_model_root=tmp_path / "missing-model-root",
    )


def test_deployment_diagnostics_accepts_matching_release_and_frontend(tmp_path: Path) -> None:
    result = deployment_diagnostics(
        _settings(tmp_path),
        require_frontend=True,
        require_release_manifest=True,
    )
    assert result["ok"] is True
    assert result["failed_checks"] == []
    assert result["checks"]["frontend"]["ready"] is True
    assert result["checks"]["release_manifest"]["ready"] is True
    assert result["checks"]["embedding"]["ready"] is False


def test_deployment_diagnostics_rejects_required_embedding_and_version_mismatch(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    release_manifest = settings.web_dist_dir.parent.parent / "release-manifest.json"
    payload = json.loads(release_manifest.read_text(encoding="utf-8"))
    payload["release_version"] = "9.9.9"
    release_manifest.write_text(json.dumps(payload), encoding="utf-8")

    result = deployment_diagnostics(
        settings,
        require_frontend=True,
        require_embedding=True,
        require_release_manifest=True,
    )
    assert result["ok"] is False
    assert "embedding" in result["failed_checks"]
    assert "release_manifest" in result["failed_checks"]
