#!/usr/bin/env python3
"""Audit (offline, read-only): how many ACCEPTED arithmetic answers of recent runs flip to wrong under the strict
exact verifier (inkling/strict_verify.py: every submitted move must be legal), compared with the lenient rule the
reports used (direct_solver.replay_plan: target reached before the first illegal move is credited).

Runs: runs/swarm-*-hard1*, runs/swarm-*-hard2*, runs/swarm-baseline-hard26* (cases.jsonl: agents with verdict true,
numbers and target from the run's corpus) and runs/collab-s1-v1, runs/collab-s1-v2 (records.jsonl: accepted
submissions, numbers and target from the embedded plan's cases). The old reports are not changed.

usage: audit_strict_verifier.py [--runs-root runs] [--out results/audit-strict-verifier]
"""
import argparse
import glob
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import strict_verify as sv  # noqa: E402

PATTERNS = ('swarm-*-hard1*', 'swarm-*-hard2*', 'swarm-baseline-hard26*')
COLLAB = ('collab-s1-v1', 'collab-s1-v2')


def read_jsonl(path):
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def swarm_run(d, root):
    meta = json.loads((d / 'metadata.json').read_text())
    plan = meta.get('protocol') or meta.get('plan') or {}
    data = json.loads((Path(root) / plan['dataset']).read_text())
    tasks = {t['id']: t for t in data['tasks']}
    accepted = []
    for row in read_jsonl(d / 'cases.jsonl'):
        task = tasks.get(row.get('task_id'))
        for a in row.get('agents') or []:
            if a.get('verdict') is True and task is not None:
                accepted.append((f"{row['task_id']}-s{row.get('seed')}-a{a.get('slot')}", task['numbers'],
                                 task['target'], a.get('plan')))
    return accepted


def collab_run(d):
    meta = json.loads((d / 'metadata.json').read_text())
    cases = {c['case_id']: c for c in meta['plan']['cases']}
    accepted = []
    for rec in read_jsonl(d / 'records.jsonl'):
        case = cases.get(rec.get('case_id'))
        for i, s in enumerate(rec.get('submissions') or []):
            if s.get('accepted') is True and case is not None:
                accepted.append((f"{rec['case_id']}-{rec.get('arm')}-a{rec.get('slot')}-{i}", case['numbers'],
                                 case['target'], s.get('parsed')))
    return accepted


def audit(runs_root, root):
    runs_root = Path(runs_root)
    dirs = sorted({Path(p) for pat in PATTERNS for p in glob.glob(str(runs_root / pat)) if Path(p).is_dir()})
    dirs += [runs_root / c for c in COLLAB if (runs_root / c).is_dir()]
    table, total = [], dict(accepted=0, lenient_solved=0, strict_solved=0, flips=0)
    for d in dirs:
        try:
            items = collab_run(d) if d.name in COLLAB else swarm_run(d, root)
        except (OSError, KeyError, ValueError) as exc:
            table.append(dict(run=d.name, error=f'{type(exc).__name__}: {exc}'[:200]))
            continue
        row = dict(run=d.name, accepted=len(items), lenient_solved=0, strict_solved=0, flips=0, flipped=[])
        for key, numbers, target, plan in items:
            lenient, strict = sv.lenient_solved(numbers, target, plan), sv.strict_solved(numbers, target, plan)
            row['lenient_solved'] += lenient
            row['strict_solved'] += strict
            if lenient and not strict:
                row['flips'] += 1
                row['flipped'].append(key)
        for k in total:
            total[k] += row[k]
        table.append(row)
    return dict(runs=table, total=total)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs-root', type=Path, default=ROOT / 'runs')
    p.add_argument('--root', type=Path, default=ROOT, help='repository with datasets/')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'audit-strict-verifier')
    a = p.parse_args(argv)
    r = audit(a.runs_root, a.root)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    for row in r['runs']:
        print(json.dumps({k: v for k, v in row.items() if k != 'flipped'}))
    print(json.dumps(dict(total=r['total'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
