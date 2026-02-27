"""Web APIs: weather, news. Uses env vars for API keys."""
from __future__ import annotations

import os
from typing import Any

import httpx

from jarvis_core import load_config


def get_weather(location: str) -> dict[str, Any]:
    """Return weather for location. Set OPENWEATHER_API_KEY and optionally OPENWEATHER_BASE_URL."""
    api_key = os.getenv("OPENWEATHER_API_KEY", "").strip()
    base = os.getenv("OPENWEATHER_BASE_URL", "https://api.openweathermap.org/data/2.5").rstrip("/")
    if not api_key:
        return {"summary": "Weather API not configured", "location": location}
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(f"{base}/weather", params={"q": location or "London", "appid": api_key, "units": "metric"})
            if not r.is_success:
                return {"summary": "Unable to fetch weather", "location": location}
            d = r.json()
            main = d.get("main", {})
            desc = (d.get("weather") or [{}])[0].get("description", "")
            temp = main.get("temp")
            return {"summary": f"{desc}, {temp}°C", "temp": temp, "description": desc, "location": d.get("name", location)}
    except Exception as e:
        return {"summary": str(e), "location": location}


def get_news(limit: int = 5) -> dict[str, Any]:
    """Return top headlines. Set NEWS_API_KEY (newsapi.org) in env for optional news."""
    api_key = os.getenv("NEWS_API_KEY", "").strip()
    if not api_key:
        return {"headlines": [], "error": "NEWS_API_KEY not set"}
    try:
        with httpx.Client(timeout=10) as client:
            r = client.get(
                "https://newsapi.org/v2/top-headlines",
                params={"apiKey": api_key, "pageSize": limit, "language": "en"},
            )
            if not r.is_success:
                return {"headlines": [], "error": r.text}
            d = r.json()
            articles = d.get("articles") or []
            headlines = [a.get("title") or "" for a in articles if a.get("title")]
            return {"headlines": headlines, "count": len(headlines)}
    except Exception as e:
        return {"headlines": [], "error": str(e)}
