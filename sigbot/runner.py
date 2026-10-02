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
from .journal import OrderJournal, recover
from .portfolio import Leg, RacePosition, portfolio_floor
from .risk import PortfolioState, RiskManager
from .strategies.base import MarketView, Quote
from .strategies.ladder import LadderStrategy
from .strategies.pair import PairStrategy
from .strategies.relvalue import RelValueStrategy
from .strategies.sleeve import SleeveStrategy

STATE_PATH = os.environ.get("SIGBOT_STATE", "research/data/bot_state.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def load_state() -> dict:
    try:
        return json.load(open(STATE_PATH))
    except Exception:
        return {"managed_order_ids": [], "peak_equity": 100_000.0}


def save_state(st: dict) -> None:
    """
    Atomic write. Truncating the real file and then writing leaves a corrupt or
    empty file if the process dies between the two, and load_state would then
    silently reset peak_equity - disarming the drawdown kill switch.
    """
    d = os.path.dirname(STATE_PATH)
    if d:
        os.makedirs(d, exist_ok=True)
    tmp = STATE_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(st, f)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, STATE_PATH)


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
        outcomes = tuple(sorted(universe[race]))
        # A race whose outcome space we cannot fully enumerate is NOT safe to
        # treat as hedgeable: a missing outcome is one that cannot lose, so any
        # floor computed over a partial set is optimistic.
        rp = races.setdefault(race, RacePosition(race, outcomes, [],
                                                 complete=len(outcomes) >= 2))
        rp.legs.append(Leg(mt.group(1), float(p["quantity"]), float(p["avgCost"])))
    return races, party_exchange


def cycle(client: Client, risk: RiskManager, state: dict, *,
          journal: OrderJournal | None = None,
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
    for strat in (PairStrategy(), LadderStrategy(), RelValueStrategy(),
                  SleeveStrategy()):
        got = (strat.desired(view, races, party_exchange)
               if isinstance(strat, PairStrategy) else strat.desired(view))
        counts[type(strat).__name__] = len(got)
        desired.extend(got)

    live = [LiveOrder.from_api(o) for o in client.open_orders()]
    live_ids = {o.order_id for o in live}
    # Ownership comes from the journal, never from the account. An order we did
    # not record is someone else's and must not be cancelled.
    managed = (journal.managed_order_ids() if journal
               else set(state.get("managed_order_ids", [])))
    if journal:
        journal.record_closed(managed - live_ids)   # filled or already cancelled
        managed &= live_ids
    # Truncate to the per-cycle order budget, but STICKILY: a desire that
    # already has one of our resting orders is kept first. Without this the
    # truncated set reshuffles every cycle and the bot cancels and re-places
    # perfectly good orders simply because a different market entered the top N.
    priority = {"ladder": 3, "relvalue": 2, "sleeve": 1}
    have = {(str(o.exchange_id), o.side, o.action) for o in live
            if o.order_id in managed}
    desired.sort(key=lambda o: (
        0 if (str(o.exchange_id), o.side, o.action) in have else 1,
        priority.get(o.strategy, 0),
    ))
    if len(desired) > s.max_orders_per_cycle:
        desired = desired[:s.max_orders_per_cycle]

    plan = plan_orders(desired, live, risk, pstate, managed_order_ids=managed)
    result = Executor(client, risk, journal=journal).apply(plan)

    if not result.get("dry_run") and not journal:
        # Fallback only when no journal is configured.
        newly = {int(i) for i in result.get("placed_order_ids", [])}
        state["managed_order_ids"] = sorted((managed & live_ids) | newly)
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
        if journal:
            print(f"  journal: {journal.stats()} managed={len(managed)}")
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
    journal = OrderJournal()
    print(f"sigbot starting | trading_enabled={s.trading_enabled} "
          f"(DRY_RUN and LIVE_TRADING latches) | interval={args.interval}s")

    # Resolve anything a previous process left pending before trading again.
    rec = recover(journal, client, dry_run=not s.trading_enabled)
    if rec["pending"]:
        print(f"  recovery: {rec}")

    while True:
        try:
            cycle(client, risk, state, journal=journal,
                  use_polymarket=not args.no_polymarket)
        except ApiError as e:
            print(f"[{_now()}] api error: {e}")
        except Exception as e:                      # keep the loop alive
            print(f"[{_now()}] cycle failed: {type(e).__name__}: {e}")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
