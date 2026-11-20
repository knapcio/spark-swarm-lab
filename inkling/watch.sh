#!/usr/bin/env bash
# Watchdog for Inkling runs: prints a line on problems, on run exit, and a progress line every ~30 min.
# usage: watch.sh RUN_DIR... (relative to apps/swarm-lab/runs)
cd "$(dirname "$0")/.." || exit 1
tick=0
done_list=" "
runs_line=""
while true; do
  runs_line=""
  for n in 01 02 03 04; do
    out=$(ssh -o BatchMode=yes -o ConnectTimeout=10 "Spark_${n}" '
      s=$(docker inspect --format "{{.State.Running}} {{.State.OOMKilled}} {{.RestartCount}}" swarm-inkling 2>/dev/null)
      h=$(docker inspect --format "{{.State.Running}} {{.RestartCount}}" swarm-inkling-shim 2>/dev/null)
      m=$(curl -s -m 5 127.0.0.1:18096/metrics)
      w=$(echo "$m" | grep -E "^vllm:num_requests_waiting" | awk "{print \$2}")
      r=$(echo "$m" | grep -E "^vllm:num_requests_running" | awk "{print \$2}")
      e=$(echo "$m" | grep -E "^shim:upstream_errors" | awk "{print \$2}")
      nm=$(echo "$m" | grep -E "^shim:non_monotonic" | awk "{print \$2}")
      echo "$s|$h|$r|$w|$e|$nm"' 2>&1)
    IFS='|' read -r srv shim run wait err nonmono <<< "$out"
    [[ "$srv" == "true false 0" ]] || echo "ALERT Spark_${n} server state: $srv"
    [[ "$shim" == "true 0" ]] || echo "ALERT Spark_${n} shim state: $shim"
    [[ "${wait:-x}" == "0.0" ]] || echo "ALERT Spark_${n} waiting=$wait running=$run"
    eval "b=\${base_err_$n:-}"; if [[ -z "$b" ]]; then eval "base_err_$n=${err:-0}"; b=${err:-0}; fi
    [[ "${err:-0}" == "$b" ]] || { echo "ALERT Spark_${n} shim upstream_errors=$err (baseline $b)"; eval "base_err_$n=$err"; }
    [[ "${nonmono:-0}" == "0" ]] || echo "WARN Spark_${n} shim non_monotonic=$nonmono"
    runs_line="$runs_line$n:$run "
  done
  for d in "$@"; do
    log="runs/$d.log"
    if [[ "$done_list" != *" $d "* ]] && ! pgrep -f "output runs/$d" >/dev/null; then
      done_list="$done_list$d "
      echo "RUN EXITED $d: $(tail -c 400 "$log" | tr '\n' ' ')"
    fi
  done
  if (( tick % 15 == 0 )); then
    a=$(ls runs/inkling-hard4-v1/agents 2>/dev/null | grep -c '\.jsonl$')
    c=$(ls runs/inkling-coding-hard-v1 2>/dev/null | grep -c '\.jsonl$')
    echo "PROGRESS $(date +%H:%M) arithmetic agent files=$a coding agent files=$c running $runs_line"
  fi
  tick=$((tick + 1))
  runs_line=""
  [[ $(echo $done_list | wc -w) -eq $# ]] && exit 0
  sleep 120
done
