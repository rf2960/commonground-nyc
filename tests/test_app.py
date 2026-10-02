import json
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import app as webapp


class FakeReply:
    def __init__(self, content=None, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls or []

    def model_dump(self):
        dumped = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            dumped["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in self.tool_calls
            ]
        return dumped


def completion(reply):
    return SimpleNamespace(choices=[SimpleNamespace(message=reply)])


def tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name=name, arguments=json.dumps(arguments)),
    )


def test_agent_runs_tool_then_returns_answer(monkeypatch):
    replies = iter(
        [
            completion(
                FakeReply(
                    tool_calls=[
                        tool_call(
                            "score_fairest_option",
                            {
                                "options": [
                                    {
                                        "area": "Union Square",
                                        "commute_minutes": [24, 27, 29, 31],
                                    },
                                    {
                                        "area": "Herald Square",
                                        "commute_minutes": [15, 20, 22, 42],
                                    },
                                ]
                            },
                        )
                    ]
                )
            ),
            completion(FakeReply(content="Union Square is the fairest option.")),
        ]
    )
    observed_messages = []

    def fake_completion(**kwargs):
        observed_messages.append(list(kwargs["messages"]))
        return next(replies)

    monkeypatch.setattr(webapp.litellm, "completion", fake_completion)
    messages = [
        {"role": "system", "content": webapp.SYSTEM_PROMPT},
        {"role": "user", "content": "Which supplied option is fairest?"},
    ]

    answer, calls = webapp.run_agent(messages)

    assert answer == "Union Square is the fairest option."
    assert calls[0]["name"] == "score_fairest_option"
    assert json.loads(calls[0]["result"])["selected_area"] == "Union Square"
    assert any(message["role"] == "tool" for message in observed_messages[1])


def test_bad_tool_arguments_are_visible_to_model(monkeypatch):
    bad_call = SimpleNamespace(
        id="bad-call",
        function=SimpleNamespace(
            name="score_fairest_option", arguments="not valid json"
        ),
    )
    replies = iter(
        [
            completion(FakeReply(tool_calls=[bad_call])),
            completion(FakeReply(content="Please provide valid commute data.")),
        ]
    )
    monkeypatch.setattr(webapp.litellm, "completion", lambda **_: next(replies))

    answer, calls = webapp.run_agent(
        [{"role": "user", "content": "Compare these options"}]
    )

    assert answer == "Please provide valid commute data."
    assert "Invalid tool arguments" in json.loads(calls[0]["result"])["error"]


def test_chat_remembers_one_session_and_separates_another(monkeypatch):
    webapp.sessions.clear()
    snapshots = []

    def fake_agent(messages):
        snapshots.append([dict(message) for message in messages])
        messages.append({"role": "assistant", "content": "remembered"})
        return "remembered", []

    monkeypatch.setattr(webapp, "run_agent", fake_agent)
    first = webapp.chat(webapp.ChatRequest(message="Alice starts at Columbia"))
    webapp.chat(
        webapp.ChatRequest(
            message="Move Alice to Queensboro Plaza", session_id=first.session_id
        )
    )
    webapp.chat(webapp.ChatRequest(message="A separate group"))

    assert any(
        message.get("content") == "Alice starts at Columbia"
        for message in snapshots[1]
    )
    assert not any(
        message.get("content") == "Alice starts at Columbia"
        for message in snapshots[2]
    )


def test_chat_contains_model_failure_in_response(monkeypatch):
    webapp.sessions.clear()

    def fail(_messages):
        raise RuntimeError("fixture failure")

    monkeypatch.setattr(webapp, "run_agent", fail)
    response = webapp.chat(webapp.ChatRequest(message="hello"))

    assert response.tool_calls == []
    assert "Model call failed: RuntimeError" in response.response


def test_clear_removes_only_requested_session():
    webapp.sessions.clear()
    webapp.sessions.update({"one": [], "two": []})

    assert webapp.clear("one") == {"status": "ok"}
    assert "one" not in webapp.sessions
    assert "two" in webapp.sessions


@pytest.mark.parametrize("message", ["", "x" * 4001])
def test_message_length_validation(message):
    with pytest.raises(ValidationError):
        webapp.ChatRequest(message=message)

