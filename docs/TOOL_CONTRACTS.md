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

### `get_transit_matrix` — Andrew

- Input: `origins`, `candidate_areas`, `departure_time`
- Output: `{areas: [{area, lat, lng, commute_minutes}], provider, departure_time}`
- Responsibility: one transit duration per traveler per candidate; return errors explicitly.

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

### `score_best_cafe_option` — Yulia (implemented)

- Input: `cafes`, optional `min_rating=0`, `price_levels=null`, `require_open=true`, `max_station_distance_meters=null`.
- Cafe fields: existing cafe-search fields plus optional `station_distance_meters`. Unknown metadata uses null; prices normalize to integer categories 0–4.
- Constraints: reject missing/below-threshold ratings; an active price or station-distance filter rejects unknown values. Known closed cafes are excluded when `require_open=true`; unknown hours remain provisional and require confirmation.
- Quality: `(review_count * rating + 50 * 4.0) / (review_count + 50)`. Constants are a documented design heuristic, not a measured population average. Missing review count uses zero evidence with a warning.
- Tie breakers: shortest known station distance, most reviews, name, place ID. No numeric station penalty is added to rating.
- Output: `{selected_cafe, objective, scoring_rule, explanation, ranking, excluded}`. Each ranked record includes cafe, factor_breakdown, warnings, provisional, rank. No matches returns null selected_cafe and actionable explanation without relaxing constraints.
- A provider's `open_now` is not sufficient to establish `open_at_meeting_time` for a future meeting. Do not invent opening data or station distances.

## Integration rule

Every tool returns a JSON string. Expected API or validation failures are encoded as
`{"error": "..."}` so Gemini can recover instead of crashing the `/chat` endpoint.

