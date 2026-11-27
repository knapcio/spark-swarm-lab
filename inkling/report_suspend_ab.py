#!/usr/bin/env python3
"""Report of the idea #5 live A/B (CODING_SUSPEND_CONTROL_PLAN.json vs CODING_SUSPEND_HOLD_PLAN.json), with the frozen
rule: PASS only if wrong(hold) <= wrong(control), solved(hold) >= solved(control) - 1 and GPU Wh per solved case of the
hold arm <= 0.90 x control; otherwise STOP. INCOMPLETE (no decision) unless both arms are complete: the run embeds its
plan, the two plans differ only in their arm fields, no runner errors, the source did not change, the cases are exactly
the frozen task x seed keys (the plan's tasks file, checked against its sha256), the runner exited 0, the drain was
confirmed, no signal stopped the arm, and energy covers exactly the four nodes (coverage >= MIN_COVERAGE each). Wh per
solved case is compared before any rounding.

usage: report_suspend_ab.py --control PLAN --hold PLAN [--control-run runs/...] [--hold-run runs/...] [--out DIR]
"""
import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARM_FIELDS = ('study', 'ab_arm', 'suspend_siblings', 'execution')
MIN_COVERAGE = 0.9
NODES = ('01', '02', '03', '04')


def expected_keys(plan, root):
    """The frozen (task_id, seed) keys: the plan's tasks file (sha256-checked), its split, times its seeds."""
    m = plan['matrix']
    path = Path(root) / m['tasks']
    if not path.exists() or hashlib.sha256(path.read_bytes()).hexdigest() != m['tasks_sha256']:
        return None
    tasks = [t['id'] for t in json.loads(path.read_text())['tasks'] if t['split'] == m['split']]
    if len(tasks) != m['tasks_count']:
        return None
    return {(t, s) for t in tasks for s in m['seeds']}
ENERGY_RATIO, SOLVED_SLACK = 0.90, 1


def arm_view(plan):
    return {k: v for k, v in plan.items() if k not in ARM_FIELDS}


def load(run_dir):
    run_dir = Path(run_dir)

    def read(name):
        return json.loads((run_dir / name).read_text()) if (run_dir / name).exists() else None
    return read('metadata.json') or {}, read('cases.json'), read('arm_accounting.json') or {}


def arm_problems(arm, plan, meta, cases, acct, root):
    out = []
    if meta.get('protocol') != plan:
        out.append(f'{arm}: the run does not embed its plan')
    if meta.get('errors'):
        out.append(f"{arm}: runner errors {meta['errors'][:2]}")
    if meta.get('source_changed_during_run'):
        out.append(f'{arm}: the source changed during the run')
    expected = expected_keys(plan, root)
    keys = [(c.get('task_id'), c.get('seed')) for c in (cases or [])]
    if expected is None:
        out.append(f'{arm}: the frozen tasks file is missing or differs from its sha256')
    elif cases is None or len(keys) != len(set(keys)) or set(keys) != expected:
        out.append(f'{arm}: cases are not exactly the {len(expected)} frozen task x seed keys '
                   f'({len(set(keys) & expected)} matching, {len(set(keys) - expected)} extra)')
    if acct.get('runner_exit') != 0:
        out.append(f"{arm}: runner exit {acct.get('runner_exit')}")
    if acct.get('drain_confirmed') is not True:
        out.append(f'{arm}: drain not confirmed')
    if acct.get('stopped_by_signal'):
        out.append(f'{arm}: stopped by a signal')
    energy = acct.get('energy') or {}
    nodes = energy.get('nodes') or {}
    if not isinstance(energy.get('total_wh'), (int, float)) or set(nodes) != set(NODES) or any(
            not isinstance((nodes[n] or {}).get('coverage'), (int, float)) or nodes[n]['coverage'] < MIN_COVERAGE
            for n in NODES):
        out.append(f'{arm}: energy not covered on all four nodes')
    return out


def arm_metrics(cases, acct, meta):
    solved = sum(bool(c['solved']) for c in cases)
    answered = sum(bool(c['answered']) for c in cases)
    wh = acct['energy']['total_wh']
    total = (acct.get('server') or {}).get('total') or {}
    return dict(cases=len(cases), solved=solved, answered=answered, wrong=answered - solved, energy_wh=wh,
                wh_per_solved=(wh / solved) if solved else None,
                server_generation_tokens=total.get('generation_tokens'), server_requests=total.get('requests'),
                runner_wall_seconds=acct.get('runner_wall_seconds'), holds=meta.get('holds'))


def build(control_plan, hold_plan, control_run, hold_run, root=ROOT):
    problems = []
    if arm_view(control_plan) != arm_view(hold_plan):
        problems.append('the two plans differ beyond their arm fields')
    if control_plan.get('suspend_siblings') is not None or hold_plan.get('suspend_siblings') != 'hold_dispatch':
        problems.append('arm fields wrong (control without, hold with suspend_siblings = hold_dispatch)')
    loaded = {}
    for arm, plan, run in (('control', control_plan, control_run), ('hold', hold_plan, hold_run)):
        meta, cases, acct = load(run)
        problems += arm_problems(arm, plan, meta, cases, acct, root)
        loaded[arm] = (meta, cases, acct)
    out = dict(study=control_plan.get('study_group'), control_run=str(control_run), hold_run=str(hold_run),
               rule=control_plan.get('decision_rule'))
    if problems:
        return dict(out, status='incomplete', problems=problems[:20], decision='INCOMPLETE (no decision)')
    m = {arm: arm_metrics(cases, acct, meta) for arm, (meta, cases, acct) in loaded.items()}
    c, h = m['control'], m['hold']
    checks = dict(no_additional_wrong=h['wrong'] <= c['wrong'], solved=h['solved'] >= c['solved'] - SOLVED_SLACK,
                  energy=(c['wh_per_solved'] is not None and h['wh_per_solved'] is not None
                          and h['wh_per_solved'] <= ENERGY_RATIO * c['wh_per_solved']))
    ratio = (h['wh_per_solved'] / c['wh_per_solved']) if c['wh_per_solved'] and h['wh_per_solved'] else None
    tokens = (round(1 - h['server_generation_tokens'] / c['server_generation_tokens'], 4)
              if c['server_generation_tokens'] and h['server_generation_tokens'] is not None else None)
    decision = 'PASS' if all(checks.values()) else 'STOP'  # every comparison above uses unrounded values
    return dict(out, status='complete', arms=m, checks=checks, energy_per_solved_ratio=ratio,
                server_generation_token_saving=tokens, decision=decision)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--control', type=Path, default=ROOT / 'CODING_SUSPEND_CONTROL_PLAN.json')
    p.add_argument('--hold', type=Path, default=ROOT / 'CODING_SUSPEND_HOLD_PLAN.json')
    p.add_argument('--control-run', type=Path, default=ROOT / 'runs' / 'coding-suspend-v1-control')
    p.add_argument('--hold-run', type=Path, default=ROOT / 'runs' / 'coding-suspend-v1-hold')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'coding-suspend-v1')
    a = p.parse_args(argv)
    r = build(json.loads(a.control.read_text()), json.loads(a.hold.read_text()), a.control_run, a.hold_run)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(decision=r['decision'], checks=r.get('checks'), ratio=r.get('energy_per_solved_ratio'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
