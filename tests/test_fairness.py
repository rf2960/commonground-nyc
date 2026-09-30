import json

from commonground.fairness import score_fairest_option


def result(**kwargs):
    return json.loads(score_fairest_option(**kwargs))


def test_prefers_smallest_worst_commute():
    scored = result(
        options=[
            {"area": "Union Square", "commute_minutes": [24, 27, 29, 31]},
            {"area": "Herald Square", "commute_minutes": [15, 20, 22, 42]},
        ]
    )

    assert scored["selected_area"] == "Union Square"
    assert scored["ranking"][0]["max_commute_minutes"] == 31


def test_hard_limit_violations_dominate_other_metrics():
    scored = result(
        options=[
            {"area": "A", "commute_minutes": [10, 10, 61]},
            {"area": "B", "commute_minutes": [50, 50, 50]},
        ],
        hard_limit_minutes=60,
    )

    assert scored["selected_area"] == "B"


def test_invalid_input_returns_model_readable_error():
    scored = result(options=[])
    assert "error" in scored

