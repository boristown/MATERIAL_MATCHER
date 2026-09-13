from material_matcher.normalize.pipeline import apply_processing_pipeline


def test_empty_pipeline_is_exact_identity() -> None:
    value = "  AbC-88  "
    output = apply_processing_pipeline(value, [])
    assert output.value == value
    assert output.raw_value == value
    assert output.trace == []


def test_text_88_is_not_implicitly_null() -> None:
    assert apply_processing_pipeline("88", []).value == "88"


def test_explicit_processing_preserves_raw_value_and_trace() -> None:
    output = apply_processing_pipeline("  AbC  ", [{"op": "trim"}, {"op": "case_map", "options": {"mode": "lower"}}])
    assert output.value == "abc"
    assert output.raw_value == "  AbC  "
    assert [item.operator for item in output.trace] == ["trim", "case_map"]
