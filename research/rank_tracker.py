#!/usr/bin/env python3
"""
Rank-neighbourhood tracker.

The existing tape.db `lb` table only ever captures the top 100 of the
leaderboard (confirmed 2026-10-28: min(rank)=1, max(rank)=100 across 2,372
snapshots), so it cannot answer "are players near OUR rank moving together,
or are we moving independently of them" -- our actual peer group (other
diversified anchor-arbitrage books, not the top 100's early-big-bet
winners) was never logged at all.

This fills that gap going forward: every cycle, pulls our own rank and a
window around it (+/- NEIGHBOURHOOD ranks), so we can compute, from here to
the Nov 4 lock, whether a given move in our own P&L is shared by the ranks
immediately around us (market-wide noise) or specific to us (a real
divergence worth investigating).

Read-only. Uses the recon key only. Never places orders.
"""
import os, json, sqlite3, time, urllib.request, urllib.error, datetime, pathlib

BASE = os.environ["SIG_BASE_URL"]
KEY = os.environ["SIG_RECON_KEY"]
# Deliberately a SEPARATE file from tape.db. collector.py writes to tape.db
# continuously; sharing it risked "database is locked" contention for no
# benefit, since this data has nothing to do with quotes/trades.
DB = pathlib.Path(__file__).parent / "data" / "rank_tracker.db"

SNAP_EVERY = 300          # 5 min, matching the live bot's own cycle cadence
NEIGHBOURHOOD = 49        # ranks on each side of us (2*49+1=99, API caps limit<=100)


def api(path, tries=5):
    for a in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + KEY})
            return json.load(urllib.request.urlopen(req, timeout=45))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (a + 1))
                continue
            return None
        except Exception:
            time.sleep(1.5 * (a + 1))
    return None


def init(con):
    con.executescript("""
    CREATE TABLE IF NOT EXISTS lb_neighbourhood(
      ts TEXT, rank INTEGER, username TEXT, pnl REAL, trades INTEGER,
      total INTEGER, my_rank INTEGER,
      PRIMARY KEY(ts, rank));
    """)
    con.commit()


def tournament_slug():
    cfg = api("/tournaments?status=active")
    if cfg and cfg.get("data"):
        return cfg["data"][0]["slug"]
    return "midterm-elections"


def main():
    con = sqlite3.connect(str(DB))
    init(con)
    slug = tournament_slug()
    print(f"rank_tracker starting, tournament={slug}, neighbourhood=+/-{NEIGHBOURHOOD}",
          flush=True)
    while True:
        try:
            d = api(f"/tournaments/{slug}/leaderboard?period=all&limit=1")
            if d is None:
                time.sleep(SNAP_EVERY)
                continue
            my_rank, total = d["myRank"], d["total"]
            offset = max(0, my_rank - 1 - NEIGHBOURHOOD)
            window = min(2 * NEIGHBOURHOOD + 1, total - offset)
            page = api(f"/tournaments/{slug}/leaderboard?period=all&limit={window}&offset={offset}")
            ts = datetime.datetime.now(datetime.timezone.utc).isoformat()
            if page and page.get("leaderboard"):
                rows = [(ts, offset + i + 1, r["username"], r["pnl"], r["tradesCount"],
                         total, my_rank)
                        for i, r in enumerate(page["leaderboard"])]
                con.executemany(
                    "INSERT OR IGNORE INTO lb_neighbourhood VALUES (?,?,?,?,?,?,?)", rows)
                con.commit()
                print(f"{ts} my_rank={my_rank}/{total} logged {len(rows)} rows", flush=True)
        except Exception as e:
            print(f"error: {e}", flush=True)
        time.sleep(SNAP_EVERY)


if __name__ == "__main__":
    main()
