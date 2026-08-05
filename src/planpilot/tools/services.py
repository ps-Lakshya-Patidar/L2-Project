"""Service implementations for the PlanPilot tools.

Calls external free APIs: Open-Meteo, Open Library, and DuckDuckGo search.
"""

from __future__ import annotations
import html
import re
import urllib.parse
from typing import Any
import httpx

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


async def get_weather_data(city: str) -> dict[str, Any]:
    """Fetch current weather for a city using Open-Meteo Geocoding and Forecast APIs.

    Returns current temperature in Celsius, windspeed in km/h, and precipitation forecast.
    """
    search_name = city.lower().strip()
    query_city = city
    note = None

    if search_name in REGION_FALLBACKS:
        fallback_city, region_name = REGION_FALLBACKS[search_name]
        query_city = fallback_city
        note = f"Showing weather for {fallback_city} (major city/capital of {region_name})"

    async with httpx.AsyncClient() as client:
        # 1. Geocode city name to lat/lon
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={query_city}&count=1&language=en&format=json"
        geo_resp = await client.get(geo_url)
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()

        if not geo_data.get("results"):
            return {"error": f"City '{city}' not found."}

        result = geo_data["results"][0]
        lat = result["latitude"]
        lon = result["longitude"]
        name = result.get("name", city)
        country = result.get("country", "")

        # 2. Get current weather and hourly forecast for precipitation
        weather_url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            f"&current_weather=true&hourly=precipitation_probability,rain&temperature_unit=celsius&wind_speed_unit=kmh"
        )
        weather_resp = await client.get(weather_url)
        weather_resp.raise_for_status()
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
            else:
                try:
                    from datetime import datetime

                    if current_time_str:
                        curr_hour = datetime.fromisoformat(current_time_str).hour
                        start_idx = min(curr_hour, len(hourly_times) - 1)
                except Exception:
                    start_idx = 0

            # Slice next 12 hours
            next_12_rain = hourly_rain[start_idx : start_idx + 12]
            next_12_prob = hourly_prob[start_idx : start_idx + 12]

            any_rain_expected = any(r > 0.1 for r in next_12_rain)
            rain_probability_max = max(next_12_prob) if next_12_prob else 0
            rain_sum_mm = round(sum(next_12_rain), 2) if next_12_rain else 0.0

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
        }
        if note:
            res["note"] = note
        return res


async def search_books_data(query: str) -> list[dict[str, Any]]:
    """Search books using Open Library API with a fast fallback to DuckDuckGo web search."""
    safe_query = urllib.parse.quote(query)
    url = (
        f"https://openlibrary.org/search.json?q={safe_query}&limit=5"
        "&fields=key,title,author_name,first_publish_year,number_of_pages_median"
    )

    # 1. Try Open Library with a crisp 3.5s timeout
    try:
        async with httpx.AsyncClient(timeout=3.5) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
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
                    return books
    except Exception:
        pass

    # 2. Fallback to fast web search for books
    try:
        search_term = urllib.parse.quote(f"{query} books recommendations")
        ddg_url = f"https://html.duckduckgo.com/html/?q={search_term}"
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        async with httpx.AsyncClient(timeout=4.0) as client:
            resp = await client.get(ddg_url, headers=headers)
            if resp.status_code == 200:
                blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
                fallback_books = []
                for block in blocks[1:5]:
                    title_match = re.search(r'<a class="result__url"[^>]*>(.*?)</a>', block, re.DOTALL)
                    snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)
                    if title_match and snippet_match:
                        title = html.unescape(re.sub(r"<[^>]*>", "", title_match.group(1)).strip())
                        snippet = html.unescape(re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip())
                        fallback_books.append({"title": title, "author": "Web Recommendation", "info_url": snippet})
                if fallback_books:
                    return fallback_books
    except Exception:
        pass

    return [{"source": "Notice", "summary": f"No book results found for '{query}'"}]


async def discover_events_data(city: str, query: str | None = None) -> list[dict[str, str]]:
    """Search for live events happening in a specific location using SerpAPI Google Search, with a fallback to DuckDuckGo search."""
    from planpilot.utils.config import get_settings
    settings = get_settings()

    if query:
        search_query = f"{query} in {city} this weekend"
    else:
        search_query = f"events in {city} this weekend"

    # 1. Attempt to use SerpAPI standard search if API Key is configured
    if settings.serpapi_api_key and settings.serpapi_api_key.strip():
        api_key = settings.serpapi_api_key.strip()
        safe_query = urllib.parse.quote(search_query)
        safe_location = urllib.parse.quote(city)
        url = f"https://serpapi.com/search.json?q={safe_query}&location={safe_location}&api_key={api_key}"

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.get(url, timeout=15.0)
                if resp.status_code == 200:
                    data = resp.json()
                    events_list = data.get("events_results", [])
                    if events_list:
                        results = []
                        for ev in events_list[:5]:
                            title = ev.get("title", "Unknown Event")
                            date_str = ev.get("date", "TBD")
                            time_str = ev.get("time", "")

                            address = ev.get("address", [])
                            venue = address[0] if address else "Unknown Venue"

                            # Construct direct Google Search URL for the specific event to find booking pages
                            safe_event_search = urllib.parse.quote(f"{title} {city} tickets")
                            link = f"https://www.google.com/search?q={safe_event_search}"

                            when_str = f"{date_str} at {time_str}" if time_str else date_str
                            summary = f"Happening at {venue} ({when_str}). Info/Tickets: {link}"
                            results.append({"source": title, "summary": summary})
                        return results
                    else:
                        return [
                            {
                                "source": "SerpAPI Notice",
                                "summary": f"No upcoming events matched '{search_query}' in structured search results.",
                            }
                        ]
        except Exception:
            # Fall back to DuckDuckGo search if SerpAPI request fails
            pass

    # 2. Fallback to DuckDuckGo web scraping
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }
    if query:
        search_query = f"{query} in {city} this weekend"
    else:
        search_query = f"events in {city} this weekend"

    safe_search_query = urllib.parse.quote(search_query)
    url = f"https://html.duckduckgo.com/html/?q={safe_search_query}"

    async with httpx.AsyncClient() as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()

    blocks = resp.text.split('<div class="result results_links results_links_deep web-result')
    results = []

    for block in blocks[1:6]:  # Extract top 5 results
        title_match = re.search(r'<a class="result__url"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_match = re.search(r'<a class="result__snippet"[^>]*>(.*?)</a>', block, re.DOTALL)

        if title_match and snippet_match:
            title = re.sub(r"<[^>]*>", "", title_match.group(1)).strip()
            snippet = re.sub(r"<[^>]*>", "", snippet_match.group(1)).strip()

            title = html.unescape(title)
            snippet = html.unescape(snippet)

            results.append({"source": title, "summary": snippet})

    if not results:
        results.append(
            {
                "source": "Search Parser Warning",
                "summary": (
                    "The search request completed, but the HTML parsing rules did not match the page layout. "
                    "The search engine layout may have changed, or no events matched the query. "
                    "Please check event websites directly."
                ),
            }
        )

    return results


def compute_weekend_score(
    weather: dict,
    events: list[dict],
    prefs: dict | None = None,
) -> dict:
    """Compute a Weekend Quality Score (0-100) based on weather, events, and user preferences.

    Scoring breakdown:
    - Weather base score: 0-50 points
      * Clear/sunny (code 0-1): 50 pts
      * Partly cloudy (code 2-3): 40 pts
      * Overcast (code 45+): 25 pts
      * Rain expected: subtract up to 20 pts based on probability
    - Events score: 0-30 points
      * 0 events: 0 pts | 1-2: 10 pts | 3-4: 20 pts | 5+: 30 pts
    - Preference match bonus: 0-20 points
      * +4 pts per event/activity that matches a user interest keyword (max 20)

    Returns a dict with score (int), label (str), weather_summary (str), and tips (list[str]).
    """
    score = 0
    tips: list[str] = []

    # --- Weather Score ---
    weather_code = weather.get("weather_code", 99)
    temp = weather.get("temperature_c", 20)
    forecast = weather.get("forecast_next_12h", {})
    rain_expected = forecast.get("any_rain_expected", False)
    rain_prob = forecast.get("max_rain_probability_percent", 0)

    if weather_code <= 1:
        weather_score = 50
        weather_summary = f"Clear and sunny ({temp}°C) - perfect outdoor conditions!"
    elif weather_code <= 3:
        weather_score = 40
        weather_summary = f"Partly cloudy ({temp}°C) - pleasant weather for outings."
    elif weather_code <= 48:
        weather_score = 25
        weather_summary = f"Overcast ({temp}°C) - comfortable but grey skies."
    else:
        weather_score = 15
        weather_summary = f"Rainy/stormy ({temp}°C) - expect wet conditions."

    if rain_expected:
        penalty = min(int(rain_prob / 5), 20)  # up to 20 pts penalty
        weather_score = max(0, weather_score - penalty)
        tips.append("Rain expected - have a backup indoor plan ready.")
    score += weather_score

    # --- Events Score ---
    valid_events = [e for e in events if e.get("source") not in ("SerpAPI Notice", "Search Parser Warning")]
    n = len(valid_events)
    if n >= 5:
        events_score = 30
    elif n >= 3:
        events_score = 20
    elif n >= 1:
        events_score = 10
    else:
        events_score = 0
        tips.append("No events found - consider exploring parks or trying a new restaurant.")
    score += events_score

    # --- Preference Match Bonus ---
    bonus = 0
    if prefs and prefs.get("interests") and valid_events:
        interests = [i.lower() for i in prefs.get("interests", [])]
        for ev in valid_events:
            ev_text = (ev.get("source", "") + " " + ev.get("summary", "")).lower()
            if any(kw in ev_text for kw in interests):
                bonus = min(bonus + 4, 20)
    score += bonus

    # --- Label ---
    if score >= 80:
        label = "Excellent Weekend!"
    elif score >= 60:
        label = "Great Weekend!"
    elif score >= 40:
        label = "Good Weekend"
    elif score >= 20:
        label = "Average Weekend"
    else:
        label = "Tough Weekend"

    # General tips
    if temp > 35:
        tips.append("It's quite hot - stay hydrated and prefer evening outings.")
    elif temp < 10:
        tips.append("It's cold - layer up before heading outdoors.")

    return {
        "score": min(score, 100),
        "label": label,
        "weather_summary": weather_summary,
        "events_found": n,
        "preference_bonus": bonus,
        "tips": tips,
    }
