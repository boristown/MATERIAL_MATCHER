from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from openpyxl import Workbook

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


def test_profile_does_not_flag_constant_or_sparse_descriptive_columns_as_enum(tmp_path: Path) -> None:
    path = tmp_path / "descriptive.csv"
    path.write_text(
        "特殊说明,型号\n"
        "无,M1\n"
        "无,M1\n"
        "无,M2\n"
        "无,M3\n"
        "无,M4\n"
        "无,M5\n"
        "无,M5\n"
        "无,M5\n",
        encoding="utf-8",
    )

    profile = profile_tabular_columns(path)
    by_name = {item["field_name"]: item for item in profile["columns"]}

    # A constant column carries no useful mapping choice and should not surface
    # as an enum candidate in STEP1.
    assert by_name["特殊说明"]["unique_count"] == 1
    assert by_name["特殊说明"]["enum_candidate"] is False

    # Five values across only eight rows is weak evidence and previously caused
    # fields such as model/specification to show a misleading "candidate" hint.
    assert by_name["型号"]["unique_count"] == 5
    assert by_name["型号"]["enum_candidate"] is False


def test_profile_requires_repeated_evidence_for_tiny_enum_samples(tmp_path: Path) -> None:
    sparse = tmp_path / "sparse.csv"
    sparse.write_text("类型\n10\n11\n", encoding="utf-8")
    sparse_profile = profile_tabular_columns(sparse)
    assert sparse_profile["columns"][0]["enum_candidate"] is False

    repeated = tmp_path / "repeated.csv"
    repeated.write_text("类型\n10\n11\n10\n11\n", encoding="utf-8")
    repeated_profile = profile_tabular_columns(repeated)
    assert repeated_profile["columns"][0]["enum_candidate"] is True


def test_profile_rejects_more_than_ten_dictionary_values(tmp_path: Path) -> None:
    path = tmp_path / "too-many-enum-values.csv"
    rows = ["类型"]
    for _ in range(5):
        rows.extend(f"V{index:02d}" for index in range(1, 12))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")

    profile = profile_tabular_columns(path)
    column = profile["columns"][0]

    assert column["unique_count"] == 11
    assert column["enum_candidate"] is False


def test_profile_preserves_leading_zero_codes_as_text(tmp_path: Path) -> None:
    path = tmp_path / "codes.csv"
    path.write_text("编码\n001\n002\n003\n", encoding="utf-8")

    profile = profile_tabular_columns(path)
    column = profile["columns"][0]

    assert column["datatype"] == "TEXT"
    assert column["sample_values"] == ["001", "002", "003"]



def test_profile_tabular_columns_supports_xlsx(tmp_path: Path) -> None:
    path = tmp_path / "template.xlsx"
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "模板"
    worksheet.append(["物料编码", "来源类型"])
    for index, value in enumerate([10, 11, 10, 11], start=1):
        worksheet.append([f"M{index:03d}", value])
    workbook.save(path)

    profile = profile_tabular_columns(path)
    by_name = {item["field_name"]: item for item in profile["columns"]}

    assert profile["sheet_name"] == "模板"
    assert by_name["来源类型"]["datatype"] == "INTEGER"
    assert by_name["来源类型"]["unique_count"] == 2
    assert by_name["来源类型"]["enum_candidate"] is True

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
