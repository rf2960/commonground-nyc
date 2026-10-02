import json
import os
import uuid
from pathlib import Path

import litellm
import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tools import TOOLS, run_tool


MODEL = os.getenv("GEMINI_MODEL", "vertex_ai/gemini-3.5-flash-lite")
VERTEX_LOCATION = os.getenv("GOOGLE_CLOUD_LOCATION", "global")
MAX_TOOL_ROUNDS = 6

SYSTEM_PROMPT = """You are CommonGround, an NYC group meeting-planning agent.
Your job is to make the trade-off between fairness, total travel time, and cafe
quality understandable. Preserve the people, origins, meeting date and time,
budget, rating threshold, and preferred objective across follow-up turns. Ask
one concise question when a required input is missing. Never invent locations,
coordinates, transit times, cafes, opening status, ratings, prices, or reviews.

Available tools:
- score_fairest_option ranks candidate areas after commute-time arrays are known.
- search_cafes_in_areas searches real cafes after a maps/transit result or the
  user supplies trustworthy candidate-area coordinates and an ISO meeting time.
- score_best_cafe_option ranks the exact cafe records returned by cafe search.

When cafe search succeeds, pass its cafe records to score_best_cafe_option
without manufacturing missing fields. Clearly label regular weekly opening hours
as estimates and retain tool warnings. If a tool returns an error, explain the
actionable limitation and request only the information needed to recover.

Location resolution, candidate generation, transit matrices, and fastest scoring
are not integrated yet. Until those tools are available, do not pretend to solve
an end-to-end origin-to-cafe request. You may compare user-supplied commute data
or cafe records, and you may search cafes only from trustworthy supplied areas.
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
    message: str = Field(min_length=1, max_length=4000)
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

