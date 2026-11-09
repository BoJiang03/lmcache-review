#!/usr/bin/env bash
# Pre-launch distillation round, driven by what the AI misses:
#   1. run the reviewer on N train samples of AREA           (paid: ~$1.3/sample)
#   2. judge them -> human-only comments (misses)            (paid: ~$0.4/sample)
#   3. distill a rulebook from the misses only               (paid: < $1 for a few dozen misses)
#   4. coverage: do the new entries explain held-out (test) misses of the same reviewer? (paid: < $1)
# Then, only if coverage looks useful: A/B on test with `lmreview review/eval --vs` (not in this script).
#
# usage: scripts/misses_pipeline.sh [AREA] [N] [REVIEWER] [OUT]
#        DRY=1 scripts/misses_pipeline.sh ...   # print plans and estimates only, spend nothing
set -euo pipefail
AREA=${1:-vllm-integration}; N=${2:-30}; R=${3:-v0b@high}; OUT=${4:-r2-${AREA}}
cd "$(dirname "$0")/.."
L=bin/lmreview
if [[ "${DRY:-0}" == 1 ]]; then C_REV=0 C_JUDGE=0 C_DIST=0 C_COV=0
else C_REV=$(python3 -c "print(round($N*1.3*1.15,1))") C_JUDGE=$(python3 -c "print(round($N*0.4*1.25,1))") C_DIST=3 C_COV=1; fi

$L review --reviewer "$R" --split train --area "$AREA" --limit "$N" --max-cost "$C_REV"
[[ "${DRY:-0}" == 1 ]] || $L eval --reviewer "$R" --max-cost "$C_JUDGE" > /dev/null
$L distill "$OUT" --misses-of "$R" --max-cost "$C_DIST"
[[ "${DRY:-0}" == 1 ]] && { echo "(dry run: judge ~\$$(python3 -c "print(round($N*0.4,1))") and coverage < \$1 not estimated in detail)"; exit 0; }
$L eval --rules "$OUT" --split test --misses-of "$R" --max-cost "$C_COV"
