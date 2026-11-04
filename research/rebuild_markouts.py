"""
Recompute markouts from the timestamped tape instead of from live polls.

The original collector had two timing defects, both of which bias the measured
edge UPWARD:

  1. `mid_at_fill` was stamped with the mid at DISCOVERY -- whenever the poller
     next ran -- not the mid at `filled_at`. A fill found twenty minutes later
     was compared against a twenty-minute-old market.

  2. `take_markouts` fetched ONE current mid and wrote it for every horizon
     that happened to be due. A fill that was already four hours old when first
     polled had its 1m, 5m, 30m and 240m "markouts" all set to the same
     observation. Only 2 of 304 fills collapsed fully, but partial collapse is
     widespread, and it compresses the horizon curve toward the long end.

Both are fixed here by reading mids out of tape.db at the times they actually
matter: `filled_at` for entry, `filled_at + horizon` for each markout.

The tape samples each exchange roughly every 1.9 minutes, so a horizon is only
reported when a quote exists within a tolerance of the target time. Horizons
that cannot be measured are DROPPED rather than filled in with the nearest
available quote -- substituting a far-away quote is precisely what produced the
original bias.
"""
import datetime as dt
import sqlite3
import sys

sys.path.insert(0, ".")
from sigbot.algos import markout          # noqa: E402  (single source of truth)

HORIZONS_MIN = (1, 5, 30, 240)
# A quote may stand in for the target time only if it is this close. Scaled by
# horizon because a 90-second error matters far more at 1 minute than at 4
# hours, but floored so short horizons are not measured with stale quotes.
def tolerance_s(h_min: int) -> float:
    return max(90.0, 0.25 * h_min * 60.0)


def _parse(ts: str) -> dt.datetime:
    return dt.datetime.fromisoformat(ts.replace("Z", "+00:00"))


def load_quotes(tape: sqlite3.Connection) -> dict[str, list]:
    """exchange_id -> [(epoch_seconds, yes_mid)], ascending."""
    out: dict[str, list] = {}
    for ts, ex, bid, ask in tape.execute(
            "SELECT ts, exchange_id, bid, ask FROM quote "
            "WHERE bid IS NOT NULL AND ask IS NOT NULL ORDER BY ts"):
        out.setdefault(str(ex), []).append(
            (_parse(ts).timestamp(), (float(bid) + float(ask)) / 2.0))
    return out


def mid_at(series: list, target: float, tol: float) -> float | None:
    """Nearest quote to `target`, or None if none lies within `tol`."""
    if not series:
        return None
    lo, hi = 0, len(series) - 1
    while lo < hi:                       # binary search for insertion point
        mid = (lo + hi) // 2
        if series[mid][0] < target:
            lo = mid + 1
        else:
            hi = mid
    best = None
    for i in (lo - 1, lo, lo + 1):
        if 0 <= i < len(series):
            d = abs(series[i][0] - target)
            if best is None or d < best[0]:
                best = (d, series[i][1])
    return best[1] if best and best[0] <= tol else None


def main() -> None:
    tape = sqlite3.connect("research/data/tape.db")
    mk = sqlite3.connect("research/data/markout.db")
    quotes = load_quotes(tape)

    fills = mk.execute(
        "SELECT fill_id, exchange_id, price, quantity, side, filled_at, "
        "mid_at_fill FROM fill").fetchall()

    mk.execute("""CREATE TABLE IF NOT EXISTS markout_v2(
        fill_id INTEGER, horizon_min INTEGER, mid_at_fill REAL, mid REAL,
        markout_per_share REAL, PRIMARY KEY(fill_id, horizon_min))""")
    mk.execute("DELETE FROM markout_v2")

    entry_ok = entry_missing = 0
    written = {h: 0 for h in HORIZONS_MIN}
    drift = []

    for fid, ex, px, qty, side, fat, old_mid in fills:
        series = quotes.get(str(ex), [])
        t0 = _parse(fat).timestamp()
        m0 = mid_at(series, t0, tolerance_s(1))
        if m0 is None:
            entry_missing += 1
            continue
        entry_ok += 1
        if old_mid is not None:
            drift.append(abs(float(old_mid) - m0))
        for h in HORIZONS_MIN:
            m1 = mid_at(series, t0 + h * 60.0, tolerance_s(h))
            if m1 is None:
                continue
            mk.execute("INSERT OR REPLACE INTO markout_v2 VALUES(?,?,?,?,?)",
                       (fid, h, m0, m1, markout(px, m1, side)))
            written[h] += 1
    mk.commit()

    print(f"fills                     : {len(fills)}")
    print(f"  entry mid recovered     : {entry_ok}")
    print(f"  entry mid unavailable   : {entry_missing}")
    if drift:
        drift.sort()
        print(f"  |stamped - true| entry mid: median {drift[len(drift)//2]:.4f}  "
              f"p90 {drift[int(0.9*len(drift))]:.4f}  max {drift[-1]:.4f}")
    print("\nmeasurable horizons:")
    for h in HORIZONS_MIN:
        print(f"  {h:>4}m: {written[h]:>4}")


if __name__ == "__main__":
    main()
