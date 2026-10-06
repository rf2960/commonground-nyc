# CommonGround NYC

CommonGround is a group decision agent that uses transit time to expose the trade-off
between **fairness**, **speed**, and **cafe quality**. It is not just a midpoint or cafe
finder: the same group can receive three different recommendations depending on the
objective it values.

**[Try the deployed agent](https://commonground-nyc-1053619589756.us-east1.run.app)**

The product question is deliberately human rather than geometric: *who carries the
cost of getting everyone together?* CommonGround shows the fairest area, the fastest
area, and the strongest cafe option side by side, including how much travel time a
cafe-quality choice adds or saves.

## How to use it

1. Enter 2–6 origins plus a specific future date and meeting time.
2. Add a budget or minimum rating, then choose **Fairest**, **Fastest**, **Best cafe**,
   or compare all three.
3. Inspect the per-person commute impact, cafe evidence, caveats, and the complete
   tool-call trace. Use a follow-up message to move one traveler or change a constraint;
   **New meetup** starts a separate session.

## What is implemented

This repository is built from the course's `gemini-web-tool-calling` starter and
includes the complete tool chain:

- the Gemini tool-calling loop and session memory;
- the required `/chat` response shape with visible tool calls;
- Ruochen's tested `score_fairest_option` tool;
- Andrew's tested NYC-metro location resolver, candidate generator, Google
  door-to-door transit matrix with driving fallback, and `score_fastest_option`
  tool;
- Yulia's tested Google Places cafe search and `score_best_cafe_option` tool,
  including meeting-time regular-hours estimates;
- an integrated agent prompt that moves from origins to transit comparisons and
  then to cafe recommendations without inventing provider data;
- a decision UI that makes the three objectives and per-person commute burden visible;
- a Cloud Run-ready Dockerfile with continuous deployment from GitHub.

## Seven-tool workflow

| Stage | Tool | Team contribution |
| --- | --- | --- |
| Understand origins | `resolve_group_locations` | Andrew |
| Shortlist hubs | `generate_candidate_areas` | Andrew |
| Measure real travel | `get_transit_matrix` | Andrew; Google Routes external data |
| Protect the hardest trip | `score_fairest_option` | Ruochen's original objective tool |
| Minimize group travel | `score_fastest_option` | Andrew's original objective tool |
| Find real cafes | `search_cafes_in_areas` | Yulia; Google Places external data |
| Rank cafe evidence | `score_best_cafe_option` | Yulia's original objective tool |

The final recommendation is not delegated to unverified model arithmetic. The backend
builds an authoritative alignment across the three scoring outputs, while the model
explains the trade-off and preserves provider warnings.

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

## Sample grading queries

1. “Four of us are coming from Columbia University, Astoria, Bedford Ave, and Jay
   St-MetroTech. We want coffee on October 10, 2026 at 2:00 PM Eastern Time,
   moderate budget, rating at least 4.3. Compare the fairest and fastest areas,
   then recommend qualifying cafes.”
2. “Actually Bob is coming from Queensboro Plaza instead. Keep everyone else the
   same, preserve the date, time, and budget, and rerun the comparison.”
3. “Using the same group and time, compare the fairest meeting area with the
   fastest one. Explain the commute trade-off, then recommend the best qualifying
   cafe in the fairest area.”

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

## Operational notes

The public MVP keeps conversations isolated by `session_id`, expires inactive
process-local sessions after two hours, and bounds the number retained by each Cloud
Run instance. This is enough for the course interaction model but is not durable storage:
a production version should use a TTL-backed store such as Firestore if conversations
must survive instance restarts. Restrict the Google Maps key to Places API (New) and
Routes API, keep Cloud Run scaling and API quotas bounded, and configure billing alerts.


## Google Maps data setup

Set `GOOGLE_MAPS_API_KEY` in the server environment using a key restricted to
Places API (New) and Routes API. The project must have both APIs enabled and
working billing.
Never put the key in frontend JavaScript, tool arguments, git, or screenshots.
Location resolution uses Places Text Search (New) and accepts both exact places
and broad NYC-metro areas. Commute comparison uses a Routes API transit matrix;
Google transit durations can include walking links, buses, subways, trains, and
transfers. A traffic-aware driving estimate is used only when a transit pair is
unavailable and does not include rideshare pickup, parking, or drop-off time.
Cafe search uses Nearby Search (New). Cafe search requests rating, review count, price and
regular opening hours; requested fields affect billing.

Meeting-time opening is estimated from structured regular weekly hours in
`America/New_York`, including overnight hours and week wrap. Missing/incomplete
hours remain unknown. Holidays and last-minute changes are not verified, so
regular-hours recommendations remain provisional; check with the venue.
Explicit ISO offsets are converted to NYC; offset-free times mean NYC local time
and ambiguous/nonexistent DST times need an explicit offset. `tzdata` provides
NYC timezone rules on Windows as well as Linux. Preserve provider
links/attributions and opening estimate notes in result cards.
