from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import json as _json
import re
import unicodedata
from typing import Any, Mapping, Sequence

from material_matcher.domain.errors import DomainError


@dataclass(frozen=True)
class TraceItem:
    operator: str
    options: dict[str, object]
    input_preview: str
    output_preview: str


@dataclass
class ProcessedValue:
    raw_value: object
    value: object
    text: str | None
    is_missing: bool
    structured: dict[str, object] = field(default_factory=dict)
    trace: list[TraceItem] = field(default_factory=list)


def _preview(value: object) -> str:
    return "" if value is None else str(value)[:120]


def _dictionary_map(before: object, options: dict[str, object]) -> object:
    if before is None:
        return None
    mapping_raw = options.get("mapping")
    if not isinstance(mapping_raw, Mapping):
        raise DomainError(
            "DICTIONARY_NOT_MATERIALIZED",
            "业务字典尚未解析为运行时映射，请检查字典版本配置",
            status_code=409,
        )
    mapping = {str(key): str(value) for key, value in mapping_raw.items()}
    text = str(before)
    case_sensitive = bool(options.get("case_sensitive", True))
    mode = str(options.get("mode", "exact"))
    on_missing = str(options.get("on_missing", "keep"))

    if mode == "exact":
        if case_sensitive:
            if text in mapping:
                return mapping[text]
        else:
            lowered = {key.lower(): value for key, value in mapping.items()}
            if text.lower() in lowered:
                return lowered[text.lower()]
        if on_missing == "keep":
            return before
        if on_missing == "null":
            return None
        raise DomainError(
            "PROCESSING_PIPELINE_INVALID",
            "dictionary_map 的 on_missing 必须为 keep 或 null",
            status_code=422,
        )

    if mode == "replace":
        if not mapping:
            return before
        keys = sorted(mapping, key=len, reverse=True)
        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = re.compile("|".join(re.escape(key) for key in keys), flags)
        if case_sensitive:
            return pattern.sub(lambda match: mapping[match.group(0)], text)
        lowered = {key.lower(): value for key, value in mapping.items()}
        return pattern.sub(lambda match: lowered[match.group(0).lower()], text)

    raise DomainError(
        "PROCESSING_PIPELINE_INVALID",
        "dictionary_map 的 mode 必须为 exact 或 replace",
        status_code=422,
    )


def _normalize_base_text(before: object, *, case: str = "upper") -> str | None:
    if before is None:
        return None
    text = unicodedata.normalize("NFKC", str(before)).strip()
    if case == "upper":
        text = text.upper()
    elif case == "lower":
        text = text.lower()
    elif case not in {"keep", "none"}:
        raise DomainError(
            "PROCESSING_PIPELINE_INVALID",
            "文本归一化 case 必须为 upper、lower 或 keep",
            status_code=422,
        )
    return text


def _text_normalize(before: object, options: dict[str, object]) -> object:
    text = _normalize_base_text(before, case=str(options.get("case", "upper")))
    if text is None:
        return None
    translations = str.maketrans(
        {
            "，": ",",
            "。": ".",
            "；": ";",
            "：": ":",
            "（": "(",
            "）": ")",
            "【": "[",
            "】": "]",
            "—": "-",
            "–": "-",
            "−": "-",
            "／": "/",
        }
    )
    text = text.translate(translations)
    text = re.sub(r"\s+", " ", text).strip()
    if bool(options.get("compact", False)):
        chars = str(options.get("punctuation", " _-/\\()[]{}.,;:，。；："))
        text = text.translate(str.maketrans({char: "" for char in chars}))
        text = re.sub(r"\s+", "", text)
    return text


def _standard_number_normalize(before: object, options: dict[str, object]) -> object:
    text = _normalize_base_text(before, case="upper")
    if text is None:
        return None
    text = text.translate(str.maketrans({"—": "-", "–": "-", "−": "-", "／": "/"}))
    # Common Chinese standard families are frequently written as GB/T, GBT or GB-T.
    # Keep the operator generic and field-scoped; no customer/material identifiers are embedded.
    prefixes = options.get(
        "t_prefixes",
        ["GB", "JB", "HG", "SJ", "HB", "QJ", "CB", "SY", "NY", "DL", "JT", "TB", "YD", "YY"],
    )
    for prefix in sorted((str(item).upper() for item in prefixes), key=len, reverse=True):
        text = re.sub(rf"(?<![A-Z]){re.escape(prefix)}\s*[-/]?\s*T(?=\s*\d)", f"{prefix}/T", text)
    text = re.sub(r"\s*([/\-.])\s*", r"\1", text)
    if bool(options.get("remove_spaces", True)):
        text = re.sub(r"\s+", "", text)
    else:
        text = re.sub(r"\s+", " ", text).strip()
    return text


def _specification_normalize(before: object, options: dict[str, object]) -> object:
    text = _normalize_base_text(before, case="upper")
    if text is None:
        return None
    text = text.translate(
        str.maketrans(
            {
                "φ": "Φ",
                "ϕ": "Φ",
                "Ø": "Φ",
                "ø": "Φ",
                "∅": "Φ",
                "⌀": "Φ",
                "✕": "×",
                "✖": "×",
                "—": "-",
                "–": "-",
                "−": "-",
            }
        )
    )
    # Convert x/X/* to a multiplication sign only when it acts as a dimension separator.
    text = re.sub(r"(?<=\d)\s*[X*×]\s*(?=\d)", "×", text)
    text = re.sub(r"Φ\s+(?=\d)", "Φ", text)
    if bool(options.get("strip_mm_unit", True)):
        text = re.sub(r"(?<=\d)\s*(?:MM|毫米)(?=$|[^A-Z])", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def _model_normalize(before: object, options: dict[str, object]) -> object:
    text = _normalize_base_text(before, case=str(options.get("case", "upper")))
    if text is None:
        return None
    text = text.translate(str.maketrans({"—": "-", "–": "-", "−": "-", "／": "/"}))
    text = re.sub(r"\s+", "", text)
    if bool(options.get("strip_wrapping_punctuation", False)):
        text = text.strip("()[]{}")
    return text


def _manufacturer_normalize(before: object, options: dict[str, object]) -> object:
    text = _normalize_base_text(before, case=str(options.get("case", "upper")))
    if text is None:
        return None
    text = re.sub(r"[\s_\-—–/\\()（）\[\]【】,，.;；:：]+", "", text)
    if bool(options.get("strip_legal_suffix", True)):
        suffixes = options.get(
            "suffixes",
            ["股份有限公司", "有限责任公司", "集团有限公司", "集团公司", "有限公司", "公司"],
        )
        changed = True
        while changed and text:
            changed = False
            for suffix in sorted((str(item) for item in suffixes), key=len, reverse=True):
                if suffix and text.endswith(suffix) and len(text) > len(suffix):
                    text = text[: -len(suffix)]
                    changed = True
                    break
    return text


def _trace_options(operator: str, options: dict[str, object]) -> dict[str, object]:
    if operator != "dictionary_map":
        return options
    # Do not duplicate a potentially large dictionary in every candidate trace.
    return {key: value for key, value in options.items() if key not in {"mapping"}}


_PIPELINE_MEMO: "OrderedDict[tuple, ProcessedValue]" = OrderedDict()
_PIPELINE_MEMO_LIMIT = 200_000


def _step_key(step: Mapping[str, Any]) -> dict[str, object]:
    options = dict(step.get("options") or {})
    if options.get("dictionary_sha256") or options.get("dictionary_id"):
        # The version digest pins the mapping content; drop the inline payload from the key.
        options.pop("mapping", None)
    return {"op": str(step.get("op")), "options": options}


def clear_pipeline_memo() -> None:
    _PIPELINE_MEMO.clear()


_STEPS_CANONICAL: "OrderedDict[int, tuple[object, str]]" = OrderedDict()


def _steps_canonical(steps: Sequence[Mapping[str, Any]]) -> str:
    # Pipeline lists are immutable pydantic materializations per task snapshot,
    # so identity caching is safe; a strong reference keeps id() from being reused.
    sid = id(steps)
    hit = _STEPS_CANONICAL.get(sid)
    if hit is not None and hit[0] is steps:
        return hit[1]
    canonical = _json.dumps([_step_key(step) for step in steps], sort_keys=True, ensure_ascii=False, default=str)
    if len(_STEPS_CANONICAL) > 4096:
        _STEPS_CANONICAL.popitem(last=False)
    _STEPS_CANONICAL[sid] = (steps, canonical)
    return canonical


def apply_processing_pipeline(
    input_value: object,
    steps: Sequence[Mapping[str, Any]] | None,
) -> ProcessedValue:
    """Memoized wrapper for pure, explicitly configured normalization pipelines."""
    if not steps:
        return _apply_pipeline_uncached(input_value, steps)
    key = (type(input_value).__name__, repr(input_value), _steps_canonical(steps))
    cached = _PIPELINE_MEMO.get(key)
    if cached is not None:
        return ProcessedValue(
            raw_value=cached.raw_value,
            value=cached.value,
            text=cached.text,
            is_missing=cached.is_missing,
            structured=dict(cached.structured),
            trace=list(cached.trace),
        )
    result = _apply_pipeline_uncached(input_value, steps)
    _PIPELINE_MEMO[key] = result
    if len(_PIPELINE_MEMO) > _PIPELINE_MEMO_LIMIT:
        _PIPELINE_MEMO.popitem(last=False)
    return result


def _apply_pipeline_uncached(
    input_value: object,
    steps: Sequence[Mapping[str, Any]] | None,
) -> ProcessedValue:
    """Apply only explicitly configured operators, in configured order.

    An absent/empty pipeline is exactly identity. Text such as ``88`` or
    ``N/A`` is never treated as missing unless a ``nullify`` step asks for it.
    Dictionary behavior is explicit as well: aliases are supplied by immutable
    dictionary versions rather than embedded customer-specific code.
    """

    current = ProcessedValue(
        raw_value=input_value,
        value=input_value,
        text=None if input_value is None else str(input_value),
        is_missing=input_value is None,
    )
    for step in steps or ():
        operator = str(step.get("op", "identity"))
        options = dict(step.get("options") or {})
        before = current.value

        if operator == "identity":
            after = before
        elif operator == "trim":
            after = None if before is None else str(before).strip()
        elif operator == "unicode_normalize":
            after = None if before is None else unicodedata.normalize(
                str(options.get("form", "NFKC")), str(before)
            )
        elif operator == "case_map":
            text = None if before is None else str(before)
            mode = str(options.get("mode", "lower"))
            if text is None:
                after = None
            elif mode == "upper":
                after = text.upper()
            elif mode == "lower":
                after = text.lower()
            else:
                raise DomainError(
                    "PROCESSING_PIPELINE_INVALID",
                    "大小写处理模式必须为 lower 或 upper",
                    status_code=422,
                )
        elif operator == "whitespace_map":
            after = None if before is None else re.sub(
                r"\s+", str(options.get("replacement", " ")), str(before)
            )
        elif operator == "punctuation_map":
            chars = str(options.get("chars", ""))
            replacement = str(options.get("replacement", ""))
            after = None if before is None else str(before).translate(
                str.maketrans({char: replacement for char in chars})
            )
        elif operator == "text_normalize":
            after = _text_normalize(before, options)
        elif operator == "standard_number_normalize":
            after = _standard_number_normalize(before, options)
        elif operator == "specification_normalize":
            after = _specification_normalize(before, options)
        elif operator == "model_normalize":
            after = _model_normalize(before, options)
        elif operator == "manufacturer_normalize":
            after = _manufacturer_normalize(before, options)
        elif operator == "nullify":
            values = [str(value) for value in options.get("values", [])]
            case_sensitive = bool(options.get("case_sensitive", True))
            text = None if before is None else str(before)
            probe = text if case_sensitive else text.lower() if text else text
            expected = values if case_sensitive else [value.lower() for value in values]
            after = None if probe in expected else before
        elif operator == "regex_replace":
            after = None if before is None else re.sub(
                str(options.get("pattern", "")),
                str(options.get("replacement", "")),
                str(before),
            )
        elif operator == "substring":
            text = None if before is None else str(before)
            start = int(options.get("start", 0))
            end = options.get("end")
            after = None if text is None else text[start : int(end) if end is not None else None]
        elif operator == "dictionary_map":
            after = _dictionary_map(before, options)
        else:
            raise DomainError(
                "PROCESSING_OPERATOR_NOT_FOUND",
                f"不支持的数据处理操作：{operator}",
                status_code=422,
            )

        current.value = after
        current.text = None if after is None else str(after)
        current.is_missing = after is None
        current.trace.append(
            TraceItem(
                operator=operator,
                options=_trace_options(operator, options),
                input_preview=_preview(before),
                output_preview=_preview(after),
            )
        )
    return current
