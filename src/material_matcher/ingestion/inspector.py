from __future__ import annotations

import csv
from pathlib import Path
import re
from typing import Sequence

from openpyxl import load_workbook

ALIASES: dict[str, tuple[str, ...]] = {
    "source_id": ("matnr", "物料", "物料号", "物料编码", "物资编码"),
    "group_code": ("集团码", "集团编码", "集团物资编码"),
    "material_name": ("物料名称", "物料描述", "名称", "品名", "zwlmc", "maktx"),
    "model": ("型号", "牌号", "系列", "zxh"),
    "specification": ("规格", "型号规格", "详细型号规格", "尺寸", "zxhgg", "zgg"),
    "manufacturer": ("生产厂家", "制造商", "厂家", "品牌", "zsccj"),
    "material_group": ("物料组", "物料类型", "分类", "matkl", "zwlyx"),
    "standard": ("标准", "采用标准", "技术标准", "规范", "标准号", "zcgbz", "zjsbz", "zbzh"),
    "unit": ("计量单位", "单位", "meins"),
}


def _normalize_header(value: object) -> str:
    text = "" if value is None else str(value).strip().lower()
    return re.sub(r"[\s_\-—–/（）()【】\[\]:：]+", "", text)


def _hint(header: str) -> tuple[str | None, float]:
    normalized = _normalize_header(header)
    best: tuple[str | None, float] = (None, 0.0)
    for field_name, aliases in ALIASES.items():
        for alias in aliases:
            candidate = _normalize_header(alias)
            score = (
                0.99
                if normalized == candidate
                else 0.82
                if candidate and (candidate in normalized or normalized in candidate)
                else 0.0
            )
            if score > best[1]:
                best = (field_name, score)
    return best


def _header_score(row: Sequence[object]) -> float:
    values = [value for value in row if value is not None and str(value).strip()]
    if not values:
        return 0.0
    return (
        len(values)
        + sum(isinstance(value, str) for value in values) * 1.5
        + sum(_hint(str(value))[0] is not None for value in values) * 2.5
        + len({_normalize_header(value) for value in values}) * 0.2
    )


def inspect_tabular_file(
    path: Path,
    *,
    max_scan_rows: int = 30,
    sample_data_rows: int = 20,
) -> dict[str, object]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        return _inspect_csv(path, max_scan_rows, sample_data_rows)
    if suffix not in {".xlsx", ".xlsm"}:
        raise ValueError("unsupported tabular file")

    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    sheets: list[dict[str, object]] = []
    try:
        for worksheet in workbook.worksheets:
            scan_rows = list(
                worksheet.iter_rows(
                    min_row=1,
                    max_row=min(max_scan_rows, worksheet.max_row or 1),
                    values_only=True,
                )
            )
            scored = [(index + 1, _header_score(row)) for index, row in enumerate(scan_rows)]
            header_row, best = max(scored, key=lambda item: item[1], default=(1, 0.0))
            scores = sorted((score for _, score in scored), reverse=True)
            second = scores[1] if len(scores) > 1 else 0.0
            confidence = 0.0 if best <= 0 else min(1.0, 0.55 + max(0.0, best - second) / best)
            headers = next(
                worksheet.iter_rows(min_row=header_row, max_row=header_row, values_only=True),
                (),
            )
            columns: list[dict[str, object]] = []
            warnings: list[str] = []
            for column_index, header in enumerate(headers, 1):
                if header is None or not str(header).strip():
                    continue
                samples: list[object] = []
                for row in worksheet.iter_rows(
                    min_row=header_row + 1,
                    max_row=min(worksheet.max_row or header_row, header_row + sample_data_rows),
                    min_col=column_index,
                    max_col=column_index,
                    values_only=True,
                ):
                    if row[0] is not None:
                        samples.append(row[0])
                business_hint, hint_confidence = _hint(str(header))
                leading_zero_risk = business_hint in {"source_id", "group_code", "material_group"} and any(
                    isinstance(value, (int, float)) and not isinstance(value, bool) for value in samples
                )
                if leading_zero_risk:
                    warnings.append(f"列“{str(header).strip()}”疑似编码字段且包含数值单元格，前导零可能已丢失，请人工确认。")
                columns.append({
                    "index": column_index,
                    "header": str(header).strip(),
                    "samples": [str(value) for value in samples[:5]],
                    "inferred_type": "TEXT",
                    "business_hint": business_hint,
                    "hint_confidence": hint_confidence,
                    "leading_zero_risk": leading_zero_risk,
                })
            sheets.append({
                "sheet_name": worksheet.title,
                "recommended_header_row": header_row,
                "header_confidence": round(confidence, 3),
                "row_count_estimate": max(0, (worksheet.max_row or 0) - header_row),
                "column_count": len(columns),
                "columns": columns,
                "warnings": warnings,
            })
    finally:
        workbook.close()

    recommended = max(
        sheets,
        key=lambda sheet: (float(sheet["header_confidence"]), int(sheet["row_count_estimate"])),
        default=None,
    )
    return {
        "file_type": suffix.lstrip("."),
        "sheets": sheets,
        "recommended_sheet": recommended["sheet_name"] if recommended else None,
        "warnings": [],
    }


def _inspect_csv(path: Path, scan_rows: int, sample_rows: int) -> dict[str, object]:
    with path.open("rb") as stream:
        raw = stream.read(256 * 1024)
    try:
        text = raw.decode("utf-8-sig")
        encoding = "utf-8-sig"
    except UnicodeDecodeError:
        text = raw.decode("gb18030")
        encoding = "gb18030"
    rows = list(csv.reader(text.splitlines()))[: scan_rows + sample_rows]
    scored = [(index + 1, _header_score(row)) for index, row in enumerate(rows[:scan_rows])]
    header_row, best = max(scored, key=lambda item: item[1], default=(1, 0.0))
    headers = rows[header_row - 1] if rows else []
    columns: list[dict[str, object]] = []
    for column_index, header in enumerate(headers):
        business_hint, hint_confidence = _hint(header)
        values = [
            row[column_index]
            for row in rows[header_row : header_row + sample_rows]
            if len(row) > column_index and row[column_index] != ""
        ]
        columns.append({
            "index": column_index + 1,
            "header": header,
            "samples": values[:5],
            "inferred_type": "TEXT",
            "business_hint": business_hint,
            "hint_confidence": hint_confidence,
            "leading_zero_risk": False,
        })
    sheet = {
        "sheet_name": "CSV",
        "recommended_header_row": header_row,
        "header_confidence": 1.0 if best else 0.0,
        "row_count_estimate": max(0, len(rows) - header_row),
        "column_count": len(columns),
        "columns": columns,
        "warnings": [],
    }
    return {
        "file_type": "csv",
        "sheets": [sheet],
        "recommended_sheet": "CSV",
        "warnings": [],
        "encoding": encoding,
    }
