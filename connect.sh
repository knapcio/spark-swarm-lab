#!/usr/bin/env bash
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
mkdir -p "$HERE/.runtime"
for node in 01 02 03 04; do
  socket="$HERE/.runtime/ssh-$node"
  host="Spark_$node"
  if [[ ${1:-connect} == disconnect ]]; then
    ssh -S "$socket" -O exit "$host" 2>/dev/null || true
    continue
  fi
  if ! ssh -S "$socket" -O check "$host" >/dev/null 2>&1; then
    port=$((18080 + 10#$node))
    python3 - "$socket" "$host" "$port" "$HERE" <<'PY'
from pathlib import Path
import subprocess, sys, time
socket, host, port, root = sys.argv[1:]
with (Path(root) / '.runtime' / (host + '.log')).open('a') as log:
    process = subprocess.Popen([
        'ssh', '-M', '-S', socket, '-NT', '-o', 'BatchMode=yes',
        '-o', 'ExitOnForwardFailure=yes', '-o', 'ServerAliveInterval=15',
        '-o', 'ServerAliveCountMax=3', '-L',
        f'127.0.0.1:{port}:127.0.0.1:18096', host,
    ], stdout=log, stderr=log, start_new_session=True)
(Path(root) / '.runtime' / (host + '.pid')).write_text(str(process.pid) + '\n')
time.sleep(1)
if process.poll() is not None:
    raise SystemExit(f'{host}: SSH forward failed; inspect .runtime/{host}.log')
PY
  fi
done
