from __future__ import annotations

from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[1]
INSTALLER = REPO / "installer"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_bundle_entry_files_exist() -> None:
    for name in (
        "install.sh",
        "install_wizard.sh",
        "launch_install.sh",
        "maintain.sh",
        "mmctl",
        "desktop_install.desktop",
        "desktop_maintain.desktop",
        "README_first.txt",
        "docs/install-manual.md",
        "docs/maintain-manual.md",
        "docs/troubleshooting.md",
    ):
        assert (INSTALLER / name).is_file(), name


def test_install_sh_prefers_bundle_bootstrap_python() -> None:
    text = read(INSTALLER / "install.sh")
    assert "bootstrap/python/bin/python3" in text
    assert 'RUNTIME_DIR_NAME="${MM_PYTHON_RUNTIME_DIR:-runtime}"' in text
    # 系统 python3 仅允许作为最后的 fallback（出现在 resolve_python 候选列表末位）。
    assert re.search(r'command -v python3 >', text)


def test_wizard_steps_match_manual_contract() -> None:
    wizard = read(INSTALLER / "install_wizard.sh")
    manual = read(INSTALLER / "docs/install-manual.md")
    for label in ("欢迎", "环境检查", "安装位置", "数据位置", "服务端口", "管理员密码", "确认安装", "安装成功"):
        assert label in wizard, label
        assert label in manual, label
    assert "18080" in wizard and "18080" in manual
    assert "/opt/material_matcher" in wizard and "/opt/material_matcher" in manual
    # 手册不得要求普通用户直接 sudo ./install.sh。
    assert "sudo ./install.sh" not in manual


def test_desktop_entries_point_to_launch_script() -> None:
    assert "启动安装.sh" in read(INSTALLER / "desktop_install.desktop")
    assert "维护工具.sh" in read(INSTALLER / "desktop_maintain.desktop")
    readme = read(INSTALLER / "README_first.txt")
    assert "安装物料集团码智能匹配平台" in readme
    assert "启动安装.sh" in readme


def test_business_error_exit_codes_contract() -> None:
    text = read(INSTALLER / "install.sh")
    for const in ("EXIT_PORT=40", "EXIT_MEDIA=41", "EXIT_DISK=42", "EXIT_DB=45", "EXIT_DOCTOR=46"):
        assert const in text


def test_mmctl_covers_maintenance_contract() -> None:
    text = read(INSTALLER / "mmctl")
    for cmd in ("status", "start", "stop", "restart", "logs", "doctor", "version", "backup", "verify", "restore", "export", "rebuild-frontend"):
        assert cmd in text
    maintain = read(INSTALLER / "maintain.sh")
    assert "查看状态" in maintain and "备份数据" in maintain and "导出诊断包" in maintain


def test_installer_smoke_is_stdlib_only() -> None:
    text = read(REPO / "scripts/installer_smoke.py")
    assert not re.search(r"^\s*(import|from)\s+(httpx|requests)\b", text, re.MULTILINE)
    for step in ("STEP1", "STEP2", "STEP3", "STEP4"):
        assert step in text


def test_verify_requires_final_media_entries() -> None:
    text = read(INSTALLER / "verify_offline_bundle.py")
    for entry in ("启动安装.sh", "install_wizard.sh", "bootstrap/python/bin/python3", "BUILD_INFO.txt", "SHA256SUMS", "git_commit"):
        assert entry in text


def test_builder_plan_covers_manual_layout() -> None:
    text = read(REPO / "scripts/build_offline_bundle.py")
    for target in ("启动安装.sh", "安装物料集团码智能匹配平台.desktop", "docs/安装手册.md", "README-安装前必读.txt"):
        assert target in text
    # 根目录不出现开发仓库噪音：builder 只复制计划内文件。
    assert "git clone" not in text
