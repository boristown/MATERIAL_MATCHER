from __future__ import annotations

from importlib.metadata import version as distribution_version
from pathlib import Path
import tomllib

import material_matcher
from fastapi.testclient import TestClient


REPO = Path(__file__).resolve().parents[1]
VERSION_FILE = REPO / "src/material_matcher/VERSION"


def _canonical_version() -> str:
    return VERSION_FILE.read_text(encoding="utf-8").strip()


def test_canonical_version_drives_package_and_distribution_metadata() -> None:
    canonical = _canonical_version()
    assert material_matcher.__version__ == canonical
    assert distribution_version("material-matcher") == canonical


def test_pyproject_has_no_second_manual_version_source() -> None:
    with (REPO / "pyproject.toml").open("rb") as stream:
        pyproject = tomllib.load(stream)
    project = pyproject["project"]
    assert "version" not in project
    assert "version" in project["dynamic"]
    assert pyproject["tool"]["setuptools"]["dynamic"]["version"] == {"attr": "material_matcher.__version__"}
    assert "VERSION" in pyproject["tool"]["setuptools"]["package-data"]["material_matcher"]


def test_health_returns_canonical_version(client: TestClient) -> None:
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["version"] == _canonical_version() == material_matcher.__version__


def test_release_builders_resolve_the_canonical_version() -> None:
    from scripts.versioning import canonical_version, resolve_release_version

    canonical = _canonical_version()
    assert canonical_version(REPO) == canonical
    assert resolve_release_version(None, repo_root=REPO) == canonical
    assert resolve_release_version(canonical, repo_root=REPO) == canonical
