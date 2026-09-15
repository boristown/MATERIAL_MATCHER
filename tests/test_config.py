import pytest
from pydantic import ValidationError
from material_matcher.domain.models import MatchingConfig

def test_weight_and_numeric_tolerance_contract():
    with pytest.raises(ValidationError):
        MatchingConfig.model_validate({'rules':[{'id':'x','source':{'fields':['a']},'target':{'fields':['b']},'matcher':'numeric','weight':101}]})
    with pytest.raises(ValidationError):
        MatchingConfig.model_validate({'rules':[{'id':'x','source':{'fields':['a']},'target':{'fields':['b']},'matcher':'numeric','weight':50}]})
    valid=MatchingConfig.model_validate({'rules':[{'id':'x','source':{'fields':['a']},'target':{'fields':['b']},'matcher':'numeric','weight':50,'matcher_options':{'tolerance':{'mode':'exact'}}}]})
    assert valid.rules[0].weight==50

def test_scope_requires_fields():
    with pytest.raises(ValidationError): MatchingConfig.model_validate({'scope_mode':'STRICT','rules':[]})
