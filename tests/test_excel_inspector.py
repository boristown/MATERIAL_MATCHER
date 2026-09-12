import io

from openpyxl import Workbook

from material_matcher.excel_inspector import inspect_excel


def test_excel_inspector_detects_header_and_business_fields() -> None:
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "SAP导出"
    sheet.append(["导出说明", None, None, None])
    sheet.append(["MATNR", "物料名称", "型号规格", "生产厂家"])
    sheet.append(["000000001234", "环氧玻璃布板", "3240 2mm", "某材料厂"])
    sheet.append(["000000001235", "环氧玻璃布棒", "3841 Φ20", "某材料厂"])

    buffer = io.BytesIO()
    workbook.save(buffer)

    result = inspect_excel(buffer.getvalue())
    assert result.recommended_sheet == "SAP导出"
    inspected = result.sheets[0]
    assert inspected.header_row == 2

    hints = {column.header: column.logical_hint for column in inspected.columns}
    assert hints["MATNR"] == "source_id"
    assert hints["物料名称"] == "material_name"
    assert hints["型号规格"] == "specification"
    assert hints["生产厂家"] == "manufacturer"
