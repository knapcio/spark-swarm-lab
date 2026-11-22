#!/usr/bin/env python3
"""Run an arithmetic swarm (run_variants.py, one policy) and a coding swarm (run_coding_earlystop.py) CONCURRENTLY on the
Inkling fleet, with one accounting window: fresh admission, prefix-cache flush, server counters on all four nodes, both
runners started together, wait for both, idle wait, counters again, GPU energy. Writes OUTPUT/arm_accounting.json.
The per-runner concurrency comes from each plan (they must sum to <= 25 client requests per node).

usage: mixed_arms.py --arith-plan PLAN --arm POLICY --coding-plan PLAN --output runs/NAME
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
import arms  # noqa: E402  (helpers only)
import energy  # noqa: E402


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--arith-plan', type=Path, required=True)
    p.add_argument('--arm', required=True)
    p.add_argument('--coding-plan', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    ap, cp = json.loads(a.arith_plan.read_text()), json.loads(a.coding_plan.read_text())
    out = a.output.resolve()
    if out.exists():
        raise SystemExit('output exists')
    out.mkdir(parents=True)
    xl, cs = ROOT / '.runtime' / 'xl-source', ROOT / cp['source_path']
    adm = {}
    for name, plan, src in (('arith', a.arith_plan, xl), ('coding', a.coding_plan, cs)):
        path = ROOT / '.runtime' / (json.loads(plan.read_text())['study'].upper().replace('-', '_') + '_ADMISSION.json')
        r = subprocess.run([sys.executable, str(HERE / 'admit.py'), '--plan', str(plan), '--source', str(src), '--output', str(path),
                            '--note', f'mixed arm {out.name} ({name})'], capture_output=True, text=True)
        print(name, r.stdout.strip(), flush=True)
        if r.returncode:
            raise SystemExit('admission failed: ' + r.stderr[-500:])
        adm[name] = path
    flushed = arms.flush_caches()
    before = arms.wait_idle()
    if not arms.idle(before):
        raise SystemExit('fleet not idle before the arm')
    ao, co = out / 'arith', out / 'coding'
    cmds = {'arith': [sys.executable, str(ROOT / 'run_variants.py'), '--plan', str(a.arith_plan), '--output', str(ao), '--source', str(xl),
                      '--admission', str(adm['arith']), '--run', '--policy', a.arm],
            'coding': [sys.executable, str(ROOT / 'run_coding_earlystop.py'), '--plan', str(a.coding_plan), '--output', str(co),
                       '--source', str(cs), '--admission', str(adm['coding']), '--run']}
    start = time.monotonic()
    procs, logs, ends = {}, {}, {}
    for name, cmd in cmds.items():
        logs[name] = open(str(out) + f'-{name}.log', 'x')
        procs[name] = subprocess.Popen(cmd, cwd=ROOT, stdout=logs[name], stderr=subprocess.STDOUT)
    while len(ends) < len(procs):
        for name, proc in procs.items():
            if name not in ends and proc.poll() is not None:
                ends[name] = dict(exit=proc.returncode, wall=round(time.monotonic() - start, 1))
                print(json.dumps({name: ends[name]}), flush=True)
        time.sleep(5)
    wall = time.monotonic() - start
    after = arms.wait_idle()
    try:
        joules = energy.window(before['utc'], after['utc'])
    except Exception as exc:
        joules = dict(error=f'{type(exc).__name__}: {exc}')
    record = dict(protocol='swarm-mixed-accounting-v1', arith_plan=str(a.arith_plan), coding_plan=str(a.coding_plan), arm=a.arm,
                  output=str(out), runners=ends, runner_wall_seconds=round(wall, 1), admissions={k: str(v) for k, v in adm.items()},
                  cache_flush=flushed, before=before, after=after, idle_after=arms.idle(after), server=arms.delta(before, after), energy=joules)
    (out / 'arm_accounting.json').write_text(json.dumps(record, indent=1) + '\n')
    print(json.dumps(dict(exit=max(e['exit'] for e in ends.values()), wall=round(wall), server=record['server']['total'],
                          energy_wh=joules.get('total_wh'))), flush=True)
    return max(e['exit'] for e in ends.values())


if __name__ == '__main__':
    raise SystemExit(main())
