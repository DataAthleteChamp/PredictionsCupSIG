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
import contextlib
import json
import os
import re
import signal
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
from .strategies.base import Lot, MarketView, Quote
from .strategies.exit import ExitStrategy
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


def _parse_ts(value: str) -> datetime | None:
    """Tolerate the venue's 7-digit fractional seconds and trailing Z."""
    if not value:
        return None
    s = str(value).replace("Z", "+00:00")
    m = re.match(r"^(.*\.\d{6})\d*(.*)$", s)
    if m:
        s = m.group(1) + m.group(2)
    try:
        d = datetime.fromisoformat(s)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def build_lots(positions: list[dict], now: datetime | None = None) -> dict[str, Lot]:
    """
    Normalise raw positions into YES-space lots with an age.

    Two conversions matter and both have bitten us before:

    * `avgCost` is quoted in the frame of the shares actually held. A short is
      held as NO shares, so its avgCost of 0.72 means a YES entry of 0.28.
      Feeding the NO-space number into a YES-space exit price would quote the
      wrong side of the book by (1 - 2p).
    * Age is quantity-weighted across lots, so one old scrap does not make a
      mostly-fresh position look stale, nor a fresh top-up refresh an old one.
    """
    now = now or datetime.now(timezone.utc)
    out: dict[str, Lot] = {}
    for p in positions:
        qty = float(p.get("quantity") or 0.0)
        if qty == 0:
            continue
        ex = str(p["exchangeId"])
        avg = float(p.get("avgCost") or 0.0)
        if qty < 0:                       # held as NO shares -> convert to YES
            avg = 1.0 - avg

        num = den = 0.0
        for lot in p.get("lots") or []:
            ts = _parse_ts(lot.get("openedAt"))
            if ts is None:
                continue
            w = abs(float(lot.get("quantity") or 0.0))
            num += w * max(0.0, (now - ts).total_seconds() / 60.0)
            den += w
        age = num / den if den > 0 else 0.0
        out[ex] = Lot(exchange_id=ex, quantity=qty, avg_cost=avg, age_minutes=age)
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
        # A short's avgCost is quoted in NO space, so the YES entry price is
        # its complement. Feeding 0.72 where the YES entry is 0.28 corrupts
        # every settlement floor computed from these legs.
        qty = float(p["quantity"])
        avg = float(p["avgCost"])
        rp.legs.append(Leg(mt.group(1), qty, avg if qty >= 0 else 1.0 - avg))
    return races, party_exchange


# Lower sorts FIRST: these are ranks under an ascending sort, not scores.
#
# This previously read {"ladder": 3, "relvalue": 2, "sleeve": 1}, which looks
# like a desirability score but ordered them exit, sleeve, relvalue, ladder --
# putting the highest-EV strategy LAST. With ~277 ladder desires and 60
# relvalue against a 150-order cap, every relvalue order survived and ladder
# absorbed the entire truncation, despite ladder measuring +0.0163 per
# order-hour at its optimal depth against relvalue's unmeasured edge.
#
# Exit leads because it only reduces exposure and the edge it harvests is
# perishable. Sleeve is last because it is the speculative layer.
STRATEGY_PRIORITY = {"exit": 0, "pair": 1, "ladder": 2, "relvalue": 3,
                     "sleeve": 4}


def _truncate_by_priority(desired, live, managed, cap):
    """
    Cut the desired set to the per-cycle order budget.

    STICKY: a desire that already has one of our resting orders sorts first, so
    the kept set does not reshuffle every cycle and cancel perfectly good
    orders merely because a different market entered the top N.
    """
    have = {(str(o.exchange_id), o.side, o.action) for o in live
            if o.order_id in managed}
    ordered = sorted(desired, key=lambda o: (
        0 if (str(o.exchange_id), o.side, o.action) in have else 1,
        STRATEGY_PRIORITY.get(o.strategy, len(STRATEGY_PRIORITY)),
    ))
    return ordered[:cap] if len(ordered) > cap else ordered



# Exponential decay per cycle. At a 300s cycle, 0.97 gives a half-life of about
# 1.9 hours, long enough to be stable across quiet patches but short enough to
# follow the market as attention rotates between races.
ACTIVITY_DECAY = 0.97


def update_activity(state: dict, quotes_raw: dict) -> dict[str, float]:
    """
    Maintain a per-market trading-activity score across cycles.

    A market's `latestPrice` changing between two cycles means it traded. That
    signal is free -- /exchanges/prices is already fetched for all 237 markets
    every cycle -- and against real trade counts it scores Spearman rho = +0.92.

    This matters because the capital cap binds: we can only rest ~84 orders, so
    the choice of WHICH markets sets the fill rate. Ordering by exchange id put
    us in 29 markets carrying 12% of the venue's flow, with orders in 1 of the
    20 busiest. Ranking by this score captures 28.7% of flow against 10.3%,
    where a perfect oracle would get 33.9%.
    """
    scores = {k: float(v) for k, v in state.get("activity", {}).items()}
    last = state.get("last_price", {})
    now_last = {}
    for ex, q in quotes_raw.items():
        lp = q.get("latestPrice")
        if lp is None:
            continue
        now_last[ex] = lp
        s = scores.get(ex, 0.0) * ACTIVITY_DECAY
        if ex in last and last[ex] != lp:
            s += 1.0
        scores[ex] = s
    state["activity"] = scores
    state["last_price"] = now_last
    return scores



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
    activity = update_activity(state, quotes_raw)

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
                      equity=equity, lots=build_lots(positions),
                      activity=activity)
    races, party_exchange = build_races(markets, positions)
    floor = portfolio_floor(list(races.values())) if races else {}

    # --- strategies -------------------------------------------------------
    desired = []
    counts = {}
    # Exit runs first: the measured edge decays to negative by 240 min, so
    # harvesting existing inventory takes precedence over adding more.
    for strat in (ExitStrategy(), PairStrategy(), LadderStrategy(),
                  RelValueStrategy(), SleeveStrategy()):
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
    desired = _truncate_by_priority(desired, live, managed,
                                    s.max_orders_per_cycle)

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


class CycleTimeout(RuntimeError):
    """A cycle exceeded its wall-clock budget and was abandoned."""


@contextlib.contextmanager
def cycle_deadline(seconds: float):
    """
    Hard wall-clock bound on a cycle.

    Per-request timeouts are not sufficient. A socket timeout only limits the
    gap BETWEEN bytes, so a server trickling data keeps a connection alive
    indefinitely; one such read stalled the live bot for 2h10m with no trading
    and no error. Retries do not help either -- they bound each attempt, not
    the total.

    SIGALRM interrupts the blocking syscall itself, which is the only thing
    that reliably breaks a wedged read in a single-threaded loop. Quotes older
    than a couple of minutes are worthless to us anyway: abandoning a slow
    cycle and starting fresh is strictly better than finishing a stale one.
    """
    if not hasattr(signal, "SIGALRM"):             # pragma: no cover
        yield
        return

    def _fire(signum, frame):
        raise CycleTimeout(f"cycle exceeded {seconds:.0f}s budget")

    old = signal.signal(signal.SIGALRM, _fire)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, old)



def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=300)
    ap.add_argument("--no-polymarket", action="store_true")
    ap.add_argument("--adopt-orphans", action="store_true",
                    help="Take ownership of open orders missing from the "
                         "journal so the executor can reprice them. Only safe "
                         "on a single-tenant account.")
    args = ap.parse_args()

    s = Settings.from_env()
    client = Client(s)
    risk = RiskManager(s)
    state = load_state()
    journal = OrderJournal()
    print(f"sigbot starting | trading_enabled={s.trading_enabled} "
          f"(DRY_RUN and LIVE_TRADING latches) | interval={args.interval}s")
    print(f"  {s.risk_banner()}")

    # Resolve anything a previous process left pending before trading again.
    rec = recover(journal, client, dry_run=not s.trading_enabled)
    if rec["pending"]:
        print(f"  recovery: {rec}")

    if args.adopt_orphans:
        n = journal.adopt(client.open_orders())
        print(f"  adopted {n} orphaned order(s) into the journal")

    consecutive_failures = 0
    while True:
        started = time.monotonic()
        try:
            with cycle_deadline(args.interval * 1.5):
                cycle(client, risk, state, journal=journal,
                      use_polymarket=not args.no_polymarket)
            consecutive_failures = 0
        except ApiError as e:
            consecutive_failures += 1
            print(f"[{_now()}] api error: {e}")
        except Exception as e:                      # keep the loop alive
            consecutive_failures += 1
            print(f"[{_now()}] cycle failed after "
                  f"{time.monotonic() - started:.0f}s: {type(e).__name__}: {e}")
        if consecutive_failures and consecutive_failures % 5 == 0:
            # A detached bot that fails silently looks identical to one that is
            # working. Make sustained failure loud instead of invisible.
            print(f"[{_now()}] WARNING: {consecutive_failures} consecutive "
                  f"failed cycles -- not trading")
        if args.once:
            return
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
