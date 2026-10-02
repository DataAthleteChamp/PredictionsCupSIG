"""
S5 — pair completion. The market-neutral income engine.

The problem it solves: the ladder buys dips, which leaves us holding ONE side of
a race. That is a directional bet. Measured on our live book, the guaranteed
floor across 11 races was **-772.77** — zero of them risk-free.

The fix is structural, not predictive. Every race resolves to exactly one
outcome, so if we hold all sides of a race for a combined cost below 1.0, we are
paid 1.0 whatever happens. There is no forecast involved and no exposure to the
national swing factor that moves all races together.

So: for each race where we are already long one side, rest a bid on the
complement at the highest price that still leaves a non-negative guaranteed
floor. When it fills, that race becomes risk-free and stays that way.

This is how the system earns regardless of what the market does.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..algos import round_to_tick
from ..config import MAX_PRICE, MIN_PRICE
from ..executor import DesiredOrder
from ..portfolio import RacePosition
from .base import MarketView


@dataclass(frozen=True)
class PairConfig:
    # Require this much locked profit per pair before bothering, in points.
    min_lock_edge: float = 0.01
    # Never bid above this fraction of the theoretical lock price, so a fill
    # always leaves a margin rather than landing exactly at break-even.
    price_haircut: float = 0.005
    max_markets: int = 80
    # Cap the completion size at the existing leg so we do not over-pair.
    max_quantity: int = 5_000


class PairStrategy:
    name = "ladder"          # shares the ladder's budget: it completes its fills

    def __init__(self, cfg: PairConfig | None = None):
        self.cfg = cfg or PairConfig()

    def desired(self, view: MarketView,
                races: dict[str, RacePosition] | None = None,
                party_exchange: dict[tuple[str, str], str] | None = None
                ) -> list[DesiredOrder]:
        """
        `races` maps race name -> our current RacePosition.
        `party_exchange` maps (race, party) -> exchange id, so we know where to bid.
        """
        if not races or not party_exchange:
            return []
        c = self.cfg
        out: list[DesiredOrder] = []
        used = 0
        for race, rp in sorted(races.items()):
            if used >= c.max_markets:
                break
            if rp.is_risk_free:
                continue                      # already locked; leave it alone
            # Which outcome hurts us most? Completing THAT side raises the floor.
            worst = min(rp.outcomes, key=lambda w: rp.payout_if(w))
            ex = party_exchange.get((race, worst))
            if ex is None:
                continue
            q = view.quotes.get(ex)
            if q is None or not q.tradeable:
                continue
            qty = int(min(c.max_quantity,
                          max(abs(l.quantity) for l in rp.legs) if rp.legs else 0))
            if qty <= 0:
                continue
            lock_px = rp.max_price_to_lock(worst, qty)
            if lock_px is None:
                continue
            # Stay passive: join the bid, never improve or cross. Measured EV of
            # improving the touch is negative, and a lock is worth waiting for.
            target = round_to_tick(min(lock_px - c.price_haircut, q.best_bid))
            if target < MIN_PRICE or target > MAX_PRICE:
                continue
            # Only worth doing if it genuinely locks something.
            if lock_px - target < c.min_lock_edge:
                continue
            if q.best_ask is not None and target >= q.best_ask:
                continue
            out.append(DesiredOrder(exchange_id=ex, side="yes", action="buy",
                                    price=target, quantity=qty,
                                    strategy=self.name))
            used += 1
        return out
