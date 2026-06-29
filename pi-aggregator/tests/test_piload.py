import asyncio
from pathlib import Path

import httpx

from pi_aggregator.aggregator import Aggregator
from pi_aggregator.config import Config, PiLoadConfig, load_config
from pi_aggregator.sources.piload import (
    fetch_piload,
    parse_cpu_percent,
    parse_mem_percent,
    read_temp_c,
)

STAT_BEFORE = "cpu  100 0 100 700 100 0 0 0 0 0\ncpu0 50 0 50 350 50 0 0 0 0 0\n"
STAT_AFTER = "cpu  150 0 150 900 100 0 0 0 0 0\ncpu0 75 0 75 450 50 0 0 0 0 0\n"
# before: total=1000 idle_all=800 busy=200 ; after: total=1300 idle_all=1000 busy=300
# delta total=300 delta busy=100 -> 33.3 %

MEMINFO = "MemTotal:        4000000 kB\nMemFree:  500000 kB\nMemAvailable: 1000000 kB\n"
# used = (4000000-1000000)/4000000 = 75.0 %


def test_parse_cpu_percent():
    assert parse_cpu_percent(STAT_BEFORE, STAT_AFTER) == 33.3


def test_parse_cpu_percent_no_delta_is_zero():
    assert parse_cpu_percent(STAT_BEFORE, STAT_BEFORE) == 0.0


def test_parse_mem_percent():
    assert parse_mem_percent(MEMINFO) == 75.0


def test_parse_mem_percent_zero_total_is_zero():
    assert parse_mem_percent("MemTotal: 0 kB\nMemAvailable: 0 kB\n") == 0.0


def test_read_temp_c():
    assert read_temp_c("48312\n") == 48.3


def test_fetch_piload_returns_none_off_linux(monkeypatch):
    # Simule /proc illisible : la lecture lève OSError -> None.
    from pi_aggregator.sources import piload

    def boom(_self):
        raise OSError("no /proc here")

    monkeypatch.setattr(piload.Path, "read_text", boom)
    assert asyncio.run(fetch_piload()) is None


# ---------------------------------------------------------------------------
# Tests config + agrégateur (Task 2)
# ---------------------------------------------------------------------------


def test_piload_config_default_enabled(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[piload]\nenabled = true\n")
    cfg = load_config(cfg_file)
    assert cfg.piload == PiLoadConfig(enabled=True, refresh_minutes=1)


def test_piload_disabled_gives_none(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("[piload]\nenabled = false\n")
    assert load_config(cfg_file).piload is None


def test_piload_absent_gives_none(tmp_path):
    cfg_file = tmp_path / "config.toml"
    cfg_file.write_text("")  # pas de section [piload]
    assert load_config(cfg_file).piload is None


def test_aggregator_includes_piload_source_when_configured():
    cfg = Config(layout_file=Path("layout.json"), piload=PiLoadConfig())
    client = httpx.AsyncClient()
    try:
        agg = Aggregator(cfg, client=client)
        assert any(s.name == "piload" for s in agg.sources)
    finally:
        asyncio.run(client.aclose())


def test_aggregator_omits_piload_source_when_none():
    cfg = Config(layout_file=Path("layout.json"))
    client = httpx.AsyncClient()
    try:
        agg = Aggregator(cfg, client=client)
        assert not any(s.name == "piload" for s in agg.sources)
    finally:
        asyncio.run(client.aclose())
