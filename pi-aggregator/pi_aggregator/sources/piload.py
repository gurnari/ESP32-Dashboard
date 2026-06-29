"""Charge du Raspberry Pi : CPU %, RAM %, température CPU.

Lecture locale de /proc et /sys (aucune dépendance ; le Pi est sous Linux).
Sur une plateforme sans /proc (macOS de dev, certains runners CI), fetch_piload
renvoie None et la clé "piload" est omise du JSON (widget « Not available »).
La température est omise si /sys/class/thermal n'est pas lisible.
"""

import asyncio
from pathlib import Path

CPU_SAMPLE_DELAY = 0.3


def _cpu_times(stat: str) -> tuple[int, int]:
    """(total, idle_all) à partir de la ligne agrégée « cpu » de /proc/stat."""
    for line in stat.splitlines():
        if line.startswith("cpu "):
            fields = [int(x) for x in line.split()[1:]]
            idle_all = fields[3] + fields[4]  # idle + iowait
            return sum(fields), idle_all
    return 0, 0


def parse_cpu_percent(stat_before: str, stat_after: str) -> float:
    total_b, idle_b = _cpu_times(stat_before)
    total_a, idle_a = _cpu_times(stat_after)
    d_total = total_a - total_b
    if d_total <= 0:
        return 0.0
    d_idle = idle_a - idle_b
    return round(100.0 * (d_total - d_idle) / d_total, 1)


def parse_mem_percent(meminfo: str) -> float:
    total = avail = 0
    for line in meminfo.splitlines():
        if line.startswith("MemTotal:"):
            total = int(line.split()[1])
        elif line.startswith("MemAvailable:"):
            avail = int(line.split()[1])
    if total <= 0:
        return 0.0
    return round(100.0 * (total - avail) / total, 1)


def read_temp_c(thermal_raw: str) -> float:
    return round(int(thermal_raw.strip()) / 1000.0, 1)


async def fetch_piload() -> dict | None:
    try:
        before = Path("/proc/stat").read_text()
        await asyncio.sleep(CPU_SAMPLE_DELAY)
        after = Path("/proc/stat").read_text()
        meminfo = Path("/proc/meminfo").read_text()
    except OSError:
        return None

    result: dict = {
        "cpu": parse_cpu_percent(before, after),
        "ram": parse_mem_percent(meminfo),
    }
    try:
        result["temp"] = read_temp_c(
            Path("/sys/class/thermal/thermal_zone0/temp").read_text()
        )
    except OSError:
        pass  # température indisponible -> champ omis
    return result
