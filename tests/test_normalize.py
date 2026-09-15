from material_matcher.normalize.pipeline import apply_processing_pipeline

def test_identity_preserves_business_tokens():
    assert apply_processing_pipeline('88', []).text=='88'
    assert apply_processing_pipeline('N/A', []).text=='N/A'

def test_processing_is_explicit_and_traced():
    value=apply_processing_pipeline('  ABC-01  ',[{'op':'trim'},{'op':'punctuation_map','options':{'chars':'-','replacement':''}},{'op':'case_map','options':{'mode':'lower'}}])
    assert value.text=='abc01'; assert [item.operator for item in value.trace]==['trim','punctuation_map','case_map']
