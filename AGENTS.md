# Repository instructions for coding agents

- Keep `app.py`, `pyproject.toml`, `uv.lock`, `README.md`, and `submission.json` at the repository root; the grader expects them there.
- Never commit API keys, service-account JSON, `.env`, or generated credentials.
- Preserve the `/chat` response shape: `response`, `session_id`, and `tool_calls`, including each call's `name`, `args`, and `result`.
- Read `docs/TOOL_CONTRACTS.md` before changing tool arguments or result shapes.
- Put provider/API code behind small functions and return model-readable JSON errors at the tool boundary.
- Add or update tests for every scoring rule and edge case.
- Run `uv run pytest` before opening a pull request.
- Do not add reservations, payments, accounts, RAG, or multi-agent architecture to the MVP.

