# Risk Policy

## Principle

**The risk manager has absolute veto power.**

No trade is opened without explicit risk-manager approval. No AI output,
no catalyst score, and no technical signal can override the risk manager.

---

## Mandatory Controls

All of the following controls are enforced at all times:

| Control | Description |
|---|---|
| **Daily max loss** | Total paper P&L loss for the day cannot exceed a defined limit. When hit, no new positions open for the remainder of the session. |
| **Per-trade max risk** | Each individual trade has a hard cap on maximum loss exposure (dollar or percent of paper capital). |
| **Max open positions** | No more than a defined number of positions may be open simultaneously. |
| **Max trades per day** | Total trade count for the day is capped regardless of P&L state. |
| **Ticker cooldown after loss** | After a losing trade on a specific ticker, that ticker is blocked from re-entry for a cooldown period. |
| **Duplicate signal suppression** | If the same signal or catalyst fires multiple times in a short window, only the first is evaluated; duplicates are discarded. |
| **Kill switch** | A global kill switch halts all new position opening immediately. Existing positions follow their defined exit rules. |

---

## Evaluation Order

```
Signal arrives
    ↓
Risk manager checks kill switch → if ON: reject
    ↓
Risk manager checks daily loss limit → if hit: reject
    ↓
Risk manager checks daily trade count → if hit: reject
    ↓
Risk manager checks open position count → if at max: reject
    ↓
Risk manager checks ticker cooldown → if active: reject
    ↓
Risk manager checks per-trade max risk → if exceeds limit: reject
    ↓
APPROVED → engine proceeds to paper execution
```

---

## Non-Negotiable

No module, including the AI layer, the engine, or the catalyst scorer,
may bypass, override, or disable any risk-manager control.
