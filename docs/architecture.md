# Architecture

## Decision Flow

Every trade opportunity flows through this pipeline in strict order:

```
1. Market Data Ingestion
      ↓
   Polygon REST + WebSocket feeds provide price, volume, and quote data.

2. Catalyst Collection
      ↓
   External events are gathered: news, SEC filings, insider activity, etc.

3. AI / NLP Catalyst Interpretation
      ↓
   The AI layer reads catalyst text and produces a structured scoring object.
   AI does NOT place trades or generate orders.

4. Catalyst Scoring
      ↓
   Scores are normalized (sentiment, urgency, confidence, impact window).

5. Market Confirmation
      ↓
   The engine checks technical conditions: price action, volume, spread,
   relative volume — confirming that market structure supports the catalyst.

6. Risk-Manager Approval
      ↓
   The risk manager evaluates the opportunity against all active controls:
   daily loss limit, per-trade risk, open position count, ticker cooldown,
   and kill-switch state. The risk manager has ABSOLUTE VETO POWER.
   No position is opened without risk-manager approval.

7. Paper Execution
      ↓
   Approved trades are sent to the paper execution layer.
   No broker API calls. No real money involved.

8. P&L and Analytics Dashboard
      ↓
   All paper trades, outcomes, and signals are recorded for analysis.
   The frontend dashboard visualizes performance in real time.
```

## Key Principle

**AI is not the execution authority.**

The AI layer provides structured interpretation of external information.
It may recommend that the engine evaluate an opportunity.
It may not recommend direct order execution.
All execution decisions rest with the risk manager.
