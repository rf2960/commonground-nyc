import json
from unittest.mock import Mock

import pytest
import requests

from commonground.places import search_cafes_in_areas

AREA = {'area':'Union Square', 'lat':40.7359, 'lng':-73.9911}
TIME = '2026-10-03T14:00:00-04:00'
PLACE = {'id':'p1','displayName':{'text':'Cafe'}, 'location':{'latitude':40.736,'longitude':-73.991},
         'rating':4.5,'userRatingCount':100,'priceLevel':'PRICE_LEVEL_MODERATE',
         'regularOpeningHours':{'weekdayDescriptions':['Monday: 9 AM–5 PM']}}


@pytest.fixture
def post(monkeypatch):
    monkeypatch.setenv('GOOGLE_MAPS_API_KEY','fixture-secret')
    response = Mock(status_code=200)
    response.json.return_value = {'places':[PLACE]}
    mock = Mock(return_value=response)
    monkeypatch.setattr('commonground.places.requests.post',mock)
    return mock


def call(**kwargs):
    return json.loads(search_cafes_in_areas(**{'areas':[AREA], 'meeting_time':TIME, **kwargs}))


def test_normalizes_real_fields_and_leaves_future_hours_unknown(post):
    r=call()
    c=r['cafes'][0]
    assert c['price_level']==2 and c['review_count']==100
    assert c['open_at_meeting_time'] is None
    assert c['regular_opening_hours']==PLACE['regularOpeningHours']
    params=post.call_args.kwargs
    assert params['timeout']==15
    assert params['json']['includedPrimaryTypes']==['cafe', 'coffee_shop']
    assert 'includedTypes' not in params['json']
    assert params['json']['locationRestriction']['circle']['center']['latitude']==AREA['lat']
    assert params['headers']['X-Goog-Api-Key']=='fixture-secret'
    assert 'fixture-secret' not in json.dumps(r)


def test_deduplicates_overlapping_areas(post):
    assert len(call(areas=[AREA,dict(AREA,area='Other hub')])['cafes'])==1
    assert post.call_count==2


def test_filters_rating_and_price(post):
    assert call(min_rating=4.6)['cafes']==[]
    assert call(price_levels=[1])['cafes']==[]


def test_unknown_price_does_not_pass_budget(post):
    post.return_value.json.return_value={'places':[dict(PLACE,priceLevel='PRICE_LEVEL_UNSPECIFIED')]}
    assert call(price_levels=[2])['cafes']==[]
    assert call()['cafes'][0]['price_level'] is None


def test_known_closed_business(post):
    post.return_value.json.return_value={'places':[dict(PLACE,businessStatus='CLOSED_PERMANENTLY')]}
    assert call()['cafes'][0]['open_at_meeting_time'] is False


def test_empty_provider_results(post):
    post.return_value.json.return_value={}
    assert call()['cafes']==[] and 'error' not in call()


@pytest.mark.parametrize('status',[400,401,403,429,500])
def test_provider_failures_are_actionable_and_redacted(post,status):
    post.return_value.status_code=status
    r=call()
    assert 'error' in r and str(status) in r['area_errors'][0]['error']
    assert 'fixture-secret' not in json.dumps(r)


def test_timeout_and_partial_results(post):
    good=post.return_value
    post.side_effect=[requests.Timeout('fixture-secret'),good]
    r=call(areas=[AREA,dict(AREA,area='Other')])
    assert r['partial'] and r['cafes'] and 'fixture-secret' not in json.dumps(r)


def test_missing_key_never_calls_api(post,monkeypatch):
    monkeypatch.delenv('GOOGLE_MAPS_API_KEY')
    assert 'GOOGLE_MAPS_API_KEY' in call()['error']
    post.assert_not_called()


@pytest.mark.parametrize('kwargs',[{'areas':[]},{'areas':[AREA]*5}, {'areas':[dict(AREA,lat=0)]},
    {'areas':[dict(AREA,lat=float('nan'))]}, {'meeting_time':'Saturday'}, {'price_levels':[True]}])
def test_validation_before_requests(post,kwargs):
    assert 'error' in call(**kwargs)
    post.assert_not_called()
