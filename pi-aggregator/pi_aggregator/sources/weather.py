"""Météo Open-Meteo — reproduit la forme de fetchOpenMeteo() de l'ancien Apps Script."""

import asyncio
import logging

import httpx

from ..config import WeatherConfig

log = logging.getLogger(__name__)

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
MAX_DAYS = 7  # limite firmware
ATTEMPTS = 3


def shape_weather(daily: dict, days: int) -> list[dict]:
    """Met les tableaux `daily` d'Open-Meteo à la forme du contrat JSON.

    sunrise/sunset tronqués à 16 caractères : le firmware attend
    "YYYY-MM-DDTHH:MM" sans secondes.
    """
    days = max(1, min(days, MAX_DAYS, len(daily.get("time", []))))
    return [
        {
            "sunrise": (daily["sunrise"][i] or "")[:16],
            "sunset": (daily["sunset"][i] or "")[:16],
            "temp_max": daily["temperature_2m_max"][i] or 0,
            "temp_min": daily["temperature_2m_min"][i] or 0,
            "weather_code": daily["weather_code"][i] or 0,
        }
        for i in range(days)
    ]


async def fetch_weather(cfg: WeatherConfig, client: httpx.AsyncClient) -> list[dict] | None:
    params = {
        "latitude": cfg.latitude,
        "longitude": cfg.longitude,
        "daily": "weather_code,sunrise,sunset,temperature_2m_max,temperature_2m_min",
        "forecast_days": max(1, min(cfg.days, MAX_DAYS)),
        "timezone": "auto",
    }
    for attempt in range(ATTEMPTS):
        try:
            response = await client.get(OPEN_METEO_URL, params=params)
            if response.status_code == 200:
                daily = response.json().get("daily")
                if daily:
                    return shape_weather(daily, cfg.days)
            log.warning("Open-Meteo: HTTP %s (essai %d)", response.status_code, attempt + 1)
        except httpx.HTTPError as exc:
            log.warning("Open-Meteo: %s (essai %d)", exc, attempt + 1)
        await asyncio.sleep(0.5 * (attempt + 1))
    return None
