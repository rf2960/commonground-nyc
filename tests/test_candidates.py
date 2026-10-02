import json

import pytest

from commonground.candidates import generate_candidate_areas


EXAMPLE_ORIGINS = [
    {"traveler_id": "columbia", "lat": 40.8075, "lng": -73.9626},
    {"traveler_id": "astoria", "lat": 40.7644, "lng": -73.9235},
    {"traveler_id": "bedford", "lat": 40.7172, "lng": -73.9565},
    {"traveler_id": "jay", "lat": 40.6922, "lng": -73.9867},
]


def result(**kwargs):
    return json.loads(generate_candidate_areas(**kwargs))


def test_generates_deterministic_shortlist_for_demo_origins():
    generated = result(resolved_locations=EXAMPLE_ORIGINS)

    assert generated["candidate_areas"] == [
        {"area": "Bedford Ave", "lat": 40.7172, "lng": -73.9565},
        {"area": "Grand Central", "lat": 40.7527, "lng": -73.9772},
        {"area": "Court Square", "lat": 40.747, "lng": -73.9453},
        {"area": "Queensboro Plaza", "lat": 40.7506, "lng": -73.9402},
    ]
    assert "real transit times" in generated["strategy"].lower()


def test_respects_requested_candidate_count():
    generated = result(resolved_locations=EXAMPLE_ORIGINS, max_candidates=6)

    assert len(generated["candidate_areas"]) == 6
    assert len({area["area"] for area in generated["candidate_areas"]}) == 6


def test_input_order_does_not_change_candidates():
    forward = result(resolved_locations=EXAMPLE_ORIGINS)
    reversed_order = result(resolved_locations=list(reversed(EXAMPLE_ORIGINS)))

    assert forward["candidate_areas"] == reversed_order["candidate_areas"]


def test_brooklyn_origins_produce_brooklyn_candidates():
    generated = result(
        resolved_locations=[
            {"traveler_id": "alice", "lat": 40.6845, "lng": -73.9775},
            {"traveler_id": "bob", "lat": 40.6922, "lng": -73.9867},
        ],
        max_candidates=3,
    )

    names = {area["area"] for area in generated["candidate_areas"]}
    assert {"Atlantic Terminal", "Jay St-MetroTech"}.issubset(names)


@pytest.mark.parametrize(
    ("resolved_locations", "expected_error"),
    [
        ([], "resolved_locations must contain at least 2 travelers"),
        (None, "resolved_locations must contain at least 2 travelers"),
        (
            [{"traveler_id": "alice", "lat": 40.7, "lng": -73.9}],
            "resolved_locations must contain at least 2 travelers",
        ),
        (
            [
                {"traveler_id": str(index), "lat": 40.7, "lng": -73.9}
                for index in range(7)
            ],
            "resolved_locations supports at most 6 travelers",
        ),
        (
            ["Astoria", {"traveler_id": "bob", "lat": 40.7, "lng": -73.9}],
            "resolved location 1 must be an object",
        ),
        (
            [
                {"traveler_id": "", "lat": 40.7, "lng": -73.9},
                {"traveler_id": "bob", "lat": 40.7, "lng": -73.9},
            ],
            "resolved location 1 is missing traveler_id",
        ),
        (
            [
                {"traveler_id": "alice", "lat": "40.7", "lng": -73.9},
                {"traveler_id": "bob", "lat": 40.7, "lng": -73.9},
            ],
            "alice: lat and lng must be finite numeric values",
        ),
        (
            [
                {"traveler_id": "alice", "lat": 34.0522, "lng": -118.2437},
                {"traveler_id": "bob", "lat": 40.7, "lng": -73.9},
            ],
            "alice: coordinates must be within New York City",
        ),
    ],
)
def test_invalid_origins_return_model_readable_errors(
    resolved_locations, expected_error
):
    assert result(resolved_locations=resolved_locations) == {"error": expected_error}


def test_rejects_duplicate_traveler_ids_case_insensitively():
    generated = result(
        resolved_locations=[
            {"traveler_id": "Alice", "lat": 40.7, "lng": -73.9},
            {"traveler_id": "alice", "lat": 40.8, "lng": -73.95},
        ]
    )

    assert generated == {"error": "duplicate traveler_id: alice"}


@pytest.mark.parametrize(
    ("max_candidates", "expected_error"),
    [
        (True, "max_candidates must be an integer"),
        (2.5, "max_candidates must be an integer"),
        (0, "max_candidates must be between 1 and 6"),
        (7, "max_candidates must be between 1 and 6"),
    ],
)
def test_invalid_candidate_count_returns_model_readable_error(
    max_candidates, expected_error
):
    assert result(
        resolved_locations=EXAMPLE_ORIGINS,
        max_candidates=max_candidates,
    ) == {"error": expected_error}
