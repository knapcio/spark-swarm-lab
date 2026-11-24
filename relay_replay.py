#!/usr/bin/env python3
"""Generic artifact relay vs equal-budget replacement on a recorded run's clean abstentions (relay.py).

One invocation runs ONE arm (--arm relay or --arm replace), so inkling/account_cmd.py can wrap each arm with its own
server-side accounting; run RELAY first, then REPLACE, on the same cohort (frozen with --case-list). Per case both arms
get the same number of workers: the number of artifacts RELAY selected for that case (seeded uniform sampling of up to
K distinct, nonempty failed-agent artifacts), so the arms are paired by case and equal in worker budget. Workers use
the recorded run's agent variant (same budget) unless the plan sets relay.variant. Worker seeds: a stable hash of
(arm, plan salt, source run, task, case seed, slot); slot = 200 + i for RELAY, 300 + i for REPLACE. With several runs, each (task_id, seed) is used once (first run listed; --no-dedupe keeps all).

Cohort: as closer_replay (frozen resume rule, clean abstentions, each case once; --case-list / --write-case-list).
Plan fields: relay = {k, max_chars, selection_seed, variant?}, seed_offsets.relay/.replace, source_revision,
source_path, agent_wall_deadline_seconds, serving (admission).

usage: relay_replay.py --runs RUN... --plan-only [--plan PLAN] [--write-case-list FILE]
       relay_replay.py --runs RUN... --arm relay|replace --plan PLAN --admission {admission} --output {output}
                       [--case-list FILE] [--source DIR] [--endpoints ...] [--max-per-endpoint N]
"""
import argparse
import json
import statistics
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import closer_replay
import closers
import relay
import run_variants
from run_agents72 import read, require, sha, validate_source, write

HERE = Path(__file__).resolve().parent
MAX_PER_ENDPOINT = 20


def dedupe(runs):
    """Each (task_id, seed) once across the given runs: the first run listed supplies it (its agents' artifacts);
    returns the dropped duplicates [[run, task_id, seed, kept_from_run], ...]."""
    owner, dropped = {}, []
    for run in runs:
        kept = []
        for c in run['cases']:
            key = (c['task']['id'], c['seed'])
            if key in owner:
                dropped.append([run['run'], key[0], key[1], owner[key]])
            else:
                owner[key] = run['run']
                kept.append(c)
        run['cases'] = kept
    return dropped


def case_plans(runs, s):
    out = []
    for run in runs:
        for c in run['cases']:
            out.append((run, c, relay.case_plan(c['seg'], c['row'], c['task'], c['seed'], s)))
    return out


def plan_only(runs, s, duplicates=()):
    plans = case_plans(runs, s)
    per_run = {}
    for run, c, cp in plans:
        agg = per_run.setdefault(run['run'], dict(cases=0, failed_agents=0, candidates=0, selected=0, cases_with_workers=0,
                                                  dense_window_differs=0, chars_used=[]))
        agg['dense_window_differs'] += sum(relay.dense_window(x['text'], s['max_chars'])[1] > 0 for x in cp['selected'])
        agg['cases'] += 1
        agg['failed_agents'] += cp['failed_agents']
        agg['candidates'] += cp['candidates']
        agg['selected'] += len(cp['selected'])
        agg['cases_with_workers'] += bool(cp['selected'])
        agg['chars_used'] += [x['chars_used'] for x in cp['selected']]
        print(json.dumps(dict(run=run['run'], task_id=c['task']['id'], seed=c['seed'], failed_agents=cp['failed_agents'],
                              candidates=cp['candidates'], selected_slots=[x['source_slot'] for x in cp['selected']],
                              chars=[x['chars'] for x in cp['selected']])))
    total = dict(cases=0, failed_agents=0, candidates=0, selected=0, cases_with_workers=0, dense_window_differs=0)
    for name, agg in per_run.items():
        chars = agg.pop('chars_used')
        agg.update(relay_workers=agg['selected'], replace_workers=agg['selected'],
                   chars_used_median=statistics.median(chars) if chars else None, chars_used_max=max(chars) if chars else None)
        print(json.dumps(dict(summary=dict(run=name, **agg))))
        for k in total:
            total[k] += agg[k]
    print(json.dumps(dict(mode='plan', model_calls=0, window=s['window'], dropped_duplicates=len(duplicates),
                          distinct_puzzles=len({c['task']['id'] for r in runs for c in r['cases']}), k=s['k'], max_chars=s['max_chars'], selection_seed=s['selection_seed'],
                          total=dict(total, relay_workers=total['selected'], replace_workers=total['selected']))))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs', type=Path, nargs='+', required=True)
    p.add_argument('--arm', choices=relay.ARMS)
    p.add_argument('--plan', type=Path)
    p.add_argument('--output', type=Path)
    p.add_argument('--source', type=Path)
    p.add_argument('--admission', type=Path)
    p.add_argument('--endpoints', nargs='+', default=list(run_variants.ENDPOINTS))
    p.add_argument('--max-per-endpoint', type=int, default=8)
    p.add_argument('--plan-only', action='store_true')
    p.add_argument('--case-list', type=Path)
    p.add_argument('--window', choices=('tail', 'dense'),
                   help='relay window for this arm (a window screen runs two RELAY arms); must be listed in plan '
                        'relay.windows (frozen), default the plan relay.window')
    p.add_argument('--no-dedupe', dest='dedupe', action='store_false',
                   help='keep a (task_id, seed) that several runs abstained on once per run (default: once overall)')
    p.add_argument('--write-case-list', type=Path)
    a = p.parse_args(argv)
    require(1 <= a.max_per_endpoint <= MAX_PER_ENDPOINT, 'max-per-endpoint must be 1..20')
    require(len(set(a.endpoints)) == len(a.endpoints), 'duplicate endpoints')
    runs = closer_replay.load_cohort(a.runs, a.case_list)
    duplicates = dedupe(runs) if a.dedupe else []
    plan = read(a.plan) if a.plan else {}
    s = relay.settings(plan)
    if a.window:
        allowed = (plan.get('relay') or {}).get('windows') or [s['window']]
        require(a.window in allowed, f'--window {a.window} is not frozen in plan relay.windows {allowed}')
        s['window'] = a.window
    require(s['k'] >= 1 and s['max_chars'] >= 1, 'relay.k and relay.max_chars must be >= 1')
    if a.plan_only:
        if a.write_case_list:
            require(not a.write_case_list.exists(), 'case list file exists')
            write(a.write_case_list, closer_replay.cohort_list(runs))
        return plan_only(runs, s, duplicates)
    require(a.arm and a.plan and a.output and a.admission, '--arm, --plan, --output and --admission are required for a run')
    out = a.output.resolve()
    require(not out.exists(), 'output exists')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900,
            'Fresh admission')
    outside = sorted(set(a.endpoints) - closer_replay.admitted_endpoints(adm))
    require(not outside, f'endpoints not verified by the admission: {outside}')
    source = (a.source or HERE / plan.get('source_path', '.runtime/xl-source')).resolve()
    validate_source(source, plan['source_revision'])
    variants = {r['run']: s['variant'] or read(r['dir'] / 'metadata.json')['protocol']['agent_variant'] for r in runs}
    for r in runs:
        for d in ('agents', 'judges', 'extra'):
            (out / 'runs' / r['run'] / d).mkdir(parents=True)
    write(out / 'metadata.json', dict(protocol='swarm-relay-replay-v1', arm=a.arm, plan=str(a.plan), plan_sha256=sha(a.plan),
                                      serving=plan.get('serving'), relay_settings=s, protocol_sentence=relay.PROTOCOL,
                                      runner_sha256=sha(Path(__file__)), relay_sha256=sha(HERE / 'relay.py'),
                                      run_variants_sha256=sha(HERE / 'run_variants.py'), runs=[str(r['dir']) for r in runs],
                                      cohort=closer_replay.cohort_list(runs), agent_variants=variants,
                                      dedupe=a.dedupe, dropped_duplicates=duplicates,
                                      case_list=str(a.case_list) if a.case_list else None,
                                      case_list_sha256=sha(a.case_list) if a.case_list else None,
                                      cost_note='client_tokens are client-side completion tokens only; server-side cost '
                                                'comes from the account_cmd fleet counters of this arm',
                                      source=str(source), endpoints=a.endpoints, max_per_endpoint=a.max_per_endpoint,
                                      started_utc=datetime.now(timezone.utc).isoformat(), admission=adm))
    slots, lock, stop, rows = closers.EndpointSlots(a.endpoints, a.max_per_endpoint), threading.Lock(), threading.Event(), []
    jobs = case_plans(runs, s)

    def work(job):
        run, c, cp = job
        if stop.is_set():
            return
        wplan = dict(agent_variant=variants[run['run']], agent_wall_deadline_seconds=plan['agent_wall_deadline_seconds'])
        try:
            rec = relay.run_arm(a.arm, wplan, source, out / 'runs' / run['run'], c['task'], c['seed'], c['case_index'], cp,
                                slots, a.endpoints, s, run_name=run['run'])
        except Exception as exc:  # never lose the case: a fault row (the arm is then incomplete)
            rec = dict(arm=a.arm, task_id=c['task']['id'], seed=c['seed'], case_index=c['case_index'], workers=[],
                       rescued=False, wrong=False, answered=False, faults=1, client_tokens=0, artifact_chars_used=0,
                       error=f'{type(exc).__name__}: {exc}'[:300])
        rec = dict(run=run['run'], selected_source_slots=[x['source_slot'] for x in cp['selected']], **rec)
        with lock:
            rows.append(rec)
            if rec['faults']:
                stop.set()
            with (out / 'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(done=len(rows), total=len(jobs), arm=a.arm, task=rec['task_id'], seed=rec['seed'],
                                  workers=len(rec['workers']), rescued=rec['rescued'], wrong=rec['wrong'])), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(max(1, min(len(jobs), 4 * a.max_per_endpoint))) as pool:
        list(pool.map(work, jobs))
    meta = read(out / 'metadata.json')
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=round(time.monotonic() - start, 1),
                stopped=stop.is_set(), cases=len(rows), cohort_cases=len(jobs),
                summary=dict(rescued=sum(r['rescued'] for r in rows), wrong=sum(r['wrong'] for r in rows),
                             faults=sum(bool(r['faults']) for r in rows), client_tokens=sum(r['client_tokens'] for r in rows)))
    write(out / 'metadata.json', meta)
    print(json.dumps(meta['summary']))
    return int(meta['stopped'] or len(rows) != len(jobs))


if __name__ == '__main__':
    raise SystemExit(main())
