from __future__ import annotations

import hashlib
import json
from typing import Literal, Mapping

from material_matcher.domain.models import FieldSide, MatchingConfig
from material_matcher.matching.scorer import prepare_side_values

SideName = Literal["source", "target"]


def _side_for_rule(rule: object, side: SideName) -> FieldSide:
    return getattr(rule, side)


def build_retrieval_text(row: Mapping[str, object], config: MatchingConfig, side: SideName) -> str:
    explicit = getattr(config.retrieval, side)
    sides: list[tuple[FieldSide, Mapping[str, str] | None]]
    if explicit is not None:
        sides = [(explicit, None)]
    else:
        sides = [
            (
                _side_for_rule(rule, side),
                rule.value_mapping if side == "source" else None,
            )
            for rule in config.rules
            if rule.weight > 0
        ]
    parts: list[str] = []
    seen: set[str] = set()
    for field_side, value_mapping in sides:
        for processed in prepare_side_values(row, field_side, value_mapping=value_mapping):
            text = processed.text
            if text is None or text == "" or text in seen:
                continue
            seen.add(text); parts.append(text)
    return " ".join(parts)


def retrieval_text_signature(config: MatchingConfig, side: SideName) -> str:
    explicit = getattr(config.retrieval, side)
    if explicit is not None:
        payload: object = {"explicit": explicit.model_dump(mode="json")}
    else:
        payload = {
            "derived_from_rules": [
                {
                    "side": _side_for_rule(rule, side).model_dump(mode="json"),
                    "value_mapping": rule.value_mapping if side == "source" else {},
                }
                for rule in config.rules if rule.weight > 0
            ]
        }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
