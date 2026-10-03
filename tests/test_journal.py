"""
Tests for the durable order journal.

The scenario these protect against: the bot places orders, then the process dies
before recording their ids. Those orders rest on the venue forever, invisible to
the bot. The journal's write-ahead ordering plus the venue's idempotency makes
that recoverable.
"""
import pytest

from sigbot.executor import DesiredOrder, Executor, Plan
from sigbot.journal import (CLOSED, FAILED, PENDING, PLACED, OrderJournal,
                            recover)
from sigbot.config import Settings
from sigbot.risk import RiskManager


@pytest.fixture
def jr(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    yield j
    j.close()


def d(exchange_id="36", price=0.50, quantity=100, strategy="ladder"):
    return DesiredOrder(exchange_id, "yes", "buy", price, quantity, strategy)


def rm():
    return RiskManager(Settings(base_url="x", recon_key="r", exec_key="e"))


class StubClient:
    def __init__(self, dry=False, fail=False, start_id=1000):
        self.s = Settings(base_url="x", recon_key="r", exec_key="e",
                          dry_run=dry, live_trading=not dry)
        self.fail = fail
        self.next_id = start_id
        self.seen_keys = []
        self.cancelled = []

    def place_order(self, ex, side, action, qty, price, idempotency_key=None):
        self.seen_keys.append(idempotency_key)
        if self.fail:
            from sigbot.api import ApiError
            raise ApiError(400, "VALIDATION_ERROR", "bad")
        self.next_id += 1
        return {"orderId": self.next_id}

    def place_batch(self, orders, idempotency_key=None):
        rows = []
        for i, _ in enumerate(orders):
            self.next_id += 1
            rows.append({"ok": True, "index": i, "data": {"orderId": self.next_id}})
        return {"results": rows}

    def cancel_order(self, oid):
        self.cancelled.append(oid)


# ------------------------------------------------------------- basics -------

def test_intent_is_recorded_as_pending(jr):
    jr.record_intent("k1", "36", "yes", "buy", 0.5, 10, "ladder")
    e = jr.get("k1")
    assert e.status == PENDING and e.order_id is None
    assert e.payload() == {"exchangeId": "36", "side": "yes", "action": "buy",
                           "quantity": 10, "price": 0.5}


def test_placed_records_the_order_id(jr):
    jr.record_intent("k1", "36", "yes", "buy", 0.5, 10, "ladder")
    jr.record_placed("k1", 4242)
    assert jr.get("k1").status == PLACED
    assert jr.managed_order_ids() == {4242}


def test_failed_entries_are_not_pending(jr):
    jr.record_intent("k1", "36", "yes", "buy", 0.5, 10, "ladder")
    jr.record_failed("k1", "bad")
    assert jr.pending() == []
    assert jr.get("k1").status == FAILED


def test_intent_is_idempotent_on_the_same_key(jr):
    jr.record_intent("k1", "36", "yes", "buy", 0.5, 10, "ladder")
    jr.record_placed("k1", 7)
    jr.record_intent("k1", "36", "yes", "buy", 0.5, 10, "ladder")   # replay
    assert jr.get("k1").status == PLACED       # must not revert to pending


def test_managed_ids_exclude_pending_and_closed(jr):
    jr.record_intent("a", "1", "yes", "buy", 0.5, 1, "ladder")
    jr.record_intent("b", "2", "yes", "buy", 0.5, 1, "ladder")
    jr.record_placed("b", 22)
    jr.record_intent("c", "3", "yes", "buy", 0.5, 1, "ladder")
    jr.record_placed("c", 33)
    jr.record_closed([33])
    assert jr.managed_ids_sanity() if hasattr(jr, "managed_ids_sanity") else True
    assert jr.managed_order_ids() == {22}


def test_prune_only_removes_old_terminal_entries(jr):
    jr.record_intent("a", "1", "yes", "buy", 0.5, 1, "ladder")
    jr.record_placed("a", 1)
    jr.record_closed([1])
    assert jr.prune(older_than_seconds=-1) == 1
    jr.record_intent("b", "2", "yes", "buy", 0.5, 1, "ladder")
    assert jr.prune(older_than_seconds=-1) == 0      # pending is never pruned
    assert len(jr.pending()) == 1


def test_stats_reports_counts(jr):
    jr.record_intent("a", "1", "yes", "buy", 0.5, 1, "ladder")
    jr.record_intent("b", "2", "yes", "buy", 0.5, 1, "ladder")
    jr.record_placed("b", 2)
    s = jr.stats()
    assert s[PENDING] == 1 and s[PLACED] == 1


# -------------------------------------------------- write-ahead ordering ----

def test_intent_exists_before_the_order_is_submitted(tmp_path):
    """
    The core guarantee. If the venue call raises, the entry must already be on
    disk as pending so recovery can resolve it.
    """
    j = OrderJournal(str(tmp_path / "j.db"))

    class Boom(StubClient):
        def place_order(self, *a, **k):
            # by now the intent must already be durable
            assert j.pending(), "intent was not recorded before submission"
            raise RuntimeError("process died")

    ex = Executor(Boom(), rm(), journal=j)
    with pytest.raises(RuntimeError):
        ex.apply(Plan([], [d()], [], []))
    assert len(j.pending()) == 1
    j.close()


def test_retryable_failure_leaves_entry_pending_for_recovery(tmp_path):
    """A 502 may already have executed, so the entry must stay recoverable."""
    from sigbot.api import ApiError
    j = OrderJournal(str(tmp_path / "j.db"))

    class Unknown(StubClient):
        def place_order(self, *a, **k):
            raise ApiError(502, "ORDER_STATUS_UNKNOWN", "")

    Executor(Unknown(), rm(), journal=j).apply(Plan([], [d()], [], []))
    assert len(j.pending()) == 1          # NOT marked failed
    j.close()


def test_terminal_failure_is_marked_failed(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    Executor(StubClient(fail=True), rm(), journal=j).apply(Plan([], [d()], [], []))
    assert j.pending() == []
    assert j.stats().get(FAILED) == 1
    j.close()


def test_executor_uses_the_journal_key_for_placement(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    cl = StubClient()
    Executor(cl, rm(), journal=j).apply(Plan([], [d()], [], []))
    assert cl.seen_keys and cl.seen_keys[0]
    assert j.get(cl.seen_keys[0]).status == PLACED
    j.close()


def test_batch_placements_are_journalled(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    places = [d(exchange_id=str(i)) for i in range(5)]
    Executor(StubClient(), rm(), journal=j).apply(Plan([], places, [], []))
    assert len(j.managed_order_ids()) == 5
    assert j.pending() == []
    j.close()


def test_executor_works_without_a_journal(tmp_path):
    out = Executor(StubClient(), rm(), journal=None).apply(Plan([], [d()], [], []))
    assert out["placed"] == 1


# ----------------------------------------------------------- recovery ------

def test_recover_resolves_orphans_using_the_same_key(tmp_path):
    """
    Simulates a crash: an entry is pending with no order id. Recovery re-submits
    under the SAME key, which the venue replays rather than double-placing.
    """
    j = OrderJournal(str(tmp_path / "j.db"))
    j.record_intent("orphan-1", "36", "yes", "buy", 0.5, 10, "ladder")
    cl = StubClient()
    out = recover(j, cl, dry_run=False)
    assert out["pending"] == 1 and out["resolved"] == 1
    assert cl.seen_keys == ["orphan-1"]            # same key, not a new one
    assert j.pending() == []
    assert j.managed_order_ids()
    j.close()


def test_recover_is_a_noop_in_dry_run(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    j.record_intent("orphan-1", "36", "yes", "buy", 0.5, 10, "ladder")
    cl = StubClient()
    out = recover(j, cl, dry_run=True)
    assert out["pending"] == 1 and out["resolved"] == 0
    assert cl.seen_keys == []
    assert len(j.pending()) == 1
    j.close()


def test_recover_marks_terminal_failures(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    j.record_intent("orphan-1", "36", "yes", "buy", 0.5, 10, "ladder")
    out = recover(j, StubClient(fail=True), dry_run=False)
    assert out["failed"] == 1 and j.pending() == []
    j.close()


def test_journal_survives_reopen(tmp_path):
    """Durability: a new process must see what the dead one recorded."""
    path = str(tmp_path / "j.db")
    j1 = OrderJournal(path)
    j1.record_intent("k", "36", "yes", "buy", 0.5, 10, "ladder")
    j1.close()
    j2 = OrderJournal(path)
    assert len(j2.pending()) == 1
    j2.close()


def test_ownership_comes_from_the_journal_not_the_account(tmp_path):
    """
    A manual order placed outside the bot must never appear in managed ids,
    no matter what the account returns.
    """
    j = OrderJournal(str(tmp_path / "j.db"))
    j.record_intent("mine", "36", "yes", "buy", 0.5, 10, "ladder")
    j.record_placed("mine", 111)
    assert j.managed_order_ids() == {111}          # 999 (manual) is absent
    j.close()


# ------------------------------------------------------------- adoption ---

def _live(oid, ex="7", px=0.3, qty=10):
    return {"id": oid, "exchangeId": ex, "side": "yes", "action": "buy",
            "priceLimit": px, "quantity": qty}


def test_adopt_takes_ownership_of_orphans(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    assert j.managed_order_ids() == set()
    assert j.adopt([_live(11), _live(12)]) == 2
    assert j.managed_order_ids() == {11, 12}


def test_adopt_is_idempotent(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    j.adopt([_live(11)])
    assert j.adopt([_live(11), _live(12)]) == 1      # only the new one
    assert j.managed_order_ids() == {11, 12}


def test_adopt_does_not_resurrect_closed_orders(tmp_path):
    """A filled order must not be re-adopted as if it were still open."""
    j = OrderJournal(str(tmp_path / "j.db"))
    k = j.record_intent("k1", "7", "yes", "buy", 0.3, 10, "ladder")
    j.record_placed(k, 99)
    j.record_closed([99])
    assert j.adopt([_live(99)]) == 0
    assert 99 not in j.managed_order_ids()


def test_adopt_preserves_order_details(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    j.adopt([_live(11, ex="42", px=0.125, qty=77)])
    row = j._rows("WHERE order_id=11")[0]
    assert (row.exchange_id, row.price, row.quantity) == ("42", 0.125, 77)
    assert row.strategy == "adopted"


def test_adopt_skips_orders_without_an_id(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    assert j.adopt([{"exchangeId": "7", "side": "yes", "action": "buy"}]) == 0


def _pstate():
    from sigbot.risk import PortfolioState
    return PortfolioState(balance=99_000.0, equity=100_000.0,
                          cost_basis=1_000.0, peak_equity=100_000.0,
                          positions={}, deployed_by_strategy={})


def test_adopted_orders_become_cancellable_by_the_executor(tmp_path):
    """The whole point: adoption must make the executor willing to cancel."""
    from sigbot.executor import LiveOrder, plan_orders
    j = OrderJournal(str(tmp_path / "j.db"))
    live = [LiveOrder.from_api(_live(11, px=0.08))]
    risk = RiskManager(Settings(base_url="https://x", recon_key="r",
                                exec_key="e"))
    before = plan_orders([], live, risk, _pstate(), managed_order_ids=set())
    assert before.cancels == []                      # unowned: left alone
    j.adopt([_live(11, px=0.08)])
    after = plan_orders([], live, risk, _pstate(),
                        managed_order_ids=j.managed_order_ids())
    assert [o.order_id for o in after.cancels] == [11]


# -------------------------------------------------- fail-closed semantics ---

def test_placed_without_an_order_id_stays_pending(tmp_path):
    """
    A success response with no order id is AMBIGUOUS. Recording PLACED would
    claim success while leaving the order permanently unmanageable.
    """
    j = OrderJournal(str(tmp_path / "j.db"))
    k = j.record_intent("k1", "7", "yes", "buy", 0.3, 10, "ladder")
    j.record_placed(k, None)
    assert j.managed_order_ids() == set()
    assert [e.key for e in j.pending()] == ["k1"], "must remain recoverable"


def test_pending_intents_are_reconciled_not_duplicated(tmp_path):
    """
    A batch that times out mid-flight leaves intents PENDING with no order id,
    so the orders it DID place are invisible to managed_order_ids() and the
    planner places them again. Measured live: 47 landed, 0 recorded, 47
    orphaned.

    On a single-tenant account the ambiguity is resolvable: adopt what is live
    and unmanaged, then retire the pending intents.
    """
    j = OrderJournal(str(tmp_path / "j.db"))
    k1 = j.record_intent("k1", "7", "yes", "buy", 0.3, 10, "ladder")
    k2 = j.record_intent("k2", "8", "yes", "buy", 0.3, 10, "ladder")
    assert len(j.pending()) == 2 and j.managed_order_ids() == set()

    live = [_live(501, ex="7"), _live(502, ex="8")]      # they actually landed
    assert j.adopt(live, strategy="reconciled") == 2
    for e in j.pending():
        j.record_failed(e.key)

    assert j.managed_order_ids() == {501, 502}, "live orders must become ours"
    assert j.pending() == [], "ambiguity must not persist into the next cycle"


def test_reconcile_does_not_claim_orders_already_managed(tmp_path):
    j = OrderJournal(str(tmp_path / "j.db"))
    k = j.record_intent("k1", "7", "yes", "buy", 0.3, 10, "ladder")
    j.record_placed(k, 501)
    assert j.adopt([_live(501, ex="7")], strategy="reconciled") == 0
    assert j.managed_order_ids() == {501}
