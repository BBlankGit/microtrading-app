"""
Phase G1B Part B — paper_candidate_outcomes resolver.

For every persisted paper candidate we queue forward-return outcome rows at
fixed horizons (5/10/15/30/60 minutes). This module resolves the pending
rows by looking up the symbol's current cached price and computing the
future return and hit flags.

Design constraints (from the G1B spec):
  - Rate-safe: a single invocation processes at most _MAX_PER_RUN rows.
  - Must NOT block the paper tick loop — runs in its own admin-triggered
    endpoint or background task.
  - Must NOT replay 5,000 symbols — only candidates that were actually
    persisted are eligible.
  - Read-only with respect to market data: pulls from the existing Redis
    cache (paper/marketdata_adapter style). No new provider calls.
  - Fake-money only. No broker. No real orders.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from paper import db as _db

logger = logging.getLogger(__name__)

# Per-run cap. Tunable later via runtime_config if needed.
_MAX_PER_RUN = 200

# Hit thresholds (percent). Must match column names in the schema.
_HIT_POSITIVE = (1.0, 2.0, 3.0, 5.0)
_HIT_NEGATIVE = (1.0, 2.0)

# Surfaced via /api/audit/persistence/status so dashboards can show the
# resolver heartbeat without going to the DB.
_LAST_RUN: dict = {"at": None, "summary": None}

# Caveat surfaced via persistence_status() for Part G of the H1 review:
# the cache-only resolver cannot observe interval high/low between the
# reference tick and the horizon.
_HIGH_LOW_CAVEAT = (
    "Interval high/low unavailable in current resolver; future_price is "
    "cache price at resolution time."
)


async def _read_cached_last_price(symbol: str) -> float | None:
    """Pull the most recent cached last_price for `symbol`, or None."""
    try:
        from marketdata import cache as _cache
        payload = await _cache.read_symbol(symbol)
    except Exception as exc:
        logger.debug("outcome_resolver: cache read failed for %s: %s", symbol, exc)
        return None
    if not payload:
        return None
    if payload.get("raw_status") != "ok":
        return None
    price = payload.get("last_price")
    if price is None:
        price = payload.get("close")
    try:
        return float(price) if price is not None else None
    except (TypeError, ValueError):
        return None


def _compute_hits(
    reference_price: float, future_price: float
) -> tuple[float, dict[str, bool]]:
    """Return (future_return_percent, hit_flags_dict)."""
    if reference_price <= 0:
        return 0.0, {}
    ret = (future_price - reference_price) / reference_price * 100.0
    hits: dict[str, bool] = {}
    for pct in _HIT_POSITIVE:
        col = f"hit_plus_{int(pct)}pct"
        hits[col] = ret >= pct
    for pct in _HIT_NEGATIVE:
        col = f"hit_minus_{int(pct)}pct"
        hits[col] = ret <= -pct
    return ret, hits


async def resolve_pending(max_rows: int = _MAX_PER_RUN) -> dict:
    """
    Resolve up to `max_rows` pending outcome rows whose horizon has elapsed.

    Returns a summary dict suitable for the admin endpoint response.
    Never raises — falls back to {"ok": False, "reason": ...} on any error.
    """
    max_rows = max(1, min(int(max_rows), _MAX_PER_RUN))
    pool = await _db.get_pool()
    if pool is None:
        return {"ok": False, "skipped": True, "reason": "no pool"}

    now = datetime.now(timezone.utc)
    summary = {
        "ok": True,
        "scanned": 0,
        "resolved": 0,
        "missing_data": 0,
        "errored": 0,
        "max_rows": max_rows,
        "now": now.isoformat(),
    }

    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, symbol, reference_price, reference_at, horizon_minutes
                  FROM paper_candidate_outcomes
                 WHERE status = 'pending'
                   AND reference_at IS NOT NULL
                   AND reference_at + (horizon_minutes::text || ' minutes')::interval <= $1
                 ORDER BY id ASC
                 LIMIT $2
                """,
                now,
                max_rows,
            )
            summary["scanned"] = len(rows)

            for row in rows:
                row_id = row["id"]
                symbol = row["symbol"]
                ref_price = row["reference_price"]
                ref_at = row["reference_at"]
                try:
                    future_price = await _read_cached_last_price(symbol)
                    if future_price is None or ref_price is None or float(ref_price) <= 0:
                        await conn.execute(
                            """
                            UPDATE paper_candidate_outcomes
                               SET status = 'missing_data',
                                   resolved_at = $1,
                                   error = $2,
                                   source = $3
                             WHERE id = $4
                            """,
                            now,
                            "no cached price" if future_price is None else "invalid reference_price",
                            "missing_cache",
                            row_id,
                        )
                        summary["missing_data"] += 1
                        continue

                    fr, hits = _compute_hits(float(ref_price), float(future_price))
                    # NOTE: interval high/low is not safely available from the
                    # cache (which only stores a single last_price point), so
                    # max_high_return_percent and max_low_return_percent stay
                    # NULL. The resolver does not synthesize them — clients
                    # should treat NULL as "interval high/low unavailable".
                    await conn.execute(
                        """
                        UPDATE paper_candidate_outcomes
                           SET status = 'resolved',
                               resolved_at = $1,
                               future_price = $2,
                               future_at = $1,
                               future_return_percent = $3,
                               hit_plus_1pct = $4,
                               hit_plus_2pct = $5,
                               hit_plus_3pct = $6,
                               hit_plus_5pct = $7,
                               hit_minus_1pct = $8,
                               hit_minus_2pct = $9,
                               source = $10
                         WHERE id = $11
                        """,
                        now,
                        float(future_price),
                        fr,
                        hits.get("hit_plus_1pct"),
                        hits.get("hit_plus_2pct"),
                        hits.get("hit_plus_3pct"),
                        hits.get("hit_plus_5pct"),
                        hits.get("hit_minus_1pct"),
                        hits.get("hit_minus_2pct"),
                        "marketdata_cache",
                        row_id,
                    )
                    summary["resolved"] += 1
                except Exception as exc:
                    logger.warning(
                        "outcome_resolver: row %s (%s) failed: %s", row_id, symbol, exc
                    )
                    try:
                        await conn.execute(
                            """
                            UPDATE paper_candidate_outcomes
                               SET status = 'error',
                                   resolved_at = $1,
                                   error = $2,
                                   source = $3
                             WHERE id = $4
                            """,
                            now,
                            f"{type(exc).__name__}: {exc}"[:512],
                            "error",
                            row_id,
                        )
                    except Exception:
                        pass
                    summary["errored"] += 1

        _LAST_RUN["at"] = now.isoformat()
        _LAST_RUN["summary"] = dict(summary)
        return summary
    except Exception as exc:
        logger.warning("outcome_resolver: resolve_pending failed: %s", exc)
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}


def last_run() -> dict:
    """Public accessor for the last resolver-run heartbeat."""
    return dict(_LAST_RUN)


async def persistence_status() -> dict:
    """Counts for the /api/audit/persistence/status endpoint."""
    pool = await _db.get_pool()
    if pool is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no pool",
            "high_low_caveat": _HIGH_LOW_CAVEAT,
            "resolver_last_run": last_run(),
        }
    try:
        async with pool.acquire() as conn:
            cand_total = await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates"
            )
            cand_with_extras = await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL"
            )
            outcome_counts = await conn.fetch(
                """
                SELECT status, COUNT(*) AS n
                  FROM paper_candidate_outcomes
                 GROUP BY status
                """
            )
            outcomes_by_status = {r["status"]: int(r["n"]) for r in outcome_counts}
            by_horizon_rows = await conn.fetch(
                """
                SELECT horizon_minutes, status, COUNT(*) AS n
                  FROM paper_candidate_outcomes
                 GROUP BY horizon_minutes, status
                 ORDER BY horizon_minutes
                """
            )
            by_horizon: dict[str, dict[str, int]] = {}
            for r in by_horizon_rows:
                bucket = by_horizon.setdefault(str(int(r["horizon_minutes"])), {})
                bucket[r["status"]] = int(r["n"])
            by_source_rows = await conn.fetch(
                """
                SELECT COALESCE(source, 'unknown') AS source, COUNT(*) AS n
                  FROM paper_candidate_outcomes
                 GROUP BY source
                """
            )
            by_source = {r["source"]: int(r["n"]) for r in by_source_rows}
            recent_extras_examples = await conn.fetch(
                """
                SELECT id, symbol, created_at,
                       (extras_json IS NOT NULL) AS has_extras
                  FROM paper_candidates
                 ORDER BY id DESC
                 LIMIT 5
                """
            )
        total = int(cand_total or 0)
        with_extras = int(cand_with_extras or 0)
        coverage_percent = round(with_extras / total * 100.0, 2) if total else 0.0
        return {
            "ok": True,
            "candidates_total": total,
            "candidates_with_extras_json": with_extras,
            "extras_json_coverage_percent": coverage_percent,
            "outcomes_by_status": outcomes_by_status,
            "outcomes_by_horizon": by_horizon,
            "outcomes_by_source": by_source,
            "recent_extras_examples": [
                {
                    "id": int(r["id"]),
                    "symbol": r["symbol"],
                    "has_extras": bool(r["has_extras"]),
                    "created_at": r["created_at"].isoformat() if r["created_at"] else None,
                }
                for r in recent_extras_examples
            ],
            "high_low_caveat": _HIGH_LOW_CAVEAT,
            "resolver_last_run": last_run(),
        }
    except Exception as exc:
        logger.warning("outcome_resolver: persistence_status failed: %s", exc)
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
            "high_low_caveat": _HIGH_LOW_CAVEAT,
            "resolver_last_run": last_run(),
        }
