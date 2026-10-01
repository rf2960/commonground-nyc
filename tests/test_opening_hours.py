import pytest

from commonground.opening_hours import opening_status, parse_meeting_time


def point(day, hour, minute=0):
    return {'day': day, 'hour': hour, 'minute': minute}


def place(*periods):
    return {'regularOpeningHours': {'periods': list(periods)}}


def status(p, time='2026-10-03T14:00:00-04:00'):
    return opening_status(p, parse_meeting_time(time))['open_at_meeting_time']


@pytest.mark.parametrize('time,expected', [('08:59:59', False), ('09:00:00', True),
    ('16:59:59', True), ('17:00:00', False)])
def test_opening_inclusive_closing_exclusive(time, expected):
    p = place({'open': point(6, 9), 'close': point(6, 17)})
    assert status(p, f'2026-10-03T{time}-04:00') is expected


def test_lunch_break_and_multiple_periods():
    p = place({'open': point(6, 9), 'close': point(6, 12)},
              {'open': point(6, 14), 'close': point(6, 18)})
    assert status(p, '2026-10-03T13:00:00-04:00') is False
    assert status(p) is True


def test_overnight_week_wrap_and_midweek():
    p = place({'open': point(6, 22), 'close': point(0, 2)})
    assert status(p, '2026-10-04T01:00:00-04:00') is True
    assert status(p, '2026-10-04T02:00:00-04:00') is False
    p = place({'open': point(1, 22), 'close': point(2, 2)})
    assert status(p, '2026-10-06T01:00:00-04:00') is True


def test_24_7_and_empty_vs_absent_hours():
    assert status(place({'open': point(0, 0)})) is True
    assert status(place()) is False
    assert status({}) is None
    assert status({'regularOpeningHours': {'openNow': True}}) is None


@pytest.mark.parametrize('period', [None, {}, {'open': point(3, 9)},
    {'open': point(6, 9), 'close': point(6, 9)},
    {'open': point(7, 9), 'close': point(6, 17)},
    {'open': point(6, True), 'close': point(6, 17)},
    {'open': point(6, 9), 'close': {'day': 6, 'hour': 17, 'truncated': True}}])
def test_malformed_or_incomplete_schedule_is_unknown(period):
    assert status(place(period)) is None


def test_unsorted_periods_and_omitted_zero_scalars():
    p = place({'open': point(6, 14), 'close': point(6, 17)},
              {'open': {'day': 6, 'hour': 9}, 'close': point(6, 12)})
    assert status(p) is True


def test_business_closure_overrides_hours():
    p = dict(place({'open': point(0, 0)}), businessStatus='CLOSED_TEMPORARILY')
    assert status(p) is False


def test_utc_conversion_changes_weekday_and_dst_offset():
    p = place({'open': point(6, 22), 'close': point(0, 2)})
    assert status(p, '2026-10-04T03:00:00Z') is True  # Saturday 11pm in NYC.
    assert parse_meeting_time('2026-12-05T19:00:00Z').hour == 14
    assert parse_meeting_time('2026-07-04T18:00:00Z').hour == 14


def test_naive_time_is_nyc_but_dst_ambiguity_rejected():
    assert parse_meeting_time('2026-10-03T14:00:00').isoformat().endswith('-04:00')
    for time in ('2026-11-01T01:30:00', '2026-03-08T02:30:00'):
        with pytest.raises(ValueError, match='ambiguous or nonexistent'):
            parse_meeting_time(time)
    assert parse_meeting_time('2026-11-01T01:30:00-05:00').hour == 1


def test_schedule_output_is_explicitly_an_estimate():
    r = opening_status(place({'open': point(0, 0)}), parse_meeting_time('2026-10-03T14:00:00'))
    assert r['opening_status_source'] == 'regular_schedule'
    assert 'Holiday' in r['opening_status_note']
