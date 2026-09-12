from __future__ import annotations

import csv
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .matching import normalize_text, read_excel_rows


class PipelineError(ValueError):
    pass


@dataclass
class Dataset:
    name: str
    columns: list[str]
    rows: list[dict[str, Any]]


def load_dataset(name: str, config: dict[str, Any], base_dir: Path | None = None) -> Dataset:
    adapter = str(config.get("adapter") or config.get("plugin") or "excel").lower()
    raw_path = config.get("path")
    if not raw_path:
        raise PipelineError(f"dataset {name} missing path")
    path = Path(raw_path)
    if base_dir and not path.is_absolute():
        path = base_dir / path
    options = config.get("options") or {}

    if adapter == "excel":
        columns, rows = read_excel_rows(
            path,
            options.get("sheet"),
            int(options.get("header_row", 1)),
            int(options["max_rows"]) if options.get("max_rows") else None,
        )
        return Dataset(name=name, columns=columns, rows=rows)

    if adapter == "csv":
        encoding = str(options.get("encoding", "utf-8-sig"))
        delimiter = str(options.get("delimiter", ","))
        with path.open("r", encoding=encoding, newline="") as handle:
            reader = csv.DictReader(handle, delimiter=delimiter)
            rows = [dict(row) for row in reader]
            return Dataset(name=name, columns=list(reader.fieldnames or []), rows=rows)

    raise PipelineError(f"unsupported datasource adapter: {adapter}")


def join_datasets(left: Dataset, right: Dataset, config: dict[str, Any]) -> Dataset:
    join_type = str(config.get("type", "left")).lower()
    if join_type not in {"left", "inner"}:
        raise PipelineError(f"unsupported join type: {join_type}")
    keys = config.get("keys") or []
    if not keys:
        raise PipelineError("join requires keys")
    max_matches = int(config.get("max_matches_per_left", 20))
    select = config.get("select")
    prefix = str(config.get("right_prefix", f"{right.name}."))

    def key_for(row: dict[str, Any], side: str) -> tuple[str, ...]:
        values = []
        for item in keys:
            field = item.get(side)
            if not field:
                raise PipelineError(f"join key missing {side} field")
            values.append(normalize_text(row.get(str(field))))
        return tuple(values)

    right_index: dict[tuple[str, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in right.rows:
        right_index[key_for(row, "right")].append(row)

    output: list[dict[str, Any]] = []
    selected_right = list(select) if isinstance(select, list) else right.columns
    for left_row in left.rows:
        matches = right_index.get(key_for(left_row, "left"), [])
        if len(matches) > max_matches:
            raise PipelineError(
                f"join explosion: one left row matched {len(matches)} right rows, limit={max_matches}"
            )
        if not matches:
            if join_type == "left":
                output.append(dict(left_row))
            continue
        for right_row in matches:
            merged = dict(left_row)
            for column in selected_right:
                value = right_row.get(column)
                if column not in merged:
                    merged[column] = value
                else:
                    merged[f"{prefix}{column}"] = value
            output.append(merged)

    columns = list(left.columns)
    for column in selected_right:
        output_name = column if column not in columns else f"{prefix}{column}"
        if output_name not in columns:
            columns.append(output_name)
    return Dataset(name=str(config.get("id") or f"{left.name}_{right.name}"), columns=columns, rows=output)


def apply_transform(row: dict[str, Any], expression: dict[str, Any], dictionaries: dict[str, dict[str, str]] | None = None) -> Any:
    op = str(expression.get("op", "copy"))
    dictionaries = dictionaries or {}

    def field(name: str) -> Any:
        return row.get(name)

    if op == "copy":
        return field(str(expression.get("field", "")))
    if op == "constant":
        return expression.get("value")
    if op == "concat":
        separator = str(expression.get("separator", " "))
        values = [normalize_text(field(str(name))) for name in expression.get("fields", [])]
        values = [value for value in values if value or not expression.get("skip_empty", True)]
        if expression.get("deduplicate", False):
            values = list(dict.fromkeys(values))
        return separator.join(values)
    if op == "coalesce":
        for name in expression.get("fields", []):
            value = field(str(name))
            if normalize_text(value):
                return value
        return ""
    if op == "trim":
        return str(field(str(expression.get("field", ""))) or "").strip()
    if op == "lower":
        return str(field(str(expression.get("field", ""))) or "").lower()
    if op == "upper":
        return str(field(str(expression.get("field", ""))) or "").upper()
    if op == "replace":
        value = str(field(str(expression.get("field", ""))) or "")
        return value.replace(str(expression.get("old", "")), str(expression.get("new", "")))
    if op == "regex_replace":
        value = str(field(str(expression.get("field", ""))) or "")
        return re.sub(str(expression.get("pattern", "")), str(expression.get("replacement", "")), value)
    if op == "regex_extract":
        value = str(field(str(expression.get("field", ""))) or "")
        match = re.search(str(expression.get("pattern", "")), value)
        if not match:
            return ""
        group = int(expression.get("group", 0))
        return match.group(group)
    if op == "value_map":
        value = str(field(str(expression.get("field", ""))) or "")
        mapping = expression.get("mapping") or {}
        return mapping.get(value, expression.get("default", value))
    if op == "dictionary_map":
        value = str(field(str(expression.get("field", ""))) or "")
        dictionary = dictionaries.get(str(expression.get("dictionary", "")), {})
        return dictionary.get(value, dictionary.get(normalize_text(value), value))
    if op == "nullify":
        value = field(str(expression.get("field", "")))
        tokens = {normalize_text(item) for item in expression.get("tokens", [])}
        return "" if normalize_text(value) in tokens else value
    if op == "join_unique":
        separator = str(expression.get("separator", " "))
        values = []
        for name in expression.get("fields", []):
            value = normalize_text(field(str(name)))
            if value and value not in values:
                values.append(value)
        return separator.join(values)
    raise PipelineError(f"unsupported transform op: {op}")


def apply_transforms(dataset: Dataset, transforms: dict[str, dict[str, Any]], dictionaries: dict[str, dict[str, str]] | None = None) -> Dataset:
    if not transforms:
        return dataset
    rows: list[dict[str, Any]] = []
    for raw in dataset.rows:
        row = dict(raw)
        for output_field, expression in transforms.items():
            row[output_field] = apply_transform(row, expression, dictionaries)
        rows.append(row)
    columns = list(dataset.columns)
    for name in transforms:
        if name not in columns:
            columns.append(name)
    return Dataset(name=dataset.name, columns=columns, rows=rows)


def route_record(row: dict[str, Any], routing: dict[str, Any]) -> dict[str, Any] | None:
    if not routing:
        return None
    field_name = routing.get("by_source_field") or routing.get("by")
    routes = routing.get("routes") or []
    value = row.get(str(field_name)) if field_name else None
    normalized_value = normalize_text(value)
    for route in routes:
        values = route.get("values")
        if values is not None and normalized_value in {normalize_text(item) for item in values}:
            return route
        condition = route.get("when") or {}
        if condition and _matches_condition(row, condition):
            return route
    default = routing.get("default")
    return default if isinstance(default, dict) else None


def _matches_condition(row: dict[str, Any], condition: dict[str, Any]) -> bool:
    for field_name, expected in condition.items():
        actual = normalize_text(row.get(field_name))
        if isinstance(expected, list):
            if actual not in {normalize_text(item) for item in expected}:
                return False
        elif actual != normalize_text(expected):
            return False
    return True


def execute_dataset_graph(profile: dict[str, Any], base_dir: Path | None = None) -> dict[str, Dataset]:
    dataset_configs = profile.get("datasets") or {}
    datasets = {name: load_dataset(name, config, base_dir) for name, config in dataset_configs.items()}
    for join in profile.get("joins") or []:
        left_name = str(join.get("left", ""))
        right_name = str(join.get("right", ""))
        if left_name not in datasets or right_name not in datasets:
            raise PipelineError(f"join dataset missing: {left_name}/{right_name}")
        joined = join_datasets(datasets[left_name], datasets[right_name], join)
        datasets[joined.name] = joined
    return datasets
