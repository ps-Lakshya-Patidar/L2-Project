"""Service implementations for the Weekend Wizard tools.

Calls external free APIs: Open-Meteo, Open Library, JokeAPI, Dog CEO, and Open Trivia.
"""

from __future__ import annotations

from typing import Any

import httpx


async def get_weather_data(city: str) -> dict[str, Any]:
    """Fetch current weather for a city using Open-Meteo Geocoding and Forecast APIs."""
    async with httpx.AsyncClient() as client:
        # 1. Geocode city name to lat/lon
        geo_url = f"https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1&language=en&format=json"
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

        # 2. Get current weather
        weather_url = f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current_weather=true&temperature_unit=celsius"
        weather_resp = await client.get(weather_url)
        weather_resp.raise_for_status()
        weather_data = weather_resp.json()

        current = weather_data.get("current_weather", {})
        temp = current.get("temperature")
        windspeed = current.get("windspeed")
        weathercode = current.get("weathercode")

        return {
            "city": name,
            "country": country,
            "latitude": lat,
            "longitude": lon,
            "temperature_c": temp,
            "windspeed_kmh": windspeed,
            "weather_code": weathercode,
        }


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


async def get_joke_data(category: str = "Any") -> dict[str, Any]:
    """Fetch a joke from JokeAPI."""
    async with httpx.AsyncClient() as client:
        url = f"https://v2.jokeapi.dev/joke/{category}?safe-mode"
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        if data.get("error"):
            return {"error": data.get("message", "Unknown JokeAPI error.")}

        if data.get("type") == "single":
            return {"joke": data.get("joke")}
        else:
            return {"setup": data.get("setup"), "delivery": data.get("delivery")}


async def get_dog_image_data(breed: str | None = None) -> dict[str, Any]:
    """Fetch a random dog image from Dog CEO API, optionally filtered by breed."""
    async with httpx.AsyncClient() as client:
        if breed:
            # Clean breed string (lowercase, replace spaces with sub-breed format)
            breed_path = breed.lower().strip().replace(" ", "/")
            url = f"https://dog.ceo/api/breed/{breed_path}/images/random"
        else:
            url = "https://dog.ceo/api/breeds/image/random"

        resp = await client.get(url)
        if resp.status_code == 404 and breed:
            # Fallback to general random dog if breed not found
            url = "https://dog.ceo/api/breeds/image/random"
            resp = await client.get(url)

        resp.raise_for_status()
        data = resp.json()
        return {"image_url": data.get("message")}


async def get_trivia_data(difficulty: str | None = None) -> dict[str, Any]:
    """Fetch a trivia question from Open Trivia DB."""
    async with httpx.AsyncClient() as client:
        url = "https://opentdb.com/api.php?amount=1"
        if difficulty:
            url += f"&difficulty={difficulty.lower()}"

        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

        results = data.get("results", [])
        if not results:
            return {"error": "No trivia questions returned."}

        question_info = results[0]
        return {
            "category": question_info.get("category"),
            "type": question_info.get("type"),
            "difficulty": question_info.get("difficulty"),
            "question": question_info.get("question"),
            "correct_answer": question_info.get("correct_answer"),
            "incorrect_answers": question_info.get("incorrect_answers"),
        }
