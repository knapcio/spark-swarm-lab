#!/usr/bin/env python3
"""Report of the idea #4 falsifier (FORK_SCREEN_PLAN.json, fork_replay.py): fork vs fresh.

Validation: the run embeds this plan, its summary says complete and the end-of-run drain is confirmed, and the records
are EXACTLY the planned units (per item four fresh attempts, two stems, four fork leaves), each once, none faulted or
not started; otherwise INCOMPLETE (no decision).
An arm covers a puzzle if any of its candidates is accepted by the judge AND solved by the STRICT exact verifier
(inkling/strict_verify.py, recomputed here from the candidate plan). G(arm) = agent completion tokens of every call
(stems counted once, in the fork arm) + judge tokens. STOP if C(fork) < C(fresh) or G(fork) >= G(fresh); otherwise
PASS AS A SCREEN only (adoption needs a fresh confirmation).

usage: report_fork_screen.py --plan FORK_SCREEN_PLAN.json --run runs/fork-screen-v1 [--out DIR]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import strict_verify as sv  # noqa: E402
from report_extend_screen import sign_test  # noqa: E402

ROOTS, STEMS, LEAVES = 4, 2, 4


def planned(plan):
    keys = set()
    for i in plan['items']:
        keys |= {(i['item_id'], 'fresh', j) for j in range(ROOTS)}
        keys |= {(i['item_id'], 'stem', s) for s in range(STEMS)}
        keys |= {(i['item_id'], 'fork', j) for j in range(LEAVES)}
    return keys


def faulted(r):
    return r.get('error') or r.get('judge_error') or (r.get('judge_infra') and 'judge infra') or \
        (r.get('not_started') and 'not started')


def build(plan, run_dir):
    run_dir = Path(run_dir)
    problems = []
    meta = json.loads((run_dir / 'metadata.json').read_text()) if (run_dir / 'metadata.json').exists() else {}
    if meta.get('plan') != plan:
        problems.append('the run does not embed this plan')
    summary = json.loads((run_dir / 'summary.json').read_text()) if (run_dir / 'summary.json').exists() else {}
    if summary.get('drain_confirmed') is not True:
        problems.append('the end-of-run drain was not confirmed')
    if summary.get('complete') is not True:
        problems.append('the run summary is not complete')
    path = run_dir / 'run' / 'records.jsonl'
    records = [json.loads(line) for line in path.read_text().splitlines() if line.strip()] if path.exists() else []
    by_key = {}
    for r in records:
        key = (r.get('item'), r.get('arm'), r.get('index'))
        if key in by_key:
            problems.append(f'unit {key} recorded twice')
        by_key[key] = r
    keys = planned(plan)
    extra = sorted(set(by_key) - keys, key=str)
    if extra:
        problems.append(f'records outside the plan: {extra[:3]}')
    for key in sorted(keys, key=str):
        r = by_key.get(key)
        if r is None:
            problems.append(f'unit {key} missing')
        elif faulted(r):
            problems.append(f'unit {key} faulted: {faulted(r)}')
    out = dict(study=plan['study'], run=str(run_dir), items=len(plan['items']))
    if problems:
        return dict(out, status='incomplete', problems=problems[:20], decision='INCOMPLETE (no decision)')
    items = {i['item_id']: i for i in plan['items']}

    def success(r):
        if r.get('verdict') is not True or not r.get('candidate'):
            return False
        item = items[r['item']]
        return sv.strict_solved(item['numbers'], item['target'], r['candidate']['plan'])

    arms, puzzles = {}, {}
    for arm, units in (('fresh', [('fresh', j) for j in range(ROOTS)]),
                       ('fork', [('stem', s) for s in range(STEMS)] + [('fork', j) for j in range(LEAVES)])):
        recs = [by_key[(i['item_id'], kind, n)] for i in plan['items'] for kind, n in units]
        cands = [r for r in recs if r['arm'] != 'stem' and r.get('candidate')]
        accepted = [r for r in cands if r.get('verdict') is True]
        replies = {}
        for r in recs:
            if r['arm'] != 'stem' and not r.get('stem_terminal'):
                replies[str(r.get('forced_reply'))] = replies.get(str(r.get('forced_reply')), 0) + 1
        agent = sum(r.get('tokens_generated') or 0 for r in recs)
        judge = sum(r.get('judge_tokens') or 0 for r in recs)
        arms[arm] = dict(candidates=len(cands), accepted=len(accepted), successes=sum(map(success, cands)),
                         wrong=sum(1 for r in accepted if not success(r)), forced_replies=replies,
                         agent_tokens=agent, judge_tokens=judge, generated=agent + judge,
                         prompt_tokens=sum(r.get('prompt_tokens') or 0 for r in recs))
        if arm == 'fork':
            stems = [r for r in recs if r['arm'] == 'stem']
            arms[arm].update(stems_forked=sum(1 for r in stems if r.get('forked')),
                             stems_finished=sum(1 for r in stems if r.get('forked') is False))
    for i in plan['items']:
        puzzles[i['puzzle_key']] = dict(
            fresh=any(success(by_key[(i['item_id'], 'fresh', j)]) for j in range(ROOTS)),
            fork=any(success(by_key[(i['item_id'], 'fork', j)]) for j in range(LEAVES)),
            g_fresh=sum((by_key[(i['item_id'], 'fresh', j)].get('tokens_generated') or 0)
                        + (by_key[(i['item_id'], 'fresh', j)].get('judge_tokens') or 0) for j in range(ROOTS)),
            g_fork=sum((by_key[(i['item_id'], kind, n)].get('tokens_generated') or 0)
                       + (by_key[(i['item_id'], kind, n)].get('judge_tokens') or 0)
                       for kind, n in [('stem', s) for s in range(STEMS)] + [('fork', j) for j in range(LEAVES)]))
    c_fresh = sum(p['fresh'] for p in puzzles.values())
    c_fork = sum(p['fork'] for p in puzzles.values())
    fork_only = sum(p['fork'] and not p['fresh'] for p in puzzles.values())
    fresh_only = sum(p['fresh'] and not p['fork'] for p in puzzles.values())
    g_fresh, g_fork = arms['fresh']['generated'], arms['fork']['generated']
    reasons = ([f'lower coverage: fork {c_fork} < fresh {c_fresh}'] if c_fork < c_fresh else []) + \
        ([f'no net compute saving: G(fork) {g_fork} >= G(fresh) {g_fresh}'] if g_fork >= g_fresh else [])
    decision = 'STOP' if reasons else 'PASS AS A SCREEN (adoption needs a fresh confirmation)'
    return dict(out, status='complete', arms=arms, puzzles=puzzles, coverage_fresh=c_fresh, coverage_fork=c_fork,
                fork_only=fork_only, fresh_only=fresh_only, sign_test_p=sign_test(fork_only, fresh_only),
                saving=round(1 - g_fork / g_fresh, 4) if g_fresh else None, stop_reasons=reasons, decision=decision)


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
    print(json.dumps(dict(decision=r['decision'], fresh=r.get('coverage_fresh'), fork=r.get('coverage_fork'),
                          saving=r.get('saving'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
