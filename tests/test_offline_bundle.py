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

    _write(release / "web/dist/index.html", b"<html>matcher</html>")
    (release / "release-manifest.json").write_text(
        json.dumps(
            {
                "format_version": 1,
                "product": "MATERIAL_MATCHER_RELEASE",
                "release_version": version,
                "target_arch": "x86_64",
                "python_version": "3.11.0",
                "runtime_manifest_sha256": _sha256(runtime_manifest_path),
                "source_tree_sha256": "a" * 64,
                "web_tree_sha256": "b" * 64,
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
            "--release-version", _project_version(repo_root),
            "--target-arch", "x86_64",
        ],
        check=True,
    )
    return output


def test_offline_bundle_build_and_verify(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    version = _project_version(repo_root)
    bundle = _build(repo_root, tmp_path)
    manifest = json.loads((bundle / "offline-manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["release_version"] == version
    assert len(manifest["release_manifest_sha256"]) == 64
    assert "release/release-manifest.json" in paths
    assert "release/runtime/runtime-manifest.json" in paths
    assert "release/runtime/bin/material-matcher" in paths
    assert "release/web/dist/index.html" in paths
    assert "models/BAAI/bge-base-zh-v1.5/tokenizer.json" in paths
    assert "models/BAAI/bge-base-zh-v1.5/model_int8.onnx" in paths

    verified = subprocess.run(
        [sys.executable, str(bundle / "verify_offline_bundle.py"), str(bundle), "--skip-arch"],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(verified.stdout)
    assert payload["ok"] is True
    assert payload["release_version"] == version
    assert payload["python_version"] == "3.11.0"


def test_offline_bundle_rejects_tampering_and_untracked_files(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    model = bundle / "models/BAAI/bge-base-zh-v1.5/model_int8.onnx"
    model.write_bytes(b"tampered")
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
    release_manifest_path = release / "release-manifest.json"
    release_manifest = json.loads(release_manifest_path.read_text(encoding="utf-8"))
    release_manifest["release_version"] = "9.9.9"
    release_manifest_path.write_text(json.dumps(release_manifest), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "bundle"),
            "--release-version", _project_version(repo_root),
            "--target-arch", "x86_64",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "版本" in result.stderr


def test_offline_bundle_rejects_runtime_manifest_tampering(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release, model, wheelhouse = _staging(tmp_path, repo_root)
    runtime_python = release / "runtime/bin/python3"
    runtime_python.write_bytes(b"#!/bin/sh\nexit 1\n")
    runtime_python.chmod(0o755)
    result = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "tampered-runtime"),
            "--release-version", _project_version(repo_root),
            "--target-arch", "x86_64",
        ],
        text=True,
        capture_output=True,
    )
    assert result.returncode == 2
    assert "Runtime 文件" in result.stderr or "SHA-256" in result.stderr


def test_offline_bundle_rejects_unsafe_model_id_and_arch_wheel(tmp_path: Path) -> None:
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
            "--release-version", _project_version(repo_root),
            "--target-arch", "x86_64",
            "--model-id", "../escape",
        ],
        text=True,
        capture_output=True,
    )
    assert unsafe.returncode == 2
    assert "安全的相对路径" in unsafe.stderr

    (wheelhouse / "onnxruntime-1.20.0-cp311-cp311-manylinux_x86_64.whl").unlink()
    (wheelhouse / "onnxruntime-1.20.0-cp311-cp311-manylinux_aarch64.whl").write_bytes(b"wrong-arch")
    wrong_arch = subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(tmp_path / "wrong-arch"),
            "--release-version", _project_version(repo_root),
            "--target-arch", "x86_64",
        ],
        text=True,
        capture_output=True,
    )
    assert wrong_arch.returncode == 2
    assert "onnxruntime wheel" in wrong_arch.stderr
