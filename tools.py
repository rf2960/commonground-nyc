"""Tool registry exposed to Gemini.

The first implemented original tool is Ruochen's fairness scorer. Teammates can
add their tool definitions and functions here after agreeing to the contracts in
docs/TOOL_CONTRACTS.md.
"""

import json
from collections.abc import Callable

from commonground import score_fairest_option
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


TOOLS.append({
    "type": "function",
    "function": {
        "name": "score_best_cafe_option",
        "description": "Rank known cafes by evidence-adjusted rating after enforcing rating, price, opening and optional station-distance constraints. Call after cafe search, never invent input data. Unknown opening hours produce provisional recommendations. Price levels are categories, not dollar amounts.",
        "parameters": {
            "type": "object",
            "properties": {
                "cafes": {"type": "array", "minItems": 1, "description": "Cafe records from search, with optional measured station distance.", "items": {
                    "type": "object", "properties": {
                        "name": {"type": "string", "description": "Real cafe name."},
                        "area": {"type": "string"}, "address": {"type": "string"},
                        "place_id": {"type": "string"},
                        "rating": {"type": ["number", "null"], "description": "Provider rating 0–5; null if unavailable."},
                        "review_count": {"type": ["integer", "null"], "description": "Nonnegative provider review count; null if unavailable."},
                        "price_level": {"type": ["integer", "null"], "description": "Normalized category 0–4; null if unavailable."},
                        "open_at_meeting_time": {"type": ["boolean", "null"], "description": "Whether open at the requested meeting time, not merely open now; null if unverified."},
                        "station_distance_meters": {"type": ["number", "null"], "description": "Known distance to the relevant station; omit or null if unavailable."},
                    }, "required": ["name"]}},
                "min_rating": {"type": "number", "default": 0, "description": "Minimum raw provider rating, 0–5."},
                "price_levels": {"type": "array", "items": {"type": "integer"}, "description": "Allowed categories 0–4; omit to disable price filtering. Unknown prices do not pass an active filter."},
                "require_open": {"type": "boolean", "default": True, "description": "Exclude known closed cafes; unknown opening status remains provisional."},
                "max_station_distance_meters": {"type": "number", "description": "Optional hard distance limit. Unknown distances do not pass this filter."},
            }, "required": ["cafes"],
        },
    },
})

TOOLS.append({
    "type": "function", "function": {
        "name": "search_cafes_in_areas",
        "description": "Search real cafes within 800 meters of 1–4 NYC candidate hubs using Google Places. Call after maps tools provide coordinates. Returns quality, price, regular hours and provider links. Future opening status is unverified and null, except closed businesses; do not invent opening status or station distance. Credentials are server-side only.",
        "parameters": {"type": "object", "properties": {
            "areas": {"type": "array", "minItems": 1, "maxItems": 4,
                "description": "Candidate hubs from maps/transit results, not invented coordinates.",
                "items": {"type": "object", "properties": {
                    "area": {"type": "string"}, "lat": {"type": "number"}, "lng": {"type": "number"}
                }, "required": ["area", "lat", "lng"]}},
            "meeting_time": {"type": "string", "description": "Requested ISO date/time, e.g. 2026-10-03T14:00:00-04:00. Future opening verification remains pending in this version."},
            "min_rating": {"type": "number", "default": 0, "description": "Minimum provider rating 0–5; missing rating fails a positive threshold."},
            "price_levels": {"type": "array", "items": {"type": "integer"}, "description": "Optional allowed price categories 0–4; unknown price fails an active filter."}
        }, "required": ["areas", "meeting_time"]}
    }
})

TOOL_MAP: dict[str, Callable[..., str]] = {
    "score_fairest_option": score_fairest_option,
    "score_best_cafe_option": score_best_cafe_option,
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

