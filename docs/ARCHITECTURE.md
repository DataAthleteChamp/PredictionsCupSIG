# Architecture

Technical reference for the trading system. For the story and results, see the
main [README](../README.md).

## Design invariants

1. **Strategies never place orders.** They emit *desired state*; `executor.py`
   diffs it against the live book and issues the minimum set of cancels/places.
   Strategies stay pure and unit-testable; a bug cannot spam the venue.
2. **Risk is a single choke point** with veto power over every order.
3. **Never use `price-history`.** It returns empty data while reporting
   `coverage.complete: true`. All time series come from the trade tape.
4. **Two independent latches** (`DRY_RUN=false` *and* `LIVE_TRADING=true`) are
   required before any order leaves the process.
5. **A missing external anchor is treated as an outage, not as news.** When the
   Polymarket feed degrades, the system freezes its last-known-good state
   rather than acting on a partial read.

## Layout
```
sigbot/
  config.py      settings, risk limits, strategy budgets
  api.py         rate-limited client, idempotency, retry policy
  algos.py       tested maths (de-vig, microprice, sizing)
  fair.py        external fair-value engine (Polymarket crosswalk)
  risk.py        vetoes, caps, drawdown kill switch
  executor.py    desired-state diffing
  runner.py      the cycle loop
  strategies/    settlement, ladder, pair, exit (+ 2 retired)
tests/           484 tests
data/            full trade history export (see below)
research/        measurement scripts + findings (gitignored, not public)
```

## Setup
```bash
cp .env.example .env     # add SIG_RECON_KEY and SIG_EXEC_KEY
pip install -e ".[dev]"
python -m pytest
```

## Rules the code encodes (all measured, not assumed)
- Never improve the touch — EV −0.18/order-hour
- Never buy below 0.15 — both tail buckets markout negative
- Size `q ∝ 1/√(p(1−p))` so dollar variance is flat across price levels
- Resting orders reserve no capital; only fills debit the balance

## Data
`data/trade_history.csv` — every fill for the full competition (Oct 2 – Nov 4,
2026), exported directly via the account API: timestamp, market, side, price,
quantity. Not a manual export — paginated programmatically, 9,413 rows.
