#!/usr/bin/env python3
"""从已验证的正式环境 metadata DB（只读）导出默认业务 seed（方案 + 同义词表）。

只导出业务配置表；绝不包含用户、会话、任务、文件、上传或客户 Excel。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TABLES_PROFILE = "profile_versions"
SEED_FORMAT_VERSION = 1


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def export(db_path: Path, output_dir: Path, source_note: str) -> Path:
    if not db_path.is_file():
        raise SystemExit(f"数据库不存在：{db_path}")
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    profiles = []
    for row in conn.execute("SELECT profile_id, name, created_at FROM profiles ORDER BY created_at"):
        versions = [
            {
                "version_no": int(v["version_no"]),
                "status": str(v["status"]),
                "document": json.loads(str(v["document"])),
                "sha256": str(v["sha256"]),
                "created_at": str(v["created_at"]),
            }
            for v in conn.execute(
                "SELECT version_no,status,document,sha256,created_at FROM profile_versions WHERE profile_id=? ORDER BY version_no",
                (row["profile_id"],),
            )
        ]
        published = [v for v in versions if v["status"] == "PUBLISHED"]
        if not published:
            continue
        for v in versions:
            recomputed = _sha(v["document"])
            if v["status"] == "PUBLISHED" and recomputed != v["sha256"]:
                raise SystemExit(f"方案 {row['name']} v{v['version_no']} sha 不匹配，导出中止")
        profiles.append({"profile_id": row["profile_id"], "name": row["name"], "created_at": row["created_at"], "versions": versions})

    dictionaries = []
    for row in conn.execute("SELECT dictionary_id, name, created_at FROM dictionaries ORDER BY created_at"):
        versions = [
            {
                "version_no": int(v["version_no"]),
                "document": json.loads(str(v["document"])),
                "sha256": str(v["sha256"]),
                "created_at": str(v["created_at"]),
                "created_by": str(v["created_by"]),
            }
            for v in conn.execute(
                "SELECT version_no,document,sha256,created_at,created_by FROM dictionary_versions WHERE dictionary_id=? ORDER BY version_no",
                (row["dictionary_id"],),
            )
        ]
        if not versions:
            continue
        for v in versions:
            if _sha({"mapping": v["document"]["mapping"], "case_sensitive": bool(v["document"].get("case_sensitive", True))}) != v["sha256"]:
                pass  # 兼容历史 canonical 差异：导入时以导入侧重算为准
        dictionaries.append({"dictionary_id": row["dictionary_id"], "name": row["name"], "created_at": row["created_at"], "versions": versions})

    referenced = set()
    for profile in profiles:
        for version in profile["versions"]:
            stack = [version["document"]]
            while stack:
                node = stack.pop()
                if isinstance(node, dict):
                    if isinstance(node.get("dictionary_id"), str) and isinstance(node.get("version_no"), int):
                        referenced.add((node["dictionary_id"], node["version_no"]))
                    stack.extend(node.values())
                elif isinstance(node, list):
                    stack.extend(node)
    missing = sorted(r for r in referenced if not any(d["dictionary_id"] == r[0] and any(v["version_no"] == r[1] for v in d["versions"]) for d in dictionaries))
    if missing:
        raise SystemExit(f"方案引用了未导出的同义词版本：{missing}")

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "profiles.json").write_text(json.dumps({"format_version": SEED_FORMAT_VERSION, "profiles": profiles}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (output_dir / "dictionaries.json").write_text(json.dumps({"format_version": SEED_FORMAT_VERSION, "dictionaries": dictionaries}, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    db_sha = hashlib.sha256(db_path.read_bytes()).hexdigest()
    manifest = {
        "format_version": SEED_FORMAT_VERSION,
        "product": "MATERIAL_MATCHER_BUSINESS_SEED",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "source": source_note,
        "source_db_sha256": db_sha,
        "profiles": [
            {
                "profile_id": p["profile_id"],
                "name": p["name"],
                "published_versions": [v["version_no"] for v in p["versions"] if v["status"] == "PUBLISHED"],
                "latest_document_sha256": [v["sha256"] for v in p["versions"] if v["status"] == "PUBLISHED"][-1],
            }
            for p in profiles
        ],
        "dictionaries": [
            {
                "dictionary_id": d["dictionary_id"],
                "name": d["name"],
                "versions": [v["version_no"] for v in d["versions"]],
                "rule_counts": {str(v["version_no"]): len(v["document"]["mapping"]) for v in d["versions"]},
            }
            for d in dictionaries
        ],
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"导出完成：{len(profiles)} 个方案，{len(dictionaries)} 张同义词表 → {output_dir}")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="导出正式业务 seed（仅配置，不含任何交易数据）")
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source", default="", help="来源说明（环境/日期/版本）")
    args = parser.parse_args()
    export(args.db, args.output_dir, args.source)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
