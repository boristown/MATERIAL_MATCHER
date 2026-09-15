from __future__ import annotations

import numpy as np

from material_matcher.vector.quality import exact_topk, recall_at_k


def test_exact_topk_and_recall_metrics() -> None:
    targets = np.asarray(
        [
            [1.0, 0.0],
            [0.9, 0.1],
            [0.0, 1.0],
            [-1.0, 0.0],
        ],
        dtype=np.float32,
    )
    query = np.asarray([1.0, 0.0], dtype=np.float32)
    exact = exact_topk(targets, query, 3)
    assert exact.tolist()[:2] == [0, 1]

    metrics = recall_at_k([0, 2, 1], exact, ks=(1, 2, 3))
    assert metrics[1] == 1.0
    assert metrics[2] == 0.5
    assert metrics[3] == 1.0
