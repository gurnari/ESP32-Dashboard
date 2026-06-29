"""Chargement de la configuration TOML de l'agrégateur."""

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class WeatherConfig:
    latitude: float
    longitude: float
    days: int = 4
    refresh_minutes: int = 60


@dataclass(frozen=True)
class TrackingConfig:
    api_key: str
    refresh_minutes: int = 30


@dataclass(frozen=True)
class ClaudeConfig:
    admin_api_key: str
    refresh_minutes: int = 60


@dataclass(frozen=True)
class PiLoadConfig:
    """Charge locale du Raspberry Pi (CPU, RAM, température)."""

    enabled: bool = True
    refresh_minutes: int = 1


@dataclass(frozen=True)
class Config:
    layout_file: Path
    host: str = "0.0.0.0"
    port: int = 8080
    weather: WeatherConfig | None = None
    tracking: TrackingConfig | None = None
    claude: ClaudeConfig | None = None
    piload: PiLoadConfig | None = None


def load_config(path: str | Path | None = None) -> Config:
    """Charge config.toml (chemin explicite, $PI_AGGREGATOR_CONFIG, ou racine du projet).

    Fichier absent → configuration minimale : layout seul, pas de sources réseau.
    """
    path = Path(path or os.environ.get("PI_AGGREGATOR_CONFIG", ROOT / "config.toml"))
    raw: dict = {}
    if path.is_file():
        raw = tomllib.loads(path.read_text())

    layout_file = Path(raw.get("layout", {}).get("file", "layout.json"))
    if not layout_file.is_absolute():
        layout_file = (path.parent if path.is_file() else ROOT) / layout_file

    weather_raw = raw.get("weather")
    tracking_raw = raw.get("tracking")
    tracking_enabled = bool(tracking_raw and tracking_raw.get("api_key"))
    claude_raw = raw.get("claude")
    claude_enabled = bool(claude_raw and claude_raw.get("admin_api_key"))
    piload_raw = raw.get("piload")
    piload_enabled = bool(piload_raw and piload_raw.get("enabled", True))
    server = raw.get("server", {})

    return Config(
        layout_file=layout_file,
        host=server.get("host", "0.0.0.0"),
        port=int(server.get("port", 8080)),
        weather=WeatherConfig(**weather_raw) if weather_raw else None,
        tracking=TrackingConfig(**tracking_raw) if tracking_enabled else None,
        claude=ClaudeConfig(**claude_raw) if claude_enabled else None,
        piload=PiLoadConfig(**piload_raw) if piload_enabled else None,
    )
