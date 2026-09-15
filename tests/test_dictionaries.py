from __future__ import annotations

from pathlib import Path

import pytest

from material_matcher.domain.errors import DomainError
from material_matcher.services.dictionary_service import DictionaryService
from material_matcher.services.task_service import TaskService
from material_matcher.storage.metadata import MetadataRepository


def _config(dictionary_id: str, version_no: int) -> dict[str, object]:
    return {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "desc",
                "source": {
                    "fields": ["物料描述"],
                    "combine": "concat",
                    "separator": " ",
                    "pipeline": [
                        {
                            "op": "dictionary_map",
                            "options": {
                                "dictionary_id": dictionary_id,
                                "version_no": version_no,
                                "mode": "replace",
                            },
                        }
                    ],
                },
                "target": {"fields": ["集团描述"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 100,
                "critical": False,
            }
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "scan", "retrieval_top_k": 200, "oversample": 4},
    }


def test_dictionary_versions_are_immutable_and_runtime_materialization_is_versioned(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = DictionaryService(meta)
    created = service.create("材质同义词", {"mapping": {"SUS304": "304不锈钢"}, "case_sensitive": False})
    dictionary_id = str(created["dictionary_id"])
    assert created["latest"]["version_no"] == 1

    v2 = service.add_version(dictionary_id, {"mapping": {"SUS304": "不锈钢304", "SUS316": "316不锈钢"}})
    assert v2["version_no"] == 2
    assert service.version(dictionary_id, 1)["document"]["mapping"]["SUS304"] == "304不锈钢"

    bound = service.bind_references(_config(dictionary_id, 1))
    options = bound["rules"][0]["source"]["pipeline"][0]["options"]
    assert options["dictionary_sha256"] == service.version(dictionary_id, 1)["sha256"]
    assert options["mapping"]["SUS304"] == "304不锈钢"
    assert options["case_sensitive"] is False


def test_dictionary_reference_rejects_missing_or_tampered_version(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = DictionaryService(meta)
    created = service.create("规格映射", {"mapping": {"M8": "8mm"}})
    dictionary_id = str(created["dictionary_id"])

    with pytest.raises(DomainError) as exc:
        service.bind_references(_config(dictionary_id, 99))
    assert exc.value.code == "DICTIONARY_VERSION_NOT_FOUND"

    document = _config(dictionary_id, 1)
    document["rules"][0]["source"]["pipeline"][0]["options"]["dictionary_sha256"] = "bad"
    with pytest.raises(DomainError) as exc:
        service.bind_references(document)
    assert exc.value.code == "DICTIONARY_VERSION_CHANGED"


def test_task_draft_and_snapshot_freeze_dictionary_version_content(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    dictionaries = DictionaryService(meta)
    tasks = TaskService(meta)
    created = dictionaries.create("品牌规范", {"mapping": {"ABB LTD": "ABB"}})
    dictionary_id = str(created["dictionary_id"])

    draft = tasks.create_draft("字典任务")
    saved = tasks.save_rules(str(draft["draft_id"]), _config(dictionary_id, 1))
    options = saved["config_document"]["rules"][0]["source"]["pipeline"][0]["options"]
    assert options["dictionary_id"] == dictionary_id
    assert options["version_no"] == 1
    assert options["mapping"] == {"ABB LTD": "ABB"}
    frozen_sha = options["dictionary_sha256"]

    dictionaries.add_version(dictionary_id, {"mapping": {"ABB LTD": "ABB GROUP"}})
    saved_again = tasks.get_draft(str(draft["draft_id"]))
    options_again = saved_again["config_document"]["rules"][0]["source"]["pipeline"][0]["options"]
    assert options_again["dictionary_sha256"] == frozen_sha
    assert options_again["mapping"] == {"ABB LTD": "ABB"}
