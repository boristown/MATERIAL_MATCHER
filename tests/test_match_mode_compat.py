import pytest

from material_matcher.domain.models import MatchingConfig


def _document(matcher: str) -> dict[str, object]:
    matcher_options = {"tolerance": 0.01} if matcher == "numeric" else {}
    return {
        "source_id_column": "物料编码",
        "rules": [
            {
                "id": f"rule-{matcher}",
                "source": {"fields": ["名称"]},
                "target": {"fields": ["名称"]},
                "matcher": matcher,
                "weight": 100,
                "matcher_options": matcher_options,
            }
        ],
        "decision": {
            "success_threshold": 88,
            "review_enabled": True,
            "review_threshold": 75,
            "top_n": 5,
        },
    }


@pytest.mark.parametrize("matcher", ["contains", "fuzzy", "hybrid", "numeric"])
def test_legacy_matcher_configs_remain_valid(matcher: str) -> None:
    config = MatchingConfig.model_validate(_document(matcher))
    assert config.rules[0].matcher == matcher


@pytest.mark.parametrize("matcher", ["exact", "semantic"])
def test_business_matcher_configs_are_valid(matcher: str) -> None:
    config = MatchingConfig.model_validate(_document(matcher))
    assert config.rules[0].matcher == matcher
