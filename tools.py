"""Tool registry exposed to Gemini.

The first implemented original tool is Ruochen's fairness scorer. Teammates can
add their tool definitions and functions here after agreeing to the contracts in
docs/TOOL_CONTRACTS.md.
"""

import json
from collections.abc import Callable

from commonground import score_fairest_option


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


TOOL_MAP: dict[str, Callable[..., str]] = {
    "score_fairest_option": score_fairest_option,
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

