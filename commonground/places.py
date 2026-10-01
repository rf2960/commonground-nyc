"""Google Places cafe discovery. Credentials stay in the server environment."""
from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any

import requests

from .cafes import _number

URL = 'https://places.googleapis.com/v1/places:searchNearby'
FIELDS = ','.join('places.' + field for field in (
    'id', 'displayName', 'formattedAddress', 'location', 'rating',
    'userRatingCount', 'priceLevel', 'regularOpeningHours', 'businessStatus',
    'googleMapsUri', 'attributions',
))
PRICES = {'PRICE_LEVEL_FREE': 0, 'PRICE_LEVEL_INEXPENSIVE': 1,
          'PRICE_LEVEL_MODERATE': 2, 'PRICE_LEVEL_EXPENSIVE': 3,
          'PRICE_LEVEL_VERY_EXPENSIVE': 4}


def _request_area(area: dict, key: str) -> list[dict]:
    response = requests.post(URL, headers={
        'X-Goog-Api-Key': key, 'X-Goog-FieldMask': FIELDS,
        'Content-Type': 'application/json',
    }, json={
        'includedPrimaryTypes': ['cafe', 'coffee_shop'], 'maxResultCount': 10,
        'locationRestriction': {'circle': {
            'center': {'latitude': area['lat'], 'longitude': area['lng']},
            'radius': 800.0,
        }},
    }, timeout=15)
    # Do not expose provider response text, request headers or credentials in errors.
    if response.status_code >= 400:
        actions = {400: 'Check area coordinates and requested fields.',
                   401: 'Check the server API key.',
                   403: 'Check Places API (New), key restrictions, and project billing.',
                   429: 'Quota reached; wait or check the project quota.'}
        raise ValueError(f"Google Places HTTP {response.status_code}. " +
                         actions.get(response.status_code, 'Provider unavailable; try again later.'))
    data = response.json()
    if not isinstance(data, dict) or not isinstance(data.get('places', []), list):
        raise ValueError('Google Places returned an unexpected response. Retry later.')
    return data.get('places', [])


def search_cafes_in_areas(
    areas: list[dict[str, Any]], meeting_time: str,
    min_rating: float = 0, price_levels: list[int] | None = None,
) -> str:
    """Search up to four NYC candidate hubs with one request per area.

    This first version returns regular opening hours but leaves future opening
    status unknown rather than substituting open-now or fabricating an answer.
    Coordinates come from the maps tool, never inferred by the model.
    """
    try:
        if not isinstance(areas, list) or not 1 <= len(areas) <= 4:
            raise ValueError('areas must contain 1–4 candidate areas with area, lat, lng.')
        validated = []
        for item in areas:
            if not isinstance(item, dict) or not isinstance(item.get('area'), str) or not item['area'].strip():
                raise ValueError('Each area needs a non-empty area name.')
            lat = _number(item.get('lat'), 'lat', -90, 90)
            lng = _number(item.get('lng'), 'lng', -180, 180)
            if not (40.45 <= lat <= 40.95 and -74.3 <= lng <= -73.65):
                raise ValueError('Candidate center is outside the supported NYC bounding box.')
            validated.append({'area': item['area'].strip(), 'lat': lat, 'lng': lng})
        if not isinstance(meeting_time, str) or 'T' not in meeting_time:
            raise ValueError('meeting_time must be an ISO date/time, e.g. 2026-10-03T14:00:00-04:00.')
        datetime.fromisoformat(meeting_time.replace('Z', '+00:00'))
        minimum = _number(min_rating, 'min_rating', 0, 5)
        if price_levels is not None and (not isinstance(price_levels, list) or not price_levels or any(
            isinstance(p, bool) or not isinstance(p, int) or p not in range(5) for p in price_levels
        )):
            raise ValueError('price_levels must be a non-empty list of integers 0–4, or omitted.')
        key = os.environ.get('GOOGLE_MAPS_API_KEY', '').strip()
        if not key:
            raise ValueError('Set GOOGLE_MAPS_API_KEY in the server environment, then retry. Do not provide it as a tool argument.')
        cafes, errors, seen = [], [], set()
        for area in validated:
            try:
                places = _request_area(area, key)
                for p in places:
                    if not isinstance(p, dict):
                        raise ValueError('Google Places returned a malformed place record.')
                    place_id = p.get('id')
                    if not place_id or place_id in seen:
                        continue
                    rating = p.get('rating')
                    price = PRICES.get(p.get('priceLevel'))
                    if minimum > 0 and (rating is None or rating < minimum):
                        continue
                    if price_levels is not None and price not in price_levels:
                        continue
                    loc = p.get('location') or {}
                    name = (p.get('displayName') or {}).get('text')
                    if not name or loc.get('latitude') is None or loc.get('longitude') is None:
                        continue
                    seen.add(place_id)
                    closed = p.get('businessStatus') in ('CLOSED_TEMPORARILY', 'CLOSED_PERMANENTLY')
                    cafes.append({
                        'name': name, 'area': area['area'], 'address': p.get('formattedAddress'),
                        'rating': rating, 'review_count': p.get('userRatingCount'), 'price_level': price,
                        'open_at_meeting_time': False if closed else None,
                        'lat': loc['latitude'], 'lng': loc['longitude'], 'place_id': place_id,
                        'regular_opening_hours': p.get('regularOpeningHours'),
                        'google_maps_url': p.get('googleMapsUri'), 'attributions': p.get('attributions', []),
                        'opening_status_source': 'business closure' if closed else 'not yet verified for meeting time',
                    })
            except (requests.RequestException, ValueError, TypeError) as error:
                message = str(error) if isinstance(error, ValueError) else 'Places request timed out, failed, or returned malformed data. Retry later.'
                errors.append({'area': area['area'], 'error': message})
        result = {'cafes': cafes, 'provider': 'Google Places (New)', 'meeting_time': meeting_time,
                  'area_errors': errors, 'partial': bool(cafes and errors),
                  'warnings': ['Future opening status is unverified in this version; regular hours are returned for inspection. Station distances are not computed.'],
                  'message': 'Cafe candidates found.' if cafes else 'No matching cafes returned. Inspect area_errors or ask whether to relax rating/price filters.'}
        if errors and len(errors) == len(validated):
            result['error'] = 'All area searches failed; inspect area_errors for recovery steps.'
        return json.dumps(result, allow_nan=False)
    except (ValueError, TypeError) as error:
        return json.dumps({'error': str(error), 'action': 'Correct the input or server configuration and retry.'})
