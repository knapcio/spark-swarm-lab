#!/usr/bin/env python3
"""Report of the live differential-gate A/B (DIFFGATE_LIVE_PLAN.json): control vs gate with the frozen rule.

PASS iff wrong(gate) <= 0.6 x wrong(control) AND solved(gate) >= solved(control) - 3 AND GPU Wh per solved case of
the gate <= 1.5 x control (unrounded; energy on all four nodes); otherwise STOP. INCOMPLETE (no decision) unless both
arms are complete (the checks of report_suspend_ab.arm_problems: the run embeds its plan, no runner errors, the source
did not change, exactly the frozen task x seed keys, runner exit 0, drain confirmed, no signal, energy on all four
nodes) and the plans differ only in their arm fields. Reported: solved, wrong, unanswered, agents started, generator
tokens and calls, sandbox seconds, fallback cases, wall, server generated tokens, Wh per solved, and the SHARED-BUG
cases separately (gate arm: every distinct passer agreed and the accepted answer is still wrong).

usage: report_diffgate_live.py [--control PLAN] [--gate PLAN] [--control-run DIR] [--gate-run DIR] [--out DIR]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
from report_suspend_ab import arm_problems, load  # noqa: E402

ARM_FIELDS = ('study', 'ab_arm', 'runner', 'differential_gate', 'execution')
WRONG_RATIO, SOLVED_SLACK, ENERGY_RATIO = 0.6, 3, 1.5


def arm_view(plan):
    return {k: v for k, v in plan.items() if k not in ARM_FIELDS}


def energy_wh(acct):
    """GPU Wh at full precision from the per-node joules (energy.py rounds total_wh to 2 decimals; inkling/energy.py
    itself is pinned by other frozen plans and stays unchanged)."""
    nodes = (acct.get('energy') or {}).get('nodes') or {}
    return sum(n['joules'] for n in nodes.values()) / 3600


def metrics(meta, cases, acct, rows):
    solved = sum(bool(c['solved']) for c in cases)
    answered = sum(bool(c['answered']) for c in cases)
    wh = energy_wh(acct)
    total = (acct.get('server') or {}).get('total') or {}
    gate = meta.get('gate') or {}
    return dict(cases=len(cases), solved=solved, answered=answered, wrong=answered - solved,
                unanswered=len(cases) - answered, agents_started=len(rows), energy_wh=wh,
                energy_wh_display=round(wh, 2),
                wh_per_solved=(wh / solved) if solved else None,
                server_generation_tokens=total.get('generation_tokens'),
                runner_wall_seconds=acct.get('runner_wall_seconds'),
                generator_calls=gate.get('generator_calls', 0), generator_tokens=gate.get('generator_tokens', 0),
                sandbox_seconds=gate.get('sandbox_seconds', 0.0), fallback_cases=gate.get('fallback_cases', 0))


def shared_bug(cases, gate_cases):
    by = {(g['task_id'], g['seed']): g for g in gate_cases or []}
    out = []
    for c in cases:
        g = by.get((c['task_id'], c['seed']))
        if c['answered'] and not c['solved'] and g and g.get('all_passers_agree'):
            out.append(dict(task_id=c['task_id'], seed=c['seed'], passers=g['passers'], rule=g['decision']['rule']
                            if g.get('decision') else None))
    return out


def build(control_plan, gate_plan, control_run, gate_run, root=ROOT):
    problems = []
    if arm_view(control_plan) != arm_view(gate_plan):
        problems.append('the two plans differ beyond their arm fields')
    if control_plan.get('runner') != 'run_coding_earlystop.py' or gate_plan.get('runner') != 'run_coding_diffgate.py' \
            or 'differential_gate' in control_plan or 'differential_gate' not in gate_plan:
        problems.append('arm fields wrong (control: production runner, no gate; gate: run_coding_diffgate.py)')
    loaded = {}
    for arm, plan, run in (('control', control_plan, control_run), ('gate', gate_plan, gate_run)):
        meta, cases, acct = load(run)
        problems += arm_problems(arm, plan, meta, cases, acct, root)
        rows_path = Path(run) / 'summary.json'
        rows = json.loads(rows_path.read_text()) if rows_path.exists() else []
        gate_path = Path(run) / 'gate_cases.json'
        gate_cases = json.loads(gate_path.read_text()) if gate_path.exists() else None
        if arm == 'gate':
            from report_suspend_ab import expected_keys
            keys = expected_keys(plan, root) or set()
            got = [(g.get('task_id'), g.get('seed')) for g in gate_cases or []]
            if gate_cases is None or len(got) != len(set(got)) or set(got) != keys:
                problems.append('gate: gate_cases.json is not exactly one receipt per frozen case')
        nodes = (acct.get('energy') or {}).get('nodes') or {}
        if any(not isinstance((n or {}).get('joules'), (int, float)) for n in nodes.values()):
            problems.append(f'{arm}: energy without per-node joules')
        loaded[arm] = (meta, cases, acct, rows, gate_cases)
    out = dict(study=control_plan.get('study_group'), control_run=str(control_run), gate_run=str(gate_run),
               rule=control_plan.get('decision_rule'))
    if problems:
        return dict(out, status='incomplete', problems=problems[:20], decision='INCOMPLETE (no decision)')
    m = {arm: metrics(meta, cases, acct, rows) for arm, (meta, cases, acct, rows, _) in loaded.items()}
    c, g = m['control'], m['gate']
    checks = dict(wrong=g['wrong'] <= WRONG_RATIO * c['wrong'], solved=g['solved'] >= c['solved'] - SOLVED_SLACK,
                  energy=(c['wh_per_solved'] is not None and g['wh_per_solved'] is not None
                          and g['wh_per_solved'] <= ENERGY_RATIO * c['wh_per_solved']))
    return dict(out, status='complete', arms=m, checks=checks,
                energy_per_solved_ratio=(g['wh_per_solved'] / c['wh_per_solved'])
                if c['wh_per_solved'] and g['wh_per_solved'] else None,
                shared_bug_cases=shared_bug(loaded['gate'][1], loaded['gate'][4]),
                decision='PASS' if all(checks.values()) else 'STOP')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--control', type=Path, default=ROOT / 'CODING_DIFFGATE_CONTROL_PLAN.json')
    p.add_argument('--gate', type=Path, default=ROOT / 'CODING_DIFFGATE_GATE_PLAN.json')
    p.add_argument('--control-run', type=Path, default=ROOT / 'runs' / 'coding-diffgate-v1-control')
    p.add_argument('--gate-run', type=Path, default=ROOT / 'runs' / 'coding-diffgate-v1-gate')
    p.add_argument('--out', type=Path, default=ROOT / 'results' / 'diffgate-live-v1')
    a = p.parse_args(argv)
    r = build(json.loads(a.control.read_text()), json.loads(a.gate.read_text()), a.control_run, a.gate_run)
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(decision=r['decision'], checks=r.get('checks'), problems=r.get('problems'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
