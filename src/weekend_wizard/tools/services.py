"""Service implementations for the Weekend Wizard tools.

Calls external free APIs: Open-Meteo, Open Library, and DuckDuckGo search.
"""

from __future__ import annotations
import html
import re
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
    """Fetch current weather for a city using Open-Meteo Geocoding and Forecast APIs."""
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
            f"&current_weather=true&hourly=precipitation_probability,rain&temperature_unit=celsius"
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
    """Search books using the Open Library API."""
    async with httpx.AsyncClient() as client:
        url = f"https://openlibrary.org/search.json?q={query}&limit=5"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        books = []
        for doc in data.get("docs", []):
            books.append(
                {
                    "title": doc.get("title"),
                    "author": doc.get("author_name", ["Unknown"])[0],
                    "first_publish_year": doc.get("first_publish_year"),
                    "number_of_pages_median": doc.get("number_of_pages_median"),
                    "key": doc.get("key"),
                }
            )
        return books


async def discover_events_data(city: str, query: str | None = None) -> list[dict[str, str]]:
    """Search for live events happening in a specific location using DuckDuckGo search."""
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

    url = f"https://html.duckduckgo.com/html/?q={search_query}"

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

    return results
