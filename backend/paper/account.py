import uuid
from datetime import datetime, timezone
from typing import Optional

from paper.models import ClosedTrade, Position


class PaperAccount:
    """
    In-memory virtual account for the research paper simulator.

    No broker. No real orders. No real money.
    All positions and trades are purely simulated.
    """

    def __init__(self, starting_cash: float) -> None:
        self.starting_cash = starting_cash
        self.cash = starting_cash
        self.positions: dict[str, Position] = {}
        self.trades: list[ClosedTrade] = []
        self._daily_trade_count: int = 0
        self._daily_date: str = ""

    def reset(self) -> None:
        self.cash = self.starting_cash
        self.positions = {}
        self.trades = []
        self._daily_trade_count = 0
        self._daily_date = ""

    def today_str(self) -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def daily_trade_count(self) -> int:
        if self._daily_date != self.today_str():
            return 0
        return self._daily_trade_count

    def _refresh_daily_count(self) -> None:
        today = self.today_str()
        if self._daily_date != today:
            self._daily_trade_count = 0
            self._daily_date = today

    def can_enter(self, symbol: str, max_positions: int, max_trades: int) -> tuple[bool, str]:
        if symbol in self.positions:
            return False, "already in position"
        if len(self.positions) >= max_positions:
            return False, f"max positions ({max_positions}) reached"
        self._refresh_daily_count()
        if self._daily_trade_count >= max_trades:
            return False, f"max daily trades ({max_trades}) reached"
        if self.cash <= 0:
            return False, "no cash available"
        return True, ""

    def enter_position(
        self,
        symbol: str,
        entry_price: float,
        max_size_usd: float,
        catalyst_type: str,
    ) -> Optional[Position]:
        if entry_price <= 0:
            return None
        size_usd = min(max_size_usd, self.cash)
        if size_usd <= 0:
            return None
        shares = size_usd / entry_price
        cost_basis = shares * entry_price
        position = Position(
            position_id=uuid.uuid4().hex[:8],
            symbol=symbol,
            entry_price=entry_price,
            shares=shares,
            cost_basis=cost_basis,
            entry_time=datetime.now(timezone.utc).isoformat(),
            entry_catalyst_type=catalyst_type,
        )
        self.positions[symbol] = position
        self.cash -= cost_basis
        self._refresh_daily_count()
        self._daily_trade_count += 1
        return position

    def exit_position(self, symbol: str, exit_price: float, reason: str) -> Optional[ClosedTrade]:
        position = self.positions.pop(symbol, None)
        if position is None:
            return None
        proceeds = position.shares * exit_price
        pnl = proceeds - position.cost_basis
        pnl_pct = (pnl / position.cost_basis * 100) if position.cost_basis else 0.0
        entry_dt = datetime.fromisoformat(position.entry_time)
        now = datetime.now(timezone.utc)
        hold_minutes = (now - entry_dt).total_seconds() / 60
        trade = ClosedTrade(
            position_id=position.position_id,
            symbol=symbol,
            entry_price=position.entry_price,
            exit_price=exit_price,
            shares=position.shares,
            cost_basis=position.cost_basis,
            proceeds=proceeds,
            pnl=pnl,
            pnl_percent=pnl_pct,
            entry_time=position.entry_time,
            exit_time=now.isoformat(),
            exit_reason=reason,
            entry_catalyst_type=position.entry_catalyst_type,
            hold_minutes=round(hold_minutes, 1),
        )
        self.cash += proceeds
        self.trades.append(trade)
        return trade

    def get_equity(self, last_prices: dict[str, float]) -> float:
        pos_value = sum(
            p.current_value(last_prices.get(p.symbol, p.entry_price))
            for p in self.positions.values()
        )
        return self.cash + pos_value

    def get_realized_pnl(self) -> float:
        return sum(t.pnl for t in self.trades)

    def get_unrealized_pnl(self, last_prices: dict[str, float]) -> float:
        return sum(
            p.unrealized_pnl(last_prices.get(p.symbol, p.entry_price))
            for p in self.positions.values()
        )

    def to_status(self, last_prices: dict[str, float], extra: dict | None = None) -> dict:
        equity = self.get_equity(last_prices)
        realized = self.get_realized_pnl()
        unrealized = self.get_unrealized_pnl(last_prices)
        total_pnl = realized + unrealized
        result = {
            "starting_cash": round(self.starting_cash, 4),
            "cash": round(self.cash, 4),
            "equity": round(equity, 4),
            "realized_pnl": round(realized, 4),
            "unrealized_pnl": round(unrealized, 4),
            "total_pnl": round(total_pnl, 4),
            "total_pnl_percent": round((total_pnl / self.starting_cash * 100), 4) if self.starting_cash else 0,
            "open_position_count": len(self.positions),
            "closed_trade_count": len(self.trades),
            "daily_trade_count": self.daily_trade_count(),
        }
        if extra:
            result.update(extra)
        return result
