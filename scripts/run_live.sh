#!/usr/bin/env bash
# Launch the sigbot runner with a reproducible environment.
#
# The live latches stay EXPLICIT by design. A bare restart must never resume
# trading on its own: DRY_RUN and LIVE_TRADING are deliberately absent from
# .env so that forgetting this flag fails safe into dry-run rather than
# silently trading. The deployment caps, by contrast, DO live in .env --
# a cap that exists only in one terminal's environment is not a cap, which
# is exactly how the bot once ran for hours on the 0.90 default.
#
#   ./scripts/run_live.sh              # dry run, prints the plan only
#   ./scripts/run_live.sh --live       # places real orders
#
set -euo pipefail
cd "$(dirname "$0")/.."

if [[ ! -f .env ]]; then
  echo "error: .env not found" >&2
  exit 1
fi
set -a
# shellcheck disable=SC1091
. ./.env
set +a

: "${SIG_MAX_DEPLOYED_FRACTION:?refusing to start: deployment cap not set in .env}"
: "${SIG_MAX_PER_MARKET_FRACTION:?refusing to start: per-market cap not set in .env}"

LIVE=0
ARGS=()
for a in "$@"; do
  if [[ "$a" == "--live" ]]; then LIVE=1; else ARGS+=("$a"); fi
done

if [[ "$LIVE" == "1" ]]; then
  export DRY_RUN=false LIVE_TRADING=true
  echo "LIVE: orders will be placed (deployed<=${SIG_MAX_DEPLOYED_FRACTION})"
else
  export DRY_RUN=true LIVE_TRADING=false
  echo "DRY RUN: no orders will be placed"
fi

LOG="research/logs/sigbot-$(date -u +%Y%m%dT%H%M%SZ).log"
echo "logging to $LOG"

# Hold off idle sleep for as long as the bot runs.
#
# This is not a nicety. On battery the host entered "Maintenance Sleep"
# repeatedly and the bot managed 10 cycles in 11 hours instead of ~130, losing
# roughly ten hours of trading. The failures looked like DNS errors
# ("nodename nor servname provided") because the network returns a moment
# after the process does, which disguises a host problem as a network one.
#
# -i blocks idle sleep, -m keeps the disk awake, -s holds the assertion while
# running on AC. Closing the lid still sleeps the machine; only AC power plus
# this keeps it up.
CAFFEINATE=""
if command -v caffeinate >/dev/null 2>&1; then
  CAFFEINATE="caffeinate -ims"
  echo "sleep inhibited via caffeinate"
fi
echo "follow with: tail -f $LOG"
# Write STRAIGHT to the log file rather than through a pipe.
#
# This was `| tee -a "$LOG"`. A detached bot inherits whatever stdout the
# launching shell had, and if anything downstream closes that pipe -- a
# `| head`, a disconnected terminal, a reader that exits -- the next print
# raises BrokenPipeError and kills the process mid-cycle. That happened: the
# bot died with 94% of capital deployed and nothing in the log explaining it,
# because the explanation had nowhere to be written.
#
# A file cannot be closed by whoever is reading it, so the log is the only
# safe destination for a process that must outlive its console.
exec $CAFFEINATE python3 -u -m sigbot.runner "${ARGS[@]}" >> "$LOG" 2>&1
