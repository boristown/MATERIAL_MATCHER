from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook

from material_matcher.ingestion.inspector import inspect_tabular_file


@dataclass(frozen=True)
class TableLayout:
    sheet_name: str
    header_row: int
    row_count_estimate: int


def detect_layout(path: Path) -> TableLayout:
    inspected = inspect_tabular_file(path)
    recommended = inspected.get("recommended_sheet")
    sheets = list(inspected.get("sheets") or [])
    sheet = next((item for item in sheets if item.get("sheet_name") == recommended), sheets[0] if sheets else None)
    if sheet is None:
        raise ValueError("未识别到可读取的数据表")
    return TableLayout(
        sheet_name=str(sheet["sheet_name"]),
        header_row=int(sheet["recommended_header_row"]),
        row_count_estimate=int(sheet.get("row_count_estimate") or 0),
    )


def _string_value(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value)


def iter_tabular_rows(
    path: Path,
    *,
    sheet_name: str | None = None,
    header_row: int | None = None,
    max_rows: int | None = None,
) -> Iterator[dict[str, str | None]]:
    """Stream tabular rows without converting identifier-like values to numbers.

    If Excel already stored an identifier as a number, its lost leading zeroes cannot
    be recovered here. The inspector flags that risk before a task is started.
    """
    layout = detect_layout(path)
    selected_sheet = sheet_name or layout.sheet_name
    selected_header = header_row or layout.header_row
    suffix = path.suffix.lower()
    emitted = 0
    if suffix == ".csv":
        with path.open("rb") as raw:
            sample = raw.read(256 * 1024)
        try:
            sample.decode("utf-8-sig")
            encoding = "utf-8-sig"
        except UnicodeDecodeError:
            encoding = "gb18030"
        with path.open("r", encoding=encoding, newline="") as stream:
            reader = csv.reader(stream)
            for _ in range(selected_header - 1):
                next(reader, None)
            headers = [str(value).strip() for value in (next(reader, []) or [])]
            for row in reader:
                if max_rows is not None and emitted >= max_rows:
                    break
                if not any(value != "" for value in row):
                    continue
                emitted += 1
                yield {
                    header: (row[index] if index < len(row) and row[index] != "" else None)
                    for index, header in enumerate(headers)
                    if header
                }
        return

    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        worksheet = workbook[selected_sheet]
        raw_headers = next(
            worksheet.iter_rows(min_row=selected_header, max_row=selected_header, values_only=True),
            (),
        )
        headers = ["" if value is None else str(value).strip() for value in raw_headers]
        for values in worksheet.iter_rows(min_row=selected_header + 1, values_only=True):
            if max_rows is not None and emitted >= max_rows:
                break
            if not any(value is not None for value in values):
                continue
            emitted += 1
            yield {
                header: _string_value(values[index] if index < len(values) else None)
                for index, header in enumerate(headers)
                if header
            }
    finally:
        workbook.close()
