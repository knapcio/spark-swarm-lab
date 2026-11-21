#!/usr/bin/env python3
"""Run ONE coding arm alone on the Inkling fleet with the same server-side accounting as inkling/arms.py:
fresh admission (inkling/admit.py), prefix-cache flush, server counters on all four nodes, the coding runner
(run_coding_agents.py for the run-to-the-end baseline, run_coding_earlystop.py for early stop), idle wait,
counters again, GPU energy. Writes OUTPUT/arm_accounting.json.

usage: coding_arms.py --plan PLAN --output runs/NAME
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import arms  # noqa: E402  (helpers only; arms.py itself is unchanged)
import energy  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('output exists')
    source = ROOT / plan['source_path']
    runner = 'run_coding_earlystop.py' if plan.get('early_stop') else 'run_coding_agents.py'
    admission = ROOT / '.runtime' / (plan['study'].upper().replace('-', '_') + '_ADMISSION.json')
    adm = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(a.plan), '--source', str(source),
                          '--output', str(admission), '--note', f'coding arm {plan["study"]}'], capture_output=True, text=True)
    print(adm.stdout.strip(), flush=True)
    if adm.returncode:
        raise SystemExit('admission failed: ' + adm.stderr[-500:])
    flushed = arms.flush_caches()
    before = arms.wait_idle()
    if not arms.idle(before):
        raise SystemExit('fleet not idle before the arm')
    command = [sys.executable, str(ROOT / runner), '--plan', str(a.plan), '--output', str(out), '--source', str(source),
               '--admission', str(admission), '--run']
    start = time.monotonic()
    with open(str(out) + '.log', 'x') as log:
        code = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT).returncode
    wall = time.monotonic() - start
    after = arms.wait_idle()
    try:
        joules = energy.window(before['utc'], after['utc'])
    except Exception as exc:
        joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-arm-accounting-v1', plan=str(a.plan), study=plan['study'], runner=runner, output=str(out),
                  runner_exit=code, runner_wall_seconds=round(wall, 1), admission=str(admission), cache_flush=flushed,
                  before=before, after=after, idle_after=arms.idle(after), server=arms.delta(before, after), energy=joules)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(study=plan['study'], exit=code, wall=round(wall), server=record['server']['total'],
                          energy_wh=joules.get('total_wh'))), flush=True)
    return code


if __name__ == '__main__':
    raise SystemExit(main())
