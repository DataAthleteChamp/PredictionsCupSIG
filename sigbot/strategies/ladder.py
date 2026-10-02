"""
S3 — deep passive ladder. The measured primary strategy.

Why this one leads:
  * **Zero capital while resting.** Verified: balance == 100,000 − filled cost
    basis exactly, with 1,001 of notional resting. Only fills debit.
  * **Best measured EV/order-hour** among the placements we tested.
  * **Fills concentrate overnight** — all observed fills landed 01:23–04:51 ET,
    when the US field is asleep.

The low fill rate (0.025/order-hour) is the *point*: deep orders only fill during
dislocations, and dislocations revert (median 2 minutes).

On the size of the edge: an earlier version of this docstring claimed deep fills
marked out at +0.0875/share. That number was an artifact of a frame bug that
scored NO fill prices against YES mids (see algos.markout). Corrected over 91
fills, the edge is about **+0.005/share — one tick** — with P(edge>0) = 0.96 at
1 min and 0.91 at 30 min. It is real but small, and it decays to negative by
240 min, which is why ExitStrategy exists.

Never improves the touch; never bids into the negative-markout tail.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import equal_variance_size, round_to_tick
from ..config import MAX_PRICE, MIN_PRICE
from ..executor import DesiredOrder
from .base import MarketView


@dataclass(frozen=True)
class LadderConfig:
    # Offsets below mid, in probability points. 20 ticks = 0.10.
    offsets: tuple[float, ...] = (0.08, 0.15)
    # Only quote markets whose mid sits in this band.
    min_mid: float = 0.20
    max_mid: float = 0.85
    # Never bid inside this price, regardless of offset (tail markout negative).
    floor_price: float = 0.15
    size_scale: float = 40.0
    max_notional: float = 80.0
    max_markets: int = 120
    # Skip a market if we already hold this many shares.
    max_existing_shares: float = 5_000.0


class LadderStrategy:
    name = "ladder"

    def __init__(self, cfg: LadderConfig | None = None):
        self.cfg = cfg or LadderConfig()

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = []
        eligible = 0
        for ex, q in sorted(view.quotes.items()):
            if eligible >= c.max_markets:
                break
            if not q.tradeable:
                continue
            mid = q.mid
            if mid is None or not (c.min_mid <= mid <= c.max_mid):
                continue
            if abs(view.positions.get(ex, 0.0)) >= c.max_existing_shares:
                continue
            eligible += 1
            for off in c.offsets:
                px = round_to_tick(mid - off)
                if px < max(c.floor_price, MIN_PRICE) or px > MAX_PRICE:
                    continue
                # Must stay strictly passive: never cross, never improve the touch.
                if q.best_bid is not None and px >= q.best_bid:
                    continue
                qty = equal_variance_size(px, c.size_scale, c.max_notional)
                out.append(DesiredOrder(exchange_id=ex, side="yes", action="buy",
                                        price=px, quantity=qty, strategy=self.name))
        return out
