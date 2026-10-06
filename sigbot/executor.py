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

import hashlib
from dataclasses import dataclass

from .api import ApiError, Client, DryRunBlocked
from .config import TICK
from .journal import OrderJournal
from .risk import PortfolioState, RiskManager, collateral


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
                managed_order_ids: set[int] | None = None,
                price_tolerance_ticks: int = 1,
                qty_tolerance: float = 0.15,
                force_cancel_ids: set[int] | None = None) -> Plan:
    """
    Pure diff. No I/O, fully testable.

    An existing order is KEPT when a desired order matches it closely enough,
    UNLESS it is in `force_cancel_ids`.

    That override exists because hysteresis is dangerous in one specific case.
    A resting buy is passive only relative to where the mid WAS; if the mid
    then falls through it, the order is now aggressive and will be filled by
    someone selling into us. Hysteresis, whose whole purpose is to leave orders
    alone, protects exactly the orders that have become toxic.

    Measured over 1,996 fills: 14.7% landed on orders the mid had crossed, and
    they earned -0.00276/share against +0.00368 for passive fills -- a drag of
    -106 on a book that made +623. The caller identifies them from the live
    mid and forces the cancel.

    Matching uses HYSTERESIS rather than exact equality. The ladder recomputes
    its targets from a moving mid, so an exact match would cancel and replace
    nearly every order each cycle for a sub-tick drift - burning rate-limit
    budget and, worse, surrendering queue position (where price-time priority
    is the only thing that gets a passive order filled).

    `price_tolerance_ticks` and `qty_tolerance` define "close enough".

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
                          price=d.price, quantity=d.quantity, strategy=d.strategy,
                          side=d.side)
        if veto is not None:
            vetoed.append((d, veto.reason))
            continue
        tol = price_tolerance_ticks * TICK + 1e-9
        candidates = [
            lo for lo in live
            if lo.order_id not in matched_ids and manageable(lo)
            and str(lo.exchange_id) == str(d.exchange_id)
            and lo.side == d.side and lo.action == d.action
            and abs(lo.price - d.price) <= tol
            and abs(lo.quantity - d.quantity) <= max(1.0, qty_tolerance * d.quantity)
        ]
        # Prefer the closest price, so repeated desires do not all match one order.
        if force_cancel_ids:
            candidates = [lo for lo in candidates
                          if lo.order_id not in force_cancel_ids]
        best = min(candidates, key=lambda lo: abs(lo.price - d.price), default=None)
        if best is not None:
            matched_ids.add(best.order_id)
            keeps.append(best)
        else:
            places.append(d)
        # Count it either way: a kept order is live exposure too.
        # Sign matters: an unsigned tally lets repeated SELLS walk a short
        # position toward zero, shrinking measured exposure and freeing
        # capacity for the next sell - the opposite of a cap.
        notional = collateral(d.action, d.price, d.quantity)
        delta = d.quantity if d.action == "buy" else -d.quantity
        running.cost_basis += notional
        running.positions[d.exchange_id] = (
            running.positions.get(d.exchange_id, 0.0) + delta)
        running.deployed_by_strategy[d.strategy] = (
            running.deployed_by_strategy.get(d.strategy, 0.0) + notional)

    cancels = [lo for lo in live
               if lo.order_id not in matched_ids and manageable(lo)]
    return Plan(cancels=cancels, places=places, keeps=keeps, vetoed=vetoed)


class Executor:
    """Applies a Plan. Respects the dry-run latches via the client."""

    BATCH_SIZE = 50

    def __init__(self, client: Client, risk: RiskManager,
                 journal: OrderJournal | None = None):
        self.client = client
        self.risk = risk
        # Without a journal, a crash between placement and persistence leaves
        # orders the bot can never manage again.
        self.journal = journal

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

        # The kill switch is enforced HERE as well as during planning. A Plan
        # is just data: it can be built before the switch trips and applied
        # after, and the risk manager is never consulted again on that path.
        # Cancellations are always allowed -- getting flat is what a tripped
        # switch wants -- but nothing new may be placed.
        if self.risk is not None and self.risk.tripped:
            if plan.places:
                result["errors"].append(
                    f"kill switch active ({self.risk.tripped}): "
                    f"suppressed {len(plan.places)} placement(s)")
            plan = Plan(cancels=plan.cancels, places=[], keeps=plan.keeps,
                        vetoed=plan.vetoed)
            result["kill_switch"] = self.risk.tripped

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
                key = self._intent(d)
                try:
                    resp = self.client.place_order(d.exchange_id, d.side, d.action,
                                                   d.quantity, d.price,
                                                   idempotency_key=key)
                    result["placed"] += 1
                    result["requests"] += 1
                    oid = (resp or {}).get("orderId")
                    if oid is not None:
                        result["placed_order_ids"].append(int(oid))
                    if self.journal and key:
                        self.journal.record_placed(key, oid)
                except (ApiError, DryRunBlocked) as e:
                    # Leave the entry PENDING on a retryable error so recovery
                    # can resolve it; only mark terminal failures FAILED.
                    if self.journal and key and not (
                            isinstance(e, ApiError) and e.retryable):
                        self.journal.record_failed(key, str(e))
                    result["errors"].append(f"place {d.exchange_id}@{d.price}: {e}")
        return result

    def _intent(self, d: DesiredOrder) -> str | None:
        """Write-ahead: record the intent BEFORE the order is submitted."""
        if not self.journal:
            return None
        key = self.journal.new_key()
        self.journal.record_intent(key, d.exchange_id, d.side, d.action,
                                   d.price, d.quantity, d.strategy)
        return key

    def _place_batched(self, places: list[DesiredOrder], result: dict) -> dict:
        """
        Batch placement. Cuts a 229-order cycle from ~238 requests to ~14, which
        is the difference between quoting on live prices and quoting on prices
        that moved several minutes ago.
        """
        for i in range(0, len(places), self.BATCH_SIZE):
            chunk = places[i:i + self.BATCH_SIZE]
            keys = [self._intent(d) for d in chunk]
            payload = [{"exchangeId": d.exchange_id, "side": d.side,
                        "action": d.action, "quantity": d.quantity,
                        "price": d.price} for d in chunk]
            # The venue deduplicates on the batch idempotency key, so that key
            # must be a function of durable state. Letting the client mint a
            # fresh uuid per call defeats the mechanism entirely: an ambiguous
            # failure (timeout, 502) leaves the batch possibly landed, and the
            # retry arrives under a DIFFERENT key, so the venue places it
            # again. Deriving it from the journal keys -- which are written
            # before the request and survive a crash -- means any replay of the
            # same chunk presents the same key and is deduplicated.
            #
            # Without a journal there are no durable keys, so fall back to the
            # order contents. That is still deterministic for an identical
            # retry, which is the property the venue needs.
            parts = [k if k else
                     f"{d.exchange_id}:{d.side}:{d.action}:{d.price}:{d.quantity}"
                     for k, d in zip(keys, chunk)]
            batch_key = "sigbot-batch-" + hashlib.sha256(
                "|".join(parts).encode()).hexdigest()[:32]
            try:
                resp = self.client.place_batch(payload, idempotency_key=batch_key)
                result["requests"] += 1
                rows = resp.get("results", []) if isinstance(resp, dict) else []
                if rows and len(rows) < len(chunk):
                    # The venue places serially under a time budget and may
                    # acknowledge only a prefix. Unacknowledged orders may still
                    # have landed, so flag them rather than losing them silently.
                    result["errors"].append(
                        f"batch {i // self.BATCH_SIZE}: only {len(rows)} of "
                        f"{len(chunk)} acknowledged - reconcile before next cycle")
                    result["needs_reconcile"] = True
                if rows:
                    for r in rows:
                        data = r.get("data") or {}
                        idx = r.get("index")
                        k = keys[idx] if isinstance(idx, int) and idx < len(keys) else None
                        if r.get("ok"):
                            result["placed"] += 1
                            oid = data.get("orderId")
                            if oid is not None:
                                result["placed_order_ids"].append(int(oid))
                            if self.journal and k:
                                self.journal.record_placed(k, oid)
                        else:
                            if self.journal and k:
                                self.journal.record_failed(k, str(data.get("code")))
                            result["errors"].append(
                                f"batch item {idx}: "
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
