from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tomllib


def _project_version(repo_root: Path) -> str:
    with (repo_root / "pyproject.toml").open("rb") as stream:
        return str(tomllib.load(stream)["project"]["version"])


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _tree_sha256(root: Path, *, exclude_names: set[str] | None = None) -> str:
    excluded = exclude_names or set()
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file() and not item.is_symlink()):
        if path.name in excluded:
            continue
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_sha256(path).encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _write(path: Path, content: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if executable:
        path.chmod(0o755)


def _staging(tmp_path: Path, repo_root: Path) -> tuple[Path, Path, Path]:
    release = tmp_path / "release-stage"
    runtime = release / "runtime"
    source = release / "source"
    web = release / "web-dist"
    model = tmp_path / "model-stage"
    wheelhouse = tmp_path / "wheelhouse-stage"
    version = _project_version(repo_root)

    _write(runtime / "bin/python3", b"#!/bin/sh\nexit 0\n", executable=True)
    _write(runtime / "bin/material-matcher", b"#!/bin/sh\nexit 0\n", executable=True)
    runtime_manifest = {
        "format_version": 1,
        "product": "MATERIAL_MATCHER_PYTHON_RUNTIME",
        "target_arch": "x86_64",
        "python_version": "3.11.0",
        "dependencies": [],
        "runtime_tree_sha256": _tree_sha256(runtime, exclude_names={"runtime-manifest.json"}),
    }
    runtime_manifest_path = runtime / "runtime-manifest.json"
    runtime_manifest_path.write_text(json.dumps(runtime_manifest), encoding="utf-8")

    _write(source / "pyproject.toml", f'[project]\nname="material-matcher"\nversion="{version}"\n'.encode())
    _write(source / "src/material_matcher/__init__.py", b"from material_matcher.version import get_version\n__version__=get_version()\n")
    _write(source / "src/material_matcher/version.py", b"def get_version(): return 'test'\n")
    _write(source / "web/package.json", b'{"name":"material-matcher-web"}')
    _write(source / "scripts/build_release.py", b"# builder source\n")
    _write(source / "installer/install.sh", b"#!/bin/sh\n", executable=True)
    _write(source / "docker/compose.yaml", b"services: {}\n")
    _write(web / "index.html", b"<html>matcher</html>")
    _write(web / "build-info.json", json.dumps({"version": version, "deployment_mode": "native-source"}).encode())

    release_manifest_path = release / "release-manifest.json"
    release_manifest_path.write_text(
        json.dumps(
            {
                "format_version": 1,
                "product": "MATERIAL_MATCHER_RELEASE",
                "release_version": version,
                "target_arch": "x86_64",
                "python_version": "3.11.0",
                "runtime_manifest_sha256": _sha256(runtime_manifest_path),
                "source_tree_sha256": _tree_sha256(source),
                "web_tree_sha256": _tree_sha256(web),
                "source_path": "source/src",
                "web_dist_path": "web-dist",
                "deployment_mode": "native-source",
                "git_commit": "test-commit",
                "build_time": "2026-09-17T06:00:00+00:00",
            }
        ),
        encoding="utf-8",
    )
    _write(model / "tokenizer.json", b"{}")
    _write(model / "model_int8.onnx", b"fake-onnx-model")
    _write(wheelhouse / "onnxruntime-1.20.0-cp311-cp311-manylinux_x86_64.whl", b"fake-wheel")
    _write(wheelhouse / "tokenizers-0.20.0-cp311-cp311-manylinux_x86_64.whl", b"fake-wheel")
    return release, model, wheelhouse


def _build(repo_root: Path, tmp_path: Path) -> Path:
    release, model, wheelhouse = _staging(tmp_path, repo_root)
    output = tmp_path / "bundle"
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(output),
            "--target-arch", "x86_64",
        ],
        check=True,
    )
    return output


def test_offline_bundle_build_and_verify_source_visible_media(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    version = _project_version(repo_root)
    bundle = _build(repo_root, tmp_path)
    manifest = json.loads((bundle / "offline-manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["release_version"] == version
    for required in (
        "install.sh",
        "install_wizard.sh",
        "启动安装.sh",
        "安装物料集团码智能匹配平台.desktop",
        "release/release-manifest.json",
        "release/runtime/runtime-manifest.json",
        "release/source/pyproject.toml",
        "release/source/src/material_matcher/__init__.py",
        "release/source/web/package.json",
        "release/web-dist/index.html",
        "release/web-dist/build-info.json",
    ):
        assert required in paths

    verified = subprocess.run(
        [sys.executable, str(bundle / "verify_offline_bundle.py"), str(bundle), "--skip-arch"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(verified.stdout)
    assert payload["ok"] is True
    assert payload["release_version"] == version


def test_offline_bundle_rejects_tampering_and_untracked_files(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    (bundle / "models/BAAI/bge-base-zh-v1.5/model_int8.onnx").write_bytes(b"tampered")
    tampered = subprocess.run(
        [sys.executable, str(bundle / "verify_offline_bundle.py"), str(bundle), "--skip-arch"],
        text=True,
        capture_output=True,
    )
    assert tampered.returncode == 2
    assert "校验失败" in tampered.stderr

    bundle = _build(repo_root, tmp_path / "second")
    (bundle / "unexpected.txt").write_text("not in manifest", encoding="utf-8")
    unexpected = subprocess.run(
        [sys.executable, str(bundle / "verify_offline_bundle.py"), str(bundle), "--skip-arch"],
        text=True,
        capture_output=True,
    )
    assert unexpected.returncode == 2
    assert "未登记文件" in unexpected.stderr


def test_offline_bundle_rejects_release_version_mismatch(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release, model, wheelhouse = _staging(tmp_path, repo_root)
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "bundle"),
            "--release-version", "9.9.9",
            "--target-arch", "x86_64",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "版本" in result.stderr


def test_offline_bundle_rejects_release_tree_tampering(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release, model, wheelhouse = _staging(tmp_path, repo_root)
    (release / "web-dist/index.html").write_text("tampered web", encoding="utf-8")
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "tampered-release"),
            "--target-arch", "x86_64",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "Release 前端" in result.stderr or "SHA-256" in result.stderr


def test_offline_bundle_rejects_unsafe_model_id(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release, model, wheelhouse = _staging(tmp_path, repo_root)
    unsafe = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "unsafe"),
            "--target-arch", "x86_64",
            "--model-id", "../escape",
        ],
        text=True,
        capture_output=True,
    )
    assert unsafe.returncode == 2
    assert "安全的相对路径" in unsafe.stderr
