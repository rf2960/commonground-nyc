"""Compute NYC public-transit matrices with Google Routes API."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
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
DRIVE_ESTIMATE_LOOKBACK_MINUTES = 45
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
        raise ValueError(f"{label}: coordinates must be within the NYC metro area")
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


def _normalized_arrival_time(raw_arrival_time: Any) -> str:
    if not isinstance(raw_arrival_time, str) or not raw_arrival_time.strip():
        raise ValueError("arrival_time must be an RFC 3339 timestamp")

    timestamp = raw_arrival_time.strip()
    try:
        parsed = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("arrival_time must be an RFC 3339 timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("arrival_time must include a timezone offset")
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


def _element_failure_reason(
    element: dict[str, Any], *, mode_label: str = "transit"
) -> str | None:
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
        return f"No {mode_label} route found ({condition or 'condition unavailable'})"
    return None


def _request_matrix(
    *,
    request_body: dict[str, Any],
    headers: dict[str, str],
    origin_count: int,
    destination_count: int,
    mode_label: str,
) -> tuple[dict[tuple[int, int], float], dict[tuple[int, int], str], str | None]:
    """Call Google Routes and normalize a streamed route-matrix response."""
    try:
        response = requests.post(
            ROUTE_MATRIX_URL,
            headers=headers,
            json=request_body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        return {}, {}, "Google Routes timed out; try again"
    except requests.RequestException as error:
        return {}, {}, f"Google Routes request failed: {type(error).__name__}"

    if response.status_code >= 400:
        return {}, {}, _provider_error_message(response)
    try:
        elements = response.json()
    except ValueError:
        return {}, {}, "Google Routes returned invalid JSON"
    if not isinstance(elements, list):
        return {}, {}, "Google Routes returned an invalid matrix response"

    durations: dict[tuple[int, int], float] = {}
    failures: dict[tuple[int, int], str] = {}
    seen_pairs: set[tuple[int, int]] = set()

    try:
        for element in elements:
            if not isinstance(element, dict):
                raise ValueError("Google Routes returned an invalid matrix element")
            pair = _element_indices(element, origin_count, destination_count)
            if pair in seen_pairs:
                raise ValueError("Google Routes returned a duplicate matrix element")
            seen_pairs.add(pair)

            failure_reason = _element_failure_reason(
                element, mode_label=mode_label
            )
            if failure_reason:
                failures[pair] = failure_reason
            else:
                durations[pair] = _duration_minutes(element.get("duration"))
    except ValueError as error:
        return {}, {}, str(error)

    for origin_index in range(origin_count):
        for destination_index in range(destination_count):
            pair = (origin_index, destination_index)
            if pair not in seen_pairs:
                failures[pair] = "Google Routes did not return this matrix element"

    return durations, failures, None


def get_transit_matrix(
    origins: list[dict[str, Any]],
    candidate_areas: list[dict[str, Any]],
    arrival_time: str,
    include_driving: bool = True,
) -> str:
    """Return door-to-door transit times with an optional driving fallback.

    Transit is preferred and includes the provider's walking connections to,
    from, and between public-transit stops. When enabled, driving is selected
    only for origin/destination pairs whose transit route is unavailable.
    """
    try:
        validated_origins = _validated_origins(origins)
        validated_areas = _validated_candidate_areas(candidate_areas)
        normalized_arrival_time = _normalized_arrival_time(arrival_time)
        if not isinstance(include_driving, bool):
            raise ValueError("include_driving must be a boolean")
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

    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": ROUTE_MATRIX_FIELD_MASK,
    }
    common_body = {
        "origins": [
            _waypoint(origin["lat"], origin["lng"])
            for origin in validated_origins
        ],
        "destinations": [
            _waypoint(area["lat"], area["lng"]) for area in validated_areas
        ],
        "languageCode": "en-US",
        "regionCode": "US",
    }
    transit_body = {
        **common_body,
        "travelMode": "TRANSIT",
        "arrivalTime": normalized_arrival_time,
    }
    transit_durations, transit_failures, transit_error = _request_matrix(
        request_body=transit_body,
        headers=headers,
        origin_count=len(validated_origins),
        destination_count=len(validated_areas),
        mode_label="transit",
    )

    if not include_driving and transit_error:
        return json.dumps({"error": transit_error})

    drive_durations: dict[tuple[int, int], float] = {}
    drive_failures: dict[tuple[int, int], str] = {}
    drive_error: str | None = None
    drive_departure_time: str | None = None
    if include_driving:
        parsed_arrival = datetime.fromisoformat(
            normalized_arrival_time.replace("Z", "+00:00")
        )
        drive_departure_time = (
            parsed_arrival - timedelta(minutes=DRIVE_ESTIMATE_LOOKBACK_MINUTES)
        ).isoformat(timespec="seconds").replace("+00:00", "Z")
        drive_body = {
            **common_body,
            "travelMode": "DRIVE",
            "departureTime": drive_departure_time,
            "routingPreference": "TRAFFIC_AWARE",
        }
        drive_durations, drive_failures, drive_error = _request_matrix(
            request_body=drive_body,
            headers=headers,
            origin_count=len(validated_origins),
            destination_count=len(validated_areas),
            mode_label="driving",
        )

    if include_driving and transit_error and drive_error:
        return json.dumps(
            {
                "error": "Google Routes could not compute transit or driving matrices",
                "mode_errors": {
                    "transit": transit_error,
                    "driving": drive_error,
                },
            }
        )

    if not include_driving:
        unavailable_routes = [
            {
                "traveler_id": validated_origins[origin_index]["traveler_id"],
                "area": validated_areas[destination_index]["area"],
                "reason": reason,
            }
            for (origin_index, destination_index), reason in sorted(
                transit_failures.items()
            )
        ]
        complete_areas: list[dict[str, Any]] = []
        excluded_areas: list[str] = []
        for destination_index, area in enumerate(validated_areas):
            if any(
                (origin_index, destination_index) in transit_failures
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
                        transit_durations[(origin_index, destination_index)]
                        for origin_index in range(len(validated_origins))
                    ],
                }
            )

        result: dict[str, Any] = {
            "areas": complete_areas,
            "traveler_ids": [
                origin["traveler_id"] for origin in validated_origins
            ],
            "provider": "google_routes",
            "arrival_time": normalized_arrival_time,
            "excluded_areas": excluded_areas,
            "unavailable_routes": unavailable_routes,
            "attribution": (
                f"Powered by Google, ©{datetime.now(timezone.utc).year} Google"
            ),
        }
        if not complete_areas:
            result["error"] = "No candidate area has transit routes for every traveler"
        return json.dumps(result)

    mode_failures = [
        {
            "traveler_id": validated_origins[origin_index]["traveler_id"],
            "area": validated_areas[destination_index]["area"],
            "mode": mode,
            "reason": reason,
        }
        for mode, failures in (
            ("transit", transit_failures),
            ("driving", drive_failures),
        )
        for (origin_index, destination_index), reason in sorted(failures.items())
    ]

    complete_areas: list[dict[str, Any]] = []
    excluded_areas: list[str] = []
    unavailable_routes: list[dict[str, Any]] = []
    for destination_index, area in enumerate(validated_areas):
        commute_options: list[dict[str, Any]] = []
        area_is_available = True
        for origin_index, origin in enumerate(validated_origins):
            pair = (origin_index, destination_index)
            transit_minutes = transit_durations.get(pair)
            drive_minutes = drive_durations.get(pair)
            if transit_minutes is not None:
                selected_mode = "transit"
                effective_minutes = transit_minutes
            elif drive_minutes is not None:
                selected_mode = "drive_fallback"
                effective_minutes = drive_minutes
            else:
                area_is_available = False
                unavailable_routes.append(
                    {
                        "traveler_id": origin["traveler_id"],
                        "area": area["area"],
                        "reason": "No transit or driving route was available",
                    }
                )
                continue
            commute_options.append(
                {
                    "traveler_id": origin["traveler_id"],
                    "transit_minutes": transit_minutes,
                    "drive_minutes": drive_minutes,
                    "selected_mode": selected_mode,
                    "effective_minutes": effective_minutes,
                }
            )

        if not area_is_available:
            excluded_areas.append(area["area"])
            continue
        complete_areas.append(
            {
                "area": area["area"],
                "lat": area["lat"],
                "lng": area["lng"],
                "commute_minutes": [
                    option["effective_minutes"] for option in commute_options
                ],
                "commute_options": commute_options,
                "drive_fallback_count": sum(
                    option["selected_mode"] == "drive_fallback"
                    for option in commute_options
                ),
            }
        )

    mode_errors = {
        mode: error
        for mode, error in (("transit", transit_error), ("driving", drive_error))
        if error
    }
    result = {
        "areas": complete_areas,
        "traveler_ids": [origin["traveler_id"] for origin in validated_origins],
        "provider": "google_routes",
        "arrival_time": normalized_arrival_time,
        "drive_departure_time": drive_departure_time,
        "drive_estimate_lookback_minutes": DRIVE_ESTIMATE_LOOKBACK_MINUTES,
        "excluded_areas": excluded_areas,
        "unavailable_routes": unavailable_routes,
        "mode_failures": mode_failures,
        "mode_errors": mode_errors,
        "partial": bool(mode_failures or mode_errors or excluded_areas),
        "warnings": [
            "Transit durations are door-to-door estimates that may include walking, bus, subway, train, and transfers.",
            "Driving is used only when transit is unavailable. It approximates car or rideshare travel; pickup, parking, and drop-off time are not included.",
            f"Driving traffic is estimated for a departure {DRIVE_ESTIMATE_LOOKBACK_MINUTES} minutes before the requested meeting time.",
        ],
        "attribution": f"Powered by Google, ©{datetime.now(timezone.utc).year} Google",
    }
    if not complete_areas:
        result["status"] = "no_complete_commute_options"
        result["message"] = (
            "No candidate has a transit or driving option for every traveler. "
            "Continue with cafe search using the original candidate areas instead "
            "of repeatedly asking the user to change the same inputs."
        )
    return json.dumps(result)
