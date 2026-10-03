import json
from unittest.mock import Mock

import pytest
import requests

from commonground.locations import (
    NYC_VIEWPORT,
    PLACES_FIELD_MASK,
    PLACES_TEXT_SEARCH_URL,
    REQUEST_TIMEOUT_SECONDS,
    resolve_group_locations,
)


def result(locations):
    return json.loads(resolve_group_locations(locations))


def places_response(payload, status_code=200):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    return response


@pytest.fixture(autouse=True)
def maps_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-server-key")


def test_resolves_location_and_sends_restricted_places_request(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return places_response(
            {
                "places": [
                    {
                        "id": "columbia-place-id",
                        "displayName": {"text": "Columbia University"},
                        "formattedAddress": "116th and Broadway, New York, NY",
                        "location": {"latitude": 40.8075, "longitude": -73.9626},
                    }
                ]
            }
        )

    monkeypatch.setattr("commonground.locations.requests.post", fake_post)
    resolved = result(
        [{"traveler_id": "alice", "query": "Columbia University"}]
    )

    assert resolved == {
        "resolved_locations": [
            {
                "traveler_id": "alice",
                "input_location": "Columbia University",
                "formatted_address": "116th and Broadway, New York, NY",
                "lat": 40.8075,
                "lng": -73.9626,
                "place_id": "columbia-place-id",
            }
        ],
        "unresolved": [],
    }
    assert captured["url"] == PLACES_TEXT_SEARCH_URL
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": "test-server-key",
        "X-Goog-FieldMask": PLACES_FIELD_MASK,
    }
    assert captured["json"] == {
        "textQuery": "Columbia University",
        "languageCode": "en",
        "regionCode": "US",
        "pageSize": 1,
        "locationRestriction": {"rectangle": NYC_VIEWPORT},
    }
    assert "test-server-key" not in json.dumps(resolved)


def test_preserves_successes_and_reports_unresolved_locations(monkeypatch):
    responses = iter(
        [
            places_response(
                {
                    "places": [
                        {
                            "id": "astoria-id",
                            "formattedAddress": "Astoria, Queens, NY",
                            "location": {
                                "latitude": 40.7644,
                                "longitude": -73.9235,
                            },
                        }
                    ]
                }
            ),
            places_response({"places": []}),
        ]
    )
    monkeypatch.setattr(
        "commonground.locations.requests.post", lambda *args, **kwargs: next(responses)
    )

    resolved = result(
        [
            {"traveler_id": "alice", "query": "Astoria"},
            {"traveler_id": "bob", "query": "not a real NYC place"},
        ]
    )

    assert [item["traveler_id"] for item in resolved["resolved_locations"]] == [
        "alice"
    ]
    assert resolved["unresolved"] == [
        {
            "traveler_id": "bob",
            "query": "not a real NYC place",
            "reason": "No matching place was found within New York City",
        }
    ]


def test_uses_display_name_when_formatted_address_is_missing(monkeypatch):
    monkeypatch.setattr(
        "commonground.locations.requests.post",
        lambda *args, **kwargs: places_response(
            {
                "places": [
                    {
                        "id": "neighborhood-id",
                        "displayName": {"text": "Astoria, Queens, NY"},
                        "location": {"latitude": 40.7644, "longitude": -73.9235},
                    }
                ]
            }
        ),
    )

    resolved = result([{"traveler_id": "alice", "query": "Astoria"}])
    assert (
        resolved["resolved_locations"][0]["formatted_address"]
        == "Astoria, Queens, NY"
    )


def test_reports_provider_http_error_without_crashing(monkeypatch):
    monkeypatch.setattr(
        "commonground.locations.requests.post",
        lambda *args, **kwargs: places_response(
            {"error": {"message": "Places API (New) is not enabled"}},
            status_code=403,
        ),
    )

    resolved = result([{"traveler_id": "alice", "query": "Astoria"}])
    assert resolved["unresolved"][0]["reason"] == (
        "Google Places returned HTTP 403: Places API (New) is not enabled"
    )


def test_reports_timeout_without_crashing(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("provider timed out")

    monkeypatch.setattr("commonground.locations.requests.post", timeout)
    resolved = result([{"traveler_id": "alice", "query": "Astoria"}])

    assert resolved["unresolved"][0]["reason"] == (
        "Google Places timed out; try again"
    )


def test_reports_invalid_provider_data_as_unresolved(monkeypatch):
    monkeypatch.setattr(
        "commonground.locations.requests.post",
        lambda *args, **kwargs: places_response(
            {
                "places": [
                    {
                        "id": "outside-id",
                        "formattedAddress": "Los Angeles, CA",
                        "location": {"latitude": 34.0522, "longitude": -118.2437},
                    }
                ]
            }
        ),
    )

    resolved = result([{"traveler_id": "alice", "query": "Los Angeles"}])
    assert resolved["resolved_locations"] == []
    assert resolved["unresolved"][0]["reason"] == (
        "Google Places result is outside New York City"
    )


def test_missing_api_key_returns_actionable_configuration_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")

    resolved = result([{"traveler_id": "alice", "query": "Astoria"}])

    assert resolved == {
        "error": (
            "GOOGLE_MAPS_API_KEY is not configured on the server. Enable Places "
            "API (New) and set the environment variable."
        )
    }


@pytest.mark.parametrize(
    ("locations", "expected_error"),
    [
        ([], "locations must be a non-empty list"),
        (None, "locations must be a non-empty list"),
        (["Astoria"], "location 1 must be an object"),
        ([{"traveler_id": "", "query": "Astoria"}], "location 1 is missing traveler_id"),
        ([{"traveler_id": "alice", "query": ""}], "location 1 is missing query"),
        (
            [{"traveler_id": str(index), "query": "Astoria"} for index in range(7)],
            "locations supports at most 6 travelers",
        ),
    ],
)
def test_invalid_tool_arguments_return_model_readable_errors(
    locations, expected_error
):
    assert result(locations) == {"error": expected_error}


def test_rejects_duplicate_traveler_ids_case_insensitively():
    resolved = result(
        [
            {"traveler_id": "Alice", "query": "Astoria"},
            {"traveler_id": "alice", "query": "Columbia University"},
        ]
    )

    assert resolved == {"error": "duplicate traveler_id: alice"}
