#!/usr/bin/env python3
"""Report of the idea #5 live A/B (CODING_SUSPEND_CONTROL_PLAN.json vs CODING_SUSPEND_HOLD_PLAN.json), with the frozen
rule: PASS only if wrong(hold) <= wrong(control), solved(hold) >= solved(control) - 1 and GPU Wh per solved case of the
hold arm <= 0.90 x control; otherwise STOP. INCOMPLETE (no decision) unless both arms are complete: the run embeds its
plan, the two plans differ only in their arm fields, no runner errors, the source did not change, all planned cases
are present once, the runner exited 0, the drain was confirmed, no signal stopped the arm, and energy covers every node
(coverage >= MIN_COVERAGE).

usage: report_suspend_ab.py --control PLAN --hold PLAN [--control-run runs/...] [--hold-run runs/...] [--out DIR]
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARM_FIELDS = ('study', 'ab_arm', 'suspend_siblings', 'execution')
MIN_COVERAGE = 0.9
ENERGY_RATIO, SOLVED_SLACK = 0.90, 1


def arm_view(plan):
    return {k: v for k, v in plan.items() if k not in ARM_FIELDS}


def load(run_dir):
    run_dir = Path(run_dir)

    def read(name):
        return json.loads((run_dir / name).read_text()) if (run_dir / name).exists() else None
    return read('metadata.json') or {}, read('cases.json'), read('arm_accounting.json') or {}


def arm_problems(arm, plan, meta, cases, acct):
    out = []
    if meta.get('protocol') != plan:
        out.append(f'{arm}: the run does not embed its plan')
    if meta.get('errors'):
        out.append(f"{arm}: runner errors {meta['errors'][:2]}")
    if meta.get('source_changed_during_run'):
        out.append(f'{arm}: the source changed during the run')
    expected = plan['matrix']['tasks_count'] * len(plan['matrix']['seeds'])
    keys = [(c.get('task_id'), c.get('seed')) for c in (cases or [])]
    if cases is None or len(keys) != expected or len(set(keys)) != expected \
            or {s for _, s in keys} != set(plan['matrix']['seeds']):
        out.append(f'{arm}: {len(set(keys))} of {expected} planned cases')
    if acct.get('runner_exit') != 0:
        out.append(f"{arm}: runner exit {acct.get('runner_exit')}")
    if acct.get('drain_confirmed') is not True:
        out.append(f'{arm}: drain not confirmed')
    if acct.get('stopped_by_signal'):
        out.append(f'{arm}: stopped by a signal')
    energy = acct.get('energy') or {}
    if energy.get('total_wh') is None or any((n or {}).get('coverage') is None or n['coverage'] < MIN_COVERAGE
                                             for n in (energy.get('nodes') or {'?': None}).values()):
        out.append(f'{arm}: energy not covered on every node')
    return out


def arm_metrics(cases, acct, meta):
    solved = sum(bool(c['solved']) for c in cases)
    answered = sum(bool(c['answered']) for c in cases)
    wh = acct['energy']['total_wh']
    total = (acct.get('server') or {}).get('total') or {}
    return dict(cases=len(cases), solved=solved, answered=answered, wrong=answered - solved, energy_wh=wh,
                wh_per_solved=round(wh / solved, 4) if solved else None,
                server_generation_tokens=total.get('generation_tokens'), server_requests=total.get('requests'),
                runner_wall_seconds=acct.get('runner_wall_seconds'), holds=meta.get('holds'))


def build(control_plan, hold_plan, control_run, hold_run):
    problems = []
    if arm_view(control_plan) != arm_view(hold_plan):
        problems.append('the two plans differ beyond their arm fields')
    if control_plan.get('suspend_siblings') is not None or hold_plan.get('suspend_siblings') != 'hold_dispatch':
        problems.append('arm fields wrong (control without, hold with suspend_siblings = hold_dispatch)')
    loaded = {}
    for arm, plan, run in (('control', control_plan, control_run), ('hold', hold_plan, hold_run)):
        meta, cases, acct = load(run)
        problems += arm_problems(arm, plan, meta, cases, acct)
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
    ratio = round(h['wh_per_solved'] / c['wh_per_solved'], 4) if c['wh_per_solved'] and h['wh_per_solved'] else None
    tokens = (round(1 - h['server_generation_tokens'] / c['server_generation_tokens'], 4)
              if c['server_generation_tokens'] and h['server_generation_tokens'] is not None else None)
    decision = 'PASS' if all(checks.values()) else 'STOP'
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
