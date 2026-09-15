from material_matcher.normalize.pipeline import apply_processing_pipeline


def test_identity_preserves_business_tokens():
    assert apply_processing_pipeline('88', []).text == '88'
    assert apply_processing_pipeline('N/A', []).text == 'N/A'


def test_processing_is_explicit_and_traced():
    value = apply_processing_pipeline(
        '  ABC-01  ',
        [
            {'op': 'trim'},
            {'op': 'punctuation_map', 'options': {'chars': '-', 'replacement': ''}},
            {'op': 'case_map', 'options': {'mode': 'lower'}},
        ],
    )
    assert value.text == 'abc01'
    assert [item.operator for item in value.trace] == ['trim', 'punctuation_map', 'case_map']


def test_dictionary_map_exact_and_replace_are_explicit_and_trace_does_not_duplicate_mapping():
    exact = apply_processing_pipeline(
        'SUS304',
        [{'op': 'dictionary_map', 'options': {'mapping': {'SUS304': '304不锈钢'}, 'mode': 'exact'}}],
    )
    assert exact.text == '304不锈钢'
    assert 'mapping' not in exact.trace[0].options

    replaced = apply_processing_pipeline(
        'SUS304 六角螺栓',
        [{'op': 'dictionary_map', 'options': {'mapping': {'SUS304': '304不锈钢', '六角螺栓': 'HEX_BOLT'}, 'mode': 'replace'}}],
    )
    assert replaced.text == '304不锈钢 HEX_BOLT'


def test_dictionary_map_can_be_case_insensitive_and_nullify_missing_keys():
    mapped = apply_processing_pipeline(
        'sus304',
        [{'op': 'dictionary_map', 'options': {'mapping': {'SUS304': '304不锈钢'}, 'case_sensitive': False}}],
    )
    assert mapped.text == '304不锈钢'
    missing = apply_processing_pipeline(
        'UNKNOWN',
        [{'op': 'dictionary_map', 'options': {'mapping': {'A': 'B'}, 'on_missing': 'null'}}],
    )
    assert missing.is_missing is True
