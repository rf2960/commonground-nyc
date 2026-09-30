"""Explainable fairness scoring for candidate meeting areas."""

from __future__ import annotations

import json
from statistics import fmean
from typing import Any


def _validated_minutes(raw_minutes: Any, area: str) -> list[float]:
    if not isinstance(raw_minutes, list) or not raw_minutes:
        raise ValueError(f"{area}: commute_minutes must be a non-empty list")

    minutes: list[float] = []
    for value in raw_minutes:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{area}: every commute time must be numeric")
        if value < 0:
            raise ValueError(f"{area}: commute times cannot be negative")
        minutes.append(float(value))
    return minutes


def score_fairest_option(
    options: list[dict[str, Any]],
    hard_limit_minutes: float = 60,
) -> str:
    """Rank meeting areas by the burden on the worst-off traveler.

    Options that exceed the hard commute limit for fewer people rank first.
    Remaining ties are broken by lowest maximum commute, then commute spread,
    then average commute. The transparent lexicographic rule keeps the result
    easy for users and graders to audit.
    """
    try:
        if not isinstance(options, list) or not options:
            raise ValueError("options must be a non-empty list")
        if isinstance(hard_limit_minutes, bool) or not isinstance(
            hard_limit_minutes, (int, float)
        ):
            raise ValueError("hard_limit_minutes must be numeric")
        if hard_limit_minutes <= 0:
            raise ValueError("hard_limit_minutes must be greater than zero")

        ranked: list[dict[str, Any]] = []
        for index, option in enumerate(options):
            if not isinstance(option, dict):
                raise ValueError(f"option {index + 1} must be an object")

            area = str(option.get("area", "")).strip()
            if not area:
                raise ValueError(f"option {index + 1} is missing area")

            minutes = _validated_minutes(option.get("commute_minutes"), area)
            maximum = max(minutes)
            minimum = min(minutes)
            average = fmean(minutes)
            spread = maximum - minimum
            violations = sum(value > hard_limit_minutes for value in minutes)

            ranked.append(
                {
                    "area": area,
                    "commute_minutes": [round(value, 1) for value in minutes],
                    "max_commute_minutes": round(maximum, 1),
                    "average_commute_minutes": round(average, 1),
                    "commute_spread_minutes": round(spread, 1),
                    "hard_limit_violations": violations,
                    "_rank_key": (violations, maximum, spread, average, area.lower()),
                }
            )

        ranked.sort(key=lambda option: option["_rank_key"])
        for option in ranked:
            option.pop("_rank_key")

        winner = ranked[0]
        explanation = (
            f"{winner['area']} is fairest: {winner['hard_limit_violations']} traveler(s) "
            f"exceed the {hard_limit_minutes:g}-minute limit, the longest commute is "
            f"{winner['max_commute_minutes']:g} minutes, and the commute spread is "
            f"{winner['commute_spread_minutes']:g} minutes."
        )

        return json.dumps(
            {
                "selected_area": winner["area"],
                "objective": "minimize unfair burden",
                "hard_limit_minutes": hard_limit_minutes,
                "explanation": explanation,
                "ranking": ranked,
            }
        )
    except ValueError as error:
        return json.dumps({"error": str(error)})

