#!/usr/bin/env python3
"""Run ONE arm of the frozen idea #5 A/B (CODING_SUSPEND_*_PLAN.json: judge-only coding, control vs hold_dispatch)
alone on the fleet, with inkling/coding_arms.py's accounting and a fenced fleet:

  fleet lease (inkling/fleet_lease.py) for the whole arm -> freeze checks (the plan is FROZEN and committed unchanged,
  its code pins match, the worker tree is clean at the plan's source revision) -> fresh admission (inkling/admit.py,
  idle fleet, receipt bound to this plan file) -> prefix-cache flush -> RAW sglang gauges present and zero on all four
  nodes (else no start) -> server counters -> run_coding_earlystop.py -> fenced drain (no time limit: the lease is
  released only after every node reports running = queued = 0 with both raw gauges present) -> counters again -> GPU
  energy for the window (inkling/energy.py) -> OUTPUT/arm_accounting.json.

SIGINT / SIGTERM only latch (no I/O in the handler): the runner is then terminated (no new agents; workers already
started finish their streams) and the fenced drain runs before the lease is released. Drain warnings that cannot be
written never escape the drain.

usage: suspend_arms.py --plan CODING_SUSPEND_<ARM>_PLAN.json --output runs/NAME
"""
import argparse
import hashlib
import json
import re
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import arms  # noqa: E402  (helpers only: flush_caches, parse, delta)
import energy  # noqa: E402
import fleet_lease  # noqa: E402

NODES = arms.NODES
RAW = ('sglang:num_running_reqs', 'sglang:num_queue_reqs')
SIGNALS = []


def on_signal(signum, frame):
    SIGNALS.append(signum)  # latch only


def git(tree, *args):
    return subprocess.run(['git', '-C', str(tree), *args], capture_output=True, text=True, check=True).stdout.strip()


def freeze_problem(plan_path, plan, root=ROOT):
    """None if the plan is FROZEN and committed unchanged, every code pin matches and the worker tree is clean at the
    plan's source revision."""
    if plan.get('status') != 'FROZEN':
        return 'plan is not FROZEN'
    try:
        path = Path(plan_path).resolve()
        top = Path(git(path.parent, 'rev-parse', '--show-toplevel'))
        rel = str(path.relative_to(top))
        if git(top, 'rev-parse', f'HEAD:{rel}') != git(top, 'hash-object', rel):
            return 'plan file differs from its committed version'
        source = Path(root) / plan['source_path']
        if git(source, 'rev-parse', 'HEAD') != plan['source_revision']:
            return 'the worker tree is not at the plan source revision'
        if git(source, 'status', '--porcelain', '--untracked-files=no'):
            return 'the worker tree has local changes'
    except (subprocess.CalledProcessError, ValueError, KeyError) as exc:
        return f'git check failed: {str(exc)[:200]}'
    for name, digest in (plan.get('code_sha256') or {}).items():
        p = Path(root) / name
        if not p.exists() or hashlib.sha256(p.read_bytes()).hexdigest() != digest:
            return f'{name} differs from its pin'
    if not plan.get('code_sha256'):
        return 'plan has no code pins'
    return None


def admission_problem(receipt, plan_path, plan, max_age=900):
    from datetime import datetime, timezone
    try:
        age = (datetime.now(timezone.utc) - datetime.fromisoformat(receipt['verified_utc'])).total_seconds()
    except (KeyError, TypeError, ValueError):
        return 'admission receipt unreadable'
    checks = [(receipt.get('verified') is True, 'admission not verified'),
              (receipt.get('allow_busy') is False, 'admission allowed a busy fleet'),
              (0 <= age <= max_age, 'admission receipt too old'),
              (receipt.get('plan_sha256') == hashlib.sha256(Path(plan_path).read_bytes()).hexdigest(),
               'admission is not bound to this plan file'),
              (receipt.get('source_revision') == plan.get('source_revision'), 'admission source revision differs')]
    return next((why for ok, why in checks if not ok), None)


def metrics_text(i):
    return urllib.request.urlopen(f'http://127.0.0.1:{18081 + i}/metrics', timeout=10).read().decode()


def snapshot(fetch=metrics_text):
    """Counters per node plus raw: both raw sglang gauges present on that node (arms.parse reads missing ones as 0)."""
    from datetime import datetime, timezone
    snap = dict(utc=datetime.now(timezone.utc).isoformat(), nodes={}, raw={})
    for i, n in enumerate(NODES):
        try:
            text = fetch(i)
        except Exception:
            snap['raw'][n] = False
            snap['nodes'][n] = None
            continue
        snap['nodes'][n] = arms.parse(text)
        snap['raw'][n] = all(re.search(rf'^{re.escape(name)}(\{{[^}}]*\}})?\s', text, re.M) for name in RAW)
    return snap


def idle(snap):
    return all(snap['raw'].get(n) and snap['nodes'][n] and snap['nodes'][n]['running'] == 0
               and snap['nodes'][n]['queued'] == 0 for n in NODES)


def drain(fetch=metrics_text, poll=2.0, warn_every=600):
    """Returns only when every node reports running = queued = 0 with both raw gauges present."""
    t0, warned = time.monotonic(), 0
    while True:
        snap = snapshot(fetch)
        if idle(snap):
            return snap, round(time.monotonic() - t0, 1)
        if time.monotonic() - t0 >= (warned + 1) * warn_every:
            warned += 1
            try:
                print(json.dumps(dict(warning='fleet not idle yet; the lease stays held', raw=snap['raw'])),
                      flush=True)
            except Exception:
                pass
        time.sleep(poll)


def main(argv=None, fetch=metrics_text, popen=subprocess.Popen):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('output exists')
    problem = freeze_problem(a.plan, plan)
    if problem:
        raise SystemExit(problem)
    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    with fleet_lease.lease(ROOT, f"suspend_arms.py {plan['study']} -> {out}"):
        return run_arm(a, plan, out, fetch, popen)


def run_arm(a, plan, out, fetch, popen):
    source = ROOT / plan['source_path']
    admission = ROOT / '.runtime' / (plan['study'].upper().replace('-', '_') + '_ADMISSION.json')
    adm = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(a.plan), '--source', str(source),
                          '--output', str(admission), '--note', f'suspend A/B arm {plan["study"]}'],
                         capture_output=True, text=True)
    if adm.returncode or not admission.exists():
        raise SystemExit('admission failed: ' + adm.stderr[-500:])
    problem = admission_problem(json.loads(admission.read_text()), a.plan, plan)
    if problem:
        raise SystemExit(problem)
    flushed = arms.flush_caches()
    before = snapshot(fetch)
    if not idle(before):
        raise SystemExit(f'fleet not idle (or raw gauges missing) before the arm: {before["raw"]}')
    command = [sys.executable, str(ROOT / 'run_coding_earlystop.py'), '--plan', str(a.plan), '--output', str(out),
               '--source', str(source), '--admission', str(admission), '--run']
    start, runner, code = time.monotonic(), None, None
    try:
        with open(str(out) + '.log', 'x') as log:
            runner = popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            stopped = False
            while runner.poll() is None:
                if SIGNALS and not stopped:
                    stopped = True
                    runner.terminate()  # no new agents; started workers finish, then the drain confirms idle
                time.sleep(1)
            code = runner.returncode
    finally:
        wall = time.monotonic() - start
        if runner is not None and runner.poll() is None:
            runner.terminate()  # an exception here: stop new starts, then drain before the lease is released
        after, waited = drain(fetch)  # also on an exception: the lease stays held until idle is confirmed
    out.mkdir(parents=True, exist_ok=True)
    try:
        joules = energy.window(before['utc'], after['utc'])
    except Exception as exc:  # energy is secondary to the token accounting, but the A/B report requires it
        joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan),
                  plan_sha256=hashlib.sha256(a.plan.read_bytes()).hexdigest(), study=plan['study'],
                  runner='run_coding_earlystop.py', output=str(out), runner_exit=code,
                  runner_wall_seconds=round(wall, 1),
                  admission=str(admission), cache_flush=flushed, before=before, after=after, idle_after=idle(after),
                  drain_confirmed=idle(after), drain_waited_seconds=waited, signals=list(SIGNALS),
                  stopped_by_signal=bool(SIGNALS), server=arms.delta(before, after), energy=joules)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(study=plan['study'], exit=code, wall=round(wall), server=record['server']['total'],
                          energy_wh=joules.get('total_wh'))), flush=True)
    return code or int(bool(SIGNALS))


if __name__ == '__main__':
    raise SystemExit(main())
