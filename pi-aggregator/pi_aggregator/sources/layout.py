"""Layout des widgets — lu depuis un fichier JSON éditable sur le Pi (sans reflasher l'ESP32)."""

import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

MAX_ITEMS = 15  # limite firmware


def load_layout(path: Path) -> list[dict]:
    """Relit le fichier à chaque appel pour prendre les modifications à chaud."""
    try:
        layout = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        log.exception("layout: lecture de %s impossible", path)
        return []
    if not isinstance(layout, list):
        log.error("layout: %s doit contenir un tableau JSON", path)
        return []
    if len(layout) > MAX_ITEMS:
        log.warning("layout: %d éléments, le firmware n'en lit que %d", len(layout), MAX_ITEMS)
    return layout[:MAX_ITEMS]
