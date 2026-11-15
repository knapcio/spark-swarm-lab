#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
method=${1:-democracy}
puzzle=${2:-25,50,75,100,3,6:952}
agents=${3:-100}
reputation=${4:-}
if [[ "$method" == weighted ]]; then
  [[ $# -ge 4 ]] || { echo 'weighted needs a calibration reputation file as argument 4' >&2; exit 2; }
fi
[[ "$agents" =~ ^[0-9]+$ && "$agents" -ge 1 && "$agents" -le 100 ]] || {
  echo 'Choose 1..100 agents' >&2; exit 2;
}
stamp=$(date '+%Y%m%d-%H%M%S')
set --
if [[ "$method" == weighted ]]; then set -- --reputation "$reputation"; fi
exec python3 "$HERE/harness.py" --method "$method" --puzzle "$puzzle" \
  --endpoint http://127.0.0.1:18081/v1 --endpoint http://127.0.0.1:18082/v1 \
  --endpoint http://127.0.0.1:18083/v1 --endpoint http://127.0.0.1:18084/v1 \
  --model nemotron-lightning --agents "$agents" --per-endpoint-concurrency "${SWARM_CONCURRENCY:-25}" \
  --rounds 5 --max-tokens 192 --max-calls "$((agents * 10))" \
  --max-completion-tokens "$((agents * 10 * 192))" --timeout 180 --seed "${SWARM_SEED:-1}" \
  --events "$HERE/runs/$stamp-$method-$agents.jsonl" "$@"
