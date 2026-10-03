import json
import os
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from tools import TOOLS, run_tool


MODEL = os.getenv("GEMINI_MODEL", "vertex_ai/gemini-3.5-flash-lite")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are CommonGround, an NYC group meeting-planning agent.
Your job is to make the trade-off between fairness, total travel time, and cafe
quality understandable. Preserve the people, origins, meeting date and time,
budget, rating preference, and preferred objective across follow-up turns. Ask
one concise question when required inputs are missing. Never invent locations,
coordinates, transit times, cafes, ratings, or prices.

For an origin-to-meeting-area request, use this order:
1. Call resolve_group_locations with every user-supplied origin. If any location
   is unresolved, ask only those travelers to clarify and stop the workflow.
2. Call generate_candidate_areas with the exact resolved traveler records.
3. Call get_transit_matrix with those origins, the generated candidates, and an
   RFC 3339 arrival_time equal to when the group wants to meet. It must include
   an explicit timezone offset. Never treat the meeting time as a departure time.
   Ask for a specific date or time when the request is ambiguous.
4. Pass the complete areas returned by get_transit_matrix unchanged to both
   score_fairest_option and score_fastest_option. Explain why the two objectives
   can select different winners and retain provider warnings and attribution.

If a tool returns an error, explain the actionable limitation instead of
continuing with invented data. Cafe search and cafe-quality scoring are owned by
another teammate and are not available on this branch yet.
"""


def run_agent(messages: list[dict]) -> tuple[str, list[dict]]:
    """Run Gemini until it answers without another tool request."""
    tool_calls: list[dict] = []

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

            tool_calls.append(
                {"name": call.function.name, "args": args, "result": result}
            )
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    return "Sorry, I hit my tool-call limit before finishing.", tool_calls


sessions: dict[str, list[dict]] = {}
app = FastAPI(title="CommonGround NYC")


class ChatRequest(BaseModel):
    message: str
    session_id: str | None = None


class ChatResponse(BaseModel):
    response: str
    session_id: str
    tool_calls: list[dict]


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "index.html")


@app.get("/health")
def health():
    return {"status": "ok", "model": MODEL}


@app.post("/chat", response_model=ChatResponse)
def chat(request: ChatRequest):
    session_id = request.session_id or str(uuid.uuid4())
    if session_id not in sessions:
        sessions[session_id] = [{"role": "system", "content": SYSTEM_PROMPT}]

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
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
    )
