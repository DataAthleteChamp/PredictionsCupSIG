"""
S5 -- inventory exit. Harvests the edge before it decays.

The measurement that forces this strategy to exist (304 fills, recomputed from
the timestamped tape rather than from live polls -- see
research/rebuild_markouts.py):

    horizon    mean markout/share    P(edge > 0)      n
       1 min        +0.00150             0.87        283
       5 min        +0.00217             0.98        279
      30 min        -0.00104             0.29        282
     240 min        +0.00004             0.51        172

These supersede an earlier table that read +0.0053 to +0.0063 across 1-30
minutes. That version stamped each fill with the mid at DISCOVERY rather than
at `filled_at`, and reused one current mid for every horizon that happened to
be due, which inflated the edge by roughly 7x. The corrected figures are
confirmed out-of-sample: +0.00217/share on a 71-share average fill predicts
+0.15 per trade, against +0.27 actually realised over 216 trades, while the
old figures predicted +1.89.

So the edge is real but SMALL -- about four tenths of one tick -- and it
decays far faster than first believed: it is already negative at 30 minutes,
not at four hours.

Two regimes, split at the horizon where the measured markout changes sign:
  * **fresh** (younger than `decay_minutes`): ask for the edge -- cost plus
    `target_ticks`. If the market will not pay it, keep waiting; the edge is
    still positive, so waiting is cheap.
  * **stale** (older than `decay_minutes`): the edge is now statistically zero
    or negative, so holding out for profit is no longer justified by anything
    we measured. Quote to get flat, down to a bounded scratch loss.

It never crosses the spread. Paying the spread to exit would cost about two
ticks to save an edge worth less than one.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import round_to_tick
from ..config import MAX_PRICE, MIN_PRICE, TICK
from ..executor import DesiredOrder
from .base import Lot, MarketView


@dataclass(frozen=True)
class ExitConfig:
    # Profit target above average cost, in ticks.
    #
    # The measured 5-minute edge is +0.00217/share, which is 0.43 of a tick.
    # The grid cannot express less than one tick, so 1 is already asking for
    # roughly 2.3x the mean edge. The previous value of 2 demanded ~5x it, so
    # offers rarely filled and inventory aged past the point where the edge had
    # reversed -- the exact failure this strategy exists to prevent.
    target_ticks: int = 1
    # Where the measured markout crosses zero. It is positive at 5 minutes
    # (P=0.98) and already negative at 30 (-0.00104, P(>0)=0.29), so the sign
    # change lies between. 20 minutes sits inside the positive region with a
    # margin. This was 240, which was derived from the mis-timed table and held
    # inventory roughly eight times longer than the edge survives.
    decay_minutes: float = 20.0
    # Worst scratch we will quote on stale inventory, in ticks below cost.
    max_scratch_ticks: int = 2
    # Ignore dust.
    min_shares: float = 25.0
    # Cap orders per cycle so exits cannot crowd out everything else.
    # Do not close a position that still carries settlement edge this large.
    #
    # This strategy exists to harvest a PERISHABLE edge worth about 0.4 of a
    # tick, measured over 5-30 minutes. It was also closing positions whose
    # value comes from settlement rather than from microstructure: 56% of our
    # tail shorts were bought back, 20 of them by this strategy, discarding a
    # 12-24 tick edge to capture a sub-tick one.
    #
    # A short of a contract SIG prices at 0.135 that Polymarket prices at 0.008
    # is not inventory to be recycled; it is the favourite-longshot trade, and
    # it pays on 3 November rather than in half an hour. 0.02 is four ticks --
    # comfortably above the grind edge, so ordinary inventory is unaffected.
    hold_if_settlement_edge: float = 0.02
    # Ceiling on capital tied up in held value positions, as a fraction of
    # equity.
    #
    # The hold rule must be BOUNDED. Held positions never close, so an
    # unbounded rule accumulates them until they crowd out the grind -- and
    # the grind is worth far more per unit of capital, because it recycles:
    # roughly 60% over the remaining 31 days against 7.2% for a position
    # locked until settlement, about 8x. The grind still wants capital (28
    # orders vetoed last cycle), so the two genuinely compete.
    #
    # 10% matches the sleeve budget, which is the layer meant for convex
    # settlement bets and is otherwise unused. Beyond that, positions are
    # harvested normally no matter how attractive their settlement edge.
    max_hold_fraction: float = 0.10
    # Cap orders per cycle so exits cannot crowd out everything else.
    max_orders: int = 60


class ExitStrategy:
    name = "exit"

    def __init__(self, cfg: ExitConfig | None = None):
        self.cfg = cfg or ExitConfig()

    @staticmethod
    def _settlement_edge(lot, fair: float | None, mid: float | None) -> float:
        """
        Edge still available by holding to settlement, in YES space.

        Positive means the market disagrees with the external anchor in the
        direction our position is already betting on.
        """
        if fair is None or mid is None:
            return 0.0
        return (mid - fair) if lot.quantity < 0 else (fair - mid)

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = []
        # Protect the positions with the LARGEST settlement edge first, and
        # only until the hold budget is used up. Sorting by edge means the
        # budget buys the most valuable holds rather than whichever markets
        # happen to sort first.
        edges = {}
        for ex, lot in view.lots.items():
            qq = view.quotes.get(ex)
            edges[ex] = self._settlement_edge(
                lot, view.fair.get(ex), qq.mid if qq else None)
        held = 0.0
        budget = c.max_hold_fraction * view.equity
        protected: set[str] = set()
        for ex in sorted(edges, key=lambda e: -edges[e]):
            if edges[ex] < c.hold_if_settlement_edge:
                break
            lot = view.lots[ex]
            qq = view.quotes.get(ex)
            if qq is None or qq.mid is None:
                continue
            cost = abs(lot.quantity) * (qq.mid if lot.quantity > 0
                                        else 1.0 - qq.mid)
            if held + cost > budget:
                continue
            held += cost
            protected.add(ex)

        for ex, lot in sorted(view.lots.items()):
            if len(out) >= c.max_orders:
                break
            qty = lot.quantity
            if abs(qty) < c.min_shares:
                continue
            q = view.quotes.get(ex)
            if q is None or not q.tradeable:
                continue

            # Leave value positions alone, within the hold budget.
            if ex in protected:
                continue

            stale = lot.age_minutes >= c.decay_minutes
            if qty > 0:
                px = self._long_exit_price(lot.avg_cost, q.best_bid, stale, c)
                # Strictly passive: an offer must sit above the best bid.
                if px is None or (q.best_bid is not None and px <= q.best_bid):
                    continue
                action, side = "sell", "yes"
            else:
                px = self._short_exit_price(lot.avg_cost, q.best_ask, stale, c)
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
    def _long_exit_price(avg_cost: float, best_bid: float | None,
                         stale: bool, c: ExitConfig) -> float | None:
        """
        Sell price for a long: cost plus the edge when fresh, cost minus a
        bounded scratch when stale, but never below the current bid.

        The cost-based target is deliberately not clamped DOWN to the book.
        Chasing a collapsing book looks like "quote to get out" but realises
        the loss: a 0.066 position against a 0.010 ask would quote 0.010 and
        give up 5.6 cents to recover 1.

        It must however be clamped UP. A stale position whose market moved in
        our favour produced a target below the bid -- 0.020 against a 0.035 bid
        for inventory bought at 0.032 -- and the caller's passivity check then
        discarded it. The result was that stale, PROFITABLE inventory stopped
        being quoted at all and simply sat there. Raising the floor to one tick
        above the bid both restores the exit and captures the gain instead of
        scratching beneath it.
        """
        # max_scratch_ticks governs how far BELOW cost stale inventory will
        # go; target_ticks governs the profit asked while fresh. Reusing
        # target_ticks for both made max_scratch_ticks dead configuration.
        ticks = -c.max_scratch_ticks if stale else c.target_ticks
        px = round_to_tick(avg_cost + ticks * TICK)
        if best_bid is not None:
            px = max(px, round_to_tick(best_bid + TICK))
        return px

    @staticmethod
    def _short_exit_price(avg_cost: float, best_ask: float | None,
                          stale: bool, c: ExitConfig) -> float | None:
        """Buy price to close a short. Mirror image of the long case."""
        ticks = c.max_scratch_ticks if stale else -c.target_ticks
        px = round_to_tick(avg_cost + ticks * TICK)
        if best_ask is not None:
            px = min(px, round_to_tick(best_ask - TICK))
        return px
