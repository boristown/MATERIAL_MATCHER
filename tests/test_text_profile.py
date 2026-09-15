from __future__ import annotations

from pathlib import Path

from material_matcher.domain.models import MatchingConfig
from material_matcher.embedding.profiling import profile_retrieval_texts
from material_matcher.embedding.providers import DeterministicEmbeddingProvider


def _config(max_length: int = 16) -> MatchingConfig:
    return MatchingConfig.model_validate(
        {
            "source_id_column": "物料号",
            "rules": [
                {
                    "id": "name",
                    "source": {"fields": ["物料名称", "型号"], "combine": "concat"},
                    "target": {"fields": ["物料名称", "型号"], "combine": "concat"},
                    "matcher": "fuzzy",
                    "weight": 100,
                }
            ],
            "retrieval": {
                "max_length": max_length,
                "source": {"fields": ["物料名称", "型号"], "combine": "concat"},
                "target": {"fields": ["物料名称", "型号"], "combine": "concat"},
            },
        }
    )


def test_real_text_profile_streams_with_bounded_reservoir(tmp_path: Path) -> None:
    path = tmp_path / "materials.csv"
    lines = ["物料号,物料名称,型号"]
    for index in range(30):
        name = "工业电阻" if index % 3 else ""
        model = f"R{index:03d}" if index % 5 else "LONG-MODEL-" + "X" * 30
        lines.append(f"{index:06d},{name},{model}")
    path.write_text("\n".join(lines), encoding="utf-8-sig")

    result = profile_retrieval_texts(
        path,
        config=_config(),
        side="source",
        token_counter=DeterministicEmbeddingProvider(32),
        sample_rows=8,
        scan_limit=12,
        max_batch_size=4,
        token_budget=40,
    )

    assert result["sampling_method"] == "bounded_reservoir_v1"
    assert result["scanned_rows"] == 12
    assert result["scan_complete"] is False
    assert result["coverage_ratio"] is None  # CSV inspector does not know total rows reliably.
    assert result["sampled_rows"] == 8
    assert result["token_profile"]["count"] == 8
    assert result["token_profile"]["maximum"] > 16
    assert result["current_truncation_rate"] > 0
    assert result["batching"]["planned_micro_batches"] >= 2
    assert 0 < result["batching"]["padding_efficiency"] <= 1


def test_real_text_profile_marks_full_scan_and_duplicate_rate(tmp_path: Path) -> None:
    path = tmp_path / "small.csv"
    path.write_text(
        "物料号,物料名称,型号\n"
        "0001,电阻,R10\n"
        "0002,电阻,R10\n"
        "0003,电容,C10\n",
        encoding="utf-8-sig",
    )
    result = profile_retrieval_texts(
        path,
        config=_config(128),
        side="source",
        token_counter=DeterministicEmbeddingProvider(32),
        sample_rows=10,
        scan_limit=100,
        max_batch_size=8,
        token_budget=256,
    )
    assert result["scan_complete"] is True
    assert result["coverage_ratio"] == 1.0
    assert result["sampled_rows"] == 3
    assert result["unique_sampled_texts"] == 2
    assert result["duplicate_rate"] == 0.333333
    assert result["current_truncation_rate"] == 0.0
