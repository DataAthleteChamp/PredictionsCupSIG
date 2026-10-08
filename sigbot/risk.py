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

from .algos import to_yes_frame
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
    # Unrealised mark-to-market on positions held to resolution, and the peak
    # of the equity series that excludes it. See `adjusted_equity`.
    settlement_unrealised: float = 0.0
    peak_adjusted_equity: float = START_BALANCE

    @property
    def deployed_fraction(self) -> float:
        return self.cost_basis / self.equity if self.equity > 0 else 1.0

    @property
    def adjusted_equity(self) -> float:
        """
        Equity with the settlement book valued at COST rather than at mark.

        The venue's tail marks are both inflated and violently unstable -- the
        top ten of the leaderboard lost ~15% of their P&L within one hour on
        2026-10-06 without trading. A book that is deliberately short those
        tails therefore carries large unrealised swings that say nothing about
        whether the trade is working, because the trade is settled against the
        election result and not against the mid.

        Marking those holds at cost removes that noise while leaving every
        other source of loss -- realised losses, and the marks of everything we
        are NOT holding to resolution -- fully visible to the kill switch.
        """
        return self.equity - self.settlement_unrealised

    @property
    def drawdown(self) -> float:
        if self.peak_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_equity - self.equity) / self.peak_equity)

    @property
    def adjusted_drawdown(self) -> float:
        """Drawdown of the series the kill switch actually latches on."""
        if self.peak_adjusted_equity <= 0:
            return 0.0
        return max(0.0, (self.peak_adjusted_equity - self.adjusted_equity)
                   / self.peak_adjusted_equity)


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
        """
        Latch the kill switch if drawdown breaches the limit. Never un-latches.

        Latches on `adjusted_drawdown`, which values held-to-resolution
        positions at cost. The halt is a *stopping rule*, and a stopping rule
        that fires on the mark of a position we have already decided to hold to
        settlement would liquidate the trade precisely when the venue is most
        dislocated -- which is when the trade is most valuable. That is the
        limits-to-arbitrage failure: the constraint, not the thesis, ends the
        position.

        This does NOT disarm the switch. Realised losses, and marks on
        everything not held to resolution, still count in full, and a position
        drops out of the exemption the moment the anchor stops supporting it.
        """
        if self._tripped is None and state.adjusted_drawdown >= self.limits.max_drawdown_fraction:
            self._tripped = (f"drawdown {state.adjusted_drawdown:.1%} >= "
                             f"{self.limits.max_drawdown_fraction:.1%}")

    def reset(self) -> None:
        """Explicit manual reset. Deliberately not automatic."""
        self._tripped = None

    # ------------------------------------------------------------- the veto --

    def check(self, state: PortfolioState, *, exchange_id: str, action: str,
              price: float, quantity: int, strategy: str,
              side: str = "yes") -> Veto | None:
        """Return a Veto if this order must not be placed, else None."""
        if self._tripped:
            return Veto(f"kill switch: {self._tripped}")
        if quantity <= 0:
            return Veto("non-positive quantity")

        yes_action, yes_price = to_yes_frame(side, action, price)

        held = state.positions.get(exchange_id, 0.0)
        # Split the order into the part that closes existing exposure and the
        # part that opens new exposure. Only the opening part consumes capital;
        # charging the closing part against the caps would block exits exactly
        # when we most need them -- near a cap, or on an oversized position.
        #
        # Direction must be judged in YES space: a `no` buy is economically a
        # YES sell, so reading the raw action would treat it as closing a short
        # it is actually doubling.
        closing = ((held > 0 and yes_action == "sell")
                   or (held < 0 and yes_action == "buy"))
        reduce_qty = min(quantity, abs(held)) if closing else 0
        open_qty = quantity - reduce_qty
        notional = collateral(action, price, open_qty)

        # The tail guards are statements about YES probability -- we measured
        # negative markout BUYING YES below 0.15 -- so they must be applied to
        # the economic YES trade, and ONLY to exposure being opened.
        #
        # Applying them to a closing order inverted the strategy. Our validated
        # edge is selling overpriced tails; when the price then falls below
        # 0.15 the trade has WORKED, and buying it back is how the profit is
        # realised and the collateral released. The guard vetoed exactly that,
        # so winning tail shorts could never be harvested and were forced to
        # ride to settlement instead.
        if yes_action == "buy" and open_qty > 0:
            if yes_price < self.limits.no_buy_below:
                return Veto(f"price {yes_price} below no-buy floor "
                            f"{self.limits.no_buy_below} (tail markout is negative)")
            if yes_price > self.limits.no_buy_above:
                return Veto(f"price {yes_price} above no-buy ceiling "
                            f"{self.limits.no_buy_above}")

        resulting = abs(held - quantity if yes_action == "sell" else held + quantity)
        if resulting > self.limits.max_position_shares and open_qty > 0:
            return Veto("per-market share cap")

        if open_qty > 0:
            cap = self.limits.max_per_market_fraction * state.equity
            # Existing exposure must be valued in the same frame as the new
            # order's collateral. A SHORT of n shares at price p risks (1-p)
            # per share, not p: valuing a short tail at p understates it by up
            # to 49x in the cheap tail -- exactly where RelValueStrategy sells.
            existing = (abs(held) * price if held >= 0
                        else abs(held) * (1.0 - price))
            if existing + notional > cap:
                return Veto(f"per-market cap: {existing + notional:.2f} > {cap:.2f}")

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
        # "exit" only ever reduces exposure, so it needs no opening budget; it
        # is allowed through because open_qty is zero, not because it has funds.
        return {"ladder": b.ladder, "relvalue": b.relvalue,
                "sleeve": b.sleeve, "settlement": b.settlement}.get(strategy, 0.0)
