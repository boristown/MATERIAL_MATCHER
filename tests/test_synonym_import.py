from __future__ import annotations

import io

import openpyxl
from fastapi.testclient import TestClient


def _xlsx(header, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(header)
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _dictionary(authed: TestClient):
    created = authed.post("/api/dictionaries", json={"name": "导入测试表", "mapping": {"电阻": "电阻器"}, "case_sensitive": True}).json()
    return created["dictionary_id"]


def test_synonym_import_merge_reports_added_updated_skipped(authed):
    dictionary_id = _dictionary(authed)
    upload = authed.post(
        "/api/files/upload",
        data={"role": "supplement"},
        files={"file": ("syn.xlsx", _xlsx(["原始写法", "标准词"], [["电容", "电容器"], ["电阻", "电阻器"], ["电阻", "阻值"]]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()["file"]
    result = authed.post(
        f"/api/dictionaries/{dictionary_id}/synonyms/import",
        json={"file_id": upload["file_id"], "source_column": "原始写法", "target_column": "标准词", "mode": "merge"},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["added"] == 1 and body["updated"] == 1 and body["skipped"] == 1
    latest = authed.get(f"/api/dictionaries/{dictionary_id}").json()["latest"]
    assert latest["document"]["mapping"] == {"电阻": "阻值", "电容": "电容器"}


def test_synonym_import_replace_mode_keeps_history_version(authed):
    dictionary_id = _dictionary(authed)
    upload = authed.post(
        "/api/files/upload",
        data={"role": "supplement"},
        files={"file": ("syn.csv", "源,目标\n电感,电感器\n,\n".encode("utf-8"), "text/csv")},
    ).json()["file"]
    result = authed.post(
        f"/api/dictionaries/{dictionary_id}/synonyms/import",
        json={"file_id": upload["file_id"], "source_column": "源", "target_column": "目标", "mode": "replace"},
    )
    assert result.status_code == 200, result.text
    body = result.json()
    assert body["added"] == 1 and body["skipped"] == 1 and body["version_no"] == 2
    versions = authed.get(f"/api/dictionaries/{dictionary_id}/versions").json()
    assert versions[-1]["document"]["mapping"] == {"电阻": "电阻器"}


def test_synonym_import_missing_column_fails_422(authed):
    dictionary_id = _dictionary(authed)
    upload = authed.post(
        "/api/files/upload",
        data={"role": "supplement"},
        files={"file": ("syn.xlsx", _xlsx(["a", "b"], [["1", "2"]]), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    ).json()["file"]
    result = authed.post(
        f"/api/dictionaries/{dictionary_id}/synonyms/import",
        json={"file_id": upload["file_id"], "source_column": "原始写法", "target_column": "标准词"},
    )
    assert result.status_code == 422
    assert result.json()["error"]["code"] == "SYNONYM_IMPORT_COLUMNS_NOT_FOUND"
