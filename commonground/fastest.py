"""Explainable speed scoring for candidate meeting areas."""

from __future__ import annotations

import json
import math
from statistics import fmean
from typing import Any


def _validated_minutes(raw_minutes: Any, area: str) -> list[float]:
    if not isinstance(raw_minutes, list) or not raw_minutes:
        raise ValueError(f"{area}: commute_minutes must be a non-empty list")

    minutes: list[float] = []
    for value in raw_minutes:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{area}: every commute time must be numeric")
        if not math.isfinite(value):
            raise ValueError(f"{area}: commute times must be finite")
        if value < 0:
            raise ValueError(f"{area}: commute times cannot be negative")
        minutes.append(float(value))
    return minutes


def score_fastest_option(options: list[dict[str, Any]]) -> str:
    """Rank meeting areas by total group travel time.

    The option with the lowest total commute ranks first. Ties are broken by
    the lowest maximum individual commute, then by area name so identical
    inputs always produce a stable result. Every option must contain one
    commute time per traveler; otherwise totals would not be comparable.
    """
    try:
        if not isinstance(options, list) or not options:
            raise ValueError("options must be a non-empty list")

        ranked: list[dict[str, Any]] = []
        expected_traveler_count: int | None = None
        seen_areas: set[str] = set()

        for index, option in enumerate(options):
            if not isinstance(option, dict):
                raise ValueError(f"option {index + 1} must be an object")

            area = str(option.get("area", "")).strip()
            if not area:
                raise ValueError(f"option {index + 1} is missing area")

            normalized_area = area.casefold()
            if normalized_area in seen_areas:
                raise ValueError(f"duplicate area: {area}")
            seen_areas.add(normalized_area)

            minutes = _validated_minutes(option.get("commute_minutes"), area)
            if expected_traveler_count is None:
                expected_traveler_count = len(minutes)
            elif len(minutes) != expected_traveler_count:
                raise ValueError(
                    f"{area}: expected {expected_traveler_count} commute time(s), "
                    f"received {len(minutes)}"
                )

            total = sum(minutes)
            maximum = max(minutes)
            minimum = min(minutes)
            average = fmean(minutes)

            ranked.append(
                {
                    "area": area,
                    "commute_minutes": [round(value, 1) for value in minutes],
                    "total_commute_minutes": round(total, 1),
                    "average_commute_minutes": round(average, 1),
                    "max_commute_minutes": round(maximum, 1),
                    "commute_spread_minutes": round(maximum - minimum, 1),
                    "_rank_key": (total, maximum, normalized_area),
                }
            )

        ranked.sort(key=lambda option: option["_rank_key"])
        for option in ranked:
            option.pop("_rank_key")

        winner = ranked[0]
        explanation = (
            f"{winner['area']} is fastest for the group: total travel time is "
            f"{winner['total_commute_minutes']:g} minutes, averaging "
            f"{winner['average_commute_minutes']:g} minutes per traveler, with a "
            f"longest commute of {winner['max_commute_minutes']:g} minutes. Options "
            "are ranked by total travel time, then longest individual commute."
        )

        return json.dumps(
            {
                "selected_area": winner["area"],
                "objective": "minimize total group travel time",
                "traveler_count": expected_traveler_count,
                "explanation": explanation,
                "ranking": ranked,
            }
        )
    except ValueError as error:
        return json.dumps({"error": str(error)})
