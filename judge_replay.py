#!/usr/bin/env python3
"""Judge replay screens on RECORDED candidates (judges.py; Fable round 4 ideas 3 and 4). One --part per invocation so
inkling/account_cmd.py charges each part's server work.

  --part coding  the generic protocol judge (judges.coding_judge_prompt, domain-free system prompt) on every recorded
                 winner of the finished coding arms (coding-roll*-v1*, coding-stagger-v1*, coding-earlystop-v1* with a
                 cases.json); hidden (holdout) result copied for scoring only
  --part arith   a second, independent call of the unchanged arithmetic judge (run_variants.judge_with_reason, other
                 seed) on every recorded accepted plan whose answer was forced, plus an equal-size seeded sample of
                 accepted self-closed plans (control); --include-rejected-forced adds every forced plan the first judge
                 rejected (where false accepts would show)
Every judge call uses run_variants.judge_with_reason (one retry on transport loss, same seed); seeds are stable hashes of
(salt, run, case, agent). Output: OUTPUT/candidates.jsonl (one record per candidate: verdict, reason, tokens, infra,
truth), OUTPUT/judges/*.jsonl traces, OUTPUT/metadata.json. --plan-only lists counts and a fleet-time estimate with no
model call.

usage: judge_replay.py --part coding|arith --plan-only [--runs-dir runs] [--include-rejected-forced]
       judge_replay.py --part coding|arith --plan PLAN --admission {admission} --output {output} [--endpoints ...]
                       [--max-per-endpoint N] [--include-rejected-forced]
"""
import argparse
import json
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import closer_replay
import closers
import judges
import run_variants
from run_agents72 import read, require, sha, write

HERE = Path(__file__).resolve().parent
MAX_PER_ENDPOINT = 20
# planning constants (estimates only): fleet generation rate from Fable round 4 (1.6M tokens ~ 20 min) and the coding
# judge's expected tokens per call (3K, Fable idea 3); arithmetic uses the recorded first-judge tokens of the candidates
FLEET_TOKENS_PER_SECOND = 1333
CODING_JUDGE_TOKENS = 3000


def collect(part, runs_dir, include_rejected_forced=False):
    if part == 'coding':
        runs, skipped = judges.coding_runs(runs_dir)
        cands = []
        for r in runs:
            c, sk = judges.coding_winners(r)
            cands += c
            skipped += [f'{r.name}: {x}' for x in sk]
        return cands, [r.name for r in runs], skipped
    runs = judges.arith_runs(runs_dir)
    found = []
    for r in runs:
        found += judges.arith_accepted(r, include_rejected_forced=include_rejected_forced)
    return judges.arith_selection(found), [r.name for r in runs], []


def summary(part, cands):
    groups = Counter(c['group'] for c in cands)
    truth = Counter((c['group'], c['truth']) for c in cands)
    est = (len(cands) * CODING_JUDGE_TOKENS if part == 'coding'
           else sum(c.get('recorded_judge_tokens') or 800 for c in cands))
    return dict(candidates=len(cands), groups=dict(groups),
                truth_by_group={f'{g}/{"correct" if t else "wrong"}': n for (g, t), n in sorted(truth.items())},
                forced=sum(c['forced'] for c in cands), estimated_judge_tokens=est,
                estimated_fleet_minutes=round(est / FLEET_TOKENS_PER_SECOND / 60, 1))


def judge_candidate(c, endpoint, out, slots):
    """One second-opinion judge call on a recorded candidate (the decision never reads c['truth'])."""
    stem = f"{c['part']}-{c['run']}-{c['task_id']}-s{c['seed']}-" + (f"a{c['agent']}" if c['part'] == 'coding' else f"{c['policy']}-a{c['slot']}")
    path = out / 'judges' / (stem + '.jsonl')
    with slots(endpoint):
        try:
            if c['part'] == 'coding':
                prompt = judges.coding_judge_prompt(c['statement_task'], c['code'])
                j = run_variants.judge_with_reason(None, endpoint, path, c['judge_seed'], prompt=prompt,
                                                   client_factory=judges.GenericJudge)
            else:
                cand = dict(numbers=c['numbers'], target=c['target'], plan=c['plan'])
                j = run_variants.judge_with_reason(cand, endpoint, path, c['judge_seed'])
        except run_variants.JudgeFault as exc:
            j = dict(exc.record, verdict=None)
    keep = {k: v for k, v in c.items() if k not in ('statement_task', 'code', 'plan')}
    return dict(keep, endpoint=endpoint, verdict=j['verdict'], reason=j.get('reason', ''), tokens=j['tokens'],
                infra=j['infra'], judge_retry=bool(j.get('retry')), judge_attempts=j.get('judge_attempts'),
                code_chars=len(c.get('code') or ''), events=str(path))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--part', choices=('coding', 'arith'), required=True)
    p.add_argument('--runs-dir', type=Path, default=HERE / 'runs')
    p.add_argument('--include-rejected-forced', action='store_true')
    p.add_argument('--plan', type=Path)
    p.add_argument('--admission', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--endpoints', nargs='+', default=list(run_variants.ENDPOINTS))
    p.add_argument('--max-per-endpoint', type=int, default=8)
    p.add_argument('--plan-only', action='store_true')
    a = p.parse_args(argv)
    require(1 <= a.max_per_endpoint <= MAX_PER_ENDPOINT, 'max-per-endpoint must be 1..20')
    require(len(set(a.endpoints)) == len(a.endpoints), 'duplicate endpoints')
    cands, runs, skipped = collect(a.part, a.runs_dir, a.include_rejected_forced)
    info = dict(part=a.part, runs=runs, skipped=skipped, **summary(a.part, cands))
    if a.plan_only:
        print(json.dumps(dict(mode='plan', model_calls=0, **info)))
        return 0
    require(a.plan and a.output and a.admission, '--plan, --output and --admission are required for a run')
    out = a.output.resolve()
    require(not out.exists(), 'output exists')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900,
            'Fresh admission')
    outside = sorted(set(a.endpoints) - closer_replay.admitted_endpoints(adm))
    require(not outside, f'endpoints not verified by the admission: {outside}')
    plan = read(a.plan)
    (out / 'judges').mkdir(parents=True)
    write(out / 'metadata.json', dict(protocol='swarm-judge-replay-v1', plan=str(a.plan), plan_sha256=sha(a.plan),
                                      serving=plan.get('serving'), runner_sha256=sha(Path(__file__)),
                                      judges_sha256=sha(HERE / 'judges.py'), run_variants_sha256=sha(HERE / 'run_variants.py'),
                                      generic_system=judges.GENERIC_SYSTEM, coding_tail=judges.CODING_TAIL,
                                      include_rejected_forced=a.include_rejected_forced, endpoints=a.endpoints,
                                      max_per_endpoint=a.max_per_endpoint, started_utc=datetime.now(timezone.utc).isoformat(),
                                      admission=adm, **info))
    slots, lock, rows = closers.EndpointSlots(a.endpoints, a.max_per_endpoint), threading.Lock(), []

    def work(job):
        i, c = job
        try:
            rec = judge_candidate(c, a.endpoints[i % len(a.endpoints)], out, slots)
        except Exception as exc:  # never lose a candidate: a fault record
            rec = dict({k: v for k, v in c.items() if k not in ('statement_task', 'code', 'plan')}, verdict=None,
                       tokens=0, infra=1, error=f'{type(exc).__name__}: {exc}'[:300])
        with lock:
            rows.append(rec)
            with (out / 'candidates.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            if len(rows) % 25 == 0 or len(rows) == len(cands):
                print(json.dumps(dict(done=len(rows), total=len(cands), part=a.part)), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(max(1, min(len(cands), len(a.endpoints) * a.max_per_endpoint))) as pool:
        list(pool.map(work, enumerate(cands)))
    meta = read(out / 'metadata.json')
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=round(time.monotonic() - start, 1),
                judged=len(rows), faults=sum(bool(r.get('infra')) for r in rows),
                client_tokens=sum(r.get('tokens') or 0 for r in rows))
    write(out / 'metadata.json', meta)
    print(json.dumps(dict(judged=len(rows), faults=meta['faults'])))
    return int(bool(meta['faults']) or len(rows) != len(cands))


if __name__ == '__main__':
    raise SystemExit(main())
