# CommonGround NYC

CommonGround is a group decision agent that uses transit time to expose the trade-off
between **fairness**, **speed**, and **cafe quality**. It is not just a midpoint or cafe
finder: the same group can receive three different recommendations depending on the
objective it values.

## Current milestone

This repository is the shared Phase 1 scaffold built from the course's
`gemini-web-tool-calling` starter. It already includes:

- the Gemini tool-calling loop and session memory;
- the required `/chat` response shape with visible tool calls;
- Ruochen's tested `score_fairest_option` tool;
- Yulia's tested `score_best_cafe_option` tool (quality scoring; external search available; meeting-time regular-hours estimates included);
- agreed contracts for the maps/transit and cafe work;
- a Cloud Run-ready Dockerfile.

The transit and fastest tools are still team work in progress. This
README does not claim the initial scaffold already satisfies the final rubric.

## Setup

Prerequisites: `uv`, a billed GCP project, the Agent Platform/Vertex AI API, and
Application Default Credentials.

```bash
gcloud auth application-default login
gcloud config set project YOUR_PROJECT_ID
uv sync
uv run pytest
uv run app.py
```

Open <http://localhost:8000>. Copy `.env.example` to `.env` only for local values;
never commit `.env` or credentials.

## Try the implemented fairness tool

> Compare Union Square with commutes of 24, 27, 29, and 31 minutes against Herald
> Square with commutes of 15, 20, 22, and 42 minutes. Which option is fairest?

The final integrated agent should also handle these grading/demo queries:

1. “Four of us are coming from Columbia University, Astoria, Bedford Ave, and Jay
   St-MetroTech. We want coffee Saturday at 2pm, moderate budget, rating at least
   4.3. Give us a few good choices.”
2. “Actually Bob is coming from Queensboro Plaza instead. Keep everyone else the
   same and rerun it.”
3. “We care most about fairness.” / “Just make it fastest.” / “Commute is fine —
   give us the best cafe.”

## Team workflow

Read [CONTRIBUTING.md](CONTRIBUTING.md) and
[docs/TOOL_CONTRACTS.md](docs/TOOL_CONTRACTS.md) before coding. Each teammate should
work on a focused branch and merge through pull requests so Codex sessions do not
overwrite one another's work.

## Required final checks

- At least three well-described tools and one original tool per team member.
- At least one tool calls real external data.
- Sessions remain separate and follow-up turns remember prior details.
- Tool name, arguments, and result are visible in the UI.
- `submission.json` contains every Columbia UNI/email and the deployed Cloud Run URL.
- The public Cloud Run URL works without grader setup and remains live until grades.


## Cafe search setup

Set `GOOGLE_MAPS_API_KEY` in the server environment using a key restricted to
Places API (New). The project must have that API enabled and working billing.
Never put the key in frontend JavaScript, tool arguments, git, or screenshots.
Search uses Nearby Search (New) and requests rating, review count, price and
regular opening hours; requested fields affect billing.

Meeting-time opening is estimated from structured regular weekly hours in
`America/New_York`, including overnight hours and week wrap. Missing/incomplete
hours remain unknown. Holidays and last-minute changes are not verified, so
regular-hours recommendations remain provisional; check with the venue.
Explicit ISO offsets are converted to NYC; offset-free times mean NYC local time
and ambiguous/nonexistent DST times need an explicit offset. `tzdata` provides
NYC timezone rules on Windows as well as Linux. Preserve provider
links/attributions and opening estimate notes in result cards.
