"""
Replay backtest over the recorded tape, with a deliberately pessimistic fill
rule and a validation step against our own live fills.

WHY THIS EXISTS

Several config changes shipped this week turned out to be regressions that were
only found in production: a share clamp that missed its own target band, a hold
rule that evicted the ladder from its best markets, and a deep rung that took a
third of the order slots and never filled once in 688 fills. Each cost real
money for a day or more. A replay that can be TRUSTED would have caught the
first and third before deployment.

THE HARD PART: FILLS

We have top-of-book quotes sampled every ~1.9 minutes per market and a public
trade tape, but no depth and no queue position. So a passive order's fill is
not observable, only inferable. Two rules bracket the truth:

  pessimistic  a buy at P fills only if a trade prints strictly BELOW P
               (someone sold through our level, so the queue ahead of us at P
               must have been consumed)
  optimistic   a buy at P fills if a trade prints at or below P
               (assumes we were at the front of the queue)

Reality is between them, nearer the pessimistic end when we are a small part of
the book. Both are reported, because a single number here would imply a
precision the data does not support.

VALIDATION IS THE POINT

A fill simulator that is not checked against reality is a random number
generator with extra steps. `validate()` replays the configuration we ACTUALLY
ran over the window we actually ran it, and compares simulated fills per
order-hour against the fills we really got. If the simulator cannot reproduce
history it must not be used to justify a change, and the ratio it reports is
the factor by which it is optimistic.
"""
from __future__ import annotations

import collections
import datetime as dt
import sqlite3
from dataclasses import dataclass

TICK = 0.005


def _ts(s: str) -> float:
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


@dataclass
class Fill:
    t: float
    exchange_id: str
    price: float
    depth_ticks: float


class Tape:
    """Quotes and trades from research/data/tape.db, indexed for replay."""

    def __init__(self, path: str = "research/data/tape.db",
                 since: str = "2026-10-01"):
        con = sqlite3.connect(path)
        self.mids: dict[str, list[tuple[float, float]]] = {}
        for ts, ex, b, a in con.execute(
                "SELECT ts, exchange_id, bid, ask FROM quote "
                "WHERE bid IS NOT NULL AND ask IS NOT NULL AND ts >= ? "
                "ORDER BY ts", (since,)):
            self.mids.setdefault(str(ex), []).append(
                (_ts(ts), (float(b) + float(a)) / 2.0))
        self.trades: dict[str, list[tuple[float, float]]] = {}
        for ts, ex, px in con.execute(
                "SELECT created_at, exchange_id, price FROM trade "
                "WHERE created_at >= ? ORDER BY created_at", (since,)):
            self.trades.setdefault(str(ex), []).append((_ts(ts), float(px)))
        con.close()

    def window(self) -> tuple[float, float]:
        lo = min(v[0][0] for v in self.mids.values() if v)
        hi = max(v[-1][0] for v in self.mids.values() if v)
        return lo, hi

    def mid_at(self, ex: str, t: float) -> float | None:
        s = self.mids.get(ex)
        if not s:
            return None
        lo, hi = 0, len(s) - 1
        while lo < hi:
            m = (lo + hi) // 2
            if s[m][0] < t:
                lo = m + 1
            else:
                hi = m
        i = max(0, lo - 1)
        return s[i][1] if abs(s[i][0] - t) <= 300 else None


def replay(tape: Tape, offsets: tuple[float, ...], *, max_markets: int,
           cycle_s: float = 300.0, horizon_s: float = 300.0,
           optimistic: bool = False, floor_price: float = 0.15,
           min_mid: float = 0.20, max_mid: float = 0.85) -> dict:
    """
    Replay one ladder configuration over the tape.

    Markets are ranked by trade count, mirroring the live activity ranking.
    Returns fills, fill rate per order-hour, and mean markout at `horizon_s`.
    """
    ranked = sorted(tape.trades, key=lambda e: -len(tape.trades[e]))[:max_markets]
    t0, t1 = tape.window()
    fills: list[Fill] = []
    order_hours = 0.0

    for ex in ranked:
        prints = tape.trades.get(ex, [])
        if not prints:
            continue
        pi = 0
        t = t0
        while t < t1:
            mid = tape.mid_at(ex, t)
            nxt = t + cycle_s
            if mid is None or not (min_mid <= mid <= max_mid):
                t = nxt
                continue
            # advance the trade cursor to this cycle
            while pi < len(prints) and prints[pi][0] < t:
                pi += 1
            lows = [p for ts_, p in prints[pi:] if ts_ < nxt]
            for off in offsets:
                px = round((mid - off) / TICK) * TICK
                if px < floor_price:
                    continue
                order_hours += cycle_s / 3600.0
                hit = any((p < px) or (optimistic and p <= px) for p in lows)
                if hit:
                    later = tape.mid_at(ex, t + horizon_s)
                    if later is not None:
                        fills.append(Fill(t, ex, px, (mid - px) / TICK))
            t = nxt

    mk = []
    for f in fills:
        later = tape.mid_at(f.exchange_id, f.t + horizon_s)
        if later is not None:
            mk.append(later - f.price)
    n = len(fills)
    return {
        "offsets": offsets,
        "fills": n,
        "order_hours": order_hours,
        "fills_per_order_hour": n / order_hours if order_hours else 0.0,
        "markout": sum(mk) / len(mk) if mk else 0.0,
        "pnl_per_order_hour": (sum(mk) / order_hours) if order_hours else 0.0,
    }


def validate(tape: Tape, live_fills_per_order_hour: float,
             offsets: tuple[float, ...], max_markets: int) -> dict:
    """
    Compare the simulator against what the SAME configuration actually did.

    The returned ratios are the factor by which each fill rule is optimistic.
    A simulator that cannot reproduce history must not be used to justify a
    change; it can only be used to rank configurations if its bias is roughly
    constant across them, which this ratio is the evidence for.
    """
    pess = replay(tape, offsets, max_markets=max_markets, optimistic=False)
    opt = replay(tape, offsets, max_markets=max_markets, optimistic=True)
    return {
        "live_fills_per_order_hour": live_fills_per_order_hour,
        "pessimistic": pess["fills_per_order_hour"],
        "optimistic": opt["fills_per_order_hour"],
        "pessimistic_ratio": (pess["fills_per_order_hour"]
                              / live_fills_per_order_hour
                              if live_fills_per_order_hour else float("nan")),
        "optimistic_ratio": (opt["fills_per_order_hour"]
                             / live_fills_per_order_hour
                             if live_fills_per_order_hour else float("nan")),
    }


# Depth-dependent calibration, measured by comparing the simulator's fill-share
# by depth against our own live ladder fills:
#
#     depth   sim share   live share   correction
#       1t      64.0%        47.8%       0.75
#       2t      21.5%        25.1%       1.17
#       3t       7.9%        17.8%       2.25
#       4t       3.9%         6.0%       1.54
#       6t       1.6%         2.7%       1.69
#       8t       1.0%         0.5%       0.50
#
# The simulator systematically OVER-counts shallow fills because it has no
# queue position: it assumes a print through our price reaches us, which is
# least true where the queue is longest, i.e. near the touch. Uncorrected it
# ranks 1-tick quoting best; corrected, 3 ticks wins. Acting on the raw output
# would have moved the ladder to the touch, where our own live markout is
# +0.00085 at best and NEGATIVE inside the mid.
FILL_CALIBRATION = {1: 0.75, 2: 1.17, 3: 2.25, 4: 1.54, 6: 1.69, 8: 0.50}


def calibrated_rate(depth_ticks: int, raw_rate: float) -> float:
    """Scale a simulated fill rate by the measured per-depth bias."""
    keys = sorted(FILL_CALIBRATION)
    k = min(keys, key=lambda x: abs(x - depth_ticks))
    return raw_rate * FILL_CALIBRATION[k]
