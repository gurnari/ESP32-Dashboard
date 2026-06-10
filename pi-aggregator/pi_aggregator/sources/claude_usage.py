"""Utilisation de Claude — Usage Admin API d'Anthropic (squelette).

Endpoint : GET /v1/organizations/usage_report/messages, seaux quotidiens (1d).
Nécessite une clé Admin (sk-ant-admin..., organisation Console requise — pas
disponible pour un compte individuel). Sans clé dans config.toml, la source est
désactivée et la clé "claude" est omise du JSON (widget « Not available »).

Forme produite (nouvelle clé du contrat, widget firmware à venir sur le gabarit
proxmox.cpp) :
    {"today": {"input_tokens": N, "output_tokens": N},
     "week":  {"input_tokens": N, "output_tokens": N}}
`week` = 7 derniers jours glissants (aujourd'hui inclus), en UTC.
"""

import logging
from datetime import UTC, datetime, timedelta

import httpx

from ..config import ClaudeConfig

log = logging.getLogger(__name__)

USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"
ANTHROPIC_VERSION = "2023-06-01"
DAYS = 7
MAX_PAGES = 5


def _sum_results(results: list[dict]) -> tuple[int, int]:
    """Tokens d'entrée = non-cachés + lus du cache + écritures de cache (5 min et 1 h)."""
    input_tokens = 0
    output_tokens = 0
    for item in results:
        cache_creation = item.get("cache_creation") or {}
        input_tokens += (
            (item.get("uncached_input_tokens") or 0)
            + (item.get("cache_read_input_tokens") or 0)
            + (cache_creation.get("ephemeral_5m_input_tokens") or 0)
            + (cache_creation.get("ephemeral_1h_input_tokens") or 0)
        )
        output_tokens += item.get("output_tokens") or 0
    return input_tokens, output_tokens


def shape_claude_usage(buckets: list[dict], today_start: datetime) -> dict:
    today = {"input_tokens": 0, "output_tokens": 0}
    week = {"input_tokens": 0, "output_tokens": 0}
    today_prefix = today_start.strftime("%Y-%m-%d")
    for bucket in buckets:
        inp, out = _sum_results(bucket.get("results") or [])
        week["input_tokens"] += inp
        week["output_tokens"] += out
        if str(bucket.get("starting_at", "")).startswith(today_prefix):
            today["input_tokens"] += inp
            today["output_tokens"] += out
    return {"today": today, "week": week}


async def fetch_claude_usage(cfg: ClaudeConfig, client: httpx.AsyncClient) -> dict | None:
    today_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    params: dict = {
        "starting_at": (today_start - timedelta(days=DAYS - 1)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "bucket_width": "1d",
        "limit": DAYS,
    }
    headers = {"x-api-key": cfg.admin_api_key, "anthropic-version": ANTHROPIC_VERSION}

    buckets: list[dict] = []
    for _ in range(MAX_PAGES):
        try:
            response = await client.get(USAGE_URL, params=params, headers=headers)
        except httpx.HTTPError as exc:
            log.warning("Claude usage: %s", exc)
            return None
        if response.status_code != 200:
            log.warning("Claude usage: HTTP %s — %s", response.status_code, response.text[:200])
            return None
        payload = response.json()
        buckets.extend(payload.get("data") or [])
        if not payload.get("has_more"):
            break
        params["page"] = payload.get("next_page")
    return shape_claude_usage(buckets, today_start)
