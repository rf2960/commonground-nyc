import json
from types import SimpleNamespace

import app as webapp
from commonground.recommendations import (
    build_recommendation_plans,
    infer_preferred_objective,
)


FAIREST = {
    "selected_area": "Union Square",
    "ranking": [
        {
            "area": "Union Square",
            "max_commute_minutes": 31,
            "average_commute_minutes": 27,
            "commute_spread_minutes": 8,
        },
        {
            "area": "SoHo",
            "max_commute_minutes": 39,
            "average_commute_minutes": 20.7,
            "commute_spread_minutes": 24,
        },
        {
            "area": "Bryant Park",
            "max_commute_minutes": 36,
            "average_commute_minutes": 23,
            "commute_spread_minutes": 16,
        },
    ],
}

FASTEST = {
    "selected_area": "SoHo",
    "ranking": [
        {
            "area": "SoHo",
            "total_commute_minutes": 62,
            "average_commute_minutes": 20.7,
            "max_commute_minutes": 39,
        },
        {
            "area": "Bryant Park",
            "total_commute_minutes": 69,
            "average_commute_minutes": 23,
            "max_commute_minutes": 36,
        },
        {
            "area": "Union Square",
            "total_commute_minutes": 81,
            "average_commute_minutes": 27,
            "max_commute_minutes": 31,
        },
    ],
}

CAFES = {
    "selected_cafe": {"name": "Bryant Beans", "area": "Bryant Park"},
    "ranking": [
        {
            "cafe": {
                "name": "Bryant Beans",
                "area": "Bryant Park",
                "rating": 4.8,
                "review_count": 900,
            },
            "factor_breakdown": {"adjusted_rating": 4.7579},
            "provisional": False,
        },
        {
            "cafe": {
                "name": "Union Coffee",
                "area": "Union Square",
                "rating": 4.6,
                "review_count": 500,
            },
            "factor_breakdown": {"adjusted_rating": 4.5455},
            "provisional": False,
        },
        {
            "cafe": {
                "name": "SoHo Roast",
                "area": "SoHo",
                "rating": 4.5,
                "review_count": 700,
            },
            "factor_breakdown": {"adjusted_rating": 4.4667},
            "provisional": True,
        },
    ],
}

TRANSIT = {
    "status": "partial",
    "partial": True,
    "areas": [
        {"area": "Union Square", "drive_fallback_count": 1},
        {"area": "SoHo", "drive_fallback_count": 0},
    ],
    "unavailable_routes": [{"traveler_id": "d", "area": "Bryant Park"}],
    "mode_failures": [{"mode": "TRANSIT", "count": 1}],
    "mode_errors": [{"mode": "TRANSIT", "error": "no route"}],
    "warnings": ["One trip uses a driving estimate."],
    "attribution": "Google Maps",
}


def test_explicit_fairest_uses_best_cafe_inside_fairest_area():
    aligned = build_recommendation_plans(
        FAIREST, FASTEST, CAFES, preferred_objective="fairest"
    )

    assert aligned["selected_plan"]["area"] == "Union Square"
    assert aligned["selected_plan"]["cafe"]["name"] == "Union Coffee"
    assert aligned["selected_plan"]["used_out_of_area_cafe_fallback"] is False
    assert aligned["selected_plan_tradeoff"]["same_area"] is True


def test_explicit_fastest_uses_best_cafe_inside_fastest_area():
    aligned = build_recommendation_plans(
        FAIREST, FASTEST, CAFES, preferred_objective="fastest"
    )

    assert aligned["selected_plan"]["area"] == "SoHo"
    assert aligned["selected_plan"]["cafe"]["name"] == "SoHo Roast"


def test_no_priority_returns_three_plans_without_overall_winner():
    aligned = build_recommendation_plans(FAIREST, FASTEST, CAFES)

    assert aligned["mode"] == "compare_objectives"
    assert aligned["selected_plan"] is None
    assert set(aligned["plans"]) == {"fairest", "fastest", "best_cafe"}
    assert "do not declare one overall winner" in aligned["instruction"]


def test_cross_area_cafe_tradeoffs_are_quantified():
    aligned = build_recommendation_plans(FAIREST, FASTEST, CAFES)

    versus_fair = aligned["best_cafe_vs_fairest"]
    assert versus_fair["total_commute_change_minutes"] == -12
    assert versus_fair["saved_total_commute_minutes"] == 12
    assert versus_fair["extra_longest_commute_minutes"] == 5
    assert "saves 12 minutes" in versus_fair["explanation"]
    assert "adds 5 minutes" in versus_fair["explanation"]

    versus_fast = aligned["best_cafe_vs_fastest"]
    assert versus_fast["extra_total_commute_minutes"] == 7
    assert versus_fast["longest_commute_change_minutes"] == -3
    assert versus_fast["saved_longest_commute_minutes"] == 3


def test_route_fallback_and_partial_failure_context_is_preserved():
    route = build_recommendation_plans(
        FAIREST, FASTEST, CAFES, transit=TRANSIT
    )["route_context"]

    assert route["status"] == "partial"
    assert route["partial"] is True
    assert route["areas"][0]["drive_fallback_count"] == 1
    assert route["unavailable_routes"] == TRANSIT["unavailable_routes"]
    assert route["mode_failures"] == TRANSIT["mode_failures"]
    assert route["mode_errors"] == TRANSIT["mode_errors"]
    assert route["warnings"] == TRANSIT["warnings"]


def test_missing_winner_area_cafe_uses_labeled_global_fallback():
    only_global = {**CAFES, "ranking": CAFES["ranking"][:1]}
    aligned = build_recommendation_plans(
        FAIREST, FASTEST, only_global, preferred_objective="fairest"
    )

    assert aligned["selected_plan"]["cafe"]["name"] == "Bryant Beans"
    assert aligned["selected_plan"]["used_out_of_area_cafe_fallback"] is True
    assert aligned["selected_plan_tradeoff"]["same_area"] is False


def test_preference_inference_requires_one_clear_objective():
    assert infer_preferred_objective(
        [{"role": "user", "content": "Choose fastest for this group."}]
    ) == "fastest"
    assert infer_preferred_objective(
        [{"role": "user", "content": "Compare Fairest and Fastest."}]
    ) is None
    assert infer_preferred_objective(
        [{"role": "user", "content": "这次公平优先。"}]
    ) == "fairest"


def test_preference_inference_preserves_objective_across_neutral_followup():
    messages = [
        {"role": "user", "content": "Choose fairest for this group."},
        {"role": "assistant", "content": "Here are the results."},
        {"role": "user", "content": "Actually Bob starts at Queensboro Plaza."},
    ]

    assert infer_preferred_objective(messages) == "fairest"


class FakeReply:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self):
        return {"role": "assistant", "content": self.content}


def _call(name, call_id):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments="{}"),
    )


def _completion(reply):
    return SimpleNamespace(choices=[SimpleNamespace(message=reply)])


def test_agent_injects_authoritative_alignment_before_final_answer(monkeypatch):
    results = {
        "get_transit_matrix": TRANSIT,
        "score_fairest_option": FAIREST,
        "score_fastest_option": FASTEST,
        "score_best_cafe_option": CAFES,
    }
    replies = iter(
        [
            _completion(
                FakeReply(
                    tool_calls=[
                        _call("get_transit_matrix", "1"),
                        _call("score_fairest_option", "2"),
                        _call("score_fastest_option", "3"),
                        _call("score_best_cafe_option", "4"),
                    ]
                )
            ),
            _completion(FakeReply(content="Use Union Coffee in Union Square.")),
        ]
    )
    observed = []

    def fake_completion(**kwargs):
        observed.append([dict(message) for message in kwargs["messages"]])
        return next(replies)

    monkeypatch.setattr(webapp.litellm, "completion", fake_completion)
    monkeypatch.setattr(
        webapp, "run_tool", lambda name, _args: json.dumps(results[name])
    )

    answer, _calls = webapp.run_agent(
        [{"role": "user", "content": "Plan this meetup; prioritize fairest."}]
    )

    assert answer == "Use Union Coffee in Union Square."
    alignment_message = next(
        message["content"]
        for message in observed[1]
        if isinstance(message.get("content"), str)
        and message["content"].startswith("RECOMMENDATION_ALIGNMENT")
    )
    alignment = json.loads(alignment_message.split("\n", 1)[1])
    assert alignment["preferred_objective"] == "fairest"
    assert alignment["selected_plan"]["cafe"]["name"] == "Union Coffee"
    assert alignment["route_context"]["partial"] is True
