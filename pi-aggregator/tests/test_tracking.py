import json
import re
from datetime import datetime
from pathlib import Path

from pi_aggregator.sources.tracking import shape_tracking

GOLDEN = json.loads((Path(__file__).parent.parent / "golden" / "dashboard.json").read_text())

NOW = datetime(2026, 6, 9, 8, 15, 0)


def _pkg(number: str, status: str = "in_transit") -> dict:
    return {"track_number": number, "last_status": status, "delivery_status": status}


def test_champs_identiques_a_la_fixture_golden():
    shaped = shape_tracking([_pkg("LP00432211CN")], NOW)
    assert set(shaped[0]) == set(GOLDEN["tracking"][0])


def test_litteraux_statuts_passes_tels_quels():
    shaped = shape_tracking([_pkg("A", "delivered"), _pkg("B", "in_transit")], NOW)
    assert shaped[0]["status"] == "delivered"
    assert shaped[1]["deliveryStatus"] == "in_transit"


def test_format_lastchecked():
    shaped = shape_tracking([_pkg("A")], NOW)
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", shaped[0]["lastChecked"])
    assert shaped[0]["lastChecked"] == "2026-06-09 08:15:00"


def test_limite_5_colis():
    shaped = shape_tracking([_pkg(f"N{i}") for i in range(8)], NOW)
    assert len(shaped) == 5


def test_colis_sans_numero_ignore():
    shaped = shape_tracking([{"last_status": "x"}, _pkg("A")], NOW)
    assert [p["tracking"] for p in shaped] == ["A"]
