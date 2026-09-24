from __future__ import annotations

import csv
from itertools import chain, islice
from pathlib import Path
import re
from typing import Sequence

from openpyxl import load_workbook
from openpyxl.worksheet._reader import WorkSheetParser

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


def is_effective_value(value: object) -> bool:
    """Return whether a cell contains business data rather than formatting/blank text."""
    if value is None:
        return False
    if isinstance(value, str):
        return bool(value.strip())
    return True


def row_has_effective_data(row: Sequence[object], business_columns: Sequence[int]) -> bool:
    """A data row is effective when at least one header-backed business column is non-empty."""
    return any(
        index < len(row) and is_effective_value(row[index])
        for index in business_columns
    )


def iter_sparse_worksheet_rows(worksheet):
    """Yield only row elements that actually exist in XLSX XML.

    ReadOnlyWorksheet.iter_rows() intentionally synthesizes every missing row
    between row indices. A style-only cell at row 1,000,000 can therefore turn a
    tiny workbook into a million Python iterations even after dimensions are
    reset. Openpyxl 3.x's worksheet parser already streams the XML and exposes
    the real row numbers, so use that parser directly and never expand gaps.
    """
    with worksheet._get_source() as source:
        parser = WorkSheetParser(
            source,
            worksheet._shared_strings,
            data_only=worksheet.parent.data_only,
            epoch=worksheet.parent.epoch,
            date_formats=worksheet.parent._date_formats,
            timedelta_formats=worksheet.parent._timedelta_formats,
        )
        for row_number, cells in parser.parse():
            if not cells:
                yield row_number, ()
                continue
            width = max(int(cell["column"]) for cell in cells)
            values: list[object] = [None] * width
            for cell in cells:
                values[int(cell["column"]) - 1] = cell["value"]
            yield row_number, tuple(values)


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
    values = [value for value in row if is_effective_value(value)]
    if not values:
        return 0.0
    return (
        len(values)
        + sum(isinstance(value, str) for value in values) * 1.5
        + sum(_hint(str(value))[0] is not None for value in values) * 2.5
        + len({_normalize_header(value) for value in values}) * 0.2
    )


def _header_detection(rows: Sequence[Sequence[object]]) -> tuple[int, float, float]:
    scored = [(index + 1, _header_score(row)) for index, row in enumerate(rows)]
    header_row, best = max(scored, key=lambda item: item[1], default=(1, 0.0))
    scores = sorted((score for _, score in scored), reverse=True)
    second = scores[1] if len(scores) > 1 else 0.0
    confidence = 0.0 if best <= 0 else min(1.0, 0.55 + max(0.0, best - second) / best)
    return header_row, best, confidence


def _business_columns(headers: Sequence[object]) -> list[int]:
    return [index for index, header in enumerate(headers) if is_effective_value(header)]


def _inspect_xlsx_sheet(
    worksheet,
    *,
    max_scan_rows: int,
    sample_data_rows: int,
) -> dict[str, object]:
    # Never trust worksheet.max_row/dimension here. Iterate only actual row
    # elements so a remote style-only cell does not expand all missing rows.
    row_iter = iter_sparse_worksheet_rows(worksheet)
    prefix: list[tuple[int, Sequence[object]]] = []
    pending: tuple[int, Sequence[object]] | None = None
    for positioned in row_iter:
        if positioned[0] <= max_scan_rows:
            prefix.append(positioned)
            continue
        pending = positioned
        break

    scored = [(row_number, _header_score(row)) for row_number, row in prefix]
    header_row, best = max(scored, key=lambda item: item[1], default=(1, 0.0))
    scores = sorted((score for _, score in scored), reverse=True)
    second = scores[1] if len(scores) > 1 else 0.0
    confidence = 0.0 if best <= 0 else min(1.0, 0.55 + max(0.0, best - second) / best)
    headers: Sequence[object] = next(
        (row for row_number, row in prefix if row_number == header_row),
        (),
    )
    business_columns = _business_columns(headers)

    samples_by_column: dict[int, list[object]] = {index: [] for index in business_columns}
    row_count = 0
    buffered = chain(prefix, (() if pending is None else (pending,)), row_iter)
    dimension_rows = 0
    try:
        dimension_rows = int(worksheet.max_row or 0)
    except Exception:  # noqa: BLE001
        dimension_rows = 0
    consumed = 0
    last_seen_row = header_row
    estimate_capped = False
    for row_number, row in buffered:
        if row_number <= header_row:
            continue
        if row_has_effective_data(row, business_columns):
            row_count += 1
        consumed += 1
        last_seen_row = row_number
        if row_number <= header_row + sample_data_rows:
            for index in business_columns:
                value = row[index] if index < len(row) else None
                if is_effective_value(value):
                    samples_by_column[index].append(value)
        if consumed >= LARGE_SHEET_ESTIMATE_ROWS and dimension_rows > row_number:
            estimate_capped = True
            break
    row_count_estimated = False
    if estimate_capped and consumed > 0 and dimension_rows > last_seen_row:
        ratio = row_count / consumed
        row_count += int(round(ratio * (dimension_rows - last_seen_row)))
        row_count_estimated = True
    columns: list[dict[str, object]] = []
    warnings: list[str] = []
    for column_index in business_columns:
        header = headers[column_index]
        samples = samples_by_column[column_index]
        business_hint, hint_confidence = _hint(str(header))
        leading_zero_risk = business_hint in {"source_id", "group_code", "material_group"} and any(
            isinstance(value, (int, float)) and not isinstance(value, bool) for value in samples
        )
        if leading_zero_risk:
            warnings.append(f"列“{str(header).strip()}”疑似编码字段且包含数值单元格，前导零可能已丢失，请人工确认。")
        columns.append({
            "index": column_index + 1,
            "header": str(header).strip(),
            "samples": [str(value) for value in samples[:5]],
            "inferred_type": "TEXT",
            "business_hint": business_hint,
            "hint_confidence": hint_confidence,
            "leading_zero_risk": leading_zero_risk,
        })

    return {
        "sheet_name": worksheet.title,
        "recommended_header_row": header_row,
        "header_confidence": round(confidence, 3),
        "row_count_estimate": row_count,
        "row_count_estimated": row_count_estimated,
        "column_count": len(columns),
        "columns": columns,
        "warnings": warnings,
    }


LARGE_SHEET_ESTIMATE_ROWS = 20_000

from collections import OrderedDict as _OrderedDict

_INSPECTION_CACHE: "_OrderedDict[tuple, dict]" = _OrderedDict()
_INSPECTION_CACHE_MAX = 32


def inspect_tabular_file(
    path: Path,
    *,
    max_scan_rows: int = 30,
    sample_data_rows: int = 20,
) -> dict[str, object]:
    """Cached entry point: uploads, catalog validation and the UI badge all ask
    the same question about the same stored bytes - scan the workbook once."""
    try:
        stat = path.stat()
        key: tuple = (str(path), stat.st_mtime_ns, stat.st_size, int(max_scan_rows), int(sample_data_rows))
    except OSError:
        key = ()
    if key:
        cached = _INSPECTION_CACHE.get(key)
        if cached is not None:
            _INSPECTION_CACHE.move_to_end(key)
            from copy import deepcopy as _deepcopy
            return _deepcopy(cached)
    result = _inspect_tabular_file_uncached(path, max_scan_rows=max_scan_rows, sample_data_rows=sample_data_rows)
    if key:
        _INSPECTION_CACHE[key] = result
        while len(_INSPECTION_CACHE) > _INSPECTION_CACHE_MAX:
            _INSPECTION_CACHE.popitem(last=False)
    from copy import deepcopy as _deepcopy
    return _deepcopy(result)


def _inspect_tabular_file_uncached(
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
            sheets.append(
                _inspect_xlsx_sheet(
                    worksheet,
                    max_scan_rows=max_scan_rows,
                    sample_data_rows=sample_data_rows,
                )
            )
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


def _csv_encoding(path: Path) -> str:
    with path.open("rb") as stream:
        raw = stream.read(256 * 1024)
    try:
        raw.decode("utf-8-sig")
        return "utf-8-sig"
    except UnicodeDecodeError:
        raw.decode("gb18030")
        return "gb18030"


def _inspect_csv(path: Path, scan_rows: int, sample_rows: int) -> dict[str, object]:
    encoding = _csv_encoding(path)
    with path.open("r", encoding=encoding, newline="") as stream:
        reader = csv.reader(stream)
        prefix = list(islice(reader, max(1, scan_rows)))
        header_row, best, _ = _header_detection(prefix)
        headers = prefix[header_row - 1] if len(prefix) >= header_row else []
        business_columns = _business_columns(headers)
        samples_by_column: dict[int, list[object]] = {index: [] for index in business_columns}
        row_count = 0

        for data_offset, row in enumerate(chain(prefix[header_row:], reader), start=1):
            if row_has_effective_data(row, business_columns):
                row_count += 1
            if data_offset <= sample_rows:
                for index in business_columns:
                    value = row[index] if index < len(row) else None
                    if is_effective_value(value):
                        samples_by_column[index].append(value)

    columns: list[dict[str, object]] = []
    for column_index in business_columns:
        header = headers[column_index]
        business_hint, hint_confidence = _hint(str(header))
        values = samples_by_column[column_index]
        columns.append({
            "index": column_index + 1,
            "header": str(header).strip(),
            "samples": [str(value) for value in values[:5]],
            "inferred_type": "TEXT",
            "business_hint": business_hint,
            "hint_confidence": hint_confidence,
            "leading_zero_risk": False,
        })

    sheet = {
        "sheet_name": "CSV",
        "recommended_header_row": header_row,
        "header_confidence": 1.0 if best else 0.0,
        "row_count_estimate": row_count,
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
