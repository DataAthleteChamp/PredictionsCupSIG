#!/usr/bin/env python3
"""
Markout harness.

For every fill, records the mid price at fixed horizons after the fill and
computes markout per share. Negative markout at horizon h means we were
adversely selected: our quoted distance was inside the adverse-selection cost
and we should widen.

This is the feedback loop that empirically sets our spread, per Cartea-Jaimungal-
Penalva (expected per-fill P&L ~= delta - c+/-).

Read-only. Uses the recon key. Never places orders.
"""
import os, json, sqlite3, time, urllib.request, urllib.error, datetime, pathlib

BASE = os.environ["SIG_BASE_URL"]
KEY = os.environ["SIG_RECON_KEY"]
TID = "bda92870-621e-47b0-bc3c-3602c5c26f55"
SLUG = "midterm-elections"
DB = pathlib.Path(__file__).parent / "data" / "markout.db"

HORIZONS_MIN = [1, 5, 30, 240, 1440]
POLL_SECONDS = 60


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
    CREATE TABLE IF NOT EXISTS fill(
      fill_id INTEGER PRIMARY KEY, order_id INTEGER, exchange_id TEXT,
      market_id TEXT, price REAL, quantity REAL, side TEXT, filled_at TEXT,
      mid_at_fill REAL, bucket TEXT);
    CREATE TABLE IF NOT EXISTS markout(
      fill_id INTEGER, horizon_min INTEGER, measured_at TEXT,
      mid REAL, markout_per_share REAL, markout_total REAL,
      PRIMARY KEY(fill_id, horizon_min));
    """)
    con.commit()


def price_bucket(p):
    if p is None:
        return "unknown"
    for lo, hi in [(0, .05), (.05, .15), (.15, .35), (.35, .65), (.65, .85), (.85, .95), (.95, 1.01)]:
        if lo <= p < hi:
            return f"{lo:.2f}-{hi:.2f}"
    return "unknown"


def mids(exchange_ids):
    out = {}
    ids = list(exchange_ids)
    for i in range(0, len(ids), 100):
        d = api(f"/exchanges/prices?ids={','.join(ids[i:i+100])}&tournamentId={TID}")
        if not d:
            continue
        for q in d["data"]:
            b, a = q.get("bestBid"), q.get("bestAsk")
            if b is not None and a is not None:
                out[str(q["exchangeId"])] = (b + a) / 2
        time.sleep(0.4)
    return out


def ingest_fills(con):
    """Pull all fills, insert new ones, stamp the mid at discovery time."""
    new = []
    cursor = None
    while True:
        p = f"/tournaments/{SLUG}/portfolio/fills?limit=200" + (f"&cursor={cursor}" if cursor else "")
        d = api(p)
        if not d:
            break
        for f in d.get("data", []):
            row = con.execute("SELECT 1 FROM fill WHERE fill_id=?", (f["id"],)).fetchone()
            if not row:
                new.append(f)
        pg = d.get("pagination", {})
        if not pg.get("hasMore"):
            break
        cursor = pg.get("nextCursor")
        time.sleep(0.3)
    if new:
        m = mids({f["exchangeId"] for f in new})
        for f in new:
            mid = m.get(str(f["exchangeId"]))
            con.execute(
                "INSERT OR IGNORE INTO fill VALUES(?,?,?,?,?,?,?,?,?,?)",
                (f["id"], f["orderId"], str(f["exchangeId"]), str(f.get("marketId")),
                 f["price"], f["quantity"], f.get("side"), f["filledAt"],
                 mid, price_bucket(f["price"])))
        con.commit()
    return len(new)


def take_markouts(con):
    """For each fill, measure any horizon that is now due and not yet recorded."""
    now = datetime.datetime.now(datetime.timezone.utc)
    due = []
    for fid, ex, px, qty, side, fat in con.execute(
            "SELECT fill_id,exchange_id,price,quantity,side,filled_at FROM fill"):
        t0 = datetime.datetime.fromisoformat(fat.replace("Z", "+00:00"))
        age = (now - t0).total_seconds() / 60
        for h in HORIZONS_MIN:
            if age >= h and not con.execute(
                    "SELECT 1 FROM markout WHERE fill_id=? AND horizon_min=?", (fid, h)).fetchone():
                due.append((fid, ex, px, qty, side, h))
    if not due:
        return 0
    m = mids({d[1] for d in due})
    n = 0
    for fid, ex, px, qty, side, h in due:
        mid = m.get(ex)
        if mid is None:
            continue
        # `mid` is always the YES-space mid, but a 'no' fill's price is in
        # NO space. A NO share is worth (1 - yes_mid), so comparing a NO price
        # against the YES mid mixes frames and inflates the markout by roughly
        # (1 - 2*mid) -- enough to turn a +0.0125 fill into a reported +0.9025.
        value = mid if side == "yes" else (1.0 - mid)
        per = value - px
        con.execute("INSERT OR IGNORE INTO markout VALUES(?,?,?,?,?,?)",
                    (fid, h, now.isoformat(), mid, per, per * qty))
        n += 1
    con.commit()
    return n


def report(con):
    print("\n=== MARKOUT BY HORIZON ===")
    print(f"{'horizon':>9}{'n':>5}{'mean/share':>13}{'median/share':>15}{'total':>12}")
    for h in HORIZONS_MIN:
        r = con.execute(
            "SELECT COUNT(*),AVG(markout_per_share),SUM(markout_total) FROM markout WHERE horizon_min=?",
            (h,)).fetchone()
        if not r[0]:
            continue
        med = con.execute(
            "SELECT markout_per_share FROM markout WHERE horizon_min=? ORDER BY markout_per_share "
            "LIMIT 1 OFFSET (SELECT COUNT(*)/2 FROM markout WHERE horizon_min=?)", (h, h)).fetchone()
        print(f"{str(h)+'m':>9}{r[0]:>5}{r[1]:>13.5f}{(med[0] if med else 0):>15.5f}{r[2]:>12.2f}")
    print("\n=== MARKOUT BY PRICE BUCKET (longest available horizon per fill) ===")
    rows = con.execute("""
        SELECT f.bucket, COUNT(*), AVG(m.markout_per_share), SUM(m.markout_total)
        FROM fill f JOIN markout m ON m.fill_id=f.fill_id
        WHERE m.horizon_min=(SELECT MAX(horizon_min) FROM markout m2 WHERE m2.fill_id=f.fill_id)
        GROUP BY f.bucket ORDER BY f.bucket""").fetchall()
    print(f"{'bucket':>12}{'n':>5}{'mean/share':>13}{'total':>12}")
    for b, n, a, t in rows:
        print(f"{b:>12}{n:>5}{a:>13.5f}{t:>12.2f}")
    print("\nInterpretation: negative mean markout at a horizon => we were adversely")
    print("selected at that distance; widen the quote for that bucket.")


def main():
    DB.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(DB)
    init(con)
    once = os.environ.get("MARKOUT_ONCE") == "1"
    while True:
        n_new = ingest_fills(con)
        n_mo = take_markouts(con)
        ts = datetime.datetime.now(datetime.timezone.utc).isoformat()[:19]
        nf = con.execute("SELECT COUNT(*) FROM fill").fetchone()[0]
        nm = con.execute("SELECT COUNT(*) FROM markout").fetchone()[0]
        print(f"[{ts}] fills={nf} (+{n_new})  markouts={nm} (+{n_mo})", flush=True)
        if once:
            report(con)
            return
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
