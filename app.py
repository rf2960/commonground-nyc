import json
import os
import time
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from commonground.recommendations import (
    build_recommendation_plans,
    infer_preferred_objective,
)
from tools import TOOLS, run_tool


MODEL = os.getenv("GEMINI_MODEL", "vertex_ai/gemini-3.5-flash-lite")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
MAX_TOOL_ROUNDS = 8
SESSION_TTL_SECONDS = max(60, int(os.getenv("SESSION_TTL_SECONDS", "7200")))
MAX_SESSIONS = max(1, int(os.getenv("MAX_SESSIONS", "500")))

SYSTEM_PROMPT = """You are CommonGround, an NYC group meeting-planning agent.
Your job is to make the trade-off between fairness, total travel time, and cafe
quality understandable. Preserve the people, origins, meeting date and time,
budget, rating threshold, and preferred objective across follow-up turns. Ask
one concise question when a required input is missing. Never invent locations,
coordinates, transit times, cafes, opening status, ratings, prices, or reviews.

Treat a public-transit commute as a door-to-door route: it may include walking
to or from stops, walking between transfers, buses, subways, and trains. Users
may provide either a precise address or a broad NYC-metro area. Accept a broad
area as an estimate and state the formatted point used; do not repeatedly ask
for a station or exact address after Google Places has resolved it.

For a complete origin-to-cafe request, use this order:
1. Call resolve_group_locations with every user-supplied origin. If any location
   is unresolved, ask only those travelers to clarify and stop the workflow.
2. Call generate_candidate_areas with the exact resolved traveler records.
3. Call get_transit_matrix with those origins, the generated candidates, an RFC
   3339 arrival_time equal to when the group wants to meet, and
   include_driving=true unless the user rejects car/rideshare fallback. The time
   must include an explicit timezone offset. Never treat the meeting time as a transit departure time.
   Ask for a specific date or time only when ambiguous.
4. The matrix prefers transit and uses a driving estimate only where transit is
   unavailable. Prefer areas with the fewest drive_fallback_count values, then
   pass those areas' area and commute_minutes to
   score_fairest_option and score_fastest_option. Explain every drive_fallback,
   preserve the tool warnings, and explain why fairness and total travel time may
   select different winners. Never call driving an exact Uber ETA: pickup,
   parking, and drop-off time are not included.
5. If the user explicitly prioritizes Fairest or Fastest, include that winner
   area in cafe search and prefer the highest-ranked qualifying cafe inside it.
   If the user gives no priority, search enough scored areas to support three
   distinct outputs: Fairest plan, Fastest plan, and Best cafe plan. Do not turn
   those into one unlabeled "best overall" recommendation.
6. Call search_cafes_in_areas with the relevant candidate-area coordinates and
   the same meeting time, then pass its exact cafe records to
   score_best_cafe_option without manufacturing missing fields.

The backend may provide an authoritative RECOMMENDATION_ALIGNMENT block after
the scoring tools finish. Follow it exactly. If a cafe is outside a commute
winner area, state the extra total group commute and extra longest commute from
that block. Always retain transit-versus-driving fallback, partial results,
failed routes, warnings, and attribution in the explanation.

If the user asks only for cafes, resolve locations and generate areas, then skip
commute scoring and search those areas directly. If no complete commute area is
returned, do not ask the user to cycle through addresses, stations, times, and
dates. Continue once with cafe search over the original generated candidates,
state that commute ranking was unavailable, and offer one optional clarification
for the specifically unresolved traveler. Never suggest a travel mode the tool
does not support, and never retry the same failed route request more than once.

Retain provider warnings and attribution. Clearly label opening status derived
from regular weekly hours as an estimate. If a provider or configuration error
prevents every supported fallback, explain the actionable limitation and ask
only for information that can actually recover it.
"""


def run_agent(messages: list[dict]) -> tuple[str, list[dict]]:
    """Run Gemini until it answers without another tool request."""
    tool_calls: list[dict] = []
    tool_results: dict[str, dict] = {}
    alignment_injected = False

    for _ in range(MAX_TOOL_ROUNDS):
        reply = litellm.completion(
            model=MODEL,
            vertex_location=VERTEX_LOCATION,
            messages=messages,
            tools=TOOLS,
        ).choices[0].message

        messages.append(reply.model_dump())
        if not reply.tool_calls:
            return reply.content or "", tool_calls

        for call in reply.tool_calls:
            try:
                args = json.loads(call.function.arguments)
            except (TypeError, json.JSONDecodeError) as error:
                args = {}
                result = json.dumps({"error": f"Invalid tool arguments: {error}"})
            else:
                result = run_tool(call.function.name, args)

            try:
                parsed_result = json.loads(result)
            except (TypeError, json.JSONDecodeError):
                parsed_result = None
            if isinstance(parsed_result, dict) and "error" not in parsed_result:
                tool_results[call.function.name] = parsed_result

            tool_calls.append(
                {"name": call.function.name, "args": args, "result": result}
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

        required = {
            "score_fairest_option",
            "score_fastest_option",
            "score_best_cafe_option",
        }
        if not alignment_injected and required.issubset(tool_results):
            try:
                alignment = build_recommendation_plans(
                    tool_results["score_fairest_option"],
                    tool_results["score_fastest_option"],
                    tool_results["score_best_cafe_option"],
                    preferred_objective=infer_preferred_objective(messages),
                    transit=tool_results.get("get_transit_matrix"),
                )
            except (KeyError, TypeError, ValueError):
                alignment = None
            if alignment is not None:
                messages.append(
                    {
                        "role": "system",
                        "content": (
                            "RECOMMENDATION_ALIGNMENT (authoritative backend result):\n"
                            + json.dumps(alignment, ensure_ascii=False)
                        ),
                    }
                )
                alignment_injected = True

    return "Sorry, I hit my tool-call limit before finishing.", tool_calls


sessions: dict[str, list[dict]] = {}
session_last_seen: dict[str, float] = {}
app = FastAPI(title="CommonGround NYC")


def prune_sessions(now: float | None = None) -> None:
    """Bound process-local chat memory without changing the response contract."""
    current = time.monotonic() if now is None else now
    expired = [
        session_id
        for session_id in sessions
        if current - session_last_seen.get(session_id, 0) > SESSION_TTL_SECONDS
    ]
    for session_id in expired:
        sessions.pop(session_id, None)
        session_last_seen.pop(session_id, None)

    overflow = len(sessions) - MAX_SESSIONS
    if overflow > 0:
        oldest = sorted(sessions, key=lambda key: session_last_seen.get(key, 0))
        for session_id in oldest[:overflow]:
            sessions.pop(session_id, None)
            session_last_seen.pop(session_id, None)


def make_session_room() -> None:
    """Evict the least-recently-used session before accepting a new one."""
    if len(sessions) < MAX_SESSIONS:
        return
    oldest = min(sessions, key=lambda key: session_last_seen.get(key, 0))
    sessions.pop(oldest, None)
    session_last_seen.pop(oldest, None)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    session_id: str | None = Field(default=None, max_length=128)


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/health")
def health():
    prune_sessions()
    return {"status": "ok", "model": MODEL, "active_sessions": len(sessions)}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    now = time.monotonic()
    prune_sessions(now)
    session_id = request.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        make_session_room()
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]
    session_last_seen[session_id] = now

    sessions[session_id].append({"role": "user", "content": request.message})

    try:
        response, tool_calls = run_agent(sessions[session_id])
    except Exception as error:
        response = f"Model call failed: {type(error).__name__}: {str(error)[:300]}"
        tool_calls = []

    return ChatResponse(
        response=response,
        session_id=session_id,
        tool_calls=tool_calls,
    )


@app.post("/clear")
def clear(session_id: str | None = None):
    if session_id:
        sessions.pop(session_id, None)
        session_last_seen.pop(session_id, None)
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
