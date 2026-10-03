import json

from app import SYSTEM_PROMPT
from tools import TOOLS, TOOL_MAP, run_tool


ANDREW_TOOLS = {
    "resolve_group_locations",
    "generate_candidate_areas",
    "get_transit_matrix",
    "score_fastest_option",
}


def tool_definitions():
    return {tool["function"]["name"]: tool["function"] for tool in TOOLS}


def test_andrew_tools_are_registered_once():
    names = [tool["function"]["name"] for tool in TOOLS]

    assert ANDREW_TOOLS.issubset(names)
    assert len(names) == len(set(names))
    assert ANDREW_TOOLS.issubset(TOOL_MAP)


def test_andrew_tool_schemas_are_descriptive_and_require_inputs():
    definitions = tool_definitions()

    for name in ANDREW_TOOLS:
        definition = definitions[name]
        assert len(definition["description"]) >= 80
        assert definition["parameters"]["type"] == "object"
        assert definition["parameters"]["required"]


def test_transit_tool_treats_meeting_time_as_arrival_time():
    definition = tool_definitions()["get_transit_matrix"]
    properties = definition["parameters"]["properties"]

    assert "arrival_time" in properties
    assert "departure_time" not in properties
    assert "arrival_time" in definition["parameters"]["required"]


def test_fastest_tool_dispatches_through_registry():
    scored = json.loads(
        run_tool(
            "score_fastest_option",
            {
                "options": [
                    {"area": "Union Square", "commute_minutes": [25, 30]},
                    {"area": "Herald Square", "commute_minutes": [20, 25]},
                ]
            },
        )
    )

    assert scored["selected_area"] == "Herald Square"


def test_registry_returns_model_readable_argument_error():
    error = json.loads(run_tool("score_fastest_option", {}))

    assert "Bad arguments for score_fastest_option" in error["error"]


def test_system_prompt_contains_tool_order_and_safety_rules():
    positions = [SYSTEM_PROMPT.index(name) for name in (
        "resolve_group_locations",
        "generate_candidate_areas",
        "get_transit_matrix",
        "score_fairest_option",
        "score_fastest_option",
    )]

    assert positions == sorted(positions)
    assert "Never invent" in SYSTEM_PROMPT
    assert "explicit timezone offset" in SYSTEM_PROMPT
    assert "Never treat the meeting time as a departure time" in SYSTEM_PROMPT
