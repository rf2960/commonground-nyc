import json

import pytest

from commonground.cafes import score_best_cafe_option
from tools import TOOLS, run_tool


def cafe(name='A', **changes):
    return {'name': name, 'rating': 4.5, 'review_count': 100, 'price_level': 2,
            'open_at_meeting_time': True, **changes}


def score(cafes, **kwargs):
    return json.loads(score_best_cafe_option(cafes, **kwargs))


def test_budget_and_closed_cafes_do_not_win():
    result = score([cafe('Expensive', rating=5, price_level=4), cafe('Good'),
                    cafe('Closed', rating=5, open_at_meeting_time=False)], price_levels=[1, 2])
    assert result['selected_cafe']['name'] == 'Good'
    assert len(result['excluded']) == 2


def test_many_reviews_outweigh_tiny_perfect_sample():
    result = score([cafe('Tiny sample', rating=5, review_count=2),
                    cafe('Established', rating=4.6, review_count=500)])
    assert result['selected_cafe']['name'] == 'Established'
    assert result['ranking'][0]['factor_breakdown']['adjusted_rating'] == round((500*4.6+50*4)/550, 4)


def test_open_unknown_is_explicitly_provisional():
    result = score([cafe(open_at_meeting_time=None)])
    assert result['ranking'][0]['provisional'] is True
    assert 'unverified' in result['explanation']


def test_unknown_budget_rating_and_distance_do_not_pass_hard_filters():
    result = score([cafe('Unknown price', price_level=None), cafe('Unknown rating', rating=None),
                    cafe('Unknown distance')], price_levels=[2], max_station_distance_meters=500)
    assert result['selected_cafe'] is None
    assert len(result['excluded']) == 3


def test_rating_boundary_and_station_tie_break():
    result = score([cafe('Far', station_distance_meters=500), cafe('Near', station_distance_meters=100)],
                   min_rating=4.5, max_station_distance_meters=500)
    assert result['selected_cafe']['name'] == 'Near'
    assert not result['excluded']


def test_zero_reviews_and_missing_reviews_use_prior_and_warn():
    result = score([cafe('Zero', review_count=0), cafe('Missing', review_count=None)])
    assert all(e['factor_breakdown']['adjusted_rating'] == 4 for e in result['ranking'])
    missing = next(e for e in result['ranking'] if e['cafe']['name'] == 'Missing')
    assert any('Review count' in w for w in missing['warnings'])


def test_can_include_closed_cafe_when_open_not_required():
    assert score([cafe(open_at_meeting_time=False)], require_open=False)['selected_cafe']


@pytest.mark.parametrize('field,value', [('rating',float('nan')), ('rating',6), ('rating',True),
    ('review_count',-1), ('review_count',2.5), ('price_level',True), ('price_level',5),
    ('open_at_meeting_time','yes'), ('station_distance_meters',float('inf'))])
def test_bad_cafe_data_returns_error(field, value):
    assert 'error' in score([cafe(**{field:value})])


@pytest.mark.parametrize('prefs', [{'min_rating':-1}, {'price_levels':[]}, {'price_levels':[True]},
    {'require_open':'yes'}, {'max_station_distance_meters':-1}])
def test_invalid_preferences_return_error(prefs):
    assert 'error' in score([cafe()], **prefs)


def test_empty_input_returns_actionable_error():
    result = score([])
    assert 'error' in result and 'action' in result


def test_tool_is_registered_and_returns_json():
    assert any(t['function']['name'] == 'score_best_cafe_option' for t in TOOLS)
    assert json.loads(run_tool('score_best_cafe_option', {'cafes':[cafe()]}))['selected_cafe']['name'] == 'A'
