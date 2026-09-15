from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


def _write(path: Path, content: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if executable:
        path.chmod(0o755)


def _staging(tmp_path: Path) -> tuple[Path, Path, Path]:
    release = tmp_path / "release-stage"
    model = tmp_path / "model-stage"
    wheelhouse = tmp_path / "wheelhouse-stage"
    _write(release / "runtime/bin/python3", b"#!/bin/sh\nexit 0\n", executable=True)
    _write(release / "runtime/bin/material-matcher", b"#!/bin/sh\nexit 0\n", executable=True)
    _write(release / "web/dist/index.html", b"<html>matcher</html>")
    _write(model / "tokenizer.json", b"{}")
    _write(model / "model_int8.onnx", b"fake-onnx-model")
    _write(wheelhouse / "onnxruntime-1.20.0-cp311-cp311-manylinux_x86_64.whl", b"fake-wheel")
    _write(wheelhouse / "tokenizers-0.20.0-cp311-cp311-manylinux_x86_64.whl", b"fake-wheel")
    return release, model, wheelhouse


def _build(repo_root: Path, tmp_path: Path, *, release_version: str = "0.7.0", model_id: str = "BAAI/bge-base-zh-v1.5") -> Path:
    release, model, wheelhouse = _staging(tmp_path)
    output = tmp_path / "bundle"
    subprocess.run(
        [
            sys.executable,
            str(repo_root / "scripts/build_offline_bundle.py"),
            "--release-dir", str(release),
            "--model-dir", str(model),
            "--wheelhouse-dir", str(wheelhouse),
            "--output-dir", str(output),
            "--release-version", release_version,
            "--target-arch", "x86_64",
            "--model-id", model_id,
        ],
        check=True,
    )
    return output


def _verify(bundle: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(bundle / "verify_offline_bundle.py"), str(bundle), "--skip-arch"],
        text=True,
        capture_output=True,
    )


def test_offline_bundle_build_and_verify(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    manifest = json.loads((bundle / "offline-manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["release_version"] == "0.7.0"
    assert "release/runtime/bin/material-matcher" in paths
    assert "release/web/dist/index.html" in paths
    assert "models/BAAI/bge-base-zh-v1.5/tokenizer.json" in paths
    assert "models/BAAI/bge-base-zh-v1.5/model_int8.onnx" in paths

    verified = _verify(bundle)
    assert verified.returncode == 0
    assert json.loads(verified.stdout)["ok"] is True


def test_offline_bundle_rejects_tampering_and_untracked_files(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    model = bundle / "models/BAAI/bge-base-zh-v1.5/model_int8.onnx"
    model.write_bytes(b"tampered")
    tampered = _verify(bundle)
    assert tampered.returncode == 2
    assert "校验失败" in tampered.stderr

    bundle = _build(repo_root, tmp_path / "second")
    (bundle / "unexpected.txt").write_text("not in manifest", encoding="utf-8")
    unexpected = _verify(bundle)
    assert unexpected.returncode == 2
    assert "未登记文件" in unexpected.stderr


def test_offline_bundle_rejects_unsafe_manifest_and_wrong_native_arch(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    manifest_path = bundle / "offline-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    manifest["release_version"] = "../../escape"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unsafe_version = _verify(bundle)
    assert unsafe_version.returncode == 2
    assert "release_version" in unsafe_version.stderr

    bundle = _build(repo_root, tmp_path / "second")
    manifest_path = bundle / "offline-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["model_id"] = "../escape"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    unsafe_model = _verify(bundle)
    assert unsafe_model.returncode == 2
    assert "非法离线包路径" in unsafe_model.stderr

    bundle = _build(repo_root, tmp_path / "third")
    manifest_path = bundle / "offline-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["target_arch"] = "aarch64"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    wrong_wheel = _verify(bundle)
    assert wrong_wheel.returncode == 2
    assert "aarch64" in wrong_wheel.stderr
    assert "onnxruntime" in wrong_wheel.stderr


def test_offline_bundle_rejects_non_executable_runtime(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    bundle = _build(repo_root, tmp_path)
    launcher = bundle / "release/runtime/bin/material-matcher"
    launcher.chmod(0o644)
    result = _verify(bundle)
    assert result.returncode == 2
    assert "可执行" in result.stderr


def test_builder_rejects_path_injection_and_overlapping_output(tmp_path: Path) -> None:
    repo_root = Path(__file__).resolve().parents[1]
    release, model, wheelhouse = _staging(tmp_path)
    base = [
        sys.executable,
        str(repo_root / "scripts/build_offline_bundle.py"),
        "--release-dir", str(release),
        "--model-dir", str(model),
        "--wheelhouse-dir", str(wheelhouse),
        "--target-arch", "x86_64",
    ]
    unsafe = subprocess.run(
        base + ["--output-dir", str(tmp_path / "bundle"), "--release-version", "../bad"],
        text=True,
        capture_output=True,
    )
    assert unsafe.returncode == 2
    assert "release_version" in unsafe.stderr

    overlap = subprocess.run(
        base + ["--output-dir", str(release / "bundle"), "--release-version", "0.8.0"],
        text=True,
        capture_output=True,
    )
    assert overlap.returncode == 2
    assert "重叠" in overlap.stderr
