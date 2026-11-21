#!/usr/bin/env bash
# Swarm Lab Inkling-2-Mini replica: SGLang DGX Spark DSpark recipe (sglang cookbook inkling-2-mini.jsx,
# dgx-spark/nvfp4/dspark cell), text-only, loopback only. Defaults: --mem-fraction-static 0.75 since 2026-11-21
# (~1.08M KV tokens, ~26 GiB MemAvailable after start; was 0.62 = 833K tokens, ~40 GiB), metrics on.
# Tuning record: inkling/TUNING.md.
set -euo pipefail
NAME=${NAME:-swarm-inkling}
PORT=${PORT:-30000}
MEM=${MEM:-0.75}
CTX=${CTX:-131072}
EXTRA=${EXTRA:---enable-metrics}
docker rm -f "$NAME" >/dev/null 2>&1 || true
docker run -d --name "$NAME" --label swarm-lab.owner=swarm-lab-20261120-inkling \
  --gpus all --ipc=host --network host --shm-size 16g \
  -v "$HOME/swarm-lab/inkling/model:/model:ro" \
  -v "$HOME/swarm-lab/inkling/cache:/root/.cache" \
  -e MAX_JOBS=4 \
  -e SGLANG_OPT_INKLING2_VERIFY_REL_BIAS_KERNEL=1 \
  -e SGLANG_OPT_DSV41_DSPARK_MID_FOLD=1 \
  -e SGLANG_OPT_DSV41_DSPARK_PREPARE_INPUTS_ONCE=1 \
  -e SGLANG_OPT_DSV41_DSPARK_SKIP_PREFILLED_INPUTS=1 \
  ${ENVX:-} \
  lmsysorg/sglang:inkling-2-mini \
  python3 -m sglang.launch_server --model-path /model --served-model-name inkling \
  --tp 1 --ep 1 --attention-backend fa4 --dtype bfloat16 --page-size 128 \
  ${SPEC:---speculative-algorithm DSPARK --speculative-num-draft-tokens 8} \
  --mem-fraction-static "$MEM" --context-length "$CTX" --grammar-backend xgrammar \
  --reasoning-parser inkling --tool-call-parser inkling2 \
  --host 127.0.0.1 --port "$PORT" $EXTRA
