from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
from pathlib import Path
import re
from typing import Any, Mapping
import warnings


EXPORT_PROFILE_FILENAME = "export_profile.json"
_HEX_COLOR_RE = re.compile(r"^[0-9A-Fa-f]{6}$")


DEFAULT_EXPORT_PROFILE_DOCUMENT: dict[str, Any] = {
    "schema_version": 1,
    "profile_id": "standard-business-result",
    "display_name": "标准业务结果",
    "filename_prefix": "物料集团码匹配结果",
    "candidate_top_n": 5,
    "sheets": {
        "summary": "匹配摘要",
        "final_result": "最终匹配结果",
        "top_candidates": "Top5候选",
        "audit": "人工操作记录",
        "unmatched": "未匹配清单",
    },
    "groups": {
        "source": "源数据区",
        "result": "匹配结果区",
        "target": "目标数据区",
        "candidate_result": "候选结果区",
        "audit_source": "源数据",
        "audit_action": "人工操作",
        "unmatched_reference": "参考信息",
    },
    "headers": {
        "source_row_number": "源表原始行号",
        "source_material_code": "源物料编码",
        "status": "匹配状态",
        "final_group_code": "最终集团码",
        "similarity": "相似度",
        "match_method": "匹配方式",
        "operator": "操作账号",
        "match_time": "匹配日期时间",
        "target_row_number": "目标表原始行号",
        "candidate_rank": "候选排名",
        "group_code": "集团码",
        "action": "操作",
        "comment": "备注",
        "action_time": "操作时间",
        "unmatched_status": "状态",
        "first_target_row": "第一候选目标行",
        "first_group_code": "第一候选集团码",
        "first_similarity": "第一候选相似度",
        "last_operator": "最后操作账号",
        "last_action_time": "最后操作时间",
    },
    "labels": {
        "summary_title": "匹配结果摘要",
        "legend_title": "字段颜色说明",
        "summary": {
            "scheme_name": "方案名称",
            "source_total": "源数据总数",
            "automatic_matches": "自动匹配数",
            "manual_matches": "人工匹配数",
            "unmatched_count": "未匹配数",
            "pending_count": "待处理数",
            "started_by": "启动账号",
            "started_at": "任务开始时间",
            "compute_duration": "自动计算耗时",
            "compute_completed_at": "自动计算完成时间",
            "generated_at": "结果生成时间",
            "source_file": "源文件",
            "target_file": "目标集团码文件",
            "pending_records": "待处理记录",
        },
        "legend": {
            "exact": "完全一致",
            "partial": "部分相似",
            "different": "不一致",
            "missing": "无数据",
        },
        "status": {
            "MATCHED": "自动匹配",
            "CONFIRMED": "人工匹配",
            "REVIEW": "待处理",
            "UNMATCHED": "未匹配",
        },
        "method": {
            "MATCHED": "自动匹配",
            "CONFIRMED": "人工匹配",
            "REVIEW": "待人工处理",
            "UNMATCHED_REVIEWED": "人工标记未匹配",
            "UNMATCHED": "自动判定未匹配",
        },
        "actions": {
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
            "manual_adjust": "人工调整",
        },
    },
    "style": {
        "header_fill": "1F4E78",
        "header_font_color": "FFFFFF",
        "group_source_fill": "D9EAF7",
        "group_result_fill": "DDEBF7",
        "group_target_fill": "E2F0D9",
        "group_audit_fill": "FFF2CC",
        "group_font_color": "1F2937",
        "exact_fill": "E2F0D9",
        "partial_fill": "FFF2CC",
        "different_fill": "FCE4D6",
        "missing_fill": "E7E6E6",
        "summary_title_color": "1F4E78",
        "summary_key_color": "475569",
        "summary_key_fill": "F3F6FA",
        "border_color": "D9E2F3",
        "status_fill": {
            "MATCHED": "E2F0D9",
            "CONFIRMED": "DDEBF7",
            "REVIEW": "FFF2CC",
            "UNMATCHED": "E7E6E6",
        },
        "date_format": "yyyy-mm-dd hh:mm:ss",
        "freeze_panes": "A3",
        "group_header_height": 22,
        "column_header_height": 34,
        "max_column_width": 38,
        "summary_column_widths": {
            "A": 22,
            "B": 34,
            "C": 22,
            "D": 34,
        },
    },
}


def _deep_merge(base: Mapping[str, Any], override: Mapping[str, Any], *, path: str = "") -> dict[str, Any]:
    merged = deepcopy(dict(base))
    for key, value in override.items():
        if key not in base:
            where = f"{path}.{key}" if path else key
            raise ValueError(f"未知导出模板配置项: {where}")
        base_value = base[key]
        if isinstance(base_value, Mapping):
            if not isinstance(value, Mapping):
                where = f"{path}.{key}" if path else key
                raise ValueError(f"导出模板配置项必须是对象: {where}")
            merged[key] = _deep_merge(base_value, value, path=f"{path}.{key}" if path else key)
        else:
            merged[key] = value
    return merged


def _require_text(document: Mapping[str, Any], section: str, key: str) -> str:
    value = document.get(section, {}).get(key) if isinstance(document.get(section), Mapping) else None
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"导出模板配置不能为空: {section}.{key}")
    return text


def _validate(document: Mapping[str, Any]) -> None:
    if int(document.get("schema_version") or 0) != 1:
        raise ValueError("export_profile.schema_version 当前只支持 1")

    top_n = int(document.get("candidate_top_n") or 0)
    if top_n < 1 or top_n > 50:
        raise ValueError("export_profile.candidate_top_n 必须在 1~50 之间")

    sheet_names = [_require_text(document, "sheets", key) for key in DEFAULT_EXPORT_PROFILE_DOCUMENT["sheets"]]
    if len(set(sheet_names)) != len(sheet_names):
        raise ValueError("导出模板的 Sheet 名称不能重复")
    for sheet_name in sheet_names:
        if len(sheet_name) > 31:
            raise ValueError(f"Excel Sheet 名称不能超过 31 个字符: {sheet_name}")

    style = document.get("style")
    if not isinstance(style, Mapping):
        raise ValueError("export_profile.style 必须是对象")
    color_keys = (
        "header_fill",
        "header_font_color",
        "group_source_fill",
        "group_result_fill",
        "group_target_fill",
        "group_audit_fill",
        "group_font_color",
        "exact_fill",
        "partial_fill",
        "different_fill",
        "missing_fill",
        "summary_title_color",
        "summary_key_color",
        "summary_key_fill",
        "border_color",
    )
    for key in color_keys:
        value = str(style.get(key) or "")
        if not _HEX_COLOR_RE.fullmatch(value):
            raise ValueError(f"导出模板颜色必须是 6 位十六进制: style.{key}")
    status_fill = style.get("status_fill")
    if not isinstance(status_fill, Mapping):
        raise ValueError("export_profile.style.status_fill 必须是对象")
    for status in ("MATCHED", "CONFIRMED", "REVIEW", "UNMATCHED"):
        value = str(status_fill.get(status) or "")
        if not _HEX_COLOR_RE.fullmatch(value):
            raise ValueError(f"导出模板状态颜色必须是 6 位十六进制: style.status_fill.{status}")

    if int(style.get("max_column_width") or 0) < 10:
        raise ValueError("export_profile.style.max_column_width 不能小于 10")


@dataclass(frozen=True)
class ExportProfile:
    document: dict[str, Any]
    source_path: Path | None = None

    def sheet(self, key: str) -> str:
        return str(self.document["sheets"][key])

    def group(self, key: str) -> str:
        return str(self.document["groups"][key])

    def header(self, key: str) -> str:
        return str(self.document["headers"][key])

    def label(self, key: str) -> str:
        return str(self.document["labels"][key])

    def summary_label(self, key: str) -> str:
        return str(self.document["labels"]["summary"][key])

    def legend_label(self, key: str) -> str:
        return str(self.document["labels"]["legend"][key])

    def status_label(self, status: str) -> str:
        return str(self.document["labels"]["status"].get(status, ""))

    def method_label(self, status: str, *, reviewed: bool) -> str:
        key = "UNMATCHED_REVIEWED" if status == "UNMATCHED" and reviewed else status
        return str(self.document["labels"]["method"].get(key, ""))

    def action_label(self, action: object) -> str:
        text = str(action or "").strip().upper()
        actions = self.document["labels"]["actions"]
        return str(actions.get(text, actions.get("manual_adjust", ""))) if text else ""

    def color(self, key: str) -> str:
        return str(self.document["style"][key])

    def status_color(self, status: str) -> str | None:
        value = self.document["style"]["status_fill"].get(status)
        return str(value) if value else None

    @property
    def candidate_top_n(self) -> int:
        return int(self.document["candidate_top_n"])

    @property
    def filename_prefix(self) -> str:
        return str(self.document["filename_prefix"])

    @property
    def date_format(self) -> str:
        return str(self.document["style"]["date_format"])

    @property
    def freeze_panes(self) -> str:
        return str(self.document["style"]["freeze_panes"])

    @property
    def group_header_height(self) -> int:
        return int(self.document["style"]["group_header_height"])

    @property
    def column_header_height(self) -> int:
        return int(self.document["style"]["column_header_height"])

    @property
    def max_column_width(self) -> int:
        return int(self.document["style"]["max_column_width"])

    @property
    def summary_column_widths(self) -> dict[str, float]:
        return {str(key): float(value) for key, value in self.document["style"]["summary_column_widths"].items()}

    def as_dict(self) -> dict[str, Any]:
        return deepcopy(self.document)


def default_export_profile() -> ExportProfile:
    document = deepcopy(DEFAULT_EXPORT_PROFILE_DOCUMENT)
    _validate(document)
    return ExportProfile(document=document)


def load_export_profile(config_dir: Path, *, strict: bool = False) -> ExportProfile:
    path = config_dir / EXPORT_PROFILE_FILENAME
    if not path.exists():
        return default_export_profile()

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, Mapping):
            raise ValueError("export_profile.json 顶层必须是 JSON 对象")
        document = _deep_merge(DEFAULT_EXPORT_PROFILE_DOCUMENT, raw)
        _validate(document)
        return ExportProfile(document=document, source_path=path)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        if strict:
            raise
        warnings.warn(
            f"无法加载 {path}，继续使用内置标准导出模板: {exc}",
            RuntimeWarning,
            stacklevel=2,
        )
        return default_export_profile()
