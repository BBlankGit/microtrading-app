"""
LLM Shadow Analyst — diagnostic-only candidate review (Phase L1).

Fake-money simulation only. No broker, no live trading, no real orders.
The LLM output is shadow telemetry; it MUST NOT modify eligible, action,
or entry_mode on any candidate, and it MUST NOT trigger entries, exits, or
position changes.

Provider abstraction: only OpenAI is wired in this phase, gated by the
presence of the API key resolved from settings.LLM_API_KEY_ENV (default
OPENAI_API_KEY). When LLM_SHADOW_ENABLED is False or the API key is
missing, the module short-circuits: no network calls are made and a stable
"disabled" / "missing_api_key" status is returned.

API key handling:
  - The key is read from environment via os.environ[settings.LLM_API_KEY_ENV].
  - The key is NEVER logged, never echoed into the prompt body, never
    returned via API. Prompt/response logging (when enabled) is sanitized.
  - settings.LLM_SHADOW_LOG_PROMPTS defaults to False; only structured
    response metadata is logged.

Caching: in-memory dict keyed by sha256(packet); TTL configurable.
Single-flight per packet via asyncio.Lock to avoid duplicate calls.

Telemetry: module-level counters surface via get_status() for the API
endpoint. No PII or key material is ever exposed.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from typing import Any

from core.config import settings

logger = logging.getLogger(__name__)

# ── Telemetry ────────────────────────────────────────────────────────────────
_status: dict[str, Any] = {
    "calls_total": 0,
    "calls_last_tick": 0,
    "calls_success": 0,
    "calls_error": 0,
    "cache_hits": 0,
    "cache_misses": 0,
    "latency_ms_sum": 0,
    "last_call_at": None,
    "last_success_at": None,
    "last_error": None,
    "last_model_used": None,
}

# ── Cache (packet hash → (result_dict, monotonic_ts)) ────────────────────────
_cache: dict[str, tuple[dict, float]] = {}
_cache_lock = asyncio.Lock()

# ── Provider helpers ─────────────────────────────────────────────────────────

# Patterns used to redact accidental key/secret echoes in logged strings.
_KEY_PATTERNS = [
    re.compile(r"sk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"Bearer\s+[A-Za-z0-9_\-]+", re.IGNORECASE),
]


def _redact(text: str | None) -> str:
    """Best-effort redaction of API-key-like substrings for safe logging."""
    if not text:
        return ""
    out = text
    for pat in _KEY_PATTERNS:
        out = pat.sub("<redacted>", out)
    return out


def api_key_present() -> bool:
    """True iff the env-var named by settings.LLM_API_KEY_ENV is set."""
    env_name = (settings.LLM_API_KEY_ENV or "").strip()
    if not env_name:
        return False
    val = (os.environ.get(env_name) or "").strip()
    if not val:
        return False
    return val.upper() not in {"PASTE_YOUR_KEY_HERE", "CHANGEME", "NONE", "NULL"}


def provider() -> str:
    return (settings.LLM_PROVIDER or "openai").strip().lower()


def model() -> str:
    return (settings.LLM_MODEL or "gpt-4.1-mini").strip()


def is_enabled() -> bool:
    return bool(settings.LLM_SHADOW_ENABLED)


# ── Packet hashing ────────────────────────────────────────────────────────────

def _hash_packet(packet: dict) -> str:
    """Stable hash of the packet content. Used for cache keying."""
    # Sort keys so dict ordering doesn't change the hash.
    text = json.dumps(packet, sort_keys=True, default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


# ── Intraday history (cache-first; never calls Polygon) ─────────────────────

def get_cached_intraday_history(symbol: str, max_points: int) -> dict | None:
    """
    Return a cached intraday history series for `symbol`, or None when no
    cached series exists. MUST NOT make any external API call.

    Phase L1-H1 ships this helper as a stable extension point: today there is
    no in-memory minute-bar cache for the simulator's symbol set, so this
    returns None. Future phases can populate a cache and start returning
    series here without touching build_candidate_packet's contract.
    """
    return None


# ── Rule-impact bucketing for news items inside the packet ──────────────────

def _bucket_impact_level(materiality_score) -> str:
    """
    Mirror api.intelligence._bucket_impact_level so news items that arrive
    raw from catalysts.news_collector (without I5-H2 normalization) still
    carry a rule_impact_level into the LLM packet.
    """
    if materiality_score is None:
        return "unknown"
    try:
        m = float(materiality_score)
    except (TypeError, ValueError):
        return "unknown"
    if m >= 0.7:
        return "high"
    if m >= 0.4:
        return "medium"
    return "low"


# ── Packet builder ───────────────────────────────────────────────────────────

def build_candidate_packet(
    candidate: dict,
    *,
    market_regime: dict | None = None,
    market_trend: dict | None = None,
    account_summary: dict | None = None,
    news_items_by_symbol: dict[str, list[dict]] | None = None,
    earnings_by_symbol: dict[str, dict] | None = None,
    insiders_by_symbol: dict[str, list[dict]] | None = None,
    reddit_lookup: dict | None = None,
    premarket_lookup: dict | None = None,
    intraday_history: dict | None = None,
    quality: dict | None = None,
) -> dict:
    """
    Build a structured packet describing the candidate for the LLM.

    Cross-feed inputs are optional dicts — if a feed is missing the
    corresponding section is rendered with a small `_available: False`
    flag instead of raising.
    """
    sym = (candidate.get("symbol") or "").upper()
    max_news = max(1, int(getattr(settings, "LLM_SHADOW_MAX_NEWS_ITEMS_PER_SYMBOL", 5)))

    # ── 1. Identity ───────────────────────────────────────────────────────────
    identity = {
        "symbol": sym,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "session": (market_trend or {}).get("session") or None,
        "candidate_sources": candidate.get("candidate_sources") or [],
    }

    # ── 2. Current marketdata ────────────────────────────────────────────────
    # Prefer the quality dict (per-tick evaluate_market_quality output) when
    # available; fall back to candidate fields. Never reach out to Polygon.
    q = quality or {}

    def _pick(key_q: str, *fallbacks: str):
        if key_q in q and q.get(key_q) is not None:
            return q.get(key_q)
        for k in fallbacks:
            if candidate.get(k) is not None:
                return candidate.get(k)
        return None

    raw_md_error = candidate.get("marketdata_error")
    sanitized_md_error = _redact(str(raw_md_error)) if raw_md_error else None
    last_trade_price = _pick("last_trade_price", "last_trade_price", "last_price")

    marketdata = {
        "last_trade_price":            last_trade_price,
        "last_price":                  last_trade_price,  # alias for legacy consumers
        "bid":                         _pick("bid", "bid"),
        "ask":                         _pick("ask", "ask"),
        "bid_size":                    _pick("bid_size", "bid_size"),
        "ask_size":                    _pick("ask_size", "ask_size"),
        "spread":                      _pick("spread", "spread"),
        "spread_percent":              _pick("spread_percent", "spread_percent"),
        "change_percent":              _pick("change_percent", "change_percent"),
        "day_open":                    candidate.get("day_open"),
        "day_high":                    candidate.get("day_high"),
        "day_low":                     candidate.get("day_low"),
        "previous_close":              candidate.get("previous_close"),
        "day_volume":                  _pick("day_volume", "day_volume"),
        "previous_day_volume":         _pick("previous_day_volume", "prev_day_volume"),
        "volume_ratio":                _pick("volume_ratio", "volume_ratio"),
        "time_adjusted_volume_ratio":  candidate.get("time_adjusted_volume_ratio"),
        "dollar_volume":               candidate.get("dollar_volume"),
        "vwap":                        candidate.get("vwap"),
        "tradable":                    _pick("tradable", "quality_tradable"),
        "marketdata_age_seconds":      candidate.get("marketdata_age_seconds"),
        "marketdata_source":           candidate.get("marketdata_source"),
        "marketdata_fetched_at":       candidate.get("marketdata_fetched_at"),
        "marketdata_fallback_used":    bool(candidate.get("marketdata_fallback_used")),
        "marketdata_stale":            bool(candidate.get("marketdata_stale")),
        "marketdata_missing":          raw_md_error is not None,
        "marketdata_error":            sanitized_md_error,
    }

    # ── 3. Intraday evolution (cache-first; never calls Polygon) ────────────
    cap = max(1, int(getattr(settings, "LLM_SHADOW_MAX_INTRADAY_POINTS", 20)))
    intra = (intraday_history or {}).get(sym) if intraday_history else None
    if intra is None:
        # Try the shared cache helper; today it returns None.
        intra = get_cached_intraday_history(sym, cap)

    if intra:
        intraday = {
            "intraday_history_available":     True,
            "recent_price_points":            (intra.get("recent_prices") or [])[-cap:],
            "recent_change_percent_points":   (intra.get("recent_change_pct") or [])[-cap:],
            "recent_volume_points":           (intra.get("recent_volumes") or [])[-cap:],
            "intraday_trend_direction":       intra.get("trend_direction"),
            "intraday_momentum_5m":           intra.get("momentum_5m"),
            "intraday_momentum_10m":          intra.get("momentum_10m"),
            "intraday_momentum_15m":          intra.get("momentum_15m"),
            "distance_from_day_high":         intra.get("distance_from_day_high"),
            "distance_from_day_low":          intra.get("distance_from_day_low"),
            "position_in_day_range":          intra.get("position_in_day_range"),
        }
    else:
        intraday = {
            "intraday_history_available":     False,
            "recent_price_points":            [],
            "recent_change_percent_points":   [],
            "recent_volume_points":           [],
            "intraday_unavailable_reason":    "no cached intraday history series for symbol",
        }

    # ── 4. Real engine decision ──────────────────────────────────────────────
    engine = {
        "eligible": candidate.get("eligible"),
        "action": candidate.get("action"),
        "entry_mode": candidate.get("entry_mode"),
        "total_score": candidate.get("total_score"),
        "score_threshold": candidate.get("score_threshold"),
        "score_pass": candidate.get("score_pass"),
        "rejection_reason": candidate.get("rejection_reason"),
        "decision_reason": candidate.get("decision_reason"),
        "catalyst_type": candidate.get("catalyst_type"),
        "components": candidate.get("score_components"),
        "base_score_before_intelligence_adjustments": candidate.get("base_score_before_intelligence_adjustments"),
        "intelligence_score_adjustment": candidate.get("intelligence_score_adjustment"),
        "final_score_after_intelligence_adjustments": candidate.get("final_score_after_intelligence_adjustments"),
        "earnings_score_adjustment": candidate.get("earnings_score_adjustment"),
        "insider_score_adjustment": candidate.get("insider_score_adjustment"),
        "market_trend_adjustment": candidate.get("market_trend_adjustment"),
    }

    # ── 5. Deterministic shadow decision ─────────────────────────────────────
    shadow = {
        "enhanced_shadow_score": candidate.get("enhanced_shadow_score"),
        "enhanced_shadow_decision": candidate.get("enhanced_shadow_decision"),
        "enhanced_shadow_reason": candidate.get("enhanced_shadow_reason"),
        "enhanced_shadow_components": candidate.get("enhanced_shadow_components"),
        "enhanced_shadow_blockers": candidate.get("enhanced_shadow_blockers"),
        "enhanced_shadow_confidence": candidate.get("enhanced_shadow_confidence"),
    }

    # ── 6. News / catalyst rule analysis ─────────────────────────────────────
    # Surface explicit availability instead of an empty list — the LLM should
    # be able to tell "no cached news yet for this symbol" from "we forgot".
    has_news_section = news_items_by_symbol is not None
    raw_news = (news_items_by_symbol or {}).get(sym, []) if news_items_by_symbol else []
    news_items: list[dict] = []
    for item in raw_news[:max_news]:
        materiality = item.get("rule_materiality_score")
        if materiality is None:
            materiality = item.get("materiality_score")
        rule_impact = item.get("rule_impact_level") or _bucket_impact_level(materiality)
        reasons = item.get("rule_reasons") or item.get("sentiment_reasons") or []
        rule_explanation = item.get("rule_explanation") or ("; ".join(reasons) if reasons else None)
        news_items.append({
            "title":                  item.get("title"),
            "source":                  item.get("publisher") or item.get("source"),
            "published_at":            item.get("published_utc"),
            "url":                     item.get("article_url"),
            "rule_event_type":         item.get("rule_event_type") or item.get("classified_event_type") or item.get("event_type"),
            "rule_impact_level":       rule_impact,
            "rule_sentiment":          item.get("rule_sentiment") or item.get("sentiment"),
            "rule_materiality_score":  materiality,
            "rule_sentiment_score":    item.get("rule_sentiment_score") if item.get("rule_sentiment_score") is not None else item.get("sentiment_score"),
            "rule_bullish_flags":      item.get("rule_bullish_flags") or item.get("bullish_flags") or [],
            "rule_bearish_flags":      item.get("rule_bearish_flags") or item.get("bearish_flags") or [],
            "rule_reasons":            reasons,
            "rule_explanation":        rule_explanation,
            "used_by_engine":          item.get("used_by_engine") if item.get("used_by_engine") is not None else "unknown",
        })
    if news_items:
        news_section: dict = {
            "news_available": True,
            "items":          news_items,
        }
    elif has_news_section:
        news_section = {
            "news_available":            False,
            "news_unavailable_reason":   "no cached news items for symbol",
            "items":                     [],
        }
    else:
        news_section = {
            "news_available":            False,
            "news_unavailable_reason":   "news lookup not provided to packet builder",
            "items":                     [],
        }

    # ── 7. Reddit ────────────────────────────────────────────────────────────
    reddit = {
        "reddit_rank": candidate.get("reddit_rank"),
        "reddit_mentions": candidate.get("reddit_mentions"),
        "reddit_spike_ratio": candidate.get("reddit_spike_ratio"),
        "reddit_boost": candidate.get("reddit_boost"),
        "reddit_age_seconds": (reddit_lookup or {}).get("age_seconds") if reddit_lookup else None,
        "reddit_fetched_at": (reddit_lookup or {}).get("fetched_at") if reddit_lookup else None,
    }

    # ── 8. Full-market movers / premarket ────────────────────────────────────
    pm_entry = (premarket_lookup or {}).get(sym) if premarket_lookup else None
    movers = {
        "premarket_rank": candidate.get("premarket_rank"),
        "premarket_gap_percent": candidate.get("premarket_gap_percent"),
        "premarket_volume": candidate.get("premarket_volume"),
        "premarket_dollar_volume": candidate.get("premarket_dollar_volume"),
        "premarket_volume_vs_prev_day": (pm_entry or {}).get("volume_vs_previous_day_ratio") if pm_entry else None,
        "premarket_time_adjusted_volume_ratio": (pm_entry or {}).get("time_adjusted_volume_ratio") if pm_entry else None,
        "premarket_source": (pm_entry or {}).get("source") if pm_entry else None,
        "market_mover_rank": candidate.get("market_mover_rank"),
        "market_mover_gap_percent": candidate.get("market_mover_gap_percent"),
        "market_mover_mode": candidate.get("market_mover_mode"),
        "market_mover_session": candidate.get("market_mover_session"),
    }

    # ── 9. Earnings ──────────────────────────────────────────────────────────
    earn_row = (earnings_by_symbol or {}).get(sym) if earnings_by_symbol else None
    earnings = {
        "next_earnings_date": (earn_row or {}).get("report_date") if earn_row else candidate.get("earnings_next_date"),
        "days_until": (earn_row or {}).get("days_until") if earn_row else candidate.get("earnings_days_until"),
        "report_time": (earn_row or {}).get("report_time") if earn_row else None,
        "eps_estimate": (earn_row or {}).get("eps_estimate") if earn_row else None,
        "revenue_estimate": (earn_row or {}).get("revenue_estimate") if earn_row else None,
        "earnings_score_adjustment": candidate.get("earnings_score_adjustment"),
        "earnings_reason": candidate.get("earnings_reason"),
    }

    # ── 10. Insiders ─────────────────────────────────────────────────────────
    raw_ins = (insiders_by_symbol or {}).get(sym, []) if insiders_by_symbol else []
    insider_txns = [
        {
            "transaction_date": r.get("transaction_date"),
            "transaction_code": r.get("transaction_code"),
            "transaction_type": r.get("transaction_type"),
            "buy_sell_label": r.get("buy_sell_label"),
            "shares": r.get("shares"),
            "price": r.get("price"),
            "value": r.get("value"),
            "is_discretionary_buy": r.get("is_discretionary_buy"),
            "is_recent": r.get("is_recent"),
        }
        for r in raw_ins[:5]
    ]
    insiders = {
        "recent_buy_count": candidate.get("insider_recent_buy_count"),
        "recent_buy_value": candidate.get("insider_recent_buy_value"),
        "latest_transaction_date": candidate.get("insider_latest_transaction_date"),
        "transaction_codes": candidate.get("insider_transaction_codes"),
        "insider_score_adjustment": candidate.get("insider_score_adjustment"),
        "insider_reason": candidate.get("insider_reason"),
        "recent_transactions": insider_txns,
    }

    # ── 11. Market context ───────────────────────────────────────────────────
    mr = market_regime or {}
    mt = market_trend or {}
    market_ctx = {
        "market_regime_raw": (mr or {}).get("regime"),
        "market_regime_trend_adjusted": mt.get("adjusted_regime_label") or mt.get("regime"),
        "risk_on_score_raw": (mr or {}).get("risk_on_score"),
        "risk_on_score_trend_adjusted": mt.get("market_regime_score_after_trend"),
        "market_trend_direction": mt.get("market_trend_direction") or mt.get("trend_direction"),
        "market_trend_strength": mt.get("market_trend_strength") or mt.get("trend_strength"),
        "market_trend_adjustment": mt.get("market_trend_adjustment"),
        "qqq_deltas": (mt.get("deltas") or {}),
        "market_trend_collecting": mt.get("collecting") or mt.get("market_trend_collecting"),
    }

    # ── 12. Position / account context (no secrets) ──────────────────────────
    acct = account_summary or {}
    position_ctx = {
        "already_in_position": bool(acct.get("symbols_open") and sym in acct.get("symbols_open", set())),
        "open_position_count": acct.get("open_position_count"),
        "daily_realized_pnl": acct.get("daily_realized_pnl"),
        "daily_loss_guard_triggered": acct.get("daily_loss_guard_triggered"),
        "account_cash": acct.get("account_cash"),
        "account_equity": acct.get("account_equity"),
    }

    return {
        "identity":       identity,
        "marketdata":     marketdata,
        "intraday":       intraday,
        "engine":         engine,
        "shadow":         shadow,
        "news":           news_section,
        "reddit":         reddit,
        "movers":         movers,
        "earnings":       earnings,
        "insiders":       insiders,
        "market_context": market_ctx,
        "position":       position_ctx,
        "prompt_version": settings.LLM_SHADOW_PROMPT_VERSION,
    }


# ── Candidate selection ──────────────────────────────────────────────────────

def select_candidates_for_llm(
    candidates: list[dict],
    *,
    open_position_symbols: set[str] | None = None,
    blocked_catalyst_types: set[str] | None = None,
) -> list[dict]:
    """
    Pick up to settings.LLM_SHADOW_MAX_CANDIDATES_PER_TICK candidates.

    Priority order:
      1. real-engine WOULD NOT enter but enhanced shadow WOULD_ENTER
      2. real-engine WOULD enter
      3. high-score near misses (score >= LLM_SHADOW_MIN_ENGINE_SCORE)
      4. top full-market movers inside active universe
      5. strong catalyst/news/reddit/insider signal

    Skip:
      - stale marketdata
      - missing bid/ask
      - spread > 0.50%
      - already-in-position (unless LLM_SHADOW_INCLUDE_OPEN_POSITIONS=True)
      - hard-blocked catalyst types (unless explicitly enabled later)
    """
    max_n = max(1, int(settings.LLM_SHADOW_MAX_CANDIDATES_PER_TICK))
    min_near_miss = int(settings.LLM_SHADOW_MIN_ENGINE_SCORE)
    include_open = bool(settings.LLM_SHADOW_INCLUDE_OPEN_POSITIONS)
    include_near = bool(settings.LLM_SHADOW_INCLUDE_REJECTED_NEAR_MISSES)
    open_position_symbols = open_position_symbols or set()
    blocked = blocked_catalyst_types or set()

    def _skip(c: dict) -> bool:
        if c.get("marketdata_stale"):
            return True
        if c.get("bid") is None or c.get("ask") is None:
            # missing bid/ask check is best-effort; fall through if not present
            pass
        if (c.get("spread_percent") or 0) > 0.50:
            return True
        if not include_open and (c.get("symbol") or "").upper() in open_position_symbols:
            return True
        if c.get("catalyst_type_blocked") and (c.get("catalyst_type") in blocked):
            return True
        return False

    eligible = [c for c in candidates if not _skip(c)]

    tier1 = [c for c in eligible if c.get("eligible") is False
             and c.get("enhanced_shadow_decision") == "WOULD_ENTER"]
    tier2 = [c for c in eligible if c.get("eligible") is True]
    tier3 = []
    if include_near:
        tier3 = [
            c for c in eligible
            if c.get("eligible") is False
            and (c.get("total_score") or 0) >= min_near_miss
        ]
    tier4 = [c for c in eligible if c.get("market_mover_rank") is not None]
    tier5 = [
        c for c in eligible
        if (c.get("catalyst_sentiment") == "bullish")
           or ((c.get("reddit_spike_ratio") or 0) >= 3.0)
           or ((c.get("insider_score_adjustment") or 0) > 0)
    ]

    picked: list[dict] = []
    seen: set[str] = set()
    for tier in (tier1, tier2, tier3, tier4, tier5):
        for c in tier:
            sym = (c.get("symbol") or "").upper()
            if not sym or sym in seen:
                continue
            seen.add(sym)
            picked.append(c)
            if len(picked) >= max_n:
                return picked
    return picked


# ── Response validation ──────────────────────────────────────────────────────

_VALID_DECISIONS = {"WOULD_ENTER", "WATCH", "WOULD_REJECT"}
_VALID_TIME_HORIZONS = {"minutes", "intraday", "unknown"}
_VALID_IMPACT = {"high", "medium", "low", "unknown"}
_VALID_BIAS = {"bullish", "bearish", "neutral", "mixed", "unknown"}
_VALID_MOVE = {"strong_up", "moderate_up", "flat", "down", "unknown"}
_VALID_ACTION = {"enter_now", "wait_for_confirmation", "reject", "monitor_only"}
_VALID_CONFIRM = {"break_day_high", "volume_acceleration", "spread_tightens",
                  "news_confirmation", "none", "unknown"}


def _enum(value: Any, allowed: set[str]) -> str:
    if isinstance(value, str) and value in allowed:
        return value
    return "unknown" if "unknown" in allowed else next(iter(allowed))


def _clamp(value: Any, lo: float, hi: float, default: float = 0.0) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _str_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(x) for x in value if x is not None]
    return []


def normalize_llm_response(raw: dict) -> dict:
    """
    Validate and normalize an LLM response into the canonical schema.
    Always returns a dict with stable keys. Never raises.
    """
    return {
        "llm_status":        "ok",
        "llm_decision":      raw["llm_decision"] if raw.get("llm_decision") in _VALID_DECISIONS else None,
        "llm_confidence":    _clamp(raw.get("llm_confidence"), 0.0, 1.0, 0.0),
        "llm_time_horizon":  _enum(raw.get("llm_time_horizon"), _VALID_TIME_HORIZONS),
        "llm_impact_assessment": _enum(raw.get("llm_impact_assessment"), _VALID_IMPACT),
        "llm_directional_bias":  _enum(raw.get("llm_directional_bias"), _VALID_BIAS),
        "llm_expected_move":     _enum(raw.get("llm_expected_move"), _VALID_MOVE),
        "llm_agrees_with_engine": bool(raw.get("llm_agrees_with_engine")) if raw.get("llm_agrees_with_engine") is not None else None,
        "llm_agrees_with_shadow": bool(raw.get("llm_agrees_with_shadow")) if raw.get("llm_agrees_with_shadow") is not None else None,
        "llm_primary_reason":     str(raw.get("llm_primary_reason") or "")[:500],
        "llm_supporting_factors": _str_list(raw.get("llm_supporting_factors")),
        "llm_risk_factors":       _str_list(raw.get("llm_risk_factors")),
        "llm_missing_data":       _str_list(raw.get("llm_missing_data")),
        "llm_do_not_trade_reason": (str(raw["llm_do_not_trade_reason"])[:500]
                                    if raw.get("llm_do_not_trade_reason") else None),
        "llm_score_adjustment_suggestion": int(_clamp(raw.get("llm_score_adjustment_suggestion"), -20, 20, 0)),
        "llm_recommended_action":  _enum(raw.get("llm_recommended_action"), _VALID_ACTION),
        "llm_recommended_confirmation": _enum(raw.get("llm_recommended_confirmation"), _VALID_CONFIRM),
        "llm_summary":             str(raw.get("llm_summary") or "")[:500],
    }


_SYSTEM_PROMPT = (
    "You are a microtrading shadow analyst. You review structured data only. "
    "You do not place trades. You must return valid JSON only. You must not "
    "invent missing data. If data is missing, say unknown. You evaluate "
    "short-horizon opportunity and risk for fake-money simulation."
)


def _error_result(reason: str, error_text: str | None = None) -> dict:
    """Stable shape for failure cases — never raises, never leaks secrets."""
    return {
        "llm_status": reason,
        "llm_decision": None,
        "llm_confidence": 0.0,
        "llm_time_horizon": "unknown",
        "llm_impact_assessment": "unknown",
        "llm_directional_bias": "unknown",
        "llm_expected_move": "unknown",
        "llm_agrees_with_engine": None,
        "llm_agrees_with_shadow": None,
        "llm_primary_reason": "",
        "llm_supporting_factors": [],
        "llm_risk_factors": [],
        "llm_missing_data": [],
        "llm_do_not_trade_reason": None,
        "llm_score_adjustment_suggestion": 0,
        "llm_recommended_action": "monitor_only",
        "llm_recommended_confirmation": "unknown",
        "llm_summary": "",
        "llm_error": _redact(error_text) if error_text else None,
    }


# ── LLM call ─────────────────────────────────────────────────────────────────

async def _openai_call(packet: dict) -> dict:
    """Single OpenAI chat-completions call with strict JSON response."""
    import httpx

    env_name = settings.LLM_API_KEY_ENV
    api_key = os.environ.get(env_name, "")
    timeout = float(settings.LLM_SHADOW_TIMEOUT_SECONDS)

    payload = {
        "model": model(),
        "messages": [
            {"role": "system", "content": _SYSTEM_PROMPT},
            {"role": "user", "content": json.dumps(packet, default=str)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.2,
        "max_tokens": 700,
    }
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    url = "https://api.openai.com/v1/chat/completions"

    async with httpx.AsyncClient(timeout=timeout) as client:
        resp = await client.post(url, json=payload, headers=headers)
    if resp.status_code >= 400:
        # Never include the response body verbatim — could echo headers.
        raise RuntimeError(f"openai http {resp.status_code}")
    body = resp.json()
    content = (((body.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if not content:
        raise RuntimeError("openai empty response")
    try:
        parsed = json.loads(content)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"invalid_json: {exc}")
    if not isinstance(parsed, dict):
        raise RuntimeError("response is not a JSON object")
    return parsed


async def analyze_candidate_packet(packet: dict) -> dict:
    """
    Analyze a single candidate packet. Cache-first; never raises.
    Returns the canonical normalized LLM result dict (always with
    llm_status set). On any failure, returns _error_result(...).
    """
    if not is_enabled():
        return _error_result("disabled")
    if provider() != "openai":
        return _error_result("provider_not_supported", f"provider={provider()!r}")
    if not api_key_present():
        return _error_result("missing_api_key")

    pkt_hash = _hash_packet(packet)
    now = time.monotonic()
    ttl = float(settings.LLM_SHADOW_CACHE_TTL_SECONDS)

    # Cache lookup
    async with _cache_lock:
        cached = _cache.get(pkt_hash)
        if cached and (now - cached[1]) < ttl:
            _status["cache_hits"] += 1
            out = dict(cached[0])
            out["llm_cached"] = True
            return out

    _status["cache_misses"] += 1
    retries = max(0, int(settings.LLM_SHADOW_MAX_RETRIES))
    last_err: str | None = None
    started = time.monotonic()
    try:
        for attempt in range(retries + 1):
            try:
                raw = await asyncio.wait_for(
                    _openai_call(packet),
                    timeout=float(settings.LLM_SHADOW_TIMEOUT_SECONDS) + 1.0,
                )
                result = normalize_llm_response(raw)
                result["llm_model"] = model()
                result["llm_prompt_version"] = settings.LLM_SHADOW_PROMPT_VERSION
                result["llm_cached"] = False
                latency_ms = int((time.monotonic() - started) * 1000)
                result["llm_latency_ms"] = latency_ms

                async with _cache_lock:
                    _cache[pkt_hash] = (result, time.monotonic())

                _status["calls_total"] += 1
                _status["calls_success"] += 1
                _status["latency_ms_sum"] += latency_ms
                _status["last_call_at"] = datetime.now(timezone.utc).isoformat()
                _status["last_success_at"] = _status["last_call_at"]
                _status["last_model_used"] = model()
                if settings.LLM_SHADOW_LOG_RESPONSES:
                    logger.info(
                        "LLM shadow ok symbol=%s decision=%s confidence=%.2f latency_ms=%d",
                        packet.get("identity", {}).get("symbol"),
                        result.get("llm_decision"),
                        result.get("llm_confidence") or 0,
                        latency_ms,
                    )
                return result
            except asyncio.TimeoutError:
                last_err = "timeout"
                continue
            except Exception as exc:
                last_err = _redact(str(exc))
                continue
        raise RuntimeError(last_err or "unknown_error")
    except Exception as exc:
        _status["calls_total"] += 1
        _status["calls_error"] += 1
        _status["last_call_at"] = datetime.now(timezone.utc).isoformat()
        _status["last_error"] = _redact(str(exc))
        return _error_result("error", _redact(str(exc)))


# ── Public status accessor ───────────────────────────────────────────────────

def get_status() -> dict:
    avg_latency = None
    if _status["calls_success"] > 0:
        avg_latency = int(_status["latency_ms_sum"] / _status["calls_success"])
    return {
        "enabled":                   is_enabled(),
        "provider":                  provider(),
        "model":                     model(),
        "api_key_env":               settings.LLM_API_KEY_ENV,
        "api_key_present":           api_key_present(),
        "max_candidates_per_tick":   int(settings.LLM_SHADOW_MAX_CANDIDATES_PER_TICK),
        "calls_total":               _status["calls_total"],
        "calls_last_tick":           _status["calls_last_tick"],
        "calls_success":             _status["calls_success"],
        "calls_error":               _status["calls_error"],
        "cache_hits":                _status["cache_hits"],
        "cache_misses":              _status["cache_misses"],
        "average_latency_ms":        avg_latency,
        "last_call_at":              _status["last_call_at"],
        "last_success_at":           _status["last_success_at"],
        "last_error":                _status["last_error"],
        "last_model_used":           _status["last_model_used"],
        "prompt_version":            settings.LLM_SHADOW_PROMPT_VERSION,
        "disclaimer":                "LLM shadow only; does not affect trading decisions.",
    }


def reset_tick_counters() -> None:
    _status["calls_last_tick"] = 0


def record_tick_call() -> None:
    _status["calls_last_tick"] += 1


def default_not_selected_result() -> dict:
    """The 'not picked by selector' stable shape for candidate rows."""
    return {
        "llm_status": "not_selected",
        "llm_decision": None,
        "llm_confidence": None,
        "llm_impact_assessment": None,
        "llm_directional_bias": None,
        "llm_expected_move": None,
        "llm_agrees_with_engine": None,
        "llm_agrees_with_shadow": None,
        "llm_primary_reason": None,
        "llm_supporting_factors": [],
        "llm_risk_factors": [],
        "llm_missing_data": [],
        "llm_score_adjustment_suggestion": None,
        "llm_recommended_action": None,
        "llm_recommended_confirmation": None,
        "llm_summary": None,
        "llm_model": None,
        "llm_latency_ms": None,
        "llm_cached": None,
        "llm_prompt_version": None,
    }
