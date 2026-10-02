"""
Convex sleeve — the aspirational layer of the barbell.

The tournament objective needs convexity: at ~6x behind the podium, a
high-Sharpe book cannot reach it (Dubins-Savage; Browne 1999). But convexity is
NOT free. Two independent measurements say buying generic cheap contracts loses:

  * Cardozo & Rivero-Wildemauwe (2026), 588M Polymarket trades: sub-10c
    contracts lost ~19.3c per dollar staked.
  * Our own fills: the 0.00-0.05 and 0.05-0.15 buckets were the ONLY ones with
    negative markout, and SIG prices sub-0.05 contracts at ~1.98x Polymarket.

So this strategy does NOT buy cheap contracts because they are cheap. It buys
only the ones that run CONTRARY to the measured bias — where SIG prices a tail
*below* the external anchor. Given SIG systematically overprices tails, a tail
priced below Polymarket is an unusual, filtered signal rather than a lottery
ticket, and it is the only place convexity comes without paying the premium.

If no such market exists, this strategy correctly returns nothing. An empty
sleeve is the right answer when the edge is absent.

---

MEASURED 2026-10-02, all 228 crosswalked markets, SIG mid vs live Polymarket
CLOB anchor. This is the full bias curve, not just the deep tail:

    SIG mid band      n   median SIG/Poly   SIG>Poly   sign p
      0.00-0.05      15        1.95x          15/15    6.1e-05
      0.05-0.08      26        2.35x          26/26      3e-08
      0.08-0.20      31        1.37x          30/31      3e-08
      0.20-0.40      33        1.08x          29/33    1.1e-05
      0.40-0.60      17        1.00x           9/17       1.0
      0.60-0.80      33        0.98x           7/33     0.0013
      0.80-1.00      73        0.97x           1/73    1.6e-20

Two things follow, and together they close the tournament question.

First, the overpricing is not confined to deep longshots. The 0.08-0.20 band
-- proposed in the tournament-theory work as the "tax-free" place to buy
convexity -- is overpriced 1.37x in 30 of 31 markets. That instrument does not
exist on this venue.

Second, the only band SIG prices fairly is 0.40-0.60 (median 1.00, sign test
p=1.0, 9/17 -- indistinguishable from no bias). A near-even contract pays about
2x. Reaching the podium needs 7x in a single settlement, so the contract must
be priced at or below 1/7 = 0.143, which is inside the taxed region. There is
no way around it here: the venue has no parlay product, no leverage, and every
contract settles on the same day, so nothing can be compounded.

Buying the required convexity therefore costs a 1.37x-2.35x markup, which
turns a 10% goal probability into 4-7% while committing ~70% of capital. That
is precisely the reversal condition the tournament analysis set for itself, so
the sleeve stays empty by evidence rather than by accident.

Mirrored: the same curve is why selling tails is our validated edge, and why
the 0.80-1.00 band (0.97x, 1 of 73 above anchor, p=1.6e-20) is the strongest
signal on the board -- those are the same trade seen from the other side.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import round_to_tick
from ..config import MAX_PRICE, MIN_PRICE
from ..executor import DesiredOrder
from .base import MarketView


@dataclass(frozen=True)
class SleeveConfig:
    # Only consider contracts cheap enough to be genuinely convex.
    max_price: float = 0.20
    min_price: float = 0.01
    # Require SIG to be BELOW the anchor by this much — contrary to the
    # measured 1.98x tail overpricing, so this is a filtered signal.
    min_discount: float = 0.02
    # Minimum payoff multiple, so the sleeve is actually convex.
    min_multiple: float = 5.0
    max_positions: int = 8
    size_per_position: float = 250.0      # SUSQies of notional, not shares
    max_existing_shares: float = 100_000.0


class SleeveStrategy:
    name = "sleeve"

    def __init__(self, cfg: SleeveConfig | None = None):
        self.cfg = cfg or SleeveConfig()

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        cands = []
        for ex, q in view.quotes.items():
            fair = view.fair.get(ex)
            if fair is None or not q.tradeable:
                continue
            ask = q.best_ask
            if ask is None or not (c.min_price <= ask <= c.max_price):
                continue
            if 1.0 / ask < c.min_multiple:
                continue
            if abs(view.positions.get(ex, 0.0)) >= c.max_existing_shares:
                continue
            discount = fair - ask           # positive => SIG cheaper than anchor
            if discount < c.min_discount:
                continue
            cands.append((discount, ex, q, ask))

        # Best discount first; convexity should be concentrated, not sprayed.
        cands.sort(key=lambda t: -t[0])
        out: list[DesiredOrder] = []
        for discount, ex, q, ask in cands[:c.max_positions]:
            # Stay passive: join the bid rather than paying the offer. A tail we
            # believe is underpriced is worth waiting for.
            px = round_to_tick(q.best_bid)
            if px < MIN_PRICE or px > MAX_PRICE or px >= ask:
                continue
            qty = max(1, int(round(c.size_per_position / px)))
            out.append(DesiredOrder(exchange_id=ex, side="yes", action="buy",
                                    price=px, quantity=qty, strategy=self.name))
        return out
