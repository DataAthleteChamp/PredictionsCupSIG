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
    """
    Our holdings in one race, plus the full outcome space for that race.

    `complete` records whether `outcomes` is known to enumerate EVERY possible
    winner. A floor computed over a partial outcome set is not a floor: a
    missing outcome is one that cannot lose, so the result is biased optimistic.
    A 100-share long at 0.40 with only its own outcome listed reports a +60
    floor when the true worst case is -40.
    """

    race: str
    outcomes: tuple[str, ...]
    legs: list[Leg] = field(default_factory=list)
    complete: bool = True

    @property
    def cost(self) -> float:
        return sum(l.cost for l in self.legs)

    def payout_if(self, winner: str) -> float:
        return sum(l.payout_if(winner) for l in self.legs)

    @property
    def enumerable(self) -> bool:
        """A floor is only meaningful over a complete, multi-outcome space."""
        return self.complete and len(self.outcomes) >= 2

    @property
    def worst_payout(self) -> float:
        if not self.outcomes:
            return 0.0
        if not self.enumerable:
            return 0.0          # assume the worst: nothing we hold pays
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
        """
        DEPRECATED NAME - kept only so nothing silently changes meaning.
        Use `is_conditionally_locked`. This is NOT risk-free: see
        `worst_case_floor` for what a refund does to it.
        """
        return self.is_conditionally_locked

    @property
    def is_conditionally_locked(self) -> bool:
        """
        True when the position pays a non-negative floor *conditional on* every
        leg settling 0 or 1 and one listed outcome winning.

        It is NOT unconditional. See `worst_case_floor`.
        """
        return self.enumerable and self.guaranteed_floor > 0

    # --- settlement states beyond "someone wins" --------------------------
    #
    # The venue refunds: "A cancelled or N/A outcome refunds the remaining
    # position instead of choosing a winner. The refund returns the refundable
    # cost of the held shares." A refund on ONE leg converts a constant payoff
    # into a directional one:
    #
    #   buy R 100@0.40 + D 100@0.50  -> cost 90, "locked" +10
    #   R refunded at cost, D settles 0 -> payout 40, PnL -50
    #
    # So `guaranteed_floor` is a floor over winner-states only. The true worst
    # case must also consider refunds.

    def payout_if_refunded(self, refunded: tuple[str, ...], winner: str) -> float:
        """Payout when `refunded` legs return their cost and the rest settle."""
        total = 0.0
        for l in self.legs:
            if l.party in refunded:
                total += l.cost                 # cost returned, no profit
            else:
                total += l.payout_if(winner)
        return total

    @property
    def other_wins_floor(self) -> float:
        """
        PnL if NO listed outcome wins - an unlisted candidate, a write-in, or a
        settlement we did not anticipate. Every long leg settles zero.

        This is the tail the 'risk-free' framing ignored: the outcome universe
        is built from the contracts the venue happens to list, which proves they
        exist, not that one of them must settle YES.
        """
        return self.payout_if("__other__") - self.cost

    @property
    def worst_case_floor(self) -> float:
        """
        Minimum PnL over winner-states AND single-leg refund states.

        A refunded leg cannot also be the winner, so refund states are evaluated
        against the remaining outcomes only. `guaranteed_floor` assumes refunds
        never happen, which the venue's settlement rules contradict:
        "A cancelled or N/A outcome refunds the remaining position."

        Does NOT include `other_wins_floor`, which is reported separately so the
        two very different tails are not conflated.
        """
        if not self.enumerable:
            return -self.cost
        worst = self.guaranteed_floor
        for refunded in {l.party for l in self.legs}:
            others = [w for w in self.outcomes if w != refunded]
            for w in others:
                worst = min(worst, self.payout_if_refunded((refunded,), w) - self.cost)
            # The genuinely dangerous case: the leg that WOULD have won is the
            # one refunded, so it returns cost instead of 1 and nothing else
            # pays. This is how a "locked" pair becomes a directional loss.
            worst = min(worst,
                        self.payout_if_refunded((refunded,), "__none__") - self.cost)
        return worst

    @property
    def is_unconditionally_locked(self) -> bool:
        """Non-negative even if any single leg is refunded."""
        return self.enumerable and self.worst_case_floor > 0

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
        if not self.enumerable:
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
    """
    Aggregate floors. Deterministic floors add across races — this needs no
    probabilistic independence assumption, only that each race settles on its
    own terms.
    """
    total_cost = sum(r.cost for r in races)
    total_floor = sum(r.guaranteed_floor for r in races)
    locked = [r for r in races if r.is_conditionally_locked]
    return {
        "cost": total_cost,
        "guaranteed_floor": total_floor,          # winner-states only
        "worst_case_floor": sum(r.worst_case_floor for r in races),
        "other_wins_floor": sum(r.other_wins_floor for r in races),
        "best_case": sum(r.best_payout for r in races) - total_cost,
        "n_races": len(races),
        "n_conditionally_locked": len(locked),
        "n_risk_free": len(locked),               # back-compat alias
        "n_unconditionally_locked": sum(1 for r in races
                                        if r.is_unconditionally_locked),
        "locked_floor": sum(r.guaranteed_floor for r in locked),
        "risk_free_floor": sum(r.guaranteed_floor for r in locked),
    }
