from dataclasses import dataclass, asdict


@dataclass
class Position:
    position_id: str
    symbol: str
    entry_price: float
    shares: float
    cost_basis: float
    entry_time: str       # ISO UTC
    entry_catalyst_type: str
    entry_score: int | None = None
    entry_mode: str | None = None

    def unrealized_pnl(self, current_price: float) -> float:
        return (current_price - self.entry_price) * self.shares

    def current_value(self, current_price: float) -> float:
        return current_price * self.shares

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ClosedTrade:
    position_id: str
    symbol: str
    entry_price: float
    exit_price: float
    shares: float
    cost_basis: float
    proceeds: float
    pnl: float
    pnl_percent: float
    entry_time: str
    exit_time: str
    exit_reason: str
    entry_catalyst_type: str
    hold_minutes: float
    entry_score: int | None = None
    entry_mode: str | None = None
    # Phase 2Q-Lite: virtual bracket intrabar exit metadata (all nullable)
    exit_intrabar_source: str | None = None
    exit_intrabar_high: float | None = None
    exit_intrabar_low: float | None = None
    exit_tp_price: float | None = None
    exit_sl_price: float | None = None
    exit_conservative_both_touched: bool = False

    def to_dict(self) -> dict:
        return asdict(self)
