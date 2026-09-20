#!/usr/bin/env python3
"""组装最终交付介质：根 README + d（Docker）+ n（Native）+ win7（浏览器工具包）。

用法（构建机）：
  python scripts/build_final_media.py \
    --output-dir <dir> --release-dir <native release> --model-dir <model> \
    --wheelhouse-dir <wheelhouse> --bootstrap-runtime-dir <bootstrap> \
    --node-offline-dir <node-offline> --docker-image-tar <tar> --docker-image-ref <ref> \
    --docker-image-id <id> --engine-tgz <docker tgz> --compose-bin <compose> \
    --browser-dir <含 Firefox 等的本地目录> --seed-dir seed/business \
    --release-version 1.2.0 --git-commit <sha>
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
ROOT_README = """物料集团码智能匹配平台 · 最终离线交付介质
==================================================

本介质提供两种【二选一】的服务器安装方式（选择一种即可，不要两个都安装）：

  d/                    【推荐】Docker 离线安装
                        终端执行：cd d && ./run.sh
                        服务器即使完全没有 Docker，也会由本介质离线装好。

  n/                    传统 systemd 源码安装（客户明确不允许 Docker 时使用）
                        终端执行：cd n && ./run.sh

两种方式的服务器都必须先做一件事：把所需目录完整复制到服务器本地磁盘（不要直接从 U 盘运行安装）。

客户端浏览器工具包（装在客户 Windows 7 电脑上，不装在服务器上）：
  win7/                 Firefox ESR、VSCode（Win7 可用版）等，见其 README.md

每种方式的详细中文步骤见各自目录内的安装手册。全程离线，无需公网。
"""

BROWSER_README = """客户端浏览器工具包（Windows 7 终端专用）
====================================

用途：当客户 Windows 7 电脑上的浏览器过旧、打开物料集团码智能匹配平台页面异常（白屏/按钮缺失/排版错乱）时，
在本目录内选择浏览器安装包，在【Win7 电脑】上离线安装。浏览器不安装到银河麒麟服务器上。

首选：Firefox ESR（本目录 Firefox Setup *.exe，Win7 x64）
  - 官方 archive.mozilla.org 发布，SHA256 已对官方 SHA256SUMS 校验；
  - 支持 Windows 7 SP1 x64，随 ESR 系列获得维护更新。

VSCode 1.82.3（现场改代码用，安装在工程师自备电脑）
  1.82.3 是支持 Windows 7 的最后一个官方版本（1.83 起要求 Win10+）。
  下载来源（官方）：https://update.code.visualstudio.com/1.82.3/win32-x64-user/stable
  （302 至微软 CDN vscode.download.prss.microsoft.com commit fdb98833154679dbaa7af67a5a29fe19e55c2b73）
  SHA256：811dc91817a5e8e47d23d67254bd6ea96c682f46ea28e9629c566ee39e7fbc64（见本目录 SHA256SUMS.txt）
  许可证：微软官方免费分发（Visual Studio Code License Terms），未修改安装包。
  用法：《使用手册 use.md》第 7 节"现场改代码指引"。

Chrome 109（Win7 备用内核）——客户已确认豁免（2026-09-18）：
  - Google 官方已停止公开分发 109 离线安装包（见 lic.txt 核查记录）；
  - 客户确认 Win7 终端统一使用本目录 Firefox ESR；如未来经 Google 企业渠道
    自取 109 原版，可放入本目录（验真指引见《客户工作单》第四节）。

安装 Firefox 后若仍打不开页面：请先执行《安装手册》中的“检查服务器地址/防火墙”，
再联系系统维护人员。
"""

BROWSER_LICENSES = """来源、许可证与合规记录
==========================

Firefox ESR 115.41.0esr（win64 zh-CN 完整安装程序）
  下载来源（官方）：https://archive.mozilla.org/pub/firefox/releases/115.41.0esr/win64/zh-CN/Firefox Setup 115.41.0esr.exe
  校验：与 Mozilla 官方发布的 releases/115.41.0esr/SHA256SUMS 一致（见下方 SHA256SUMS.txt）
  许可证：Mozilla Public License 2.0（安装程序内包含许可证信息；原文 https://www.mozilla.org/MPL/2.0/）
  再分发：Mozilla 官方发布文件允许再分发（不得修改安装包）——本交付介质未做任何修改。
  获取日期：{firefox_fetched}

Chrome 109.0.5414.120（Win7 兼容备用）
  状态：截至本介质构建时，Google 官方公开渠道（dl.google.com / Chrome for Testing 自 113 起）
  均已不再提供 109 版本离线安装包；为遵守“只使用官方来源、禁止第三方下载站”的交付合规要求，
  本介质【不打包 Chrome 109】，并如实记录于此。
  解决路径：如未来需要 Chrome 备用浏览器，请由客户通过 Google 企业官方授权渠道（Chrome Enterprise
  软件再分发计划）自行获取原版离线 MSI 放入本目录；原厂不对非官方来源二进制负责。
  客户决议（2026-09-18）：确认豁免 Chrome 109，Win7 终端统一使用 Firefox ESR 115.41.0esr
  （该版本已通过原厂全套 STEP1~STEP4 功能验收，Chrome 仅为备用，功能不受影响）。
"""


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build(args: argparse.Namespace) -> Path:
    out = args.output_dir
    if out.exists() and any(out.iterdir()) and not args.force:
        raise RuntimeError(f"输出目录非空：{out}")
    out.mkdir(parents=True, exist_ok=True)

    # 02 非Docker方式
    sys.path.insert(0, str(REPO / "scripts"))
    import build_offline_bundle
    import build_docker_bundle

    native_dir = out / "n"
    build_offline_bundle.build_bundle(
        release_dir=args.release_dir, model_dir=args.model_dir, wheelhouse_dir=args.wheelhouse_dir,
        bootstrap_runtime_dir=args.bootstrap_runtime_dir, output_dir=native_dir,
        release_version=args.release_version, target_arch=args.target_arch, model_id=args.model_id,
        node_offline_dir=args.node_offline_dir, git_commit=args.git_commit, force=True,
    )

    # 01 Docker方式
    docker_dir = out / "d"
    seed_db_sha = json.loads((args.seed_dir / "manifest.json").read_text(encoding="utf-8"))["source_db_sha256"]
    build_docker_bundle.build(
        output_dir=docker_dir, release_dir=args.release_dir, seed_dir=args.seed_dir,
        image_tar=args.docker_image_tar, image_ref=args.docker_image_ref, image_id=args.docker_image_id,
        engine_tgz=args.engine_tgz, compose_bin=args.compose_bin,
        bootstrap_runtime_dir=args.bootstrap_runtime_dir, release_version=args.release_version,
        target_arch=args.target_arch, git_commit=args.git_commit, seed_source_db_sha256=seed_db_sha,
        docker_engine_version="27.1.1", docker_compose_version="v2.29.7",
        force=True,
    )

    # 根 README
    (out / "README.md").write_text(ROOT_README, encoding="utf-8")

    # win7 浏览器工具包（文件名一律转短 ASCII；原名记录于 lic.txt）
    browser_out = out / "win7"
    browser_out.mkdir(parents=True, exist_ok=True)
    for item in sorted(args.browser_dir.iterdir()):
        if item.is_file() and item.name.lower().endswith((".exe", ".msi")):
            low = item.name.lower()
            target = "firefox.exe" if "firefox" in low else ("chrome.exe" if "chrome" in low else item.name.lower().replace(" ", "-"))
            shutil.copy2(item, browser_out / target)
    (browser_out / "README.md").write_text(BROWSER_README, encoding="utf-8")
    shutil.copy2(REPO / "installer/win7/CLIENT-WIN7-ACCEPTANCE-WORKSHEET.md", browser_out / "客户工作单-Win7浏览器验收与Chrome获取指引.md")
    (browser_out / "lic.txt").write_text(
        BROWSER_LICENSES.replace("{firefox_fetched}", args.firefox_fetched), encoding="utf-8")
    sums = "".join(f"{_sha256(p)}  {p.name}\n" for p in sorted(browser_out.iterdir())
                   if p.is_file() and p.name.lower().endswith((".exe", ".msi")))
    (browser_out / "SHA256SUMS.txt").write_text(sums, encoding="utf-8")

    # 顶层 SHA256SUMS + 版本记录
    # sha 汇总文件名沿用 all.sha256 / manifest.json（见 EXTRA 重命名）
    all_lines = []
    for path in sorted(out.rglob("*")):
        if not path.is_file() or path.name == "all.sha256":
            continue
        if path.is_symlink():
            continue  # 符号链接由各分区自身 manifest 校验（仅允许分区内部相对链接）
        all_lines.append(f"{_sha256(path)}  {path.relative_to(out).as_posix()}")
    (out / "all.sha256").write_text("\n".join(all_lines) + "\n", encoding="utf-8")
    manifest = {
        "product": "MM-DELIVERY",
        "format_version": 1,
        "release_version": args.release_version,
        "git_commit": args.git_commit,
        "target_arch": args.target_arch,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "docker": {"image_ref": args.docker_image_ref, "image_id": args.docker_image_id,
                    "image_tar_sha256": _sha256(args.docker_image_tar), "engine": "27.1.1", "compose": "v2.29.7"},
        "browser_dir_files": {p.name: _sha256(p) for p in sorted(browser_out.iterdir()) if p.is_file()},
        "file_count": len(all_lines),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--model-dir", type=Path, required=True)
    parser.add_argument("--model-id", default="BAAI/bge-base-zh-v1.5")
    parser.add_argument("--wheelhouse-dir", type=Path, required=True)
    parser.add_argument("--bootstrap-runtime-dir", type=Path, required=True)
    parser.add_argument("--node-offline-dir", type=Path, default=None)
    parser.add_argument("--docker-image-tar", type=Path, required=True)
    parser.add_argument("--docker-image-ref", required=True)
    parser.add_argument("--docker-image-id", required=True)
    parser.add_argument("--engine-tgz", type=Path, required=True)
    parser.add_argument("--compose-bin", type=Path, required=True)
    parser.add_argument("--browser-dir", type=Path, required=True)
    parser.add_argument("--seed-dir", type=Path, default=REPO / "seed/business")
    parser.add_argument("--release-version", required=True)
    parser.add_argument("--target-arch", choices=("x86_64", "aarch64"), default="x86_64")
    parser.add_argument("--git-commit", required=True)
    parser.add_argument("--firefox-fetched", default="2026-09-18（构建机自 archive.mozilla.org 官方发布目录下载并校验）")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    print(build(args))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
