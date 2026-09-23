from __future__ import annotations

import csv
from itertools import chain
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from openpyxl import load_workbook

from material_matcher.ingestion.inspector import (
    inspect_tabular_file,
    iter_sparse_worksheet_rows,
    row_has_effective_data,
)


@dataclass(frozen=True)
class TableLayout:
    sheet_name: str
    header_row: int
    row_count_estimate: int


# Reserved internal metadata key persisted inside vector-index records. It is
# deliberately outside the customer's field namespace and removed again before
# a target payload is exposed to callers.
ORIGINAL_ROW_NUMBER_KEY = "__material_matcher_original_row_number__"


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


def iter_tabular_rows_with_position(
    path: Path,
    *,
    sheet_name: str | None = None,
    header_row: int | None = None,
    max_rows: int | None = None,
) -> Iterator[tuple[int, dict[str, str | None]]]:
    """Stream rows together with the row number visible in the original file.

    The returned position is the real worksheet/CSV record row, not the compact
    ordinal used internally as source_row_id. Blank rows are skipped from the
    payload stream but still advance the original row number. Therefore a sheet
    whose header is on row 4 yields its first data row as row 5, exactly as users
    see it in Excel.

    Callers that already ran detect_layout should pass sheet_name and header_row
    so a million-row file is not fully inspected a second time.
    """
    layout = detect_layout(path) if sheet_name is None or header_row is None else None
    selected_sheet = sheet_name or (layout.sheet_name if layout is not None else "")
    selected_header = int(header_row if header_row is not None else layout.header_row)
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
            business_columns = [index for index, header in enumerate(headers) if header]
            original_row_number = selected_header
            for row in reader:
                original_row_number += 1
                if max_rows is not None and emitted >= max_rows:
                    break
                if not row_has_effective_data(row, business_columns):
                    continue
                emitted += 1
                yield original_row_number, {
                    header: (row[index] if index < len(row) and str(row[index]).strip() else None)
                    for index, header in enumerate(headers)
                    if header
                }
        return

    workbook = load_workbook(path, read_only=True, data_only=True, keep_links=False)
    try:
        worksheet = workbook[selected_sheet]
        row_iter = iter_sparse_worksheet_rows(worksheet)
        raw_headers: tuple[object, ...] = ()
        pending: tuple[int, tuple[object, ...]] | None = None
        for original_row_number, values in row_iter:
            if original_row_number < selected_header:
                continue
            if original_row_number == selected_header:
                raw_headers = values
            else:
                pending = (original_row_number, values)
            break

        headers = ["" if value is None else str(value).strip() for value in raw_headers]
        business_columns = [index for index, header in enumerate(headers) if header]
        positioned_rows = chain(
            (() if pending is None else (pending,)),
            row_iter,
        )
        for original_row_number, values in positioned_rows:
            if original_row_number <= selected_header:
                continue
            if max_rows is not None and emitted >= max_rows:
                break
            if not row_has_effective_data(values, business_columns):
                continue
            emitted += 1
            yield original_row_number, {
                header: _string_value(values[index] if index < len(values) else None)
                for index, header in enumerate(headers)
                if header
            }
    finally:
        workbook.close()


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
    for _, row in iter_tabular_rows_with_position(
        path,
        sheet_name=sheet_name,
        header_row=header_row,
        max_rows=max_rows,
    ):
        yield row
