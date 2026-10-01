"""One real request: run from the project root with uv run try_cafe_search.py."""
import json
from commonground.places import search_cafes_in_areas
from commonground.cafes import score_best_cafe_option

result = json.loads(search_cafes_in_areas(
    areas=[{"area": "Union Square", "lat": 40.7359, "lng": -73.9911}],
    meeting_time="2026-10-03T14:00:00-04:00",
    min_rating=4.0,
))
if result.get("error"):
    print(json.dumps(result, indent=2, ensure_ascii=False))
else:
    print("Real cafe candidates:")
    for cafe in result["cafes"]:
        print(cafe["name"], "rating:", cafe["rating"], "reviews:", cafe["review_count"], "price:", cafe["price_level"], "open at meeting:", cafe["open_at_meeting_time"] )
        print("  Hours:", cafe["opening_status_note"])
    if result["cafes"]:
        scored = json.loads(score_best_cafe_option(result["cafes"]))
        winner = scored.get("selected_cafe")
        print("Recommended:", winner["name"] if winner else "None")
        print(scored.get("explanation", scored.get("error")))
    for warning in result["warnings"]:
        print("Note:", warning)
