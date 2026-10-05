"""Deterministic alignment between commute winners and cafe recommendations."""

from __future__ import annotations

from typing import Any


OBJECTIVES = {"fairest", "fastest", "best_cafe"}


def _same_area(left: Any, right: Any) -> bool:
    return (
        isinstance(left, str)
        and isinstance(right, str)
        and left.strip().casefold() == right.strip().casefold()
    )


def _winner(scored: dict[str, Any]) -> dict[str, Any] | None:
    selected = scored.get("selected_area")
    ranking = scored.get("ranking")
    if not isinstance(ranking, list):
        return None
    return next(
        (
            entry
            for entry in ranking
            if isinstance(entry, dict) and _same_area(entry.get("area"), selected)
        ),
        ranking[0] if ranking and isinstance(ranking[0], dict) else None,
    )


def _ranked_cafes(scored: dict[str, Any]) -> list[dict[str, Any]]:
    ranking = scored.get("ranking")
    if not isinstance(ranking, list):
        return []
    return [
        entry
        for entry in ranking
        if isinstance(entry, dict) and isinstance(entry.get("cafe"), dict)
    ]


def _cafe_summary(entry: dict[str, Any] | None) -> dict[str, Any] | None:
    if entry is None:
        return None
    cafe = entry["cafe"]
    factors = entry.get("factor_breakdown")
    return {
        "name": cafe.get("name"),
        "area": cafe.get("area"),
        "rating": cafe.get("rating"),
        "review_count": cafe.get("review_count"),
        "review_adjusted_rating": (
            factors.get("adjusted_rating") if isinstance(factors, dict) else None
        ),
        "provisional": bool(entry.get("provisional")),
    }


def _best_cafe_in_area(
    ranked_cafes: list[dict[str, Any]], area: Any
) -> dict[str, Any] | None:
    return next(
        (
            entry
            for entry in ranked_cafes
            if _same_area(entry["cafe"].get("area"), area)
        ),
        None,
    )


def _metrics_by_area(scored: dict[str, Any], area: Any) -> dict[str, Any] | None:
    ranking = scored.get("ranking")
    if not isinstance(ranking, list):
        return None
    return next(
        (
            entry
            for entry in ranking
            if isinstance(entry, dict) and _same_area(entry.get("area"), area)
        ),
        None,
    )


def _tradeoff(
    cafe_area: Any,
    winner_area: Any,
    fastest: dict[str, Any],
) -> dict[str, Any] | None:
    if not isinstance(cafe_area, str) or not isinstance(winner_area, str):
        return None
    if _same_area(cafe_area, winner_area):
        return {
            "cafe_area": cafe_area,
            "winner_area": winner_area,
            "same_area": True,
            "extra_total_commute_minutes": 0,
            "extra_longest_commute_minutes": 0,
        }

    cafe_metrics = _metrics_by_area(fastest, cafe_area)
    winner_metrics = _metrics_by_area(fastest, winner_area)
    if cafe_metrics is None or winner_metrics is None:
        return {
            "cafe_area": cafe_area,
            "winner_area": winner_area,
            "same_area": False,
            "extra_total_commute_minutes": None,
            "extra_longest_commute_minutes": None,
            "note": "Commute cost cannot be quantified because one area lacks a complete route matrix.",
        }

    total_change = round(
        cafe_metrics["total_commute_minutes"]
        - winner_metrics["total_commute_minutes"],
        1,
    )
    longest_change = round(
        cafe_metrics["max_commute_minutes"]
        - winner_metrics["max_commute_minutes"],
        1,
    )
    changes = []
    for label, value in (
        ("total group commute", total_change),
        ("longest individual commute", longest_change),
    ):
        if value > 0:
            changes.append(f"adds {value:g} minutes of {label}")
        elif value < 0:
            changes.append(f"saves {-value:g} minutes of {label}")
        else:
            changes.append(f"does not change {label}")

    return {
        "cafe_area": cafe_area,
        "winner_area": winner_area,
        "same_area": False,
        "total_commute_change_minutes": total_change,
        "longest_commute_change_minutes": longest_change,
        "extra_total_commute_minutes": max(total_change, 0),
        "extra_longest_commute_minutes": max(longest_change, 0),
        "saved_total_commute_minutes": max(-total_change, 0),
        "saved_longest_commute_minutes": max(-longest_change, 0),
        "explanation": (
            f"Choosing a cafe in {cafe_area} instead of {winner_area} "
            + " and ".join(changes)
            + "."
        ),
    }


def _route_context(transit: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(transit, dict):
        return None
    areas = transit.get("areas")
    area_status = []
    if isinstance(areas, list):
        area_status = [
            {
                "area": area.get("area"),
                "drive_fallback_count": area.get("drive_fallback_count", 0),
            }
            for area in areas
            if isinstance(area, dict)
        ]
    return {
        "status": transit.get("status", "ok"),
        "partial": bool(transit.get("partial")),
        "areas": area_status,
        "excluded_areas": transit.get("excluded_areas", []),
        "unavailable_routes": transit.get("unavailable_routes", []),
        "mode_failures": transit.get("mode_failures", []),
        "mode_errors": transit.get("mode_errors", []),
        "warnings": transit.get("warnings", []),
        "attribution": transit.get("attribution"),
    }


def build_recommendation_plans(
    fairest: dict[str, Any],
    fastest: dict[str, Any],
    best_cafe: dict[str, Any],
    *,
    preferred_objective: str | None = None,
    transit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return auditable plans without collapsing distinct objectives.

    When fairness or speed is explicit, cafe quality is optimized inside that
    objective's winning area. If no qualifying cafe exists there, the global
    cafe winner is retained as a transparent fallback with a commute trade-off.
    """
    if preferred_objective not in OBJECTIVES | {None}:
        raise ValueError(f"unsupported preferred_objective: {preferred_objective}")

    fair_winner = _winner(fairest)
    fast_winner = _winner(fastest)
    if fair_winner is None or fast_winner is None:
        raise ValueError("fairest and fastest results must contain a winner")

    cafes = _ranked_cafes(best_cafe)
    global_cafe = cafes[0] if cafes else None
    fair_cafe = _best_cafe_in_area(cafes, fair_winner.get("area"))
    fast_cafe = _best_cafe_in_area(cafes, fast_winner.get("area"))

    fairest_plan = {
        "objective": "fairest",
        "area": fair_winner.get("area"),
        "max_commute_minutes": fair_winner.get("max_commute_minutes"),
        "commute_spread_minutes": fair_winner.get("commute_spread_minutes"),
        "cafe": _cafe_summary(fair_cafe),
    }
    fastest_plan = {
        "objective": "fastest",
        "area": fast_winner.get("area"),
        "total_commute_minutes": fast_winner.get("total_commute_minutes"),
        "average_commute_minutes": fast_winner.get("average_commute_minutes"),
        "cafe": _cafe_summary(fast_cafe),
    }
    best_cafe_summary = _cafe_summary(global_cafe)
    best_cafe_plan = {
        "objective": "best_cafe",
        "area": best_cafe_summary.get("area") if best_cafe_summary else None,
        "cafe": best_cafe_summary,
    }

    plans = {
        "fairest": fairest_plan,
        "fastest": fastest_plan,
        "best_cafe": best_cafe_plan,
    }
    selected_plan = None
    cafe_fallback = False
    if preferred_objective is not None:
        selected_plan = dict(plans[preferred_objective])
        if preferred_objective in {"fairest", "fastest"} and selected_plan["cafe"] is None:
            selected_plan["cafe"] = best_cafe_summary
            cafe_fallback = best_cafe_summary is not None
        selected_plan["used_out_of_area_cafe_fallback"] = cafe_fallback

    global_cafe_area = best_cafe_summary.get("area") if best_cafe_summary else None
    selected_cafe_area = (
        selected_plan["cafe"].get("area")
        if selected_plan and isinstance(selected_plan.get("cafe"), dict)
        else None
    )
    selected_area = selected_plan.get("area") if selected_plan else None

    return {
        "mode": "selected_objective" if preferred_objective else "compare_objectives",
        "preferred_objective": preferred_objective,
        "plans": plans,
        "selected_plan": selected_plan,
        "instruction": (
            "Present the selected plan as the recommendation."
            if preferred_objective
            else "Present all three plans separately; do not declare one overall winner."
        ),
        "selected_plan_tradeoff": (
            _tradeoff(selected_cafe_area, selected_area, fastest)
            if selected_plan
            else None
        ),
        "best_cafe_vs_fairest": _tradeoff(
            global_cafe_area, fair_winner.get("area"), fastest
        ),
        "best_cafe_vs_fastest": _tradeoff(
            global_cafe_area, fast_winner.get("area"), fastest
        ),
        "route_context": _route_context(transit),
    }


def infer_preferred_objective(messages: list[dict[str, Any]]) -> str | None:
    """Infer an explicit objective, retaining it across neutral follow-ups."""
    explicit = {
        "fairest": (
            "prioritize fairest",
            "choose fairest",
            "in the fairest area",
            "fairest is my priority",
            "公平优先",
            "选择最公平",
            "最公平的区域",
        ),
        "fastest": (
            "prioritize fastest",
            "choose fastest",
            "in the fastest area",
            "fastest is my priority",
            "最快优先",
            "选择最快",
            "最快的区域",
        ),
        "best_cafe": (
            "prioritize best cafe",
            "choose best cafe",
            "cafe quality is my priority",
            "best cafe is my priority",
            "咖啡店优先",
            "选择最好的咖啡店",
        ),
    }
    for message in reversed(messages):
        if message.get("role") != "user":
            continue
        text = str(message.get("content", "")).casefold()
        matches = [
            objective
            for objective, phrases in explicit.items()
            if any(phrase in text for phrase in phrases)
        ]
        if len(matches) == 1:
            return matches[0]

        mentions = {
            "fairest": any(
                term in text for term in ("fairest", "fairness", "最公平")
            ),
            "fastest": any(
                term in text for term in ("fastest", "quickest", "最快")
            ),
            "best_cafe": any(
                term in text for term in ("best cafe", "cafe quality", "最好咖啡")
            ),
        }
        mentioned = [objective for objective, present in mentions.items() if present]
        if len(mentioned) == 1:
            return mentioned[0]
        if len(mentioned) > 1:
            return None
    return None
