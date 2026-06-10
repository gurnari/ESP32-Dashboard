from datetime import UTC, datetime

from pi_aggregator.sources.claude_usage import shape_claude_usage

TODAY = datetime(2026, 6, 10, 0, 0, 0, tzinfo=UTC)


def _bucket(day: str, uncached: int, cache_read: int, c5m: int, c1h: int, out: int) -> dict:
    return {
        "starting_at": f"{day}T00:00:00Z",
        "ending_at": f"{day}T00:00:00Z",
        "results": [
            {
                "uncached_input_tokens": uncached,
                "cache_read_input_tokens": cache_read,
                "cache_creation": {
                    "ephemeral_5m_input_tokens": c5m,
                    "ephemeral_1h_input_tokens": c1h,
                },
                "output_tokens": out,
            }
        ],
    }


def test_forme_today_week():
    shaped = shape_claude_usage([_bucket("2026-06-10", 100, 0, 0, 0, 10)], TODAY)
    assert set(shaped) == {"today", "week"}
    assert set(shaped["today"]) == {"input_tokens", "output_tokens"}
    assert set(shaped["week"]) == {"input_tokens", "output_tokens"}


def test_semaine_somme_tous_les_seaux_jour_isole():
    buckets = [
        _bucket("2026-06-08", 1000, 0, 0, 0, 100),
        _bucket("2026-06-09", 2000, 0, 0, 0, 200),
        _bucket("2026-06-10", 4000, 0, 0, 0, 400),
    ]
    shaped = shape_claude_usage(buckets, TODAY)
    assert shaped["today"] == {"input_tokens": 4000, "output_tokens": 400}
    assert shaped["week"] == {"input_tokens": 7000, "output_tokens": 700}


def test_tokens_cache_comptes_en_entree():
    shaped = shape_claude_usage([_bucket("2026-06-10", 100, 200, 30, 40, 5)], TODAY)
    assert shaped["today"]["input_tokens"] == 100 + 200 + 30 + 40


def test_plusieurs_resultats_par_seau():
    bucket = _bucket("2026-06-10", 100, 0, 0, 0, 10)
    bucket["results"].append({"uncached_input_tokens": 50, "output_tokens": 5})
    shaped = shape_claude_usage([bucket], TODAY)
    assert shaped["today"] == {"input_tokens": 150, "output_tokens": 15}


def test_sans_seaux_zeros():
    shaped = shape_claude_usage([], TODAY)
    assert shaped == {
        "today": {"input_tokens": 0, "output_tokens": 0},
        "week": {"input_tokens": 0, "output_tokens": 0},
    }
