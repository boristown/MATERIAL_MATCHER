from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any

from material_matcher.domain.errors import DomainError
from material_matcher.storage.metadata import MetadataRepository


def _canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _sha(value: object) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


class BusinessSeedService:
    """默认业务基础数据（匹配方案 + 同义词表）的幂等导入。

    语义（安装手册 7.1 合同）：
    - 首次安装：系统中不存在对应配置（按 id 或名称判断）时导入 seed 的全部已发布版本；
    - 重复运行/修复：已存在（id 或同名）→ 整个对象跳过，绝不重复生成同名配置；
    - 升级：客户已修改/发布的方案与同义词版本绝不被覆盖；
    - seed 只含业务配置，不含用户/会话/任务/文件数据。
    """

    def __init__(self, metadata: MetadataRepository) -> None:
        self.meta = metadata

    @staticmethod
    def _load(seed_dir: Path, name: str) -> dict[str, Any]:
        path = seed_dir / name
        if not path.is_file():
            raise DomainError("SEED_MISSING", f"业务 seed 缺少 {name}", status_code=500)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("format_version") != 1:
            raise DomainError("SEED_FORMAT", f"{name} 格式版本不受支持", status_code=500)
        return payload

    def import_seed(self, seed_dir: Path) -> dict[str, object]:
        seed_dir = Path(seed_dir)
        manifest = self._load(seed_dir, "manifest.json")
        if manifest.get("product") != "MATERIAL_MATCHER_BUSINESS_SEED":
            raise DomainError("SEED_FORMAT", "seed manifest 产品标识不正确", status_code=500)
        profiles_payload = self._load(seed_dir, "profiles.json")
        dictionaries_payload = self._load(seed_dir, "dictionaries.json")

        result: dict[str, list[str]] = {"dictionaries_imported": [], "dictionaries_skipped": [], "profiles_imported": [], "profiles_skipped": []}
        with self.meta.connect() as connection:
            for dictionary in dictionaries_payload["dictionaries"]:
                if self._dictionary_present(connection, dictionary):
                    result["dictionaries_skipped"].append(str(dictionary["name"]))
                    continue
                self._insert_dictionary(connection, dictionary)
                result["dictionaries_imported"].append(str(dictionary["name"]))
            for profile in profiles_payload["profiles"]:
                if self._profile_present(connection, profile):
                    result["profiles_skipped"].append(str(profile["name"]))
                    continue
                self._insert_profile(connection, profile)
                result["profiles_imported"].append(str(profile["name"]))
        return {
            "ok": True,
            "seed_exported_at": manifest.get("exported_at"),
            **{key: sorted(value) for key, value in result.items()},
            "counts": {
                "dictionaries_imported": len(result["dictionaries_imported"]),
                "dictionaries_skipped": len(result["dictionaries_skipped"]),
                "profiles_imported": len(result["profiles_imported"]),
                "profiles_skipped": len(result["profiles_skipped"]),
            },
        }

    @staticmethod
    def _dictionary_present(connection: Any, dictionary: dict[str, Any]) -> bool:
        row = connection.execute(
            "SELECT 1 FROM dictionaries WHERE dictionary_id=? OR name=?",
            (str(dictionary["dictionary_id"]), str(dictionary["name"])),
        ).fetchone()
        return row is not None

    @staticmethod
    def _profile_present(connection: Any, profile: dict[str, Any]) -> bool:
        row = connection.execute(
            "SELECT 1 FROM profiles WHERE profile_id=? OR name=?",
            (str(profile["profile_id"]), str(profile["name"])),
        ).fetchone()
        return row is not None

    @staticmethod
    def _insert_dictionary(connection: Any, dictionary: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO dictionaries VALUES(?,?,?)",
            (str(dictionary["dictionary_id"]), str(dictionary["name"]), str(dictionary["created_at"])),
        )
        for version in dictionary["versions"]:
            document = {"mapping": deepcopy(dict(version["document"]["mapping"])), "case_sensitive": bool(version["document"].get("case_sensitive", True))}
            connection.execute(
                "INSERT INTO dictionary_versions(dictionary_id,version_no,document,sha256,created_at,created_by) VALUES(?,?,?,?,?,?)",
                (
                    str(dictionary["dictionary_id"]),
                    int(version["version_no"]),
                    _canonical(document),
                    _sha(document),
                    str(version["created_at"]),
                    str(version.get("created_by") or "business-seed"),
                ),
            )

    @staticmethod
    def _insert_profile(connection: Any, profile: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO profiles VALUES(?,?,?)",
            (str(profile["profile_id"]), str(profile["name"]), str(profile["created_at"])),
        )
        for version in profile["versions"]:
            document = deepcopy(version["document"])
            connection.execute(
                "INSERT INTO profile_versions(profile_id,version_no,document,sha256,status,created_at) VALUES(?,?,?,?,?,?)",
                (
                    str(profile["profile_id"]),
                    int(version["version_no"]),
                    _canonical(document),
                    _sha(document),
                    str(version["status"]),
                    str(version["created_at"]),
                ),
            )
