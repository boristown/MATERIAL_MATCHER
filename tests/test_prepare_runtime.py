from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import shlex
import subprocess
import sys


def _arch() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "aarch64"
    raise RuntimeError(value)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name == "runtime-manifest.json":
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _base_runtime(tmp_path: Path) -> Path:
    base = tmp_path / "base-runtime"
    fake_modules = tmp_path / "fake-modules"
    fake_modules.mkdir(parents=True)
    (fake_modules / "onnxruntime.py").write_text("__version__='test'\n", encoding="utf-8")
    (fake_modules / "tokenizers.py").write_text("__version__='test'\n", encoding="utf-8")
    python = base / "bin/python3"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        "if [ \"${1:-}\" = \"-m\" ] && [ \"${2:-}\" = \"pip\" ]; then exit 0; fi\n"
        f"export PYTHONPATH={shlex.quote(str(fake_modules))}:\"${{PYTHONPATH:-}}\"\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    return base


def test_prepare_runtime_uses_offline_install_contract(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    output = tmp_path / "runtime"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/prepare_runtime.py"),
            "--base-runtime-dir", str(_base_runtime(tmp_path)),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(output),
            "--target-arch", _arch(),
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert Path(result.stdout.strip()) == output / "runtime-manifest.json"
    manifest = json.loads((output / "runtime-manifest.json").read_text(encoding="utf-8"))
    assert manifest["product"] == "MATERIAL_MATCHER_PYTHON_RUNTIME"
    assert manifest["target_arch"] == _arch()
    assert manifest["python_version"] == platform.python_version()
    assert len(manifest["runtime_tree_sha256"]) == 64
    assert manifest["runtime_tree_sha256"] == _tree_sha256(output)
    assert any(str(item).startswith("onnxruntime") for item in manifest["dependencies"])
    assert any(str(item).startswith("tokenizers") for item in manifest["dependencies"])
    launcher = output / "bin/material-matcher"
    assert launcher.is_file()
    assert launcher.stat().st_mode & 0o111
    assert "material_matcher.cli" in launcher.read_text(encoding="utf-8")


def test_prepare_runtime_rejects_output_overlapping_input(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    base = _base_runtime(tmp_path)
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/prepare_runtime.py"),
            "--base-runtime-dir", str(base),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(base / "nested"),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "输出目录不能与输入目录重叠" in result.stderr
