"""
Portfolio-level outcome analysis.

The question this module answers: **what do we keep no matter what happens?**

Each race resolves to exactly one outcome, so a position set has a finite,
enumerable payoff space. The minimum over that space is the guaranteed floor.
A floor above zero means the position is risk-free in the strict sense — it
pays regardless of who wins.

This is the basis for market-neutral income on this venue. There is no "market
direction" to hedge: every contract converges to 0 or 1 on a known date. The
only real risk is *which* outcome occurs, and that is fully enumerable.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Leg:
    """One holding. Positive qty = long YES; negative = long NO (short YES)."""

    party: str
    quantity: float
    avg_cost: float

    @property
    def cost(self) -> float:
        """Cash actually paid. A short YES at p is a long NO at (1-p)."""
        if self.quantity >= 0:
            return self.quantity * self.avg_cost
        return abs(self.quantity) * (1.0 - self.avg_cost)

    def payout_if(self, winner: str) -> float:
        if self.quantity >= 0:
            return self.quantity if self.party == winner else 0.0
        return abs(self.quantity) if self.party != winner else 0.0


@dataclass
class RacePosition:
    """Our holdings in one race, plus the full outcome space for that race."""

    race: str
    outcomes: tuple[str, ...]
    legs: list[Leg] = field(default_factory=list)

    @property
    def cost(self) -> float:
        return sum(l.cost for l in self.legs)

    def payout_if(self, winner: str) -> float:
        return sum(l.payout_if(winner) for l in self.legs)

    @property
    def worst_payout(self) -> float:
        if not self.outcomes:
            return 0.0
        return min(self.payout_if(w) for w in self.outcomes)

    @property
    def best_payout(self) -> float:
        if not self.outcomes:
            return 0.0
        return max(self.payout_if(w) for w in self.outcomes)

    @property
    def guaranteed_floor(self) -> float:
        """PnL we keep in the worst outcome. Positive => risk-free."""
        return self.worst_payout - self.cost

    @property
    def is_risk_free(self) -> bool:
        return self.guaranteed_floor > 0

    def max_price_to_lock(self, party: str, quantity: float) -> float | None:
        """
        Highest price we could pay for `quantity` of `party` and still end up
        with a non-negative guaranteed floor.

        This is the core of pair completion: the ladder leaves us long one side
        of a race; buying the complement cheaply enough converts a directional
        holding into locked profit.

        Returns None when no price in (0, 1) achieves it.
        """
        if party not in self.outcomes or quantity <= 0:
            return None
        lo, hi = 0.0, 1.0
        for _ in range(60):                      # bisection; monotone in price
            mid = (lo + hi) / 2
            trial = RacePosition(self.race, self.outcomes,
                                 self.legs + [Leg(party, quantity, mid)])
            if trial.guaranteed_floor >= 0:
                lo = mid
            else:
                hi = mid
        return lo if lo > 1e-6 else None


def portfolio_floor(races: list[RacePosition]) -> dict:
    """Aggregate worst case. Races are independent, so floors simply add."""
    total_cost = sum(r.cost for r in races)
    total_floor = sum(r.guaranteed_floor for r in races)
    risk_free = [r for r in races if r.is_risk_free]
    return {
        "cost": total_cost,
        "guaranteed_floor": total_floor,
        "best_case": sum(r.best_payout for r in races) - total_cost,
        "n_races": len(races),
        "n_risk_free": len(risk_free),
        "risk_free_floor": sum(r.guaranteed_floor for r in risk_free),
    }
