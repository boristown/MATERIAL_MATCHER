from material_matcher.domain.models import MatchingConfig
from material_matcher.matching.scorer import score_candidate, decide_status

def test_generic_field_scoring_and_inclusive_threshold():
    config=MatchingConfig.model_validate({'rules':[{'id':'name','source':{'fields':['s']},'target':{'fields':['t']},'matcher':'exact','weight':100}], 'decision':{'success_threshold':90,'review_enabled':True,'review_threshold':80,'top_n':5}})
    score=score_candidate({'s':'电阻'},{'t':'电阻'},config)
    assert score.display_score==100
    assert decide_status(90,config)=='MATCHED'
    assert decide_status(90.0001,config)=='MATCHED'

def test_best_of_supports_many_to_many():
    config=MatchingConfig.model_validate({'rules':[{'id':'model','source':{'fields':['a','b'],'combine':'best_of'},'target':{'fields':['x','y'],'combine':'best_of'},'matcher':'exact','weight':100}]})
    score=score_candidate({'a':'A','b':'B'},{'x':'C','y':'B'},config)
    assert score.display_score==100


def test_critical_conflict_is_exposed_as_metadata_without_zeroing_total_score():
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


def _veto_config(veto_threshold):
    rule = {'id': 'spec', 'source': {'fields': ['s_spec']}, 'target': {'fields': ['t_spec']}, 'matcher': 'exact', 'weight': 10}
    if veto_threshold is not None:
        rule['veto_threshold'] = veto_threshold
    return MatchingConfig.model_validate({'rules': [
        {'id': 'name', 'source': {'fields': ['s_name']}, 'target': {'fields': ['t_name']}, 'matcher': 'exact', 'weight': 90},
        rule,
    ], 'decision': {'success_threshold': 80, 'review_enabled': True, 'review_threshold': 50, 'top_n': 5}})


def test_veto_threshold_zeroes_total_similarity_when_field_below_threshold():
    config = _veto_config(60)
    score = score_candidate({'s_name': '电阻', 's_spec': '0805'}, {'t_name': '电阻', 't_spec': '1206'}, config)
    assert score.display_score == 0.0
    assert any(item.vetoed for item in score.field_scores)
    assert not score.auto_match_safe
    assert decide_status(score.display_score, config) != 'MATCHED'


def test_veto_threshold_not_triggered_when_field_meets_threshold():
    config = _veto_config(60)
    score = score_candidate({'s_name': '电阻', 's_spec': '0805'}, {'t_name': '电阻', 't_spec': '0805'}, config)
    assert score.display_score == 100.0
    assert not any(item.vetoed for item in score.field_scores)


def test_veto_threshold_boundary_equal_is_not_below():
    config = _veto_config(0)
    score = score_candidate({'s_name': '电阻', 's_spec': 'A'}, {'t_name': '电阻', 't_spec': 'B'}, config)
    assert not any(item.vetoed for item in score.field_scores)
    assert score.display_score == 90.0


def test_veto_disabled_by_default_keeps_legacy_weighted_score():
    config = _veto_config(None)
    score = score_candidate({'s_name': '电阻', 's_spec': '0805'}, {'t_name': '电阻', 't_spec': '1206'}, config)
    assert score.display_score == 90.0


def test_veto_works_on_zero_weight_pure_veto_rule():
    """weight=0 的纯否决规则必须生效（此前被 weight<=0 continue 静默跳过）。"""
    config = MatchingConfig.model_validate({
        "rules": [
            {"id": "name", "source": {"fields": ["s_name"]}, "target": {"fields": ["t_name"]}, "matcher": "exact", "weight": 100},
            {"id": "pkg", "source": {"fields": ["s_pkg"]}, "target": {"fields": ["t_pkg"]}, "matcher": "exact", "weight": 0, "veto_threshold": 50},
        ],
        "decision": {"success_threshold": 80, "review_enabled": True, "review_threshold": 50, "top_n": 5},
    })
    ok = score_candidate({"s_name": "电阻", "s_pkg": "0805"}, {"t_name": "电阻", "t_pkg": "0805"}, config)
    assert ok.display_score == 100.0 and not any(i.vetoed for i in ok.field_scores)
    veto = score_candidate({"s_name": "电阻", "s_pkg": "1206"}, {"t_name": "电阻", "t_pkg": "0805"}, config)
    assert veto.display_score == 0.0
    assert any(i.vetoed and i.rule_id == "pkg" for i in veto.field_scores)
    assert not veto.auto_match_safe
