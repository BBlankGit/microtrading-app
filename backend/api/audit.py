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


@router.get("/persistence/deep-status-scoped")
async def persistence_deep_status_scoped(
    scope_tick_id_prefix: str,
) -> dict:
    """
    Phase G1B-H12 Part A — test-only scoped audit.

    Returns the same shape as `/persistence/deep-status` but every
    underlying SQL query is filtered to rows whose `tick_id` starts with
    `scope_tick_id_prefix`. This lets the integration test seed a unique
    isolated dataset and assert exact endpoint values without depending
    on the production aggregates.

    Disabled in production by default. Requires the
    `AUDIT_TEST_FILTERS_ENABLED` settings flag to be True; otherwise
    returns HTTP 403 with `disabled` status.

    Fake-money paper simulation only — read-only audit, no writes.
    """
    from core.config import settings as _settings
    if not getattr(_settings, "AUDIT_TEST_FILTERS_ENABLED", False):
        from fastapi import HTTPException
        raise HTTPException(
            status_code=403,
            detail={
                "ok": False,
                "disabled": True,
                "reason": "AUDIT_TEST_FILTERS_ENABLED=false",
                "note": "Test-only endpoint; never exposed in production.",
            },
        )
    if not scope_tick_id_prefix or len(scope_tick_id_prefix) < 4:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="scope_tick_id_prefix must be >= 4 chars")

    pool = await _db.get_pool()
    if pool is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no pool",
            "scope_tick_id_prefix": scope_tick_id_prefix,
        }
    sp = scope_tick_id_prefix + "%"  # SQL LIKE pattern

    try:
        async with pool.acquire() as conn:
            # ── Candidates (scoped) ──────────────────────────────────
            cand_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates WHERE tick_id LIKE $1", sp
            ) or 0)
            cand_with_extras = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates "
                "WHERE tick_id LIKE $1 AND extras_json IS NOT NULL", sp
            ) or 0)
            cand_missing_tick_id = 0  # by construction (filter requires tick_id)
            cand_missing_created_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates "
                "WHERE tick_id LIKE $1 AND created_at IS NULL", sp
            ) or 0)
            cand_min_created = await conn.fetchval(
                "SELECT MIN(created_at) FROM paper_candidates WHERE tick_id LIKE $1", sp
            )
            cand_max_created = await conn.fetchval(
                "SELECT MAX(created_at) FROM paper_candidates WHERE tick_id LIKE $1", sp
            )
            cand_by_action = {
                (r["action"] or "unknown"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT action, COUNT(*) AS n FROM paper_candidates "
                    "WHERE tick_id LIKE $1 GROUP BY action", sp
                )
            }
            cand_by_catalyst_type = {
                (r["catalyst_type"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT catalyst_type, COUNT(*) AS n FROM paper_candidates "
                    "WHERE tick_id LIKE $1 GROUP BY catalyst_type", sp
                )
            }
            cand_by_entry_mode = {
                (r["entry_mode"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT entry_mode, COUNT(*) AS n FROM paper_candidates "
                    "WHERE tick_id LIKE $1 GROUP BY entry_mode", sp
                )
            }
            cand_by_decision_reason = {
                (r["decision_reason"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT decision_reason, COUNT(*) AS n FROM paper_candidates "
                    "WHERE tick_id LIKE $1 GROUP BY decision_reason", sp
                )
            }
            cand_coverage_pct = (
                round(cand_with_extras / cand_total * 100.0, 2)
                if cand_total else 0.0
            )

            # ── paper_ticks (scoped) ────────────────────────────────
            ticks_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_ticks WHERE tick_id LIKE $1", sp
            ) or 0)
            tick_started_min = await conn.fetchval(
                "SELECT MIN(started_at) FROM paper_ticks WHERE tick_id LIKE $1", sp
            )
            tick_started_max = await conn.fetchval(
                "SELECT MAX(started_at) FROM paper_ticks WHERE tick_id LIKE $1", sp
            )
            tick_missing_started = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_ticks "
                "WHERE tick_id LIKE $1 AND started_at IS NULL", sp
            ) or 0)
            candidates_join_ticks_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidates c "
                "INNER JOIN paper_ticks t ON t.tick_id = c.tick_id "
                "WHERE c.tick_id LIKE $1", sp
            ) or 0)
            cand_tick_join_coverage_pct = (
                round(candidates_join_ticks_count / cand_total * 100.0, 2)
                if cand_total else 0.0
            )

            # ── Outcomes (scoped via tick_id) ───────────────────────
            out_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE tick_id LIKE $1", sp
            ) or 0)
            out_by_status = {
                r["status"]: int(r["n"])
                for r in await conn.fetch(
                    "SELECT status, COUNT(*) AS n FROM paper_candidate_outcomes "
                    "WHERE tick_id LIKE $1 GROUP BY status", sp
                )
            }
            resolved_at_null_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes "
                "WHERE tick_id LIKE $1 AND resolved_at IS NULL", sp
            ) or 0)
            resolved_at_present_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes "
                "WHERE tick_id LIKE $1 AND resolved_at IS NOT NULL", sp
            ) or 0)
            out_min_resolved = await conn.fetchval(
                "SELECT MIN(resolved_at) FROM paper_candidate_outcomes "
                "WHERE tick_id LIKE $1 AND resolved_at IS NOT NULL", sp
            )
            out_max_resolved = await conn.fetchval(
                "SELECT MAX(resolved_at) FROM paper_candidate_outcomes "
                "WHERE tick_id LIKE $1 AND resolved_at IS NOT NULL", sp
            )
            distinct_candidates_with_any_outcome = int(await conn.fetchval(
                "SELECT COUNT(DISTINCT candidate_id) FROM paper_candidate_outcomes "
                "WHERE tick_id LIKE $1", sp
            ) or 0)
            joinable_cand_outcome = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes o "
                "INNER JOIN paper_candidates c ON c.id = o.candidate_id "
                "WHERE o.tick_id LIKE $1", sp
            ) or 0)

            # True missing-horizon-row per required horizon (scoped)
            REQUIRED_HORIZONS = [5, 15, 30, 60, 120]
            horizon_row_coverage: dict[str, dict] = {}
            missing_horizon_row_count_by_horizon: dict[str, int] = {}
            for h in REQUIRED_HORIZONS:
                missing_rows = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_candidates c "
                    " WHERE c.tick_id LIKE $1 AND NOT EXISTS ("
                    "  SELECT 1 FROM paper_candidate_outcomes o "
                    "   WHERE o.candidate_id = c.id AND o.horizon_minutes = $2"
                    " )",
                    sp, h,
                ) or 0)
                present_rows = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_candidates c "
                    " WHERE c.tick_id LIKE $1 AND EXISTS ("
                    "  SELECT 1 FROM paper_candidate_outcomes o "
                    "   WHERE o.candidate_id = c.id AND o.horizon_minutes = $2"
                    " )",
                    sp, h,
                ) or 0)
                resolved_rows = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_candidate_outcomes "
                    "WHERE tick_id LIKE $1 AND horizon_minutes = $2 "
                    "  AND status = 'resolved'", sp, h,
                ) or 0)
                pending_rows = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_candidate_outcomes "
                    "WHERE tick_id LIKE $1 AND horizon_minutes = $2 "
                    "  AND status = 'pending'", sp, h,
                ) or 0)
                error_rows = int(await conn.fetchval(
                    "SELECT COUNT(*) FROM paper_candidate_outcomes "
                    "WHERE tick_id LIKE $1 AND horizon_minutes = $2 "
                    "  AND status IN ('error','missing_data')", sp, h,
                ) or 0)
                missing_horizon_row_count_by_horizon[str(h)] = missing_rows
                horizon_row_coverage[str(h)] = {
                    "candidates_with_row": present_rows,
                    "candidates_missing_row": missing_rows,
                    "resolved_rows": resolved_rows,
                    "pending_rows": pending_rows,
                    "error_or_missing_data_rows": error_rows,
                }
            candidates_with_all_required_horizons = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM (
                    SELECT o.candidate_id FROM paper_candidate_outcomes o
                     INNER JOIN paper_candidates c ON c.id = o.candidate_id
                     WHERE c.tick_id LIKE $1
                       AND o.horizon_minutes = ANY($2::int[])
                     GROUP BY o.candidate_id
                    HAVING COUNT(DISTINCT o.horizon_minutes) >= cardinality($2::int[])
                ) c5
                """,
                sp, REQUIRED_HORIZONS,
            ) or 0)
            candidates_missing_any_required_horizon = (
                cand_total - candidates_with_all_required_horizons
            )

            # ── Trades (scoped) ─────────────────────────────────────
            trade_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE tick_id LIKE $1", sp
            ) or 0)
            trade_by_event = {
                r["event"]: int(r["n"])
                for r in await conn.fetch(
                    "SELECT event, COUNT(*) AS n FROM paper_trades_journal "
                    "WHERE tick_id LIKE $1 GROUP BY event", sp
                )
            }
            trade_by_wallet = {
                (r["wallet_id"] or "missing"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT wallet_id, COUNT(*) AS n FROM paper_trades_journal "
                    "WHERE tick_id LIKE $1 GROUP BY wallet_id", sp
                )
            }
            trade_by_strategy = {
                (r["strategy_id"] or "missing"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT strategy_id, COUNT(*) AS n FROM paper_trades_journal "
                    "WHERE tick_id LIKE $1 GROUP BY strategy_id", sp
                )
            }
            trade_by_exit_reason = {
                (r["exit_reason"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    "SELECT exit_reason, COUNT(*) AS n FROM paper_trades_journal "
                    "WHERE tick_id LIKE $1 AND event = 'exit' "
                    "GROUP BY exit_reason", sp
                )
            }
            trade_missing_wallet = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND (wallet_id IS NULL OR wallet_id = '')", sp
            ) or 0)
            trade_missing_strategy = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND (strategy_id IS NULL OR strategy_id = '')", sp
            ) or 0)
            trade_missing_opened_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND event = 'entry' AND opened_at IS NULL", sp
            ) or 0)
            trade_missing_closed_at = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND event = 'exit' AND closed_at IS NULL", sp
            ) or 0)
            trade_missing_entry_time_overall = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND opened_at IS NULL", sp
            ) or 0)
            invalid_oos_trade_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 "
                "  AND exit_reason = 'invalid_out_of_session_entry_flatten'", sp
            ) or 0)
            trade_min_opened = await conn.fetchval(
                "SELECT MIN(opened_at) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND opened_at IS NOT NULL", sp
            )
            trade_max_opened = await conn.fetchval(
                "SELECT MAX(opened_at) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND opened_at IS NOT NULL", sp
            )
            trade_min_closed = await conn.fetchval(
                "SELECT MIN(closed_at) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND closed_at IS NOT NULL", sp
            )
            trade_max_closed = await conn.fetchval(
                "SELECT MAX(closed_at) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND closed_at IS NOT NULL", sp
            )
            trade_min_created = await conn.fetchval(
                "SELECT MIN(created_at) FROM paper_trades_journal WHERE tick_id LIKE $1", sp
            )
            trade_max_created = await conn.fetchval(
                "SELECT MAX(created_at) FROM paper_trades_journal WHERE tick_id LIKE $1", sp
            )
            trade_future_opened = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND opened_at > now() + interval '5 minutes'", sp
            ) or 0)
            trade_future_closed = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE tick_id LIKE $1 AND closed_at > now() + interval '5 minutes'", sp
            ) or 0)

            # ── NY-session grouping (scoped) ────────────────────────
            trade_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    "SELECT to_char(COALESCE(closed_at, opened_at, created_at) "
                    "  AT TIME ZONE 'America/New_York', 'YYYY-MM-DD') AS sd, "
                    "  COUNT(*) AS n FROM paper_trades_journal "
                    "WHERE tick_id LIKE $1 "
                    "  AND COALESCE(closed_at, opened_at, created_at) IS NOT NULL "
                    "GROUP BY sd ORDER BY sd DESC LIMIT 30", sp
                )
            }
            cand_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    "SELECT to_char(created_at AT TIME ZONE 'America/New_York', "
                    "  'YYYY-MM-DD') AS sd, COUNT(*) AS n "
                    "FROM paper_candidates WHERE tick_id LIKE $1 "
                    "  AND created_at IS NOT NULL "
                    "GROUP BY sd ORDER BY sd DESC LIMIT 30", sp
                )
            }
            out_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    "SELECT to_char(COALESCE(resolved_at, created_at) "
                    "  AT TIME ZONE 'America/New_York', 'YYYY-MM-DD') AS sd, "
                    "  COUNT(*) AS n FROM paper_candidate_outcomes "
                    "WHERE tick_id LIKE $1 "
                    "  AND COALESCE(resolved_at, created_at) IS NOT NULL "
                    "GROUP BY sd ORDER BY sd DESC LIMIT 30", sp
                )
            }

            # ── extras_json field-family coverage (scoped, full-scope) ─
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
                "selected_path": ["entry_mode", "candidate_sources", "market_trend_path_name"],
                "score_components": ["score_components", "total_score", "final_score_after_intelligence_adjustments"],
            }
            scope_extras_sample = cand_with_extras  # full-scope (small)
            field_family_coverage: dict[str, dict] = {}
            for family, keys in family_probes.items():
                if scope_extras_sample == 0:
                    field_family_coverage[family] = {
                        "coverage_scope": "full_scope",
                        "sample_size": 0,
                        "rows_present": 0,
                        "present": 0,
                        "coverage_percent": 0.0,
                        "status": "not_collected",
                        "keys": keys,
                        "keys_found": [],
                    }
                    continue
                or_clauses = " OR ".join(
                    [f"extras_json ? $2::text"]
                    + [f"extras_json ? ${i+3}::text" for i in range(len(keys) - 1)]
                )
                present = int(await conn.fetchval(
                    f"SELECT COUNT(*) FROM paper_candidates "
                    f"WHERE tick_id LIKE $1 AND extras_json IS NOT NULL "
                    f"  AND ({or_clauses})",
                    sp, *keys,
                ) or 0)
                keys_found: list[str] = []
                for k in keys:
                    n = int(await conn.fetchval(
                        "SELECT COUNT(*) FROM paper_candidates "
                        "WHERE tick_id LIKE $1 AND extras_json IS NOT NULL "
                        "  AND extras_json ? $2::text",
                        sp, k,
                    ) or 0)
                    if n > 0:
                        keys_found.append(k)
                pct = round(present / scope_extras_sample * 100.0, 2) if scope_extras_sample else 0.0
                field_family_coverage[family] = {
                    "coverage_scope": "full_scope",
                    "sample_size": scope_extras_sample,
                    "rows_present": present,
                    "present": present,
                    "coverage_percent": pct,
                    "status": "collected" if present > 0 else "not_collected",
                    "keys": keys,
                    "keys_found": keys_found,
                }

            # ── Shadow decision persistence (scoped) ────────────────
            shadow_row = await conn.fetchrow(
                """
                SELECT
                    COUNT(*) AS sample_size,
                    COUNT(*) FILTER (WHERE extras_json ? 'enhanced_shadow_decision') AS det_decision_rows,
                    COUNT(*) FILTER (WHERE extras_json ? 'enhanced_shadow_score') AS det_score_rows,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WOULD_ENTER') AS det_would_enter,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WATCH') AS det_watch,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WOULD_REJECT') AS det_would_reject,
                    COUNT(*) FILTER (WHERE extras_json ? 'llm_decision') AS ai_decision_rows,
                    COUNT(*) FILTER (WHERE extras_json ? 'llm_status') AS ai_status_rows,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WOULD_ENTER') AS ai_would_enter,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WATCH') AS ai_watch,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WOULD_REJECT') AS ai_would_reject,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'disabled') AS ai_disabled,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'error') AS ai_error,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'not_selected') AS ai_not_selected
                  FROM paper_candidates
                 WHERE tick_id LIKE $1 AND extras_json IS NOT NULL
                """,
                sp,
            )

        # Build response (full structure mirrors deep-status)
        sw_sample = int(shadow_row["sample_size"] or 0) if shadow_row else 0
        det_decision_rows = int(shadow_row["det_decision_rows"] or 0) if shadow_row else 0
        ai_decision_rows = int(shadow_row["ai_decision_rows"] or 0) if shadow_row else 0
        ai_status_rows = int(shadow_row["ai_status_rows"] or 0) if shadow_row else 0

        det_persistence = {
            "sample_size": sw_sample,
            "decision_field_present_rows": det_decision_rows,
            "score_field_present_rows": int(shadow_row["det_score_rows"] or 0) if shadow_row else 0,
            "would_enter_count": int(shadow_row["det_would_enter"] or 0) if shadow_row else 0,
            "watch_count": int(shadow_row["det_watch"] or 0) if shadow_row else 0,
            "would_reject_count": int(shadow_row["det_would_reject"] or 0) if shadow_row else 0,
            "missing_decision_count": sw_sample - det_decision_rows,
            "evidence_based_separable": det_decision_rows > 0,
            "status": "collected" if det_decision_rows > 0 else "not_collected",
        }
        ai_persistence = {
            "sample_size": sw_sample,
            "decision_field_present_rows": ai_decision_rows,
            "status_field_present_rows": ai_status_rows,
            "would_enter_count": int(shadow_row["ai_would_enter"] or 0) if shadow_row else 0,
            "watch_count": int(shadow_row["ai_watch"] or 0) if shadow_row else 0,
            "would_reject_count": int(shadow_row["ai_would_reject"] or 0) if shadow_row else 0,
            "disabled_count": int(shadow_row["ai_disabled"] or 0) if shadow_row else 0,
            "error_count": int(shadow_row["ai_error"] or 0) if shadow_row else 0,
            "not_selected_count": int(shadow_row["ai_not_selected"] or 0) if shadow_row else 0,
            "missing_decision_count": sw_sample - ai_decision_rows,
            "missing_status_count": sw_sample - ai_status_rows,
            "evidence_based_separable": ai_decision_rows > 0 or ai_status_rows > 0,
            "status": "collected" if (ai_decision_rows > 0 or ai_status_rows > 0) else "not_collected",
            "no_paid_ai_calls": True,
        }

        latest_trade = next(iter(trade_by_ny_session), None)
        latest_cand = next(iter(cand_by_ny_session), None)
        latest_out = next(iter(out_by_ny_session), None)
        available = [(s, d) for s, d in (
            ("trades", latest_trade), ("candidates", latest_cand), ("outcomes", latest_out)
        ) if d]
        if available:
            latest_session_date = max(d for _, d in available)
            latest_session_date_source = next(s for s, d in available if d == latest_session_date)
        else:
            latest_session_date = None
            latest_session_date_source = "no_data"

        engine_separable = (
            trade_by_wallet.get("engine", 0) > 0
            or trade_by_wallet.get("missing", 0) == 0
        )
        det_separable = det_persistence["evidence_based_separable"]
        ai_separable = ai_persistence["evidence_based_separable"]

        blocking_gaps: list[str] = []
        warnings_list: list[str] = []
        if cand_total == 0:
            blocking_gaps.append("no_candidates_persisted")
        if joinable_cand_outcome == 0 and cand_total > 0:
            blocking_gaps.append("no_candidate_to_outcome_joins")
        if not engine_separable:
            warnings_list.append("engine_trade_attribution_incomplete")
        if not det_separable:
            warnings_list.append("deterministic_shadow_decisions_not_persisted")
        if not ai_separable:
            warnings_list.append("ai_shadow_decisions_not_persisted")

        engine_analysis_ready = (
            cand_total > 0
            and joinable_cand_outcome > 0
            and engine_separable
        )
        deterministic_shadow_analysis_ready = det_separable and cand_total > 0
        ai_shadow_analysis_ready = ai_separable
        overall_freeze_audit_ready = (
            engine_analysis_ready
            and deterministic_shadow_analysis_ready
            and len(blocking_gaps) == 0
        )

        from datetime import datetime as _dt
        return {
            "ok": True,
            "scoped": True,
            "scope_tick_id_prefix": scope_tick_id_prefix,
            "analysis_ready": overall_freeze_audit_ready,
            "overall_freeze_audit_ready": overall_freeze_audit_ready,
            "engine_analysis_ready": engine_analysis_ready,
            "deterministic_shadow_analysis_ready": deterministic_shadow_analysis_ready,
            "ai_shadow_analysis_ready": ai_shadow_analysis_ready,
            "blocking_gaps": blocking_gaps,
            "warnings": warnings_list,
            "candidates": {
                "total": cand_total,
                "with_extras_json": cand_with_extras,
                "extras_json_coverage_percent": cand_coverage_pct,
                "min_created_at": cand_min_created.isoformat() if cand_min_created else None,
                "max_created_at": cand_max_created.isoformat() if cand_max_created else None,
                "by_action": cand_by_action,
                "by_catalyst_type": cand_by_catalyst_type,
                "by_entry_mode": cand_by_entry_mode,
                "by_decision_reason": cand_by_decision_reason,
                "missing_tick_id": cand_missing_tick_id,
                "missing_created_at": cand_missing_created_at,
            },
            "tick_ts_audit": {
                "tick_ts_persistence_status": "not_persisted_as_candidate_column",
                "paper_ticks_total": ticks_total,
                "paper_ticks_started_at_min": tick_started_min.isoformat() if tick_started_min else None,
                "paper_ticks_started_at_max": tick_started_max.isoformat() if tick_started_max else None,
                "paper_ticks_missing_started_at": tick_missing_started,
                "candidates_joinable_to_ticks_count": candidates_join_ticks_count,
                "candidates_joinable_to_ticks_coverage_percent": cand_tick_join_coverage_pct,
            },
            "extras_json_field_family_coverage": field_family_coverage,
            "shadow_decision_persistence": {
                "deterministic_shadow": det_persistence,
                "ai_shadow": ai_persistence,
                "evidence_source": f"full-scope ({scope_extras_sample} rows)",
            },
            "outcomes": {
                "total": out_total,
                "by_status": out_by_status,
                "resolved_at_null_count": resolved_at_null_count,
                "resolved_at_present_count": resolved_at_present_count,
                "min_resolved_at": out_min_resolved.isoformat() if out_min_resolved else None,
                "max_resolved_at": out_max_resolved.isoformat() if out_max_resolved else None,
                "resolved_at_min": out_min_resolved.isoformat() if out_min_resolved else None,
                "resolved_at_max": out_max_resolved.isoformat() if out_max_resolved else None,
                "distinct_candidates_with_any_outcome": distinct_candidates_with_any_outcome,
                "required_horizons": REQUIRED_HORIZONS,
                "candidates_with_all_required_horizons": candidates_with_all_required_horizons,
                "candidates_missing_any_required_horizon": candidates_missing_any_required_horizon,
                "missing_horizon_row_count_by_horizon": missing_horizon_row_count_by_horizon,
                "horizon_row_coverage": horizon_row_coverage,
            },
            "trades": {
                "total": trade_total,
                "by_event": trade_by_event,
                "by_wallet_id": trade_by_wallet,
                "by_strategy_id": trade_by_strategy,
                "by_exit_reason": trade_by_exit_reason,
                "missing_wallet_id": trade_missing_wallet,
                "missing_strategy_id": trade_missing_strategy,
                "missing_entry_time": trade_missing_entry_time_overall,
                "missing_exit_time_for_closed": trade_missing_closed_at,
                "missing_opened_at_for_entry": trade_missing_opened_at,
                "missing_closed_at_for_exit": trade_missing_closed_at,
                "invalid_out_of_session_count": invalid_oos_trade_count,
                "min_created_at": trade_min_created.isoformat() if trade_min_created else None,
                "max_created_at": trade_max_created.isoformat() if trade_max_created else None,
                "min_opened_at": trade_min_opened.isoformat() if trade_min_opened else None,
                "max_opened_at": trade_max_opened.isoformat() if trade_max_opened else None,
                "min_closed_at": trade_min_closed.isoformat() if trade_min_closed else None,
                "max_closed_at": trade_max_closed.isoformat() if trade_max_closed else None,
                "future_opened_at_count": trade_future_opened,
                "future_closed_at_count": trade_future_closed,
                "column_mapping_note": (
                    "opened_at IS the entry timestamp; closed_at IS the exit timestamp."
                ),
            },
            "ny_session_grouping": {
                "session_date_ny_storage": "derived",
                "trade_by_ny_session": trade_by_ny_session,
                "candidates_by_ny_session": cand_by_ny_session,
                "outcomes_by_ny_session": out_by_ny_session,
                "latest_trade_session_date": latest_trade,
                "latest_candidate_session_date": latest_cand,
                "latest_outcome_session_date": latest_out,
                "latest_session_date": latest_session_date,
                "latest_session_date_source": latest_session_date_source,
            },
            "disclaimer": (
                "Fake-money paper simulation only. Test-only scoped audit. "
                "Disabled in production."
            ),
        }
    except Exception as exc:
        return {
            "ok": False,
            "scoped": True,
            "scope_tick_id_prefix": scope_tick_id_prefix,
            "error": f"{type(exc).__name__}: {exc}",
        }


@router.get("/persistence/deep-status")
async def persistence_deep_status() -> dict:
    """
    Phase G1B-H6 Part D + G1B-H8 — comprehensive persistence audit.

    Reports candidate / outcome / trade persistence with evidence-based
    flags so we can prove each engine's data is separately analysable.
    Includes tick_ts column status, candidate grouping, extras_json
    field-family coverage, evidence-based shadow/AI decision persistence,
    NY-session grouping, outcome completeness, and an analysis_ready
    summary with blocking_gaps and warnings. Fake-money only.
    """
    pool = await _db.get_pool()
    if pool is None:
        return {
            "ok": False,
            "skipped": True,
            "reason": "no pool",
            "analysis_ready": False,
            "overall_freeze_audit_ready": False,
            "engine_analysis_ready": False,
            "deterministic_shadow_analysis_ready": False,
            "ai_shadow_analysis_ready": False,
            "ai_shadow_status_note": "postgres_pool_unavailable",
            "blocking_gaps": ["postgres_pool_unavailable"],
            "warnings": [],
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

            # G1B-H9 Part D: direct resolved_at NULL/present counts
            resolved_at_null_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NULL"
            ) or 0)
            resolved_at_present_count = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_candidate_outcomes WHERE resolved_at IS NOT NULL"
            ) or 0)

            # G1B-H9 Part E: TRUE missing-horizon-row count (absent rows, not
            # just unresolved). For each REQUIRED horizon, count candidates
            # that have NO row at all for that horizon.
            REQUIRED_HORIZONS = [5, 15, 30, 60, 120]
            missing_horizon_row_count_by_horizon: dict[str, int] = {}
            horizon_row_coverage: dict[str, dict] = {}
            for h in REQUIRED_HORIZONS:
                missing_rows = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM paper_candidates c
                     WHERE NOT EXISTS (
                        SELECT 1 FROM paper_candidate_outcomes o
                         WHERE o.candidate_id = c.id
                           AND o.horizon_minutes = $1
                     )
                    """,
                    h,
                ) or 0)
                present_rows = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM paper_candidates c
                     WHERE EXISTS (
                        SELECT 1 FROM paper_candidate_outcomes o
                         WHERE o.candidate_id = c.id
                           AND o.horizon_minutes = $1
                     )
                    """,
                    h,
                ) or 0)
                resolved_rows = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM paper_candidate_outcomes
                     WHERE horizon_minutes = $1 AND status = 'resolved'
                    """,
                    h,
                ) or 0)
                pending_rows = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM paper_candidate_outcomes
                     WHERE horizon_minutes = $1 AND status = 'pending'
                    """,
                    h,
                ) or 0)
                error_rows = int(await conn.fetchval(
                    """
                    SELECT COUNT(*) FROM paper_candidate_outcomes
                     WHERE horizon_minutes = $1 AND status IN ('error','missing_data')
                    """,
                    h,
                ) or 0)
                missing_horizon_row_count_by_horizon[str(h)] = missing_rows
                horizon_row_coverage[str(h)] = {
                    "candidates_with_row": present_rows,
                    "candidates_missing_row": missing_rows,
                    "resolved_rows": resolved_rows,
                    "pending_rows": pending_rows,
                    "error_or_missing_data_rows": error_rows,
                }
            candidates_with_all_required_horizons = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM (
                    SELECT candidate_id FROM paper_candidate_outcomes
                     WHERE horizon_minutes = ANY($1::int[])
                     GROUP BY candidate_id
                    HAVING COUNT(DISTINCT horizon_minutes) >= cardinality($1::int[])
                ) c
                """,
                REQUIRED_HORIZONS,
            ) or 0)
            candidates_missing_any_required_horizon = cand_total - candidates_with_all_required_horizons

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
                "selected_path": ["entry_mode", "candidate_sources", "market_trend_path_name"],
                "score_components": ["score_components", "total_score", "final_score_after_intelligence_adjustments"],
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
                # G1B-H9 Part C: every coverage object explicitly includes
                # coverage_scope, status (collected/not_collected), and the
                # set of keys actually found in present rows.
                if sample_size == 0:
                    field_family_coverage[family] = {
                        "coverage_scope": "sampled",
                        "sample_size": 0,
                        "rows_present": 0,
                        "present": 0,  # backwards-compat alias
                        "coverage_percent": 0.0,
                        "status": "not_collected",
                        "keys": keys,
                        "keys_found": [],
                    }
                    continue
                or_clauses = " OR ".join([f"extras_json ? $1::text"] + [f"extras_json ? ${i+2}::text" for i in range(len(keys) - 1)])
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
                # Find which specific keys actually appear in the sample
                keys_found: list[str] = []
                for k in keys:
                    n = int(await conn.fetchval(
                        """
                        SELECT COUNT(*) FROM (
                            SELECT extras_json FROM paper_candidates
                             WHERE extras_json IS NOT NULL
                             ORDER BY id DESC LIMIT 5000
                        ) s WHERE extras_json ? $1::text
                        """,
                        k,
                    ) or 0)
                    if n > 0:
                        keys_found.append(k)
                pct = round(present / sample_size * 100.0, 2) if sample_size else 0.0
                field_family_coverage[family] = {
                    "coverage_scope": "sampled",
                    "sample_size": sample_size,
                    "rows_present": present,
                    "present": present,  # backwards-compat alias
                    "coverage_percent": pct,
                    "status": "collected" if present > 0 else "not_collected",
                    "keys": keys,
                    "keys_found": keys_found,
                }

            # ── Per-engine trade separability ──────────────────────────
            engine_trade_counts = {
                "engine": trade_by_wallet.get("engine", 0),
                "deterministic_shadow": trade_by_wallet.get("deterministic_shadow", 0),
                "ai_shadow": trade_by_wallet.get("ai_shadow", 0),
                "unattributed_missing_wallet_id": trade_by_wallet.get("missing", 0),
            }

            # ── Phase G1B-H8 Part B: tick_ts column audit ───────────────
            # paper_candidates has no `tick_ts` column. The candidate's
            # `created_at` is the insert timestamp; the actual tick start
            # is in paper_ticks.started_at, joinable via tick_id. We audit
            # both honestly and report `tick_ts_persistence_status`.
            ticks_total = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_ticks"
            ) or 0)
            tick_started_min = await conn.fetchval(
                "SELECT MIN(started_at) FROM paper_ticks"
            )
            tick_started_max = await conn.fetchval(
                "SELECT MAX(started_at) FROM paper_ticks"
            )
            tick_missing_started = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_ticks WHERE started_at IS NULL"
            ) or 0)
            candidates_join_ticks_count = int(await conn.fetchval(
                """
                SELECT COUNT(*) FROM paper_candidates c
                  INNER JOIN paper_ticks t ON t.tick_id = c.tick_id
                """
            ) or 0)
            cand_tick_join_coverage_pct = (
                round(candidates_join_ticks_count / cand_total * 100.0, 2)
                if cand_total else 0.0
            )

            # ── Phase G1B-H8 Part C: additional candidate grouping ──────
            cand_by_catalyst_type = {
                (r["catalyst_type"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT catalyst_type, COUNT(*) AS n
                      FROM paper_candidates
                     GROUP BY catalyst_type
                     ORDER BY n DESC LIMIT 25
                    """
                )
            }
            cand_by_entry_mode = {
                (r["entry_mode"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT entry_mode, COUNT(*) AS n
                      FROM paper_candidates
                     GROUP BY entry_mode
                     ORDER BY n DESC LIMIT 25
                    """
                )
            }
            cand_by_decision_reason = {
                (r["decision_reason"] or "none"): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT decision_reason, COUNT(*) AS n
                      FROM paper_candidates
                     GROUP BY decision_reason
                     ORDER BY n DESC LIMIT 25
                    """
                )
            }

            # ── Phase G1B-H8 Part E: evidence-based shadow audit ────────
            # Sample the most recent 5K extras rows and count actual values
            # of enhanced_shadow_decision / llm_decision / llm_status.
            shadow_evidence_sample = 5000
            shadow_row = await conn.fetchrow(
                f"""
                SELECT
                    COUNT(*) AS sample_size,
                    COUNT(*) FILTER (WHERE extras_json ? 'enhanced_shadow_decision') AS det_decision_rows,
                    COUNT(*) FILTER (WHERE extras_json ? 'enhanced_shadow_score') AS det_score_rows,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WOULD_ENTER') AS det_would_enter,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WATCH') AS det_watch,
                    COUNT(*) FILTER (WHERE extras_json ->> 'enhanced_shadow_decision' = 'WOULD_REJECT') AS det_would_reject,
                    COUNT(*) FILTER (WHERE extras_json ? 'llm_decision') AS ai_decision_rows,
                    COUNT(*) FILTER (WHERE extras_json ? 'llm_status') AS ai_status_rows,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WOULD_ENTER') AS ai_would_enter,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WATCH') AS ai_watch,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_decision' = 'WOULD_REJECT') AS ai_would_reject,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'disabled') AS ai_disabled,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'error') AS ai_error,
                    COUNT(*) FILTER (WHERE extras_json ->> 'llm_status' = 'not_selected') AS ai_not_selected
                  FROM (
                    SELECT extras_json FROM paper_candidates
                     WHERE extras_json IS NOT NULL
                     ORDER BY id DESC LIMIT {shadow_evidence_sample}
                  ) s
                """
            )

            # ── Phase G1B-H8 Part G: NY-session grouping ────────────────
            trade_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT to_char(
                             COALESCE(closed_at, opened_at, created_at)
                             AT TIME ZONE 'America/New_York', 'YYYY-MM-DD'
                           ) AS sd,
                           COUNT(*) AS n
                      FROM paper_trades_journal
                     WHERE COALESCE(closed_at, opened_at, created_at) IS NOT NULL
                     GROUP BY sd
                     ORDER BY sd DESC LIMIT 30
                    """
                )
            }
            cand_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT to_char(
                             created_at AT TIME ZONE 'America/New_York',
                             'YYYY-MM-DD'
                           ) AS sd,
                           COUNT(*) AS n
                      FROM paper_candidates
                     WHERE created_at IS NOT NULL
                     GROUP BY sd
                     ORDER BY sd DESC LIMIT 30
                    """
                )
            }
            out_by_ny_session = {
                str(r["sd"]): int(r["n"])
                for r in await conn.fetch(
                    """
                    SELECT to_char(
                             COALESCE(resolved_at, created_at)
                             AT TIME ZONE 'America/New_York', 'YYYY-MM-DD'
                           ) AS sd,
                           COUNT(*) AS n
                      FROM paper_candidate_outcomes
                     WHERE COALESCE(resolved_at, created_at) IS NOT NULL
                     GROUP BY sd
                     ORDER BY sd DESC LIMIT 30
                    """
                )
            }

            # ── Phase G1B-H8 Part G: trade timestamp min/max ────────────
            trade_min_opened = await conn.fetchval(
                "SELECT MIN(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL"
            )
            trade_max_opened = await conn.fetchval(
                "SELECT MAX(opened_at) FROM paper_trades_journal WHERE opened_at IS NOT NULL"
            )
            trade_min_closed = await conn.fetchval(
                "SELECT MIN(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL"
            )
            trade_max_closed = await conn.fetchval(
                "SELECT MAX(closed_at) FROM paper_trades_journal WHERE closed_at IS NOT NULL"
            )
            trade_future_opened = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE opened_at > now() + interval '5 minutes'"
            ) or 0)
            trade_future_closed = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal "
                "WHERE closed_at > now() + interval '5 minutes'"
            ) or 0)
            trade_missing_entry_time_overall = int(await conn.fetchval(
                "SELECT COUNT(*) FROM paper_trades_journal WHERE opened_at IS NULL"
            ) or 0)
            trade_missing_exit_time_for_closed = trade_missing_closed_at

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

        # ── Phase G1B-H8 Part E/F: evidence-based shadow persistence ──
        sw_sample = int(shadow_row["sample_size"] or 0) if shadow_row else 0
        det_decision_rows = int(shadow_row["det_decision_rows"] or 0) if shadow_row else 0
        ai_decision_rows = int(shadow_row["ai_decision_rows"] or 0) if shadow_row else 0
        ai_status_rows = int(shadow_row["ai_status_rows"] or 0) if shadow_row else 0

        det_persistence = {
            "sample_size": sw_sample,
            "decision_field_present_rows": det_decision_rows,
            "score_field_present_rows": int(shadow_row["det_score_rows"] or 0) if shadow_row else 0,
            "would_enter_count": int(shadow_row["det_would_enter"] or 0) if shadow_row else 0,
            "watch_count": int(shadow_row["det_watch"] or 0) if shadow_row else 0,
            "would_reject_count": int(shadow_row["det_would_reject"] or 0) if shadow_row else 0,
            "missing_decision_count": sw_sample - det_decision_rows,
            "evidence_based_separable": det_decision_rows > 0,
            "status": "collected" if det_decision_rows > 0 else "not_collected",
        }
        ai_persistence = {
            "sample_size": sw_sample,
            "decision_field_present_rows": ai_decision_rows,
            "status_field_present_rows": ai_status_rows,
            "would_enter_count": int(shadow_row["ai_would_enter"] or 0) if shadow_row else 0,
            "watch_count": int(shadow_row["ai_watch"] or 0) if shadow_row else 0,
            "would_reject_count": int(shadow_row["ai_would_reject"] or 0) if shadow_row else 0,
            "disabled_count": int(shadow_row["ai_disabled"] or 0) if shadow_row else 0,
            "error_count": int(shadow_row["ai_error"] or 0) if shadow_row else 0,
            "not_selected_count": int(shadow_row["ai_not_selected"] or 0) if shadow_row else 0,
            "missing_decision_count": sw_sample - ai_decision_rows,
            "missing_status_count": sw_sample - ai_status_rows,
            "evidence_based_separable": ai_decision_rows > 0 or ai_status_rows > 0,
            "status": "collected" if (ai_decision_rows > 0 or ai_status_rows > 0) else "not_collected",
            "no_paid_ai_calls": True,
        }

        det_separable = det_persistence["evidence_based_separable"]
        ai_separable = ai_persistence["evidence_based_separable"]
        engine_separable = (
            engine_trade_counts["engine"] > 0
            or engine_trade_counts["unattributed_missing_wallet_id"] == 0
        )

        # ── Phase G1B-H9 Part F: latest_session_date from multiple sources ──
        latest_trade_session_date = next(iter(trade_by_ny_session), None)
        latest_candidate_session_date = next(iter(cand_by_ny_session), None)
        latest_outcome_session_date = next(iter(out_by_ny_session), None)
        candidate_sources = [
            ("trades", latest_trade_session_date),
            ("candidates", latest_candidate_session_date),
            ("outcomes", latest_outcome_session_date),
        ]
        available = [(src, d) for src, d in candidate_sources if d]
        if available:
            latest_session_date = max(d for _, d in available)
            latest_session_date_source = next(src for src, d in available if d == latest_session_date)
        else:
            latest_session_date = None
            latest_session_date_source = "no_data"

        # ── Phase G1B-H9 Part H: per-engine and overall readiness ─────
        blocking_gaps: list[str] = []
        warnings_list: list[str] = []
        if cand_total == 0:
            blocking_gaps.append("no_candidates_persisted")
        if joinable_cand_outcome == 0 and cand_total > 0:
            blocking_gaps.append("no_candidate_to_outcome_joins")
        if not engine_separable:
            warnings_list.append("engine_trade_attribution_incomplete")
        if not det_separable:
            warnings_list.append("deterministic_shadow_decisions_not_persisted")
        if not ai_separable:
            warnings_list.append("ai_shadow_decisions_not_persisted")
        if cand_coverage_pct < 50.0 and cand_total > 0:
            warnings_list.append(
                f"low_extras_json_coverage_{cand_coverage_pct:.1f}_percent"
            )
        if engine_trade_counts["unattributed_missing_wallet_id"] > 0:
            warnings_list.append(
                f"trades_missing_wallet_id_{engine_trade_counts['unattributed_missing_wallet_id']}"
            )
        if candidates_missing_any_required_horizon > 0 and cand_total > 0:
            warnings_list.append(
                f"missing_outcome_rows_{candidates_missing_any_required_horizon}_candidates"
            )

        # Per-engine readiness — evidence-based
        engine_analysis_ready = (
            cand_total > 0
            and joinable_cand_outcome > 0
            and engine_separable
        )
        deterministic_shadow_analysis_ready = (
            det_separable
            and cand_total > 0
        )
        # AI shadow is "ready for analysis" only if its decisions are persisted.
        # Being inactive due to LLM_SHADOW_ENABLED=false is NOT readiness — it
        # means the audit cannot compare AI_SHADOW yet.
        ai_shadow_analysis_ready = ai_separable
        ai_shadow_status_note = (
            "ai_shadow_data_collected"
            if ai_separable
            else "ai_shadow_inactive_or_decisions_not_persisted"
        )

        overall_freeze_audit_ready = (
            engine_analysis_ready
            and deterministic_shadow_analysis_ready
            and len(blocking_gaps) == 0
            # AI shadow not required for freeze if it's intentionally disabled
            # AND warnings call this out clearly.
        )

        # Keep top-level analysis_ready for backwards-compat but make it strict.
        analysis_ready = overall_freeze_audit_ready

        return {
            "ok": True,
            "generated_at": now_utc.isoformat(),
            "analysis_ready": analysis_ready,
            "overall_freeze_audit_ready": overall_freeze_audit_ready,
            "engine_analysis_ready": engine_analysis_ready,
            "deterministic_shadow_analysis_ready": deterministic_shadow_analysis_ready,
            "ai_shadow_analysis_ready": ai_shadow_analysis_ready,
            "ai_shadow_status_note": ai_shadow_status_note,
            "blocking_gaps": blocking_gaps,
            "warnings": warnings_list,
            "candidates": {
                "total": cand_total,
                "with_extras_json": cand_with_extras,
                "extras_json_coverage_percent": cand_coverage_pct,
                "min_created_at": cand_min_created.isoformat() if cand_min_created else None,
                "max_created_at": cand_max_created.isoformat() if cand_max_created else None,
                "by_action": cand_by_action,
                "by_rejection_reason": cand_by_rejection,
                "by_catalyst_type": cand_by_catalyst_type,
                "by_entry_mode": cand_by_entry_mode,
                "by_decision_reason": cand_by_decision_reason,
                "by_marketdata_source": cand_by_marketdata_source,
                "missing_tick_id": cand_missing_tick_id,
                "missing_created_at": cand_missing_created_at,
                "future_max_created_at": _future(cand_max_created),
            },
            "tick_ts_audit": {
                "tick_ts_persistence_status": "not_persisted_as_candidate_column",
                "tick_ts_persistence_note": (
                    "paper_candidates has no `tick_ts` column. The actual tick "
                    "start time is in paper_ticks.started_at; candidates link via "
                    "tick_id. paper_candidates.created_at is the insert timestamp."
                ),
                "paper_ticks_total": ticks_total,
                "paper_ticks_started_at_min": tick_started_min.isoformat() if tick_started_min else None,
                "paper_ticks_started_at_max": tick_started_max.isoformat() if tick_started_max else None,
                "paper_ticks_missing_started_at": tick_missing_started,
                "candidates_joinable_to_ticks_count": candidates_join_ticks_count,
                "candidates_joinable_to_ticks_coverage_percent": cand_tick_join_coverage_pct,
                "missing_tick_id_on_candidates": cand_missing_tick_id,
                "derivation_supported": True,
            },
            "extras_json_field_family_coverage": field_family_coverage,
            "shadow_decision_persistence": {
                "deterministic_shadow": det_persistence,
                "ai_shadow": ai_persistence,
                "evidence_source": (
                    f"sampled most-recent {sw_sample} candidate rows with extras_json"
                ),
            },
            "outcomes": {
                "total": out_total,
                "by_status": out_by_status,
                "by_horizon": out_by_horizon,
                "by_source": out_by_source,
                "min_resolved_at": out_min_resolved.isoformat() if out_min_resolved else None,
                "max_resolved_at": out_max_resolved.isoformat() if out_max_resolved else None,
                # G1B-H10 Part D: spec-named aliases (Codex requested
                # resolved_at_min / resolved_at_max; the legacy keys above
                # are kept for backwards-compat).
                "resolved_at_min": out_min_resolved.isoformat() if out_min_resolved else None,
                "resolved_at_max": out_max_resolved.isoformat() if out_max_resolved else None,
                # G1B-H9 Part D: direct resolved_at NULL/present counts
                "resolved_at_null_count": resolved_at_null_count,
                "resolved_at_present_count": resolved_at_present_count,
                # Status-derived counts kept separate
                "status_derived_missing_resolved_at_count": (
                    out_by_status.get("pending", 0)
                    + out_by_status.get("missing_data", 0)
                    + out_by_status.get("error", 0)
                ),
                "missing_resolved_at_count": resolved_at_null_count,  # backwards-compat
                "distinct_candidates_with_any_outcome": distinct_candidates_with_any_outcome,
                "candidates_with_all_5_horizons": candidates_with_all_5_horizons,
                # G1B-H9 Part E: TRUE missing horizon rows (absent, not just unresolved)
                "required_horizons": [5, 15, 30, 60, 120],
                "candidates_with_all_required_horizons": candidates_with_all_required_horizons,
                "candidates_missing_any_required_horizon": candidates_missing_any_required_horizon,
                "missing_horizon_row_count_by_horizon": missing_horizon_row_count_by_horizon,
                "horizon_row_coverage": horizon_row_coverage,
                "missing_outcome_count_by_horizon": missing_by_horizon,  # backwards-compat (unresolved only)
            },
            "trades": {
                "total": trade_total,
                "by_event": trade_by_event,
                "by_wallet_id": trade_by_wallet,
                "by_strategy_id": trade_by_strategy,
                "by_exit_reason": trade_by_exit_reason,
                "missing_wallet_id": trade_missing_wallet,
                "missing_strategy_id": trade_missing_strategy,
                "missing_entry_time": trade_missing_entry_time_overall,
                "missing_exit_time_for_closed": trade_missing_exit_time_for_closed,
                "missing_opened_at_for_entry": trade_missing_opened_at,
                "missing_closed_at_for_exit": trade_missing_closed_at,
                "invalid_out_of_session_count": invalid_oos_trade_count,
                "min_created_at": trade_min_created.isoformat() if trade_min_created else None,
                "max_created_at": trade_max_created.isoformat() if trade_max_created else None,
                "min_opened_at": trade_min_opened.isoformat() if trade_min_opened else None,
                "max_opened_at": trade_max_opened.isoformat() if trade_max_opened else None,
                "min_closed_at": trade_min_closed.isoformat() if trade_min_closed else None,
                "max_closed_at": trade_max_closed.isoformat() if trade_max_closed else None,
                "future_max_created_at": _future(trade_max_created),
                "future_opened_at_count": trade_future_opened,
                "future_closed_at_count": trade_future_closed,
                "column_mapping_note": (
                    "opened_at IS the entry timestamp; closed_at IS the exit "
                    "timestamp. entry_time and exit_time in API responses derive "
                    "from these columns."
                ),
            },
            "ny_session_grouping": {
                "session_date_ny_storage": "derived",
                "derivation_method": (
                    "Postgres `AT TIME ZONE 'America/New_York'` on closed_at | "
                    "opened_at | created_at; mirrors session.session_date_for()."
                ),
                "trade_by_ny_session": trade_by_ny_session,
                "candidates_by_ny_session": cand_by_ny_session,
                "outcomes_by_ny_session": out_by_ny_session,
                # G1B-H9 Part F: explicit per-source latest dates + derived latest
                "latest_trade_session_date": latest_trade_session_date,
                "latest_candidate_session_date": latest_candidate_session_date,
                "latest_outcome_session_date": latest_outcome_session_date,
                "latest_session_date": latest_session_date,
                "latest_session_date_source": latest_session_date_source,
                "weekend_after_close_derivation_supported": True,
            },
            "wallet_snapshots": wallet_snapshots,
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
                "engine_data_separable": engine_separable,
                # Evidence-based (Phase G1B-H8 Part F)
                "deterministic_shadow_data_separable": det_separable,
                "deterministic_shadow_data_separable_evidence": {
                    "decision_field_present_rows": det_decision_rows,
                    "sample_size": sw_sample,
                },
                "ai_shadow_data_separable": ai_separable,
                "ai_shadow_data_separable_evidence": {
                    "decision_field_present_rows": ai_decision_rows,
                    "status_field_present_rows": ai_status_rows,
                    "sample_size": sw_sample,
                },
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
            "analysis_ready": False,
            "overall_freeze_audit_ready": False,
            "engine_analysis_ready": False,
            "deterministic_shadow_analysis_ready": False,
            "ai_shadow_analysis_ready": False,
            "ai_shadow_status_note": "audit_query_failed",
            "blocking_gaps": ["audit_query_failed"],
            "warnings": [],
        }
