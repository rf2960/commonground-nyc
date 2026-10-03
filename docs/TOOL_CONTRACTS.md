# Tool contracts

Agree on these shapes before implementing APIs. Keeping contracts stable lets each
person develop and test with fixtures on a separate branch.

## Shared data shapes

```json
{
  "traveler_id": "alice",
  "input_location": "Columbia University",
  "formatted_address": "116th and Broadway, New York, NY",
  "lat": 40.8075,
  "lng": -73.9626,
  "place_id": "provider-specific-id"
}
```

```json
{
  "area": "Union Square",
  "lat": 40.7359,
  "lng": -73.9911,
  "commute_minutes": [24, 27, 29, 31]
}
```

## External-data tools

### `resolve_group_locations` — Andrew

- Input: `locations: [{traveler_id, query}]`
- Output: `{resolved_locations: [{traveler_id, input_location, formatted_address, lat, lng, place_id}], unresolved: []}`
- Responsibility: resolve NYC addresses, landmarks, intersections, and subway stations.

### `generate_candidate_areas` — Andrew

- Input: `resolved_locations: [{traveler_id, lat, lng}]`, optional `max_candidates=4`.
- Output: `{candidate_areas: [{area, lat, lng}], strategy}`.
- Responsibility: create a deterministic shortlist of NYC transit hubs using geographic
  heuristics. This shortlist never replaces real transit-time ranking.

### `get_transit_matrix` — Andrew

- Input: `origins`, `candidate_areas`, `arrival_time` (the requested meeting time)
- Output: `{areas: [{area, lat, lng, commute_minutes}], traveler_ids, provider, arrival_time, excluded_areas, unavailable_routes, attribution}`
- Responsibility: one transit duration per traveler per candidate; exclude candidates
  missing any traveler route, preserve traveler order, and calculate routes that arrive
  by the meeting time rather than depart at the meeting time.

### `search_cafes_in_areas` — Yulia

- Input: `areas`, `meeting_time`, optional `min_rating`, optional `price_levels`
- Output: `{cafes: [{name, area, address, rating, review_count, price_level, open_at_meeting_time, lat, lng, place_id}]}`
- Responsibility: real cafe data with enough metadata for transparent ranking.

## Original decision tools

### `score_fairest_option` — Ruochen (implemented)

- Input: `options: [{area, commute_minutes}]`, optional `hard_limit_minutes=60`
- Ranking: fewer hard-limit violations, lowest maximum commute, smallest spread, lowest average.
- Output: selected area, explanation, and full metrics/ranking.

### `score_fastest_option` — Andrew

- Input: `options: [{area, commute_minutes}]`
- Ranking: lowest total commute, then lowest maximum commute.
- Output: selected area, explanation, and full metrics/ranking.

### `score_best_cafe_option` — Yulia

- Input: cafes plus the group's rating, price, open-time, and station-distance preferences.
- Ranking: explainable quality score; do not use an opaque model-generated number.
- Output: selected cafe, factor breakdown, explanation, and ranked alternatives.

## Integration rule

Every tool returns a JSON string. Expected API or validation failures are encoded as
`{"error": "..."}` so Gemini can recover instead of crashing the `/chat` endpoint.
