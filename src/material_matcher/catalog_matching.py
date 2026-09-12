from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from .bbq import EmbeddedBBQFlatIndex
from .catalog_index import CatalogStore
from .embedding import create_embedding_provider
from .matching import MatchConfig, _combined, _row_score, normalize_text, read_excel_rows


def _source_text(row: dict[str, Any], config: MatchConfig) -> str:
    parts: list[str] = []
    for rule in config.mappings:
        value = normalize_text(_combined(row, rule.source_header))
        if value and value not in parts:
            parts.append(value)
    return " | ".join(parts)


def _target_groups_for_source(row: dict[str, Any], config: MatchConfig) -> list[str] | None:
    if config.group_mode == "global":
        return None
    if not config.source_group_column:
        return []
    source_group = normalize_text(row.get(config.source_group_column))
    if not source_group:
        return []
    if config.group_mode == "strict":
        return [source_group]
    return list(config.group_mapping.get(source_group, []))


def run_matching_catalog(
    source_path: Path,
    sqlite_path: Path,
    index_dir: Path,
    raw_config: dict[str, Any],
    *,
    embedding_config: dict[str, Any] | None = None,
    max_source_rows: int | None = None,
) -> dict[str, Any]:
    """Run matching using the persistent 1-bit BBQ catalog index.

    Queries are bucketed by group scope so rows with the same group filter are
    searched in one vectorized batch rather than looping one query at a time.
    """
    config = MatchConfig.from_dict(raw_config)
    source_headers, source_rows = read_excel_rows(
        source_path,
        config.source_sheet,
        config.source_header_row,
        max_source_rows,
    )
    if config.group_mode != "global" and (
        not config.source_group_column or config.source_group_column not in source_headers
    ):
        raise ValueError("按物料组匹配时，客户物料组字段不存在或未配置")

    index = EmbeddedBBQFlatIndex.load(index_dir, mmap=True)
    store = CatalogStore(sqlite_path)
    provider = create_embedding_provider(embedding_config)
    if provider.dimensions != index.dimensions:
        raise ValueError(
            f"embedding dimensions mismatch: provider={provider.dimensions}, index={index.dimensions}"
        )

    buckets: dict[tuple[str, ...] | None, list[int]] = defaultdict(list)
    for idx, row in enumerate(source_rows):
        groups = _target_groups_for_source(row, config)
        key = None if groups is None else tuple(sorted(normalize_text(group) for group in groups if normalize_text(group)))
        buckets[key].append(idx)

    candidate_rows: dict[int, list[int]] = {idx: [] for idx in range(len(source_rows))}
    for group_key, source_indices in buckets.items():
        if group_key is not None and not group_key:
            continue
        allowed = None if group_key is None else store.group_candidate_indices(list(group_key))
        if allowed is not None and len(allowed) == 0:
            continue
        texts = [_source_text(source_rows[idx], config) for idx in source_indices]
        query_vectors = provider.encode(texts)
        hit_batches = index.search_batch(
            query_vectors,
            top_k=config.candidate_limit,
            candidate_indices=allowed,
            rerank=False,
        )
        for source_idx, hits in zip(source_indices, hit_batches, strict=True):
            candidate_rows[source_idx] = [int(hit.item_id) for hit in hits]

    all_row_ids = sorted({row_id for ids in candidate_rows.values() for row_id in ids})
    targets = store.fetch_rows(all_row_ids)
    output_rows: list[dict[str, Any]] = []
    matched = review = unmatched = 0

    for source_idx, source in enumerate(source_rows, start=1):
        ranked: list[tuple[float, int, list[dict[str, Any]]]] = []
        for row_id in candidate_rows.get(source_idx - 1, []):
            target = targets.get(row_id)
            if not target:
                continue
            score, evidence = _row_score(source, target, config.mappings)
            ranked.append((score, row_id, evidence))
        ranked.sort(key=lambda item: item[0], reverse=True)
        top = ranked[: config.top_n]
        best_score = top[0][0] if top else 0.0
        best_target = targets.get(top[0][1], {}) if top else {}
        if best_score > config.threshold:
            status = "MATCHED"
            matched += 1
        elif config.review_threshold is not None and best_score > config.review_threshold:
            status = "REVIEW"
            review += 1
        else:
            status = "UNMATCHED"
            unmatched += 1
        group_code = best_target.get(config.group_code_column, "") if status == "MATCHED" else ""
        candidates = []
        for rank, (score, row_id, evidence) in enumerate(top, start=1):
            target = targets.get(row_id, {})
            candidates.append(
                {
                    "rank": rank,
                    "score": round(score, 6),
                    "group_code": target.get(config.group_code_column, ""),
                    "target": target,
                    "evidence": evidence,
                }
            )
        output_rows.append(
            {
                "source_index": source_idx,
                "source": source,
                "source_id": source.get(config.source_id_column, "") if config.source_id_column else "",
                "status": status,
                "matched_group_code": group_code,
                "score": round(best_score, 6),
                "candidates": candidates,
            }
        )

    total = len(output_rows)
    return {
        "summary": {
            "source_rows": total,
            "target_rows": index.count,
            "matched": matched,
            "review": review,
            "unmatched": unmatched,
            "matched_rate": round(matched / total, 6) if total else 0.0,
            "threshold": config.threshold,
            "review_threshold": config.review_threshold,
            "group_mode": config.group_mode,
            "retrieval": "embedded_bbq_flat",
        },
        "source_headers": source_headers,
        "rows": output_rows,
    }
