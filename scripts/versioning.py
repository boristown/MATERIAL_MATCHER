from __future__ import annotations

from pathlib import Path
import re


VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def canonical_version(repo_root: Path | None = None) -> str:
    root = repo_root or Path(__file__).resolve().parents[1]
    path = root / "src/material_matcher/VERSION"
    if not path.is_file():
        raise ValueError(f"缺少 canonical version 文件：{path}")
    version = path.read_text(encoding="utf-8").strip()
    if not VERSION_RE.fullmatch(version):
        raise ValueError(f"canonical version 格式无效：{version!r}")
    return version


def resolve_release_version(requested: str | None, *, repo_root: Path | None = None) -> str:
    version = canonical_version(repo_root)
    if requested is not None and requested.strip() and requested.strip() != version:
        raise ValueError(
            f"release_version={requested.strip()} 与项目版本 {version} 不一致；"
            "发布版本只允许修改 src/material_matcher/VERSION"
        )
    return version
