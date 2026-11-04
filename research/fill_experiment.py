#!/usr/bin/env python3
"""
Near-touch fill experiment tracker.

Measures fill probability as a function of distance from the touch:
  improve = bestBid + 1 tick (front of a new price level)
  join    = bestBid          (behind the existing queue)
  back3   = bestBid - 3 ticks

Compares against the deep ladder (20 and 40 ticks from mid) from /tmp/fillexp.json.

Read-only reporting. Uses the recon key. Places no orders.
"""
import os, json, urllib.request, urllib.error, time, datetime, sys
from collections import defaultdict
from scipy import stats

BASE = os.environ["SIG_BASE_URL"]
KEY = os.environ["SIG_RECON_KEY"]


def api(path, tries=4):
    for a in range(tries):
        try:
            req = urllib.request.Request(BASE + path, headers={"Authorization": "Bearer " + KEY})
            return json.load(urllib.request.urlopen(req, timeout=40))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                time.sleep(3 * (a + 1))
                continue
            return None
        except Exception:
            time.sleep(1.2 * (a + 1))
    return None


def poisson_ci(k, exposure_hours):
    if exposure_hours <= 0:
        return (0.0, 0.0)
    lo = 0.0 if k == 0 else stats.chi2.ppf(0.025, 2 * k) / 2 / exposure_hours
    hi = stats.chi2.ppf(0.975, 2 * (k + 1)) / 2 / exposure_hours
    return (lo, hi)


def load(path, labeller):
    try:
        d = json.load(open(path))
    except Exception:
        return []
    out = []
    for o in d["orders"]:
        if not o.get("ok"):
            continue
        out.append({"orderId": o["orderId"], "label": labeller(o), "qty": o["qty"],
                    "price": o["price"], "exchangeId": o["exchangeId"],
                    "placedAt": o["placedAt"]})
    return out


def main():
    now = datetime.datetime.now(datetime.timezone.utc)
    orders = load("/tmp/neartouch.json", lambda o: o["label"])
    orders += load("/tmp/fillexp.json", lambda o: f"deep{int(o['offset']/0.005)}tk")
    if not orders:
        print("no experiment orders found")
        return
    stat = {}
    for o in orders:
        r = api(f"/orders/{o['orderId']}")
        if r is None:
            continue
        rem = r.get("quantity")
        filled = (r.get("open") is False) or (rem is not None and rem < o["qty"])
        stat[o["orderId"]] = (o, filled, r)
        time.sleep(0.35)

    agg = defaultdict(lambda: {"n": 0, "fills": 0, "hours": 0.0})
    for oid, (o, filled, r) in stat.items():
        t0 = datetime.datetime.fromisoformat(o["placedAt"])
        hrs = (now - t0).total_seconds() / 3600
        a = agg[o["label"]]
        a["n"] += 1
        a["fills"] += 1 if filled else 0
        a["hours"] += hrs

    print(f"=== FILL RATE BY DISTANCE FROM TOUCH  ({now.isoformat()[:19]}Z) ===\n")
    print(f"{'placement':>12}{'n':>4}{'fills':>7}{'order-hours':>13}{'fills/order-hr':>16}{'95% CI':>22}")
    order_of = ["improve", "join", "back3", "deep20tk", "deep40tk"]
    for lab in order_of + [k for k in agg if k not in order_of]:
        if lab not in agg:
            continue
        a = agg[lab]
        rate = a["fills"] / a["hours"] if a["hours"] else 0
        lo, hi = poisson_ci(a["fills"], a["hours"])
        print(f"{lab:>12}{a['n']:>4}{a['fills']:>7}{a['hours']:>13.1f}{rate:>16.4f}"
              f"{f'[{lo:.4f}, {hi:.4f}]':>22}")
    print("\nimprove = bestBid+1tick (front of new level) | join = bestBid (behind queue)")
    print("back3 = bestBid-3ticks | deepNtk = N ticks below mid (original ladder)")
    print("\nLokin & Yu (2026): ~85% of fills occur within 1 tick of the best quote.")
    print("If 'improve' >> 'deep', that is confirmed and S3 must quote near the touch.")


if __name__ == "__main__":
    main()
