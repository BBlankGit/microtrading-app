"""
Phase 2S tests — persistent daily paper session restore after restart.

No broker. No live trading. No real orders. No real-money execution.
Tests cover: Redis restore (valid/stale/missing/error), DB restore
(empty/closed/open/cash), restore_session orchestration (redis-preferred,
fallback-to-db, no-source).
"""

import json
import unittest
from datetime import datetime, timezone, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

from paper.models import ClosedTrade, Position

TODAY = "2026-06-09"
YESTERDAY = "2026-06-08"
STARTING_CASH = 1000.0


def _redis_snapshot(ny_today: str = TODAY, cash: float = 950.0, trades=None, positions=None) -> str:
    """Return a serialised Redis snapshot for the given date (Phase-2U v2 format)."""
    return json.dumps({
        # Phase-2U integrity metadata
        "schema_version": 2,
        "namespace": "paper:prod",
        "saved_after_journal": True,
        "saved_at": "2026-06-10T14:00:00+00:00",
        "tick_id": None,
        # Account state
        "cash": cash,
        "starting_cash": STARTING_CASH,
        "positions": positions or {},
        "trades": trades or [],
        "daily_trade_count": len(trades or []),
        "daily_date": ny_today,
        "daily_baseline_date": ny_today,
        "daily_start_equity": STARTING_CASH,
        "last_prices": {"AAPL": 175.0},
    })


def _make_closed_row(symbol="AAPL", pnl=10.0, shares=1.0, cost_basis=150.0,
                     exit_price=160.0, position_id="abc123"):
    """Simulate an asyncpg Record-like dict for a closed trade row."""
    now = datetime.now(timezone.utc)
    row = {
        "symbol": symbol,
        "entry_price": cost_basis / shares,
        "exit_price": exit_price,
        "shares": shares,
        "cost_basis": cost_basis,
        "pnl": pnl,
        "pnl_percent": round(pnl / cost_basis * 100, 4),
        "exit_reason": "take_profit",
        "catalyst_type": "earnings",
        "total_score": 75,
        "opened_at": now - timedelta(minutes=20),
        "closed_at": now - timedelta(minutes=5),
        "entry_mode": "catalyst",
        "position_id": position_id,
    }
    return row


def _make_open_row(symbol="MSFT", shares=2.0, cost_basis=200.0,
                   entry_price=100.0, position_id="def456"):
    now = datetime.now(timezone.utc)
    return {
        "symbol": symbol,
        "entry_price": entry_price,
        "shares": shares,
        "cost_basis": cost_basis,
        "catalyst_type": "momentum",
        "total_score": 80,
        "opened_at": now - timedelta(minutes=10),
        "entry_mode": "catalyst",
        "position_id": position_id,
    }


def _make_async_pool(closed_rows=None, open_rows=None, null_pid_count=0,
                     prior_day_count=0):
    """Build a mock asyncpg pool whose conn.fetch alternates results.

    null_pid_count: first fetchval result (NULL position_id open entries skipped).
    prior_day_count: second fetchval result (prior-day open entries skipped).
    Both default to 0 — no warnings generated.
    """
    closed_rows = closed_rows or []
    open_rows = open_rows or []
    conn = MagicMock()
    fetch_results = [closed_rows, open_rows]
    fetch_count = {"n": 0}
    fetchval_results = [null_pid_count, prior_day_count]
    fetchval_count = {"n": 0}

    async def fetch(*args, **kwargs):
        idx = fetch_count["n"]
        fetch_count["n"] += 1
        return fetch_results[idx] if idx < len(fetch_results) else []

    async def fetchval(*args, **kwargs):
        idx = fetchval_count["n"]
        fetchval_count["n"] += 1
        return fetchval_results[idx] if idx < len(fetchval_results) else 0

    conn.fetch = fetch
    conn.fetchval = fetchval

    pool = MagicMock()
    pool.acquire = MagicMock()
    pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn)
    pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return pool


class TestTryRedisRestore(unittest.IsolatedAsyncioTestCase):

    async def test_valid_snapshot_for_today_returns_dict(self):
        """Redis has a valid snapshot for today → returns snapshot dict."""
        from paper.session_restore import try_redis_restore

        raw = _redis_snapshot(ny_today=TODAY)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=raw)
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await try_redis_restore(TODAY)

        self.assertIsNotNone(result)
        self.assertEqual(result["daily_baseline_date"], TODAY)
        self.assertAlmostEqual(result["cash"], 950.0)

    async def test_stale_date_returns_none(self):
        """Redis snapshot is for yesterday → returns None (stale)."""
        from paper.session_restore import try_redis_restore

        raw = _redis_snapshot(ny_today=YESTERDAY)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=raw)
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await try_redis_restore(TODAY)

        self.assertIsNone(result)

    async def test_missing_key_returns_none(self):
        """Redis has no paper:state key → returns None."""
        from paper.session_restore import try_redis_restore

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=None)
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await try_redis_restore(TODAY)

        self.assertIsNone(result)

    async def test_redis_error_returns_none(self):
        """Redis raises an exception → returns None, does not raise."""
        from paper.session_restore import try_redis_restore

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await try_redis_restore(TODAY)

        self.assertIsNone(result)


class TestTryDbRestore(unittest.IsolatedAsyncioTestCase):

    async def test_no_pool_returns_none(self):
        """No DB pool → returns None."""
        from paper.session_restore import try_db_restore

        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=None)
            result = await try_db_restore(TODAY, STARTING_CASH)

        self.assertIsNone(result)

    async def test_empty_db_returns_blank_result(self):
        """DB has no trades today → returns dict with empty trades/positions."""
        from paper.session_restore import try_db_restore

        pool = _make_async_pool(closed_rows=[], open_rows=[])
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY, STARTING_CASH)

        self.assertIsNotNone(result)
        self.assertEqual(result["trades"], [])
        self.assertEqual(result["positions"], {})
        self.assertAlmostEqual(result["cash"], STARTING_CASH)

    async def test_closed_trades_reconstructed(self):
        """DB closed trade rows → ClosedTrade list with correct fields."""
        from paper.session_restore import try_db_restore

        row = _make_closed_row(symbol="AAPL", pnl=10.0, shares=1.0,
                                cost_basis=150.0, exit_price=160.0, position_id="abc123")
        pool = _make_async_pool(closed_rows=[row], open_rows=[])
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY, STARTING_CASH)

        self.assertEqual(len(result["trades"]), 1)
        trade = result["trades"][0]
        self.assertIsInstance(trade, ClosedTrade)
        self.assertEqual(trade.symbol, "AAPL")
        self.assertAlmostEqual(trade.pnl, 10.0)
        self.assertEqual(trade.position_id, "abc123")
        self.assertEqual(trade.exit_reason, "take_profit")

    async def test_open_positions_reconstructed(self):
        """DB open entry rows (no matching exit) → Position dict with correct fields."""
        from paper.session_restore import try_db_restore

        row = _make_open_row(symbol="MSFT", shares=2.0, cost_basis=200.0,
                              entry_price=100.0, position_id="def456")
        pool = _make_async_pool(closed_rows=[], open_rows=[row])
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY, STARTING_CASH)

        self.assertEqual(len(result["positions"]), 1)
        pos = result["positions"]["MSFT"]
        self.assertIsInstance(pos, Position)
        self.assertEqual(pos.symbol, "MSFT")
        self.assertAlmostEqual(pos.cost_basis, 200.0)
        self.assertEqual(pos.position_id, "def456")

    async def test_cash_estimation_from_db(self):
        """Cash = starting_cash + realized_pnl - open_cost_basis."""
        from paper.session_restore import try_db_restore

        closed_row = _make_closed_row(symbol="AAPL", pnl=20.0, cost_basis=150.0,
                                       exit_price=170.0, shares=1.0, position_id="p1")
        open_row = _make_open_row(symbol="MSFT", cost_basis=100.0, shares=1.0,
                                   entry_price=100.0, position_id="p2")
        pool = _make_async_pool(closed_rows=[closed_row], open_rows=[open_row])
        with patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await try_db_restore(TODAY, STARTING_CASH)

        # cash = 1000 + 20 - 100 = 920
        self.assertAlmostEqual(result["cash"], 920.0, places=2)


class TestRestoreSession(unittest.IsolatedAsyncioTestCase):

    async def test_redis_preferred_when_valid(self):
        """restore_session returns source=redis when Redis snapshot is valid."""
        from paper.session_restore import restore_session

        raw = _redis_snapshot(ny_today=TODAY, cash=980.0,
                              trades=[{"pnl": 5.0}], positions={})
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=raw)
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis):
            result = await restore_session(TODAY, STARTING_CASH)

        self.assertEqual(result["source"], "redis")
        self.assertIsNotNone(result["snapshot"])
        self.assertEqual(result["closed_trades_count"], 1)
        self.assertAlmostEqual(result["daily_realized_pnl"], 5.0)

    async def test_fallback_to_db_when_redis_stale(self):
        """restore_session falls back to DB when Redis is stale."""
        from paper.session_restore import restore_session

        stale_raw = _redis_snapshot(ny_today=YESTERDAY)
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value=stale_raw)
        mock_redis.aclose = AsyncMock()

        closed_row = _make_closed_row(symbol="NVDA", pnl=15.0, position_id="xx1")
        pool = _make_async_pool(closed_rows=[closed_row], open_rows=[])

        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=pool)
            result = await restore_session(TODAY, STARTING_CASH)

        self.assertEqual(result["source"], "db")
        self.assertEqual(result["closed_trades_count"], 1)
        self.assertAlmostEqual(result["daily_realized_pnl"], 15.0)
        self.assertEqual(result["warning"], "cash_estimated_from_db")

    async def test_no_source_when_both_unavailable(self):
        """restore_session returns source=none when Redis and DB both fail."""
        from paper.session_restore import restore_session

        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(side_effect=ConnectionError("down"))
        mock_redis.aclose = AsyncMock()

        with patch("paper.session_restore.make_redis", return_value=mock_redis), \
             patch("paper.session_restore._db") as mock_db:
            mock_db.get_pool = AsyncMock(return_value=None)
            result = await restore_session(TODAY, STARTING_CASH)

        self.assertEqual(result["source"], "none")
        self.assertEqual(result["closed_trades_count"], 0)
        self.assertIsNone(result["warning"])


if __name__ == "__main__":
    unittest.main()
