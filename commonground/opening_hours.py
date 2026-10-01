"""Evaluate Google's typical weekly schedule, without promising future availability."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

NYC = ZoneInfo("America/New_York")
WEEK_SECONDS = 7 * 24 * 60 * 60


def parse_meeting_time(value: str) -> datetime:
    """Explicit offsets are converted to NYC; offset-free times mean NYC local time."""
    if not isinstance(value, str) or "T" not in value:
        raise ValueError("meeting_time must be an ISO date/time, e.g. 2026-10-03T14:00:00-04:00.")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        return parsed.astimezone(NYC)
    # An offset-free time at the DST switch can be ambiguous or nonexistent.
    candidates = []
    for fold in (0, 1):
        aware = parsed.replace(tzinfo=NYC, fold=fold)
        roundtrip = aware.astimezone(timezone.utc).astimezone(NYC)
        if roundtrip.replace(tzinfo=None) == parsed:
            candidates.append(aware)
    if not candidates or len({c.utcoffset() for c in candidates}) > 1:
        raise ValueError("NYC meeting_time is ambiguous or nonexistent at the daylight-saving change. Supply a valid time with an explicit UTC offset.")
    return candidates[0]


def _point_seconds(point: dict) -> int:
    if not isinstance(point, dict) or not point or point.get("truncated") or "date" in point:
        raise ValueError("Not a complete weekly schedule point")
    # Zero scalar values can be omitted in provider JSON.
    values = [point.get(key, 0) for key in ("day", "hour", "minute")]
    for value, limit in zip(values, (6, 23, 59)):
        if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= limit:
            raise ValueError("Invalid weekly schedule point")
    day, hour, minute = values
    return ((day * 24 + hour) * 60 + minute) * 60


def opening_status(place: dict, meeting: datetime) -> dict:
    """Return true/false for regular hours, null for missing/malformed data.

    Intervals include the opening instant and exclude the closing instant.
    Overnight intervals and Saturday-to-Sunday wrap are supported.
    Regular hours are an estimate: holidays and last-minute changes may differ.
    """
    if place.get("businessStatus") in ("CLOSED_TEMPORARILY", "CLOSED_PERMANENTLY"):
        return {"open_at_meeting_time": False, "opening_status_source": "business closure",
                "opening_status_note": "Provider reports this business temporarily or permanently closed."}
    unknown = {"open_at_meeting_time": None, "opening_status_source": "unavailable",
               "opening_status_note": "Meeting-time hours unavailable or incomplete; check before going."}
    hours = place.get("regularOpeningHours")
    if not isinstance(hours, dict) or not isinstance(hours.get("periods"), list):
        return unknown
    local = meeting.astimezone(NYC)
    target = (((local.weekday() + 1) % 7 * 24 + local.hour) * 60 + local.minute) * 60 + local.second + local.microsecond / 1_000_000
    intervals = []
    try:
        for period in hours["periods"]:
            if not isinstance(period, dict):
                return unknown
            start = _point_seconds(period.get("open"))
            if "close" not in period:
                if len(hours["periods"]) == 1 and start == 0:
                    intervals.append((0, WEEK_SECONDS))  # Documented 24/7 representation.
                    continue
                return unknown
            end = _point_seconds(period["close"])
            if end == start:
                return unknown
            if end < start:
                end += WEEK_SECONDS
            intervals.append((start, end))
    except ValueError:
        return unknown
    opened = any(start <= target < end or start <= target + WEEK_SECONDS < end
                 for start, end in intervals)
    return {"open_at_meeting_time": opened, "opening_status_source": "regular_schedule",
            "opening_status_note": "Expected " + ("open" if opened else "closed") + " according to regular weekly hours in America/New_York. Holiday hours and last-minute changes are unverified; check before going."}
