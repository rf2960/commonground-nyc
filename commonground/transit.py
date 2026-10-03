"""Compute NYC public-transit matrices with Google Routes API."""

from __future__ import annotations

from datetime import datetime, timezone
import json
import math
import os
import re
from typing import Any

import requests

from .candidates import MAX_CANDIDATE_COUNT
from .locations import MAX_GROUP_SIZE, NYC_VIEWPORT


ROUTE_MATRIX_URL = (
    "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix"
)
ROUTE_MATRIX_FIELD_MASK = (
    "originIndex,destinationIndex,status,condition,duration"
)
REQUEST_TIMEOUT_SECONDS = 30
_DURATION_PATTERN = re.compile(r"^(\d+(?:\.\d{1,9})?)s$")


def _validated_coordinates(
    record: dict[str, Any],
    *,
    label: str,
) -> tuple[float, float]:
    latitude = record.get("lat")
    longitude = record.get("lng")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
    ):
        raise ValueError(f"{label}: lat and lng must be finite numeric values")

    low = NYC_VIEWPORT["low"]
    high = NYC_VIEWPORT["high"]
    if not (
        low["latitude"] <= latitude <= high["latitude"]
        and low["longitude"] <= longitude <= high["longitude"]
    ):
        raise ValueError(f"{label}: coordinates must be within New York City")
    return float(latitude), float(longitude)


def _validated_origins(origins: Any) -> list[dict[str, Any]]:
    if not isinstance(origins, list) or len(origins) < 2:
        raise ValueError("origins must contain at least 2 travelers")
    if len(origins) > MAX_GROUP_SIZE:
        raise ValueError(f"origins supports at most {MAX_GROUP_SIZE} travelers")

    validated: list[dict[str, Any]] = []
    seen_traveler_ids: set[str] = set()
    for index, origin in enumerate(origins):
        if not isinstance(origin, dict):
            raise ValueError(f"origin {index + 1} must be an object")
        traveler_id = origin.get("traveler_id")
        if not isinstance(traveler_id, str) or not traveler_id.strip():
            raise ValueError(f"origin {index + 1} is missing traveler_id")
        traveler_id = traveler_id.strip()
        normalized_id = traveler_id.casefold()
        if normalized_id in seen_traveler_ids:
            raise ValueError(f"duplicate traveler_id: {traveler_id}")
        seen_traveler_ids.add(normalized_id)
        latitude, longitude = _validated_coordinates(origin, label=traveler_id)
        validated.append(
            {"traveler_id": traveler_id, "lat": latitude, "lng": longitude}
        )
    return validated


def _validated_candidate_areas(candidate_areas: Any) -> list[dict[str, Any]]:
    if not isinstance(candidate_areas, list) or not candidate_areas:
        raise ValueError("candidate_areas must be a non-empty list")
    if len(candidate_areas) > MAX_CANDIDATE_COUNT:
        raise ValueError(
            f"candidate_areas supports at most {MAX_CANDIDATE_COUNT} areas"
        )

    validated: list[dict[str, Any]] = []
    seen_areas: set[str] = set()
    for index, candidate in enumerate(candidate_areas):
        if not isinstance(candidate, dict):
            raise ValueError(f"candidate area {index + 1} must be an object")
        area = candidate.get("area")
        if not isinstance(area, str) or not area.strip():
            raise ValueError(f"candidate area {index + 1} is missing area")
        area = area.strip()
        normalized_area = area.casefold()
        if normalized_area in seen_areas:
            raise ValueError(f"duplicate candidate area: {area}")
        seen_areas.add(normalized_area)
        latitude, longitude = _validated_coordinates(candidate, label=area)
        validated.append({"area": area, "lat": latitude, "lng": longitude})
    return validated


def _normalized_departure_time(raw_departure_time: Any) -> str:
    if not isinstance(raw_departure_time, str) or not raw_departure_time.strip():
        raise ValueError("departure_time must be an RFC 3339 timestamp")

    timestamp = raw_departure_time.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("departure_time must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("departure_time must include a timezone offset")
    return (
        parsed.astimezone(timezone.utc)
        .isoformat(timespec="seconds")
        .replace("+00:00", "Z")
    )


def _waypoint(latitude: float, longitude: float) -> dict[str, Any]:
    return {
        "waypoint": {
            "location": {
                "latLng": {"latitude": latitude, "longitude": longitude}
            }
        }
    }


def _provider_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Google Routes returned HTTP {response.status_code}"
    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message.strip():
        return f"Google Routes returned HTTP {response.status_code}: {message.strip()[:240]}"
    return f"Google Routes returned HTTP {response.status_code}"


def _duration_minutes(raw_duration: Any) -> float:
    if not isinstance(raw_duration, str):
        raise ValueError("route duration is missing")
    match = _DURATION_PATTERN.fullmatch(raw_duration)
    if not match:
        raise ValueError("route duration has an invalid format")
    seconds = float(match.group(1))
    if not math.isfinite(seconds):
        raise ValueError("route duration must be finite")
    return round(seconds / 60, 1)


def _element_indices(
    element: dict[str, Any],
    origin_count: int,
    destination_count: int,
) -> tuple[int, int]:
    # Proto3 may omit a scalar field whose value is zero, so absent indices
    # represent the first origin or destination.
    origin_index = element.get("originIndex", 0)
    destination_index = element.get("destinationIndex", 0)
    if (
        isinstance(origin_index, bool)
        or isinstance(destination_index, bool)
        or not isinstance(origin_index, int)
        or not isinstance(destination_index, int)
        or not 0 <= origin_index < origin_count
        or not 0 <= destination_index < destination_count
    ):
        raise ValueError("Google Routes returned an invalid matrix index")
    return origin_index, destination_index


def _element_failure_reason(element: dict[str, Any]) -> str | None:
    status = element.get("status")
    if isinstance(status, dict):
        status_code = status.get("code", 0)
        if status_code:
            message = status.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()[:240]
            return f"Google Routes element status {status_code}"
    elif status is not None:
        return "Google Routes returned an invalid element status"

    condition = element.get("condition")
    if condition != "ROUTE_EXISTS":
        return f"No transit route found ({condition or 'condition unavailable'})"
    return None


def get_transit_matrix(
    origins: list[dict[str, Any]],
    candidate_areas: list[dict[str, Any]],
    departure_time: str,
) -> str:
    """Return complete per-area transit times for every traveler.

    Candidate areas with one or more unavailable routes are excluded from the
    scoring-ready ``areas`` list and described in ``unavailable_routes``.
    """
    try:
        validated_origins = _validated_origins(origins)
        validated_areas = _validated_candidate_areas(candidate_areas)
        normalized_departure_time = _normalized_departure_time(departure_time)
    except ValueError as error:
        return json.dumps({"error": str(error)})

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return json.dumps(
            {
                "error": (
                    "GOOGLE_MAPS_API_KEY is not configured on the server. Enable "
                    "Routes API and set the environment variable."
                )
            }
        )

    request_body = {
        "origins": [
            _waypoint(origin["lat"], origin["lng"])
            for origin in validated_origins
        ],
        "destinations": [
            _waypoint(area["lat"], area["lng"]) for area in validated_areas
        ],
        "travelMode": "TRANSIT",
        "departureTime": normalized_departure_time,
        "languageCode": "en-US",
        "regionCode": "US",
    }
    try:
        response = requests.post(
            ROUTE_MATRIX_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": ROUTE_MATRIX_FIELD_MASK,
            },
            json=request_body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        return json.dumps({"error": "Google Routes timed out; try again"})
    except requests.RequestException as error:
        return json.dumps(
            {"error": f"Google Routes request failed: {type(error).__name__}"}
        )

    if response.status_code >= 400:
        return json.dumps({"error": _provider_error_message(response)})
    try:
        elements = response.json()
    except ValueError:
        return json.dumps({"error": "Google Routes returned invalid JSON"})
    if not isinstance(elements, list):
        return json.dumps({"error": "Google Routes returned an invalid matrix response"})

    durations: dict[tuple[int, int], float] = {}
    failures: dict[tuple[int, int], str] = {}
    seen_pairs: set[tuple[int, int]] = set()

    try:
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError("Google Routes returned an invalid matrix element")
            pair = _element_indices(
                element, len(validated_origins), len(validated_areas)
            )
            if pair in seen_pairs:
                raise ValueError("Google Routes returned a duplicate matrix element")
            seen_pairs.add(pair)

            failure_reason = _element_failure_reason(element)
            if failure_reason:
                failures[pair] = failure_reason
            else:
                durations[pair] = _duration_minutes(element.get("duration"))
    except ValueError as error:
        return json.dumps({"error": str(error)})

    for origin_index in range(len(validated_origins)):
        for destination_index in range(len(validated_areas)):
            pair = (origin_index, destination_index)
            if pair not in seen_pairs:
                failures[pair] = "Google Routes did not return this matrix element"

    unavailable_routes = [
        {
            "traveler_id": validated_origins[origin_index]["traveler_id"],
            "area": validated_areas[destination_index]["area"],
            "reason": reason,
        }
        for (origin_index, destination_index), reason in sorted(failures.items())
    ]

    complete_areas: list[dict[str, Any]] = []
    excluded_areas: list[str] = []
    for destination_index, area in enumerate(validated_areas):
        if any(
            (origin_index, destination_index) in failures
            for origin_index in range(len(validated_origins))
        ):
            excluded_areas.append(area["area"])
            continue
        complete_areas.append(
            {
                "area": area["area"],
                "lat": area["lat"],
                "lng": area["lng"],
                "commute_minutes": [
                    durations[(origin_index, destination_index)]
                    for origin_index in range(len(validated_origins))
                ],
            }
        )

    result: dict[str, Any] = {
        "areas": complete_areas,
        "traveler_ids": [origin["traveler_id"] for origin in validated_origins],
        "provider": "google_routes",
        "departure_time": normalized_departure_time,
        "excluded_areas": excluded_areas,
        "unavailable_routes": unavailable_routes,
        "attribution": f"Powered by Google, ©{datetime.now(timezone.utc).year} Google",
    }
    if not complete_areas:
        result["error"] = "No candidate area has transit routes for every traveler"
    return json.dumps(result)
