"""
Desired-state executor.

The central invariant of this system: **strategies never place orders.** They
declare the book they want to have, and this module computes the minimum set of
cancels and placements that turns the live book into that book.

Why it matters:
  * strategies become pure functions of market state, so they are unit-testable
  * a buggy strategy cannot spam the venue — the diff is bounded by the desired set
  * re-quoting is idempotent: running the same desired state twice is a no-op
"""
from __future__ import annotations

from dataclasses import dataclass

from .api import ApiError, Client, DryRunBlocked
from .risk import PortfolioState, RiskManager


@dataclass(frozen=True)
class DesiredOrder:
    exchange_id: str
    side: str          # "yes" | "no"
    action: str        # "buy" | "sell"
    price: float
    quantity: int
    strategy: str      # budget bucket, e.g. "ladder"

    @property
    def key(self) -> tuple:
        """Orders match when exchange, direction and price coincide."""
        return (str(self.exchange_id), self.side, self.action, round(self.price, 3))


@dataclass(frozen=True)
class LiveOrder:
    order_id: int
    exchange_id: str
    side: str
    action: str
    price: float
    quantity: int

    @property
    def key(self) -> tuple:
        return (str(self.exchange_id), self.side, self.action, round(self.price, 3))

    @staticmethod
    def from_api(d: dict) -> "LiveOrder":
        return LiveOrder(
            order_id=int(d["id"]),
            exchange_id=str(d["exchangeId"]),
            side=d["side"],
            action=d["action"],
            price=float(d["priceLimit"]) if d.get("priceLimit") is not None else 0.0,
            quantity=int(d["quantity"]),
        )


@dataclass
class Plan:
    cancels: list[LiveOrder]
    places: list[DesiredOrder]
    keeps: list[LiveOrder]
    vetoed: list[tuple[DesiredOrder, str]]

    @property
    def is_noop(self) -> bool:
        return not self.cancels and not self.places

    def summary(self) -> str:
        return (f"keep={len(self.keeps)} cancel={len(self.cancels)} "
                f"place={len(self.places)} vetoed={len(self.vetoed)}")


def plan_orders(desired: list[DesiredOrder], live: list[LiveOrder],
                risk: RiskManager, state: PortfolioState,
                managed_order_ids: set[int] | None = None) -> Plan:
    """
    Pure diff. No I/O, fully testable.

    An existing order is KEPT when an identical (exchange, side, action, price)
    order is desired with the same quantity. A quantity change means cancel and
    replace, because the venue has no amend operation.

    Risk is evaluated CUMULATIVELY: each approved order increments a running
    tally of per-market, per-strategy and total exposure, so a plan of many
    individually-valid orders cannot collectively breach a budget. Evaluating
    each order against the same starting state would let 229 small orders blow
    through a cap that none of them breaches alone.

    `managed_order_ids` scopes what the bot is allowed to cancel. Orders placed
    outside the bot (manual experiments, another process) are left strictly
    alone. Pass None to manage everything — only safe when the bot is the sole
    writer on the account.
    """
    live_by_key: dict[tuple, list[LiveOrder]] = {}
    for lo in live:
        live_by_key.setdefault(lo.key, []).append(lo)

    keeps: list[LiveOrder] = []
    places: list[DesiredOrder] = []
    vetoed: list[tuple[DesiredOrder, str]] = []
    matched_ids: set[int] = set()

    # Running tally so cumulative exposure is enforced, not just per-order.
    running = PortfolioState(
        balance=state.balance, equity=state.equity, cost_basis=state.cost_basis,
        peak_equity=state.peak_equity, positions=dict(state.positions),
        deployed_by_strategy=dict(state.deployed_by_strategy),
    )

    def manageable(o: LiveOrder) -> bool:
        return managed_order_ids is None or o.order_id in managed_order_ids

    for d in desired:
        veto = risk.check(running, exchange_id=d.exchange_id, action=d.action,
                          price=d.price, quantity=d.quantity, strategy=d.strategy)
        if veto is not None:
            vetoed.append((d, veto.reason))
            continue
        candidates = [lo for lo in live_by_key.get(d.key, [])
                      if lo.order_id not in matched_ids and manageable(lo)]
        exact = next((lo for lo in candidates if lo.quantity == d.quantity), None)
        if exact is not None:
            matched_ids.add(exact.order_id)
            keeps.append(exact)
        else:
            places.append(d)
        # Count it either way: a kept order is live exposure too.
        notional = d.price * d.quantity
        running.cost_basis += notional
        running.positions[d.exchange_id] = (
            running.positions.get(d.exchange_id, 0.0) + d.quantity)
        running.deployed_by_strategy[d.strategy] = (
            running.deployed_by_strategy.get(d.strategy, 0.0) + notional)

    cancels = [lo for lo in live
               if lo.order_id not in matched_ids and manageable(lo)]
    return Plan(cancels=cancels, places=places, keeps=keeps, vetoed=vetoed)


class Executor:
    """Applies a Plan. Respects the dry-run latches via the client."""

    BATCH_SIZE = 50

    def __init__(self, client: Client, risk: RiskManager):
        self.client = client
        self.risk = risk

    def apply(self, plan: Plan, *, dry_run: bool | None = None,
              use_batch: bool = True) -> dict:
        dry = self.client.s.dry_run if dry_run is None else dry_run
        # placed_order_ids is how ownership is established. It must contain ONLY
        # ids the venue returned for orders WE submitted. Never infer ownership
        # from account-level open orders - that would adopt (and later cancel)
        # orders placed manually or by another process.
        result = {"cancelled": 0, "placed": 0, "errors": [], "dry_run": dry,
                  "requests": 0, "placed_order_ids": []}
        if dry:
            result["would_cancel"] = [o.order_id for o in plan.cancels]
            result["would_place"] = [
                {"exchangeId": d.exchange_id, "action": d.action, "side": d.side,
                 "price": d.price, "quantity": d.quantity, "strategy": d.strategy}
                for d in plan.places]
            return result

        # Cancel first so capacity and queue slots are freed before re-posting.
        for lo in plan.cancels:
            try:
                self.client.cancel_order(lo.order_id)
                result["cancelled"] += 1
                result["requests"] += 1
            except (ApiError, DryRunBlocked) as e:
                # 409 generally means it already filled or closed - not an error.
                if isinstance(e, ApiError) and e.status == 409:
                    result["cancelled"] += 1
                else:
                    result["errors"].append(f"cancel {lo.order_id}: {e}")

        if use_batch and len(plan.places) > 1:
            result.update(self._place_batched(plan.places, result))
        else:
            for d in plan.places:
                try:
                    resp = self.client.place_order(d.exchange_id, d.side, d.action,
                                                   d.quantity, d.price)
                    result["placed"] += 1
                    result["requests"] += 1
                    oid = (resp or {}).get("orderId")
                    if oid is not None:
                        result["placed_order_ids"].append(int(oid))
                except (ApiError, DryRunBlocked) as e:
                    result["errors"].append(f"place {d.exchange_id}@{d.price}: {e}")
        return result

    def _place_batched(self, places: list[DesiredOrder], result: dict) -> dict:
        """
        Batch placement. Cuts a 229-order cycle from ~238 requests to ~14, which
        is the difference between quoting on live prices and quoting on prices
        that moved several minutes ago.
        """
        for i in range(0, len(places), self.BATCH_SIZE):
            chunk = places[i:i + self.BATCH_SIZE]
            payload = [{"exchangeId": d.exchange_id, "side": d.side,
                        "action": d.action, "quantity": d.quantity,
                        "price": d.price} for d in chunk]
            try:
                resp = self.client.place_batch(payload)
                result["requests"] += 1
                rows = resp.get("results", []) if isinstance(resp, dict) else []
                if rows:
                    for r in rows:
                        data = r.get("data") or {}
                        if r.get("ok"):
                            result["placed"] += 1
                            oid = data.get("orderId")
                            if oid is not None:
                                result["placed_order_ids"].append(int(oid))
                        else:
                            result["errors"].append(
                                f"batch item {r.get('index')}: "
                                f"{data.get('code', r.get('status'))}")
                else:
                    # Unrecognised response shape: do NOT assume success. This
                    # feeds ownership tracking, so failing open here would both
                    # overstate placements and lose order ids.
                    result["errors"].append(
                        f"batch {i // self.BATCH_SIZE}: unrecognised response shape")
            except (ApiError, DryRunBlocked) as e:
                result["errors"].append(f"batch {i // self.BATCH_SIZE}: {e}")
        return result
