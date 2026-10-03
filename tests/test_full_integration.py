import json
from types import SimpleNamespace

import app as webapp
from tools import TOOLS, TOOL_MAP


EXPECTED_TOOLS = {
    "resolve_group_locations",
    "generate_candidate_areas",
    "get_transit_matrix",
    "score_fairest_option",
    "score_fastest_option",
    "search_cafes_in_areas",
    "score_best_cafe_option",
}


class FakeReply:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self):
        return {"role": "assistant", "content": self.content}


def _completion(reply):
    return SimpleNamespace(choices=[SimpleNamespace(message=reply)])


def _call(name, call_id):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps({})),
    )


def test_all_team_tools_are_registered_once():
    names = [tool["function"]["name"] for tool in TOOLS]

    assert set(names) == EXPECTED_TOOLS
    assert len(names) == len(set(names))
    assert set(TOOL_MAP) == EXPECTED_TOOLS


def test_agent_can_finish_complete_origin_to_cafe_workflow(monkeypatch):
    replies = iter(
        [
            _completion(FakeReply(tool_calls=[_call("resolve_group_locations", "1")])),
            _completion(FakeReply(tool_calls=[_call("generate_candidate_areas", "2")])),
            _completion(FakeReply(tool_calls=[_call("get_transit_matrix", "3")])),
            _completion(
                FakeReply(
                    tool_calls=[
                        _call("score_fairest_option", "4a"),
                        _call("score_fastest_option", "4b"),
                    ]
                )
            ),
            _completion(FakeReply(tool_calls=[_call("search_cafes_in_areas", "5")])),
            _completion(FakeReply(tool_calls=[_call("score_best_cafe_option", "6")])),
            _completion(FakeReply(content="Integrated recommendation.")),
        ]
    )
    monkeypatch.setattr(webapp.litellm, "completion", lambda **_: next(replies))
    monkeypatch.setattr(webapp, "run_tool", lambda name, args: json.dumps({"tool": name}))

    answer, calls = webapp.run_agent([{"role": "user", "content": "Plan our meetup"}])

    assert answer == "Integrated recommendation."
    assert [call["name"] for call in calls] == [
        "resolve_group_locations",
        "generate_candidate_areas",
        "get_transit_matrix",
        "score_fairest_option",
        "score_fastest_option",
        "search_cafes_in_areas",
        "score_best_cafe_option",
    ]
