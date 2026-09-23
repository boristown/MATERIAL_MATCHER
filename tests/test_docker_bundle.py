from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[1]


def _version() -> str:
    return (REPO / "src/material_matcher/VERSION").read_text(encoding="utf-8").strip()


def _write(path: Path, content: bytes, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    if executable:
        path.chmod(0o755)


def _bootstrap(tmp_path: Path) -> Path:
    bootstrap = tmp_path / "bootstrap-stage"
    _write(bootstrap / "bin/python3", b"#!/bin/sh\nexit 0\n", executable=True)
    _write(bootstrap / "lib/stdlib.txt", b"fake\n")
    return bootstrap


def _release(tmp_path: Path) -> Path:
    release = tmp_path / "release-stage"
    _write(release / "source/pyproject.toml", b"[project]\n")
    _write(release / "source/web/package.json", b"{}\n")
    (release / "release-manifest.json").write_text(json.dumps({
        "format_version": 1,
        "product": "MATERIAL_MATCHER_RELEASE",
        "release_version": _version(),
        "target_arch": "x86_64",
    }), encoding="utf-8")
    return release


def test_docker_bundle_build_and_verify(tmp_path: Path) -> None:
    seed = tmp_path / "seed"
    seed.mkdir(parents=True)
    (seed / "manifest.json").write_text(json.dumps({
        "format_version": 1,
        "product": "MATERIAL_MATCHER_BUSINESS_SEED",
        "source_db_sha256": "a" * 64,
        "exported_at": "2026-01-01T00:00:00+00:00",
        "profiles": [
            {"profile_id": f"{i:032x}", "name": name, "published_versions": [1], "latest_document_sha256": "b" * 64}
            for i, name in enumerate(["A001 元器件", "A002 标准紧固件", "A003 金属材料", "A005 非金属材料", "A006 复合材料", "A007 物资类其他(跨类目)"])
        ],
        "dictionaries": [{"dictionary_id": "c" * 32, "name": "物料同义词表", "versions": [1], "rule_counts": {"1": 3}}],
    }, ensure_ascii=False), encoding="utf-8")
    (seed / "profiles.json").write_text(json.dumps({"format_version": 1, "profiles": []}), encoding="utf-8")
    (seed / "dictionaries.json").write_text(json.dumps({"format_version": 1, "dictionaries": []}), encoding="utf-8")

    image_tar = tmp_path / "fake-image.tar"
    image_tar.write_bytes(b"fake-docker-save-stream")
    engine = tmp_path / "docker-27.1.1.tgz"
    engine.write_bytes(b"fake-engine")
    compose = tmp_path / "docker-compose-linux-x86_64"
    _write(compose, b"#!/bin/sh\nexit 0\n", executable=True)

    output = tmp_path / "01-docker"
    subprocess.run(
        [
            sys.executable, str(REPO / "scripts/build_docker_bundle.py"),
            "--output-dir", str(output),
            "--release-dir", str(_release(tmp_path)),
            "--seed-dir", str(seed),
            "--image-tar", str(image_tar),
            "--image-ref", f"material-matcher-app:{_version()}",
            "--image-id", "sha256:" + "d" * 64,
            "--engine-tgz", str(engine),
            "--compose-bin", str(compose),
            "--bootstrap-runtime-dir", str(_bootstrap(tmp_path)),
            "--target-arch", "x86_64",
            "--git-commit", "e" * 40,
            "--seed-source-db-sha256", "a" * 64,
        ],
        check=True,
    )
    manifest = json.loads((output / "docker-manifest.json").read_text(encoding="utf-8"))
    paths = {item["path"] for item in manifest["files"]}
    assert manifest["product"] == "MATERIAL_MATCHER_DOCKER_BUNDLE"
    assert manifest["release_version"] == _version()
    assert f"版本: {_version()}" in (output / "BUILD_INFO.txt").read_text(encoding="utf-8")
    for required in (
        "run.sh", "docker_wizard.sh", "install_docker.sh", "menu.sh",
        "docker/engine/docker-27.1.1.tgz", "docker/compose/docker-compose-linux-x86_64",
        "images/fake-image.tar", "seed/business/manifest.json", "smoke/smoke-待匹配数据.xlsx",
        "doc.md", "BUILD_INFO.txt", "SHA256SUMS",
    ):
        assert required in paths, required
    verified = subprocess.run(
        [sys.executable, str(output / "verify_docker_bundle.py"), str(output), "--skip-arch"],
        check=True, text=True, capture_output=True,
    )
    payload = json.loads(verified.stdout)
    assert payload["ok"] is True and payload["image_ref"] == f"material-matcher-app:{_version()}"


def test_docker_bundle_rejects_tampering(tmp_path: Path) -> None:
    test_docker_bundle_build_and_verify(tmp_path / "first")
    bundle = tmp_path / "first" / "01-docker"
    engine = bundle / "docker/engine/docker-27.1.1.tgz"
    engine.write_bytes(b"tampered-engine")
    result = subprocess.run(
        [sys.executable, str(bundle / "verify_docker_bundle.py"), str(bundle), "--skip-arch"],
        text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert "校验失败" in result.stderr or "SHA-256" in result.stderr


def test_docker_bundle_requires_six_seed_profiles(tmp_path: Path) -> None:
    test_docker_bundle_build_and_verify(tmp_path / "ok")
    bundle = tmp_path / "ok" / "01-docker"
    seed = json.loads((bundle / "seed/business/manifest.json").read_text(encoding="utf-8"))
    seed["profiles"] = seed["profiles"][:5]
    (bundle / "seed/business/manifest.json").write_text(json.dumps(seed, ensure_ascii=False), encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(bundle / "verify_docker_bundle.py"), str(bundle), "--skip-arch"],
        text=True, capture_output=True,
    )
    assert result.returncode == 2
    assert ("6" in result.stderr) or ("校验失败" in result.stderr)


def test_final_media_layout_scripts_exist() -> None:
    assert (REPO / "scripts/build_final_media.py").is_file()
    text = (REPO / "scripts/build_final_media.py").read_text(encoding="utf-8")
    for marker in ('out / "d"', 'out / "n"', 'out / "win7"', "all.sha256", "二选一"):
        assert marker in text
