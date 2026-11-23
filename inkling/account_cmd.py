#!/usr/bin/env python3
"""Server-side accounting around ANY replay/screen command, the same as inkling/arms.py gives one run_variants arm,
with stricter checks (arms.py itself stays unchanged: finished studies pin its hash).

Sequence: fresh admission (inkling/admit.py, idle fleet) -> prefix-cache flush on each node (own ssh call: ssh exit
status 0, HTTP 2xx from `curl -f`, body exactly SGLang's recorded success text) -> server counters on all four nodes on an idle fleet ->
CMD (exec list, no shell; cwd = repo root; stdout+stderr to OUTPUT.log) -> wait until every node is idle (an idle
sample counts only if it was taken before the drain deadline) -> counters again -> GPU energy for the window
(inkling/energy.py). Writes OUTPUT/arm_accounting.json in the arms.py schema (protocol 'swarm-arm-accounting-v1')
plus 'command', and on any fault 'accounting_error' / 'energy_error'. The command must be the only client.

Counters: every counter of arms.COUNTERS must be exported by every node (label filters matched as arms.parse does),
finite, and no cumulative counter may decrease over the window (a reset makes the window unusable).
CMD must be a real program or script: no shell (sh, bash, zsh, dash, ... also via env) and no interpreter with inline
code (python -c, perl -e, ...); an interpreter needs an existing script file. CMD argv elements that are exactly
'{admission}' or '{output}' are replaced by the receipt path / OUTPUT; any other
occurrence of a placeholder is refused. OUTPUT must be a new path under runs/; the receipt
.runtime/<STUDY>_<LABEL>_ADMISSION.JSON must not exist yet (study and label: letters, digits, '.', '_', '-').

Exit: 2 if admission, flush or the first snapshot fails (CMD never runs; a record is still written); otherwise CMD's
exit code if non-zero; else 3 for a counter/metrics/drain fault after CMD; else 4 if GPU energy is missing for the
window or for any node; else 0.

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh
exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter
reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after
its limit without failing, and an energy failure does not change the exit code.

usage: account_cmd.py --plan PLAN --output runs/NAME [--label NAME] [--source DIR] [--drain-seconds N] -- CMD ...
"""
import argparse
import json
import math
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

# SGLang's /flush_cache success body, exactly as recorded by every finished arm (runs/*/arm_accounting.json,
# cache_flush); any other body (e.g. 'Cache flushed.' + 'Operation was skipped.') is a failed flush
FLUSH_OK = ('Cache flushed.\nPlease check backend logs for more details. (When there are running or waiting requests, '
            'the operation will not be performed.)')
SHELLS = {'sh', 'bash', 'zsh', 'dash', 'ksh', 'fish', 'csh', 'tcsh', 'ash', 'busybox'}
INLINE = {'python': ('-c', '-'), 'perl': ('-e', '-E'), 'ruby': ('-e',), 'node': ('-e', '--eval', '-p', '--print')}
DRAIN_SECONDS = 120
MIN_ENERGY_COVERAGE = 0.9
PLACEHOLDERS = ('{admission}', '{output}')
SAFE_NAME = re.compile(r'^[A-Za-z0-9._-]+$')
FLUSH_REMOTE = 'curl -sS -f -m 30 -w "\\n%{http_code}" -X POST 127.0.0.1:30000/flush_cache'


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
    """arms.snapshot with checks: transport and parse errors, missing and non-finite counters raise AccountingError."""
    snap = dict(utc=datetime.now(timezone.utc).isoformat(), nodes={})
    for i, n in enumerate(arms.NODES):
        try:
            text = fetch_metrics(i)
            values = arms.parse(text)
        except Exception as exc:
            raise AccountingError(f'node {n}: metrics unavailable: {type(exc).__name__}: {exc}') from exc
        missing = missing_counters(text)
        if missing:
            raise AccountingError(f'node {n}: counters missing: {missing}')
        bad = sorted(k for k, x in values.items() if not math.isfinite(x))
        if bad:
            raise AccountingError(f'node {n}: non-finite counters: {bad}')
        snap['nodes'][n] = values
    return snap


def drain(limit):
    """Wait until every node is idle. Only a snapshot completed before the deadline counts; AccountingError otherwise."""
    deadline = time.monotonic() + limit
    while True:
        snap = snapshot()
        if time.monotonic() > deadline:
            raise AccountingError(f'fleet not idle within {limit} s')
        if arms.idle(snap):
            return snap
        time.sleep(2)


def checked_delta(before, after):
    """arms.delta, refusing a negative delta (counter reset or wrong node) and non-finite values."""
    d = arms.delta(before, after)
    bad = sorted(f'{n}.{k}' for n, per in d['per_node'].items() for k, x in per.items() if not math.isfinite(x) or x < 0)
    if bad:
        raise AccountingError(f'negative or non-finite counter deltas (counter reset?): {bad}')
    return d


def ssh(node, remote):
    return subprocess.run(['ssh', '-o', 'BatchMode=yes', f'Spark_{node}', remote], capture_output=True, text=True,
                          timeout=60)


def flush_checked():
    """Prefix-cache flush on every node with the ssh exit status, the HTTP status (curl -f) and the body checked."""
    out, bad = {}, {}
    for n in arms.NODES:
        try:
            res = ssh(n, FLUSH_REMOTE)
        except Exception as exc:
            bad[n] = f'{type(exc).__name__}: {exc}'
            continue
        body, _, status = res.stdout.rstrip('\n').rpartition('\n')
        out[n] = dict(exit=res.returncode, http_status=status.strip(), body=body.rstrip()[:1000])
        if res.returncode != 0 or not re.fullmatch(r'2\d\d', status.strip()) or body.rstrip() != FLUSH_OK:
            bad[n] = dict(out[n], stderr=res.stderr.strip()[:200])
    if bad:
        raise AccountingError(f'prefix-cache flush failed: {bad}')
    return out


def admit(plan_path, source, admission, note):
    run = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(plan_path), '--source', str(source),
                          '--output', str(admission), '--note', note], capture_output=True, text=True)
    print(run.stdout.strip(), flush=True)
    if run.returncode:
        raise AccountingError('admission failed: ' + run.stderr[-500:])


def run_command(command, log_path):
    with open(log_path, 'x') as log:
        return subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, shell=False).returncode


def check_command(command, root):
    """Only real programs or scripts: no shell (directly or via env), no interpreter running inline code; an
    interpreter's first non-option argument must be an existing script file (python -m MODULE is allowed)."""
    argv = list(command)
    if argv and Path(argv[0]).name == 'env':
        argv = argv[1:]
        while argv and (argv[0].startswith('-') or '=' in argv[0]):
            argv = argv[1:]
    if not argv:
        raise SystemExit('empty command')
    name = Path(argv[0]).name
    if name in SHELLS:
        raise SystemExit(f'shell commands are not allowed: {name}')
    family = next((k for k in INLINE if re.fullmatch(re.escape(k) + r'[0-9.]*', name)), None)
    if family is None:
        return
    for i, arg in enumerate(argv[1:], 1):
        if arg in INLINE[family] or (family == 'python' and re.fullmatch(r'-[A-Za-z]*c', arg)):
            raise SystemExit(f'inline code is not allowed: {name} {arg}')
        if family == 'python' and arg == '-m':
            return
        if not arg.startswith('-'):
            script = Path(arg) if Path(arg).is_absolute() else root / arg
            if not script.is_file():
                raise SystemExit(f'script not found: {arg}')
            return
    raise SystemExit(f'{name} without a script path')


def substitute(command, admission, out):
    """Whole-element placeholder substitution only (exec list, no shell)."""
    result = []
    for arg in command:
        if arg == '{admission}':
            result.append(str(admission))
        elif arg == '{output}':
            result.append(str(out))
        elif any(ph in arg for ph in PLACEHOLDERS):
            raise SystemExit(f'placeholder must be a whole argument: {arg!r}')
        else:
            result.append(arg)
    return result


def energy_fault(joules):
    if not isinstance(joules, dict) or 'error' in joules:
        return f"energy unavailable: {(joules or {}).get('error') if isinstance(joules, dict) else joules}"
    nodes = joules.get('nodes') or {}
    bad = sorted(n for n in arms.NODES if not (nodes.get(n) or {}).get('joules')
                 or (nodes[n].get('coverage') or 0) < MIN_ENERGY_COVERAGE)
    return f'energy samples missing or incomplete on nodes {bad}' if bad else None


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if '--' not in argv:
        raise SystemExit('usage: account_cmd.py --plan PLAN --output runs/NAME [...] -- CMD ...')
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
    out = (a.output if a.output.is_absolute() else ROOT / a.output).resolve()
    runs = (ROOT / 'runs').resolve()
    if runs not in out.parents:
        raise SystemExit(f'output must be under {runs}')
    if out.exists() or Path(str(out) + '.log').exists():
        raise SystemExit('output or its log exists')
    label = a.label or out.name
    if not (SAFE_NAME.match(str(plan.get('study', ''))) and SAFE_NAME.match(label)):
        raise SystemExit('study and label must be letters, digits, ".", "_" or "-"')
    (ROOT / '.runtime').mkdir(parents=True, exist_ok=True)  # admit.py writes the receipt there
    admission = ROOT / '.runtime' / f"{plan['study']}-{label}-ADMISSION.json".upper().replace('-', '_')
    if admission.exists() or admission.resolve().parent != (ROOT / '.runtime').resolve():
        raise SystemExit(f'admission receipt exists or escapes .runtime: {admission}')
    check_command(command, ROOT)
    command = substitute(command, admission, out)
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan), study=plan['study'], arm=label, output=str(out),
                  runner_exit=None, runner_wall_seconds=None, admission=str(admission), cache_flush=None, before=None,
                  after=None, idle_after=False, server=None, energy=None, resumed_from=None, command=command)

    def finish(code):
        out.mkdir(parents=True, exist_ok=True)
        (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
        print(json.dumps(dict(label=label, exit=code, runner_exit=record['runner_exit'],
                              accounting_error=record.get('accounting_error'), energy_error=record.get('energy_error'),
                              server=(record['server'] or {}).get('total'),
                              energy_wh=(record['energy'] or {}).get('total_wh') if isinstance(record['energy'], dict)
                              else None)), flush=True)
        return code
    try:
        admit(a.plan, a.source, admission, f'account_cmd {label} of {plan["study"]}')
        record['cache_flush'] = flush_checked()
        record['before'] = drain(a.drain_seconds)
    except AccountingError as exc:
        record.update(accounting_error=str(exc), command_started=False)
        return finish(2)
    start = time.monotonic()
    code = run_command(command, str(out) + '.log')
    record.update(runner_exit=code, runner_wall_seconds=round(time.monotonic() - start, 1))
    try:
        record['after'] = drain(a.drain_seconds)
        record['idle_after'] = True
        record['server'] = checked_delta(record['before'], record['after'])
    except AccountingError as exc:
        record['accounting_error'] = str(exc)
        if record['after'] is None:
            try:  # keep what the fleet reports now, flagged by accounting_error
                record['after'] = snapshot()
                record['idle_after'] = arms.idle(record['after'])
            except AccountingError as exc2:
                record['accounting_error'] += f'; {exc2}'
    end = (record['after'] or {}).get('utc') or datetime.now(timezone.utc).isoformat()
    try:
        record['energy'] = energy.window(record['before']['utc'], end)
    except Exception as exc:  # energy is secondary to tokens, but its absence must never look like success
        record['energy'] = dict(error=f'{type(exc).__name__}: {exc}')
    fault = energy_fault(record['energy'])
    if fault:
        record['energy_error'] = fault
    return finish(code if code else 3 if record.get('accounting_error') else 4 if fault else 0)


if __name__ == '__main__':
    raise SystemExit(main())
