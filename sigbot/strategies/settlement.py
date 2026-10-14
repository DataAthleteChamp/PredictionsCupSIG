"""
S6 -- the held-to-settlement convergence book.

This strategy exists because of one line in the Official Rules:

    "The three (3) participants with the highest total SUSQies balance
     FOLLOWING THE RESOLUTION OF ALL MARKETS will receive cash prizes"

The live leaderboard is marked to venue mid, and the venue mid is not the
score. Every contract is credited or debited at resolution, so the only number
that decides the competition is the balance after 2026-11-04T17:00Z. Measured
on 2026-10-08, the top of the leaderboard carried 9.1M SUSQies of *paper*
profit -- rank 1 booked 593k of it on the first day, and the whole top ten
dropped ~15% within a single hour on 2026-10-06. That is correlated mark
revaluation, not trading, and it reverses at settlement.

WHY THIS IS NOT RelValueStrategy
--------------------------------
RelValue has the right thesis and the wrong selection rule. It walks markets in
`by_activity()` order and stops at 60, because it was designed to earn a
microstructure edge, which only exists where there is flow. The convergence
edge lives in exactly the opposite place: the illiquid tails nobody trades.
With `max_notional=120` spread over the 60 busiest markets, it had accumulated
a total short-tail book of 111 shares. The edge was researched for days and
never actually put on.

This strategy ranks by EV per unit of collateral and ignores activity entirely.

THE EDGE (measured 2026-10-08, 228 markets anchored to Polymarket)
------------------------------------------------------------------
SIG compresses probabilities toward 0.5 and never fully corrects:

    Rhode Island Senate (R)     SIG 0.150   anchor 0.007    21x
    South Dakota Senate (D)     SIG 0.095   anchor 0.002    48x
    Delaware Senate (R)         SIG 0.130   anchor 0.017     8x

122 of 228 markets price above their anchor. Selling the tail and holding to
resolution is worth +11.2k on 101k of collateral, and it survives a 2022-sized
polling miss (+10.2k under a 6pp national swing, +8.6k under 10pp) because the
book shorts BOTH parties' tails -- a uniform swing cancels across the two legs.

Depth is not the constraint: 37.5M shares sit on bids above our anchor across
the top 40 markets, against capital that supports roughly 120k shares.

SIZING
------
Rank by return on collateral, (price - fair) / (1 - price), not by raw edge.
Raw edge prefers a 0.205 contract with a 0.110 gap over a 0.150 contract with a
0.143 gap, but the second ties up less cash per share and pays more per unit of
it. Collateral is the binding resource, so it belongs in the denominator.

EXECUTION
---------
Hybrid, and deliberately so. Posting passively earns the spread but may never
fill in a market that trades twice a day; crossing guarantees the fill but pays
the spread. Against a 0.143 edge a one-tick spread is 3.5% of the edge, so
certainty is worth far more than the saving -- but only after passive has been
given a fair chance. So: rest at the offer, and once a market has been targeted
for `cross_after_minutes` without filling, take the bid.

The cross is still guarded. We only lift a bid that leaves `min_edge` intact,
so a book that has gapped away from the anchor is skipped rather than chased.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import round_to_tick
from ..config import MAX_PRICE, MIN_PRICE
from ..executor import DesiredOrder
from .base import MarketView


@dataclass(frozen=True)
class SettlementConfig:
    # Minimum (price - fair) to open, in probability points. Four ticks, which
    # is an order of magnitude above the ~0.4-tick microstructure grind edge.
    min_edge: float = 0.02
    # Only sell inside the tail band. Above this the contract is no longer a
    # longshot and the compression edge we measured does not apply.
    max_sell_price: float = 0.35
    # Below this the premium collected cannot cover a single tick of slippage.
    min_sell_price: float = 0.03
    # How many distinct markets to hold. Diversification is the whole defence
    # against a wrong anchor: 20 independent-ish races at 5% each cannot be
    # undone by any single result.
    max_markets: int = 24
    # Collateral committed per market, as a fraction of equity.
    #
    # Raised 0.05 -> 0.08 on 2026-10-13. By then the opportunity set was
    # exhausted: of 49 unheld candidates only ONE beat our book average of
    # 7.7% return on collateral (11.3%), with the second best at 7.4%. With
    # nothing better to rotate INTO, the only way left to raise the book's
    # return was to put more behind the positions already identified as best.
    #
    # Monte Carlo on the live book, moving 60% of the weakest seven positions
    # into the strongest four: expected P&L +7,265 -> +8,001 with P(loss)
    # 13.2% -> 12.9% and the 5th percentile -4,071 -> -4,933. Slightly fatter
    # tail, materially better mean, and the concentration lands in markets the
    # anchor prices at under 1%.
    per_market_fraction: float = 0.08
    # Total collateral the book may commit, as a fraction of equity. The risk
    # manager's own budget also applies; the lower of the two binds.
    max_book_fraction: float = 0.78
    # Rest passively for at least this long before crossing. One cycle is
    # ~5.5 min, so this gives passive two clean attempts.
    cross_after_minutes: float = 12.0
    # Ignore dust shortfalls rather than churning one-share orders.
    min_shares: int = 25
    # Never send more than this in one market in one cycle; a single enormous
    # order is both more visible and more likely to be partially filled at a
    # worse average price than a sequence of smaller ones.
    max_shares_per_order: int = 4_000
    # --- rotation gates ------------------------------------------------
    # Rank of the candidate a holding is judged against. Comparing to the
    # single best market would rotate everything into one name that cannot
    # absorb it; this asks "is there a realistic home for this capital?".
    #
    # Lowered 8 -> 3 on 2026-10-13. The candidate list decays far faster than
    # assumed -- measured #1=11.3%, #2=7.4%, #3=7.0%, #8=5.5% -- so judging
    # against the eighth-best compared our holdings to a target barely better
    # than themselves and rotation correctly found nothing to do. Three is
    # about what the per-market cap can actually absorb in one pass.
    rotate_rank: int = 3
    # A holding must be worse than target/ratio before it is worth unwinding.
    # Round-tripping costs roughly one tick each way, so a 10-20% edge
    # improvement is consumed entirely by the spread.
    rotate_ratio: float = 1.8
    # ...and the gap must also be this many points of return on collateral in
    # absolute terms, so near-zero edges cannot clear the ratio on noise.
    rotate_min_gain: float = 0.02
    # Markets rotated per cycle. An unwind that runs away costs far more than
    # a slow rotation gains, and the book has 23 days to converge.
    rotate_max_markets: int = 2


class SettlementStrategy:
    name = "settlement"

    def __init__(self, cfg: SettlementConfig | None = None):
        self.cfg = cfg or SettlementConfig()

    # ------------------------------------------------------------- ranking --

    def candidates(self, view: MarketView) -> list[tuple[str, float, float]]:
        """
        Markets worth shorting, best return-on-collateral first.

        Returns (exchange_id, sell_price, return_on_collateral). The price is
        the one we would actually rest at, so the edge is evaluated where the
        trade would happen rather than at an unreachable mid.
        """
        c = self.cfg
        out = []
        for ex, q in view.quotes.items():
            fair = view.fair.get(ex)
            if fair is None or not q.tradeable or q.best_ask is None:
                continue
            px = round_to_tick(q.best_ask)
            if not (c.min_sell_price <= px <= min(c.max_sell_price, MAX_PRICE)):
                continue
            if px - fair < c.min_edge:
                continue
            coll = 1.0 - px
            if coll <= 0:
                continue
            out.append((ex, px, (px - fair) / coll))
        out.sort(key=lambda r: (-r[2], str(r[0])))
        return out

    def holds(self, view: MarketView) -> set[str]:
        """
        Positions currently held for their settlement value.

        Used by the risk manager to exempt these marks from the drawdown kill
        switch, so membership is deliberately re-derived from the anchor every
        cycle rather than remembered. A short whose anchor no longer supports
        it loses the exemption immediately and is marked like anything else --
        the exemption is conditional on the thesis, not on how we got in.

        The test is the EDGE only. It deliberately does NOT apply
        `max_sell_price`, which is an opening rule: it says where the measured
        favourite-longshot bias lives and therefore where we are willing to
        start a position. Whether to KEEP one is a different question, and
        answering it with the opening rule punishes exactly the positions that
        have moved against us. Measured 2026-10-14: four shorts drifted above
        0.35 (to 0.362-0.438) while still carrying +0.023 to +0.073 of edge,
        and all four silently lost both their kill-switch exemption and their
        protection from ExitStrategy -- the trade was going against us, so we
        made it eligible to be closed at a loss.

        The edge test alone is the right guard. A position the anchor stops
        supporting drops out on its own, wherever it is priced.
        """
        c = self.cfg
        out = set()
        for ex, qty in view.positions.items():
            if qty >= 0:                       # only short tails qualify
                continue
            q = view.quotes.get(ex)
            fair = view.fair.get(ex)
            if q is None or q.mid is None or fair is None:
                continue
            if q.mid - fair >= c.min_edge:
                out.add(ex)
        return out

    # ------------------------------------------------------------ rotation --

    def rotations(self, view: MarketView) -> list[DesiredOrder]:
        """
        Close holdings whose remaining edge is far worse than what is available.

        The book is built once and then frozen: `desired` only ever ADDS, and
        with the deployment cap binding there is never room to add anything
        better. Measured 2026-10-13, 11 of 32 holdings (24,112 of collateral)
        carried less remaining edge than the eighth-best market we did not own
        -- ours at 2.6-5.4% return on collateral against 5.9-9.5% available.

        Rotation is deliberately hard to trigger. Closing a short costs the
        spread and re-opening costs it again, roughly 1 tick each way, so a
        marginal improvement is worth nothing after costs. The gate is a
        MULTIPLE plus an absolute floor, and only a bounded number of markets
        move per cycle, because an unwind that runs away is far more expensive
        than a slow rotation is valuable.

        Closing orders are exempt from the opening-side risk caps, so these
        cannot deadlock against the deployment cap the way a new short would.
        """
        c = self.cfg
        cands = self.candidates(view)
        if not cands:
            return []
        best = [r for _ex, _px, r in cands[:c.max_markets]]
        if not best:
            return []
        # Compare against what we could realistically rotate INTO, not the
        # single best market, which one position can never absorb.
        target_roc = best[min(len(best) - 1, c.rotate_rank)]

        ranked = []
        for ex, qty in view.positions.items():
            if qty >= 0:
                continue
            q = view.quotes.get(ex)
            fair = view.fair.get(ex)
            if q is None or fair is None or not q.tradeable or q.best_ask is None:
                continue
            mid = q.mid
            if mid is None or mid >= 1.0:
                continue
            roc = (mid - fair) / (1.0 - mid)
            ranked.append((roc, ex, q, -qty))
        ranked.sort()

        out = []
        for roc, ex, q, shares in ranked[:c.rotate_max_markets]:
            if roc >= target_roc / c.rotate_ratio:
                break
            if target_roc - roc < c.rotate_min_gain:
                break
            # Close by BUYING YES back. Join the offer rather than crossing:
            # the position is not urgent, and paying up to exit a position we
            # entered for its edge would hand back the gain twice over.
            px = round_to_tick(q.best_ask)
            if not (MIN_PRICE <= px <= MAX_PRICE):
                continue
            n = int(min(shares, c.max_shares_per_order))
            if n < c.min_shares:
                continue
            out.append(DesiredOrder(ex, "yes", "buy", px, n, self.name))
        return out

    # -------------------------------------------------------------- orders --

    def desired(self, view: MarketView) -> list[DesiredOrder]:
        c = self.cfg
        out: list[DesiredOrder] = list(self.rotations(view))
        rotating = {o.exchange_id for o in out}
        budget = c.max_book_fraction * view.equity
        per_market = c.per_market_fraction * view.equity
        committed = 0.0

        for ex, px, _roc in self.candidates(view)[:c.max_markets]:
            if committed >= budget:
                break
            if ex in rotating:          # never buy and sell the same market
                continue
            q = view.quotes[ex]
            fair = view.fair[ex]

            # Hybrid: rest at the offer, then take the bid once passive has had
            # its chance. The bid must still clear min_edge on its own -- we
            # cross to buy certainty, never to chase a book that has moved.
            price = px
            waited = view.targeted_minutes.get(ex, 0.0)
            if waited >= c.cross_after_minutes and q.best_bid is not None:
                bid = round_to_tick(q.best_bid)
                if bid - fair >= c.min_edge and bid >= c.min_sell_price:
                    price = bid

            coll_per_share = 1.0 - price
            if coll_per_share <= 0:
                continue

            # Size to the SHORTFALL against the target, not to the target, or
            # every cycle would re-request a position we already hold.
            held_short = max(0.0, -view.positions.get(ex, 0.0))
            target_shares = min(per_market, budget - committed) / coll_per_share
            shortfall = int(target_shares - held_short)
            if shortfall < c.min_shares:
                committed += held_short * coll_per_share
                continue

            qty = min(shortfall, c.max_shares_per_order)
            out.append(DesiredOrder(ex, "yes", "sell", price, qty, self.name))
            committed += (held_short + qty) * coll_per_share
        return out
