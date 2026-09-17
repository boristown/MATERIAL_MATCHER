from __future__ import annotations

from pathlib import Path
import subprocess
import sys

FORBIDDEN_SUFFIXES = {
    ".docx", ".pdf", ".xlsx", ".xls", ".xlsm", ".png", ".jpg", ".jpeg",
    ".gif", ".zip", ".tar", ".gz", ".7z", ".rar", ".db", ".sqlite",
    ".sqlite3", ".onnx", ".pt", ".pth", ".bin", ".index", ".so", ".dll",
    ".exe", ".pyc",
}
FORBIDDEN_PARTS = {"node_modules", ".venv", "venv", "dist", "build", "runtime", "cache", "tmp"}
MAX_TEXT_BYTES = 5 * 1024 * 1024

# origin_data.zip is the project's canonical, intentionally versioned seed-data package.
# Keep the exception path-specific so arbitrary ZIP/binary artifacts remain rejected.
ALLOWED_BINARY_PATHS = {Path("origin_data.zip")}


def tracked_files() -> list[Path]:
    result = subprocess.run(["git", "ls-files", "-z"], check=True, capture_output=True)
    return [Path(item.decode()) for item in result.stdout.split(b"\0") if item]


def main() -> int:
    errors: list[str] = []
    for path in tracked_files():
        if any(part in FORBIDDEN_PARTS for part in path.parts):
            errors.append(f"禁止提交目录: {path}")
            continue
        if path.suffix.lower() in FORBIDDEN_SUFFIXES:
            if path not in ALLOWED_BINARY_PATHS:
                errors.append(f"禁止提交二进制/运行产物: {path}")
            continue
        if path.exists() and path.stat().st_size > MAX_TEXT_BYTES:
            errors.append(f"文本文件超过 5MB: {path}")
            continue
        if path.exists() and b"\x00" in path.read_bytes():
            errors.append(f"检测到 NUL 字节: {path}")
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print("repository file policy: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
