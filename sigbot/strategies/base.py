"""Strategy interface. A strategy is a pure function of market state."""
from __future__ import annotations

from dataclasses import dataclass
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
class MarketView:
    """Everything a strategy is allowed to see."""

    quotes: dict[str, Quote]
    fair: dict[str, float]                      # exchange_id -> external fair value
    positions: dict[str, float]                 # exchange_id -> signed shares
    equity: float


class Strategy(Protocol):
    name: str

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        """Return the complete book this strategy wants to have resting."""
        ...
