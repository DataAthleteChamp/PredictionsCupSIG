#!/usr/bin/env python3
"""
End-to-end dry run against LIVE market data.

Reads real quotes and positions, runs both strategies, diffs against our live
resting orders through the risk layer, and prints the plan WITHOUT placing
anything. DRY_RUN defaults to true, so this is safe.

    python -m sigbot.dryrun
"""
from __future__ import annotations

import os

from .api import Client
from .config import Settings
from .executor import Executor, LiveOrder, plan_orders
from .risk import PortfolioState, RiskManager, collateral
from .strategies.base import MarketView, Quote
from .strategies.ladder import LadderStrategy
from .strategies.relvalue import RelValueStrategy


def build_view(client: Client, exchange_ids: list[str],
               fair: dict[str, float] | None = None) -> tuple[MarketView, PortfolioState]:
    acct = client.account()
    pos_raw = client.positions()
    positions = {str(p["exchangeId"]): float(p["quantity"])
                 for p in pos_raw.get("positions", [])}
    summary = pos_raw.get("summary", {})
    equity = float(acct["balance"]) + float(summary.get("totalMarketValue", 0.0))

    quotes_raw = client.prices(exchange_ids)
    quotes = {ex: Quote(ex, q.get("bestBid"), q.get("bestAsk"))
              for ex, q in quotes_raw.items()}

    state = PortfolioState(
        balance=float(acct["balance"]),
        equity=equity,
        cost_basis=float(summary.get("totalCostBasis", 0.0)),
        peak_equity=max(equity, 100_000.0),
        positions=positions,
    )
    return MarketView(quotes=quotes, fair=fair or {}, positions=positions,
                      equity=equity), state


def main() -> None:
    s = Settings.from_env()
    client = Client(s)
    risk = RiskManager(s)

    markets = client.get("/markets?limit=100&status=open"
                         f"&tournamentId={s.tournament_id}")
    exchange_ids = [m["exchanges"][0]["id"] for m in markets.get("data", [])
                    if m.get("exchanges")]
    print(f"discovered {len(exchange_ids)} exchanges (first page)")

    view, state = build_view(client, exchange_ids)
    risk.update(state)
    print(f"equity={state.equity:,.2f} balance={state.balance:,.2f} "
          f"cost={state.cost_basis:,.2f} positions={len(state.positions)} "
          f"drawdown={state.drawdown:.2%} kill_switch={risk.tripped}")

    live = [LiveOrder.from_api(o) for o in client.open_orders()]
    print(f"live resting orders: {len(live)}")

    desired = []
    for strat in (LadderStrategy(), RelValueStrategy()):
        got = strat.desired(view)
        print(f"  {strat.name:9} wants {len(got)} orders")
        desired.extend(got)

    # The bot manages only orders it placed. Our running manual experiments
    # must be left strictly alone, so nothing is manageable in a dry run yet.
    managed: set[int] = set()
    plan = plan_orders(desired, live, risk, state, managed_order_ids=managed)
    print(f"\nPLAN: {plan.summary()}")

    if plan.vetoed:
        print("\nvetoed (first 5):")
        for d, reason in plan.vetoed[:5]:
            print(f"  {d.exchange_id} {d.action}@{d.price} -> {reason}")

    if plan.places:
        print("\nwould place (first 10):")
        for d in plan.places[:10]:
            print(f"  {d.strategy:9} {d.exchange_id:>5} {d.action:>4} "
                  f"{d.quantity:>5} @ {d.price:.3f}  "
                  f"notional={collateral(d.action, d.price, d.quantity):7.2f}")
        # price*quantity understates a tail SELL by up to 49x: selling at 0.02
        # ties up 0.98/share, not 0.02. Reporting the wrong number here is how
        # an over-deployed book looks safe.
        total = sum(collateral(d.action, d.price, d.quantity) for d in plan.places)
        print(f"  total collateral if ALL filled: {total:,.2f} "
              f"({total/state.equity*100:.2f}% of equity)")

    out = Executor(client, risk).apply(plan, dry_run=True)
    print(f"\nexecutor (dry): would_cancel={len(out.get('would_cancel', []))} "
          f"would_place={len(out.get('would_place', []))}")
    print(f"api requests used: {client.request_count}")
    print(f"\ntrading_enabled={s.trading_enabled}  (needs DRY_RUN=false AND LIVE_TRADING=true)")


if __name__ == "__main__":
    main()
