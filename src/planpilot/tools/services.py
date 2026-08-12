"""Service implementations for the PlanPilot tools.

Calls external free APIs: Open-Meteo, Open Library, and DuckDuckGo search.
"""

from __future__ import annotations
import html
import re
import urllib.parse
from typing import Any
import httpx
from planpilot.utils.logger import logger

# Map of common regions/states to their capital or major city for weather lookup
REGION_FALLBACKS = {
    "assam": ("Guwahati", "Assam, India"),
    "bihar": ("Patna", "Bihar, India"),
    "goa": ("Panaji", "Goa, India"),
    "gujarat": ("Ahmedabad", "Gujarat, India"),
    "haryana": ("Chandigarh", "Haryana, India"),
    "himachal pradesh": ("Shimla", "Himachal Pradesh, India"),
    "jharkhand": ("Ranchi", "Jharkhand, India"),
    "karnataka": ("Bengaluru", "Karnataka, India"),
    "kerala": ("Thiruvananthapuram", "Kerala, India"),
    "madhya pradesh": ("Bhopal", "Madhya Pradesh, India"),
    "maharashtra": ("Mumbai", "Maharashtra, India"),
    "manipur": ("Imphal", "Manipur, India"),
    "meghalaya": ("Shillong", "Meghalaya, India"),
    "mizoram": ("Aizawl", "Mizoram, India"),
    "nagaland": ("Kohima", "Nagaland, India"),
    "odisha": ("Bhubaneswar", "Odisha, India"),
    "punjab": ("Chandigarh", "Punjab, India"),
    "rajasthan": ("Jaipur", "Rajasthan, India"),
    "sikkim": ("Gangtok", "Sikkim, India"),
    "tamil nadu": ("Chennai", "Tamil Nadu, India"),
    "telangana": ("Hyderabad", "Telangana, India"),
    "tripura": ("Agartala", "Tripura, India"),
    "uttar pradesh": ("Lucknow", "Uttar Pradesh, India"),
    "uttarakhand": ("Dehradun", "Uttarakhand, India"),
    "west bengal": ("Kolkata", "West Bengal, India"),
    "kashmir": ("Srinagar", "Jammu and Kashmir, India"),
    "jammu": ("Jammu", "Jammu and Kashmir, India"),
    "ladakh": ("Leh", "Ladakh, India"),
    "texas": ("Houston", "Texas, USA"),
    "california": ("Los Angeles", "California, USA"),
    "florida": ("Miami", "Florida, USA"),
}


def validate_city_name(city: str) -> str:
    """Validate and sanitize city name.

    Removes special characters and validates length constraints.
    """
    cleaned = re.sub(r"[^a-zA-Z\s\-\.\']", "", city.strip())
    if len(cleaned) < 2:
        raise ValueError("City name must be at least 2 characters long.")
    if len(cleaned) > 100:
        raise ValueError("City name exceeds maximum allowed length (100 characters).")
    return cleaned


async def get_weather_data(city: str) -> dict[str, Any]:
    """Fetch current weather for a city using Open-Meteo Geocoding and Forecast APIs.

    Returns current temperature in Celsius, windspeed in km/h, and precipitation forecast.
    """
    city = validate_city_name(city)
    search_name = city.lower().strip()
    query_city = city
    note = None

    if search_name in REGION_FALLBACKS:
        fallback_city, region_name = REGION_FALLBACKS[search_name]
        query_city = fallback_city
        note = f"Showing weather for {fallback_city} (major city/capital of {region_name})"

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # 1. Geocode city name to lat/lon
            logger.info(f"Geocoding city: '{query_city}'")
            geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={query_city}&count=1&language=en&format=json"
            geo_resp = await client.get(geo_url)
            geo_resp.raise_for_status()
            geo_data = geo_resp.json()

            if not geo_data.get("results"):
                logger.warning(f"Geocoding miss: City '{query_city}' not found.")
                return {"error": f"City '{city}' not found."}

            logger.debug(f"Geocoding hit: '{query_city}' resolved successfully.")

            result = geo_data["results"][0]
            lat = result["latitude"]
            lon = result["longitude"]
            name = result.get("name", city)
            country = result.get("country", "")

            # 2. Get current weather, hourly forecast, and daily forecast (for weekend details)
            logger.info(f"Fetching weather data for lat={lat}, lon={lon}")
            weather_url = (
                f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                f"&current_weather=true&hourly=precipitation_probability,rain"
                f"&daily=weathercode,temperature_2m_max,temperature_2m_min,precipitation_probability_max"
                f"&timezone=auto&temperature_unit=celsius&wind_speed_unit=kmh"
            )
            weather_resp = await client.get(weather_url)
            weather_resp.raise_for_status()
            logger.debug("Weather API request successful.")
            weather_data = weather_resp.json()

            current = weather_data.get("current_weather", {})
            temp = current.get("temperature")
            windspeed = current.get("windspeed")
            weathercode = current.get("weathercode")

            # Parse hourly rain forecast for the next 12 hours
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

            # Parse daily forecast for the next 3 days
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

            res = {
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
            if note:
                res["note"] = note
            return res

    except httpx.TimeoutException as e:
        logger.error(f"Weather API request timed out for '{city}': {e}")
        return {"error": f"Weather API request timed out for city '{city}'. Please try again."}
    except httpx.HTTPStatusError as e:
        logger.error(f"Weather API HTTP status error ({e.response.status_code}): {e}")
        return {"error": f"Weather API HTTP error ({e.response.status_code}): {e.response.text}"}
    except httpx.HTTPError as e:
        logger.error(f"Weather API communication error: {e}")
        return {"error": f"Weather API communication error: {str(e)}"}
    except ValueError as e:
        logger.warning(f"Weather validation error for '{city}': {e}")
        return {"error": str(e)}
    except Exception as e:
        logger.error(f"Unexpected error fetching weather for '{city}': {e}", exc_info=True)
        return {"error": f"Unexpected error fetching weather: {str(e)}"}


async def search_books_data(query: str) -> list[dict[str, Any]]:
    """Search books using the Open Library API.

    Returns up to 5 books with title, author, publish year, page count, and a
    clickable Open Library info URL.
    """
    safe_query = urllib.parse.quote(query)
    url = (
        f"https://openlibrary.org/search.json?q={safe_query}&limit=5"
        "&fields=key,title,author_name,first_publish_year,number_of_pages_median"
    )

    logger.info(f"Searching books for query: '{query}' via Open Library")
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            books = []
            for doc in data.get("docs", []):
                key = doc.get("key")
                info_url = f"https://openlibrary.org{key}" if key else "Unknown"
                books.append(
                    {
                        "title": doc.get("title", "Unknown Title"),
                        "author": doc.get("author_name", ["Unknown"])[0] if doc.get("author_name") else "Unknown",
                        "first_publish_year": doc.get("first_publish_year"),
                        "number_of_pages_median": doc.get("number_of_pages_median"),
                        "info_url": info_url,
                    }
                )
            if books:
                logger.debug(f"Found {len(books)} books from Open Library")
                return books
            logger.warning(f"Open Library returned no results for '{query}'")
            return [{"source": "Notice", "summary": f"No book results found for '{query}'"}]
    except httpx.TimeoutException:
        logger.error(f"Open Library API timed out for query: '{query}'")
        return [{"error": f"Book search timed out for '{query}'. Please try again."}]
    except httpx.HTTPStatusError as e:
        logger.error(f"Open Library API returned HTTP {e.response.status_code} for query: '{query}'")
        return [{"error": f"Book search failed (HTTP {e.response.status_code})."}]
    except Exception as e:
        logger.error(f"Unexpected error searching books for '{query}': {e}", exc_info=True)
        return [{"error": f"Unexpected error during book search: {e}"}]


async def discover_events_data(city: str, query: str | None = None) -> list[dict[str, Any]]:
    """Search for live events happening in a specific location using SerpAPI or DuckDuckGo.

    If no events are retrieved, returns a clean default notice message.
    """
    try:
        city = validate_city_name(city)
    except ValueError as e:
        return [{"source": "Notice", "summary": str(e)}]
    from planpilot.utils.config import get_settings
    settings = get_settings()

    if query:
        search_query = f"{query} in {city} this weekend"
    else:
        search_query = f"events in {city} this weekend"

    results: list[dict[str, Any]] = []

    # 1. Try SerpAPI standard search if API Key is configured
    if settings.serpapi_api_key and settings.serpapi_api_key.strip():
        logger.info(f"Searching events for '{search_query}' via SerpAPI")
        try:
            api_key = settings.serpapi_api_key.strip()
            safe_query = urllib.parse.quote(search_query)
            safe_location = urllib.parse.quote(city)
            url = f"https://serpapi.com/search.json?q={safe_query}&location={safe_location}&api_key={api_key}"

            async with httpx.AsyncClient(timeout=8.0) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                data = resp.json()
                events_list = data.get("events_results", []) or data.get("organic_results", [])
                for ev in events_list[:5]:
                    title = ev.get("title", "Event Option")
                    date_str = ev.get("date", "")
                    address = ev.get("address", [])
                    venue = address[0] if address else ""
                    snippet = ev.get("snippet", "")
                    link = ev.get("link", f"https://www.google.com/search?q={urllib.parse.quote(title)}")

                    parts = [p for p in [venue, date_str, snippet] if p]
                    summary_str = " | ".join(parts) if parts else "Event details"
                    if link:
                        summary_str += f" Info/Tickets: {link}"

                    results.append({"source": title, "summary": summary_str})
                if results:
                    logger.debug(f"Found {len(results)} events from SerpAPI")
                    return results
                else:
                    logger.debug("SerpAPI returned no events, falling back to DuckDuckGo")
        except httpx.TimeoutException:
            logger.warning("SerpAPI timed out. Falling back to DuckDuckGo search.")
        except httpx.HTTPStatusError as e:
            logger.warning(f"SerpAPI failed with status {e.response.status_code}. Falling back to DuckDuckGo search.")
        except Exception as e:
            logger.warning(f"SerpAPI error: {e}. Falling back to DuckDuckGo search.")

    # 2. Try DuckDuckGo search if SerpAPI is not configured or fails
    if not results:
        logger.info(f"Searching events for '{search_query}' via DuckDuckGo")
        try:
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
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
                for block in blocks[1:6]:
                    title_match = re.search(r'<a class="result__url"[^>]*>(.*?)</a>', block, re.DOTALL)
                    snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

                    if title_match and snippet_match:
                        title = html.unescape(re.sub(r"<[^>]*>", "", title_match.group(1)).strip())
                        snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip())
                        results.append({"source": title, "summary": snippet})
                if results:
                    logger.debug(f"Found {len(results)} events from DuckDuckGo")
        except httpx.TimeoutException:
            logger.error("DuckDuckGo event search timed out.")
            return [{"error": "Event search timed out. Please try again later."}]
        except httpx.HTTPStatusError as e:
            logger.error(f"DuckDuckGo event search failed with status {e.response.status_code}")
            return [{"error": f"Event search failed (HTTP {e.response.status_code})."}]
        except Exception as e:
            logger.error(f"DuckDuckGo event search error: {e}", exc_info=True)
            return [{"error": f"An unexpected error occurred during event search: {e}"}]

    # 3. If no events were retrieved, return default notice message
    if not results:
        return [
            {
                "source": "Notice",
                "summary": f"No events retrieved for {city}.",
            }
        ]

    return results
