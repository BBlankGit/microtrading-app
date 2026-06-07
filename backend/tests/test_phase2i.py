"""
Tests for Phase 2I: Rule-Based Catalyst Sentiment Layer.

No broker. No real orders. Research-only fake-money simulation.
No AI/LLM. No Polygon API calls. All deterministic rule-based logic.
"""

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch


# ── Safety invariants ─────────────────────────────────────────────────────────

def test_sentiment_py_no_ai_no_broker():
    text = (pathlib.Path(__file__).parent.parent / "catalysts" / "sentiment.py").read_text()
    for word in ("openai", "anthropic", "langchain", "alpaca", "execute_order", "place_order"):
        assert word not in text.lower(), f"Forbidden '{word}' in sentiment.py"


def test_sentiment_py_has_disclaimer():
    text = (pathlib.Path(__file__).parent.parent / "catalysts" / "sentiment.py").read_text()
    assert "No broker" in text or "no broker" in text.lower()
    assert "No live trading" in text or "no live trading" in text.lower()
    assert "No real orders" in text or "no real orders" in text.lower()


def test_sentiment_method_label():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company releases annual report"})
    assert result["sentiment_method"] == "rules_v1"


# ── Return shape ──────────────────────────────────────────────────────────────

def test_analyze_catalyst_sentiment_return_shape():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "XYZ beats estimates"})
    for key in ("sentiment", "sentiment_score", "materiality_score",
                "sentiment_method", "sentiment_reasons", "bearish_flags", "bullish_flags"):
        assert key in result
    assert isinstance(result["sentiment_reasons"], list)
    assert isinstance(result["bullish_flags"], list)
    assert isinstance(result["bearish_flags"], list)
    assert -1.0 <= result["sentiment_score"] <= 1.0
    assert 0.0 <= result["materiality_score"] <= 1.0


# ── Bullish phrase tests ──────────────────────────────────────────────────────

def test_bullish_fda_approval():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company receives FDA approval for new drug"})
    assert result["sentiment"] == "bullish"
    assert result["materiality_score"] == 0.9
    assert result["sentiment_score"] > 0


def test_bullish_raises_guidance():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "ACME Corp raises guidance for the full year"})
    assert result["sentiment"] == "bullish"
    assert result["materiality_score"] >= 0.9


def test_bullish_beats_estimates():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "XYZ beats estimates with record revenue"})
    assert result["sentiment"] == "bullish"
    assert result["materiality_score"] == 0.9


def test_bullish_acquisition():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company to be acquired by BigCorp at premium"})
    assert result["sentiment"] == "bullish"
    assert result["materiality_score"] == 0.9


def test_bullish_contract_award():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Defense company wins contract award from DOD"})
    assert result["sentiment"] == "bullish"
    assert result["materiality_score"] == 0.7


def test_bullish_upgraded_to_buy():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Analyst upgraded to buy on positive outlook"})
    assert result["sentiment"] == "bullish"


def test_bullish_flags_populated():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company beats estimates"})
    assert len(result["bullish_flags"]) > 0
    assert result["bearish_flags"] == []


# ── Bearish phrase tests ──────────────────────────────────────────────────────

def test_bearish_fda_rejection():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "FDA rejected the drug application for new therapy"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] == 0.9
    assert result["sentiment_score"] < 0


def test_bearish_lowers_guidance():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "ACME Corp lowers guidance for Q4"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] >= 0.9


def test_bearish_misses_estimates():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "XYZ misses estimates on eps miss"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] == 0.9


def test_bearish_bankruptcy():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company files for bankruptcy Chapter 11"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] == 0.9


def test_bearish_secondary_offering():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company prices secondary offering of 5M shares"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] == 0.7


def test_bearish_downgraded_to_sell():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Analyst downgraded to sell with price target cut"})
    assert result["sentiment"] == "bearish"


def test_bearish_sec_investigation():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company faces SEC investigation into accounting"})
    assert result["sentiment"] == "bearish"
    assert result["materiality_score"] == 0.7


def test_bearish_flags_populated():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company reports revenue miss and lowers guidance"})
    assert len(result["bearish_flags"]) > 0
    assert result["bullish_flags"] == []


# ── Mixed sentiment ───────────────────────────────────────────────────────────

def test_mixed_beats_then_lowers_guidance():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "XYZ beats estimates but lowers guidance for Q3"
    })
    assert result["sentiment"] == "mixed"
    assert len(result["bullish_flags"]) > 0
    assert len(result["bearish_flags"]) > 0
    assert -1.0 <= result["sentiment_score"] <= 1.0


def test_mixed_has_both_flags():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "Company beats estimates but issues secondary offering and lowers guidance"
    })
    assert result["sentiment"] == "mixed"
    assert result["bullish_flags"]
    assert result["bearish_flags"]


# ── Unknown / neutral ─────────────────────────────────────────────────────────

def test_unknown_no_signal():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({"title": "Company releases annual shareholder letter"})
    assert result["sentiment"] == "unknown"
    assert result["sentiment_score"] == 0.0
    assert "No directional sentiment rule matched" in result["sentiment_reasons"]


def test_unknown_materiality_uses_event_type_default():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "Company releases annual shareholder letter",
        "classified_event_type": "earnings",
    })
    assert result["sentiment"] == "unknown"
    # earnings fallback is 0.4
    assert result["materiality_score"] == 0.4


# ── Offering event-type prior ─────────────────────────────────────────────────

def test_offering_prior_when_no_phrase_matched():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "Company announces new leadership appointment",
        "classified_event_type": "offering",
    })
    assert result["sentiment"] == "bearish"
    assert any("offering event type prior" in r for r in result["sentiment_reasons"])


def test_offering_prior_sentinel_not_in_bearish_flags():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "Company appoints new board member",
        "classified_event_type": "offering",
    })
    assert "stock_offering_event_type" not in result["bearish_flags"]


def test_offering_phrase_overrides_prior():
    from catalysts.sentiment import analyze_catalyst_sentiment
    result = analyze_catalyst_sentiment({
        "title": "Company announces secondary offering of shares",
        "classified_event_type": "offering",
    })
    assert result["sentiment"] == "bearish"
    assert "secondary offering" in result["bearish_flags"]


# ── Scoring: sentiment-aware section E ───────────────────────────────────────

def _q(tradable=True, spread=0.05, change=2.5, vol_ratio=1.5):
    return {
        "tradable": tradable,
        "spread_percent": spread,
        "change_percent": change,
        "volume_ratio": vol_ratio,
        "bid": 10.0,
        "ask": 10.05,
        "last_trade_price": 10.02,
        "rejection_reasons": [],
    }


def _cat(sentiment, materiality, ss=0.9, event_type="earnings", title="test headline"):
    return {
        "symbol": "XYZ",
        "classified_event_type": event_type,
        "sentiment": sentiment,
        "sentiment_score": ss,
        "materiality_score": materiality,
        "sentiment_reasons": [f"{sentiment} signal"],
        "bullish_flags": ["beats estimates"] if sentiment in ("bullish", "mixed") else [],
        "bearish_flags": ["lowers guidance"] if sentiment in ("bearish", "mixed") else [],
        "title": title,
    }


def test_scoring_bullish_high_materiality_20pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bullish", 0.9)])
    assert result["components"]["catalyst_score"] == 20
    assert result["catalyst_sentiment"] == "bullish"
    assert result["catalyst_materiality_score"] == 0.9
    assert any("bullish catalyst" in r for r in result["positive_reasons"])


def test_scoring_bullish_medium_materiality_16pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bullish", 0.5)])
    assert result["components"]["catalyst_score"] == 16


def test_scoring_bullish_low_materiality_10pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bullish", 0.3)])
    assert result["components"]["catalyst_score"] == 10


def test_scoring_mixed_high_materiality_12pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("mixed", 0.9, ss=0.0)])
    assert result["components"]["catalyst_score"] == 12
    assert any("Mixed catalyst sentiment" in r for r in result["negative_reasons"])


def test_scoring_mixed_medium_materiality_10pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("mixed", 0.5, ss=0.0)])
    assert result["components"]["catalyst_score"] == 10


def test_scoring_mixed_low_materiality_8pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("mixed", 0.2, ss=0.0)])
    assert result["components"]["catalyst_score"] == 8


def test_scoring_neutral_catalyst_5pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("neutral", 0.2, ss=0.0)])
    assert result["components"]["catalyst_score"] == 5
    assert any("Weak/unknown" in r for r in result["negative_reasons"])


def test_scoring_unknown_catalyst_5pts():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("unknown", 0.1, ss=0.0)])
    assert result["components"]["catalyst_score"] == 5


def test_scoring_bearish_zero_catalyst_score_and_penalty():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bearish", 0.9, ss=-0.9)])
    assert result["components"]["catalyst_score"] == 0
    assert result["components"]["risk_penalty"] <= -15
    assert any("Bearish catalyst" in r for r in result["negative_reasons"])
    assert result["catalyst_sentiment"] == "bearish"
    assert result["catalyst_materiality_score"] == 0.9


def test_scoring_fallback_to_event_type_when_no_sentiment():
    from paper.scoring import score_candidate
    cats = [{"symbol": "XYZ", "classified_event_type": "earnings"}]
    result = score_candidate("XYZ", _q(), cats)
    assert result["components"]["catalyst_score"] == 20
    assert result["catalyst_sentiment"] is None
    assert any("high-value catalyst" in r for r in result["positive_reasons"])


def test_scoring_returns_all_sentiment_output_fields():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bullish", 0.9)])
    for field in (
        "catalyst_sentiment", "catalyst_sentiment_score", "catalyst_materiality_score",
        "catalyst_sentiment_reasons", "bullish_flags", "bearish_flags",
        "strongest_catalyst_title", "strongest_catalyst_sentiment",
    ):
        assert field in result, f"Missing field: {field}"


def test_scoring_strongest_catalyst_fields():
    from paper.scoring import score_candidate
    result = score_candidate("XYZ", _q(), [_cat("bullish", 0.9, title="beats estimates record")])
    assert result["strongest_catalyst_title"] == "beats estimates record"
    assert result["strongest_catalyst_sentiment"] == "bullish"


def test_scoring_best_catalyst_selected_by_materiality():
    from paper.scoring import score_candidate
    low = _cat("bullish", 0.4, title="low")
    high = _cat("bullish", 0.9, title="high")
    result = score_candidate("XYZ", _q(), [low, high])
    assert result["strongest_catalyst_title"] == "high"
    assert result["components"]["catalyst_score"] == 20


# ── Hard rejection gate ───────────────────────────────────────────────────────

def test_bearish_hard_reject_gate_enabled():
    """Bearish + materiality >= threshold → hard_rejection = strong_bearish_catalyst."""
    from paper.scoring import score_candidate

    class FakeSettings:
        PAPER_REJECT_STRONG_BEARISH_CATALYST = True
        PAPER_BEARISH_CATALYST_REJECT_MATERIALITY = 0.8
        PAPER_ENTRY_SCORE_THRESHOLD = 70

    scoring = score_candidate("XYZ", _q(), [_cat("bearish", 0.9, ss=-0.9)])
    assert scoring["catalyst_sentiment"] == "bearish"
    mat = scoring.get("catalyst_materiality_score") or 0.0

    hard_rejection = None
    if (
        FakeSettings.PAPER_REJECT_STRONG_BEARISH_CATALYST
        and scoring.get("catalyst_sentiment") == "bearish"
        and mat >= FakeSettings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY
    ):
        hard_rejection = "strong_bearish_catalyst"
    assert hard_rejection == "strong_bearish_catalyst"


def test_bearish_hard_reject_gate_disabled():
    """Config disabled → no hard rejection even for strong bearish."""
    from paper.scoring import score_candidate

    class FakeSettings:
        PAPER_REJECT_STRONG_BEARISH_CATALYST = False
        PAPER_BEARISH_CATALYST_REJECT_MATERIALITY = 0.8
        PAPER_ENTRY_SCORE_THRESHOLD = 70

    scoring = score_candidate("XYZ", _q(), [_cat("bearish", 0.9, ss=-0.9)])
    hard_rejection = None
    if (
        FakeSettings.PAPER_REJECT_STRONG_BEARISH_CATALYST
        and scoring.get("catalyst_sentiment") == "bearish"
        and (scoring.get("catalyst_materiality_score") or 0.0)
        >= FakeSettings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY
    ):
        hard_rejection = "strong_bearish_catalyst"
    assert hard_rejection is None


def test_bearish_hard_reject_low_materiality_no_gate():
    """Bearish but materiality below threshold → no hard rejection."""
    from paper.scoring import score_candidate

    class FakeSettings:
        PAPER_REJECT_STRONG_BEARISH_CATALYST = True
        PAPER_BEARISH_CATALYST_REJECT_MATERIALITY = 0.8
        PAPER_ENTRY_SCORE_THRESHOLD = 70

    scoring = score_candidate("XYZ", _q(), [_cat("bearish", 0.5, ss=-0.5)])
    mat = scoring.get("catalyst_materiality_score") or 0.0

    hard_rejection = None
    if (
        FakeSettings.PAPER_REJECT_STRONG_BEARISH_CATALYST
        and scoring.get("catalyst_sentiment") == "bearish"
        and mat >= FakeSettings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY
    ):
        hard_rejection = "strong_bearish_catalyst"
    assert hard_rejection is None


# ── Config ────────────────────────────────────────────────────────────────────

def test_config_has_bearish_reject_fields():
    from core.config import settings
    assert hasattr(settings, "PAPER_REJECT_STRONG_BEARISH_CATALYST")
    assert hasattr(settings, "PAPER_BEARISH_CATALYST_REJECT_MATERIALITY")
    assert isinstance(settings.PAPER_REJECT_STRONG_BEARISH_CATALYST, bool)
    assert isinstance(settings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY, float)
    assert settings.PAPER_REJECT_STRONG_BEARISH_CATALYST is True
    assert settings.PAPER_BEARISH_CATALYST_REJECT_MATERIALITY == 0.8


# ── DB schema ─────────────────────────────────────────────────────────────────

def test_db_schema_has_sentiment_columns():
    from paper.db import _CREATE_TABLES
    assert "catalyst_sentiment" in _CREATE_TABLES
    assert "catalyst_sentiment_score" in _CREATE_TABLES
    assert "catalyst_materiality_score" in _CREATE_TABLES


def test_db_schema_has_alter_table_migration():
    from paper.db import _CREATE_TABLES
    assert "ALTER TABLE paper_candidates ADD COLUMN IF NOT EXISTS catalyst_sentiment" in _CREATE_TABLES
    assert "ALTER TABLE paper_candidates ADD COLUMN IF NOT EXISTS catalyst_sentiment_score" in _CREATE_TABLES
    assert "ALTER TABLE paper_candidates ADD COLUMN IF NOT EXISTS catalyst_materiality_score" in _CREATE_TABLES


# ── Journal SQL ───────────────────────────────────────────────────────────────

def test_journal_sql_has_21_params():
    import paper.journal as _journal
    import inspect
    src = inspect.getsource(_journal.persist_tick_result)
    assert "$19" in src and "$20" in src and "$21" in src, \
        "Journal INSERT must have params $19, $20, $21 for sentiment fields"


def test_journal_sql_includes_sentiment_columns():
    import paper.journal as _journal
    import inspect
    src = inspect.getsource(_journal.persist_tick_result)
    assert "catalyst_sentiment" in src
    assert "catalyst_sentiment_score" in src
    assert "catalyst_materiality_score" in src


# ── news_collector integration ────────────────────────────────────────────────

async def test_news_collector_analyze_sentiment_false():
    """analyze_sentiment=False must not add sentiment field."""
    with patch("catalysts.news_collector.polygon_client") as mock_pc, \
         patch("catalysts.news_collector.make_redis") as mock_redis:
        mock_pc.get_ticker_news = AsyncMock(return_value=[
            {
                "title": "Company raises guidance",
                "description": "",
                "published_utc": "2025-01-01T12:00:00Z",
                "article_url": "http://x.com/1",
                "tickers": ["AAPL"],
                "id": "a1",
            }
        ])
        r = MagicMock()
        r.setex = AsyncMock()
        r.aclose = AsyncMock()
        mock_redis.return_value = r

        from catalysts.news_collector import collect_news_for_symbols
        result = await collect_news_for_symbols(
            ["AAPL"], limit_per_symbol=1, analyze_sentiment=False
        )
        for c in result["catalysts"]:
            assert "sentiment" not in c


async def test_news_collector_analyze_sentiment_true():
    """analyze_sentiment=True must add sentiment fields to each catalyst."""
    with patch("catalysts.news_collector.polygon_client") as mock_pc, \
         patch("catalysts.news_collector.make_redis") as mock_redis:
        mock_pc.get_ticker_news = AsyncMock(return_value=[
            {
                "title": "Company raises guidance for full year",
                "description": "",
                "published_utc": "2025-01-01T12:00:00Z",
                "article_url": "http://x.com/1",
                "tickers": ["AAPL"],
                "id": "a1",
            }
        ])
        r = MagicMock()
        r.setex = AsyncMock()
        r.aclose = AsyncMock()
        mock_redis.return_value = r

        from catalysts.news_collector import collect_news_for_symbols
        result = await collect_news_for_symbols(
            ["AAPL"], limit_per_symbol=1, analyze_sentiment=True
        )
        for c in result["catalysts"]:
            assert "sentiment" in c
            assert "sentiment_score" in c
            assert "materiality_score" in c
            assert c["sentiment_method"] == "rules_v1"
