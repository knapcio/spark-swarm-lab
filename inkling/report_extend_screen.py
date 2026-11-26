#!/usr/bin/env python3
"""Report of the idea #1 fleet screen (EXTEND_SCREEN_PLAN.json, extend_replay.py): the frozen rule.

Validation: the run embeds this plan, every planned attempt (item x arm x attempt) has exactly one record without a
transport or judge fault, and the end-of-run drain is confirmed; otherwise INCOMPLETE (no decision).
Per puzzle an arm rescues it if any of its attempts is accepted by the judge AND solved by the exact verifier.
STOP if the extensions rescue no more puzzles than the fresh agents (E <= F, clustered by puzzle); otherwise PASS AS A
SCREEN only (adoption needs a fresh confirmation). Reported: wrong acceptances per arm, tokens, exact sign test over
the discordant puzzles.

usage: report_extend_screen.py --plan EXTEND_SCREEN_PLAN.json --run runs/extend-screen-v1 [--out DIR]
"""
import argparse
import json
from math import comb
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARMS, ATTEMPTS = ('extension', 'fresh'), (1, 2)


def sign_test(wins, losses):
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2 ** n)


def build(plan, run_dir):
    run_dir = Path(run_dir)
    problems = []
    meta = json.loads((run_dir / 'metadata.json').read_text()) if (run_dir / 'metadata.json').exists() else {}
    if meta.get('plan') != plan:
        problems.append('the run does not embed this plan')
    summary = json.loads((run_dir / 'summary.json').read_text()) if (run_dir / 'summary.json').exists() else {}
    if summary.get('drain_confirmed') is not True:
        problems.append('the end-of-run drain was not confirmed')
    path = run_dir / 'run' / 'records.jsonl'
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    by_key = {}
    for r in records:
        key = (r.get('item'), r.get('arm'), r.get('attempt'))
        if key in by_key:
            problems.append(f'attempt {key} recorded twice')
        by_key[key] = r
    for item in plan['items']:
        for arm in ARMS:
            for k in ATTEMPTS:
                r = by_key.get((item['item_id'], arm, k))
                if r is None:
                    problems.append(f"attempt {item['item_id']} {arm}{k} missing")
                elif r.get('error') or r.get('judge_error') or r.get('judge_infra'):
                    problems.append(f"attempt {item['item_id']} {arm}{k} faulted: "
                                    f"{r.get('error') or r.get('judge_error') or 'judge infra'}")
    out = dict(study=plan['study'], run=str(run_dir), items=len(plan['items']))
    if problems:
        return dict(out, status='incomplete', problems=problems, decision='INCOMPLETE (no decision)')
    puzzles, arms = {}, {}
    for arm in ARMS:
        recs = [by_key[(i['item_id'], arm, k)] for i in plan['items'] for k in ATTEMPTS]
        accepted = [r for r in recs if r.get('verdict') is True]
        arms[arm] = dict(attempts=len(recs), accepted=len(accepted),
                         wrong=sum(1 for r in accepted if not r.get('verifier_solved')),
                         tokens=sum(r.get('tokens_generated') or 0 for r in recs),
                         judge_tokens=sum(r.get('judge_tokens') or 0 for r in recs))
    for item in plan['items']:
        puzzles[item['puzzle_key']] = {arm: any(by_key[(item['item_id'], arm, k)].get('verdict') is True
                                                and by_key[(item['item_id'], arm, k)].get('verifier_solved')
                                                for k in ATTEMPTS) for arm in ARMS}
    e = sum(p['extension'] for p in puzzles.values())
    f = sum(p['fresh'] for p in puzzles.values())
    ext_only = sum(p['extension'] and not p['fresh'] for p in puzzles.values())
    fresh_only = sum(p['fresh'] and not p['extension'] for p in puzzles.values())
    decision = 'STOP' if e <= f else 'PASS AS A SCREEN (adoption needs a fresh confirmation)'
    return dict(out, status='complete', arms=arms, puzzles=puzzles, extension_rescues=e, fresh_rescues=f,
                extension_only=ext_only, fresh_only=fresh_only, sign_test_p=sign_test(ext_only, fresh_only),
                decision=decision)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--plan', type=Path, required=True)
    p.add_argument('--run', type=Path, required=True)
    p.add_argument('--out', type=Path)
    a = p.parse_args(argv)
    plan = json.loads(a.plan.read_text())
    r = build(plan, a.run)
    out = a.out or ROOT / 'results' / plan['study']
    out.mkdir(parents=True, exist_ok=True)
    (out / 'report.json').write_text(json.dumps(r, indent=1) + '\n')
    print(json.dumps(dict(decision=r['decision'], extension=r.get('extension_rescues'), fresh=r.get('fresh_rescues'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
