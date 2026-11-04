#!/usr/bin/env python3
"""
Tape collector. The platform's price-history endpoint returns empty with
coverage.complete=true (silent failure), so we build our own time series
from /exchanges/prices snapshots and the /exchanges/{id}/trades tape.

Read-only. Uses the recon key only. Never places orders.
"""
import os, json, sqlite3, time, urllib.request, urllib.error, datetime, sys, pathlib

BASE = os.environ["SIG_BASE_URL"]
KEY = os.environ["SIG_RECON_KEY"]
TID = "bda92870-621e-47b0-bc3c-3602c5c26f55"
DB = pathlib.Path(__file__).parent / "data" / "tape.db"

SNAP_EVERY = 60
TAPE_BATCH = 40
TAPE_EVERY = 90


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
    CREATE TABLE IF NOT EXISTS quote(
      ts TEXT, exchange_id TEXT, last REAL, bid REAL, ask REAL, spread REAL,
      PRIMARY KEY(ts, exchange_id));
    CREATE TABLE IF NOT EXISTS trade(
      trade_id TEXT PRIMARY KEY, exchange_id TEXT, created_at TEXT,
      price REAL, size REAL, side TEXT);
    CREATE TABLE IF NOT EXISTS lb(
      ts TEXT, rank INTEGER, username TEXT, pnl REAL, trades INTEGER, volume REAL,
      PRIMARY KEY(ts, username));
    CREATE INDEX IF NOT EXISTS i_trade_ex ON trade(exchange_id, created_at);
    CREATE INDEX IF NOT EXISTS i_quote_ex ON quote(exchange_id, ts);
    """)
    con.commit()


def fetch_market_ids() -> list[str]:
    """
    Paginate /markets directly rather than trusting a /tmp cache file.

    This previously read a hardcoded /tmp/markets.json, written once by a
    one-off script and never refreshed. /tmp is not durable storage -- a
    routine OS cleanup removed it, and the collector crashed on startup with
    FileNotFoundError and silently stayed down for about two hours before a
    status check noticed the tape had stopped growing. Paginating the live
    endpoint means a cold start never depends on a file nothing else writes.
    """
    out, cursor = [], None
    for _ in range(20):
        p = f"/markets?limit=100&status=open&tournamentId={TID}"
        if cursor:
            p += f"&cursor={cursor}"
        d = api(p)
        if not d:
            break
        out.extend(m["exchanges"][0]["id"] for m in d.get("data", [])
                   if m.get("exchanges"))
        pg = d.get("pagination", {}) or {}
        nxt = pg.get("nextCursor")
        if not pg.get("hasMore") or not nxt or nxt == cursor:
            break
        cursor = nxt
    return out


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    init(con)
    eids = fetch_market_ids()
    if not eids:
        print("no markets returned; refusing to run with an empty id list",
              file=sys.stderr)
        return
    state = {"cursor": 0, "last_tape": 0.0, "last_lb": 0.0}
    while True:
        try:
            _collect_once(con, eids, state)
        except Exception as e:
            # Keep the loop alive. This process previously had no protection
            # at all around its commits: a single "database is locked" error
            # (this file's writes used SQLite's default rollback-journal mode,
            # which takes an exclusive lock on every commit, and this file is
            # also read concurrently by ad-hoc queries and research/markout.py)
            # propagated out of main() and killed the whole collector. It sat
            # dead for about two hours before a status check noticed the tape
            # had stopped growing. The journal mode is now WAL, which allows
            # concurrent readers during a commit, but the exception guard
            # stays regardless -- a research tool that depends on a live venue
            # feed must survive the feed's own transient failures the same way
            # the trading loop already does. `state` is mutated in place, so a
            # partial failure mid-cycle keeps whatever progress it made rather
            # than losing it to a fresh local variable on the next iteration.
            print(f"[{datetime.datetime.now(datetime.timezone.utc).isoformat()}] "
                  f"cycle failed: {type(e).__name__}: {e}", file=sys.stderr)
        time.sleep(SNAP_EVERY)


def _collect_once(con, eids, state):
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for i in range(0, len(eids), 100):
        d = api(f"/exchanges/prices?ids={','.join(eids[i:i+100])}&tournamentId={TID}")
        if not d:
            continue
        con.executemany(
            "INSERT OR IGNORE INTO quote VALUES(?,?,?,?,?,?)",
            [(now, str(q["exchangeId"]), q.get("latestPrice"), q.get("bestBid"),
              q.get("bestAsk"), q.get("spread")) for q in d["data"]])
        time.sleep(0.5)
    con.commit()

    if time.time() - state["last_tape"] > TAPE_EVERY:
        cursor = state["cursor"]
        batch = eids[cursor:cursor + TAPE_BATCH] or eids[:TAPE_BATCH]
        state["cursor"] = (cursor + TAPE_BATCH) % len(eids)
        for e in batch:
            d = api(f"/exchanges/{e}/trades?tournamentId={TID}&limit=200")
            if d and d.get("data"):
                con.executemany(
                    "INSERT OR IGNORE INTO trade VALUES(?,?,?,?,?,?)",
                    [(str(t["id"]), e, t["createdAt"], t["price"], t["size"],
                      t.get("side")) for t in d["data"]])
            time.sleep(0.5)
        con.commit()
        state["last_tape"] = time.time()

    if time.time() - state["last_lb"] > 900:
        d = api("/tournaments/midterm-elections/leaderboard?period=all&limit=100")
        if d:
            con.executemany(
                "INSERT OR IGNORE INTO lb VALUES(?,?,?,?,?,?)",
                [(now, r["rank"], r["username"], r["pnl"], r["tradesCount"],
                  r["volume"]) for r in d["leaderboard"]])
            con.commit()
        state["last_lb"] = time.time()

    q = con.execute("SELECT COUNT(*) FROM quote").fetchone()[0]
    t = con.execute("SELECT COUNT(*) FROM trade").fetchone()[0]
    print(f"[{now}] quotes={q:,} trades={t:,}", flush=True)


if __name__ == "__main__":
    main()
