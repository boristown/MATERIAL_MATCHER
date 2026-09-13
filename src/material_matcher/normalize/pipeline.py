from __future__ import annotations

from dataclasses import dataclass, field
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


def apply_processing_pipeline(
    input_value: object,
    steps: Sequence[Mapping[str, Any]] | None,
) -> ProcessedValue:
    """Apply only the explicitly configured operators, in configured order.

    An absent/empty pipeline is exactly identity. Text such as ``88`` or
    ``N/A`` is never treated as missing unless a ``nullify`` step asks for it.
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
                options=options,
                input_preview=_preview(before),
                output_preview=_preview(after),
            )
        )
    return current
