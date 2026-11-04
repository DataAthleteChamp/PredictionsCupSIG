"""
Price-band experiment: does market-making cheap contracts actually pay more?

THE MEASUREMENT THAT PROMPTED THIS
----------------------------------
Leaderboard volume is notional (verified: our own reported volume, 275,568.17,
equals our own summed fill notional to the SUSQie). So P&L per unit volume is
directly comparable across players, and it is the whole gap:

    kind-brook-6861  (rank 1)     9.99%
    calm-badger-5206 (rank 6)    15.03%
    us              (rank 232)    0.72%

The cause is price level, not skill. One tick is 0.6% of a 0.90 contract and
16.7% of a 0.03 one, and 84% of our traded notional sits in 0.50-1.00. Relative
price travel over the whole contest confirms where the movement is:

    price bucket   travel / price
    0.00-0.05          62.5
    0.05-0.10          54.5
    0.10-0.20          37.6
    0.20-0.50          11.1
    0.50-1.00           4.8

WHY THE EXISTING BACKTEST COULD NEVER HAVE FOUND THIS
-----------------------------------------------------
`backtest.replay` scores a configuration by `markout`, measured in ABSOLUTE
price units. That metric is not neutral: a +0.005 markout is a 10% return on a
0.05 contract and a 0.56% return on a 0.90 one, and the absolute number is
identical. Ranking by it systematically prefers expensive contracts, which is
exactly where our ladder ended up.

So this experiment reports BOTH, and treats return-on-notional as the decision
metric. It also replays the sell side, which `replay` does not model at all --
it only ever posts bids.

HONESTY ABOUT THE SIMULATOR
---------------------------
It has no queue position, so it over-counts fills nearest the touch. The
measured per-depth correction in backtest.FILL_CALIBRATION is applied here
unchanged. Absolute levels remain unreliable; only the RANKING of
configurations is used, and only where the gap is large.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass

sys.path.insert(0, "research")
from backtest import TICK, FILL_CALIBRATION, Tape, _ts          # noqa: E402

BUCKETS = ((0.00, 0.05), (0.05, 0.10), (0.10, 0.20),
           (0.20, 0.50), (0.50, 1.00))


def bucket_of(p: float) -> tuple[float, float]:
    for lo, hi in BUCKETS:
        if lo <= p < hi:
            return (lo, hi)
    return BUCKETS[-1]


@dataclass
class Quote:
    t: float
    ex: str
    price: float
    side: str            # "buy" | "sell"
    depth_ticks: float


def _calib(depth_ticks: float) -> float:
    keys = sorted(FILL_CALIBRATION)
    k = min(keys, key=lambda x: abs(x - depth_ticks))
    return FILL_CALIBRATION[k]


def replay_band(tape: Tape, *, offsets, proportional: bool,
                min_mid: float, max_mid: float, sides: str = "both",
                max_markets: int = 240, cycle_s: float = 300.0,
                horizon_s: float = 300.0, floor_price: float = 0.0,
                optimistic: bool = False) -> dict:
    """
    Replay a two-sided quoting configuration and score it by RETURN ON
    NOTIONAL as well as by absolute markout.

    `proportional=True` reads `offsets` as fractions of the mid rather than
    absolute prices, so a 0.20 offset is 1 tick at 0.025 and 18 ticks at 0.45.
    That is the change under test: an absolute 0.015 offset is 21% of a 0.07
    contract and cannot ever sit near its touch.
    """
    ranked = sorted(tape.trades, key=lambda e: -len(tape.trades[e]))[:max_markets]
    t0, t1 = tape.window()
    per_bucket: dict[tuple, dict] = {b: {"fills": 0, "oh": 0.0, "mk": 0.0,
                                         "roi": 0.0, "notional": 0.0,
                                         "capital": 0.0}
                                     for b in BUCKETS}

    for ex in ranked:
        prints = tape.trades.get(ex, [])
        if not prints:
            continue
        pi, t = 0, t0
        while t < t1:
            mid = tape.mid_at(ex, t)
            nxt = t + cycle_s
            if mid is None or not (min_mid <= mid <= max_mid):
                t = nxt
                continue
            while pi < len(prints) and prints[pi][0] < t:
                pi += 1
            window = [p for ts_, p in prints[pi:] if ts_ < nxt]
            b = bucket_of(mid)
            for off in offsets:
                delta = mid * off if proportional else off
                for side in (("buy", "sell") if sides == "both" else (sides,)):
                    px = (mid - delta) if side == "buy" else (mid + delta)
                    px = round(px / TICK) * TICK
                    if px <= 0 or px >= 1.0:
                        continue
                    if side == "buy" and px < floor_price:
                        continue
                    depth = abs(mid - px) / TICK
                    if depth < 1:          # cannot quote inside one tick
                        continue
                    s = per_bucket[b]
                    s["oh"] += cycle_s / 3600.0
                    hit = any((p < px if side == "buy" else p > px)
                              or (optimistic and (p <= px if side == "buy"
                                                  else p >= px))
                              for p in window)
                    if not hit:
                        continue
                    later = tape.mid_at(ex, t + horizon_s)
                    if later is None:
                        continue
                    # Markout in the direction of the position taken.
                    mk = (later - px) if side == "buy" else (px - later)
                    w = _calib(depth)
                    s["fills"] += w
                    s["mk"] += mk * w
                    # Return on CAPITAL, which is what we are actually short of.
                    #
                    # Not return on notional. For a BUY the two coincide --
                    # cash paid is price*q. For a SELL they do not: shorting a
                    # 0.05 contract receives 0.05 but ties up 0.95 of
                    # collateral, so scoring it against notional overstates it
                    # by 19x. An earlier version of this file made exactly that
                    # error and ranked short-tail quoting far too highly.
                    #
                    # This also explains the leaderboard. P&L-per-volume uses
                    # notional as the denominator, and for a BUY that equals
                    # capital -- so a player who buys cheap contracts shows a
                    # huge P&L/volume honestly, while the same number for a
                    # seller is a measurement artefact.
                    capital = px if side == "buy" else (1.0 - px)
                    s["roi"] += (mk / capital) * w
                    s["notional"] += px * w
                    s["capital"] += capital * w
            t = nxt

    tot = {"fills": 0.0, "oh": 0.0, "mk": 0.0, "roi": 0.0, "notional": 0.0,
           "capital": 0.0}
    for s in per_bucket.values():
        for k in tot:
            tot[k] += s[k]
    return {"per_bucket": per_bucket, "total": tot,
            "markout_per_fill": tot["mk"] / tot["fills"] if tot["fills"] else 0.0,
            "roi_per_fill": tot["roi"] / tot["fills"] if tot["fills"] else 0.0,
            "pnl_per_capital": tot["mk"] / tot["capital"] if tot["capital"] else 0.0,
            "pnl_per_order_hour": tot["mk"] / tot["oh"] if tot["oh"] else 0.0,
            "roi_per_order_hour": tot["roi"] / tot["oh"] if tot["oh"] else 0.0}


def show(name: str, r: dict) -> None:
    t = r["total"]
    print(f"\n=== {name} ===")
    print(f"  fills={t['fills']:>9,.0f}  order_hours={t['oh']:>10,.0f}  "
          f"notional={t['notional']:>12,.0f}")
    print(f"  markout/fill={r['markout_per_fill']:+.5f}   "
          f"ROIcap/fill={r['roi_per_fill']*100:+.2f}%")
    print(f"  capital-weighted return={r['pnl_per_capital']*100:+.3f}% "
          f"per round trip   capital={t['capital']:>12,.0f}")
    print(f"  P&L/order-hour={r['pnl_per_order_hour']:+.5f}   "
          f"ROI/order-hour={r['roi_per_order_hour']*100:+.3f}%")
    print(f"  {'bucket':<12} {'fills':>9} {'mk/fill':>10} {'ROIcap':>10}")
    for b, s in r["per_bucket"].items():
        if s["fills"] < 1:
            continue
        print(f"  {f'{b[0]:.2f}-{b[1]:.2f}':<12} {s['fills']:>9,.0f} "
              f"{s['mk']/s['fills']:>+10.5f} {s['roi']/s['fills']*100:>+9.2f}%")


if __name__ == "__main__":
    tape = Tape()
    print(f"tape: {len(tape.mids)} markets with quotes, "
          f"{sum(len(v) for v in tape.trades.values()):,} trades")

    # A: what we run today -- absolute offsets, locked to 0.20-0.85, bids only.
    show("A  CURRENT (absolute offsets, 0.20-0.85, buy side)",
         replay_band(tape, offsets=(0.015, 0.02, 0.03), proportional=False,
                     min_mid=0.20, max_mid=0.85, sides="buy",
                     floor_price=0.15, max_markets=80))

    # B: same offsets, but allowed into the tails. Isolates the BAND from the
    # offset scheme -- if absolute offsets simply cannot quote there, B will
    # show almost no fills below 0.20 despite being allowed in.
    show("B  CURRENT OFFSETS, BAND OPENED (0.03-0.85, buy side)",
         replay_band(tape, offsets=(0.015, 0.02, 0.03), proportional=False,
                     min_mid=0.03, max_mid=0.85, sides="buy",
                     floor_price=0.0, max_markets=240))

    # C: proportional offsets across the whole band, sell side only -- the
    # short-tail market-making actually proposed, which never opens a long
    # longshot and so keeps the measured favourite-longshot edge intact.
    show("C  PROPORTIONAL OFFSETS, SELL SIDE (0.03-0.85)",
         replay_band(tape, offsets=(0.10, 0.18, 0.30), proportional=True,
                     min_mid=0.03, max_mid=0.85, sides="sell",
                     max_markets=240))

    # D: proportional, both sides, for reference on what we give up by
    # refusing to open long tails.
    show("D  PROPORTIONAL OFFSETS, BOTH SIDES (0.03-0.85)",
         replay_band(tape, offsets=(0.10, 0.18, 0.30), proportional=True,
                     min_mid=0.03, max_mid=0.85, sides="both",
                     max_markets=240))

    # --- follow-up: the correction above kills the short-tail proposal, so
    # test the change that IS supported -- concentrating the existing buy-side
    # ladder in the band that actually pays, rather than extending it.
    for lo, hi, label in ((0.20, 0.85, "E  current band 0.20-0.85"),
                          (0.20, 0.50, "F  narrowed  0.20-0.50"),
                          (0.15, 0.50, "G  narrowed  0.15-0.50"),
                          (0.15, 0.60, "H  narrowed  0.15-0.60"),
                          (0.20, 0.65, "I  narrowed  0.20-0.65")):
        show(label, replay_band(tape, offsets=(0.015, 0.02, 0.03),
                                proportional=False, min_mid=lo, max_mid=hi,
                                sides="buy", floor_price=0.15, max_markets=80))
