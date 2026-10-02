"""
Main loop.

One cycle:

    read state  ->  build fair value  ->  run strategies  ->  risk veto
                ->  diff against live book  ->  execute  ->  log

Defaults to dry run. Live orders require DRY_RUN=false AND LIVE_TRADING=true,
and the bot only ever cancels orders it placed itself.

    python -m sigbot.runner --once
    python -m sigbot.runner --interval 300
"""
from __future__ import annotations

import argparse
import json
import os
import re
import time
from collections import defaultdict
from datetime import datetime, timezone

from .api import ApiError, Client
from .config import Settings
from .executor import Executor, LiveOrder, plan_orders
from .fair import Crosswalk, FairValueEngine, clob_midpoints, sig_key
from .portfolio import Leg, RacePosition, portfolio_floor
from .risk import PortfolioState, RiskManager
from .strategies.base import MarketView, Quote
from .strategies.ladder import LadderStrategy
from .strategies.pair import PairStrategy
from .strategies.relvalue import RelValueStrategy

STATE_PATH = os.environ.get("SIGBOT_STATE", "research/data/bot_state.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"managed_order_ids": [], "peak_equity": 100_000.0}


def save_state(st: dict) -> None:
    os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
    with open(STATE_PATH, "w") as f:
        json.dump(st, f)


def fetch_markets(client: Client, max_pages: int = 20) -> list[dict]:
    """Paginate markets with a hard page cap and a stuck-cursor guard, so a
    server returning a constant cursor cannot wedge the loop forever."""
    out, cursor = [], None
    for _ in range(max_pages):
        p = (f"/markets?limit=100&status=open"
             f"&tournamentId={client.s.tournament_id}")
        if cursor:
            p += f"&cursor={cursor}"
        d = client.get(p)
        out.extend(d.get("data", []))
        pg = d.get("pagination", {}) or {}
        nxt = pg.get("nextCursor")
        if not pg.get("hasMore") or not nxt or nxt == cursor:
            return out
        cursor = nxt
    return out


def build_races(markets: list[dict], positions: list[dict]) -> tuple[dict, dict]:
    """Group our holdings by race and record the full outcome space."""
    title = {m["exchanges"][0]["id"]: m["title"] for m in markets if m.get("exchanges")}
    universe: dict[str, set] = defaultdict(set)
    party_exchange: dict[tuple[str, str], str] = {}
    for m in markets:
        mt = re.match(r"Will the (\w+) Party win the (.+)\?$", m.get("title", ""))
        if mt and m.get("exchanges"):
            universe[mt.group(2)].add(mt.group(1))
            party_exchange[(mt.group(2), mt.group(1))] = m["exchanges"][0]["id"]
    races: dict[str, RacePosition] = {}
    for p in positions:
        mt = re.match(r"Will the (\w+) Party win the (.+)\?$",
                      title.get(str(p["exchangeId"]), ""))
        if not mt:
            continue
        race = mt.group(2)
        rp = races.setdefault(race, RacePosition(race, tuple(sorted(universe[race])), []))
        rp.legs.append(Leg(mt.group(1), float(p["quantity"]), float(p["avgCost"])))
    return races, party_exchange


def cycle(client: Client, risk: RiskManager, state: dict, *,
          use_polymarket: bool = True, verbose: bool = True) -> dict:
    s = client.s
    markets = fetch_markets(client)
    exchange_ids = [m["exchanges"][0]["id"] for m in markets if m.get("exchanges")]

    acct = client.account()
    pos_raw = client.positions()
    positions = pos_raw.get("positions", [])
    summary = pos_raw.get("summary", {})
    equity = float(acct["balance"]) + float(summary.get("totalMarketValue", 0.0))
    peak = max(float(state.get("peak_equity", 100_000.0)), equity)
    state["peak_equity"] = peak

    quotes_raw = client.prices(exchange_ids)
    quotes = {ex: Quote(ex, q.get("bestBid"), q.get("bestAsk"))
              for ex, q in quotes_raw.items()}

    pstate = PortfolioState(
        balance=float(acct["balance"]), equity=equity,
        cost_basis=float(summary.get("totalCostBasis", 0.0)), peak_equity=peak,
        positions={str(p["exchangeId"]): float(p["quantity"]) for p in positions},
    )
    risk.update(pstate)

    # --- fair value -------------------------------------------------------
    fair: dict[str, float] = {}
    if use_polymarket:
        try:
            xw = (Crosswalk.load("research/data/crosswalk.json")
                  if os.path.exists("research/data/crosswalk.json") else None)
            if xw is None:
                from .fair import build_crosswalk
                xw = build_crosswalk(markets)
                os.makedirs("research/data", exist_ok=True)
                xw.save("research/data/crosswalk.json")
            mids = clob_midpoints(list(xw.token_by_exchange.values()))
            fair = FairValueEngine(xw).combine(quotes_raw, mids)
        except Exception as e:          # external feed must never stop the loop
            if verbose:
                print(f"  [warn] fair value unavailable: {e}")

    view = MarketView(quotes=quotes, fair=fair, positions=pstate.positions,
                      equity=equity)
    races, party_exchange = build_races(markets, positions)
    floor = portfolio_floor(list(races.values())) if races else {}

    # --- strategies -------------------------------------------------------
    desired = []
    counts = {}
    for strat in (PairStrategy(), LadderStrategy(), RelValueStrategy()):
        got = (strat.desired(view, races, party_exchange)
               if isinstance(strat, PairStrategy) else strat.desired(view))
        counts[type(strat).__name__] = len(got)
        desired.extend(got)

    live = [LiveOrder.from_api(o) for o in client.open_orders()]
    managed = set(state.get("managed_order_ids", []))
    plan = plan_orders(desired, live, risk, pstate, managed_order_ids=managed)
    result = Executor(client, risk).apply(plan)

    # Ownership comes ONLY from ids the executor actually placed. Reading
    # account-level open orders here would adopt manually-placed orders and
    # later cancel them, which must never happen.
    if not result.get("dry_run"):
        newly = {int(i) for i in result.get("placed_order_ids", [])}
        still_open = {int(o["id"]) for o in live}
        # Drop ids that are no longer open (filled or cancelled) to bound growth.
        state["managed_order_ids"] = sorted((managed & still_open) | newly)
    save_state(state)

    if verbose:
        print(f"[{_now()}] equity={equity:,.2f} bal={pstate.balance:,.2f} "
              f"pos={len(positions)} dd={pstate.drawdown:.2%} kill={risk.tripped}")
        if floor:
            print(f"  floor={floor['guaranteed_floor']:+,.2f} "
                  f"risk_free={floor['n_risk_free']}/{floor['n_races']} "
                  f"cost={floor['cost']:,.2f}")
        print(f"  fair values: {len(fair)} | strategies: {counts}")
        print(f"  plan: {plan.summary()} | applied: placed={result['placed']} "
              f"cancelled={result['cancelled']} dry={result['dry_run']}")
        for err in result.get("errors", [])[:3]:
            print(f"  [err] {err}")
    return {"equity": equity, "plan": plan, "result": result, "floor": floor}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--no-polymarket", action="store_true")
    args = ap.parse_args()

    s = Settings.from_env()
    client = Client(s)
    risk = RiskManager(s)
    state = load_state()
    print(f"sigbot starting | trading_enabled={s.trading_enabled} "
          f"(DRY_RUN and LIVE_TRADING latches) | interval={args.interval}s")

    while True:
        try:
            cycle(client, risk, state, use_polymarket=not args.no_polymarket)
        except ApiError as e:
            print(f"[{_now()}] api error: {e}")
        except Exception as e:                      # keep the loop alive
            print(f"[{_now()}] cycle failed: {type(e).__name__}: {e}")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
