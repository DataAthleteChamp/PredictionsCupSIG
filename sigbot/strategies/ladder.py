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
from ..config import MAX_PRICE, MIN_PRICE, SETTLEMENT_HOLD_BUDGET, SETTLEMENT_HOLD_EDGE
from ..executor import DesiredOrder
from .base import MarketView


@dataclass(frozen=True)
class LadderConfig:
    # Offsets below mid, in probability points. 1 tick = 0.005.
    #
    # Measured EV/order-hour by depth (corrected markout x fitted fill rate,
    # 10k bootstrap over our own fills):
    #
    #     depth below mid   n    EV/order-hr   95% CI            P(best)
    #     inside/at mid    30    +0.00035      [-0.0106,+0.0122]   0.9%
    #     0-1 ticks       148    +0.00821      [+0.0028,+0.0132]   2.9%
    #     2-3 ticks        19    +0.01633      [+0.0085,+0.0228]  87.3%
    #     4-6 ticks         4    +0.00281      [-0.0143,+0.0200]   8.8%
    #     13+ ticks         6    +0.00364      [+0.0033,+0.0040]   0.0%
    #
    # THAT 87.3% IS NOT TRUSTWORTHY. The bootstrap resampled markouts but held
    # the fill rate fixed, and that rate comes from a two-parameter queue model
    # fitted to exactly TWO points (1 tick -> 3.17/hr, 20 ticks -> 0.025/hr).
    # Zero residual degrees of freedom means the functional form is assumed,
    # not measured. A power law fits the same two anchors exactly and implies
    # very different rates in between:
    #
    #     ticks   geometric   power law
    #         3      1.904       0.537
    #         6      0.886       0.175
    #        30      0.002       0.013
    #
    # Under the power law the 2-3 tick bucket's P(best) collapses to ~10% and
    # the optimum moves to 1 tick. So the precise optimum is UNIDENTIFIED.
    #
    # What IS robust: both forms agree the previous (0.08, 0.15) offsets -- 16
    # and 30 ticks, where fills arrive roughly once per 500 order-hours -- are
    # far from optimal. The disagreement is only between 1 and 3 ticks, both
    # shallow. These offsets therefore straddle the disagreement rather than
    # betting on one form, and quoting at 3, 6 and 20 ticks simultaneously is a
    # deliberate experiment: three depths overidentify the two-parameter model,
    # so the next refit can settle the functional form from our own fills
    # instead of assuming it.
    #
    # The deep rung also earns its place independently: resting is free and
    # deep fills carry a much larger per-fill markout (+0.070/share) from
    # dislocation reversion, uncorrelated with the shallow rungs' edge.
    offsets: tuple[float, ...] = (0.015, 0.03, 0.10)
    # Only quote markets whose mid sits in this band.
    min_mid: float = 0.20
    max_mid: float = 0.85
    # Never bid inside this price, regardless of offset (tail markout negative).
    floor_price: float = 0.15
    # Sizing. Raised together with the 20% deployment cap.
    #
    # Extra capital can be spent two ways: more markets, or more size in the
    # markets we already like. The measurement says size, decisively.
    #
    #   market rank   edge/share   P(>0)    realised P&L
    #     top 30       +0.00199    0.955       +35.04
    #     31-80        +0.00250    0.957       +14.41
    #     81-150       +0.00067    0.673       -11.37
    #
    # Edge survives past rank 80 only barely and then turns negative, while
    # per-share edge is essentially flat in fill size up to ~150 shares
    # (Spearman +0.14). So breadth is capped at the measured ceiling and the
    # additional capital goes into size instead.
    size_scale: float = 100.0
    max_notional: float = 200.0
    # Hard share ceiling, applied AFTER equal_variance_size.
    #
    # Neither existing knob bounds share count. equal_variance_size returns
    # min(scale/sqrt(p(1-p)), max_notional/p), and across 0.15-0.95 that is
    # 200-280 shares -- every single order landed in the measured 32%-fill
    # band, not the ~146-share P&L/order optimum the sizing change was aiming
    # for. max_notional cannot fix it because it binds on CASH, which is small
    # for cheap contracts: at p=0.15 a 42 notional order is still 280 shares.
    #
    # It also falsified the 25% cap arithmetic. The generated ladder book was
    # 24,852 against the 17,520 the cap was sized for, so with inventory the
    # real requirement was ~32%, not 24.5%. Clamping restores it to 16,935.
    max_shares: int = 150
    # The evidence-backed ceiling. Past this the edge is indistinguishable from
    # zero and our own fills there lost money, so additional capital must not
    # buy additional markets.
    max_markets: int = 80
    # Skip a market if we already hold this many shares.
    max_existing_shares: float = 5_000.0


class LadderStrategy:
    name = "ladder"

    def __init__(self, cfg: LadderConfig | None = None):
        self.cfg = cfg or LadderConfig()

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = []
        # A position held for its settlement value must not be CLOSED by a
        # quote. Buying back a protected short destroys the hold and opens the
        # opposite exposure: a 100-share short protected on a 0.05 fair was met
        # with a 236-share ladder bid, leaving a 136-share long against that
        # same fair.
        #
        # But skipping the whole MARKET was far too blunt, and it created a
        # trap: we trade a market, accumulate a position there, that position
        # earns settlement edge, the market becomes protected, and we stop
        # quoting in it. The markets we are best at are exactly the ones we get
        # evicted from. Measured: 17 of our top-80 markets were blocked,
        # including the single busiest, which is 21% of the quoting universe
        # and coincided with fills falling from 22/hour to 6.8/hour while
        # venue-wide volume was unchanged at 3,000-5,500 trades/hour.
        #
        # The ladder only ever BUYS, so it reduces a protected SHORT but merely
        # adds to a protected LONG. Only the former needs blocking; the
        # per-market cap bounds the latter.
        protected = {ex for ex in view.protected(SETTLEMENT_HOLD_EDGE,
                                                 SETTLEMENT_HOLD_BUDGET)
                     if view.positions.get(ex, 0.0) < 0}
        eligible = 0
        for ex, q in view.by_activity():
            if eligible >= c.max_markets:
                break
            if not q.tradeable or ex in protected:
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
                qty = min(equal_variance_size(px, c.size_scale,
                                              c.max_notional),
                          c.max_shares)
                out.append(DesiredOrder(exchange_id=ex, side="yes", action="buy",
                                        price=px, quantity=qty, strategy=self.name))
        return out
