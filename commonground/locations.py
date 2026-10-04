"""Resolve user-supplied NYC-metro locations with Google Places Text Search."""

from __future__ import annotations

import json
import math
import os
from typing import Any

import requests


PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
PLACES_FIELD_MASK = (
    "places.id,places.displayName,places.formattedAddress,places.location,"
    "places.primaryType"
)
REQUEST_TIMEOUT_SECONDS = 10
MAX_GROUP_SIZE = 6

# Covers the five boroughs plus common nearby commuter origins such as Fort Lee,
# Hoboken, and Jersey City. Candidate meeting areas remain centered in NYC.
NYC_VIEWPORT = {
    "low": {"latitude": 40.45, "longitude": -74.35},
    "high": {"latitude": 41.05, "longitude": -73.65},
}

AREA_PRIMARY_TYPES = {
    "administrative_area_level_1",
    "administrative_area_level_2",
    "locality",
    "neighborhood",
    "postal_code",
    "sublocality",
}


def _validated_locations(locations: Any) -> list[dict[str, str]]:
    if not isinstance(locations, list) or not locations:
        raise ValueError("locations must be a non-empty list")
    if len(locations) > MAX_GROUP_SIZE:
        raise ValueError(f"locations supports at most {MAX_GROUP_SIZE} travelers")

    validated: list[dict[str, str]] = []
    seen_traveler_ids: set[str] = set()

    for index, location in enumerate(locations):
        if not isinstance(location, dict):
            raise ValueError(f"location {index + 1} must be an object")

        traveler_id = location.get("traveler_id")
        query = location.get("query")
        if not isinstance(traveler_id, str) or not traveler_id.strip():
            raise ValueError(f"location {index + 1} is missing traveler_id")
        if not isinstance(query, str) or not query.strip():
            raise ValueError(f"location {index + 1} is missing query")

        traveler_id = traveler_id.strip()
        query = query.strip()
        normalized_traveler_id = traveler_id.casefold()
        if normalized_traveler_id in seen_traveler_ids:
            raise ValueError(f"duplicate traveler_id: {traveler_id}")
        seen_traveler_ids.add(normalized_traveler_id)
        validated.append({"traveler_id": traveler_id, "query": query})

    return validated


def _provider_error_message(response: requests.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"Google Places returned HTTP {response.status_code}"

    error = payload.get("error") if isinstance(payload, dict) else None
    message = error.get("message") if isinstance(error, dict) else None
    if isinstance(message, str) and message.strip():
        return f"Google Places returned HTTP {response.status_code}: {message.strip()[:240]}"
    return f"Google Places returned HTTP {response.status_code}"


def _resolved_place(place: Any, traveler_id: str, query: str) -> dict[str, Any]:
    if not isinstance(place, dict):
        raise ValueError("Google Places returned an invalid place record")

    place_id = place.get("id")
    location = place.get("location")
    display_name = place.get("displayName")
    if not isinstance(place_id, str) or not place_id:
        raise ValueError("Google Places result is missing place_id")
    if not isinstance(location, dict):
        raise ValueError("Google Places result is missing coordinates")

    latitude = location.get("latitude")
    longitude = location.get("longitude")
    if (
        isinstance(latitude, bool)
        or isinstance(longitude, bool)
        or not isinstance(latitude, (int, float))
        or not isinstance(longitude, (int, float))
        or not math.isfinite(latitude)
        or not math.isfinite(longitude)
    ):
        raise ValueError("Google Places result has invalid coordinates")

    low = NYC_VIEWPORT["low"]
    high = NYC_VIEWPORT["high"]
    if not (
        low["latitude"] <= latitude <= high["latitude"]
        and low["longitude"] <= longitude <= high["longitude"]
    ):
        raise ValueError("Google Places result is outside the NYC metro area")

    formatted_address = place.get("formattedAddress")
    if not isinstance(formatted_address, str) or not formatted_address.strip():
        if isinstance(display_name, dict):
            formatted_address = display_name.get("text")
    if not isinstance(formatted_address, str) or not formatted_address.strip():
        raise ValueError("Google Places result is missing a readable address")

    primary_type = place.get("primaryType")
    location_precision = (
        "area_estimate" if primary_type in AREA_PRIMARY_TYPES else "specific_place"
    )

    return {
        "traveler_id": traveler_id,
        "input_location": query,
        "formatted_address": formatted_address.strip(),
        "lat": float(latitude),
        "lng": float(longitude),
        "place_id": place_id,
        "location_precision": location_precision,
    }


def _search_nyc_place(query: str, api_key: str) -> tuple[dict[str, Any] | None, str | None]:
    try:
        response = requests.post(
            PLACES_TEXT_SEARCH_URL,
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": PLACES_FIELD_MASK,
            },
            json={
                "textQuery": query,
                "languageCode": "en",
                "regionCode": "US",
                "pageSize": 1,
                "locationRestriction": {"rectangle": NYC_VIEWPORT},
            },
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.Timeout:
        return None, "Google Places timed out; try again"
    except requests.RequestException as error:
        return None, f"Google Places request failed: {type(error).__name__}"

    if response.status_code >= 400:
        return None, _provider_error_message(response)

    try:
        payload = response.json()
    except ValueError:
        return None, "Google Places returned invalid JSON"
    if not isinstance(payload, dict):
        return None, "Google Places returned an invalid response"

    places = payload.get("places")
    if not isinstance(places, list) or not places:
        return None, "No matching place was found within the NYC metro area"
    return places[0], None


def resolve_group_locations(locations: list[dict[str, Any]]) -> str:
    """Resolve 1-6 traveler queries to verified NYC-metro place records.

    Expected lookup failures are returned in ``unresolved`` so the agent can ask
    only the affected traveler for clarification. Configuration and malformed
    tool arguments return a top-level ``error``.
    """
    try:
        validated_locations = _validated_locations(locations)
    except ValueError as error:
        return json.dumps({"error": str(error)})

    api_key = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
    if not api_key:
        return json.dumps(
            {
                "error": (
                    "GOOGLE_MAPS_API_KEY is not configured on the server. Enable "
                    "Places API (New) and set the environment variable."
                )
            }
        )

    resolved_locations: list[dict[str, Any]] = []
    unresolved: list[dict[str, str]] = []

    for location in validated_locations:
        traveler_id = location["traveler_id"]
        query = location["query"]
        place, lookup_error = _search_nyc_place(query, api_key)
        if lookup_error:
            unresolved.append(
                {"traveler_id": traveler_id, "query": query, "reason": lookup_error}
            )
            continue

        try:
            resolved_locations.append(_resolved_place(place, traveler_id, query))
        except ValueError as error:
            unresolved.append(
                {"traveler_id": traveler_id, "query": query, "reason": str(error)}
            )

    return json.dumps(
        {"resolved_locations": resolved_locations, "unresolved": unresolved}
    )
