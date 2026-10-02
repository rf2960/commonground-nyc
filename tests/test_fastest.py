import json

import pytest

from commonground.fastest import score_fastest_option


def result(**kwargs):
    return json.loads(score_fastest_option(**kwargs))


def test_prefers_lowest_total_commute():
    scored = result(
        options=[
            {"area": "Union Square", "commute_minutes": [10, 20, 30, 40]},
            {"area": "Herald Square", "commute_minutes": [26, 26, 26, 26]},
        ]
    )

    assert scored["selected_area"] == "Union Square"
    assert scored["objective"] == "minimize total group travel time"
    assert scored["traveler_count"] == 4
    assert scored["ranking"][0]["total_commute_minutes"] == 100
    assert scored["ranking"][0]["average_commute_minutes"] == 25


def test_total_commute_beats_a_lower_maximum():
    scored = result(
        options=[
            {"area": "Lower Total", "commute_minutes": [10, 20, 70]},
            {"area": "Lower Maximum", "commute_minutes": [33, 34, 34]},
        ]
    )

    assert scored["selected_area"] == "Lower Total"


def test_breaks_total_tie_with_lowest_maximum_commute():
    scored = result(
        options=[
            {"area": "Uneven", "commute_minutes": [10, 50]},
            {"area": "Balanced", "commute_minutes": [30, 30]},
        ]
    )

    assert scored["selected_area"] == "Balanced"
    assert [option["area"] for option in scored["ranking"]] == [
        "Balanced",
        "Uneven",
    ]


def test_breaks_exact_tie_by_area_name():
    scored = result(
        options=[
            {"area": "Union Square", "commute_minutes": [20, 30]},
            {"area": "Herald Square", "commute_minutes": [20, 30]},
        ]
    )

    assert scored["selected_area"] == "Herald Square"


def test_returns_complete_metrics_and_explanation():
    scored = result(
        options=[
            {"area": "Bryant Park", "commute_minutes": [20.25, 25.25, 30.25]},
        ]
    )

    winner = scored["ranking"][0]
    assert winner == {
        "area": "Bryant Park",
        "commute_minutes": [20.2, 25.2, 30.2],
        "total_commute_minutes": 75.8,
        "average_commute_minutes": 25.2,
        "max_commute_minutes": 30.2,
        "commute_spread_minutes": 10.0,
    }
    assert "Bryant Park is fastest" in scored["explanation"]


@pytest.mark.parametrize(
    ("options", "expected_error"),
    [
        ([], "options must be a non-empty list"),
        (None, "options must be a non-empty list"),
        (["Union Square"], "option 1 must be an object"),
        ([{"area": " ", "commute_minutes": [10]}], "option 1 is missing area"),
        (
            [{"area": "Union Square", "commute_minutes": []}],
            "Union Square: commute_minutes must be a non-empty list",
        ),
        (
            [{"area": "Union Square", "commute_minutes": [True]}],
            "Union Square: every commute time must be numeric",
        ),
        (
            [{"area": "Union Square", "commute_minutes": ["20"]}],
            "Union Square: every commute time must be numeric",
        ),
        (
            [{"area": "Union Square", "commute_minutes": [-1]}],
            "Union Square: commute times cannot be negative",
        ),
        (
            [{"area": "Union Square", "commute_minutes": [float("inf")]}],
            "Union Square: commute times must be finite",
        ),
    ],
)
def test_invalid_input_returns_model_readable_error(options, expected_error):
    assert result(options=options) == {"error": expected_error}


def test_rejects_inconsistent_traveler_counts():
    scored = result(
        options=[
            {"area": "Union Square", "commute_minutes": [20, 30]},
            {"area": "Herald Square", "commute_minutes": [15]},
        ]
    )

    assert scored == {
        "error": "Herald Square: expected 2 commute time(s), received 1"
    }


def test_rejects_duplicate_area_names_case_insensitively():
    scored = result(
        options=[
            {"area": "Union Square", "commute_minutes": [20]},
            {"area": "union square", "commute_minutes": [21]},
        ]
    )

    assert scored == {"error": "duplicate area: union square"}
