#!/usr/bin/env bash
set -euo pipefail

OWNER=swarm-lab-20261115
IMAGE=vllm/vllm-openai@sha256:1c8e60a0841b333c700488cb029d3664807249da0c071e862191b00fe34b228c
MODEL_REPO=nvidia/NVIDIA-Nemotron-3.5-Lightning-30B-A3B-NVFP4
MODEL_REV=bee7596271d1495f6992ae224aefde4410e816b8
CONTAINER=swarm-lightning

usage() {
  echo "Usage: $0 {prepare|pull|start|status|stop} [01 02 03 04] | restore" >&2
  exit 2
}
[[ $# -gt 0 ]] || usage
ACTION=$1
shift
case "$ACTION" in prepare|pull|start|status|stop|restore) ;; *) usage ;; esac
if [[ "$ACTION" == restore && $# -gt 0 ]]; then usage; fi
if [[ $# -eq 0 ]]; then set -- 01 02 03 04; fi
NODES=("$@")
for node in "${NODES[@]}"; do
  case "$node" in 01|02|03|04) ;; *) usage ;; esac
done

host_for() {
  local key="SWARM_HOST_$1"
  printf '%s' "${!key:-Spark_$1}"
}

# All remote mutations are explicit commands; failure leaves guards in place.
remote() {
  local node=$1 operation=$2
  ssh -o BatchMode=yes -o ConnectTimeout=15 "$(host_for "$node")" \
    bash -s -- "$node" "$operation" "$OWNER" "$IMAGE" "$MODEL_REPO" "$MODEL_REV" "$CONTAINER" <<'REMOTE'
set -euo pipefail
node=$1 operation=$2 owner=$3 image=$4 model_repo=$5 model_rev=$6 container=$7
expected="spark-$node"
actual=$(hostname -s)
[[ "$actual" == "$expected" ]] || { echo "Refusing host $actual; expected $expected" >&2; exit 1; }
root="$HOME/swarm-lab"
model="$root/model"
guards=()
if [[ "$node" == 01 ]]; then
  guards=("$HOME/dsgb10/no-autostart" "$HOME/fleet_busy")
fi

guard_check() {
  local path
  for path in "${guards[@]}"; do
    if [[ -e "$path" || -L "$path" ]]; then
      [[ -f "$path" && ! -L "$path" && "$(cat "$path")" == "$owner" ]] || {
        echo "Foreign marker: $path; left intact" >&2; return 1;
      }
    fi
  done
}
claim_guards() {
  local path
  guard_check
  [[ "$node" == 01 ]] || return 0
  [[ -d "$HOME/dsgb10" ]] || { echo 'Missing ~/dsgb10' >&2; return 1; }
  for path in "${guards[@]}"; do
    if [[ ! -e "$path" ]]; then
      (set -o noclobber; printf '%s\n' "$owner" > "$path") || {
        echo "Marker appeared while claiming $path; inspect manually" >&2; return 1;
      }
    fi
  done
  guard_check
}
container_exists() { docker container inspect "$container" >/dev/null 2>&1; }
require_ours() {
  local label
  label=$(docker container inspect --format '{{index .Config.Labels "swarm-lab.owner"}}' "$container")
  [[ "$label" == "$owner" ]] || { echo "Foreign container $container; left intact" >&2; return 1; }
}
stop_ours() {
  if container_exists; then
    require_ours
    docker stop -t 60 "$container"
  fi
}
check_model() {
  [[ -s "$model/config.json" && -s "$model/model.safetensors.index.json" && -s "$model/tokenizer.json" && -s "$model/chat_template.jinja" ]] || {
    echo "Incomplete model at $model; expected $model_repo@$model_rev" >&2; return 1;
  }
  python3 - "$model" "$model_rev" <<'PY'
import json, pathlib, sys
p = pathlib.Path(sys.argv[1])
revision = sys.argv[2]
index = json.loads((p / 'model.safetensors.index.json').read_text())
shards = set(index['weight_map'].values())
missing = [s for s in shards if not (p / s).is_file() or (p / s).stat().st_size == 0]
if missing:
    raise SystemExit('Missing model shards: ' + ', '.join(sorted(missing)))
if len(shards) != 52:
    raise SystemExit(f'Expected 52 model shards; found {len(shards)}')
# HF local-dir download metadata records the exact requested commit per file.
metadata = p / '.cache/huggingface/download'
for name in ['config.json', 'model.safetensors.index.json', 'tokenizer.json', 'tokenizer_config.json', 'chat_template.jinja', *sorted(shards)]:
    marker = metadata / (name + '.metadata')
    if not marker.is_file() or marker.read_text().splitlines()[0] != revision:
        raise SystemExit(f'Unverified revision for {name}; download using --revision {revision} --local-dir {p}')
print(f'Model snapshot verified: {revision}, {len(shards)} shards')
PY
}
disk_check() {
  local available
  available=$(df -Pk "$HOME" | awk 'END {print $4}')
  [[ "$available" =~ ^[0-9]+$ && "$available" -ge 10485760 ]] || {
    echo 'Need at least 10 GiB free disk before starting' >&2; return 1;
  }
}
case "$operation" in
  prepare)
    echo "$actual"
    df -h "$HOME"
    awk '/MemAvailable:/ {printf "MemAvailable: %.2f GiB\n", $2/1048576}' /proc/meminfo
    docker version --format '{{.Server.Version}}'
    docker image inspect "$image" --format '{{.Architecture}} {{.Id}}' 2>/dev/null || true
    if [[ -d "$model" ]]; then du -sh "$model"; fi
    ;;
  pull)
    docker pull --platform linux/arm64 "$image"
    ;;
  preflight)
    guard_check
    disk_check
    check_model
    [[ "$(docker image inspect "$image" --format '{{.Architecture}}')" == arm64 ]]
    if container_exists; then require_ours; fi
    ;;
  claim)
    claim_guards
    ;;
  stop-production)
    [[ "$node" == 01 ]]
    guard_check
    cd "$HOME/dsgb10/pico-dgx-ds4/ds41f-4xgx10-switchless"
    FLEET="$HOME/dsgb10/fleet.conf" engine/server/service.sh stop
    ;;
  start)
    guard_check
    for path in "${guards[@]}"; do [[ -f "$path" ]]; done
    disk_check
    check_model
    if container_exists; then
      require_ours
      if [[ "$(docker container inspect --format '{{.State.Running}}' "$container")" == true ]]; then
        curl --fail --silent --show-error --max-time 10 http://127.0.0.1:18096/health
        echo "$actual: already running"
        exit 0
      fi
    fi
    available=$(awk '/MemAvailable:/ {print $2}' /proc/meminfo)
    [[ "$available" =~ ^[0-9]+$ && "$available" -ge 94371840 ]] || {
      echo "$actual: need 90 GiB MemAvailable; found ${available:-unknown} KiB" >&2; exit 1;
    }
    if container_exists; then docker container rm "$container"; fi
    mkdir -p "$root/cache"
    docker run -d --name "$container" --label "swarm-lab.owner=$owner" \
      --label "swarm-lab.model=$model_repo" --label "swarm-lab.revision=$model_rev" \
      --gpus all --ipc=host --network=host --restart=no \
      -v "$model:/model:ro" -v "$root/cache:/root/.cache" \
      "$image" /model --served-model-name nemotron-lightning \
      --host 127.0.0.1 --port 18096 --max-model-len 16384 --max-num-seqs 25 \
      --max-num-batched-tokens 4096 --gpu-memory-utilization 0.70 \
      --moe-backend marlin --kv-cache-dtype fp8 --mamba-backend flashinfer \
      --mamba-cache-mode align --enable-prefix-caching --enable-chunked-prefill \
      --reasoning-parser nemotron_v3 --tool-call-parser qwen3_coder --enable-auto-tool-choice
    echo "$actual: started; wait for /health before sending work"
    ;;
  status)
    echo "$actual"
    for path in "${guards[@]}"; do
      if [[ -e "$path" || -L "$path" ]]; then
        if [[ -f "$path" && ! -L "$path" && "$(cat "$path")" == "$owner" ]]; then
          echo "Owned guard: $path"
        else echo "Foreign guard: $path"; fi
      else echo "Absent guard: $path"; fi
    done
    if container_exists; then
      docker container inspect --format '{{.Name}} {{.State.Status}} restart={{.HostConfig.RestartPolicy.Name}} owner={{index .Config.Labels "swarm-lab.owner"}}' "$container"
    else echo 'Prototype container absent'; fi
    curl --fail --silent --show-error --max-time 5 http://127.0.0.1:18096/health && echo ' health=200' || echo ' health=not-ready'
    ;;
  stop)
    stop_ours
    echo "$actual: prototype stopped; production guards retained"
    ;;
  restore-check)
    guard_check
    if container_exists; then require_ours; fi
    ;;
  release)
    guard_check
    for path in "${guards[@]}"; do
      if [[ -f "$path" && ! -L "$path" && "$(cat "$path")" == "$owner" ]]; then rm -- "$path"; fi
    done
    ;;
  production)
    [[ "$node" == 01 ]]
    guard_check
    "$HOME/dsgb10/window.sh" prod
    ;;
  *) exit 2 ;;
esac
REMOTE
}

case "$ACTION" in
  start)
    # Preflight selected model nodes before stopping the shared TP4 service.
    for node in "${NODES[@]}"; do remote "$node" preflight; done
    for node in 01 02 03 04; do remote "$node" claim; done
    remote 01 stop-production
    for node in "${NODES[@]}"; do remote "$node" start; done
    ;;
  restore)
    for node in 01 02 03 04; do remote "$node" restore-check; done
    for node in 01 02 03 04; do remote "$node" stop; done
    for node in 01 02 03 04; do remote "$node" release; done
    remote 01 production
    ;;
  *) for node in "${NODES[@]}"; do remote "$node" "$ACTION"; done ;;
esac
