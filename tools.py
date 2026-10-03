"""Tool registry exposed to Gemini."""

import json
from collections.abc import Callable

from commonground import (
    generate_candidate_areas,
    get_transit_matrix,
    resolve_group_locations,
    score_fairest_option,
    score_fastest_option,
)
from commonground.cafes import score_best_cafe_option
from commonground.places import search_cafes_in_areas


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "score_fairest_option",
            "description": (
                "Rank candidate NYC meeting areas by fairness. Prefer fewer travelers "
                "over the hard commute limit, then the smallest worst commute, commute "
                "spread, and average commute. Call this only after commute times are known."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "options": {
                        "type": "array",
                        "description": "Candidate areas and one transit time per traveler.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "area": {
                                    "type": "string",
                                    "description": "Readable candidate area name.",
                                },
                                "commute_minutes": {
                                    "type": "array",
                                    "description": "Transit minutes for every traveler.",
                                    "items": {"type": "number"},
                                    "minItems": 1,
                                },
                            },
                            "required": ["area", "commute_minutes"],
                        },
                        "minItems": 1,
                    },
                    "hard_limit_minutes": {
                        "type": "number",
                        "description": "Commute limit above which a traveler is heavily penalized.",
                        "default": 60,
                    },
                },
                "required": ["options"],
            },
        },
    },
]


TOOLS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "resolve_group_locations",
                "description": (
                    "Resolve 1-6 unverified NYC location queries to real Google "
                    "Places records. Call this before generating candidate areas when "
                    "the user supplies addresses, landmarks, neighborhoods, "
                    "intersections, or subway stations. Never invent coordinates. If "
                    "any item is unresolved, ask only those travelers to clarify."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "locations": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 6,
                            "description": "One location query per traveler.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "traveler_id": {
                                        "type": "string",
                                        "description": (
                                            "Stable traveler name or identifier used "
                                            "throughout the conversation."
                                        ),
                                    },
                                    "query": {
                                        "type": "string",
                                        "description": (
                                            "The traveler's NYC origin exactly as "
                                            "provided or clarified by the user."
                                        ),
                                    },
                                },
                                "required": ["traveler_id", "query"],
                            },
                        }
                    },
                    "required": ["locations"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "generate_candidate_areas",
                "description": (
                    "Generate a small deterministic shortlist of NYC transit hubs from "
                    "resolved traveler coordinates. Call only with records returned by "
                    "resolve_group_locations. This is a geographic shortlist, not a "
                    "final recommendation; always obtain real transit times next."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "resolved_locations": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 6,
                            "description": (
                                "Verified NYC traveler locations returned by the "
                                "location resolver."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "traveler_id": {"type": "string"},
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["traveler_id", "lat", "lng"],
                            },
                        },
                        "max_candidates": {
                            "type": "integer",
                            "minimum": 1,
                            "maximum": 6,
                            "default": 4,
                            "description": "Number of transit hubs to shortlist.",
                        },
                    },
                    "required": ["resolved_locations"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "get_transit_matrix",
                "description": (
                    "Compute real Google Routes public-transit times from every "
                    "traveler to every candidate area. Call after candidate generation "
                    "and use the requested meeting time as an RFC 3339 arrival time "
                    "including a timezone offset. Never treat the meeting time as a "
                    "departure time. Candidates missing any traveler route are excluded. "
                    "Pass the returned complete areas unchanged to the scoring tools."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "origins": {
                            "type": "array",
                            "minItems": 2,
                            "maxItems": 6,
                            "description": "Verified traveler coordinates.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "traveler_id": {"type": "string"},
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["traveler_id", "lat", "lng"],
                            },
                        },
                        "candidate_areas": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 6,
                            "description": (
                                "Transit hubs returned by generate_candidate_areas."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "area": {"type": "string"},
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["area", "lat", "lng"],
                            },
                        },
                        "arrival_time": {
                            "type": "string",
                            "description": (
                                "The time everyone should arrive for the meeting, in "
                                "RFC 3339 format with an explicit offset, for example "
                                "2026-10-03T14:00:00-04:00."
                            ),
                        },
                    },
                    "required": ["origins", "candidate_areas", "arrival_time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "score_fastest_option",
                "description": (
                    "Rank candidate meeting areas by the lowest total group transit "
                    "time, breaking ties by the lowest longest individual commute. Call "
                    "only with complete commute-time arrays returned by "
                    "get_transit_matrix."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "options": {
                            "type": "array",
                            "minItems": 1,
                            "description": (
                                "Candidate areas with one transit time per traveler. "
                                "Every array must contain the same number of travelers."
                            ),
                            "items": {
                                "type": "object",
                                "properties": {
                                    "area": {
                                        "type": "string",
                                        "description": "Readable candidate area name.",
                                    },
                                    "commute_minutes": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {"type": "number"},
                                        "description": (
                                            "Transit minutes in the traveler order "
                                            "returned by get_transit_matrix."
                                        ),
                                    },
                                },
                                "required": ["area", "commute_minutes"],
                            },
                        }
                    },
                    "required": ["options"],
                },
            },
        },
    ]
)

TOOLS.extend(
    [
        {
            "type": "function",
            "function": {
                "name": "search_cafes_in_areas",
                "description": (
                    "Search real cafes within 800 meters of 1-4 verified NYC candidate "
                    "hubs using Google Places. Call after transit tools provide area "
                    "coordinates. Returns ratings, price categories, provider links, and "
                    "meeting-time opening estimates from regular weekly hours. Preserve "
                    "all warnings and never invent station distance or missing metadata."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "areas": {
                            "type": "array",
                            "minItems": 1,
                            "maxItems": 4,
                            "items": {
                                "type": "object",
                                "properties": {
                                    "area": {"type": "string"},
                                    "lat": {"type": "number"},
                                    "lng": {"type": "number"},
                                },
                                "required": ["area", "lat", "lng"],
                            },
                        },
                        "meeting_time": {
                            "type": "string",
                            "description": (
                                "Requested ISO date and time. Use the same explicit "
                                "timezone offset supplied to the transit tool."
                            ),
                        },
                        "min_rating": {
                            "type": "number",
                            "default": 0,
                            "description": "Minimum provider rating from 0 to 5.",
                        },
                        "price_levels": {
                            "type": "array",
                            "items": {"type": "integer"},
                            "description": "Optional allowed price categories 0-4.",
                        },
                    },
                    "required": ["areas", "meeting_time"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "score_best_cafe_option",
                "description": (
                    "Rank the exact cafe records returned by cafe search using an "
                    "evidence-adjusted rating after applying rating, price, opening, "
                    "and optional station-distance constraints. Unknown or estimated "
                    "metadata remains visible and recommendations may be provisional."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "cafes": {
                            "type": "array",
                            "minItems": 1,
                            "description": "Cafe records returned by search_cafes_in_areas.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "name": {"type": "string"},
                                    "area": {"type": "string"},
                                    "address": {"type": "string"},
                                    "place_id": {"type": "string"},
                                    "rating": {"type": ["number", "null"]},
                                    "review_count": {"type": ["integer", "null"]},
                                    "price_level": {"type": ["integer", "null"]},
                                    "opening_status_source": {"type": "string"},
                                    "opening_status_note": {"type": "string"},
                                    "open_at_meeting_time": {
                                        "type": ["boolean", "null"]
                                    },
                                    "station_distance_meters": {
                                        "type": ["number", "null"]
                                    },
                                },
                                "required": ["name"],
                            },
                        },
                        "min_rating": {"type": "number", "default": 0},
                        "price_levels": {
                            "type": "array",
                            "items": {"type": "integer"},
                        },
                        "require_open": {"type": "boolean", "default": True},
                        "max_station_distance_meters": {"type": "number"},
                    },
                    "required": ["cafes"],
                },
            },
        },
    ]
)


TOOL_MAP: dict[str, Callable[..., str]] = {
    "generate_candidate_areas": generate_candidate_areas,
    "get_transit_matrix": get_transit_matrix,
    "resolve_group_locations": resolve_group_locations,
    "score_best_cafe_option": score_best_cafe_option,
    "score_fairest_option": score_fairest_option,
    "score_fastest_option": score_fastest_option,
    "search_cafes_in_areas": search_cafes_in_areas,
}


def run_tool(name: str, args: dict) -> str:
    """Run one model-requested tool without letting bad calls crash the agent."""
    if name not in TOOL_MAP:
        return json.dumps({"error": f"Unknown tool '{name}'. Available: {list(TOOL_MAP)}"})
    try:
        return TOOL_MAP[name](**args)
    except TypeError as error:
        return json.dumps({"error": f"Bad arguments for {name}: {error}"})
    except Exception as error:  # Last-resort tool boundary; details remain visible.
        return json.dumps({"error": f"{name} failed: {type(error).__name__}: {error}"})
