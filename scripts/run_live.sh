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
exec python3 -u -m sigbot.runner "${ARGS[@]}" 2>&1 | tee -a "$LOG"
