"""Strategy interface. A strategy is a pure function of market state."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..executor import DesiredOrder


@dataclass(frozen=True)
class Quote:
    """A market's current top of book, as we see it."""

    exchange_id: str
    best_bid: float | None
    best_ask: float | None
    bid_size: float = 0.0
    ask_size: float = 0.0

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2.0

    @property
    def spread_ticks(self) -> int:
        if self.best_bid is None or self.best_ask is None:
            return 0
        return round((self.best_ask - self.best_bid) / 0.005)

    @property
    def tradeable(self) -> bool:
        return (self.best_bid is not None and self.best_ask is not None
                and self.best_ask > self.best_bid)


@dataclass(frozen=True)
class Lot:
    """Aggregated inventory in one market, with the age needed to time exits."""

    exchange_id: str
    quantity: float                             # signed shares
    avg_cost: float
    age_minutes: float = 0.0


@dataclass(frozen=True)
class MarketView:
    """Everything a strategy is allowed to see."""

    quotes: dict[str, Quote]
    fair: dict[str, float]                      # exchange_id -> external fair value
    positions: dict[str, float]                 # exchange_id -> signed shares
    equity: float
    # Cost basis and age per market. Optional so existing strategies and their
    # tests, which only need signed share counts, are unaffected.
    lots: dict[str, Lot] = field(default_factory=dict)
    # exchange_id -> recent trading activity score, higher is busier.
    #
    # With a binding capital cap we can only quote a fraction of the 237
    # markets, so WHICH ones decides the fill rate. Selecting them by sorted
    # exchange id -- the previous behaviour -- put us in 29 markets holding 12%
    # of the venue's flow, with orders in exactly 1 of the 20 busiest.
    #
    # The score counts how often a market's last price CHANGED between cycles.
    # That costs nothing: /exchanges/prices is already fetched for all 237 every
    # cycle. Measured against real trade counts it has Spearman rho = +0.92, and
    # picking the top 29 by this score captures 28.7% of flow against 10.3% for
    # id order and 33.9% for a perfect oracle.
    activity: dict[str, float] = field(default_factory=dict)

    def by_activity(self) -> list[tuple[str, Quote]]:
        """Quotes ordered busiest first, with a stable tie-break."""
        return sorted(self.quotes.items(),
                      key=lambda kv: (-self.activity.get(kv[0], 0.0), kv[0]))

    def settlement_edge(self, ex: str) -> float:
        """
        Edge still available by holding this position to settlement, YES space.

        Positive means the external anchor agrees with the direction we are
        already positioned in.
        """
        lot = self.lots.get(ex)
        q = self.quotes.get(ex)
        fair = self.fair.get(ex)
        if lot is None or q is None or q.mid is None or fair is None:
            return 0.0
        return (q.mid - fair) if lot.quantity < 0 else (fair - q.mid)

    def protected(self, min_edge: float, budget_fraction: float) -> set[str]:
        """
        Markets whose position is being held for its settlement value.

        This lives on the view rather than inside ExitStrategy because every
        strategy needs it. When only the exit strategy knew, Ladder happily
        bought back a protected 100-share short with a 236-share bid -- closing
        the position AND opening a 136-share long against a fair value of 0.05,
        turning an expected +20 into -23.66. The hold decision is worthless if
        another strategy can undo it in the same cycle.

        Highest edge first, so a limited budget buys the most valuable holds.
        The tie-break is explicit: equal edges previously inherited dict order,
        so a reordering of the venue's position response silently flipped which
        position was protected and churned orders.
        """
        ranked = sorted(self.lots, key=lambda e: (-self.settlement_edge(e), str(e)))
        budget = budget_fraction * self.equity
        held, out = 0.0, set()
        for ex in ranked:
            if self.settlement_edge(ex) < min_edge:
                break
            q = self.quotes.get(ex)
            if q is None or q.mid is None:
                continue
            lot = self.lots[ex]
            cost = abs(lot.quantity) * (q.mid if lot.quantity > 0 else 1.0 - q.mid)
            if held + cost > budget:
                continue
            held += cost
            out.add(ex)
        return out


class Strategy(Protocol):
    name: str

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        """Return the complete book this strategy wants to have resting."""
        ...
