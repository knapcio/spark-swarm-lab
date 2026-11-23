#!/usr/bin/env python3
"""Closer replay (round-3 idea 1, stage 1): closers on the recorded failed agents of finished arms.

For every case of the given run directories that the arm left unanswered: one short Inkling call writes the wanted
list (T+x, T-x, T*x, T/x for each given number x); the recorded thinking text of each failed agent is scanned for
statements `a op b = v` with v on that list (tier 1) or v = target (tier 2) (regex and equality only); the top-ranked
failed agents with a lead get one closer each (worker variant forced_original, original task + the lines); plans go to the
unchanged judge (run_variants.judge_with_reason); the first accepted plan of a case is its rescue and cancels the
other closers. The exact verifier only scores afterwards. Agent/judge records, seeds (1000*seed + offset + slot) and
the per-endpoint Slots cap are those of run_variants.run_agent.

--plan-only lists cases, failed agents and lead counts with no model call. Tier 1 is then ESTIMATED with the exact
wanted values (reporting only; in a run the model writes the list, so run-time tier-1 counts can differ).

Closers per case: the top --max-closers-per-case (default plan closers.max_per_case, else 4) failed agents with a
lead, ranked by (tier-1 lines desc, tier-2 lines desc, slot asc); the others are recorded as skipped.

Cohort (frozen resume rule): an arm is its directory plus its -resumeN segments; per (task, seed) the latest segment
row counts, infra/error rows superseded by a resume segment are skipped, and cases whose latest row is still infra or
error are left out (listed as unresolved). A case is never scheduled twice, even if a resume directory is also passed.
--write-case-list FILE (plan-only) freezes the cohort; --case-list FILE runs exactly that cohort.

Cost: only client-side completion tokens are recorded (client_tokens); server-side cost (incl. cancelled work) must
come from the fleet counters of the arm driver, not from this driver.

usage: closer_replay.py --runs runs/A runs/B ... --plan-only [--max-closers-per-case N] [--write-case-list FILE]
       closer_replay.py --runs ... --plan PLAN.json --admission ADM.json --output runs/NAME [--case-list FILE]
"""
import argparse
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import closers
import run_variants
from run_agents72 import read, require, sha, validate_source, write

HERE = Path(__file__).resolve().parent
MAX_PER_ENDPOINT = 20


_RESUME = re.compile(r'^(.*)-resume(\d+)$')


def arm_base(run_dir):
    """The arm directory of a run or resume-segment directory."""
    run_dir = Path(run_dir)
    m = _RESUME.match(run_dir.name)
    return run_dir.parent / m.group(1) if m else run_dir


def arm_segments(base):
    """The arm directory and its resume segments, in order."""
    found = [(int(m.group(2)), d) for d in base.parent.glob(base.name + '-resume*')
             if (m := _RESUME.match(d.name)) and m.group(1) == base.name and (d / 'cases.jsonl').exists()]
    return [base] + [d for _, d in sorted(found)]


def load_run(run_dir):
    """Clean unanswered cases of one recorded arm (all its segments) with their task, case index (run order) and the
    segment whose agent traces belong to the counted row."""
    base = arm_base(run_dir)
    segs = arm_segments(base)
    plan = read(base / 'metadata.json')['protocol']
    for seg in segs[1:]:
        meta = read(seg / 'metadata.json')
        require(meta['protocol'] == plan and meta.get('resume'), f'{seg.name} is not a resume segment of {base.name}')
    tasks = run_variants.plan_tasks(plan, HERE)
    index = {(t['id'], s): si * len(tasks) + ti for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)}
    expected = set(index)
    if plan.get('case_list'):
        expected = {(c[0], c[1]) for c in read(HERE / plan['case_list'])['cases']}
    by_id = {t['id']: t for t in tasks}
    latest, superseded = {}, []
    for seg in segs:
        seen = set()
        for line in (seg / 'cases.jsonl').read_text().splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            key = (row['task_id'], row['seed'])
            require(key in index, f'unknown case {key} in {seg.name}')
            require(key not in seen, f'duplicate case {key} in {seg.name}')
            seen.add(key)
            if key in latest:
                prev_seg, prev = latest[key]
                require('error' in prev or prev.get('infra'), f'{seg.name} reruns the clean case {key}')
                superseded.append(dict(task_id=key[0], seed=key[1], segment=prev_seg.name))
            latest[key] = (seg, row)
    require(set(latest) == expected, f'{base.name}: segments do not cover the plan cases exactly')
    clean = {k: v for k, v in latest.items() if 'error' not in v[1] and not v[1].get('infra')}
    cases = [dict(row=row, seg=seg, task=by_id[k[0]], seed=k[1], case_index=index[k])
             for k, (seg, row) in sorted(latest.items(), key=lambda kv: index[kv[0]])
             if k in clean and not row['answered']]
    return dict(run=base.name, dir=base, segments=[d.name for d in segs], cases=cases, arm_cases=len(latest),
                superseded=superseded, unresolved=[dict(task_id=k[0], seed=k[1]) for k in latest if k not in clean])


def load_cohort(run_dirs, case_list=None):
    """Arms of the given directories (each arm once), optionally restricted to a frozen case list
    ({"cases": [[run, task_id, seed], ...]}, run = arm directory name); every listed case must be in the cohort."""
    bases = []
    for d in run_dirs:
        b = arm_base(d).resolve()
        if b not in bases:
            bases.append(b)
    runs = [load_run(b) for b in bases]
    names = [r['run'] for r in runs]
    require(len(set(names)) == len(names), 'arm directories must have distinct names')
    if case_list is not None:
        listed = [(c[0], c[1], c[2]) for c in read(case_list)['cases']]
        require(len(set(listed)) == len(listed), 'case list has duplicate cases')
        have = {(r['run'], c['task']['id'], c['seed']) for r in runs for c in r['cases']}
        missing = [c for c in listed if c not in have]
        require(not missing, f'case list names cases outside the clean unanswered cohort: {missing[:3]}')
        for r in runs:
            r['cases'] = [c for c in r['cases'] if (r['run'], c['task']['id'], c['seed']) in set(listed)]
    return runs


def cohort_list(runs):
    return dict(protocol='swarm-closer-cohort-v1', runs=[r['run'] for r in runs],
                cases=[[r['run'], c['task']['id'], c['seed']] for r in runs for c in r['cases']],
                segments={f"{r['run']}/{c['task']['id']}/s{c['seed']}": c['seg'].name for r in runs for c in r['cases']
                          if c['seg'].name != r['run']})


def admitted_endpoints(adm):
    """Endpoints the admission receipt verified: its 'endpoints' list, else the tunnel of every ok node (Spark_0N on
    127.0.0.1:18080+N, as inkling/admit.py checks them)."""
    if adm.get('endpoints'):
        return set(adm['endpoints'])
    return {f"http://127.0.0.1:{18080 + int(n['node'])}/v1" for n in adm.get('nodes', []) if n.get('ok') and 'node' in n}


def plan_only(runs, max_closers):
    report, total = [], dict(cases=0, failed_agents=0, missing_traces=0, tier1_agents=0, tier2_agents=0, closers=0,
                             skipped_closers=0,
                             tier1_lines=0, tier2_lines=0, cases_tier1=0, cases_any=0)
    for run in runs:
        agg = dict(run=run['run'], **{k: 0 for k in total})
        for c in run['cases']:
            task = c['task']
            wanted = closers.reference_wanted_values(task['numbers'], task['target'])
            rows = closers.case_leads(c['seg'], c['row'], wanted, task['target'])
            line = dict(run=run['run'], task_id=task['id'], seed=c['seed'], case_index=c['case_index'], segment=c['seg'].name,
                        failed_agents=len(rows), missing_traces=sum(r['missing'] for r in rows),
                        tier1_agents=sum(bool(r['tier1']) for r in rows), tier2_agents=sum(bool(r['tier2']) for r in rows),
                        closers=len(closers.select_closers(rows, max_closers)[0]),
                        skipped_closers=len(closers.select_closers(rows, max_closers)[1]),
                        tier1_lines=sum(len(r['tier1']) for r in rows), tier2_lines=sum(len(r['tier2']) for r in rows))
            print(json.dumps(line))
            for k in ('failed_agents', 'missing_traces', 'tier1_agents', 'tier2_agents', 'closers', 'skipped_closers',
                      'tier1_lines', 'tier2_lines'):
                agg[k] += line[k]
            agg['cases'] += 1
            agg['cases_tier1'] += line['tier1_agents'] > 0
            agg['cases_any'] += line['closers'] > 0
        report.append(agg)
        for k in total:
            total[k] += agg[k]
    for agg, run in zip(report, runs):
        print(json.dumps(dict(summary=dict(agg, segments=run['segments'], superseded=run['superseded'],
                                           unresolved=run['unresolved']))))
    print(json.dumps(dict(mode='plan', model_calls=0, max_closers_per_case=max_closers, tier1='estimated with exact wanted values (report only)', total=total)))
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--runs', type=Path, nargs='+', required=True)
    p.add_argument('--plan', type=Path, help='plan with serving/admission fields, source_revision, source_path, '
                                             'agent_wall_deadline_seconds, optional seed_offsets.closer')
    p.add_argument('--output', type=Path)
    p.add_argument('--source', type=Path, help='worker source (default: the plan source_path)')
    p.add_argument('--admission', type=Path)
    p.add_argument('--endpoints', nargs='+', default=list(run_variants.ENDPOINTS))
    p.add_argument('--max-per-endpoint', type=int, default=8)
    p.add_argument('--max-closers-per-case', type=int,
                   help=f'closers started per case (default: plan closers.max_per_case, else {closers.MAX_CLOSERS_PER_CASE})')
    p.add_argument('--plan-only', action='store_true')
    p.add_argument('--case-list', type=Path, help='frozen cohort {"cases": [[run, task_id, seed], ...]}')
    p.add_argument('--write-case-list', type=Path, help='plan-only: write the cohort as a case list (new file)')
    a = p.parse_args(argv)
    require(1 <= a.max_per_endpoint <= MAX_PER_ENDPOINT, 'max-per-endpoint must be 1..20')
    require(len(set(a.endpoints)) == len(a.endpoints), 'duplicate endpoints')
    runs = load_cohort(a.runs, a.case_list)
    plan = read(a.plan) if a.plan else {}
    max_closers = a.max_closers_per_case
    if max_closers is None:
        max_closers = plan.get('closers', {}).get('max_per_case', closers.MAX_CLOSERS_PER_CASE)
    require(isinstance(max_closers, int) and max_closers >= 1, 'max closers per case must be >= 1')
    if a.plan_only:
        if a.write_case_list:
            require(not a.write_case_list.exists(), 'case list file exists')
            write(a.write_case_list, cohort_list(runs))
        return plan_only(runs, max_closers)
    require(a.plan and a.output and a.admission, '--plan, --output and --admission are required for a run')
    out = a.output.resolve()
    require(not out.exists(), 'output exists')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900,
            'Fresh admission')
    outside = sorted(set(a.endpoints) - admitted_endpoints(adm))
    require(not outside, f'endpoints not verified by the admission: {outside}')
    source = (a.source or HERE / plan.get('source_path', '.runtime/xl-source')).resolve()
    validate_source(source, plan['source_revision'])
    offset = plan.get('seed_offsets', {}).get('closer', closers.CLOSER_SEED_OFFSET)
    cplan = dict(agent_variant=closers.CLOSER_VARIANT, agent_wall_deadline_seconds=plan['agent_wall_deadline_seconds'])
    for r in runs:
        for d in ('agents', 'judges', 'extra', 'wanted'):
            (out / 'runs' / r['run'] / d).mkdir(parents=True)
    write(out / 'metadata.json', dict(protocol='swarm-closer-replay-v1', plan=str(a.plan), plan_sha256=sha(a.plan),
                                      serving=plan.get('serving'), runner_sha256=sha(Path(__file__)),
                                      closers_sha256=sha(HERE / 'closers.py'), run_variants_sha256=sha(HERE / 'run_variants.py'),
                                      runs=[str(r['dir']) for r in runs], cohort=cohort_list(runs),
                                      case_list=str(a.case_list) if a.case_list else None,
                                      case_list_sha256=sha(a.case_list) if a.case_list else None,
                                      cost_note='client_tokens are client-side completion tokens only; server-side cost '
                                                'comes from the arm driver fleet counters', source=str(source), closer_variant=closers.CLOSER_VARIANT,
                                      seed_offset=offset, max_closers_per_case=max_closers, endpoints=a.endpoints, max_per_endpoint=a.max_per_endpoint,
                                      started_utc=datetime.now(timezone.utc).isoformat(), admission=adm))
    slots, lock, stop, rows = closers.EndpointSlots(a.endpoints, a.max_per_endpoint), threading.Lock(), threading.Event(), []
    jobs = [(r, c) for r in runs for c in r['cases']]

    def work(job):
        run, c = job
        if stop.is_set():
            return
        task, row = c['task'], c['row']
        try:
            rec = closers.run_case(cplan, source, out / 'runs' / run['run'], task, c['seed'], c['case_index'],
                                   lambda wanted, seg=c['seg']: closers.case_leads(seg, row, wanted, task['target']),
                                   slots, a.endpoints, offset, max_closers=max_closers)
        except Exception as exc:
            with lock:
                stop.set()
                rows.append(dict(run=run['run'], task_id=task['id'], seed=c['seed'], error=f'{type(exc).__name__}: {exc}'))
            return
        rec = dict(run=run['run'], **rec)
        with lock:
            rows.append(rec)
            if rec['infra']:
                stop.set()
            with (out / 'cases.jsonl').open('a') as stream:
                stream.write(json.dumps(rec) + '\n')
            print(json.dumps(dict(done=len(rows), total=len(jobs), run=run['run'], task=task['id'], seed=c['seed'],
                                  closers=len(rec['closers']), rescue=rec['rescue'], wrong=rec['wrong'])), flush=True)

    start = time.monotonic()
    with ThreadPoolExecutor(max(1, min(len(jobs), 4 * a.max_per_endpoint))) as pool:
        list(pool.map(work, jobs))
    meta = read(out / 'metadata.json')
    summary = {}
    for r in runs:
        mine = [x for x in rows if x.get('run') == r['run'] and 'error' not in x]
        summary[r['run']] = dict(unanswered=len(r['cases']), cases=len(mine), closers=sum(len(x['closers']) for x in mine),
                                 skipped_closers=sum(x['skipped_closers'] for x in mine),
                                 rescued=sum(x['rescue'] for x in mine), solved=sum(x['solved'] for x in mine),
                                 wrong=sum(x['wrong'] for x in mine), client_tokens=sum(x['client_tokens'] for x in mine))
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=round(time.monotonic() - start, 1),
                stopped=stop.is_set(), errors=[x for x in rows if 'error' in x], summary=summary)
    write(out / 'metadata.json', meta)
    print(json.dumps(summary))
    return int(bool(meta['errors']) or meta['stopped'])


if __name__ == '__main__':
    raise SystemExit(main())
