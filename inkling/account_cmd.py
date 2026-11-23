#!/usr/bin/env python3
"""Server-side accounting around ANY replay/screen command, the same as inkling/arms.py gives one run_variants arm.

Sequence: fresh admission (inkling/admit.py, idle fleet) -> prefix-cache flush on each node (every response must
report 'Cache flushed') -> server counters on all four nodes (every counter of arms.COUNTERS must be exported) on an
idle fleet -> CMD (cwd = repo root, stdout+stderr to OUTPUT.log) -> wait until every node is idle (drain limit) ->
counters again -> GPU energy for the window (inkling/energy.py). Writes OUTPUT/arm_accounting.json in the arms.py
schema (protocol 'swarm-arm-accounting-v1') plus 'command'. The command must be the only client of the fleet.

In CMD, '{admission}' is replaced by the admission receipt path and '{output}' by OUTPUT. OUTPUT must not exist
before the run (CMD may create it, e.g. closer_replay.py --output {output}); it is created after CMD if needed.
Exit: CMD's exit code; 3 if the drain timed out or counters were missing after CMD (the record is still written,
with 'accounting_error'); 2 (and CMD never runs) if admission, flush, idle or counters fail before it.

usage: account_cmd.py --plan PLAN --output DIR [--label NAME] [--source DIR] [--drain-seconds N] -- CMD ...
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
import arms  # noqa: E402
import energy  # noqa: E402

FLUSH_OK = 'Cache flushed'
DRAIN_SECONDS = 120


class AccountingError(RuntimeError):
    pass


def fetch_metrics(index):
    return urllib.request.urlopen(f'http://127.0.0.1:{18081 + index}/metrics', timeout=10).read().decode()


def missing_counters(text):
    """Counters of arms.COUNTERS (metric + label filter, matched exactly as arms.parse matches them) that no line
    of the exposition reports."""
    seen = set()
    for line in text.splitlines():
        m = re.match(r'^([^{\s]+)(\{[^}]*\})?\s+(\S+)', line)
        if not m or line.startswith('#'):
            continue
        for key, (name, label) in arms.COUNTERS.items():
            if m.group(1) == name and label in (m.group(2) or ''):
                seen.add(key)
    return sorted(set(arms.COUNTERS) - seen)


def snapshot():
    """arms.snapshot with a completeness check: every counter of arms.COUNTERS must be exported by every node
    (arms.parse would silently count a missing counter as 0)."""
    snap = dict(utc=datetime.now(timezone.utc).isoformat(), nodes={})
    for i, n in enumerate(arms.NODES):
        text = fetch_metrics(i)
        missing = missing_counters(text)
        if missing:
            raise AccountingError(f'node {n}: counters missing: {missing}')
        snap['nodes'][n] = arms.parse(text)
    return snap


def drain(limit):
    """Wait until every node is idle; AccountingError on timeout (never a silent partial window)."""
    start = time.monotonic()
    while True:
        snap = snapshot()
        if arms.idle(snap):
            return snap
        if time.monotonic() - start > limit:
            raise AccountingError(f'fleet not idle after {limit} s')
        time.sleep(2)


def flush_checked():
    out = arms.flush_caches()
    bad = {n: r for n, r in out.items() if not str(r).startswith(FLUSH_OK)}
    if bad or set(out) != set(arms.NODES):
        raise AccountingError(f'prefix-cache flush failed: {bad or out}')
    return out


def admit(plan_path, source, admission, note):
    run = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(plan_path), '--source', str(source),
                          '--output', str(admission), '--note', note], capture_output=True, text=True)
    print(run.stdout.strip(), flush=True)
    if run.returncode:
        raise AccountingError('admission failed: ' + run.stderr[-500:])


def run_command(command, log_path):
    with open(log_path, 'x') as log:
        return subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--' not in argv:
        raise SystemExit('usage: account_cmd.py --plan PLAN --output DIR [...] -- CMD ...')
    split = argv.index('--')
    own, command = argv[:split], argv[split + 1:]
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--label', help='name in the admission file and record (default: output directory name)')
    p.add_argument('--source', type=Path, default=ROOT / '.runtime' / 'xl-source')
    p.add_argument('--drain-seconds', type=int, default=DRAIN_SECONDS)
    a = p.parse_args(own)
    if not command:
        raise SystemExit('no command after --')
    plan = json.loads(a.plan.read_text())
    out = a.output.resolve()
    if out.exists() or Path(str(out) + '.log').exists():
        raise SystemExit('output or its log exists')
    label = a.label or out.name
    admission = ROOT / '.runtime' / f"{plan['study']}-{label}-ADMISSION.json".upper().replace('-', '_')
    command = [c.replace('{admission}', str(admission)).replace('{output}', str(out)) for c in command]
    try:
        admit(a.plan, a.source, admission, f'account_cmd {label} of {plan["study"]}')
        flushed = flush_checked()
        before = drain(a.drain_seconds)
    except AccountingError as exc:
        print(json.dumps(dict(error=str(exc), command_started=False)), flush=True)
        return 2
    start = time.monotonic()
    code = run_command(command, str(out) + '.log')
    wall = time.monotonic() - start
    error = after = None
    try:
        after = drain(a.drain_seconds)
    except AccountingError as exc:
        error = str(exc)
        try:  # keep whatever the fleet reports now, flagged as not idle / incomplete
            after = snapshot()
        except AccountingError as exc2:
            error += f'; {exc2}'
    joules = None
    if after is not None:
        try:
            joules = energy.window(before['utc'], after['utc'])
        except Exception as exc:  # energy is secondary; never lose the token accounting
            joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan), study=plan['study'], arm=label,
                  output=str(out), runner_exit=code, runner_wall_seconds=round(wall, 1), admission=str(admission),
                  cache_flush=flushed, before=before, after=after, idle_after=bool(after and arms.idle(after)),
                  server=arms.delta(before, after) if after is not None else None, energy=joules, resumed_from=None,
                  command=command)
    if error:
        record['accounting_error'] = error
    out.mkdir(parents=True, exist_ok=True)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(label=label, exit=code, wall=round(wall), accounting_error=error,
                          server=record['server']['total'] if record['server'] else None,
                          energy_wh=(joules or {}).get('total_wh'))), flush=True)
    return 3 if error and code == 0 else code


if __name__ == '__main__':
    raise SystemExit(main())
