import json
import math
import os
import unicodedata
from functools import lru_cache
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv


load_dotenv()

NOMINATIM_BASE_URL = os.getenv("NOMINATIM_BASE_URL", "https://nominatim.openstreetmap.org")
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT", "fiveFood/1.0")
NOMINATIM_TIMEOUT_SECONDS = float(os.getenv("NOMINATIM_TIMEOUT_SECONDS", "6"))
NOMINATIM_DEFAULT_COUNTRY = os.getenv("NOMINATIM_DEFAULT_COUNTRY", "vn")
TRACK_ASIA_BASE_URL = os.getenv("TRACK_ASIA_BASE_URL", "https://maps.track-asia.com/api/v2/place")
TRACK_ASIA_API_KEY = os.getenv("TRACK_ASIA_MAPS_API_KEY", "").strip()
TRACK_ASIA_TIMEOUT_SECONDS = float(os.getenv("TRACK_ASIA_TIMEOUT_SECONDS", "6"))
TRACK_ASIA_USE_NEW_ADMIN = os.getenv("TRACK_ASIA_USE_NEW_ADMIN", "true").lower() in {"1", "true", "yes", "on"}

AREA_ALIASES = {
    "hồ chí minh": ("hồ chí minh", "ho chi minh", "ho-chi-minh", "thành phố hồ chí minh", "tp hcm", "tphcm", "hcm"),
    "hà nội": ("hà nội", "ha noi", "hanoi", "thành phố hà nội", "tp ha noi", "tphn"),
    "đà nẵng": ("đà nẵng", "da nang", "danang", "thành phố đà nẵng", "tp da nang", "tpdn"),
    "cần thơ": ("cần thơ", "can tho", "cantho", "thành phố cần thơ", "tp can tho", "tpct"),
}

# Fallback coordinates for the seeded home data when Nominatim is unavailable.
SEED_LOCATION_FALLBACKS = {
    ("123 Nguyễn Văn Linh", "Quận 7"): (10.7379, 106.7219),
    ("45 Lê Văn Sỹ", "Quận 3"): (10.7864, 106.6719),
    ("241 Nguyễn Trãi", "Quận 1"): (10.7628, 106.6837),
    ("88 Cao Thắng", "Quận 3"): (10.7718, 106.6819),
    ("26 Lê Thị Riêng", "Quận 1"): (10.7675, 106.6707),
    ("Lotte Mart", "Quận 7"): (10.7425, 106.7363),
    ("Phan Xích Long", "Phú Nhuận"): (10.7992, 106.6838),
    ("Hồ Tùng Mậu", "Quận 1"): (10.7736, 106.7049),
    ("12 Hẻm 456", "Quận 7"): (10.7359, 106.7248),
    ("Lý Tự Trọng", "Quận 1"): (10.7728, 106.7050),
}


def _strip_accents(value):
    normalized = unicodedata.normalize("NFD", value or "")
    return "".join(char for char in normalized if unicodedata.category(char) != "Mn")


def normalize_text(value):
    return _strip_accents((value or "").strip()).casefold()


def _normalize_query_key(query, area=None):
    return normalize_text(" ".join(part for part in [query, area] if part))


def _build_url(base_url, path, params):
    return f"{base_url.rstrip('/')}/{path.lstrip('/')}?{urlencode(params)}"


@lru_cache(maxsize=256)
def _fetch_nominatim_json(url):
    request = Request(url, headers={"User-Agent": NOMINATIM_USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=NOMINATIM_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _request_nominatim(path, params):
    url = _build_url(NOMINATIM_BASE_URL, path, params)
    try:
        return _fetch_nominatim_json(url)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return []


@lru_cache(maxsize=256)
def _fetch_trackasia_json(url):
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=TRACK_ASIA_TIMEOUT_SECONDS) as response:
        payload = response.read().decode("utf-8")
    return json.loads(payload)


def _request_trackasia(path, params):
    if not TRACK_ASIA_API_KEY:
        return {}

    request_params = dict(params)
    request_params["key"] = TRACK_ASIA_API_KEY
    if TRACK_ASIA_USE_NEW_ADMIN:
        request_params["new_admin"] = "true"

    url = _build_url(TRACK_ASIA_BASE_URL, path, request_params)
    try:
        return _fetch_trackasia_json(url)
    except (HTTPError, URLError, TimeoutError, ValueError, json.JSONDecodeError):
        return {}


def _extract_trackasia_area_from_components(address_components):
    if not address_components:
        return ""

    level_1 = ""
    level_2 = ""
    for component in address_components:
        types = component.get("types") or []
        value = component.get("long_name") or component.get("short_name") or ""
        if not value:
            continue
        if "administrative_area_level_1" in types and not level_1:
            level_1 = value
        elif "administrative_area_level_2" in types and not level_2:
            level_2 = value

    return level_1 or level_2 or ""


def _trackasia_text_matches_area(text, selected_area):
    if not selected_area:
        return True
    normalized_text = normalize_text(text)
    if not normalized_text:
        return False
    return any(alias in normalized_text for alias in _area_aliases(selected_area))


def _trackasia_matches_area(prediction, detail_result, selected_area):
    if not selected_area:
        return True

    texts = [
        prediction.get("description", ""),
        prediction.get("formatted_address", ""),
        prediction.get("name", ""),
        detail_result.get("formatted_address", ""),
        detail_result.get("vicinity", ""),
        detail_result.get("name", ""),
        _extract_trackasia_area_from_components(detail_result.get("address_components") or []),
    ]

    texts.extend(
        component.get("long_name", "")
        for component in (detail_result.get("address_components") or [])
        if component.get("long_name")
    )
    texts.extend(
        component.get("short_name", "")
        for component in (detail_result.get("address_components") or [])
        if component.get("short_name")
    )

    return any(_trackasia_text_matches_area(text, selected_area) for text in texts)


def _normalize_trackasia_result(prediction, detail_result, query, selected_area=None):
    geometry = detail_result.get("geometry") or {}
    location = geometry.get("location") or {}
    lat = location.get("lat")
    lon = location.get("lng")
    if lat is None or lon is None:
        return None

    formatted_address = detail_result.get("formatted_address") or prediction.get("formatted_address") or prediction.get("description") or prediction.get("name") or query
    address_components = detail_result.get("address_components") or []
    types = detail_result.get("types") or prediction.get("types") or []

    return {
        "query": query,
        "place_id": prediction.get("place_id", ""),
        "reference": prediction.get("reference", ""),
        "name": prediction.get("name", ""),
        "description": prediction.get("description", ""),
        "display_name": formatted_address,
        "address": formatted_address,
        "formatted_address": formatted_address,
        "address_components": address_components,
        "lat": float(lat),
        "lon": float(lon),
        "area": _extract_trackasia_area_from_components(address_components) or selected_area or "",
        "type": types[0] if types else "",
        "types": types,
        "icon": prediction.get("icon") or detail_result.get("icon") or "",
        "structured_formatting": prediction.get("structured_formatting") or {},
        "source": "trackasia",
    }


def _trackasia_place_details(place_id):
    if not place_id:
        return {}

    payload = _request_trackasia(
        "details/json",
        {
            "place_id": place_id,
        },
    )
    if not payload or payload.get("status") != "OK":
        return {}
    return payload.get("result") or {}


def _search_trackasia_addresses(query, selected_area=None, limit=8):
    query = (query or "").strip()
    if not query or not TRACK_ASIA_API_KEY:
        return []

    search_input = query if not selected_area else f"{query}, {selected_area}"
    payload = _request_trackasia(
        "autocomplete/json",
        {
            "input": search_input,
            "size": max(1, min(int(limit or 8), 10)),
        },
    )
    if not payload or payload.get("status") != "OK":
        return []

    predictions = payload.get("predictions") or []
    normalized = []
    for prediction in predictions:
        if not isinstance(prediction, dict):
            continue

        place_id = prediction.get("place_id")
        detail_result = _trackasia_place_details(place_id)
        if not detail_result:
            continue

        if not _trackasia_matches_area(prediction, detail_result, selected_area):
            continue

        item = _normalize_trackasia_result(prediction, detail_result, query, selected_area=selected_area)
        if item:
            normalized.append(item)

    return normalized


def _search_nominatim_addresses(query, selected_area=None, limit=8):
    query = (query or "").strip()
    if not query:
        return []

    params = {
        "q": query if not selected_area else f"{query}, {selected_area}",
        "format": "jsonv2",
        "addressdetails": 1,
        "limit": max(1, min(int(limit or 8), 10)),
        "countrycodes": NOMINATIM_DEFAULT_COUNTRY,
        "accept-language": "vi",
    }
    results = _request_nominatim("search", params)
    if not results and selected_area:
        results = _request_nominatim(
            "search",
            {
                **params,
                "q": query,
            },
        )

    normalized = []
    for result in results:
        if not _matches_area(result, selected_area):
            continue
        item = _normalize_result(result, query, selected_area=selected_area, source="nominatim")
        if item:
            normalized.append(item)
    return normalized


def _area_aliases(area):
    normalized = normalize_text(area)
    aliases = [normalized]
    aliases.extend(AREA_ALIASES.get(normalized, ()))
    aliases.extend(
        {
            "ho chi minh": ("ho chi minh", "thanh pho ho chi minh", "tp hcm", "tphcm", "hcm"),
            "ha noi": ("ha noi", "thanh pho ha noi", "tp ha noi", "hanoi", "tphn"),
            "da nang": ("da nang", "thanh pho da nang", "tp da nang", "danang", "tpdn"),
            "can tho": ("can tho", "thanh pho can tho", "tp can tho", "cantho", "tpct"),
        }.get(normalized, ())
    )
    return [normalize_text(alias) for alias in aliases if alias]


def _extract_area(result):
    address = result.get("address") or {}
    for key in ("city", "town", "municipality", "county", "state_district", "state", "region"):
        value = address.get(key)
        if value:
            return value
    return ""


def _matches_area(result, selected_area):
    if not selected_area:
        return True

    normalized_selected = _area_aliases(selected_area)
    if not normalized_selected:
        return True

    haystacks = [
        normalize_text(result.get("display_name", "")),
        normalize_text(_extract_area(result)),
    ]
    address = result.get("address") or {}
    haystacks.extend(normalize_text(value) for value in address.values() if value)

    for haystack in haystacks:
        if not haystack:
            continue
        if any(alias in haystack for alias in normalized_selected):
            return True
    return False


def _normalize_result(result, query, selected_area=None, source="nominatim"):
    lat = result.get("lat")
    lon = result.get("lon")
    if lat is None or lon is None:
        return None

    area = _extract_area(result) or selected_area or ""
    return {
        "query": query,
        "display_name": result.get("display_name", query),
        "address_components": result.get("address") or {},
        "lat": float(lat),
        "lon": float(lon),
        "area": area,
        "type": result.get("type", ""),
        "source": source,
    }


def _seed_fallback(query, selected_area=None):
    key = (query.strip(), selected_area.strip() if selected_area else "")
    coords = SEED_LOCATION_FALLBACKS.get(key)
    if not coords:
        return None
    lat, lon = coords
    return {
        "query": query,
        "display_name": query.strip(),
        "lat": lat,
        "lon": lon,
        "area": selected_area or "",
        "type": "seed-fallback",
        "source": "seed-fallback",
    }


def search_addresses(query, selected_area=None, limit=8):
    query = (query or "").strip()
    if not query:
        return []

    results = _search_trackasia_addresses(query, selected_area=selected_area, limit=limit)
    if results:
        return results

    return _search_nominatim_addresses(query, selected_area=selected_area, limit=limit)


def resolve_address(query, selected_area=None, require_area_match=True, allow_seed_fallback=True):
    query = (query or "").strip()
    if not query:
        return None

    candidates = search_addresses(query, selected_area=selected_area, limit=5)
    if candidates:
        return candidates[0]

    if allow_seed_fallback:
        fallback = _seed_fallback(query, selected_area=selected_area)
        if fallback:
            return fallback

    if not require_area_match and selected_area:
        candidates = search_addresses(query, selected_area=None, limit=5)
        if candidates:
            return candidates[0]

    return None


def _matches_selected_area(text, selected_area):
    if not selected_area:
        return True
    normalized_text = normalize_text(text)
    return any(alias in normalized_text for alias in _area_aliases(selected_area))


def area_matches(text, selected_area):
    return _matches_selected_area(text, selected_area)


def resolve_address_for_area(address, selected_area, allow_seed_fallback=True):
    resolved = resolve_address(
        address,
        selected_area=selected_area,
        require_area_match=True,
        allow_seed_fallback=allow_seed_fallback,
    )
    if not resolved:
        return None
    return resolved


def format_distance_km(distance_km):
    if distance_km is None:
        return "Chưa xác định"
    if distance_km < 10:
        return f"{distance_km:.1f} km"
    return f"{distance_km:.0f} km"


def haversine_distance_km(lat1, lon1, lat2, lon2):
    if None in {lat1, lon1, lat2, lon2}:
        return None

    radius_km = 6371.0
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    delta_phi = math.radians(float(lat2) - float(lat1))
    delta_lambda = math.radians(float(lon2) - float(lon1))

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return radius_km * c


def location_sort_key(distance_km, restaurant_id):
    if distance_km is None:
        return (1, float("inf"), restaurant_id or 0)
    return (0, distance_km, restaurant_id or 0)
