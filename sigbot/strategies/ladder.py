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
    # SETTLED EXPERIMENT. Quoting at 3, 6 and 20 ticks simultaneously was a
    # deliberate test, because a two-parameter queue model fitted to two points
    # could not distinguish geometric from power-law decay. 688 ladder fills
    # later:
    #
    #     rung    fills   share of fills   edge/share   P&L
    #     ~3t       641        93.2%        +0.00405   +389.6
    #     ~6t        47         6.8%        +0.01883   +132.8
    #     ~20t        0            0%              --       --
    #
    # The deep rung produced ZERO fills while holding about a third of the
    # order slots and their capital -- roughly 48 dead orders. The power law
    # predicted ~62 fills there and geometric ~10, so geometric wins and even
    # it was optimistic about depth. The "dislocation capture" rationale for a
    # deep rung is simply false on this venue: dislocations never travel 20
    # ticks before someone else takes them.
    #
    # Per order slot the shallow rung is worth about 3x the middle one (4.93
    # against 1.68), so the freed slots go shallow rather than being retired.
    # The three rungs still catch progressively larger moves, just inside the
    # range where fills actually happen.
    offsets: tuple[float, ...] = (0.015, 0.02, 0.03)
    # Only quote markets whose mid sits in this band.
    #
    # Upper bound cut from 0.85 to 0.50 on 2026-10-08. The binding resource is
    # CAPITAL, not order slots -- we run at ~94% deployed -- so the metric that
    # decides this is return on capital, not markout per share. Measured on our
    # own 2,063 live fills at a 5-minute horizon:
    #
    #     price paid     n     markout/share   return on capital
    #      <0.10         26      -0.00442          -4.36%
    #      0.10-0.20    128      +0.00068          +0.51%
    #      0.20-0.35    440      +0.00251          +0.88%
    #      0.35-0.50    261      +0.00176          +0.41%
    #      0.50-0.70    472      +0.00256          +0.41%
    #      0.70-0.85    619      +0.00162          +0.21%
    #      0.85-1.00    117      +0.00111          +0.13%
    #
    # Markout per share is nearly FLAT across the whole range -- which is why
    # this went unnoticed for so long. Every tool we had, including
    # research/backtest.py, scored configurations by markout per share, and
    # that metric is blind to the fact that a +0.0016 edge costs 0.775 of
    # capital at the top of the band and 0.265 in the middle of it.
    #
    # Weighted, 0.20-0.50 returns 0.70% against 0.30% for 0.50-0.85: 2.3x, on
    # 701 and 1,091 fills respectively. The replay backtest agrees on
    # direction, at 1.62x.
    min_mid: float = 0.20
    max_mid: float = 0.50
    # Never bid inside this price, regardless of offset (tail markout negative).
    #
    # Re-confirmed 2026-10-08 and worth keeping despite a backtest that
    # disagreed loudly. research/band_experiment.py scored the 0.00-0.05 band
    # at +48% return on capital per fill; our own live fills below 0.10 return
    # -4.36% on 26 fills with only 46% positive. The simulator has no queue
    # position, so it assumes any print through our price reaches us -- least
    # true exactly where books are thinnest. Live measurement wins.
    floor_price: float = 0.15
    # Refuse a buy the external anchor says is already overpriced by this much.
    #
    # The ladder has no anchor awareness at all otherwise -- it buys on pure
    # local microstructure (a dip in the recent mid), which is a DIFFERENT
    # signal from the anchor comparison RelValue and Settlement already make
    # with the same `view.fair` data. Usually these agree. On 2026-10-16 they
    # did not: the ladder bought IA-01 (R) at 0.155 while the anchor priced it
    # at 0.09, a position that directly fought our own validated
    # favourite-longshot edge. It sat for 12+ hours as an unfillable exit
    # order (resting above the market, waiting for a rise the anchor says is
    # unlikely) before this was found.
    #
    # Isolated and small (one position, $11.70 of edge fought, -$1.80
    # realised) -- not a material bleed on its own. The fix is cheap because
    # the data is already fetched for every other strategy, so there is no
    # reason to leave this gap open for the 19 remaining days.
    max_anchor_overprice: float = 0.03
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
            fair = view.fair.get(ex)
            for off in c.offsets:
                px = round_to_tick(mid - off)
                if px < max(c.floor_price, MIN_PRICE) or px > MAX_PRICE:
                    continue
                # Must stay strictly passive: never cross, never improve the touch.
                if q.best_bid is not None and px >= q.best_bid:
                    continue
                # Refuse to buy where the anchor itself says this price is
                # already overpriced. Without this, the ladder's local
                # microstructure signal can directly contradict the anchor
                # comparison every other strategy makes with the same data.
                if fair is not None and px - fair >= c.max_anchor_overprice:
                    continue
                qty = min(equal_variance_size(px, c.size_scale,
                                              c.max_notional),
                          c.max_shares)
                out.append(DesiredOrder(exchange_id=ex, side="yes", action="buy",
                                        price=px, quantity=qty, strategy=self.name))
        return out
