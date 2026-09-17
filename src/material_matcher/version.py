from __future__ import annotations

from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path
import re

_PROJECT_VERSION_RE = re.compile(
    r'^\s*version\s*=\s*["\']([^"\']+)["\']\s*$',
    re.MULTILINE,
)
_PROJECT_SECTION_RE = re.compile(r'^\s*\[project\]\s*$', re.MULTILINE)
_NEXT_SECTION_RE = re.compile(r'^\s*\[[^]]+\]\s*$', re.MULTILINE)


def _source_pyproject() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "pyproject.toml"
        if candidate.is_file():
            return candidate
    return None


def _version_from_pyproject(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    section = _PROJECT_SECTION_RE.search(text)
    if section is None:
        raise RuntimeError(f"pyproject.toml 缺少 [project]：{path}")
    next_section = _NEXT_SECTION_RE.search(text, section.end())
    body = text[section.end() : next_section.start() if next_section else len(text)]
    match = _PROJECT_VERSION_RE.search(body)
    if match is None:
        raise RuntimeError(f"pyproject.toml 缺少 [project].version：{path}")
    return match.group(1)


def get_version() -> str:
    """Return the application version without maintaining a second literal version."""
    source = _source_pyproject()
    if source is not None:
        return _version_from_pyproject(source)
    try:
        return distribution_version("material-matcher")
    except PackageNotFoundError:
        return "0+unknown"
