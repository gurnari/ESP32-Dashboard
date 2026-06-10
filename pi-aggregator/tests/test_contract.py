"""Tests du contrat JSON : ce que /dashboard sert doit respecter les pièges
documentés dans golden/README.md (le firmware est la référence)."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from pi_aggregator.app import create_app
from pi_aggregator.config import Config

ROOT = Path(__file__).parent.parent
GOLDEN = json.loads((ROOT / "golden" / "dashboard.json").read_text())
LAYOUT_FILE = ROOT / "layout.json"


def test_layout_par_defaut_respecte_le_contrat():
    layout = json.loads(LAYOUT_FILE.read_text())
    assert len(layout) <= 15
    golden_keys = set(GOLDEN["layout"][0])
    for item in layout:
        assert set(item) == golden_keys, f"clés divergentes pour ID {item.get('ID')}"
        # Row_Height / Col_Width avec underscore, sinon lus à 0 par le firmware
        assert isinstance(item["Row_Height"], int)
        assert isinstance(item["Col_Width"], int)
        for extra in ("Extra1", "Extra2", "Extra3", "Extra4", "Extra5"):
            assert isinstance(item[extra], str)


def test_layout_sans_widgets_supprimes():
    layout = json.loads(LAYOUT_FILE.read_text())
    ids = {item["ID"] for item in layout}
    assert not ids & {4, 32, 512}, "Stocks/Proxmox/MakerWorld sont supprimés du fork"


def test_dashboard_sert_layout_et_omet_les_sources_inactives():
    cfg = Config(layout_file=LAYOUT_FILE)  # pas de weather ni tracking
    with TestClient(create_app(cfg)) as client:
        response = client.get("/dashboard")
    assert response.status_code == 200
    doc = response.json()
    assert doc["layout"] == json.loads(LAYOUT_FILE.read_text())
    assert "lastUpdated" in doc
    # sources non configurées / supprimées → clés absentes (firmware : « Not available »)
    for key in ("weather", "tracking", "claude", "stocks", "makerworld", "calEvents"):
        assert key not in doc
    # capacité du DynamicJsonDocument côté firmware
    assert len(response.content) < 60_000


def test_healthz():
    cfg = Config(layout_file=LAYOUT_FILE)
    with TestClient(create_app(cfg)) as client:
        response = client.get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_layout_illisible_donne_tableau_vide():
    cfg = Config(layout_file=ROOT / "nexiste-pas.json")
    with TestClient(create_app(cfg)) as client:
        doc = client.get("/dashboard").json()
    assert doc["layout"] == []
