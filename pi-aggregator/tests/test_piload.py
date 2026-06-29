import asyncio

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
