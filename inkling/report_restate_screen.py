#!/usr/bin/env python3
"""Report of the idea #2 falsifier (RESTATE_SCREEN_PLAN.json, restate_replay.py): restated vs original input.

Validation: the run embeds this plan, its summary says complete and the end-of-run drain is confirmed, and the records
are EXACTLY the planned workers (item x arm x k), each once, none faulted or not started; otherwise INCOMPLETE.
An arm rescues a puzzle if any of its candidates is accepted by the judge AND solved by the STRICT exact verifier
(inkling/strict_verify.py, recomputed here on the ORIGINAL numbers and target from the candidate plan). STOP if
R <= O; otherwise PASS AS A SCREEN only (adoption needs a fresh confirmation).

usage: report_restate_screen.py --plan RESTATE_SCREEN_PLAN.json --run runs/restate-screen-v1 [--out DIR]
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))
import strict_verify as sv  # noqa: E402
from report_extend_screen import sign_test  # noqa: E402

SEED_NOTE = ('pairing labels attempts only; draws are independent on this server (per-request seeds not honoured: '
             'no deterministic inference on the launch; live probe 2026-11-26 21:06Z, identical requests with the same '
             'seed at temperature 0.8 gave different outputs)')

ARMS, WORKERS = ('original', 'restated'), (0, 1)


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
            problems.append(f'worker {key} recorded twice')
        by_key[key] = r
    keys = {(i['item_id'], arm, k) for i in plan['items'] for arm in ARMS for k in WORKERS}
    extra = sorted(set(by_key) - keys, key=str)
    if extra:
        problems.append(f'records outside the plan: {extra[:3]}')
    for key in sorted(keys, key=str):
        r = by_key.get(key)
        if r is None:
            problems.append(f'worker {key} missing')
        elif faulted(r):
            problems.append(f'worker {key} faulted: {faulted(r)}')
    out = dict(study=plan['study'], run=str(run_dir), items=len(plan['items']), seeds=SEED_NOTE)
    if problems:
        return dict(out, status='incomplete', problems=problems[:20], decision='INCOMPLETE (no decision)')
    items = {i['item_id']: i for i in plan['items']}

    def success(r):
        if r.get('verdict') is not True or not r.get('candidate'):
            return False
        item = items[r['item']]
        return sv.strict_solved(item['numbers'], item['target'], r['candidate']['plan'])

    arms, puzzles = {}, {}
    for arm in ARMS:
        recs = [by_key[(i['item_id'], arm, k)] for i in plan['items'] for k in WORKERS]
        accepted = [r for r in recs if r.get('verdict') is True]
        replies = {}
        for r in recs:
            replies[str(r.get('forced_reply'))] = replies.get(str(r.get('forced_reply')), 0) + 1
        agent = sum(r.get('tokens_generated') or 0 for r in recs)
        judge = sum(r.get('judge_tokens') or 0 for r in recs)
        arms[arm] = dict(workers=len(recs), candidates=sum(1 for r in recs if r.get('candidate')),
                         accepted=len(accepted), successes=sum(map(success, recs)),
                         wrong=sum(1 for r in accepted if not success(r)), forced_replies=replies,
                         empty_restatements=sum(1 for r in recs if r.get('restatement_empty')),
                         restate_tokens=sum(r.get('restate_tokens') or 0 for r in recs),
                         agent_tokens=agent, judge_tokens=judge, generated=agent + judge)
    for i in plan['items']:
        puzzles[i['puzzle_key']] = {arm: any(success(by_key[(i['item_id'], arm, k)]) for k in WORKERS) for arm in ARMS}
    o = sum(p['original'] for p in puzzles.values())
    r_ = sum(p['restated'] for p in puzzles.values())
    restated_only = sum(p['restated'] and not p['original'] for p in puzzles.values())
    original_only = sum(p['original'] and not p['restated'] for p in puzzles.values())
    decision = 'STOP' if r_ <= o else 'PASS AS A SCREEN (adoption needs a fresh confirmation)'
    return dict(out, status='complete', arms=arms, puzzles=puzzles, original_rescues=o, restated_rescues=r_,
                restated_only=restated_only, original_only=original_only,
                sign_test_p=sign_test(restated_only, original_only), decision=decision)


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
    print(json.dumps(dict(decision=r['decision'], original=r.get('original_rescues'),
                          restated=r.get('restated_rescues'))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
