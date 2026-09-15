from __future__ import annotations

from pathlib import Path
import random
from typing import Literal, Protocol, Sequence

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.batching import profile_token_lengths, token_budget_batches
from material_matcher.embedding.text import build_retrieval_text, retrieval_text_signature
from material_matcher.ingestion.reader import detect_layout, iter_tabular_rows

SideName = Literal["source", "target"]


class TokenLengthCounter(Protocol):
    def token_lengths(self, texts: Sequence[str]) -> list[int]: ...


def _padding_efficiency(lengths: Sequence[int], batches: Sequence[Sequence[int]]) -> float:
    if not lengths or not batches:
        return 1.0
    actual = sum(max(1, int(length)) for length in lengths)
    padded = 0
    for batch in batches:
        if not batch:
            continue
        longest = max(max(1, int(lengths[index])) for index in batch)
        padded += longest * len(batch)
    return round(actual / max(1, padded), 6)


def profile_retrieval_texts(
    path: Path,
    *,
    config: MatchingConfig,
    side: SideName,
    token_counter: TokenLengthCounter,
    sample_rows: int = 4096,
    scan_limit: int = 100_000,
    max_batch_size: int = 128,
    token_budget: int = 16_384,
    seed: int = 20260915,
) -> dict[str, object]:
    """Profile actual retrieval text with bounded memory.

    Rows are streamed and a deterministic reservoir is maintained over non-empty
    retrieval texts. ``scan_limit`` intentionally bounds synchronous preflight
    work; the response reports whether EOF was reached so a partial scan cannot
    be mistaken for a full-file profile.
    """
    sample_limit = max(1, int(sample_rows))
    scan_cap = max(sample_limit, int(scan_limit))
    rng = random.Random(seed)
    reservoir: list[str] = []
    scanned_rows = 0
    nonempty_rows = 0
    empty_rows = 0
    hit_scan_limit = False

    for row in iter_tabular_rows(path):
        if scanned_rows >= scan_cap:
            hit_scan_limit = True
            break
        scanned_rows += 1
        text = build_retrieval_text(row, config, side)
        if not text:
            empty_rows += 1
            continue
        nonempty_rows += 1
        if len(reservoir) < sample_limit:
            reservoir.append(text)
            continue
        replacement = rng.randrange(nonempty_rows)
        if replacement < sample_limit:
            reservoir[replacement] = text

    layout = detect_layout(path)
    estimated_rows = max(0, int(layout.row_count_estimate))
    scan_complete = not hit_scan_limit
    coverage_ratio: float | None
    if scan_complete:
        coverage_ratio = 1.0
    elif estimated_rows > scanned_rows:
        coverage_ratio = round(scanned_rows / estimated_rows, 6)
    else:
        coverage_ratio = None

    lengths = token_counter.token_lengths(reservoir) if reservoir else []
    token_profile = profile_token_lengths(lengths)
    current_max_length = int(config.retrieval.max_length)
    clipped = [max(1, min(int(length), current_max_length)) for length in lengths]
    batches = token_budget_batches(
        clipped,
        max_batch_size=max(1, int(max_batch_size)),
        token_budget=max(1, int(token_budget)),
    )

    unique_length_by_text: dict[str, int] = {}
    for text, length in zip(reservoir, lengths):
        unique_length_by_text.setdefault(text, int(length))
    unique_lengths = list(unique_length_by_text.values())
    unique_profile = profile_token_lengths(unique_lengths)

    return {
        "side": side,
        "sampling_method": "bounded_reservoir_v1",
        "retrieval_text_signature": retrieval_text_signature(config, side),
        "estimated_rows": estimated_rows,
        "scanned_rows": scanned_rows,
        "scan_limit": scan_cap,
        "scan_complete": scan_complete,
        "coverage_ratio": coverage_ratio,
        "nonempty_rows": nonempty_rows,
        "empty_rows": empty_rows,
        "empty_rate": round(empty_rows / max(1, scanned_rows), 6),
        "sampled_rows": len(reservoir),
        "unique_sampled_texts": len(unique_length_by_text),
        "duplicate_rate": round(1.0 - len(unique_length_by_text) / max(1, len(reservoir)), 6),
        "token_profile": token_profile.to_dict(),
        "unique_text_token_profile": unique_profile.to_dict(),
        "current_max_length": current_max_length,
        "current_truncation_rate": round(
            sum(1 for length in lengths if int(length) > current_max_length) / max(1, len(lengths)),
            6,
        ),
        "batching": {
            "max_batch_size": max(1, int(max_batch_size)),
            "token_budget": max(1, int(token_budget)),
            "planned_micro_batches": len(batches),
            "padding_efficiency": _padding_efficiency(clipped, batches),
        },
    }
