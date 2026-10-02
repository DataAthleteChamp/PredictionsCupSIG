"""
S5 -- inventory exit. Harvests the edge before it decays.

The measurement that forces this strategy to exist (91 fills, corrected for the
NO/YES frame bug):

    horizon    mean markout/share    P(edge > 0)
       1 min        +0.0053             0.96
       5 min        +0.0063             0.98
      30 min        +0.0054             0.91
     240 min        -0.0010             0.44

The edge is real but it is *perishable*. It is worth about one tick and it is
gone within four hours. Every other strategy in this package only opens
positions; nothing closed them, so inventory aged past the point where the
edge had evaporated and we handed it back. That is the mechanism behind the
guaranteed floor drifting steadily more negative.

So this strategy does one thing: for inventory we already hold, rest a passive
offer that takes the edge while it still exists.

Two regimes, split at the horizon where the measured markout changes sign:
  * **fresh** (younger than `decay_minutes`): ask for the edge -- cost plus
    `target_ticks`. If the market will not pay it, keep waiting; the edge is
    still positive, so waiting is cheap.
  * **stale** (older than `decay_minutes`): the edge is now statistically zero
    or negative, so holding out for profit is no longer justified by anything
    we measured. Quote to get flat, down to a bounded scratch loss.

It never crosses the spread. Paying the spread to exit would cost about two
ticks to save an edge worth one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import round_to_tick
from ..config import MAX_PRICE, MIN_PRICE, TICK
from ..executor import DesiredOrder
from .base import Lot, MarketView


@dataclass(frozen=True)
class ExitConfig:
    # Profit target above average cost, in ticks. The measured edge is ~1 tick;
    # 2 covers the round trip and leaves something over.
    target_ticks: int = 2
    # Where the measured markout crosses zero. Past this, stop asking for edge.
    decay_minutes: float = 240.0
    # Worst scratch we will quote on stale inventory, in ticks below cost.
    # Equal to target_ticks: staleness flips the sign of the edge we ask for.
    max_scratch_ticks: int = 2
    # Ignore dust.
    min_shares: float = 25.0
    # Cap orders per cycle so exits cannot crowd out everything else.
    max_orders: int = 60


class ExitStrategy:
    name = "exit"

    def __init__(self, cfg: ExitConfig | None = None):
        self.cfg = cfg or ExitConfig()

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = []
        for ex, lot in sorted(view.lots.items()):
            if len(out) >= c.max_orders:
                break
            qty = lot.quantity
            if abs(qty) < c.min_shares:
                continue
            q = view.quotes.get(ex)
            if q is None or not q.tradeable:
                continue

            stale = lot.age_minutes >= c.decay_minutes
            if qty > 0:
                px = self._long_exit_price(lot.avg_cost, q.best_ask, stale, c)
                # Strictly passive: an offer must sit above the best bid.
                if px is None or (q.best_bid is not None and px <= q.best_bid):
                    continue
                action, side = "sell", "yes"
            else:
                px = self._short_exit_price(lot.avg_cost, q.best_bid, stale, c)
                if px is None or (q.best_ask is not None and px >= q.best_ask):
                    continue
                action, side = "buy", "yes"

            if not (MIN_PRICE <= px <= MAX_PRICE):
                continue
            out.append(DesiredOrder(exchange_id=ex, side=side, action=action,
                                    price=px, quantity=int(abs(qty)),
                                    strategy=self.name))
        return out

    @staticmethod
    def _long_exit_price(avg_cost: float, best_ask: float | None,
                         stale: bool, c: ExitConfig) -> float | None:
        """
        Sell price for a long: cost plus the edge when fresh, cost minus a
        bounded scratch when stale.

        Deliberately independent of the current ask. Clamping to the ask looks
        like "quote to get out", but it chases a collapsing book downwards: a
        0.066 position against a 0.010 ask would quote 0.010 and realise a
        5.6-cent loss to recover 1 cent of capital.

        The measurement says the edge decays to zero past `decay_minutes` -- it
        does not say the position is worth less. So stale inventory lowers its
        ask by a fixed amount and is willing not to fill. Capital is not the
        binding constraint here; realised losses are.
        """
        ticks = -c.target_ticks if stale else c.target_ticks
        return round_to_tick(avg_cost + ticks * TICK)

    @staticmethod
    def _short_exit_price(avg_cost: float, best_bid: float | None,
                          stale: bool, c: ExitConfig) -> float | None:
        """Buy price to close a short. Mirror image of the long case."""
        ticks = c.target_ticks if stale else -c.target_ticks
        return round_to_tick(avg_cost + ticks * TICK)
