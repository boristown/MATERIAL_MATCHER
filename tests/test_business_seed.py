from __future__ import annotations

from pathlib import Path

import pytest

from material_matcher.services.business_seed import BusinessSeedService
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository

REPO = Path(__file__).resolve().parents[1]
SEED_DIR = REPO / "seed" / "business"
EXPECTED_PROFILES = ["A001 元器件", "A002 标准紧固件", "A003 金属材料", "A005 非金属材料", "A006 复合材料", "A007 物资类其他(跨类目)"]


@pytest.fixture()
def meta(tmp_path: Path) -> MetadataRepository:
    return MetadataRepository(tmp_path / "meta.db")


def _names(meta: MetadataRepository) -> list[str]:
    return sorted(str(item["name"]) for item in ProfileService(meta).list())


def test_real_seed_manifest_covers_six_official_profiles() -> None:
    import json

    manifest = json.loads((SEED_DIR / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["product"] == "MATERIAL_MATCHER_BUSINESS_SEED"
    assert sorted(item["name"] for item in manifest["profiles"]) == EXPECTED_PROFILES
    assert len(manifest["dictionaries"]) == 1
    dictionary = manifest["dictionaries"][0]
    assert dictionary["versions"] == [1, 2, 3]
    assert dictionary["rule_counts"]["3"] >= 30
    assert manifest.get("source_db_sha256") and manifest.get("exported_at")


def test_seed_import_is_idempotent_and_preserves_all_versions(meta: MetadataRepository) -> None:
    service = BusinessSeedService(meta)
    first = service.import_seed(SEED_DIR)
    assert first["ok"] is True
    assert first["counts"]["profiles_imported"] == 6
    assert first["counts"]["dictionaries_imported"] == 1
    assert _names(meta) == sorted(EXPECTED_PROFILES)

    second = service.import_seed(SEED_DIR)
    assert second["counts"]["profiles_imported"] == 0
    assert second["counts"]["profiles_skipped"] == 6
    assert second["counts"]["dictionaries_skipped"] == 1
    assert _names(meta) == sorted(EXPECTED_PROFILES)

    profiles = ProfileService(meta)
    a002 = next(item for item in profiles.list() if str(item["name"]).startswith("A002"))
    detail = profiles.get(str(a002["profile_id"]))
    assert int(detail["latest_published"]["version_no"]) == 3
    dictionaries = DictionaryService(meta)
    versions = dictionaries.versions(str(dictionaries.list()[0]["dictionary_id"]))
    assert sorted(int(v["version_no"]) for v in versions) == [1, 2, 3]


def test_seed_import_never_overwrites_customer_changes(meta: MetadataRepository) -> None:
    service = BusinessSeedService(meta)
    service.import_seed(SEED_DIR)
    profiles = ProfileService(meta)
    a001 = next(item for item in profiles.list() if str(item["name"]).startswith("A001"))
    profile_id = str(a001["profile_id"])
    detail = profiles.get(profile_id)
    document = detail["latest_published"]["document"]
    document["decision"]["success_threshold"] = 99
    profiles.save_draft(profile_id, document)
    profiles.publish(profile_id)
    before = profiles.get(profile_id)

    service.import_seed(SEED_DIR)  # 修复/重装再跑一次
    after = profiles.get(profile_id)
    assert after["latest_published"]["document"]["decision"]["success_threshold"] == 99
    assert after["latest_published"]["version_no"] == before["latest_published"]["version_no"]
    assert _names(meta) == sorted(EXPECTED_PROFILES)


def test_seed_import_rejects_missing_directory(tmp_path: Path, meta: MetadataRepository) -> None:
    from material_matcher.domain.errors import DomainError

    with pytest.raises(DomainError):
        BusinessSeedService(meta).import_seed(tmp_path / "nowhere")


def test_seed_presets_domestic_import_mapping_and_composite_a007() -> None:
    import json
    payload = json.loads((SEED_DIR / "profiles.json").read_text(encoding="utf-8"))
    by_prefix = {p["name"][:4]: p for p in payload["profiles"]}
    for prefix, profile in by_prefix.items():
        document = profile["versions"][-1]["document"]
        if isinstance(document, str):
            document = json.loads(document)
        if prefix == "A007":
            advanced = document["advanced"]
            assert advanced.get("profile_kind") == "composite"
            children = advanced["composite_children"]
            assert len(children) == 5
            ids = {p["profile_id"] for p in payload["profiles"]}
            for child in children:
                assert child["profile_id"] in ids
                assert child["profile_id"] != profile["profile_id"]
            continue
        # 1.3.16 修正：不再预置写死列名的国产进口规则（列名因表而异）
        assert all(r.get("id") != "seed-enum-gnjk" for r in document["rules"]), f"{prefix} 不应再包含写死预置规则"
