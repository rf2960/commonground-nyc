import json
from unittest.mock import Mock

import pytest
import requests

from commonground.transit import (
    REQUEST_TIMEOUT_SECONDS,
    ROUTE_MATRIX_FIELD_MASK,
    ROUTE_MATRIX_URL,
    get_transit_matrix,
)


ORIGINS = [
    {"traveler_id": "alice", "lat": 40.8075, "lng": -73.9626},
    {"traveler_id": "bob", "lat": 40.7644, "lng": -73.9235},
]

CANDIDATE_AREAS = [
    {"area": "Union Square", "lat": 40.7359, "lng": -73.9911},
    {"area": "Herald Square", "lat": 40.7496, "lng": -73.9879},
]


def result(**kwargs):
    return json.loads(get_transit_matrix(**kwargs))


def routes_response(payload, status_code=200):
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.json.return_value = payload
    return response


@pytest.fixture(autouse=True)
def maps_api_key(monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "test-server-key")


def test_builds_transit_request_and_restores_matrix_order(monkeypatch):
    captured = {}

    def fake_post(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return routes_response(
            [
                {
                    "originIndex": 1,
                    "destinationIndex": 1,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "duration": "1320s",
                },
                {
                    "condition": "ROUTE_EXISTS",
                    "duration": "1800s",
                },
                {
                    "originIndex": 1,
                    "status": {},
                    "condition": "ROUTE_EXISTS",
                    "duration": "1500s",
                },
                {
                    "destinationIndex": 1,
                    "condition": "ROUTE_EXISTS",
                    "duration": "1200s",
                },
            ]
        )

    monkeypatch.setattr("commonground.transit.requests.post", fake_post)
    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T14:00:00-04:00",
    )

    assert matrix["areas"] == [
        {
            "area": "Union Square",
            "lat": 40.7359,
            "lng": -73.9911,
            "commute_minutes": [30.0, 25.0],
        },
        {
            "area": "Herald Square",
            "lat": 40.7496,
            "lng": -73.9879,
            "commute_minutes": [20.0, 22.0],
        },
    ]
    assert matrix["traveler_ids"] == ["alice", "bob"]
    assert matrix["departure_time"] == "2026-10-03T18:00:00Z"
    assert matrix["excluded_areas"] == []
    assert matrix["unavailable_routes"] == []
    assert matrix["attribution"].startswith("Powered by Google, ©")

    assert captured["url"] == ROUTE_MATRIX_URL
    assert captured["timeout"] == REQUEST_TIMEOUT_SECONDS
    assert captured["headers"] == {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": "test-server-key",
        "X-Goog-FieldMask": ROUTE_MATRIX_FIELD_MASK,
    }
    assert captured["json"]["travelMode"] == "TRANSIT"
    assert captured["json"]["departureTime"] == "2026-10-03T18:00:00Z"
    assert len(captured["json"]["origins"]) == 2
    assert len(captured["json"]["destinations"]) == 2
    assert "test-server-key" not in json.dumps(matrix)


def test_excludes_area_with_any_unavailable_route(monkeypatch):
    monkeypatch.setattr(
        "commonground.transit.requests.post",
        lambda *args, **kwargs: routes_response(
            [
                {"condition": "ROUTE_EXISTS", "duration": "1200s"},
                {
                    "destinationIndex": 1,
                    "condition": "ROUTE_EXISTS",
                    "duration": "1260s",
                },
                {
                    "originIndex": 1,
                    "condition": "ROUTE_NOT_FOUND",
                },
                {
                    "originIndex": 1,
                    "destinationIndex": 1,
                    "condition": "ROUTE_EXISTS",
                    "duration": "1320s",
                },
            ]
        ),
    )

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )

    assert [area["area"] for area in matrix["areas"]] == ["Herald Square"]
    assert matrix["excluded_areas"] == ["Union Square"]
    assert matrix["unavailable_routes"] == [
        {
            "traveler_id": "bob",
            "area": "Union Square",
            "reason": "No transit route found (ROUTE_NOT_FOUND)",
        }
    ]


def test_missing_matrix_element_excludes_affected_area(monkeypatch):
    monkeypatch.setattr(
        "commonground.transit.requests.post",
        lambda *args, **kwargs: routes_response(
            [
                {"condition": "ROUTE_EXISTS", "duration": "1200s"},
                {
                    "destinationIndex": 1,
                    "condition": "ROUTE_EXISTS",
                    "duration": "1260s",
                },
                {
                    "originIndex": 1,
                    "destinationIndex": 1,
                    "condition": "ROUTE_EXISTS",
                    "duration": "1320s",
                },
            ]
        ),
    )

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )

    assert [area["area"] for area in matrix["areas"]] == ["Herald Square"]
    assert matrix["unavailable_routes"][0]["reason"] == (
        "Google Routes did not return this matrix element"
    )


def test_reports_error_when_no_area_is_complete(monkeypatch):
    monkeypatch.setattr(
        "commonground.transit.requests.post",
        lambda *args, **kwargs: routes_response(
            [
                {"condition": "ROUTE_NOT_FOUND"},
                {"destinationIndex": 1, "condition": "ROUTE_NOT_FOUND"},
                {"originIndex": 1, "condition": "ROUTE_NOT_FOUND"},
                {
                    "originIndex": 1,
                    "destinationIndex": 1,
                    "condition": "ROUTE_NOT_FOUND",
                },
            ]
        ),
    )

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )

    assert matrix["areas"] == []
    assert matrix["excluded_areas"] == ["Union Square", "Herald Square"]
    assert matrix["error"] == (
        "No candidate area has transit routes for every traveler"
    )


def test_reports_provider_http_error(monkeypatch):
    monkeypatch.setattr(
        "commonground.transit.requests.post",
        lambda *args, **kwargs: routes_response(
            {"error": {"message": "Routes API is not enabled"}},
            status_code=403,
        ),
    )

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )
    assert matrix == {
        "error": "Google Routes returned HTTP 403: Routes API is not enabled"
    }


def test_reports_timeout(monkeypatch):
    def timeout(*args, **kwargs):
        raise requests.Timeout("provider timed out")

    monkeypatch.setattr("commonground.transit.requests.post", timeout)
    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )
    assert matrix == {"error": "Google Routes timed out; try again"}


def test_missing_api_key_returns_actionable_error(monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY")

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )
    assert matrix == {
        "error": (
            "GOOGLE_MAPS_API_KEY is not configured on the server. Enable Routes "
            "API and set the environment variable."
        )
    }


@pytest.mark.parametrize(
    ("origins", "expected_error"),
    [
        ([], "origins must contain at least 2 travelers"),
        (None, "origins must contain at least 2 travelers"),
        ([ORIGINS[0]], "origins must contain at least 2 travelers"),
        (
            [
                {"traveler_id": str(index), "lat": 40.7, "lng": -73.9}
                for index in range(7)
            ],
            "origins supports at most 6 travelers",
        ),
    ],
)
def test_invalid_origin_collections_return_errors(origins, expected_error):
    assert result(
        origins=origins,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    ) == {"error": expected_error}


@pytest.mark.parametrize(
    ("departure_time", "expected_error"),
    [
        ("Saturday at 2pm", "departure_time must be an RFC 3339 timestamp"),
        ("2026-10-03T14:00:00", "departure_time must include a timezone offset"),
        (None, "departure_time must be an RFC 3339 timestamp"),
    ],
)
def test_invalid_departure_time_returns_error(departure_time, expected_error):
    assert result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time=departure_time,
    ) == {"error": expected_error}


def test_rejects_duplicate_ids_and_areas():
    duplicate_origins = [ORIGINS[0], {**ORIGINS[1], "traveler_id": "ALICE"}]
    duplicate_areas = [
        CANDIDATE_AREAS[0],
        {**CANDIDATE_AREAS[1], "area": "union square"},
    ]

    assert result(
        origins=duplicate_origins,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    ) == {"error": "duplicate traveler_id: ALICE"}
    assert result(
        origins=ORIGINS,
        candidate_areas=duplicate_areas,
        departure_time="2026-10-03T18:00:00Z",
    ) == {"error": "duplicate candidate area: union square"}


def test_rejects_duplicate_matrix_elements(monkeypatch):
    monkeypatch.setattr(
        "commonground.transit.requests.post",
        lambda *args, **kwargs: routes_response(
            [
                {"condition": "ROUTE_EXISTS", "duration": "1200s"},
                {"condition": "ROUTE_EXISTS", "duration": "1200s"},
            ]
        ),
    )

    matrix = result(
        origins=ORIGINS,
        candidate_areas=CANDIDATE_AREAS,
        departure_time="2026-10-03T18:00:00Z",
    )
    assert matrix == {"error": "Google Routes returned a duplicate matrix element"}
