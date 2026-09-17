from __future__ import annotations

import json
from pathlib import Path

from material_matcher.services.profile_service import ProfileService
from material_matcher.services.task_service import TaskService, UNNAMED_SCHEME
from material_matcher.storage.metadata import MetadataRepository


def _document() -> dict[str, object]:
    return {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": "desc",
                "source": {"fields": ["物料描述"], "combine": "concat", "separator": " ", "pipeline": []},
                "target": {"fields": ["集团描述"], "combine": "concat", "separator": " ", "pipeline": []},
                "matcher": "fuzzy",
                "weight": 100,
                "critical": False,
            }
        ],
        "decision": {"success_threshold": 88, "review_enabled": True, "review_threshold": 75, "top_n": 5},
        "retrieval": {"mode": "auto", "retrieval_top_k": 200, "oversample": 4},
    }


def _start_profile_task(meta: MetadataRepository, internal_name: str = "SMOKE-1.1.5") -> tuple[TaskService, ProfileService, str, str]:
    profiles = ProfileService(meta)
    tasks = TaskService(meta)
    profile_id = str(profiles.create("电子元器件集团码匹配方案", _document())["profile_id"])
    published = profiles.publish(profile_id)
    document = dict(published["document"])
    document["advanced"] = {
        **dict(document.get("advanced") or {}),
        "template_source": {"profile_id": profile_id, "version_no": int(published["version_no"])},
    }
    draft = tasks.create_draft(internal_name)
    tasks.save_rules(str(draft["draft_id"]), document)
    tasks.save_data(
        str(draft["draft_id"]),
        {"source_file_id": "source-1", "catalog_version_id": "catalog-v1"},
    )
    task = tasks.start(str(draft["draft_id"]), actor="operator")
    return tasks, profiles, profile_id, str(task["task_id"])


def test_task_exposes_business_scheme_name_without_replacing_internal_name(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    tasks, _, _, task_id = _start_profile_task(meta)

    task = tasks.get_task(task_id)
    assert task["name"] == "SMOKE-1.1.5"
    assert task["scheme_name"] == "电子元器件集团码匹配方案"
    assert task["config_snapshot"]["advanced"]["scheme_display_name"] == "电子元器件集团码匹配方案"
    assert task["created_by"] == "operator"
    assert task["started_by"] == "operator"

    listed = next(item for item in tasks.list_tasks() if item["task_id"] == task_id)
    assert listed["name"] == "SMOKE-1.1.5"
    assert listed["scheme_name"] == "电子元器件集团码匹配方案"


def test_scheme_name_is_frozen_when_profile_is_renamed_after_start(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    tasks, profiles, profile_id, task_id = _start_profile_task(meta)

    profiles.rename(profile_id, "后来改过的方案名称")

    task = tasks.get_task(task_id)
    assert task["scheme_name"] == "电子元器件集团码匹配方案"
    assert task["config_snapshot"]["advanced"]["scheme_display_name"] == "电子元器件集团码匹配方案"


def test_legacy_task_uses_current_profile_name_only_when_no_frozen_name_exists(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    tasks, profiles, profile_id, task_id = _start_profile_task(meta)
    task = tasks.get_task(task_id)
    snapshot = dict(task["config_snapshot"])
    advanced = dict(snapshot.get("advanced") or {})
    advanced.pop("scheme_display_name", None)
    snapshot["advanced"] = advanced
    with meta.connect() as connection:
        connection.execute(
            "UPDATE tasks SET config_snapshot=? WHERE task_id=?",
            (json.dumps(snapshot, ensure_ascii=False), task_id),
        )

    profiles.rename(profile_id, "历史兼容方案名")
    legacy = tasks.get_task(task_id)
    assert legacy["scheme_name"] == "历史兼容方案名"
    assert legacy["name"] == "SMOKE-1.1.5"


def test_legacy_task_without_any_scheme_source_uses_business_friendly_fallback(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    tasks = TaskService(meta)
    draft = tasks.create_draft("run-technical-001")
    tasks.save_rules(str(draft["draft_id"]), _document())
    tasks.save_data(
        str(draft["draft_id"]),
        {"source_file_id": "source-1", "catalog_version_id": "catalog-v1"},
    )
    task = tasks.start(str(draft["draft_id"]))
    task_id = str(task["task_id"])
    snapshot = dict(task["config_snapshot"])
    advanced = dict(snapshot.get("advanced") or {})
    advanced.pop("scheme_display_name", None)
    snapshot["advanced"] = advanced
    with meta.connect() as connection:
        connection.execute(
            "UPDATE tasks SET profile_id=NULL, profile_version=NULL, config_snapshot=? WHERE task_id=?",
            (json.dumps(snapshot, ensure_ascii=False), task_id),
        )

    legacy = tasks.get_task(task_id)
    assert legacy["scheme_name"] == UNNAMED_SCHEME
    assert legacy["scheme_name"] != legacy["name"]
    assert legacy["name"] == "run-technical-001"
