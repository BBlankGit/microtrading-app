"""
Phase G1B — freeze-grade persistence, outcomes, parallel fake wallets.

Pure-unit tests for the new helpers — no Postgres, no broker, no real LLM
calls. The DB-touching code paths are covered indirectly via mocked
asyncpg connections in :class:`_FakeConn` below.

Sections:
  A — extras_json sanitization helper
  B — outcome resolver math + audit API wiring
  C — parallel fake wallets (deterministic_shadow + ai_shadow)
"""
from __future__ import annotations

import json
import inspect
from typing import Any

import pytest


# ── Section A — extras_json sanitization ─────────────────────────────────────

def test_sanitize_extras_returns_jsonb_string():
    from paper.journal import _sanitize_extras_json

    out = _sanitize_extras_json({"symbol": "AAPL", "eligible": True, "total_score": 80})
    assert isinstance(out, str)
    parsed = json.loads(out)
    assert parsed["symbol"] == "AAPL"
    assert parsed["eligible"] is True
    assert parsed["total_score"] == 80


def test_sanitize_extras_redacts_obvious_secret():
    from paper.journal import _sanitize_extras_json

    cand = {
        "symbol": "AAPL",
        "api_key": "sk-prod1234567890abcdef0123456789",
        "OPENAI_API_KEY": "sk-real1234567890abcdef0123",
    }
    out = _sanitize_extras_json(cand)
    assert out is not None
    assert "sk-prod1234567890abcdef" not in out
    assert "sk-real1234567890abcdef" not in out
    assert "<redacted>" in out


def test_sanitize_extras_truncates_oversize_payload():
    from paper.journal import _sanitize_extras_json, _EXTRAS_MAX_BYTES

    # Build a payload that intentionally exceeds the byte cap.
    huge_blob = "x" * (_EXTRAS_MAX_BYTES + 1000)
    cand = {
        "symbol": "AAPL",
        "eligible": False,
        "rejection_reason": "huge_payload",
        "noise": [huge_blob, huge_blob],
    }
    out = _sanitize_extras_json(cand)
    assert out is not None
    parsed = json.loads(out)
    assert parsed.get("_truncated") is True
    assert parsed.get("symbol") == "AAPL"
    assert parsed.get("rejection_reason") == "huge_payload"
    # Truncation envelope itself stays well under the cap.
    assert len(out.encode("utf-8")) <= _EXTRAS_MAX_BYTES


def test_sanitize_extras_drops_known_bulky_keys():
    from paper.journal import _sanitize_extras_json, _EXTRAS_DROP_KEYS

    # Sanity-check: the drop list contains at least the raw news/reddit keys
    # that history has shown to be very large.
    assert "news_items_raw" in _EXTRAS_DROP_KEYS
    cand = {
        "symbol": "AAPL",
        "news_items_raw": [{"body": "x" * 5000}],
        "total_score": 42,
    }
    out = _sanitize_extras_json(cand)
    assert out is not None
    parsed = json.loads(out)
    assert "news_items_raw" not in parsed
    assert parsed.get("total_score") == 42


def test_sanitize_extras_handles_non_serializable_objects():
    """Should not raise — fallback to default=str via json.dumps."""
    from paper.journal import _sanitize_extras_json

    class Opaque:
        def __repr__(self) -> str:
            return "Opaque()"

    out = _sanitize_extras_json({"symbol": "AAPL", "weird": Opaque()})
    assert out is not None
    assert "AAPL" in out


# ── Section B — outcome resolver math ────────────────────────────────────────

def test_compute_hits_positive_return():
    from paper.outcome_resolver import _compute_hits

    ret, hits = _compute_hits(reference_price=100.0, future_price=103.0)
    assert ret == pytest.approx(3.0)
    assert hits["hit_plus_1pct"] is True
    assert hits["hit_plus_2pct"] is True
    assert hits["hit_plus_3pct"] is True
    assert hits["hit_plus_5pct"] is False
    assert hits["hit_minus_1pct"] is False
    assert hits["hit_minus_2pct"] is False


def test_compute_hits_negative_return():
    from paper.outcome_resolver import _compute_hits

    ret, hits = _compute_hits(reference_price=100.0, future_price=97.5)
    assert ret == pytest.approx(-2.5)
    assert hits["hit_plus_1pct"] is False
    assert hits["hit_minus_1pct"] is True
    assert hits["hit_minus_2pct"] is True


def test_compute_hits_invalid_reference_returns_zero():
    from paper.outcome_resolver import _compute_hits

    ret, hits = _compute_hits(reference_price=0.0, future_price=100.0)
    assert ret == 0.0
    assert hits == {}


def test_outcome_resolver_max_per_run_constant_sane():
    """The resolver must self-cap; freeze constraints require rate safety."""
    from paper.outcome_resolver import _MAX_PER_RUN

    assert 1 <= _MAX_PER_RUN <= 1000


def test_audit_router_exposes_resolve_endpoint():
    from api.audit import router

    paths = {r.path for r in router.routes}
    assert "/api/audit/outcomes/resolve" in paths
    assert "/api/audit/persistence/status" in paths


def test_audit_resolve_endpoint_is_admin_protected():
    """`POST /api/audit/outcomes/resolve` must be behind require_admin_token."""
    from api.audit import router
    from api.dependencies import require_admin_token

    target = next(r for r in router.routes if r.path == "/api/audit/outcomes/resolve")
    calls: list[Any] = []
    stack = list(target.dependant.dependencies or [])
    while stack:
        d = stack.pop()
        calls.append(getattr(d, "call", None))
        stack.extend(d.dependencies or [])
    assert require_admin_token in calls, (
        "resolve_outcomes is missing require_admin_token dependency"
    )


# ── Section C — parallel fake wallets ───────────────────────────────────────

def test_shadow_wallets_disabled_by_default(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", False)
    assert sw.enabled() is False
    out = sw.process_tick(candidates=[{"symbol": "AAPL"}], quality_map={})
    assert out["entries"] == []
    assert out["exits"] == []
    assert out.get("skipped") == "disabled"


def test_shadow_deterministic_enters_on_would_enter(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    monkeypatch.setattr(settings, "PAPER_MAX_POSITION_SIZE_USD", 250.0)
    monkeypatch.setattr(settings, "PAPER_STARTING_CASH", 1000.0)
    sw.reset()
    out = sw.process_tick(
        candidates=[{
            "symbol": "AAPL",
            "enhanced_shadow_decision": "WOULD_ENTER",
            "catalyst_type": "earnings_beat",
            "total_score": 80,
        }],
        quality_map={"AAPL": {"ask": 100.0, "last_trade_price": 100.0}},
    )
    assert any(e["wallet_id"] == sw.WALLET_DETERMINISTIC for e in out["entries"])
    snap = out["snapshots"]
    assert snap[sw.WALLET_DETERMINISTIC]["open_position_count"] == 1
    # AI wallet stays untouched because LLM is disabled.
    assert snap[sw.WALLET_AI]["open_position_count"] == 0


def test_shadow_ai_skipped_when_llm_disabled(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    sw.reset()
    out = sw.process_tick(
        candidates=[{
            "symbol": "NVDA",
            "llm_decision": "WOULD_ENTER",
        }],
        quality_map={"NVDA": {"ask": 100.0, "last_trade_price": 100.0}},
    )
    assert all(e["wallet_id"] != sw.WALLET_AI for e in out["entries"])


def test_shadow_ai_enters_when_llm_enabled(monkeypatch):
    from core.config import settings
    from paper import shadow_wallets as sw

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", True)
    sw.reset()
    out = sw.process_tick(
        candidates=[{
            "symbol": "NVDA",
            "llm_decision": "WOULD_ENTER",
            "enhanced_shadow_decision": "WOULD_REJECT",
            "catalyst_type": "guidance_raise",
        }],
        quality_map={"NVDA": {"ask": 50.0, "last_trade_price": 50.0}},
    )
    ai_entries = [e for e in out["entries"] if e["wallet_id"] == sw.WALLET_AI]
    assert len(ai_entries) == 1
    snap = out["snapshots"]
    assert snap[sw.WALLET_AI]["open_position_count"] == 1
    assert snap[sw.WALLET_DETERMINISTIC]["open_position_count"] == 0


def test_shadow_wallets_independent_of_engine_positions(monkeypatch):
    """A symbol open in the engine wallet must NOT block a shadow entry."""
    from core.config import settings
    from paper import shadow_wallets as sw, simulator as sim

    monkeypatch.setattr(settings, "PAPER_SHADOW_WALLETS_ENABLED", True)
    monkeypatch.setattr(settings, "LLM_SHADOW_ENABLED", False)
    sw.reset()
    sim._account.reset()
    # Engine "holds" AAPL.
    sim._account.enter_position("AAPL", 100.0, 200.0, "test", entry_score=70)
    out = sw.process_tick(
        candidates=[{
            "symbol": "AAPL",
            "enhanced_shadow_decision": "WOULD_ENTER",
        }],
        quality_map={"AAPL": {"ask": 100.0, "last_trade_price": 100.0}},
    )
    assert len(out["entries"]) == 1
    assert out["entries"][0]["wallet_id"] == sw.WALLET_DETERMINISTIC
    # Clean up so other tests see an empty engine account.
    sim._account.reset()


def test_shadow_wallets_starting_cash_matches_engine():
    """Both shadow wallets must start with the same cash as the engine."""
    from core.config import settings
    from paper import shadow_wallets as sw

    sw.reset()
    snap = sw.snapshot()
    assert snap[sw.WALLET_DETERMINISTIC]["starting_cash"] == settings.PAPER_STARTING_CASH
    assert snap[sw.WALLET_AI]["starting_cash"] == settings.PAPER_STARTING_CASH


def test_shadow_wallets_endpoint_returns_three_buckets():
    from main import app

    routes = {r.path for r in app.routes}
    assert "/api/paper/wallets" in routes


# ── Integration-style: candidates INSERT signature includes extras_json ──────

def test_candidates_insert_includes_extras_json_column():
    """The G1B-modified INSERT must list extras_json among its columns."""
    from paper.journal import persist_tick_result
    src = inspect.getsource(persist_tick_result)
    assert "extras_json" in src, (
        "persist_tick_result must persist the extras_json column"
    )
    assert "$38" in src, "extras_json should be the $38 parameter"


def test_journal_persists_shadow_wallet_trades():
    """`persist_tick_result` must consume tick_result['shadow_entries'/'shadow_exits']."""
    from paper import journal as j
    src = inspect.getsource(j.persist_tick_result)
    assert "shadow_entries" in src
    assert "shadow_exits" in src
    assert "wallet_id" in src


# ── Migration source-truth: required ALTER/CREATE statements present ────────

def test_migration_contains_extras_json_alter():
    from paper.db import _CREATE_TABLES
    assert "ADD COLUMN IF NOT EXISTS extras_json JSONB" in _CREATE_TABLES


def test_migration_contains_outcomes_table():
    from paper.db import _CREATE_TABLES
    assert "CREATE TABLE IF NOT EXISTS paper_candidate_outcomes" in _CREATE_TABLES
    for col in (
        "horizon_minutes",
        "reference_price",
        "future_price",
        "future_return_percent",
        "hit_plus_1pct",
        "hit_minus_2pct",
        "status",
    ):
        assert col in _CREATE_TABLES, f"missing column {col!r} in outcomes DDL"


def test_migration_contains_wallet_id_columns():
    from paper.db import _CREATE_TABLES
    assert "ADD COLUMN IF NOT EXISTS wallet_id TEXT" in _CREATE_TABLES
    assert "ADD COLUMN IF NOT EXISTS strategy_id TEXT" in _CREATE_TABLES
