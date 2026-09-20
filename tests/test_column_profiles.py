from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from material_matcher.ingestion.column_profile import profile_tabular_columns


def _upload_csv(client: TestClient, content: str) -> dict[str, object]:
    response = client.post(
        "/api/files/upload",
        data={"role": "source"},
        files={"file": ("字段模板.csv", content.encode("utf-8"), "text/csv")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_profile_tabular_columns_detects_generic_enum_candidate(tmp_path: Path) -> None:
    path = tmp_path / "template.csv"
    path.write_text(
        "物料编码,国产进口,物料名称\n"
        "M001,10,电阻\n"
        "M002,11,电容\n"
        "M003,10,二极管\n"
        "M004,11,继电器\n"
        "M005,10,电机\n"
        "M006,11,轴承\n"
        "M007,10,螺母\n"
        "M008,11,螺栓\n",
        encoding="utf-8",
    )

    profile = profile_tabular_columns(path)
    by_name = {item["field_name"]: item for item in profile["columns"]}

    enum_field = by_name["国产进口"]
    assert enum_field["datatype"] == "INTEGER"
    assert enum_field["unique_count"] == 2
    assert enum_field["sample_values"] == ["10", "11"]
    assert enum_field["top_values"] == [
        {"value": "10", "count": 4},
        {"value": "11", "count": 4},
    ]
    assert enum_field["enum_candidate"] is True

    assert by_name["物料编码"]["unique_count"] == 8
    assert by_name["物料编码"]["enum_candidate"] is False
    assert by_name["物料名称"]["enum_candidate"] is False


def test_profile_preserves_leading_zero_codes_as_text(tmp_path: Path) -> None:
    path = tmp_path / "codes.csv"
    path.write_text("编码\n001\n002\n003\n", encoding="utf-8")

    profile = profile_tabular_columns(path)
    column = profile["columns"][0]

    assert column["datatype"] == "TEXT"
    assert column["sample_values"] == ["001", "002", "003"]


def test_upload_and_column_values_api_expose_column_profile(authed: TestClient) -> None:
    uploaded = _upload_csv(
        authed,
        "物料编码,国产进口,物料名称\n"
        "M001,10,电阻\n"
        "M002,11,电容\n"
        "M003,10,二极管\n"
        "M004,11,继电器\n"
        "M005,10,电机\n"
        "M006,11,轴承\n",
    )
    inspection = uploaded["inspection"]
    columns = inspection["sheets"][0]["columns"]
    enum_column = next(item for item in columns if item["header"] == "国产进口")

    assert enum_column["field_name"] == "国产进口"
    assert enum_column["datatype"] == "INTEGER"
    assert enum_column["unique_count"] == 2
    assert enum_column["sample_values"] == ["10", "11"]
    assert enum_column["enum_candidate"] is True
    assert inspection["column_profile"]["sheet_name"] == "CSV"

    file_id = uploaded["file"]["file_id"]
    profiled = authed.get(f"/api/files/{file_id}/column-profiles")
    assert profiled.status_code == 200, profiled.text
    profile_by_name = {item["field_name"]: item for item in profiled.json()["columns"]}
    assert profile_by_name["国产进口"]["top_values"] == [
        {"value": "10", "count": 3},
        {"value": "11", "count": 3},
    ]

    values = authed.get(
        f"/api/files/{file_id}/column-values",
        params={"field_name": "国产进口"},
    )
    assert values.status_code == 200, values.text
    assert values.json()["enum_candidate"] is True
    assert values.json()["values"] == ["10", "11"]
    assert values.json()["top_values"] == [
        {"value": "10", "count": 3},
        {"value": "11", "count": 3},
    ]


def test_column_values_api_rejects_unknown_field(authed: TestClient) -> None:
    uploaded = _upload_csv(
        authed,
        "编码,类型\n001,A\n002,B\n",
    )
    file_id = uploaded["file"]["file_id"]

    response = authed.get(
        f"/api/files/{file_id}/column-values",
        params={"field_name": "不存在字段"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "COLUMN_NOT_FOUND"
