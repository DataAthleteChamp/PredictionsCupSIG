"""
Risk control. A single choke point with veto power over every order.

Encodes rules we MEASURED, not rules we assumed:
  * never buy below 0.15 or above 0.95 — both tail buckets markout negative
  * size q ∝ 1/sqrt(p(1-p)) so dollar variance is flat across price levels
  * per-market and total deployment caps
  * drawdown kill switch
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .config import RiskLimits, Settings, START_BALANCE


def collateral(action: str, price: float, quantity: int) -> float:
    """
    Cash a trade actually ties up, with no leverage.

    A BUY of YES at p costs p per share. A SELL of YES at p from flat is a long
    NO at (1-p) and costs (1-p) per share. Using price*quantity for both
    understates short collateral by up to 49x in the cheap tail, which is
    exactly where RelValueStrategy is designed to sell.
    """
    q = abs(quantity)
    return (price if action == "buy" else (1.0 - price)) * q


@dataclass(frozen=True)
class Veto:
    reason: str


@dataclass
class PortfolioState:
    balance: float
    equity: float
    cost_basis: float
    peak_equity: float = START_BALANCE
    # exchange_id -> signed shares (positive YES, negative NO)
    positions: dict[str, float] = field(default_factory=dict)
    # strategy tag -> capital currently deployed
    deployed_by_strategy: dict[str, float] = field(default_factory=dict)

    @property
    def deployed_fraction(self) -> float:
        return self.cost_basis / self.equity if self.equity > 0 else 1.0

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)


class RiskManager:
    def __init__(self, settings: Settings):
        self.s = settings
        self.limits: RiskLimits = settings.limits
        self._tripped: str | None = None

    # ------------------------------------------------------------ kill switch

    @property
    def tripped(self) -> str | None:
        return self._tripped

    def update(self, state: PortfolioState) -> None:
        """Latch the kill switch if drawdown breaches the limit. Never un-latches."""
        if self._tripped is None and state.drawdown >= self.limits.max_drawdown_fraction:
            self._tripped = (f"drawdown {state.drawdown:.1%} >= "
                             f"{self.limits.max_drawdown_fraction:.1%}")

    def reset(self) -> None:
        """Explicit manual reset. Deliberately not automatic."""
        self._tripped = None

    # ------------------------------------------------------------- the veto --

    def check(self, state: PortfolioState, *, exchange_id: str, action: str,
              price: float, quantity: int, strategy: str) -> Veto | None:
        """Return a Veto if this order must not be placed, else None."""
        if self._tripped:
            return Veto(f"kill switch: {self._tripped}")
        if quantity <= 0:
            return Veto("non-positive quantity")

        notional = collateral(action, price, quantity)

        if action == "buy":
            if price < self.limits.no_buy_below:
                return Veto(f"price {price} below no-buy floor "
                            f"{self.limits.no_buy_below} (tail markout is negative)")
            if price > self.limits.no_buy_above:
                return Veto(f"price {price} above no-buy ceiling "
                            f"{self.limits.no_buy_above}")

        cap = self.limits.max_per_market_fraction * state.equity
        held = state.positions.get(exchange_id, 0.0)
        # A trade that REDUCES an existing position is risk-reducing; charging
        # it against the cap would block exits.
        reducing = (held > 0 and action == "sell") or (held < 0 and action == "buy")
        existing = abs(held) * price
        if not reducing and existing + notional > cap:
            return Veto(f"per-market cap: {existing + notional:.2f} > {cap:.2f}")

        if abs(state.positions.get(exchange_id, 0.0)) + quantity > self.limits.max_position_shares:
            return Veto("per-market share cap")

        max_deploy = self.limits.max_deployed_fraction * state.equity
        if state.cost_basis + notional > max_deploy:
            return Veto(f"total deployment cap: "
                        f"{state.cost_basis + notional:.2f} > {max_deploy:.2f}")

        budget = self.strategy_budget(strategy) * state.equity
        used = state.deployed_by_strategy.get(strategy, 0.0)
        if used + notional > budget:
            return Veto(f"{strategy} budget: {used + notional:.2f} > {budget:.2f}")

        return None

    def strategy_budget(self, strategy: str) -> float:
        b = self.s.budgets
        return {"ladder": b.ladder, "relvalue": b.relvalue}.get(strategy, 0.0)
