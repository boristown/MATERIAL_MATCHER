from __future__ import annotations

from collections import OrderedDict
from datetime import datetime
from io import BytesIO
import json
from typing import Any, Iterable, Mapping

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from material_matcher.settings import Settings
from material_matcher.storage.files import FileRepository
from material_matcher.services.task_service import resolve_task_scheme_name, safe_business_filename
from material_matcher.storage.metadata import MetadataRepository


STATUS_LABELS = {
    "MATCHED": "自动匹配",
    "CONFIRMED": "人工匹配",
    "REVIEW": "待处理",
    "UNMATCHED": "未匹配",
}

ACTION_LABELS = {
    "CONFIRM_CANDIDATE": "匹配",
    "MATCH": "匹配",
    "BATCH_CONFIRM_TOP1": "匹配",
    "CANCEL_MATCH": "取消匹配",
    "CANCEL": "取消匹配",
    "UNMATCH": "取消匹配",
    "REMATCH": "重新匹配",
    "RE_MATCH": "重新匹配",
    "REJECT_ALL": "标记未匹配",
    "MARK_UNMATCHED": "标记未匹配",
    "BATCH_REJECT": "标记未匹配",
}

HEADER_FILL = PatternFill("solid", fgColor="1F4E78")
HEADER_FONT = Font(color="FFFFFF", bold=True, size=10)
GROUP_SOURCE_FILL = PatternFill("solid", fgColor="D9EAF7")
GROUP_RESULT_FILL = PatternFill("solid", fgColor="DDEBF7")
GROUP_TARGET_FILL = PatternFill("solid", fgColor="E2F0D9")
GROUP_AUDIT_FILL = PatternFill("solid", fgColor="FFF2CC")
EXACT_FILL = PatternFill("solid", fgColor="E2F0D9")
PARTIAL_FILL = PatternFill("solid", fgColor="FFF2CC")
DIFFERENT_FILL = PatternFill("solid", fgColor="FCE4D6")
MISSING_FILL = PatternFill("solid", fgColor="E7E6E6")
STATUS_FILLS = {
    "自动匹配": PatternFill("solid", fgColor="E2F0D9"),
    "人工匹配": PatternFill("solid", fgColor="DDEBF7"),
    "待处理": PatternFill("solid", fgColor="FFF2CC"),
    "未匹配": PatternFill("solid", fgColor="E7E6E6"),
}
THIN_BORDER = Border(
    left=Side(style="thin", color="D9E2F3"),
    right=Side(style="thin", color="D9E2F3"),
    top=Side(style="thin", color="D9E2F3"),
    bottom=Side(style="thin", color="D9E2F3"),
)
DATE_FORMAT = "yyyy-mm-dd hh:mm:ss"


def _now() -> str:
    return datetime.now().astimezone().isoformat()


def _json_object(value: object) -> dict[str, object]:
    if isinstance(value, dict):
        return dict(value)
    if not value:
        return {}
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return {}
    return dict(decoded) if isinstance(decoded, dict) else {}


def _json_list(value: object) -> list[dict[str, object]]:
    if isinstance(value, list):
        return [dict(item) for item in value if isinstance(item, dict)]
    if not value:
        return []
    try:
        decoded = json.loads(str(value))
    except (TypeError, json.JSONDecodeError):
        return []
    return [dict(item) for item in decoded if isinstance(item, dict)] if isinstance(decoded, list) else []


def _display_time(value: object) -> datetime | None:
    if value is None or value == "":
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return parsed.replace(tzinfo=None)
    except ValueError:
        return None


def _text(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _is_missing(value: object) -> bool:
    return value is None or str(value).strip() == ""


def _ordered_fields(payloads: Iterable[Mapping[str, object]]) -> list[str]:
    fields: OrderedDict[str, None] = OrderedDict()
    for payload in payloads:
        for key in payload:
            text = str(key).strip()
            if text and not text.startswith("__material_matcher_"):
                fields.setdefault(text, None)
    return list(fields)


def _action_label(action: object) -> str:
    text = str(action or "").strip().upper()
    return ACTION_LABELS.get(text, "人工调整" if text else "")


def _method_label(status: str, review: Mapping[str, object] | None) -> str:
    if status == "MATCHED":
        return "自动匹配"
    if status == "CONFIRMED":
        return "人工匹配"
    if status == "REVIEW":
        return "待人工处理"
    if review:
        return "人工标记未匹配"
    return "自动判定未匹配"


class ResultExportService:
    """Build the customer-facing final workbook without exposing internal diagnostics."""

    def __init__(self, metadata: MetadataRepository, files: FileRepository, settings: Settings) -> None:
        self.meta = metadata
        self.files = files
        self.settings = settings

    def _task_actor(self, task_id: str, task: Mapping[str, object], kind: str) -> str:
        direct_keys = (
            ("created_by", "creator", "created_user", "created_username")
            if kind == "created"
            else ("started_by", "starter", "started_user", "started_username")
        )
        for key in direct_keys:
            value = task.get(key)
            if value:
                return str(value)

        action_tokens = ("CREATE", "CREATED") if kind == "created" else ("START", "STARTED")
        with self.meta.connect() as connection:
            rows = connection.execute(
                "SELECT action,payload FROM audit_events WHERE entity_type='task' AND entity_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()
        for row in rows:
            action = str(row["action"] or "").upper()
            if not any(token in action for token in action_tokens):
                continue
            payload = _json_object(row["payload"])
            for key in ("operator", "username", "user", "actor", "created_by", "started_by"):
                value = payload.get(key)
                if value:
                    return str(value)
        return ""

    @staticmethod
    def _latest_reviews(reviews: Iterable[Mapping[str, object]]) -> dict[str, Mapping[str, object]]:
        result: dict[str, Mapping[str, object]] = {}
        for review in reviews:
            source_row_id = str(review.get("source_row_id") or "")
            if not source_row_id:
                continue
            previous = result.get(source_row_id)
            if previous is None or str(review.get("created_at") or "") >= str(previous.get("created_at") or ""):
                result[source_row_id] = review
        return result

    @staticmethod
    def _candidate_map(candidates: Iterable[Mapping[str, object]]) -> dict[str, list[Mapping[str, object]]]:
        result: dict[str, list[Mapping[str, object]]] = {}
        for candidate in candidates:
            result.setdefault(str(candidate.get("source_row_id") or ""), []).append(candidate)
        for rows in result.values():
            rows.sort(key=lambda row: int(row.get("rank") or 999))
        return result

    @staticmethod
    def _selected_candidate(item: Mapping[str, object], candidates: list[Mapping[str, object]]) -> Mapping[str, object] | None:
        final_code = item.get("final_group_code")
        if final_code is None or str(final_code) == "":
            return None
        return next(
            (candidate for candidate in candidates if str(candidate.get("target_group_code")) == str(final_code)),
            None,
        )

    @staticmethod
    def _review_target_row(review: Mapping[str, object] | None, candidates: list[Mapping[str, object]]) -> object:
        if not review:
            return None
        for key in ("target_row_number", "selected_target_row", "target_excel_row", "target_row"):
            if review.get(key) not in {None, ""}:
                return review.get(key)
        selected = review.get("selected_group_code")
        if selected in {None, ""}:
            return None
        candidate = next(
            (row for row in candidates if str(row.get("target_group_code")) == str(selected)),
            None,
        )
        return candidate.get("target_row_number") if candidate else None

    @staticmethod
    def _rules(task: Mapping[str, object]) -> dict[str, dict[str, list[str]]]:
        snapshot = task.get("config_snapshot")
        if isinstance(snapshot, str):
            snapshot = _json_object(snapshot)
        if not isinstance(snapshot, dict):
            return {}
        result: dict[str, dict[str, list[str]]] = {}
        for raw_rule in snapshot.get("rules") or []:
            if not isinstance(raw_rule, dict):
                continue
            rule_id = str(raw_rule.get("id") or "")
            if not rule_id:
                continue
            source = raw_rule.get("source") if isinstance(raw_rule.get("source"), dict) else {}
            target = raw_rule.get("target") if isinstance(raw_rule.get("target"), dict) else {}
            result[rule_id] = {
                "source": [str(value) for value in source.get("fields") or [] if str(value)],
                "target": [str(value) for value in target.get("fields") or [] if str(value)],
            }
        return result

    @staticmethod
    def _field_states(
        source_payload: Mapping[str, object],
        target_payload: Mapping[str, object],
        candidate: Mapping[str, object] | None,
        rules: Mapping[str, Mapping[str, list[str]]],
    ) -> tuple[dict[str, str], dict[str, str]]:
        source_states: dict[str, str] = {}
        target_states: dict[str, str] = {}
        priority = {"exact": 1, "partial": 2, "different": 3, "missing": 4}

        def set_state(states: dict[str, str], field: str, state: str, payload: Mapping[str, object]) -> None:
            if _is_missing(payload.get(field)):
                state = "missing"
            current = states.get(field)
            if current is None or priority[state] > priority[current]:
                states[field] = state

        field_scores = _json_list(candidate.get("field_scores") if candidate else None)
        for field_score in field_scores:
            rule_id = str(field_score.get("rule_id") or "")
            rule = rules.get(rule_id)
            if not rule:
                continue
            try:
                score = float(field_score.get("score") or 0.0)
            except (TypeError, ValueError):
                score = 0.0
            state = "exact" if score >= 0.999999 else "partial" if score > 0 else "different"
            for field in rule.get("source", []):
                set_state(source_states, field, state, source_payload)
            for field in rule.get("target", []):
                set_state(target_states, field, state, target_payload)

        for field in set(source_payload).intersection(target_payload):
            if field in source_states or field in target_states:
                continue
            source_value = source_payload.get(field)
            target_value = target_payload.get(field)
            if _is_missing(source_value) or _is_missing(target_value):
                state = "missing"
            else:
                state = "exact" if str(source_value).strip() == str(target_value).strip() else "different"
            source_states[field] = state
            target_states[field] = state

        for field, value in source_payload.items():
            if _is_missing(value):
                source_states[field] = "missing"
        for field, value in target_payload.items():
            if _is_missing(value):
                target_states[field] = "missing"
        return source_states, target_states

    @staticmethod
    def _fill_for_state(state: str | None) -> PatternFill | None:
        return {
            "exact": EXACT_FILL,
            "partial": PARTIAL_FILL,
            "different": DIFFERENT_FILL,
            "missing": MISSING_FILL,
        }.get(state or "")

    @staticmethod
    def _append_grouped_headers(
        sheet: Any,
        groups: list[tuple[str, list[str], PatternFill]],
    ) -> dict[str, tuple[int, int]]:
        ranges: dict[str, tuple[int, int]] = {}
        column = 1
        for group_name, headers, fill in groups:
            if not headers:
                continue
            start = column
            end = column + len(headers) - 1
            sheet.merge_cells(start_row=1, start_column=start, end_row=1, end_column=end)
            top = sheet.cell(1, start, group_name)
            top.fill = fill
            top.font = Font(bold=True, color="1F2937")
            top.alignment = Alignment(horizontal="center", vertical="center")
            for current in range(start, end + 1):
                cell = sheet.cell(1, current)
                cell.fill = fill
                cell.border = THIN_BORDER
            for offset, header in enumerate(headers):
                cell = sheet.cell(2, start + offset, header)
                cell.fill = HEADER_FILL
                cell.font = HEADER_FONT
                cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
                cell.border = THIN_BORDER
            ranges[group_name] = (start, end)
            column = end + 1
        sheet.row_dimensions[1].height = 22
        sheet.row_dimensions[2].height = 34
        sheet.freeze_panes = "A3"
        return ranges

    @staticmethod
    def _style_data_sheet(sheet: Any, *, max_width: int = 38) -> None:
        sheet.sheet_view.showGridLines = False
        for row in sheet.iter_rows(min_row=3):
            for cell in row:
                cell.alignment = Alignment(vertical="top", wrap_text=True)
                cell.border = THIN_BORDER
        for index in range(1, sheet.max_column + 1):
            letter = get_column_letter(index)
            width = 10
            for cell in list(sheet[letter])[:250]:
                if cell.value is not None:
                    width = max(width, min(max_width, len(str(cell.value)) + 2))
            sheet.column_dimensions[letter].width = min(max_width, width)
        if sheet.max_column:
            sheet.auto_filter.ref = f"A2:{get_column_letter(sheet.max_column)}{max(2, sheet.max_row)}"

    @staticmethod
    def _write_text(cell: Any, value: object) -> None:
        cell.value = _text(value)
        cell.number_format = "@"

    @staticmethod
    def _write_time(cell: Any, value: object) -> None:
        parsed = _display_time(value)
        if parsed is None:
            cell.value = ""
            cell.number_format = "@"
        else:
            cell.value = parsed
            cell.number_format = DATE_FORMAT

    def export_task(self, task_id: str, task: Mapping[str, object], *, unresolved_review: int) -> dict[str, object]:
        with self.meta.connect() as connection:
            items = [dict(row) for row in connection.execute(
                "SELECT * FROM match_items WHERE task_id=? ORDER BY COALESCE(source_row_number, CAST(source_row_id AS INTEGER)), CAST(source_row_id AS INTEGER)",
                (task_id,),
            ).fetchall()]
            candidates = [dict(row) for row in connection.execute(
                "SELECT * FROM match_candidates WHERE task_id=? ORDER BY CAST(source_row_id AS INTEGER), rank",
                (task_id,),
            ).fetchall()]
            reviews = [dict(row) for row in connection.execute(
                "SELECT * FROM reviews WHERE task_id=? ORDER BY created_at",
                (task_id,),
            ).fetchall()]
            catalog = connection.execute(
                "SELECT v.source_file_id FROM catalog_versions v WHERE v.version_id=?",
                (task.get("catalog_version_id"),),
            ).fetchone()

        for item in items:
            item["source_payload"] = _json_object(item.get("source_payload"))
        for candidate in candidates:
            candidate["target_payload"] = _json_object(candidate.get("target_payload"))
            candidate["field_scores"] = _json_list(candidate.get("field_scores"))

        item_by_source = {str(item.get("source_row_id")): item for item in items}
        candidate_by_source = self._candidate_map(candidates)
        latest_review = self._latest_reviews(reviews)
        source_fields = _ordered_fields(item["source_payload"] for item in items)
        target_fields = _ordered_fields(candidate["target_payload"] for candidate in candidates)
        rules = self._rules(task)
        generated_at = _now()

        source_file_name = ""
        target_file_name = ""
        try:
            source_file_name = str(self.files.get(str(task.get("source_file_id")))["original_name"])
        except Exception:
            pass
        try:
            if catalog is not None:
                target_file_name = str(self.files.get(str(catalog["source_file_id"]))["original_name"])
        except Exception:
            pass

        counts = {"MATCHED": 0, "CONFIRMED": 0, "REVIEW": 0, "UNMATCHED": 0}
        for item in items:
            status = str(item.get("current_status") or "")
            if status in counts:
                counts[status] += 1

        workbook = Workbook()
        summary = workbook.active
        summary.title = "匹配摘要"
        summary.sheet_view.showGridLines = False
        summary["A1"] = "匹配结果摘要"
        summary["A1"].font = Font(size=16, bold=True, color="1F4E78")
        summary.merge_cells("A1:D1")
        created_by = self._task_actor(task_id, task, "created")
        started_by = self._task_actor(task_id, task, "started")
        scheme_name = resolve_task_scheme_name(self.meta, dict(task))
        business_digits = "".join(ch for ch in str(generated_at) if ch.isdigit())[:14]
        business_stamp = f"{business_digits[:8]}_{business_digits[8:14]}"
        summary_rows = [
            ("方案名称", scheme_name, "源数据总数", len(items)),
            ("自动匹配数", counts["MATCHED"], "人工匹配数", counts["CONFIRMED"]),
            ("未匹配数", counts["UNMATCHED"], "待处理数", counts["REVIEW"]),
            ("创建账号", created_by, "启动账号", started_by),
            ("创建时间", task.get("created_at"), "启动时间", task.get("started_at")),
            ("最终结果生成时间", generated_at, "源文件", source_file_name),
            ("目标集团码文件", target_file_name, "待处理记录", unresolved_review),
        ]
        for row_index, values in enumerate(summary_rows, start=3):
            summary.cell(row_index, 1, values[0])
            summary.cell(row_index, 3, values[2])
            for key_col in (1, 3):
                summary.cell(row_index, key_col).font = Font(bold=True, color="475569")
                summary.cell(row_index, key_col).fill = PatternFill("solid", fgColor="F3F6FA")
            if values[0].endswith("时间"):
                self._write_time(summary.cell(row_index, 2), values[1])
            else:
                self._write_text(summary.cell(row_index, 2), values[1])
            if values[2].endswith("时间"):
                self._write_time(summary.cell(row_index, 4), values[3])
            else:
                self._write_text(summary.cell(row_index, 4), values[3])
            for column in range(1, 5):
                summary.cell(row_index, column).border = THIN_BORDER
                summary.cell(row_index, column).alignment = Alignment(vertical="center", wrap_text=True)

        summary["A12"] = "字段颜色说明"
        summary["A12"].font = Font(bold=True, color="475569")
        legend = [("完全一致", EXACT_FILL), ("部分相似", PARTIAL_FILL), ("不一致", DIFFERENT_FILL), ("无数据", MISSING_FILL)]
        for offset, (label, fill) in enumerate(legend, start=1):
            cell = summary.cell(13, offset, label)
            cell.fill = fill
            cell.font = Font(bold=True)
            cell.alignment = Alignment(horizontal="center")
            cell.border = THIN_BORDER
        summary.column_dimensions["A"].width = 22
        summary.column_dimensions["B"].width = 34
        summary.column_dimensions["C"].width = 22
        summary.column_dimensions["D"].width = 34
        summary.freeze_panes = "A3"

        result_sheet = workbook.create_sheet("最终匹配结果")
        result_headers = ["匹配状态", "最终集团码", "相似度", "匹配方式", "操作账号", "匹配日期时间"]
        groups = [
            ("源数据区", ["源表原始行号", *source_fields], GROUP_SOURCE_FILL),
            ("匹配结果区", result_headers, GROUP_RESULT_FILL),
            ("目标数据区", ["目标表原始行号", *target_fields], GROUP_TARGET_FILL),
        ]
        ranges = self._append_grouped_headers(result_sheet, groups)
        source_start = ranges["源数据区"][0]
        result_start = ranges["匹配结果区"][0]
        target_start = ranges["目标数据区"][0]

        for excel_row, item in enumerate(items, start=3):
            source_payload = item["source_payload"]
            source_key = str(item.get("source_row_id") or "")
            row_candidates = candidate_by_source.get(source_key, [])
            selected = self._selected_candidate(item, row_candidates)
            target_payload = selected.get("target_payload", {}) if selected else {}
            review = latest_review.get(source_key)
            status = str(item.get("current_status") or "")
            match_time = review.get("created_at") if review else item.get("created_at") if status in {"MATCHED", "UNMATCHED"} else None
            operator = review.get("operator") if review else None
            similarity = selected.get("score") if selected else item.get("top1_score")

            result_sheet.cell(excel_row, source_start, item.get("source_row_number"))
            for index, field in enumerate(source_fields, start=source_start + 1):
                self._write_text(result_sheet.cell(excel_row, index), source_payload.get(field))

            self._write_text(result_sheet.cell(excel_row, result_start), STATUS_LABELS.get(status, ""))
            self._write_text(result_sheet.cell(excel_row, result_start + 1), item.get("final_group_code"))
            result_sheet.cell(excel_row, result_start + 2, similarity)
            result_sheet.cell(excel_row, result_start + 2).number_format = "0.0"
            self._write_text(result_sheet.cell(excel_row, result_start + 3), _method_label(status, review))
            self._write_text(result_sheet.cell(excel_row, result_start + 4), operator)
            self._write_time(result_sheet.cell(excel_row, result_start + 5), match_time)
            status_cell = result_sheet.cell(excel_row, result_start)
            if status_cell.value in STATUS_FILLS:
                status_cell.fill = STATUS_FILLS[str(status_cell.value)]

            result_sheet.cell(excel_row, target_start, selected.get("target_row_number") if selected else None)
            for index, field in enumerate(target_fields, start=target_start + 1):
                self._write_text(result_sheet.cell(excel_row, index), target_payload.get(field))

            source_states, target_states = self._field_states(source_payload, target_payload, selected, rules)
            for index, field in enumerate(source_fields, start=source_start + 1):
                fill = self._fill_for_state(source_states.get(field))
                if fill:
                    result_sheet.cell(excel_row, index).fill = fill
            for index, field in enumerate(target_fields, start=target_start + 1):
                fill = self._fill_for_state(target_states.get(field))
                if fill:
                    result_sheet.cell(excel_row, index).fill = fill

        self._style_data_sheet(result_sheet)

        top5 = workbook.create_sheet("Top5候选")
        candidate_result_headers = ["候选排名", "目标表原始行号", "集团码", "相似度"]
        top_groups = [
            ("源数据区", ["源表原始行号", "源物料编码", *source_fields], GROUP_SOURCE_FILL),
            ("候选结果区", candidate_result_headers, GROUP_RESULT_FILL),
            ("目标数据区", target_fields, GROUP_TARGET_FILL),
        ]
        top_ranges = self._append_grouped_headers(top5, top_groups)
        top_source_start = top_ranges["源数据区"][0]
        top_result_start = top_ranges["候选结果区"][0]
        top_target_start = top_ranges["目标数据区"][0]
        candidate_excel_row = 3
        for candidate in candidates:
            if int(candidate.get("rank") or 999) > 5:
                continue
            item = item_by_source.get(str(candidate.get("source_row_id") or ""))
            if item is None:
                continue
            source_payload = item["source_payload"]
            target_payload = candidate.get("target_payload") or {}
            top5.cell(candidate_excel_row, top_source_start, item.get("source_row_number"))
            self._write_text(top5.cell(candidate_excel_row, top_source_start + 1), item.get("source_id"))
            for index, field in enumerate(source_fields, start=top_source_start + 2):
                self._write_text(top5.cell(candidate_excel_row, index), source_payload.get(field))
            top5.cell(candidate_excel_row, top_result_start, candidate.get("rank"))
            top5.cell(candidate_excel_row, top_result_start + 1, candidate.get("target_row_number"))
            self._write_text(top5.cell(candidate_excel_row, top_result_start + 2), candidate.get("target_group_code"))
            top5.cell(candidate_excel_row, top_result_start + 3, candidate.get("score"))
            top5.cell(candidate_excel_row, top_result_start + 3).number_format = "0.0"
            for index, field in enumerate(target_fields, start=top_target_start):
                self._write_text(top5.cell(candidate_excel_row, index), target_payload.get(field))
            source_states, target_states = self._field_states(source_payload, target_payload, candidate, rules)
            for index, field in enumerate(source_fields, start=top_source_start + 2):
                fill = self._fill_for_state(source_states.get(field))
                if fill:
                    top5.cell(candidate_excel_row, index).fill = fill
            for index, field in enumerate(target_fields, start=top_target_start):
                fill = self._fill_for_state(target_states.get(field))
                if fill:
                    top5.cell(candidate_excel_row, index).fill = fill
            candidate_excel_row += 1
        self._style_data_sheet(top5)

        audit = workbook.create_sheet("人工操作记录")
        audit_groups = [
            ("源数据", ["源表原始行号", "源物料编码"], GROUP_SOURCE_FILL),
            ("人工操作", ["操作", "目标表原始行号", "集团码", "操作账号", "备注", "操作时间"], GROUP_AUDIT_FILL),
        ]
        audit_ranges = self._append_grouped_headers(audit, audit_groups)
        audit_source_start = audit_ranges["源数据"][0]
        audit_action_start = audit_ranges["人工操作"][0]
        for excel_row, review in enumerate(reviews, start=3):
            source_key = str(review.get("source_row_id") or "")
            item = item_by_source.get(source_key)
            row_candidates = candidate_by_source.get(source_key, [])
            audit.cell(excel_row, audit_source_start, item.get("source_row_number") if item else None)
            self._write_text(audit.cell(excel_row, audit_source_start + 1), item.get("source_id") if item else None)
            self._write_text(audit.cell(excel_row, audit_action_start), _action_label(review.get("action")))
            audit.cell(excel_row, audit_action_start + 1, self._review_target_row(review, row_candidates))
            self._write_text(audit.cell(excel_row, audit_action_start + 2), review.get("selected_group_code"))
            self._write_text(audit.cell(excel_row, audit_action_start + 3), review.get("operator"))
            self._write_text(audit.cell(excel_row, audit_action_start + 4), review.get("comment"))
            self._write_time(audit.cell(excel_row, audit_action_start + 5), review.get("created_at"))
        self._style_data_sheet(audit)

        unmatched = workbook.create_sheet("未匹配清单")
        unmatched_groups = [
            ("源数据区", ["源表原始行号", *source_fields], GROUP_SOURCE_FILL),
            ("参考信息", ["状态", "第一候选目标行", "第一候选集团码", "第一候选相似度", "最后操作账号", "最后操作时间"], GROUP_RESULT_FILL),
        ]
        unmatched_ranges = self._append_grouped_headers(unmatched, unmatched_groups)
        unmatched_source_start = unmatched_ranges["源数据区"][0]
        unmatched_result_start = unmatched_ranges["参考信息"][0]
        unmatched_excel_row = 3
        for item in items:
            if str(item.get("current_status") or "") != "UNMATCHED":
                continue
            source_key = str(item.get("source_row_id") or "")
            row_candidates = candidate_by_source.get(source_key, [])
            top1 = row_candidates[0] if row_candidates else None
            review = latest_review.get(source_key)
            unmatched.cell(unmatched_excel_row, unmatched_source_start, item.get("source_row_number"))
            for index, field in enumerate(source_fields, start=unmatched_source_start + 1):
                self._write_text(unmatched.cell(unmatched_excel_row, index), item["source_payload"].get(field))
            self._write_text(unmatched.cell(unmatched_excel_row, unmatched_result_start), "未匹配")
            unmatched.cell(unmatched_excel_row, unmatched_result_start + 1, top1.get("target_row_number") if top1 else None)
            self._write_text(unmatched.cell(unmatched_excel_row, unmatched_result_start + 2), top1.get("target_group_code") if top1 else None)
            unmatched.cell(unmatched_excel_row, unmatched_result_start + 3, top1.get("score") if top1 else None)
            unmatched.cell(unmatched_excel_row, unmatched_result_start + 3).number_format = "0.0"
            self._write_text(unmatched.cell(unmatched_excel_row, unmatched_result_start + 4), review.get("operator") if review else None)
            self._write_time(unmatched.cell(unmatched_excel_row, unmatched_result_start + 5), review.get("created_at") if review else None)
            unmatched_excel_row += 1
        self._style_data_sheet(unmatched)

        output = BytesIO()
        workbook.save(output)
        output.seek(0)
        return self.files.save_stream(
            f"物料集团码匹配结果_{safe_business_filename(scheme_name)}_{business_stamp}.xlsx",
            "result",
            output,
            self.settings.max_total_upload_bytes,
        )
