from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import shlex
import subprocess
import sys
import tomllib


def _project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def _arch() -> str:
    value = platform.machine().lower()
    if value in {"amd64", "x86_64"}:
        return "x86_64"
    if value in {"arm64", "aarch64"}:
        return "aarch64"
    raise RuntimeError(f"unsupported test arch: {value}")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _runtime_tree_sha(runtime: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in runtime.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name == "runtime-manifest.json":
            continue
        digest.update(path.relative_to(runtime).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _runtime(tmp_path: Path) -> Path:
    runtime = tmp_path / "runtime-stage"
    fake_modules = tmp_path / "fake-modules"
    fake_modules.mkdir(parents=True)
    (fake_modules / "onnxruntime.py").write_text("__version__='test'\n", encoding="utf-8")
    (fake_modules / "tokenizers.py").write_text("__version__='test'\n", encoding="utf-8")
    python = runtime / "bin/python3"
    python.parent.mkdir(parents=True)
    python.write_text(
        "#!/bin/sh\n"
        f"export PYTHONPATH={shlex.quote(str(fake_modules))}:\"${{PYTHONPATH:-}}\"\n"
        f"exec {shlex.quote(sys.executable)} \"$@\"\n",
        encoding="utf-8",
    )
    python.chmod(0o755)
    launcher = runtime / "bin/material-matcher"
    launcher.write_text(
        "#!/bin/sh\n"
        "set -eu\n"
        "BIN_DIR=$(CDPATH= cd -- \"$(dirname -- \"$0\")\" && pwd)\n"
        "RELEASE_ROOT=$(CDPATH= cd -- \"$BIN_DIR/../..\" && pwd)\n"
        "export PYTHONPATH=\"$RELEASE_ROOT/source/src${PYTHONPATH:+:$PYTHONPATH}\"\n"
        "exec \"$BIN_DIR/python3\" -m material_matcher.cli \"$@\"\n",
        encoding="utf-8",
    )
    launcher.chmod(0o755)
    (runtime / "runtime-manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "product": "MATERIAL_MATCHER_PYTHON_RUNTIME",
                "target_arch": _arch(),
                "python_version": platform.python_version(),
                "dependencies": [],
                "runtime_tree_sha256": _runtime_tree_sha(runtime),
            }
        ),
        encoding="utf-8",
    )
    return runtime


def _web_dist(tmp_path: Path) -> Path:
    dist = tmp_path / "web-dist-input"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>material matcher</html>", encoding="utf-8")
    (dist / "assets/app.js").write_text("console.log('ok')", encoding="utf-8")
    return dist


def test_build_release_creates_source_visible_layout(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    version = _project_version(repo_root)
    output = tmp_path / "release"
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_release.py"),
            "--runtime-dir", str(_runtime(tmp_path)),
            "--web-dist-dir", str(_web_dist(tmp_path)),
            "--output-dir", str(output),
            "--target-arch", _arch(),
            "--git-commit", "abc123test",
            "--build-time", "2026-09-17T06:00:00+00:00",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    assert Path(result.stdout.strip()) == output / "release-manifest.json"
    manifest = json.loads((output / "release-manifest.json").read_text(encoding="utf-8"))
    assert manifest["release_version"] == version
    assert manifest["target_arch"] == _arch()
    assert manifest["source_path"] == "source/src"
    assert manifest["web_dist_path"] == "web-dist"
    assert manifest["deployment_mode"] == "native-source"
    assert manifest["git_commit"] == "abc123test"
    assert len(manifest["runtime_manifest_sha256"]) == 64
    assert len(manifest["source_tree_sha256"]) == 64
    assert len(manifest["web_tree_sha256"]) == 64
    assert (output / "runtime/runtime-manifest.json").is_file()
    assert (output / "source/src/material_matcher/cli.py").is_file()
    assert (output / "source/web/package.json").is_file()
    assert (output / "source/scripts/build_release.py").is_file()
    assert (output / "source/installer/install.sh").is_file()
    assert (output / "source/docker/compose.yaml").is_file()
    assert (output / "source/pyproject.toml").is_file()
    assert (output / "web-dist/index.html").is_file()
    assert (output / "tools/rebuild_frontend.sh").is_file()
    build_info = json.loads((output / "web-dist/build-info.json").read_text(encoding="utf-8"))
    assert build_info["version"] == version
    assert build_info["git_commit"] == "abc123test"
    assert build_info["deployment_mode"] == "native-source"

    help_result = subprocess.run(
        [str(output / "runtime/bin/material-matcher"), "--help"],
        text=True,
        capture_output=True,
    )
    assert help_result.returncode == 0
    assert "material-matcher" in help_result.stdout


def test_build_release_rejects_version_mismatch(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_release.py"),
            "--runtime-dir", str(_runtime(tmp_path)),
            "--web-dist-dir", str(_web_dist(tmp_path)),
            "--output-dir", str(tmp_path / "release"),
            "--release-version", "99.99.99",
            "--target-arch", _arch(),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "与项目版本" in result.stderr


def test_build_release_rejects_tampered_runtime(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    runtime = _runtime(tmp_path)
    (runtime / "bin/python3").write_text("#!/bin/sh\nexit 0\n# tampered\n", encoding="utf-8")
    (runtime / "bin/python3").chmod(0o755)
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_release.py"),
            "--runtime-dir", str(runtime),
            "--web-dist-dir", str(_web_dist(tmp_path)),
            "--output-dir", str(tmp_path / "release"),
            "--target-arch", _arch(),
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "摘要不一致" in result.stderr
