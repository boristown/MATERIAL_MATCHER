import pytest
from pydantic import ValidationError

from material_matcher.domain.models import MatchingConfig


def test_weight_range_is_0_to_100() -> None:
    with pytest.raises(ValidationError):
        MatchingConfig.model_validate({"rules": [{"id": "x", "source": {"fields": ["a"]}, "target": {"fields": ["b"]}, "weight": 101}]})


def test_numeric_tolerance_must_be_explicit() -> None:
    with pytest.raises(ValidationError):
        MatchingConfig.model_validate({"rules": [{"id": "x", "source": {"fields": ["a"]}, "target": {"fields": ["b"]}, "matcher": "numeric", "weight": 50}]})


def test_many_to_many_mapping_is_valid() -> None:
    config = MatchingConfig.model_validate({"rules": [{"id": "identity", "source": {"fields": ["型号", "规格"], "combine": "best_of"}, "target": {"fields": ["集团型号", "集团规格"], "combine": "best_of"}, "weight": 100}]})
    assert config.rules[0].source.fields == ["型号", "规格"]
    assert config.rules[0].target.fields == ["集团型号", "集团规格"]
