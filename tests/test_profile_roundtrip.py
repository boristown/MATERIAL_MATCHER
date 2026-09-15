from __future__ import annotations

from pathlib import Path

from material_matcher.services.profile_service import ProfileService
from material_matcher.storage.metadata import MetadataRepository


def test_complex_profile_roundtrip_preserves_multi_fields_and_advanced_options(tmp_path: Path) -> None:
    meta = MetadataRepository(tmp_path / "meta.db")
    service = ProfileService(meta)
    document = {
        "source_id_column": "物料号",
        "scope_mode": "MAPPED",
        "scope": {
            "source_field": "客户分类",
            "target_field": "集团分类",
            "mapping": {"A": ["G01", "G02"]},
        },
        "rules": [
            {
                "id": "desc-model",
                "source": {
                    "fields": ["物料名称", "规格型号"],
                    "combine": "concat",
                    "separator": " | ",
                    "pipeline": [{"op": "trim", "options": {}}],
                },
                "target": {
                    "fields": ["集团名称", "集团规格"],
                    "combine": "best_of",
                    "separator": " ",
                    "pipeline": [{"op": "unicode_normalize", "options": {"form": "NFKC"}}],
                },
                "matcher": "hybrid",
                "weight": 80,
                "critical": True,
                "matcher_options": {"alpha": 0.7},
            }
        ],
        "decision": {"success_threshold": 90, "review_enabled": True, "review_threshold": 75, "top_n": 10},
        "retrieval": {
            "mode": "auto",
            "provider": "onnx_local",
            "model_id": "BAAI/bge-base-zh-v1.5",
            "dimensions": 768,
            "max_length": 192,
            "precision": "int8",
            "retrieval_top_k": 250,
            "oversample": 6,
        },
        "advanced": {"business_note": "keep-me", "custom_flag": True},
    }

    profile_id = str(service.create("复杂方案", document)["profile_id"])
    published = service.publish(profile_id)
    restored = published["document"]

    assert restored["scope"]["mapping"] == {"A": ["G01", "G02"]}
    assert restored["rules"][0]["source"]["fields"] == ["物料名称", "规格型号"]
    assert restored["rules"][0]["source"]["pipeline"][0]["op"] == "trim"
    assert restored["rules"][0]["target"]["combine"] == "best_of"
    assert restored["rules"][0]["matcher_options"] == {"alpha": 0.7}
    assert restored["retrieval"]["max_length"] == 192
    assert restored["retrieval"]["oversample"] == 6
    assert restored["advanced"] == {"business_note": "keep-me", "custom_flag": True}
