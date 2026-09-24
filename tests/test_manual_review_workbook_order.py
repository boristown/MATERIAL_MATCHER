from __future__ import annotations

from material_matcher.services.manual_review_service import ManualReviewService


def _rows(*keys: str) -> list[dict[str, object]]:
    return [{"source_payload": {key: f"v-{index}-{key}" for key in keys}}]


def test_business_key_order_follows_rule_weight_descending():
    document = {
        "rules": [
            {"id": "brand", "source": {"fields": ["品牌"]}, "target": {"fields": ["品牌"]}, "weight": 10},
            {"id": "name", "source": {"fields": ["物料名称"]}, "target": {"fields": ["物料名称"]}, "weight": 80},
            {"id": "spec", "source": {"fields": ["外形尺寸"]}, "target": {"fields": ["外形尺寸"]}, "weight": 10},
        ]
    }
    ordered = ManualReviewService._ordered_business_keys(_rows("品牌", "物料名称", "外形尺寸"), "source_payload", document, "source")
    assert ordered == ["物料名称", "品牌", "外形尺寸"]


def test_critical_rule_jumps_queue_and_unmapped_keys_sink():
    document = {
        "rules": [
            {"id": "code", "source": {"fields": ["物料编码"]}, "target": {"fields": ["物料编码"]}, "weight": 5, "critical": True},
            {"id": "name", "source": {"fields": ["物料名称"]}, "target": {"fields": ["物料名称"]}, "weight": 90},
        ]
    }
    ordered = ManualReviewService._ordered_business_keys(_rows("备注", "物料编码", "物料名称"), "source_payload", document, "source")
    assert ordered[0] == "物料编码" and ordered[1] == "物料名称" and ordered[-1] == "备注"


def test_missing_or_broken_document_falls_back_to_plain_sort():
    ordered = ManualReviewService._ordered_business_keys(_rows("名称", "编码"), "source_payload", {}, "source")
    assert ordered == sorted(["名称", "编码"])
