"""
Phase I4-A: Enhanced Opportunity Shadow Scoring.

Shadow/diagnostic only — computes an independent opportunity score for each
candidate evaluated by the paper simulator. Does NOT affect:
  - eligible / action / entry_mode
  - actual trade entries or exits
  - position sizing, cash, equity
  - journal entry/exit behavior

No broker. No live trading. No real orders. No real-money execution.
No AI/LLM/Ollama/OpenAI/Anthropic/LangChain.
No new Polygon calls. No new ApeWisdom calls.
All data read from already-fetched in-memory caches.
"""
from __future__ import annotations

from typing import Any

# ── Thresholds ────────────────────────────────────────────────────────────────
_WOULD_ENTER_MIN = 75
_WATCH_MIN = 60

# Gap thresholds
_GAP_STRONG = 5.0
_GAP_MODERATE = 2.0
_GAP_EXTREME = 25.0

# Volume thresholds
_DOLLAR_VOL_STRONG = 5_000_000.0   # $5M
_MENTIONS_HIGH = 200

# Hard-block sentinel
_HARD_BLOCK_SCORE = -999


def _safe_float(val: Any) -> float | None:
    if val is None:
        return None
    try:
        f = float(val)
    except (TypeError, ValueError):
        return None
    import math
    return f if math.isfinite(f) else None


# ── Premarket lookup helper ────────────────────────────────────────────────────

def _build_premarket_lookup(snap: dict | None) -> dict[str, dict]:
    """
    Build {symbol: mover_dict} from premarket snapshot top lists.
    Merges top_gainers + top_losers + top_movers in priority order.
    Returns {} if snap is None/empty.
    """
    if not snap:
        return {}
    result: dict[str, dict] = {}
    for lst_key in ("top_movers", "top_gainers", "top_losers"):
        for m in snap.get(lst_key) or []:
            sym = (m.get("symbol") or "").upper()
            if sym and sym not in result:
                result[sym] = m
    # Overwrite with gainers/losers if they have more precise rank
    for lst_key in ("top_gainers", "top_losers"):
        for m in snap.get(lst_key) or []:
            sym = (m.get("symbol") or "").upper()
            if sym:
                result[sym] = m
    return result


# ── Reddit lookup helper ───────────────────────────────────────────────────────

def _build_reddit_lookup(snap: dict | None) -> dict[str, dict]:
    """
    Build {ticker: result_dict} from reddit snapshot results.
    Returns {} if snap is None/empty.
    """
    if not snap:
        return {}
    result: dict[str, dict] = {}
    for row in snap.get("results") or []:
        ticker = (row.get("ticker") or "").upper()
        if ticker:
            result[ticker] = row
    # Also index spikes for spike_ratio lookup
    spike_map: dict[str, dict] = {}
    for sp in snap.get("spikes") or []:
        ticker = (sp.get("ticker") or "").upper()
        if ticker:
            spike_map[ticker] = sp
    for ticker, row in result.items():
        if ticker in spike_map:
            row = dict(row)
            row["_spike"] = spike_map[ticker]
            result[ticker] = row
    return result


# ── Core scoring function ─────────────────────────────────────────────────────

def compute_shadow_score(
    symbol: str,
    quality: dict,
    scoring: dict,
    tick_regime: dict | None,
    premarket_snap: dict | None,
    reddit_snap: dict | None,
    blocked_cat_types: set[str] | None = None,
    premarket_lookup: dict[str, dict] | None = None,
    reddit_lookup: dict[str, dict] | None = None,
) -> dict[str, Any]:
    """
    Compute enhanced shadow opportunity score for a single candidate.

    Returns a dict with:
      enhanced_shadow_score, enhanced_shadow_decision,
      enhanced_shadow_reason, enhanced_shadow_components,
      enhanced_shadow_blockers, enhanced_shadow_confidence,
      premarket_rank, premarket_gap_percent, premarket_dollar_volume,
      premarket_volume, premarket_source, premarket_mode, premarket_boost,
      reddit_rank, reddit_mentions, reddit_spike_ratio, reddit_boost.

    Never raises. Shadow fields only — does not touch eligible/action/entry_mode.
    """
    sym = symbol.upper()
    components: dict[str, int] = {}
    blockers: list[str] = []
    hard_blocked = False

    # ── Lazy-build lookups from snapshots if not pre-built ────────────────────
    pm_lookup = premarket_lookup if premarket_lookup is not None else _build_premarket_lookup(premarket_snap)
    rd_lookup = reddit_lookup if reddit_lookup is not None else _build_reddit_lookup(reddit_snap)

    # ── Candidate raw fields ──────────────────────────────────────────────────
    change_pct   = _safe_float(quality.get("change_percent")) or 0.0
    volume_ratio = _safe_float(quality.get("volume_ratio"))
    spread_pct   = _safe_float(quality.get("spread_percent"))
    is_tradable  = bool(quality.get("tradable"))
    marketdata_stale = bool(quality.get("marketdata_stale") or quality.get("_marketdata_stale"))

    cat_type           = scoring.get("catalyst_type") or scoring.get("cat_type")
    catalyst_sentiment = scoring.get("catalyst_sentiment")
    materiality_score  = _safe_float(scoring.get("catalyst_materiality_score")) or 0.0
    total_score        = _safe_float(scoring.get("total_score")) or 0.0
    momentum_score_raw = _safe_float(scoring.get("components", {}).get("momentum_score")) if scoring.get("components") else None

    premarket_mode_val = (premarket_snap or {}).get("mode", "unknown") if premarket_snap else None

    # ── Hard blockers ─────────────────────────────────────────────────────────
    if not is_tradable and not quality:
        blockers.append("missing_marketdata")
        hard_blocked = True

    if spread_pct is not None and spread_pct > 1.0:
        blockers.append(f"spread_too_wide:{spread_pct:.2f}%")
        hard_blocked = True

    if marketdata_stale:
        blockers.append("stale_marketdata")
        hard_blocked = True

    if blocked_cat_types:
        for _c_key in ("catalyst_type", "cat_type"):
            _ct = scoring.get(_c_key)
            if _ct and _ct in blocked_cat_types:
                blockers.append(f"catalyst_type_blocked:{_ct}")
                hard_blocked = True
                break

    if catalyst_sentiment == "bearish" and materiality_score >= 0.8:
        blockers.append("strong_bearish_catalyst")
        hard_blocked = True

    # ── 1. Base score from current engine ─────────────────────────────────────
    base = int(min(40, max(0, (total_score / 100.0) * 40)))
    components["base_engine_score"] = base

    # ── 2. Market/momentum variables ─────────────────────────────────────────
    regime = (tick_regime or {}).get("regime", "unknown")
    risk_on_score = _safe_float((tick_regime or {}).get("risk_on_score"))

    if momentum_score_raw is not None and momentum_score_raw >= 18:
        components["momentum_score"] = 10
    elif momentum_score_raw is not None and momentum_score_raw >= 12:
        components["momentum_score"] = 5
    else:
        components["momentum_score"] = 0

    if change_pct >= 2.0:
        components["change_percent"] = 8
    elif change_pct >= 1.0:
        components["change_percent"] = 4
    else:
        components["change_percent"] = 0

    if volume_ratio is not None and volume_ratio >= 1.5:
        components["volume_ratio"] = 8
    elif volume_ratio is not None and volume_ratio >= 1.0:
        components["volume_ratio"] = 3
    else:
        components["volume_ratio"] = 0

    if spread_pct is not None and spread_pct <= 0.20:
        components["spread"] = 5
    elif spread_pct is not None and spread_pct <= 0.40:
        components["spread"] = 2
    else:
        components["spread"] = 0

    if regime == "risk_on":
        components["market_regime"] = 5
    elif regime == "risk_off":
        components["market_regime"] = -10
    else:
        components["market_regime"] = 0

    # ── 3. Catalyst quality ───────────────────────────────────────────────────
    _cat_score = 0
    if cat_type == "earnings":
        _cat_score = 10
    elif cat_type == "m_and_a":
        _cat_score = 8
    elif cat_type == "fda_regulatory":
        blockers.append("fda_regulatory_hard_block")
        hard_blocked = True
        _cat_score = _HARD_BLOCK_SCORE
    elif cat_type == "generic_news":
        _cat_score = 2
    elif cat_type == "macro":
        _cat_score = -2
    elif cat_type is not None:
        _cat_score = 3
    components["catalyst_quality"] = max(_HARD_BLOCK_SCORE, _cat_score)

    # ── 4. Premarket intelligence ─────────────────────────────────────────────
    pm_mover = pm_lookup.get(sym)
    pm_rank          = int(pm_mover["rank"]) if pm_mover and pm_mover.get("rank") else None
    pm_gap           = _safe_float(pm_mover.get("gap_percent")) if pm_mover else None
    pm_dollar_vol    = _safe_float(pm_mover.get("dollar_volume")) if pm_mover else None
    pm_day_vol       = pm_mover.get("day_volume") if pm_mover else None
    pm_source        = pm_mover.get("source") if pm_mover else None

    pm_boost = 0
    if pm_rank is not None:
        if pm_rank <= 30 and premarket_mode_val == "full_universe":
            pm_boost += 15
        elif pm_rank <= 100:
            pm_boost += 8
    if pm_gap is not None:
        abs_gap = abs(pm_gap)
        if abs_gap >= _GAP_STRONG:
            pm_boost += 10
        elif abs_gap >= _GAP_MODERATE:
            pm_boost += 5
        if abs_gap > _GAP_EXTREME and (pm_dollar_vol is None or pm_dollar_vol < _DOLLAR_VOL_STRONG):
            pm_boost -= 5
    if pm_dollar_vol is not None and pm_dollar_vol >= _DOLLAR_VOL_STRONG:
        pm_boost += 5
    components["premarket_boost"] = pm_boost

    # ── 5. Reddit intelligence ────────────────────────────────────────────────
    rd_row          = rd_lookup.get(sym)
    rd_rank         = int(rd_row["rank"]) if rd_row and rd_row.get("rank") else None
    rd_mentions     = int(rd_row["mentions"]) if rd_row and rd_row.get("mentions") else None
    rd_spike_info   = rd_row.get("_spike") if rd_row else None
    rd_spike_ratio  = _safe_float(rd_spike_info.get("spike_ratio")) if rd_spike_info else None

    rd_boost = 0
    if rd_rank is not None:
        if rd_rank <= 10:
            rd_boost += 10
        elif rd_rank <= 30:
            rd_boost += 6
        elif rd_rank <= 100:
            rd_boost += 3
    if rd_spike_ratio is not None and rd_spike_ratio >= 3.0:
        rd_boost += 10
    elif rd_spike_ratio is not None and rd_spike_ratio >= 2.0:
        rd_boost += 5
    if rd_mentions is not None and rd_mentions >= _MENTIONS_HIGH:
        rd_boost += 3
    components["reddit_boost"] = rd_boost

    # ── Final score ───────────────────────────────────────────────────────────
    if hard_blocked or components.get("catalyst_quality") == _HARD_BLOCK_SCORE:
        final_score = 0
    else:
        final_score = (
            components["base_engine_score"]
            + components["momentum_score"]
            + components["change_percent"]
            + components["volume_ratio"]
            + components["spread"]
            + components["market_regime"]
            + components["catalyst_quality"]
            + components["premarket_boost"]
            + components["reddit_boost"]
        )
        final_score = max(0, min(100, final_score))

    # ── Decision ─────────────────────────────────────────────────────────────
    if hard_blocked:
        decision = "WOULD_REJECT"
        reason_parts = ["hard_block: " + "; ".join(blockers)]
    elif final_score >= _WOULD_ENTER_MIN:
        decision = "WOULD_ENTER"
        reason_parts = []
        if pm_boost > 0:
            reason_parts.append(f"premarket_boost={pm_boost}")
        if rd_boost > 0:
            reason_parts.append(f"reddit_boost={rd_boost}")
        reason_parts.append(f"score={final_score}")
    elif final_score >= _WATCH_MIN:
        decision = "WATCH"
        reason_parts = [f"score={final_score}"]
        if pm_boost > 0:
            reason_parts.append(f"premarket_boost={pm_boost}")
    else:
        decision = "WOULD_REJECT"
        reason_parts = [f"score={final_score}_below_threshold"]

    # ── Confidence ────────────────────────────────────────────────────────────
    data_sources = 0
    if pm_mover:
        data_sources += 1
    if rd_row:
        data_sources += 1
    if total_score > 0:
        data_sources += 1
    if volume_ratio is not None:
        data_sources += 1
    if data_sources >= 3:
        confidence = "high"
    elif data_sources >= 2:
        confidence = "medium"
    else:
        confidence = "low"

    return {
        # Core shadow fields
        "enhanced_shadow_score":      final_score,
        "enhanced_shadow_decision":   decision,
        "enhanced_shadow_reason":     "; ".join(reason_parts) if reason_parts else "no_reason",
        "enhanced_shadow_components": components,
        "enhanced_shadow_blockers":   blockers,
        "enhanced_shadow_confidence": confidence,
        # Premarket intelligence fields
        "premarket_rank":         pm_rank,
        "premarket_gap_percent":  pm_gap,
        "premarket_dollar_volume": pm_dollar_vol,
        "premarket_volume":       pm_day_vol,
        "premarket_source":       pm_source,
        "premarket_mode":         premarket_mode_val,
        "premarket_boost":        pm_boost,
        # Reddit intelligence fields
        "reddit_rank":            rd_rank,
        "reddit_mentions":        rd_mentions,
        "reddit_spike_ratio":     rd_spike_ratio,
        "reddit_boost":           rd_boost,
    }
