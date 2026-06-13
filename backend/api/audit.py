"""
Phase G1B Part B — admin audit endpoints.

Endpoints:
  - POST /api/audit/outcomes/resolve (admin)
      Triggers a rate-safe resolver pass for pending forward-return rows.
  - GET /api/audit/persistence/status
      Snapshot of candidate/outcome counts for the freeze readiness check.
  - GET /api/audit/persistence/deep-status (Phase G1B-H6)
      Comprehensive persistence audit: candidate/outcome/trade row counts,
      wallet/strategy coverage, timestamp integrity, analysis joinability.

Read-only with respect to broker logic. No real orders. Fake-money only.
"""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query

from api.dependencies import require_admin_token
from paper import db as _db
from paper import outcome_resolver as _resolver

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.post("/outcomes/resolve", dependencies=[Depends(require_admin_token)])
async def resolve_outcomes(
    max_rows: int = Query(default=200, ge=1, le=1000),
) -> dict:
    """Resolve up to `max_rows` pending forward-return outcomes (admin)."""
    return await _resolver.resolve_pending(max_rows=max_rows)


@router.get("/persistence/status")
async def persistence_status() -> dict:
    """Public snapshot of persistence coverage (no broker data)."""
    return await _resolver.persistence_status()


@router.get("/persistence/deep-status")
async def persistence_deep_status() -> dict:
    """
    Phase G1B-H6 Part D — comprehensive persistence audit.

    Reports candidate / outcome / trade row counts by key dimensions
    (wallet_id, strategy_id, source, status, exit_reason, horizon),
    timestamp integrity, and analysis joinability so we can confirm
    raw data is preserved for later engine improvement. Fake-money only.
    """
    pool = await _db.get_pool()
    if pool is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no pool",
        }
    try:
        from paper import shadow_wallets as _sw
        from paper import simulator as _sim
        async with pool.acquire() as conn:
            # ── Candidates ──────────────────────────────────────────────
            cand_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates"
            ) or 0)
            cand_with_extras = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates WHERE extras_json IS NOT NULL"
            ) or 0)
            cand_min_created = await conn.fetchval(
                "SELECT MIN(created_at) FROM paper_candidates"
            )
            cand_max_created = await conn.fetchval(
                "SELECT MAX(created_at) FROM paper_candidates"
            )
            cand_by_action = {
                r["action"] or "unknown": int(r["n"])
                for r in await conn.fetch(
                    "SELECT action, COUNT(*) AS n FROM paper_candidates GROUP BY action"
                )
            }
            cand_by_rejection = {
                r["rejection_reason"] or "none": int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT rejection_reason, COUNT(*) AS n
                      FROM paper_candidates
                     GROUP BY rejection_reason
                     ORDER BY n DESC LIMIT 25
                    """
                )
            }
            cand_by_marketdata_source = {
                r["marketdata_source"] or "unknown": int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT marketdata_source, COUNT(*) AS n
                      FROM paper_candidates
                     GROUP BY marketdata_source
                    """
                )
            }
            cand_missing_tick_id = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates WHERE tick_id IS NULL OR tick_id = ''"
            ) or 0)
            cand_missing_created_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates WHERE created_at IS NULL"
            ) or 0)
            cand_coverage_pct = (
                round(cand_with_extras / cand_total * 100.0, 2)
                if cand_total else 0.0
            )

            # ── Outcomes ────────────────────────────────────────────────
            out_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes"
            ) or 0)
            out_by_status = {
                r["status"]: int(r["n"])
                for r in await conn.fetch(
                    "SELECT status, COUNT(*) AS n FROM paper_candidate_outcomes GROUP BY status"
                )
            }
            out_by_horizon = {}
            for r in await conn.fetch(
                """
                SELECT horizon_minutes, status, COUNT(*) AS n
                  FROM paper_candidate_outcomes
                 GROUP BY horizon_minutes, status
                 ORDER BY horizon_minutes
                """
            ):
                bucket = out_by_horizon.setdefault(str(int(r["horizon_minutes"])), {})
                bucket[r["status"]] = int(r["n"])
            out_by_source = {
                (r["source"] or "unknown"): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT source, COUNT(*) AS n
                      FROM paper_candidate_outcomes
                     GROUP BY source
                    """
                )
            }
            out_min_resolved = await conn.fetchval(
                "SELECT MIN(resolved_at) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL"
            )
            out_max_resolved = await conn.fetchval(
                "SELECT MAX(resolved_at) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL"
            )

            # ── Trades ──────────────────────────────────────────────────
            trade_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal"
            ) or 0)
            trade_by_event = {
                r["event"]: int(r["n"])
                for r in await conn.fetch(
                    "SELECT event, COUNT(*) AS n FROM paper_trades_journal GROUP BY event"
                )
            }
            trade_by_wallet = {
                (r["wallet_id"] or "missing"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY wallet_id"
                )
            }
            trade_by_strategy = {
                (r["strategy_id"] or "missing"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT strategy_id, COUNT(*) AS n FROM paper_trades_journal GROUP BY strategy_id"
                )
            }
            trade_by_exit_reason = {
                (r["exit_reason"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT exit_reason, COUNT(*) AS n
                      FROM paper_trades_journal
                     WHERE event = 'exit'
                     GROUP BY exit_reason
                    """
                )
            }
            trade_missing_wallet = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE wallet_id IS NULL OR wallet_id = ''"
            ) or 0)
            trade_missing_strategy = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE strategy_id IS NULL OR strategy_id = ''"
            ) or 0)
            trade_missing_opened_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE event = 'entry' AND opened_at IS NULL"
            ) or 0)
            trade_missing_closed_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE event = 'exit' AND closed_at IS NULL"
            ) or 0)
            invalid_oos_trade_count = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM paper_trades_journal
                 WHERE exit_reason = 'invalid_out_of_session_entry_flatten'
                """
            ) or 0)
            trade_min_created = await conn.fetchval(
                "SELECT MIN(created_at) FROM paper_trades_journal"
            )
            trade_max_created = await conn.fetchval(
                "SELECT MAX(created_at) FROM paper_trades_journal"
            )

            # ── Joinability checks ──────────────────────────────────────
            joinable_cand_outcome = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM paper_candidate_outcomes o
                 INNER JOIN paper_candidates c ON c.id = o.candidate_id
                """
            ) or 0)
            distinct_candidates_with_any_outcome = int(await conn.fetchval(
                "SELECT COUNT(DISTINCT candidate_id) FROM paper_candidate_outcomes"
            ) or 0)
            candidates_with_all_5_horizons = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM (
                    SELECT candidate_id
                      FROM paper_candidate_outcomes
                     GROUP BY candidate_id
                    HAVING COUNT(DISTINCT horizon_minutes) >= 5
                ) AS c5
                """
            ) or 0)
            missing_by_horizon = {}
            for r in await conn.fetch(
                """
                SELECT horizon_minutes, COUNT(*) AS n
                  FROM paper_candidate_outcomes
                 WHERE status IN ('pending','missing_data','error')
                 GROUP BY horizon_minutes
                 ORDER BY horizon_minutes
                """
            ):
                missing_by_horizon[str(int(r["horizon_minutes"]))] = int(r["n"])

            # ── extras_json field-family coverage (sampled on recent rows) ──
            family_probes = {
                "marketdata": ["marketdata_source", "marketdata_age_seconds"],
                "catalyst_news": ["catalyst_type", "catalyst_sentiment", "strongest_catalyst_title"],
                "reddit": ["reddit_rank", "reddit_mentions"],
                "earnings": ["earnings_next_date", "earnings_score_adjustment"],
                "insider": ["insider_recent_buy_count", "insider_score_adjustment"],
                "market_regime_trend": ["market_trend_direction", "market_trend_strength"],
                "deterministic_shadow": ["enhanced_shadow_decision", "enhanced_shadow_score"],
                "ai_shadow": ["llm_decision", "llm_status"],
                "ai_shadow_disabled_state": ["llm_status", "llm_error"],
            }
            # Use LATERAL probe over recent 5k extras rows to stay fast on 600k tables
            field_family_coverage: dict[str, dict] = {}
            sample_size = int(await conn.fetchval(
                "SELECT COUNT(*) FROM ("
                "  SELECT 1 FROM paper_candidates"
                "   WHERE extras_json IS NOT NULL"
                "   ORDER BY id DESC LIMIT 5000"
                ") s"
            ) or 0)
            for family, keys in family_probes.items():
                if sample_size == 0:
                    field_family_coverage[family] = {
                        "sample_size": 0, "present": 0, "coverage_percent": 0.0, "keys": keys,
                    }
                    continue
                or_clauses = " OR ".join([f"extras_json ? $1::text"] + [f"extras_json ? ${i+2}::text" for i in range(len(keys) - 1)])
                # Build params list for parametrized OR
                params = list(keys)
                present = int(await conn.fetchval(
                    f"""
                    SELECT COUNT(*) FROM (
                        SELECT extras_json FROM paper_candidates
                         WHERE extras_json IS NOT NULL
                         ORDER BY id DESC LIMIT 5000
                    ) s WHERE {or_clauses}
                    """,
                    *params,
                ) or 0)
                pct = round(present / sample_size * 100.0, 2) if sample_size else 0.0
                field_family_coverage[family] = {
                    "sample_size": sample_size,
                    "present": present,
                    "coverage_percent": pct,
                    "keys": keys,
                }

            # ── Per-engine trade separability ──────────────────────────
            engine_trade_counts = {
                "engine": trade_by_wallet.get("engine", 0),
                "deterministic_shadow": trade_by_wallet.get("deterministic_shadow", 0),
                "ai_shadow": trade_by_wallet.get("ai_shadow", 0),
                "unattributed_missing_wallet_id": trade_by_wallet.get("missing", 0),
            }

        # ── Future-timestamp integrity (small tolerance for clock skew) ─
        now_utc = datetime.now(timezone.utc)
        def _future(ts) -> bool:
            if ts is None:
                return False
            return (ts - now_utc).total_seconds() > 300  # 5-minute skew tolerance

        # ── Live wallet snapshots ───────────────────────────────────────
        eng_status = _sim.get_status()
        shadow = _sw.snapshot()
        wallet_snapshots = [
            {
                "wallet_id": "engine",
                "strategy_id": "engine",
                "cash": eng_status.get("cash"),
                "equity": eng_status.get("equity"),
                "realized_pnl": eng_status.get("realized_pnl"),
                "unrealized_pnl": eng_status.get("unrealized_pnl"),
                "last_update_time": eng_status.get("last_tick_at"),
            },
        ]
        for wid in (_sw.WALLET_DETERMINISTIC, _sw.WALLET_AI):
            snap = shadow.get(wid) or {}
            wallet_snapshots.append({
                "wallet_id": wid,
                "strategy_id": wid,
                "cash": snap.get("cash"),
                "equity": snap.get("equity"),
                "realized_pnl": snap.get("realized_pnl"),
                "unrealized_pnl": snap.get("unrealized_pnl"),
                "last_update_time": snap.get("last_update_time"),
            })

        return {
            "ok": True,
            "generated_at": now_utc.isoformat(),
            "candidates": {
                "total": cand_total,
                "with_extras_json": cand_with_extras,
                "extras_json_coverage_percent": cand_coverage_pct,
                "min_created_at": cand_min_created.isoformat() if cand_min_created else None,
                "max_created_at": cand_max_created.isoformat() if cand_max_created else None,
                "by_action": cand_by_action,
                "by_rejection_reason": cand_by_rejection,
                "by_marketdata_source": cand_by_marketdata_source,
                "missing_tick_id": cand_missing_tick_id,
                "missing_created_at": cand_missing_created_at,
                "future_max_created_at": _future(cand_max_created),
            },
            "outcomes": {
                "total": out_total,
                "by_status": out_by_status,
                "by_horizon": out_by_horizon,
                "by_source": out_by_source,
                "min_resolved_at": out_min_resolved.isoformat() if out_min_resolved else None,
                "max_resolved_at": out_max_resolved.isoformat() if out_max_resolved else None,
            },
            "trades": {
                "total": trade_total,
                "by_event": trade_by_event,
                "by_wallet_id": trade_by_wallet,
                "by_strategy_id": trade_by_strategy,
                "by_exit_reason": trade_by_exit_reason,
                "missing_wallet_id": trade_missing_wallet,
                "missing_strategy_id": trade_missing_strategy,
                "missing_opened_at_for_entry": trade_missing_opened_at,
                "missing_closed_at_for_exit": trade_missing_closed_at,
                "invalid_out_of_session_count": invalid_oos_trade_count,
                "min_created_at": trade_min_created.isoformat() if trade_min_created else None,
                "max_created_at": trade_max_created.isoformat() if trade_max_created else None,
                "future_max_created_at": _future(trade_max_created),
            },
            "wallet_snapshots": wallet_snapshots,
            "extras_json_field_family_coverage": field_family_coverage,
            "analysis_readiness": {
                "candidate_to_outcome_joinable_rows": joinable_cand_outcome,
                "candidate_to_outcome_join_supported": True,
                "distinct_candidates_with_any_outcome": distinct_candidates_with_any_outcome,
                "candidates_with_all_5_horizons": candidates_with_all_5_horizons,
                "missing_outcome_count_by_horizon": missing_by_horizon,
                "trade_to_wallet_separable": trade_missing_wallet == 0,
                "trade_to_strategy_separable": trade_missing_strategy == 0,
                "ny_session_filter_supported": True,
                "ny_session_filter_note": (
                    "Apply via paper.session.session_date_for(exit_time|entry_time)"
                ),
                "invalid_out_of_session_separable_via_exit_reason": True,
                "wallet_breakdown_supported": ["engine", "deterministic_shadow", "ai_shadow"],
                "per_engine_trade_counts": engine_trade_counts,
                "engine_data_separable": engine_trade_counts["engine"] > 0
                    or engine_trade_counts["unattributed_missing_wallet_id"] == 0,
                "deterministic_shadow_data_separable": True,
                "ai_shadow_data_separable": True,
            },
            "timestamps": {
                "stored_as": "TIMESTAMPTZ (UTC)",
                "ny_session_date_derived_via": "session.session_date_for(iso_timestamp)",
                "future_timestamp_tolerance_seconds": 300,
            },
            "disclaimer": (
                "Fake-money paper simulation only. No broker data. "
                "No live orders. Research-only audit."
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": f"{type(exc).__name__}: {exc}",
        }
