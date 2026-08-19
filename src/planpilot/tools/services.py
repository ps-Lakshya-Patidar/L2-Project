"""Service implementations for the PlanPilot tools.

Calls external free APIs: Open-Meteo, Open Library, DuckDuckGo search, and OpenStreetMap.
Includes resilient fallback chains and cached responses without fabricated data.
"""

from __future__ import annotations

import html
import math
import re
import urllib.parse
from typing import Any
import httpx

from planpilot.utils.logger import logger
from planpilot.utils.resilience import (
    ResilientCache,
    execute_fallback_chain,
    global_cache,
    http_get_with_retry,
)
from planpilot.utils.validation import (
    validate_hotel_entry,
    validate_restaurant_match,
    validate_transportation,
)

# Backward-compatible cache alias for tests that clear _SERVICES_CACHE
_SERVICES_CACHE = global_cache._store
_CACHE_TTL_SECONDS = 600.0


def clear_services_cache() -> None:
    """Clear the in-memory service cache (primarily for tests)."""
    global_cache.clear()


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate Great Circle distance in kilometers between two GPS points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2.0) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2.0) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def validate_city_name(city: str) -> str:
    """Validate and sanitize city name.

    Removes special characters while preserving unicode letters and validates length.
    """
    cleaned = re.sub(r"[^\w\s\-\.\']", "", city.strip(), flags=re.UNICODE)
    if len(cleaned) < 2:
        raise ValueError("City name must be at least 2 characters long.")
    if len(cleaned) > 100:
        raise ValueError("City name exceeds maximum allowed length (100 characters).")
    return cleaned


# Geocoding results are stable — cache them for 24 hours to avoid repeated API calls
_GEO_CACHE: dict[str, tuple[float, float, str, str]] = {}


async def _geocode_city(city: str, client: httpx.AsyncClient) -> tuple[float, float, str, str] | None:
    """Geocode a city name to (lat, lon, name, country) using Open-Meteo API.

    Results are cached in-process for 24 hours — geocoding the same city
    repeatedly (e.g. once per tool call) wastes ~600 ms each time.
    """
    cache_key = city.lower().strip()
    if cache_key in _GEO_CACHE:
        return _GEO_CACHE[cache_key]

    safe_city = urllib.parse.quote(city)
    geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={safe_city}&count=1&language=en&format=json"
    try:
        logger.info(f"Geocoding city: '{city}'")
        geo_resp = await http_get_with_retry(client, geo_url, timeout=8.0, max_retries=2)
        if geo_resp.status_code == 200:
            geo_data = geo_resp.json()
            if geo_data.get("results"):
                res = geo_data["results"][0]
                lat = res["latitude"]
                lon = res["longitude"]
                name = res.get("name", city)
                country = res.get("country", "")
                logger.debug(f"Geocoding hit: '{city}' resolved to lat={lat}, lon={lon}.")
                _GEO_CACHE[cache_key] = (lat, lon, name, country)
                return lat, lon, name, country
        logger.warning(f"Geocoding miss: City '{city}' not found or status {geo_resp.status_code}.")
    except Exception as e:
        logger.warning(f"Geocoding exception for '{city}': {e}")
    return None


# ---------------------------------------------------------------------------
# 1. Weather Tool Implementation
# ---------------------------------------------------------------------------


async def get_weather_data(city: str) -> dict[str, Any]:
    """Fetch current weather for a city using Open-Meteo Geocoding and Forecast APIs.

    Fallback Chain: Open-Meteo -> Fresh Cache -> Stale Cache -> Error output.
    """
    try:
        city = validate_city_name(city)
    except ValueError as e:
        return {"error": str(e)}

    search_name = city.lower().strip()
    cache_key = f"weather:{search_name}"

    async def _fetch_open_meteo() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=10.0) as client:
            geo_res = await _geocode_city(city, client)
            if not geo_res:
                return {"_city_not_found": True, "error": f"City '{city}' not found."}

            lat, lon, name, country = geo_res

            logger.info(f"Fetching weather data for lat={lat}, lon={lon}")
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current_weather=true&hourly=precipitation_probability,rain"
                f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                f"&timezone=auto&temperature_unit=celsius&wind_speed_unit=kmh"
            )
            weather_resp = await http_get_with_retry(client, weather_url, timeout=8.0, max_retries=2)
            weather_data = weather_resp.json()

            current = weather_data.get("current_weather", {})
            temp = current.get("temperature")
            windspeed = current.get("windspeed")
            weathercode = current.get("weathercode")

            hourly = weather_data.get("hourly", {})
            hourly_times = hourly.get("time", [])
            hourly_rain = hourly.get("rain", [])
            hourly_prob = hourly.get("precipitation_probability", [])

            any_rain_expected = False
            rain_probability_max = 0
            rain_sum_mm = 0.0

            if hourly_rain and hourly_prob:
                current_time_str = current.get("time")
                start_idx = 0
                if current_time_str in hourly_times:
                    start_idx = hourly_times.index(current_time_str)

                next_12h_rain = hourly_rain[start_idx : start_idx + 12]
                next_12h_prob = hourly_prob[start_idx : start_idx + 12]

                if next_12h_prob:
                    rain_probability_max = max(next_12h_prob)
                    any_rain_expected = rain_probability_max > 30

                if next_12h_rain:
                    rain_sum_mm = round(sum(next_12h_rain), 1)

            daily = weather_data.get("daily", {})
            daily_forecast = []
            if daily.get("time"):
                daily_times = daily.get("time", [])
                daily_max = daily.get("temperature_2m_max", [])
                daily_min = daily.get("temperature_2m_min", [])
                daily_codes = daily.get("weathercode", [])
                daily_prob = daily.get("precipitation_probability_max", [])

                for i, date_str in enumerate(daily_times[:3]):
                    try:
                        import datetime
                        dt = datetime.date.fromisoformat(date_str)
                        day_name = dt.strftime("%A")
                    except Exception:
                        day_name = date_str

                    daily_forecast.append({
                        "day": day_name,
                        "date": date_str,
                        "temp_max_c": daily_max[i] if i < len(daily_max) else None,
                        "temp_min_c": daily_min[i] if i < len(daily_min) else None,
                        "weather_code": daily_codes[i] if i < len(daily_codes) else None,
                        "max_rain_probability_percent": daily_prob[i] if i < len(daily_prob) else None,
                    })

            return {
                "city": name,
                "country": country,
                "latitude": lat,
                "longitude": lon,
                "temperature_c": temp,
                "windspeed_kmh": windspeed,
                "weather_code": weathercode,
                "forecast_next_12h": {
                    "any_rain_expected": any_rain_expected,
                    "max_rain_probability_percent": rain_probability_max,
                    "total_expected_rain_mm": rain_sum_mm,
                },
                "daily_forecast_3_days": daily_forecast,
            }

    providers = [("Open-Meteo API", _fetch_open_meteo)]

    def _attach_stale_note(data: dict[str, Any]) -> dict[str, Any]:
        data_copy = dict(data)
        data_copy["note"] = "(Cached data - live weather update currently unavailable)"
        return data_copy

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, dict) and "temperature_c" in res,
        attach_stale_note=_attach_stale_note,
    )

    if result is not None:
        return result

    # Check if city was explicitly not found
    try:
        res = await _fetch_open_meteo()
        if res and res.get("_city_not_found"):
            return {"error": res["error"]}
    except Exception:
        pass

    return {"error": f"Weather data for city '{city}' is currently unavailable. Please try again later."}


# ---------------------------------------------------------------------------
# 2. Books Tool Implementation
# ---------------------------------------------------------------------------


async def search_books_data(query: str) -> list[dict[str, Any]]:
    """Search books using the Open Library API.

    Fallback Chain: Open Library -> Fresh Cache -> Stale Cache -> Notice output.
    """
    safe_query_name = query.lower().strip()
    cache_key = f"books:{safe_query_name}"

    async def _fetch_open_library() -> list[dict[str, Any]] | None:
        safe_query = urllib.parse.quote(query)
        url = (
            f"https://openlibrary.org/search.json?q={safe_query}&limit=5"
            "&fields=key,title,author_name,first_publish_year,number_of_pages_median"
        )
        logger.info(f"Searching books for query: '{query}' via Open Library")
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await http_get_with_retry(client, url, timeout=8.0, max_retries=2)
            data = resp.json()
            books = []
            for doc in data.get("docs", []):
                key = doc.get("key")
                info_url = f"https://openlibrary.org{key}" if key else "Unknown"
                books.append({
                    "title": doc.get("title", "Unknown Title"),
                    "author": doc.get("author_name", ["Unknown"])[0] if doc.get("author_name") else "Unknown",
                    "first_publish_year": doc.get("first_publish_year"),
                    "number_of_pages_median": doc.get("number_of_pages_median"),
                    "info_url": info_url,
                })
            return books if books else []

    providers = [("Open Library API", _fetch_open_library)]

    def _attach_stale_note(data: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return data  # preserve original items

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, list),
        attach_stale_note=_attach_stale_note,
    )

    if result is not None and len(result) > 0:
        return result

    return [{"source": "Notice", "summary": f"No book results found for '{query}'"}]


# ---------------------------------------------------------------------------
# 3. Events Tool Implementation
# ---------------------------------------------------------------------------


async def discover_events_data(city: str, query: str | None = None) -> list[dict[str, Any]]:
    """Search for live events happening in a specific location using SerpAPI or DuckDuckGo.

    Fallback Chain: SerpAPI -> DuckDuckGo -> Fresh Cache -> Stale Cache -> Notice output.
    """
    try:
        city = validate_city_name(city)
    except ValueError as e:
        return [{"source": "Notice", "summary": str(e)}]

    from planpilot.utils.config import get_settings
    settings = get_settings()

    search_query = f"{query} in {city} this weekend" if query else f"events in {city} this weekend"
    cache_key = f"events:{city.lower().strip()}:{search_query.lower().strip()}"

    async def _fetch_serpapi() -> list[dict[str, Any]] | None:
        if not settings.serpapi_api_key or not settings.serpapi_api_key.strip():
            return None

        api_key = settings.serpapi_api_key.strip()
        safe_q = urllib.parse.quote(search_query)
        safe_loc = urllib.parse.quote(city)
        url = f"https://serpapi.com/search.json?q={safe_q}&location={safe_loc}&api_key={api_key}"

        logger.info(f"Searching events for '{search_query}' via SerpAPI")
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await http_get_with_retry(client, url, timeout=8.0, max_retries=1)
            data = resp.json()
            events_list = data.get("events_results", []) or data.get("organic_results", [])
            results = []
            for ev in events_list[:5]:
                title = ev.get("title", "Event Option")
                date_str = ev.get("date", "")
                address = ev.get("address", [])
                venue = address[0] if address else ""
                snippet = ev.get("snippet", "")
                link = ev.get("link", "")

                parts = [p for p in [venue, date_str, snippet] if p]
                summary_str = " | ".join(parts) if parts else "Event details"
                if link:
                    summary_str += f" Info/Tickets: {link}"

                results.append({"source": title, "summary": summary_str})
            return results if results else None

    async def _fetch_duckduckgo() -> list[dict[str, Any]] | None:
        logger.info(f"Searching events for '{search_query}' via DuckDuckGo")
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/120.0.0.0"
            )
        }
        safe_search_query = urllib.parse.quote(search_query)
        url = f"https://html.duckduckgo.com/html/?q={safe_search_query}"

        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await http_get_with_retry(client, url, headers=headers, timeout=8.0, max_retries=1)
            blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
            results = []
            for block in blocks[1:6]:
                title_match = re.search(r'<a class="result__(?:a|url)"[^>]*>(.*?)</a>', block, re.DOTALL)
                snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

                if title_match and snippet_match:
                    raw_title = html.unescape(re.sub(r"<[^>]*>", "", title_match.group(1)).strip())
                    snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip())
                    clean_title = re.sub(
                        r"\s*[\|-]\s*(?:Tripadvisor|Zomato|Yelp|Wikipedia|BookMyShow|AllEvents).*",
                        "",
                        raw_title,
                        flags=re.IGNORECASE,
                    ).strip()
                    results.append({"source": clean_title[:80], "summary": snippet})
            return results if results else None

    providers = [
        ("SerpAPI", _fetch_serpapi),
        ("DuckDuckGo", _fetch_duckduckgo),
    ]

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, list) and len(res) > 0,
    )

    if result is not None and len(result) > 0:
        return result

    return [{"source": "Notice", "summary": f"No events retrieved for {city}."}]


# ---------------------------------------------------------------------------
# 4. Hotels Tool Implementation
# ---------------------------------------------------------------------------


async def find_budget_hotels_data(city: str, budget: str = "low") -> list[dict[str, Any]]:
    """Suggest budget-friendly hotels and accommodations for a city.

    Fallback Chain: OpenStreetMap Overpass API -> DuckDuckGo Search -> Fresh Cache -> Stale Cache -> Notice output.
    Fabricated hotels and fake ratings are strictly prohibited.
    """
    try:
        city = validate_city_name(city)
    except ValueError as e:
        return [{"error": str(e)}]

    budget_tier = budget.lower().strip()
    cache_key = f"hotels:{city.lower().strip()}:{budget_tier}"

    async def _fetch_openstreetmap_hotels() -> list[dict[str, Any]] | None:
        logger.info(f"Querying OpenStreetMap Overpass API for hotels in '{city}'")
        async with httpx.AsyncClient(timeout=8.0) as client:
            geo_res = await _geocode_city(city, client)
            if not geo_res:
                return None

            lat, lon, _, _ = geo_res
            op_url = "https://overpass-api.de/api/interpreter"
            headers = {"User-Agent": "PlanPilotApp/1.0 (contact@planpilot.ai)"}
            op_ql = f'[out:json][timeout:15];node["tourism"~"hotel|hostel|guest_house"](around:8000, {lat}, {lon});out tags 10;'

            resp = await http_get_with_retry(client, op_url, headers=headers, params={"data": op_ql}, timeout=20.0, max_retries=2)
            elements = resp.json().get("elements", [])
            osm_results = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name")
                if name:
                    tourism_type = tags.get("tourism", "hotel").title()
                    addr = tags.get("addr:street", tags.get("addr:suburb", tags.get("addr:city", f"City Centre, {city.title()}")))
                    stars = tags.get("stars")

                    # Truthful rating: use real stars if provided, otherwise "Rating unavailable"
                    rating_str = f"{stars} ⭐" if stars else "Rating unavailable"

                    # Truthful pricing tier label
                    if budget_tier in ("premium", "luxury", "5 star", "high"):
                        price_range = "Luxury tier (Contact hotel for current rates)"
                    elif budget_tier in ("mid-range", "medium"):
                        price_range = "Mid-range tier (Contact hotel for current rates)"
                    else:
                        price_range = "Budget tier (Contact hotel for current rates)"

                    raw_h = {
                        "hotel_name": name,
                        "price_range": price_range,
                        "rating": rating_str,
                        "location": f"{addr} ({tourism_type})",
                        "budget_tier": budget_tier,
                        "source": "OpenStreetMap Overpass API",
                    }
                    osm_results.append(validate_hotel_entry(raw_h))
                    if len(osm_results) >= 5:
                        break
            return osm_results if osm_results else None

    async def _fetch_duckduckgo_hotels() -> list[dict[str, Any]] | None:
        logger.info(f"Searching hotels for '{city}' via DuckDuckGo")
        if budget_tier in ("premium", "luxury", "5 star", "high"):
            raw_query = f"top luxury 5 star hotels in {city}"
        elif budget_tier in ("mid-range", "medium"):
            raw_query = f"best mid-range hotels in {city}"
        else:
            raw_query = f"budget hotels hostels in {city}"

        search_query = urllib.parse.quote(raw_query)
        ddg_url = f"https://html.duckduckgo.com/html/?q={search_query}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/120.0.0.0"
            )
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await http_get_with_retry(client, ddg_url, headers=headers, timeout=8.0, max_retries=1)
            blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
            results = []
            for block in blocks[1:10]:  # scan more blocks to find enough named hotels
                # Prefer the page title (<a class="result__a">) over the URL slug
                title_match = re.search(r'<a class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not (title_match and snippet_match):
                    continue
                raw_title = html.unescape(re.sub(r"<[^>]*>", "", title_match.group(1)).strip())
                snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip())
                # Strip trailing site-name suffixes (e.g. "- Booking.com", "| MakeMyTrip")
                clean_name = re.sub(
                    r"\s*[\|-]\s*(?:Booking\.com|MakeMyTrip|Tripadvisor|Agoda|Hotels\.com|Expedia|Goibibo|OYO|Airbnb|Wikipedia|JustDial|Yatra).*",
                    "", raw_title, flags=re.IGNORECASE,
                ).strip()
                # Skip entries whose "name" is still a URL or a generic directory title
                if re.search(r'https?://|www\.', clean_name) or len(clean_name) < 4:
                    continue
                raw_h = {
                    "hotel_name": clean_name[:60],
                    "price_range": "Contact hotel / booking platform for current prices",
                    "rating": "Rating unavailable",
                    "location": snippet[:100],
                    "budget_tier": budget_tier,
                    "source": "DuckDuckGo Search",
                }
                results.append(validate_hotel_entry(raw_h))
                if len(results) >= 5:
                    break
            return results if results else None

    providers = [
        ("OpenStreetMap Overpass API", _fetch_openstreetmap_hotels),
        ("DuckDuckGo Search", _fetch_duckduckgo_hotels),
    ]

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, list) and len(res) > 0,
    )

    if result is not None and len(result) > 0:
        return result

    # TRUTHFUL FALLBACK: Never fabricate fake hotels
    return [{"source": "Notice", "summary": f"No hotel recommendations found for '{city}'."}]


# ---------------------------------------------------------------------------
# 5. Restaurants Tool Implementation
# ---------------------------------------------------------------------------


async def famous_restaurants_data(city: str, query: str | None = None) -> list[dict[str, Any]]:
    """Suggest famous local restaurants for a city.

    Fallback Chain: OpenStreetMap Overpass API -> DuckDuckGo Search -> Fresh Cache -> Stale Cache -> Notice output.
    Fabricated restaurants (such as hardcoded Jaipur places for all cities) are strictly prohibited.
    """
    try:
        city = validate_city_name(city)
    except ValueError as e:
        return [{"error": str(e)}]

    cuisine_tag = f":{query.lower().strip()}" if query else ""
    cache_key = f"restaurants:{city.lower().strip()}{cuisine_tag}"

    async def _fetch_openstreetmap_restaurants() -> list[dict[str, Any]] | None:
        logger.info(f"Querying OpenStreetMap Overpass API for restaurants in '{city}'")
        async with httpx.AsyncClient(timeout=8.0) as client:
            geo_res = await _geocode_city(city, client)
            if not geo_res:
                return None

            lat, lon, _, _ = geo_res
            op_url = "https://overpass-api.de/api/interpreter"
            headers = {"User-Agent": "PlanPilotApp/1.0 (contact@planpilot.ai)"}
            op_ql = f'[out:json][timeout:15];node["amenity"="restaurant"]["name"](around:4000, {lat}, {lon});out tags 12;'

            resp = await http_get_with_retry(client, op_url, headers=headers, params={"data": op_ql}, timeout=20.0, max_retries=2)
            elements = resp.json().get("elements", [])
            osm_restaurants = []
            for el in elements:
                tags = el.get("tags", {})
                name = tags.get("name")
                if name:
                    cuisine = tags.get("cuisine", "Local Specialities").replace("_", " ").title()
                    addr = tags.get("addr:street", tags.get("addr:suburb", tags.get("addr:city", f"City Centre, {city.title()}")))

                    osm_restaurants.append({
                        "restaurant_name": name,
                        "speciality": f"{cuisine} Cuisine",
                        "rating": "Rating unavailable",  # Truthful rating: OSM node doesn't provide rating
                        "location": f"{addr}, {city.title()}",
                        "why_popular": f"Popular {cuisine} dining spot in {city.title()} listed on OpenStreetMap.",
                        "source": "OpenStreetMap Overpass API",
                    })
                    if len(osm_restaurants) >= 5:
                        break
            return osm_restaurants if osm_restaurants else None

    async def _fetch_duckduckgo_restaurants() -> list[dict[str, Any]] | None:
        search_terms = f"famous iconic {query} restaurants in {city}" if query else f"famous iconic local restaurants in {city}"
        search_query = urllib.parse.quote(search_terms)
        ddg_url = f"https://html.duckduckgo.com/html/?q={search_query}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/120.0.0.0"
            )
        }
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await http_get_with_retry(client, ddg_url, headers=headers, timeout=8.0, max_retries=1)
            blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
            results = []
            for block in blocks[1:10]:  # scan more blocks to find enough named restaurants
                # Use page title, not URL slug
                title_match = re.search(r'<a class="result__a"[^>]*>(.*?)</a>', block, re.DOTALL)
                snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                if not (title_match and snippet_match):
                    continue
                raw_title = html.unescape(re.sub(r"<[^>]*>", "", title_match.group(1)).strip())
                snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip())
                clean_name = re.sub(
                    r"\s*[\|-]\s*(?:Tripadvisor|Zomato|Yelp|Wikipedia|Blog|Instagram|Facebook|YouTube|Swiggy|Dineout|EazyDiner).*",
                    "", raw_title, flags=re.IGNORECASE,
                ).strip()
                # Skip entries whose "name" is still a URL or too short to be meaningful
                if re.search(r'https?://|www\.', clean_name) or len(clean_name) < 4:
                    continue
                results.append({
                    "restaurant_name": clean_name[:65],
                    "speciality": f"{query.title() if query else 'Famous Local Delicacies'} in {city.title()}",
                    "rating": "Rating unavailable",
                    "location": f"City Centre, {city.title()}",
                    "why_popular": snippet[:140],
                    "source": "DuckDuckGo Local Search",
                })
                if len(results) >= 5:
                    break
            return results if results else None

    providers = [
        ("OpenStreetMap Overpass API", _fetch_openstreetmap_restaurants),
        ("DuckDuckGo Search", _fetch_duckduckgo_restaurants),
    ]

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, list) and len(res) > 0,
    )

    if result is not None and len(result) > 0:
        return result

    # TRUTHFUL FALLBACK: Never fabricate fake Jaipur restaurants for other cities
    return [{"source": "Notice", "summary": f"No restaurant recommendations found for '{city}'."}]


# ---------------------------------------------------------------------------
# 6. Travel Route Tool Implementation
# ---------------------------------------------------------------------------


async def travel_route_data(source: str, destination: str) -> dict[str, Any]:
    """Suggest optimal travel route between source and destination cities.

    Fallback Chain: Geocoding via Open-Meteo -> Haversine Distance Calculation.
    If geocoding fails, returns an explicit error dict without fake distance fallbacks.
    """
    try:
        source = validate_city_name(source)
        destination = validate_city_name(destination)
    except ValueError as e:
        return {"error": str(e)}

    if source.lower().strip() == destination.lower().strip():
        return {"error": "Source and destination cities must be different."}

    logger.info(f"Calculating travel route from '{source}' to '{destination}'")
    cache_key = f"route:{source.lower().strip()}:{destination.lower().strip()}"

    async def _calculate_route_from_geocoding() -> dict[str, Any] | None:
        async with httpx.AsyncClient(timeout=8.0) as client:
            geo1 = await _geocode_city(source, client)
            geo2 = await _geocode_city(destination, client)

            if not geo1 or not geo2:
                return None

            lat1, lon1, src_name, country1 = geo1
            lat2, lon2, dest_name, country2 = geo2

            direct_dist = haversine_distance(lat1, lon1, lat2, lon2)
            dist_km = max(30, int(direct_dist * 1.25))
            is_diff_country = bool(country1 and country2 and country1.lower().strip() != country2.lower().strip())

            drive_hrs = round(dist_km / 60.0, 1)
            train_hrs = round(dist_km / 70.0, 1)
            flight_hrs = round(max(1.0, dist_km / 600.0), 1)

            base_options = [
                {"mode": "Drive", "option": "National Highway Road Trip", "duration": f"{drive_hrs} hrs", "approx_cost": f"₹{int(dist_km * 9)} - ₹{int(dist_km * 14)}"},
                {"mode": "Train", "option": "Express / Superfast Train", "duration": f"{train_hrs} hrs", "approx_cost": f"₹{max(300, int(dist_km * 1.8))} - ₹{max(800, int(dist_km * 3.2))}"},
                {"mode": "Bus", "option": "Intercity AC Sleeper Bus", "duration": f"{round(drive_hrs * 1.15, 1)} hrs", "approx_cost": f"₹{max(400, int(dist_km * 1.5))} - ₹{max(1000, int(dist_km * 2.5))}"},
            ]
            if dist_km >= 250:
                base_options.append({"mode": "Flight", "option": "Direct / Connecting Commercial Flight", "duration": f"{flight_hrs} hrs", "approx_cost": "₹3,500 - ₹8,500"})

            val_res = validate_transportation(
                origin=src_name,
                destination=dest_name,
                distance_km=dist_km,
                is_different_country=is_diff_country,
                transport_options=base_options,
            )

            # Truthful labeling: explicitly state estimated geographic distance
            return {
                "source": src_name,
                "destination": dest_name,
                "distance_km": f"~{dist_km} km (estimated road distance)",
                "travel_time": val_res.get("travel_time", f"{flight_hrs} hrs (Flight)"),
                "recommended_mode": val_res.get("recommended_mode", "Commercial Airline Flight"),
                "transport_options": val_res.get("transport_options", base_options),
                "route_summary": val_res.get("route_summary", f"Estimated transport corridor between {src_name} and {dest_name}."),
            }

    providers = [("Geocoding Distance Calculation", _calculate_route_from_geocoding)]

    result, source_used = await execute_fallback_chain(
        providers,
        cache_key=cache_key,
        cache=global_cache,
        is_valid_result=lambda res: isinstance(res, dict) and "distance_km" in res,
    )

    if result is not None:
        return result

    # TRUTHFUL FALLBACK: Return error if geocoding fails, never fabricate "Approx 350 - 500 km"
    return {"error": f"Could not calculate travel route between '{source}' and '{destination}' because location geocoding failed."}
