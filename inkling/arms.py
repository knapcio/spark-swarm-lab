#!/usr/bin/env python3
"""Run ONE arm (policy) of a frozen run_variants plan alone on the Inkling fleet, with server-side accounting.

Sequence: fresh admission (inkling/admit.py, idle fleet) -> prefix-cache flush on each node (POST /flush_cache on
the loopback SGLang port, so no arm inherits another arm's cache) -> server counters on all four nodes ->
run_variants.py --policy ARM -> wait until every node is idle -> counters again -> GPU energy for the window
(inkling/energy.py). Server counters are cumulative SGLang counters read through the tunnels; they include the
tokens of requests aborted by a cancelled agent (verified 2026-11-21, .runtime/SHIM_CANCEL_VERIFICATION_20261121.txt).
Writes OUTPUT/arm_accounting.json. The arm must be the only client of the fleet.

usage: arms.py --plan PLAN --arm POLICY --output runs/NAME [--resume-from runs/OLD]
"""
import argparse
import json
import re
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import energy  # noqa: E402
import fleet_lease  # noqa: E402

NODES = ['01', '02', '03', '04']
COUNTERS = {  # name in output -> (metric, label filter)
    'generation_tokens': ('sglang:generation_tokens_total', ''),
    'decode_tokens': ('sglang:realtime_tokens_total', 'mode="decode"'),
    'prefill_compute_tokens': ('sglang:realtime_tokens_total', 'mode="prefill_compute"'),
    'prompt_tokens': ('sglang:prompt_tokens_total', ''),
    'requests': ('sglang:num_requests_total', ''),
    'running': ('sglang:num_running_reqs', ''),
    'queued': ('sglang:num_queue_reqs', ''),
    'shim_requests': ('shim:requests', ''),
    'shim_client_cancels': ('shim:client_cancels', ''),
    'shim_upstream_errors': ('shim:upstream_errors', ''),
    'shim_non_monotonic': ('shim:non_monotonic', ''),
}


def parse(text):
    out = {k: 0.0 for k in COUNTERS}
    for line in text.splitlines():
        m = re.match(r'^([^{\s]+)(\{[^}]*\})?\s+(\S+)', line)
        if not m or line.startswith('#'):
            continue
        for key, (name, label) in COUNTERS.items():
            if m.group(1) == name and label in (m.group(2) or ''):
                out[key] += float(m.group(3))
    return out


def snapshot():
    snap = dict(utc=datetime.now(timezone.utc).isoformat(), nodes={})
    for i, n in enumerate(NODES):
        text = urllib.request.urlopen(f'http://127.0.0.1:{18081 + i}/metrics', timeout=10).read().decode()
        snap['nodes'][n] = parse(text)
    return snap


def idle(snap):
    return all(v['running'] == 0 and v['queued'] == 0 for v in snap['nodes'].values())


def wait_idle(limit=120):
    start = time.monotonic()
    while True:
        snap = snapshot()
        if idle(snap) or time.monotonic() - start > limit:
            return snap
        time.sleep(2)


def flush_caches():
    out = {}
    for n in NODES:
        out[n] = subprocess.run(['ssh', '-o', 'BatchMode=yes', f'Spark_{n}',
                                 'curl -s -m 30 -X POST 127.0.0.1:30000/flush_cache'],
                                capture_output=True, text=True, timeout=60).stdout.strip()[:200]
    return out


def delta(before, after):
    keys = [k for k in COUNTERS if k not in ('running', 'queued')]
    per = {n: {k: after['nodes'][n][k] - before['nodes'][n][k] for k in keys} for n in NODES}
    return dict(per_node=per, total={k: sum(per[n][k] for n in NODES) for k in keys})


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--arm', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--source', type=Path, default=ROOT / '.runtime' / 'xl-source')
    p.add_argument('--resume-from', type=Path)
    p.add_argument('--no-flush', action='store_true')
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('output exists')
    with fleet_lease.lease(ROOT, f"arms.py {plan['study']} {a.arm} -> {out}"):  # the fleet is this arm's until it has drained
        return run_arm(a, plan, out)


def run_arm(a, plan, out):
    admission = ROOT / '.runtime' / f"{plan['study']}-{a.arm}-ADMISSION.json".upper().replace('-', '_')
    adm = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(a.plan), '--source', str(a.source),
                          '--output', str(admission), '--note', f'arm {a.arm} of {plan["study"]}'],
                         capture_output=True, text=True)
    print(adm.stdout.strip(), flush=True)
    if adm.returncode:
        raise SystemExit('admission failed: ' + adm.stderr[-500:])
    flushed = {} if a.no_flush else flush_caches()
    before = wait_idle()
    if not idle(before):
        raise SystemExit('fleet not idle before the arm')
    command = [sys.executable, str(ROOT / 'run_variants.py'), '--plan', str(a.plan), '--output', str(out),
               '--source', str(a.source), '--admission', str(admission), '--run', '--policy', a.arm]
    if a.resume_from:
        command += ['--resume-from', str(a.resume_from.resolve())]
    start = time.monotonic()
    with open(str(out) + '.log', 'x') as log:
        code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
    wall = time.monotonic() - start
    after = wait_idle()
    try:
        joules = energy.window(before['utc'], after['utc'])
    except Exception as exc:  # energy is secondary; never lose the token accounting
        joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan), study=plan['study'], arm=a.arm,
                  output=str(out), runner_exit=code, runner_wall_seconds=round(wall, 1), admission=str(admission),
                  cache_flush=flushed, before=before, after=after, idle_after=idle(after),
                  server=delta(before, after), energy=joules, resumed_from=str(a.resume_from) if a.resume_from else None)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(arm=a.arm, exit=code, wall=round(wall), server=record['server']['total'],
                          energy_wh=joules.get('total_wh'))), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
