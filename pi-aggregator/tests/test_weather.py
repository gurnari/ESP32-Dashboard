import json
import re
from pathlib import Path

from pi_aggregator.sources.weather import shape_weather

GOLDEN = json.loads((Path(__file__).parent.parent / "golden" / "dashboard.json").read_text())

DAILY = {
    "time": ["2026-06-09", "2026-06-10", "2026-06-11", "2026-06-12"],
    "sunrise": ["2026-06-09T05:08", "2026-06-10T05:08", "2026-06-11T05:07", "2026-06-12T05:07"],
    "sunset": ["2026-06-09T20:38", "2026-06-10T20:39", "2026-06-11T20:39", "2026-06-12T20:40"],
    "temperature_2m_max": [24.3, 22.0, 25.7, 27.2],
    "temperature_2m_min": [12.1, 11.4, 13.0, 14.5],
    "weather_code": [3, 61, 1, 0],
}

HHMM = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")


def test_forme_identique_a_la_fixture_golden():
    shaped = shape_weather(DAILY, days=4)
    assert shaped == GOLDEN["weather"]


def test_sunrise_sunset_sans_secondes():
    daily = dict(DAILY, sunrise=["2026-06-09T05:08:42"], sunset=["2026-06-09T20:38:01"])
    shaped = shape_weather(daily, days=1)
    assert HHMM.fullmatch(shaped[0]["sunrise"])
    assert HHMM.fullmatch(shaped[0]["sunset"])


def test_jours_plafonnes_a_7():
    daily = {k: v * 3 for k, v in DAILY.items()}  # 12 jours disponibles
    assert len(shape_weather(daily, days=12)) == 7


def test_jours_limites_aux_donnees_disponibles():
    assert len(shape_weather(DAILY, days=7)) == 4


def test_weather_code_zero_par_defaut():
    daily = dict(DAILY, weather_code=[None, 61, 1, 0])
    assert shape_weather(daily, days=1)[0]["weather_code"] == 0
