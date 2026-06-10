"""Suivi de colis PKGE — reproduit la forme de getTrackingInfo() de l'ancien Apps Script.

Les valeurs `last_status` / `delivery_status` de PKGE sont passées telles quelles :
le firmware compare `status` à "delivered" et `deliveryStatus` à "in_transit",
littéraux qui viennent directement de PKGE.
"""

import logging
from datetime import datetime

import httpx

from ..config import TrackingConfig

log = logging.getLogger(__name__)

TRACK_URL = "https://api.pkge.net/v1/packages"
MAX_ITEMS = 5  # limite firmware


def shape_tracking(payload: list[dict], now: datetime) -> list[dict]:
    result = []
    for pkg in payload:
        number = str(pkg.get("track_number") or "")
        if not number:
            continue
        result.append(
            {
                "tracking": number,
                "status": str(pkg.get("last_status") or ""),
                "deliveryStatus": str(pkg.get("delivery_status") or ""),
                "lastChecked": now.strftime("%Y-%m-%d %H:%M:%S"),
                "cached": True,
            }
        )
        if len(result) == MAX_ITEMS:
            break
    return result


async def fetch_tracking(cfg: TrackingConfig, client: httpx.AsyncClient) -> list[dict] | None:
    try:
        response = await client.get(
            f"{TRACK_URL}/list", headers={"X-Api-Key": cfg.api_key}
        )
    except httpx.HTTPError as exc:
        log.warning("PKGE: %s", exc)
        return None
    if response.status_code != 200:
        log.warning("PKGE: HTTP %s", response.status_code)
        return None
    payload = response.json().get("payload")
    if payload is None:
        log.warning("PKGE: réponse sans champ payload")
        return None
    return shape_tracking(payload, datetime.now())
