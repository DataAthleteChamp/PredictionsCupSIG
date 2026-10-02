"""
Durable order journal.

The failure this exists to prevent: the process places orders, then crashes
before recording their ids. Those orders rest on the venue forever, invisible to
the bot, which will never cancel or replace them. With deep passive bids that is
unbounded stale exposure.

The fix uses the venue's own idempotency guarantee. Every placement is recorded
as `pending` with its idempotency key BEFORE it is submitted. If we crash at any
point, recovery re-submits the identical payload under the SAME key — the venue
replays its stored response rather than placing a second order — and we learn
the order id we lost.

Write-ahead ordering is the whole point:
    1. record intent (fsync)      <- survives a crash here
    2. submit to venue
    3. record outcome

A crash between 1 and 2 means a pending entry that was never sent; re-submitting
is a normal first placement. A crash between 2 and 3 means a pending entry that
may or may not have landed; re-submitting resolves it safely. Both are handled
by the same code path.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Iterable

PENDING = "pending"
PLACED = "placed"
FAILED = "failed"
CLOSED = "closed"


@dataclass(frozen=True)
class JournalEntry:
    key: str
    exchange_id: str
    side: str
    action: str
    price: float
    quantity: int
    strategy: str
    status: str
    order_id: int | None
    created_at: float
    updated_at: float

    def payload(self) -> dict:
        """The exact order body this entry represents."""
        return {"exchangeId": self.exchange_id, "side": self.side,
                "action": self.action, "quantity": self.quantity,
                "price": self.price}


class OrderJournal:
    """SQLite-backed write-ahead log for order placements."""

    def __init__(self, path: str = "research/data/journal.db"):
        self.path = path
        d = os.path.dirname(path)
        if d:
            os.makedirs(d, exist_ok=True)
        self.con = sqlite3.connect(path, isolation_level=None)
        # FULL synchronous: an entry must survive a crash immediately after the
        # write returns, otherwise the whole write-ahead guarantee is void.
        self.con.execute("PRAGMA journal_mode=WAL")
        self.con.execute("PRAGMA synchronous=FULL")
        self.con.execute("""
            CREATE TABLE IF NOT EXISTS orders(
              key TEXT PRIMARY KEY, exchange_id TEXT, side TEXT, action TEXT,
              price REAL, quantity INTEGER, strategy TEXT, status TEXT,
              order_id INTEGER, created_at REAL, updated_at REAL)""")
        self.con.execute(
            "CREATE INDEX IF NOT EXISTS i_status ON orders(status)")

    # ------------------------------------------------------------- writing --

    def new_key(self, prefix: str = "sigbot") -> str:
        return f"{prefix}-{uuid.uuid4()}"

    def record_intent(self, key: str, exchange_id: str, side: str, action: str,
                      price: float, quantity: int, strategy: str) -> str:
        """Step 1. Must complete before the order is submitted."""
        now = time.time()
        self.con.execute(
            "INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?,?,?,?,?,?,?)",
            (key, str(exchange_id), side, action, float(price), int(quantity),
             strategy, PENDING, None, now, now))
        return key

    def record_placed(self, key: str, order_id: int | None) -> None:
        """Step 3, success."""
        self.con.execute(
            "UPDATE orders SET status=?, order_id=?, updated_at=? WHERE key=?",
            (PLACED, int(order_id) if order_id is not None else None,
             time.time(), key))

    def record_failed(self, key: str, reason: str = "") -> None:
        """Step 3, terminal failure. Not retried on recovery."""
        self.con.execute(
            "UPDATE orders SET status=?, updated_at=? WHERE key=?",
            (FAILED, time.time(), key))

    def record_closed(self, order_ids: Iterable[int]) -> None:
        """Mark orders no longer open, so the managed set stays bounded."""
        ids = [int(i) for i in order_ids]
        if not ids:
            return
        self.con.executemany(
            "UPDATE orders SET status=?, updated_at=? WHERE order_id=?",
            [(CLOSED, time.time(), i) for i in ids])

    # ------------------------------------------------------------- reading --

    def _rows(self, where: str, args: tuple = ()) -> list[JournalEntry]:
        cur = self.con.execute(
            "SELECT key,exchange_id,side,action,price,quantity,strategy,"
            f"status,order_id,created_at,updated_at FROM orders {where}", args)
        return [JournalEntry(*r) for r in cur.fetchall()]

    def pending(self) -> list[JournalEntry]:
        """Entries whose fate is unknown. These are what recovery resolves."""
        return self._rows("WHERE status=? ORDER BY created_at", (PENDING,))

    def managed_order_ids(self) -> set[int]:
        """
        Ownership, derived from the journal rather than inferred from the
        account. Only ids we recorded for orders we submitted.
        """
        return {r.order_id for r in self._rows("WHERE status=? AND order_id IS NOT NULL",
                                               (PLACED,))
                if r.order_id is not None}

    def get(self, key: str) -> JournalEntry | None:
        rows = self._rows("WHERE key=?", (key,))
        return rows[0] if rows else None

    def stats(self) -> dict:
        cur = self.con.execute("SELECT status, COUNT(*) FROM orders GROUP BY status")
        return dict(cur.fetchall())

    def prune(self, older_than_seconds: float = 7 * 24 * 3600) -> int:
        """Drop long-closed entries so the journal does not grow forever."""
        cut = time.time() - older_than_seconds
        cur = self.con.execute(
            "DELETE FROM orders WHERE status IN (?,?) AND updated_at < ?",
            (CLOSED, FAILED, cut))
        return cur.rowcount

    def close(self) -> None:
        self.con.close()


def recover(journal: OrderJournal, client, *, dry_run: bool = True) -> dict:
    """
    Resolve every pending entry left behind by a crash.

    Re-submitting with the same idempotency key is safe by construction: the
    venue replays its stored response if the order already landed, and places it
    normally if it did not. Either way we learn the order id.
    """
    out = {"pending": 0, "resolved": 0, "failed": 0, "dry_run": dry_run}
    entries = journal.pending()
    out["pending"] = len(entries)
    if dry_run or not entries:
        return out
    for e in entries:
        try:
            resp = client.place_order(e.exchange_id, e.side, e.action,
                                      e.quantity, e.price, idempotency_key=e.key)
            journal.record_placed(e.key, (resp or {}).get("orderId"))
            out["resolved"] += 1
        except Exception as exc:
            journal.record_failed(e.key, str(exc))
            out["failed"] += 1
    return out
