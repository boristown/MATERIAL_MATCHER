from material_matcher.domain.models import MatchingConfig
from material_matcher.matching.scorer import score_candidate, decide_status

def test_generic_field_scoring_and_strict_threshold():
    config=MatchingConfig.model_validate({'rules':[{'id':'name','source':{'fields':['s']},'target':{'fields':['t']},'matcher':'exact','weight':100}], 'decision':{'success_threshold':90,'review_enabled':True,'review_threshold':80,'top_n':5}})
    score=score_candidate({'s':'电阻'},{'t':'电阻'},config)
    assert score.display_score==100
    assert decide_status(90,config)=='REVIEW'
    assert decide_status(90.0001,config)=='MATCHED'

def test_best_of_supports_many_to_many():
    config=MatchingConfig.model_validate({'rules':[{'id':'model','source':{'fields':['a','b'],'combine':'best_of'},'target':{'fields':['x','y'],'combine':'best_of'},'matcher':'exact','weight':100}]})
    score=score_candidate({'a':'A','b':'B'},{'x':'C','y':'B'},config)
    assert score.display_score==100


def test_critical_conflict_blocks_auto_match_without_zeroing_total_score():
    config = MatchingConfig.model_validate({
        'rules': [
            {
                'id': 'name',
                'source': {'fields': ['source_name']},
                'target': {'fields': ['target_name']},
                'matcher': 'exact',
                'weight': 90,
            },
            {
                'id': 'origin',
                'source': {'fields': ['source_origin']},
                'target': {'fields': ['target_origin']},
                'matcher': 'exact',
                'weight': 10,
                'critical': True,
            },
        ],
        'decision': {
            'success_threshold': 80,
            'review_enabled': True,
            'review_threshold': 0,
            'top_n': 5,
        },
    })

    score = score_candidate(
        {'source_name': '继电器', 'source_origin': '国产'},
        {'target_name': '继电器', 'target_origin': '进口'},
        config,
    )

    assert score.display_score == 90
    assert score.critical_conflict is True
    assert score.auto_match_safe is False


def test_tie_break_default_auto_selects_first_candidate():
    from material_matcher.domain.models import DecisionConfig
    assert DecisionConfig().tie_break == "top1"
    assert DecisionConfig(tie_break="review").tie_break == "review"
