from __future__ import annotations

import json
from pathlib import Path
from typing import Mapping, Sequence

import numpy as np

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.cache import EmbeddingCache
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature


def embedding_rekey(
    *,
    index_dir: Path,
    cache: EmbeddingCache,
    config: MatchingConfig,
    dry_run: bool = False,
) -> dict[str, object]:
    """Re-register legacy (signature+text) cache entries under the model-scoped
    text key, using existing target index records as the text source.

    Run this BEFORE changing a plan whose retrieval text is (mostly) unchanged,
    so plan edits stop triggering a full 1M-row re-embedding.
    """
    old_signature = retrieval_text_signature(config, "target")
    scanned_indexes = 0
    scanned_rows = 0
    texts: dict[str, None] = {}
    for metadata_path in sorted(Path(index_dir).rglob("metadata.json")):
        try:
            meta = json.loads(metadata_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        if str(meta.get("target_text_signature") or "") != old_signature:
            continue
        records_path = metadata_path.parent / "records.jsonl"
        if not records_path.exists():
            continue
        scanned_indexes += 1
        with records_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                scanned_rows += 1
                try:
                    row = json.loads(line)
                except Exception:  # noqa: BLE001
                    continue
                if not isinstance(row, Mapping):
                    continue
                text = build_retrieval_text(row, config, "target")
                if text:
                    texts.setdefault(text, None)
    unique_texts = list(texts)
    migrated = 0
    already = 0
    legacy_found = 0
    if unique_texts:
        legacy_keys = [cache.key(text, old_signature) for text in unique_texts]
        found = cache.get_many(legacy_keys)
        legacy_found = len(found)
        model_keys = [cache.model_key(text) for text in unique_texts]
        existing = cache.get_many(model_keys)
        items: list[tuple[str, np.ndarray]] = []
        for text, legacy_key, model_key in zip(unique_texts, legacy_keys, model_keys):
            vector = found.get(legacy_key)
            if vector is None:
                continue
            if model_key in existing:
                already += 1
                continue
            items.append((model_key, vector))
        if items and not dry_run:
            cache.put_many(items)
        migrated = len(items)
    return {
        "ok": True,
        "old_signature": old_signature,
        "index_dirs_scanned": scanned_indexes,
        "records_rows": scanned_rows,
        "unique_texts": len(unique_texts),
        "legacy_vectors_found": legacy_found,
        "legacy_vectors_missing": len(unique_texts) - legacy_found,
        "migrated": migrated,
        "already_present": already,
        "dry_run": bool(dry_run),
    }
