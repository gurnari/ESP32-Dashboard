"""Assemblage du JSON consolidé servi à l'ESP32.

Chaque source garde sa dernière bonne valeur (last-good) : un échec réseau ne vide
jamais le dashboard, la valeur précédente reste servie et la source est retentée
au tick suivant tant qu'elle est périmée.
"""

import logging
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta

import httpx

from .config import Config
from .sources.layout import load_layout
from .sources.piload import fetch_piload
from .sources.tracking import fetch_tracking
from .sources.weather import fetch_weather

log = logging.getLogger(__name__)


class Source:
    def __init__(
        self,
        name: str,
        fetch: Callable[[], Awaitable[list | dict | None]],
        refresh: timedelta,
    ):
        self.name = name
        self._fetch = fetch
        self._refresh = refresh
        self.value: list | dict | None = None
        self.refreshed_at: datetime | None = None

    @property
    def stale(self) -> bool:
        if self.refreshed_at is None:
            return True
        return datetime.now(UTC) - self.refreshed_at >= self._refresh

    async def refresh(self) -> None:
        try:
            value = await self._fetch()
        except Exception:
            log.exception("source %s: échec du rafraîchissement", self.name)
            return
        if value is None:
            log.warning("source %s: pas de données, dernière valeur conservée", self.name)
            return
        self.value = value
        self.refreshed_at = datetime.now(UTC)


class Aggregator:
    def __init__(self, cfg: Config, client: httpx.AsyncClient):
        self.cfg = cfg
        self.sources: list[Source] = []
        if cfg.weather:
            weather_cfg = cfg.weather
            self.sources.append(
                Source(
                    "weather",
                    lambda: fetch_weather(weather_cfg, client),
                    timedelta(minutes=weather_cfg.refresh_minutes),
                )
            )
        if cfg.tracking:
            tracking_cfg = cfg.tracking
            self.sources.append(
                Source(
                    "tracking",
                    lambda: fetch_tracking(tracking_cfg, client),
                    timedelta(minutes=tracking_cfg.refresh_minutes),
                )
            )
        if cfg.piload:
            self.sources.append(
                Source(
                    "piload",
                    lambda: fetch_piload(),
                    timedelta(minutes=cfg.piload.refresh_minutes),
                )
            )

    async def refresh_stale(self) -> None:
        for source in self.sources:
            if source.stale:
                await source.refresh()

    def build(self) -> dict:
        """JSON consolidé. Une source sans valeur est omise : le firmware tolère
        l'absence d'une clé de 1er niveau (widget « Not available »)."""
        doc: dict = {"layout": load_layout(self.cfg.layout_file)}
        for source in self.sources:
            if source.value is not None:
                doc[source.name] = source.value
        doc["lastUpdated"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return doc

    def health(self) -> dict:
        return {
            source.name: source.refreshed_at.isoformat() if source.refreshed_at else None
            for source in self.sources
        }
