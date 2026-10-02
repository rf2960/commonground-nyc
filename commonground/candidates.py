"""Generate a small, diverse set of NYC transit-hub candidates."""

from __future__ import annotations

import json
import math
from typing import Any

from .locations import MAX_GROUP_SIZE, NYC_VIEWPORT


EARTH_RADIUS_KM = 6371.0088
DEFAULT_CANDIDATE_COUNT = 4
MAX_CANDIDATE_COUNT = 6

# Stable station-complex coordinates used only to create a shortlist. Google
# Routes travel times, not these straight-line distances, decide the winners.
TRANSIT_HUBS = (
    {"area": "125 St-Lexington Ave", "borough": "Manhattan", "lat": 40.8041, "lng": -73.9376},
    {"area": "Columbus Circle", "borough": "Manhattan", "lat": 40.7681, "lng": -73.9819},
    {"area": "Times Square", "borough": "Manhattan", "lat": 40.7580, "lng": -73.9855},
    {"area": "Herald Square", "borough": "Manhattan", "lat": 40.7496, "lng": -73.9879},
    {"area": "Grand Central", "borough": "Manhattan", "lat": 40.7527, "lng": -73.9772},
    {"area": "Union Square", "borough": "Manhattan", "lat": 40.7359, "lng": -73.9911},
    {"area": "Fulton Center", "borough": "Manhattan", "lat": 40.7104, "lng": -74.0086},
    {"area": "Atlantic Terminal", "borough": "Brooklyn", "lat": 40.6845, "lng": -73.9775},
    {"area": "Jay St-MetroTech", "borough": "Brooklyn", "lat": 40.6922, "lng": -73.9867},
    {"area": "Bedford Ave", "borough": "Brooklyn", "lat": 40.7172, "lng": -73.9565},
    {"area": "Broadway Junction", "borough": "Brooklyn", "lat": 40.6783, "lng": -73.9053},
    {"area": "Court Square", "borough": "Queens", "lat": 40.7470, "lng": -73.9453},
    {"area": "Queensboro Plaza", "borough": "Queens", "lat": 40.7506, "lng": -73.9402},
    {"area": "Jackson Hts-Roosevelt Ave", "borough": "Queens", "lat": 40.7466, "lng": -73.8913},
    {"area": "Jamaica Center", "borough": "Queens", "lat": 40.7021, "lng": -73.8011},
    {"area": "149 St-Grand Concourse", "borough": "Bronx", "lat": 40.8184, "lng": -73.9274},
    {"area": "St George Terminal", "borough": "Staten Island", "lat": 40.6437, "lng": -74.0736},
)


def _haversine_km(
    first_lat: float,
    first_lng: float,
    second_lat: float,
    second_lng: float,
) -> float:
    first_lat_radians = math.radians(first_lat)
    second_lat_radians = math.radians(second_lat)
    latitude_delta = math.radians(second_lat - first_lat)
    longitude_delta = math.radians(second_lng - first_lng)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(first_lat_radians)
        * math.cos(second_lat_radians)
        * math.sin(longitude_delta / 2) ** 2
    )
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(haversine))


def _validated_origins(resolved_locations: Any) -> list[dict[str, Any]]:
    if not isinstance(resolved_locations, list) or len(resolved_locations) < 2:
        raise ValueError("resolved_locations must contain at least 2 travelers")
    if len(resolved_locations) > MAX_GROUP_SIZE:
        raise ValueError(
            f"resolved_locations supports at most {MAX_GROUP_SIZE} travelers"
        )

    validated: list[dict[str, Any]] = []
    seen_traveler_ids: set[str] = set()
    low = NYC_VIEWPORT["low"]
    high = NYC_VIEWPORT["high"]

    for index, origin in enumerate(resolved_locations):
        if not isinstance(origin, dict):
            raise ValueError(f"resolved location {index + 1} must be an object")

        traveler_id = origin.get("traveler_id")
        if not isinstance(traveler_id, str) or not traveler_id.strip():
            raise ValueError(
                f"resolved location {index + 1} is missing traveler_id"
            )
        traveler_id = traveler_id.strip()
        normalized_traveler_id = traveler_id.casefold()
        if normalized_traveler_id in seen_traveler_ids:
            raise ValueError(f"duplicate traveler_id: {traveler_id}")
        seen_traveler_ids.add(normalized_traveler_id)

        latitude = origin.get("lat")
        longitude = origin.get("lng")
        if (
            isinstance(latitude, bool)
            or isinstance(longitude, bool)
            or not isinstance(latitude, (int, float))
            or not isinstance(longitude, (int, float))
            or not math.isfinite(latitude)
            or not math.isfinite(longitude)
        ):
            raise ValueError(
                f"{traveler_id}: lat and lng must be finite numeric values"
            )
        if not (
            low["latitude"] <= latitude <= high["latitude"]
            and low["longitude"] <= longitude <= high["longitude"]
        ):
            raise ValueError(f"{traveler_id}: coordinates must be within New York City")

        validated.append(
            {"traveler_id": traveler_id, "lat": float(latitude), "lng": float(longitude)}
        )

    return validated


def _validated_candidate_count(max_candidates: Any) -> int:
    if isinstance(max_candidates, bool) or not isinstance(max_candidates, int):
        raise ValueError("max_candidates must be an integer")
    if not 1 <= max_candidates <= MAX_CANDIDATE_COUNT:
        raise ValueError(
            f"max_candidates must be between 1 and {MAX_CANDIDATE_COUNT}"
        )
    return max_candidates


def generate_candidate_areas(
    resolved_locations: list[dict[str, Any]],
    max_candidates: int = DEFAULT_CANDIDATE_COUNT,
) -> str:
    """Select transit hubs using complementary geographic shortlist heuristics.

    The generator alternates between hubs with the lowest average distance,
    lowest worst-person distance, and shortest distance to the group centroid.
    These are only shortlist heuristics; real transit durations must determine
    the final fairest and fastest recommendations.
    """
    try:
        origins = _validated_origins(resolved_locations)
        candidate_count = _validated_candidate_count(max_candidates)
    except ValueError as error:
        return json.dumps({"error": str(error)})

    centroid_latitude = sum(origin["lat"] for origin in origins) / len(origins)
    centroid_longitude = sum(origin["lng"] for origin in origins) / len(origins)
    scored_hubs: list[dict[str, Any]] = []

    for hub in TRANSIT_HUBS:
        distances = [
            _haversine_km(origin["lat"], origin["lng"], hub["lat"], hub["lng"])
            for origin in origins
        ]
        scored_hubs.append(
            {
                **hub,
                "average_distance_km": sum(distances) / len(distances),
                "maximum_distance_km": max(distances),
                "centroid_distance_km": _haversine_km(
                    centroid_latitude,
                    centroid_longitude,
                    hub["lat"],
                    hub["lng"],
                ),
            }
        )

    rankings = (
        sorted(
            scored_hubs,
            key=lambda hub: (
                hub["average_distance_km"],
                hub["maximum_distance_km"],
                hub["area"].casefold(),
            ),
        ),
        sorted(
            scored_hubs,
            key=lambda hub: (
                hub["maximum_distance_km"],
                hub["average_distance_km"],
                hub["area"].casefold(),
            ),
        ),
        sorted(
            scored_hubs,
            key=lambda hub: (
                hub["centroid_distance_km"],
                hub["average_distance_km"],
                hub["area"].casefold(),
            ),
        ),
    )

    selected: list[dict[str, Any]] = []
    selected_names: set[str] = set()
    while len(selected) < candidate_count:
        for ranking in rankings:
            next_hub = next(
                hub for hub in ranking if hub["area"] not in selected_names
            )
            selected.append(next_hub)
            selected_names.add(next_hub["area"])
            if len(selected) == candidate_count:
                break

    candidate_areas = [
        {
            "area": hub["area"],
            "lat": hub["lat"],
            "lng": hub["lng"],
        }
        for hub in selected
    ]
    return json.dumps(
        {
            "candidate_areas": candidate_areas,
            "strategy": (
                "Geographic shortlist alternating lowest average distance, "
                "lowest maximum distance, and nearest group centroid. Use real "
                "transit times for final ranking."
            ),
        }
    )
