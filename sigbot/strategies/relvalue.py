"""
S1 — relative value against an external fair-value anchor.

The measured edge is NOT directional. Comparing 104 liquid markets against
Polymarket, expected seat counts agreed almost exactly (17.30 vs 17.22) but the
seat-count dispersion did not (sd 1.88 vs 2.36). The venue is **systematically
less certain than it should be**: it compresses probabilities toward 0.5.

So the trade is to sell that excess uncertainty — sell the overpriced tail side,
buy the underpriced favorite side — rather than to take a view on who wins.

Confirmed on our own fills: the 0.00–0.05 and 0.05–0.15 buckets were the only
ones with negative markout. We were buying longshots and losing on them.

De-prioritised relative to the ladder for a reason beyond EV: at least one strong
competitor runs the same longshot fade, and because prizes are pooled and split
on ties, crowded variance is worth less than idiosyncratic variance.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import equal_variance_size, round_to_tick
from ..config import MAX_PRICE
from ..executor import DesiredOrder
from .base import MarketView


@dataclass(frozen=True)
class RelValueConfig:
    # Minimum edge versus fair value before quoting, in probability points.
    min_edge: float = 0.02
    # Only buy inside this band; outside it the measured markout is negative.
    buy_min_price: float = 0.15
    buy_max_price: float = 0.95
    # Selling the tail is the point of the strategy, so allow it lower.
    sell_min_price: float = 0.02
    # Raised with the 20% deployment cap. Relvalue's measured per-share edge
    # is the weakest of the three (+0.00050, P(>0)=0.624), so it scales less
    # aggressively than the ladder and keeps its narrower market count.
    size_scale: float = 60.0
    max_notional: float = 120.0
    max_markets: int = 60
    max_existing_shares: float = 5_000.0


class RelValueStrategy:
    name = "relvalue"

    def __init__(self, cfg: RelValueConfig | None = None):
        self.cfg = cfg or RelValueConfig()

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = []
        used = 0
        for ex, q in view.by_activity():
            if used >= c.max_markets:
                break
            fair = view.fair.get(ex)
            if fair is None or not q.tradeable:
                continue
            if abs(view.positions.get(ex, 0.0)) >= c.max_existing_shares:
                continue

            # Stay passive: join the touch, never improve it and never cross.
            # Measured EV of improving the touch is -0.18/order-hour, so the edge
            # is taken by resting where liquidity already sits, not by paying up.
            #
            # Edge is evaluated AT the price we would actually trade.
            sell_px = round_to_tick(q.best_ask)
            if (sell_px - fair >= c.min_edge
                    and c.sell_min_price <= sell_px <= MAX_PRICE):
                out.append(DesiredOrder(ex, "yes", "sell", sell_px,
                                        equal_variance_size(sell_px, c.size_scale,
                                                            c.max_notional),
                                        self.name))
                used += 1
                continue

            buy_px = round_to_tick(q.best_bid)
            if (fair - buy_px >= c.min_edge
                    and c.buy_min_price <= buy_px <= c.buy_max_price):
                out.append(DesiredOrder(ex, "yes", "buy", buy_px,
                                        equal_variance_size(buy_px, c.size_scale,
                                                            c.max_notional),
                                        self.name))
                used += 1
        return out
