#!/usr/bin/env bash
# usage: benchset.sh LABEL  -> appends JSON lines to bench.jsonl (on-box, through the shim)
L=$1
python3 bench_think.py --base http://127.0.0.1:18096 --concurrency 1 --requests 3 --max-tokens 2048 --label "$L-c1" >> bench.jsonl
python3 bench_think.py --base http://127.0.0.1:18096 --concurrency 8 --requests 16 --max-tokens 4096 --label "$L-c8" >> bench.jsonl
python3 bench_think.py --base http://127.0.0.1:18096 --concurrency 24 --requests 48 --max-tokens 4096 --label "$L-c24" >> bench.jsonl
echo done >> bench.jsonl
