#!/usr/bin/env python3
"""Run ONE arm of the frozen live differential-gate A/B (CODING_DIFFGATE_CONTROL_PLAN.json /
CODING_DIFFGATE_GATE_PLAN.json) alone on the fleet with the reviewed controls of inkling/suspend_arms.py: fleet lease,
freeze and code-pin checks, fresh admission bound to the plan file, cache flush, RAW sglang gauges present and zero on
every node before the start, the arm's runner (plan.runner: run_coding_earlystop.py for the control,
run_coding_diffgate.py for the gate), fenced drain (no time limit) before the lease is released, GPU energy for the
window, OUTPUT/arm_accounting.json. SIGINT / SIGTERM only latch; a latch before the launch starts nothing; after the
launch the runner gets SIGTERM, stops admissions, terminates and reaps its workers and generator processes, and is
waited for before the drain. After the drain, every fleet host is swept until no sandbox container with the sandbox
owner label is left (verified; an unreachable host is retried), and only then is the lease released.

usage: diffgate_arms.py --plan CODING_DIFFGATE_<ARM>_PLAN.json --output runs/NAME
"""
import argparse
import hashlib
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import sandbox_outputs  # noqa: E402
import suspend_arms as sa  # noqa: E402  (the reviewed fleet controls)

RUNNERS = ('run_coding_earlystop.py', 'run_coding_diffgate.py')
CANONICAL = [f'http://127.0.0.1:{p}/v1' for p in range(18081, 18085)]


def sweep_until_clean(sweep=None, poll=10.0, warn_every=600):
    """Sweep every fleet host until each reports 0 sandbox containers left; returns the rounds' results."""
    sweep = sweep or sandbox_outputs.sweep
    rounds, t0, warned = [], time.monotonic(), 0
    while True:
        left = sweep()
        rounds.append(left)
        if left and all(v == 0 for v in left.values()):
            return dict(rounds=len(rounds), last=left)
        if time.monotonic() - t0 >= (warned + 1) * warn_every:
            warned += 1
            try:
                print(json.dumps(dict(warning='sandbox containers left; the lease stays held', left=left)), flush=True)
            except Exception:
                pass
        time.sleep(poll)


def main(argv=None, fetch=sa.metrics_text, popen=subprocess.Popen):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('output exists')
    if plan.get('runner') not in RUNNERS:
        raise SystemExit(f'unknown runner {plan.get("runner")!r}')
    problem = sa.freeze_problem(a.plan, plan)
    if problem:
        raise SystemExit(problem)
    signal.signal(signal.SIGINT, sa.on_signal)
    signal.signal(signal.SIGTERM, sa.on_signal)
    with sa.fleet_lease.lease(ROOT, f"diffgate_arms.py {plan['study']} -> {out}"):
        return run_arm(a, plan, out, fetch, popen)


def run_arm(a, plan, out, fetch, popen):
    source = ROOT / plan['source_path']
    admission = ROOT / '.runtime' / (plan['study'].upper().replace('-', '_') + '_ADMISSION.json')
    adm = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(a.plan), '--source', str(source),
                          '--output', str(admission), '--note', f'diff gate A/B arm {plan["study"]}'],
                         capture_output=True, text=True)
    if adm.returncode or not admission.exists():
        raise SystemExit('admission failed: ' + adm.stderr[-500:])
    receipt = json.loads(admission.read_text())
    problem = sa.admission_problem(receipt, a.plan, plan)
    if problem is None and receipt.get('endpoints') != CANONICAL:
        problem = 'admission endpoints are not the canonical fleet'
    if problem:
        raise SystemExit(problem)
    if sa.SIGNALS:
        raise SystemExit('signal before the launch: nothing started')
    flushed = sa.arms.flush_caches()
    before = sa.snapshot(fetch)
    if not sa.idle(before):
        raise SystemExit(f'fleet not idle (or raw gauges missing) before the arm: {before["raw"]}')
    command = [sys.executable, str(ROOT / plan['runner']), '--plan', str(a.plan), '--output', str(out),
               '--source', str(source), '--admission', str(admission), '--run']
    if sa.SIGNALS:
        raise SystemExit('signal before the launch: nothing started')
    start, runner, code = time.monotonic(), None, None
    try:
        with open(str(out) + '.log', 'x') as log:
            runner = popen(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT)
            stopped = False
            while runner.poll() is None:
                if sa.SIGNALS and not stopped:
                    stopped = True
                    runner.terminate()  # the runner stops admissions, terminates and reaps its workers, then exits
                time.sleep(1)
            code = runner.returncode
    finally:
        wall = time.monotonic() - start
        if runner is not None and runner.poll() is None:
            runner.terminate()
        if runner is not None:
            runner.wait()  # every owned worker is reaped before the drain samples the fleet
        after, waited = sa.drain(fetch)  # also on an exception: the lease stays held until idle is confirmed
        swept = sweep_until_clean()  # no owned sandbox container outlives the lease
    out.mkdir(parents=True, exist_ok=True)
    try:
        joules = sa.energy.window(before['utc'], after['utc'])
    except Exception as exc:
        joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan),
                  plan_sha256=hashlib.sha256(a.plan.read_bytes()).hexdigest(), study=plan['study'],
                  runner=plan['runner'], output=str(out), runner_exit=code, runner_wall_seconds=round(wall, 1),
                  admission=str(admission), cache_flush=flushed, before=before, after=after, idle_after=sa.idle(after),
                  drain_confirmed=sa.idle(after), drain_waited_seconds=waited, signals=list(sa.SIGNALS),
                  stopped_by_signal=bool(sa.SIGNALS), sandbox_sweep=swept, server=sa.arms.delta(before, after),
                  energy=joules)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(study=plan['study'], exit=code, wall=round(wall), server=record['server']['total'],
                          energy_wh=joules.get('total_wh'))), flush=True)
    return code or int(bool(sa.SIGNALS))


if __name__ == '__main__':
    raise SystemExit(main())
