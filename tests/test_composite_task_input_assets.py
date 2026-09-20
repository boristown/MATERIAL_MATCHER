from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json

from fastapi.testclient import TestClient
from openpyxl import Workbook


def _xlsx(headers: list[str], rows: list[list[str]], sheet_name: str) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = sheet_name
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    workbook.close()
    return output.getvalue()


def _upload(client: TestClient, name: str, payload: bytes, role: str = "target") -> dict[str, object]:
    response = client.post(
        "/api/files/upload",
        data={"role": role},
        files={"file": (name, payload, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )
    assert response.status_code == 200, response.text
    return response.json()["file"]


def _catalog(
    client: TestClient,
    *,
    name: str,
    file_id: str,
    group_code_column: str,
) -> dict[str, object]:
    response = client.post(
        "/api/catalogs",
        json={
            "name": name,
            "source_file_id": file_id,
            "group_code_column": group_code_column,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def _seed_published_profile(
    client: TestClient,
    *,
    profile_id: str,
    name: str,
    document: dict[str, object],
    version_no: int = 1,
) -> None:
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = sha256(encoded.encode("utf-8")).hexdigest()
    now = "2026-09-20T11:19:00+08:00"
    meta = client.app.state.meta
    with meta.connect() as connection:
        connection.execute(
            "INSERT INTO profiles(profile_id,name,created_at) VALUES(?,?,?)",
            (profile_id, name, now),
        )
        connection.execute(
            """INSERT INTO profile_versions(
                   profile_id,version_no,document,sha256,status,created_at
               ) VALUES(?,?,?,?,?,?)""",
            (profile_id, version_no, encoded, digest, "PUBLISHED", now),
        )


def _single_document(target_field: str) -> dict[str, object]:
    return {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [
            {
                "id": f"rule_{target_field}",
                "source": {"fields": ["物料名称"]},
                "target": {"fields": [target_field]},
                "matcher": "fuzzy",
                "weight": 100,
            }
        ],
        "decision": {
            "success_threshold": 80,
            "review_enabled": True,
            "review_threshold": 50,
            "top_n": 2,
        },
        "retrieval": {"mode": "scan", "retrieval_top_k": 10, "oversample": 2},
        "advanced": {"profile_kind": "single"},
    }


def _seed_composite_profiles(client: TestClient) -> dict[str, object]:
    children = [
        ("P1", "电气类方案", "名称"),
        ("P2", "标准件方案", "规格"),
        ("P3", "辅材方案", "描述"),
    ]
    for profile_id, name, target_field in children:
        _seed_published_profile(
            client,
            profile_id=profile_id,
            name=name,
            document=_single_document(target_field),
        )
    parent_document = {
        "source_id_column": "物料号",
        "scope_mode": "GLOBAL",
        "rules": [],
        "decision": {
            "success_threshold": 80,
            "review_enabled": True,
            "review_threshold": 50,
            "top_n": 2,
        },
        "retrieval": {"mode": "scan", "retrieval_top_k": 10, "oversample": 2},
        "advanced": {
            "profile_kind": "composite",
            "composite_children": [
                {"profile_id": profile_id, "version_no": 1}
                for profile_id, _, _ in children
            ],
        },
    }
    _seed_published_profile(
        client,
        profile_id="PCOMP",
        name="A007 跨类目组合方案",
        document=parent_document,
    )
    return parent_document


def test_composite_draft_freezes_three_heterogeneous_targets_and_keeps_history(
    authed: TestClient,
) -> None:
    parent_document = _seed_composite_profiles(authed)

    source_bytes = _xlsx(
        ["物料号", "物料名称", "物料类型"],
        [["A007001", "六角螺栓", "A007"], ["A007002", "绝缘胶带", "A007"]],
        "SAP_A007",
    )
    source = _upload(authed, "SAP_A007.xlsx", source_bytes, role="source")

    target_payloads = {
        "P1": _xlsx(
            ["集团码", "名称"],
            [["G-E-001", "六角螺栓"]],
            "电气目录",
        ),
        "P2": _xlsx(
            ["CODE", "规格", "品牌"],
            [["G-S-001", "M8×30", "标准件厂"]],
            "标准件_2026",
        ),
        "P3": _xlsx(
            ["GC", "描述", "类别", "单位"],
            [["G-A-001", "PVC绝缘胶带", "辅材", "卷"]],
            "Sheet_辅材",
        ),
    }
    target_files = {
        profile_id: _upload(authed, f"{profile_id}_集团目录.xlsx", payload)
        for profile_id, payload in target_payloads.items()
    }
    catalogs = {
        "P1": _catalog(
            authed,
            name="电气目录",
            file_id=str(target_files["P1"]["file_id"]),
            group_code_column="集团码",
        ),
        "P2": _catalog(
            authed,
            name="标准件目录",
            file_id=str(target_files["P2"]["file_id"]),
            group_code_column="CODE",
        ),
        "P3": _catalog(
            authed,
            name="辅材目录",
            file_id=str(target_files["P3"]["file_id"]),
            group_code_column="GC",
        ),
    }

    draft = authed.post("/api/task-drafts", json={}).json()
    draft_id = str(draft["draft_id"])
    initial = authed.patch(
        f"/api/task-drafts/{draft_id}",
        json={
            "source_file_id": source["file_id"],
            "template_profile_id": "PCOMP",
            "template_profile_version": 1,
            "config_document": parent_document,
        },
    )
    assert initial.status_code == 200, initial.text
    seeded = initial.json()["composite_targets"]
    assert [(item["profile_id"], item["version_no"]) for item in seeded] == [
        ("P1", 1),
        ("P2", 1),
        ("P3", 1),
    ]
    assert all(item["catalog_version_id"] is None for item in seeded)
    assert initial.json()["catalog_version_id"] is None

    incomplete_bindings = [
        {
            "profile_id": profile_id,
            "version_no": 1,
            "catalog_version_id": catalogs[profile_id]["version_id"] if profile_id != "P3" else None,
        }
        for profile_id in ("P1", "P2", "P3")
    ]
    saved_incomplete = authed.patch(
        f"/api/task-drafts/{draft_id}",
        json={"composite_targets": incomplete_bindings},
    )
    assert saved_incomplete.status_code == 200, saved_incomplete.text
    refused = authed.post(f"/api/task-drafts/{draft_id}/start")
    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "TASK_DRAFT_INCOMPLETE"

    complete_bindings = [
        {
            "profile_id": profile_id,
            "version_no": 1,
            "catalog_version_id": catalogs[profile_id]["version_id"],
        }
        for profile_id in ("P1", "P2", "P3")
    ]
    saved = authed.put(
        f"/api/task-drafts/{draft_id}/data",
        json={
            "source_file_id": source["file_id"],
            "template_profile_id": "PCOMP",
            "template_profile_version": 1,
            "composite_targets": complete_bindings,
        },
    )
    assert saved.status_code == 200, saved.text

    restored = authed.get(f"/api/task-drafts/{draft_id}")
    assert restored.status_code == 200
    restored_body = restored.json()
    assert restored_body["source_file_id"] == source["file_id"]
    assert restored_body["catalog_version_id"] is None
    assert restored_body["composite_targets"] == complete_bindings

    started = authed.post(f"/api/task-drafts/{draft_id}/start")
    assert started.status_code == 202, started.text
    task = started.json()
    task_id = str(task["task_id"])

    runtime_map = task["config_snapshot"]["advanced"]["composite_run"]
    assert runtime_map == complete_bindings
    frozen_snapshot = task["config_snapshot"]["advanced"]["input_assets"]
    assert set(frozen_snapshot) == {"source", "target.P1", "target.P2", "target.P3"}
    for profile_id in ("P1", "P2", "P3"):
        snapshot = frozen_snapshot[f"target.{profile_id}"]
        assert snapshot["profile_id"] == profile_id
        assert snapshot["profile_version"] == 1
        assert snapshot["catalog_version_id"] == catalogs[profile_id]["version_id"]
        assert snapshot["file_id"] == target_files[profile_id]["file_id"]

    with authed.app.state.meta.connect() as connection:
        rows = connection.execute(
            """SELECT asset_role,file_id,catalog_version_id,profile_id,profile_version
               FROM task_input_assets WHERE task_id=? ORDER BY rowid""",
            (task_id,),
        ).fetchall()
    assert len(rows) == 4
    assert [row["asset_role"] for row in rows] == [
        "source",
        "target.P1",
        "target.P2",
        "target.P3",
    ]
    assert [
        (row["profile_id"], row["profile_version"], row["catalog_version_id"])
        for row in rows[1:]
    ] == [
        ("P1", 1, catalogs["P1"]["version_id"]),
        ("P2", 1, catalogs["P2"]["version_id"]),
        ("P3", 1, catalogs["P3"]["version_id"]),
    ]

    assets_response = authed.get(f"/api/tasks/{task_id}/input-assets")
    assert assets_response.status_code == 200
    assets = assets_response.json()
    assert assets["composite"] is True
    assert assets["target"] is None
    assert assets["source"]["original_name"] == "SAP_A007.xlsx"
    assert [item["profile_id"] for item in assets["targets"]] == ["P1", "P2", "P3"]
    assert [item["profile_name"] for item in assets["targets"]] == ["电气类方案", "标准件方案", "辅材方案"]
    exposed = json.dumps(assets, ensure_ascii=False)
    assert '"file_id"' not in exposed
    assert '"stored_path"' not in exposed

    assert authed.get(f"/api/tasks/{task_id}/input-files/source").content == source_bytes
    for profile_id, original_payload in target_payloads.items():
        download = authed.get(f"/api/tasks/{task_id}/input-files/targets/{profile_id}")
        assert download.status_code == 200
        assert download.content == original_payload

    # Later uploads/catalog versions and even editing the old draft must not change
    # the exact bytes frozen into the historical task.
    replacement_catalogs: dict[str, dict[str, object]] = {}
    group_code_columns = {"P1": "集团码", "P2": "CODE", "P3": "GC"}
    for profile_id, catalog in catalogs.items():
        group_code_column = group_code_columns[profile_id]
        replacement = _xlsx(
            [group_code_column, "新版字段", "额外列"],
            [[f"NEW-{profile_id}", "后来上传的数据", "x"]],
            f"新版_{profile_id}",
        )
        replacement_file = _upload(authed, f"{profile_id}_集团目录.xlsx", replacement)
        response = authed.post(
            f"/api/catalogs/{catalog['catalog_id']}/versions",
            json={
                "source_file_id": replacement_file["file_id"],
                "group_code_column": group_code_column,
                "activate": True,
            },
        )
        assert response.status_code == 200, response.text
        replacement_catalogs[profile_id] = response.json()

    replaced_draft = authed.patch(
        f"/api/task-drafts/{draft_id}",
        json={
            "composite_targets": [
                {
                    "profile_id": profile_id,
                    "version_no": 1,
                    "catalog_version_id": replacement_catalogs[profile_id]["version_id"],
                }
                for profile_id in ("P1", "P2", "P3")
            ]
        },
    )
    assert replaced_draft.status_code == 200, replaced_draft.text

    for profile_id, original_payload in target_payloads.items():
        historical = authed.get(f"/api/tasks/{task_id}/input-files/targets/{profile_id}")
        assert historical.status_code == 200
        assert historical.content == original_payload

    # Composite tasks deliberately do not pretend that one child target is the
    # single authoritative target. The legacy target endpoint remains for normal tasks.
    legacy_target = authed.get(f"/api/tasks/{task_id}/input-files/target")
    assert legacy_target.status_code == 404


def test_composite_target_download_requires_exact_frozen_child(authed: TestClient) -> None:
    response = authed.get("/api/tasks/not-a-task/input-files/targets/P1")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ORIGINAL_FILE_UNAVAILABLE"
