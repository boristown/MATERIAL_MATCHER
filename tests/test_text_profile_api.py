from __future__ import annotations

from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook

from material_matcher.embedding.providers import DeterministicEmbeddingProvider


def _xlsx(headers: list[str], rows: list[list[str]]) -> bytes:
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(headers)
    for row in rows:
        sheet.append(row)
    output = BytesIO()
    workbook.save(output)
    return output.getvalue()


def test_task_text_profile_uses_actual_draft_files_and_retrieval_config(authed: TestClient) -> None:
    authed.app.state.matches.indexes.provider_factory = lambda _settings, _config: DeterministicEmbeddingProvider(32)

    source = authed.post(
        "/api/files/upload",
        data={"role": "source"},
        files={
            "file": (
                "source.xlsx",
                _xlsx(
                    ["物料号", "物料名称", "型号"],
                    [
                        ["0001", "工业电阻", "LONG-MODEL-XXXXXXXXXXXXXXXXXXXXXXXX"],
                        ["0002", "工业电阻", "R10"],
                        ["0003", "工业电容", "C10"],
                    ],
                ),
                "application/octet-stream",
            )
        },
    ).json()
    target = authed.post(
        "/api/files/upload",
        data={"role": "target"},
        files={
            "file": (
                "target.xlsx",
                _xlsx(
                    ["集团码", "物料名称", "型号"],
                    [
                        ["G001", "工业电阻", "LONG-MODEL-XXXXXXXXXXXXXXXXXXXXXXXX"],
                        ["G002", "工业电阻", "R10"],
                        ["G003", "工业电容", "C10"],
                    ],
                ),
                "application/octet-stream",
            )
        },
    ).json()
    catalog = authed.post(
        "/api/catalogs",
        json={"name": "集团目录", "source_file_id": target["file"]["file_id"], "group_code_column": "集团码"},
    ).json()
    draft = authed.post("/api/task-drafts", json={"name": "画像测试"}).json()
    authed.put(
        f"/api/task-drafts/{draft['draft_id']}/data",
        json={"source_file_id": source["file"]["file_id"], "catalog_version_id": catalog["version_id"]},
    )
    rules = {
        "source_id_column": "物料号",
        "rules": [
            {
                "id": "main",
                "source": {"fields": ["物料名称", "型号"], "combine": "concat"},
                "target": {"fields": ["物料名称", "型号"], "combine": "concat"},
                "matcher": "fuzzy",
                "weight": 100,
            }
        ],
        "retrieval": {
            "max_length": 16,
            "source": {"fields": ["物料名称", "型号"], "combine": "concat"},
            "target": {"fields": ["物料名称", "型号"], "combine": "concat"},
        },
    }
    assert authed.put(f"/api/task-drafts/{draft['draft_id']}/rules", json=rules).status_code == 200

    response = authed.post(
        f"/api/task-drafts/{draft['draft_id']}/text-profile",
        json={"sample_rows": 64, "scan_limit": 1000},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["provider"]["provider"] == "deterministic_test"
    assert body["current_max_length"] == 16
    assert body["recommendation_is_advisory"] is True
    assert body["source"]["scan_complete"] is True
    assert body["target"]["scan_complete"] is True
    assert body["source"]["sampled_rows"] == 3
    assert body["target"]["sampled_rows"] == 3
    assert body["source"]["current_truncation_rate"] > 0
    assert body["target"]["current_truncation_rate"] > 0
    assert body["recommended_max_length"] in {128, 192, 256, 512}
