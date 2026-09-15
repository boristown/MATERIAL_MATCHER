from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

import numpy as np


@dataclass(frozen=True)
class TokenLengthProfile:
    count: int
    p50: int
    p95: int
    p99: int
    p999: int
    maximum: int
    recommended_max_length: int
    truncation_rates: dict[str, float]

    def to_dict(self) -> dict[str, object]:
        return {
            "count": self.count,
            "p50": self.p50,
            "p95": self.p95,
            "p99": self.p99,
            "p999": self.p999,
            "maximum": self.maximum,
            "recommended_max_length": self.recommended_max_length,
            "truncation_rates": self.truncation_rates,
        }


def profile_token_lengths(lengths: Sequence[int], candidates: Sequence[int] = (128, 192, 256, 512)) -> TokenLengthProfile:
    if not lengths:
        return TokenLengthProfile(0, 0, 0, 0, 0, 0, int(candidates[0]), {str(item): 0.0 for item in candidates})
    values = np.asarray([max(0, int(item)) for item in lengths], dtype=np.int64)

    def percentile(q: float) -> int:
        return int(np.ceil(float(np.percentile(values, q))))

    p99 = percentile(99)
    ordered = sorted({max(1, int(item)) for item in candidates})
    recommended = next((item for item in ordered if item >= p99), ordered[-1])
    rates = {str(item): round(float(np.mean(values > item)), 6) for item in ordered}
    return TokenLengthProfile(
        count=int(values.size),
        p50=percentile(50),
        p95=percentile(95),
        p99=p99,
        p999=percentile(99.9),
        maximum=int(values.max()),
        recommended_max_length=recommended,
        truncation_rates=rates,
    )


def token_budget_batches(lengths: Sequence[int], *, max_batch_size: int, token_budget: int) -> list[list[int]]:
    """Return original indexes grouped by similar token length.

    Sorting by length reduces padding. A batch is accepted only when
    ``rows * longest_sequence <= token_budget`` and row count stays below
    ``max_batch_size``. The caller restores the original output order.
    """
    if not lengths:
        return []
    row_limit = max(1, int(max_batch_size))
    budget = max(1, int(token_budget))
    order = sorted(range(len(lengths)), key=lambda index: (max(1, int(lengths[index])), index))
    result: list[list[int]] = []
    active: list[int] = []
    active_max = 0
    for index in order:
        length = max(1, int(lengths[index]))
        proposed_max = max(active_max, length)
        proposed_rows = len(active) + 1
        if active and (proposed_rows > row_limit or proposed_rows * proposed_max > budget):
            result.append(active)
            active = []
            active_max = 0
        active.append(index)
        active_max = max(active_max, length)
        if len(active) >= row_limit or len(active) * active_max >= budget:
            result.append(active)
            active = []
            active_max = 0
    if active:
        result.append(active)
    return result
