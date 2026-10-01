"""Transparent cafe ranking; no provider calls or invented cafe attributes."""
from __future__ import annotations

import json
import math
from typing import Any


def _number(value: Any, field: str, low: float, high: float | None = None) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be numeric")
    if not math.isfinite(value) or value < low or (high is not None and value > high):
        raise ValueError(f"{field} must be finite and between {low} and {high or 'infinity'}")
    return float(value)


def score_best_cafe_option(
    cafes: list[dict[str, Any]],
    min_rating: float = 0,
    price_levels: list[int] | None = None,
    require_open: bool = True,
    max_station_distance_meters: float | None = None,
) -> str:
    """Filter constraints, then rank evidence-adjusted rating and station access.

    Rating adjustment = (review_count * rating + 50 * 4.0) / (review_count + 50).
    4.0 and 50 are explicit design constants, not estimated NYC population data.
    Unknown review counts use zero evidence; unknown opening hours remain provisional.
    """
    try:
        if not isinstance(cafes, list) or not cafes:
            raise ValueError("cafes must be a non-empty list")
        threshold = _number(min_rating, "min_rating", 0, 5)
        if not isinstance(require_open, bool):
            raise ValueError("require_open must be boolean")
        if price_levels is not None:
            if not isinstance(price_levels, list) or not price_levels or any(
                isinstance(p, bool) or not isinstance(p, int) or p not in range(5)
                for p in price_levels
            ):
                raise ValueError("price_levels must be a non-empty list of integers 0–4")
        distance_limit = None if max_station_distance_meters is None else _number(
            max_station_distance_meters, "max_station_distance_meters", 0
        )
        ranking, excluded = [], []
        for index, cafe in enumerate(cafes):
            if not isinstance(cafe, dict) or not isinstance(cafe.get("name"), str) or not cafe["name"].strip():
                raise ValueError(f"cafe {index + 1} needs a non-empty name")
            name = cafe["name"].strip()
            rating = cafe.get("rating")
            rating = None if rating is None else _number(rating, f"{name}.rating", 0, 5)
            reviews = cafe.get("review_count")
            if reviews is not None:
                _number(reviews, f"{name}.review_count", 0)
                if not isinstance(reviews, int):
                    raise ValueError(f"{name}.review_count must be an integer")
            price = cafe.get("price_level")
            if price is not None and (isinstance(price, bool) or not isinstance(price, int) or price not in range(5)):
                raise ValueError(f"{name}.price_level must be an integer 0–4 or null")
            opened = cafe.get("open_at_meeting_time")
            if opened is not None and not isinstance(opened, bool):
                raise ValueError(f"{name}.open_at_meeting_time must be boolean or null")
            distance = cafe.get("station_distance_meters")
            distance = None if distance is None else _number(distance, f"{name}.station_distance_meters", 0)
            reasons, warnings = [], []
            if rating is None:
                reasons.append("Rating unavailable; cannot compare cafe quality.")
            elif rating < threshold:
                reasons.append(f"Rating {rating:g} is below minimum {threshold:g}.")
            if price_levels is not None and price not in price_levels:
                reasons.append("Price is unknown or outside the allowed price levels.")
            if require_open and opened is False:
                reasons.append("Expected closed according to regular weekly hours; holiday exceptions are unverified." if cafe.get("opening_status_source") == "regular_schedule" else "Closed at the meeting time.")
            if distance_limit is not None and (distance is None or distance > distance_limit):
                reasons.append("Station distance is unknown or above the allowed maximum.")
            if reasons:
                excluded.append({"name": name, "place_id": cafe.get("place_id"), "reasons": reasons})
                continue
            schedule_estimate = cafe.get("opening_status_source") == "regular_schedule"
            if schedule_estimate:
                warnings.append("Opening estimate uses regular weekly hours; holiday hours and last-minute changes are unverified.")
            if opened is None:
                warnings.append("Opening status at meeting time is unverified; check before going.")
            if price is None:
                warnings.append("Price level is unavailable.")
            if reviews is None:
                warnings.append("Review count is unavailable; use zero review evidence for scoring.")
            if distance is None:
                warnings.append("Station distance is unavailable; do not assume convenient access.")
            count = reviews if reviews is not None else 0
            adjusted = (count * rating + 50 * 4.0) / (count + 50)
            entry = {"cafe": dict(cafe), "factor_breakdown": {
                "raw_rating": rating, "review_count": reviews,
                "adjusted_rating": round(adjusted, 4), "review_evidence_weight": round(count / (count + 50), 4),
                "price_level": price, "open_at_meeting_time": opened,
                "station_distance_meters": distance,
            }, "warnings": warnings, "provisional": require_open and (opened is None or schedule_estimate),
                "_key": (-adjusted, distance if distance is not None else float('inf'), -count, name.casefold(), str(cafe.get('place_id', '')))}
            ranking.append(entry)
        ranking.sort(key=lambda entry: entry['_key'])
        for rank, entry in enumerate(ranking, 1):
            entry.pop('_key')
            entry['rank'] = rank
        winner = ranking[0] if ranking else None
        return json.dumps({
            "selected_cafe": winner['cafe'] if winner else None,
            "objective": "best cafe quality within group constraints",
            "scoring_rule": {
                "formula": "(review_count * rating + 50 * 4.0) / (review_count + 50)",
                "design_prior_rating": 4.0, "design_prior_review_count": 50,
                "tie_breakers": ["shorter known station distance", "more reviews", "name", "place_id"],
                "note": "Design heuristic, not a satisfaction probability or measured NYC average. Price levels are categories, not exact dollar prices.",
            },
            "explanation": (f"{winner['cafe']['name']} has the highest evidence-adjusted rating among cafes passing the constraints."
                + (" Meeting-time opening is unverified or based only on regular hours, so this recommendation is provisional." if winner['provisional'] else ""))
                if winner else "No cafe meets the constraints. Search another area or ask the group whether to relax a filter; do not silently relax it.",
            "ranking": ranking, "excluded": excluded,
        }, allow_nan=False)
    except ValueError as error:
        return json.dumps({"error": str(error), "action": "Correct the named field and call score_best_cafe_option again."})
