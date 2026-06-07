from datetime import datetime, timezone
from typing import Any


def _parse_utc(s: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, AttributeError, TypeError):
        return None


def filter_catalysts(
    catalysts: list[dict[str, Any]],
    max_age_hours: int = 24,
) -> dict[str, Any]:
    """
    Deterministic freshness and relevance filter for normalized catalyst records.

    Rules (applied in order):
    1. Reject duplicate catalyst_id — keep first occurrence only.
    2. Reject if title is missing or empty.
    3. Reject if published_utc is missing or unparseable.
    4. Reject if age exceeds max_age_hours.
    5. Reject if raw_relevance_hint is not 'direct'.

    Accepted records gain two extra fields:
      freshness_age_hours (float, 2dp)
      filter_status = "accepted"

    No scoring, no sentiment inference, no recommended action.
    """
    now = datetime.now(timezone.utc)
    seen_ids: set[str] = set()
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []

    for catalyst in catalysts:
        catalyst_id = catalyst.get("catalyst_id", "")

        # Rule 1 — deduplicate: reject second+ occurrences immediately
        if catalyst_id in seen_ids:
            rejected.append({
                "catalyst": catalyst,
                "rejection_reasons": ["duplicate catalyst_id"],
            })
            continue
        seen_ids.add(catalyst_id)

        reasons: list[str] = []

        # Rule 2 — title
        title = catalyst.get("title")
        if not title or not str(title).strip():
            reasons.append("title is missing or empty")

        # Rule 3 — published_utc parseable
        published_utc = catalyst.get("published_utc")
        published_dt: datetime | None = None
        if not published_utc:
            reasons.append("published_utc is missing")
        else:
            published_dt = _parse_utc(published_utc)
            if published_dt is None:
                reasons.append("published_utc is invalid")

        # Rule 4 — freshness (only if we have a valid datetime)
        freshness_age_hours: float | None = None
        if published_dt is not None:
            freshness_age_hours = round(
                (now - published_dt).total_seconds() / 3600, 2
            )
            if freshness_age_hours > max_age_hours:
                reasons.append(
                    f"too old: {freshness_age_hours}h exceeds max {max_age_hours}h"
                )

        # Rule 5 — relevance hint
        if catalyst.get("raw_relevance_hint") != "direct":
            reasons.append("raw_relevance_hint is not 'direct'")

        if reasons:
            rejected.append({"catalyst": catalyst, "rejection_reasons": reasons})
        else:
            accepted.append({
                **catalyst,
                "freshness_age_hours": freshness_age_hours,
                "filter_status": "accepted",
            })

    return {
        "total_input": len(catalysts),
        "accepted_count": len(accepted),
        "rejected_count": len(rejected),
        "accepted": accepted,
        "rejected": rejected,
    }
