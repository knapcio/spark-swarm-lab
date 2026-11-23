#!/usr/bin/env python3
"""Closer replay (round-3 idea 1, stage 1): closers on the recorded failed agents of finished arms.

For every case of the given run directories that the arm left unanswered: one short Inkling call writes the wanted
list (T+x, T-x, T*x, T/x for each given number x); the recorded thinking text of each failed agent is scanned for
statements `a op b = v` with v on that list (tier 1) or v = target (tier 2) (regex and equality only); each failed
agent with a lead gets one closer (worker variant forced_original, original task + the lines); closer plans go to the
unchanged judge (run_variants.judge_with_reason); the first accepted plan of a case is its rescue and cancels the
other closers. The exact verifier only scores afterwards. Agent/judge records, seeds (1000*seed + offset + slot) and
the per-endpoint Slots cap are those of run_variants.run_agent.

--plan-only lists cases, failed agents and lead counts with no model call. Tier 1 is then ESTIMATED with the exact
wanted values (reporting only; in a run the model writes the list, so run-time tier-1 counts can differ).

usage: closer_replay.py --runs runs/A runs/B ... [--plan-only]
       closer_replay.py --runs ... --plan PLAN.json --admission ADM.json --output runs/NAME [--source DIR]
"""
import argparse
import json
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


def load_run(run_dir):
    """Unanswered cases of one recorded arm with their task, case index (run order) and the arm's token total."""
    run_dir = Path(run_dir)
    meta = read(run_dir / 'metadata.json')
    plan = meta['protocol']
    tasks = run_variants.plan_tasks(plan, HERE)
    index = {(t['id'], s): si * len(tasks) + ti for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)}
    by_id = {t['id']: t for t in tasks}
    rows = [json.loads(line) for line in (run_dir / 'cases.jsonl').read_text().splitlines() if line.strip()]
    seen, cases = set(), []
    for r in rows:
        if 'error' in r:
            continue
        key = (r['task_id'], r['seed'])
        require(key not in seen, f'duplicate case {key} in {run_dir}')  # a resumed arm would need its segments merged
        seen.add(key)
        if not r['answered']:
            cases.append(dict(row=r, task=by_id[r['task_id']], seed=r['seed'], case_index=index[key]))
    return dict(run=run_dir.name, dir=run_dir, cases=cases, arm_cases=len(seen),
                arm_tokens=sum(r.get('tokens', 0) for r in rows if 'error' not in r))


def plan_only(runs):
    report, total = [], dict(cases=0, failed_agents=0, missing_traces=0, tier1_agents=0, tier2_agents=0, closers=0,
                             tier1_lines=0, tier2_lines=0, cases_tier1=0, cases_any=0)
    for run in runs:
        agg = dict(run=run['run'], **{k: 0 for k in total})
        for c in run['cases']:
            task = c['task']
            wanted = closers.reference_wanted_values(task['numbers'], task['target'])
            rows = closers.case_leads(run['dir'], c['row'], wanted, task['target'])
            line = dict(run=run['run'], task_id=task['id'], seed=c['seed'], case_index=c['case_index'],
                        failed_agents=len(rows), missing_traces=sum(r['missing'] for r in rows),
                        tier1_agents=sum(bool(r['tier1']) for r in rows), tier2_agents=sum(bool(r['tier2']) for r in rows),
                        closers=sum(bool(r['lines']) for r in rows),
                        tier1_lines=sum(len(r['tier1']) for r in rows), tier2_lines=sum(len(r['tier2']) for r in rows))
            print(json.dumps(line))
            for k in ('failed_agents', 'missing_traces', 'tier1_agents', 'tier2_agents', 'closers', 'tier1_lines', 'tier2_lines'):
                agg[k] += line[k]
            agg['cases'] += 1
            agg['cases_tier1'] += line['tier1_agents'] > 0
            agg['cases_any'] += line['closers'] > 0
        report.append(agg)
        for k in total:
            total[k] += agg[k]
    for agg in report:
        print(json.dumps(dict(summary=agg)))
    print(json.dumps(dict(mode='plan', model_calls=0, tier1='estimated with exact wanted values (report only)', total=total)))
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
    p.add_argument('--plan-only', action='store_true')
    a = p.parse_args(argv)
    require(1 <= a.max_per_endpoint <= MAX_PER_ENDPOINT, 'max-per-endpoint must be 1..20')
    require(len(set(a.endpoints)) == len(a.endpoints), 'duplicate endpoints')
    runs = [load_run(r) for r in a.runs]
    if a.plan_only:
        return plan_only(runs)
    require(a.plan and a.output and a.admission, '--plan, --output and --admission are required for a run')
    plan = read(a.plan)
    out = a.output.resolve()
    require(not out.exists(), 'output exists')
    adm = read(a.admission)
    require(adm.get('verified') is True and 0 <= (datetime.now(timezone.utc) - datetime.fromisoformat(adm['verified_utc'])).total_seconds() <= 900,
            'Fresh admission')
    source = (a.source or HERE / plan.get('source_path', '.runtime/xl-source')).resolve()
    validate_source(source, plan['source_revision'])
    offset = plan.get('seed_offsets', {}).get('closer', closers.CLOSER_SEED_OFFSET)
    cplan = dict(agent_variant=closers.CLOSER_VARIANT, agent_wall_deadline_seconds=plan['agent_wall_deadline_seconds'])
    names = [r['run'] for r in runs]
    require(len(set(names)) == len(names), 'run directories must have distinct names')
    for r in runs:
        for d in ('agents', 'judges', 'extra', 'wanted'):
            (out / 'runs' / r['run'] / d).mkdir(parents=True)
    write(out / 'metadata.json', dict(protocol='swarm-closer-replay-v1', plan=str(a.plan), plan_sha256=sha(a.plan),
                                      serving=plan.get('serving'), runner_sha256=sha(Path(__file__)),
                                      closers_sha256=sha(HERE / 'closers.py'), run_variants_sha256=sha(HERE / 'run_variants.py'),
                                      runs=[str(r['dir']) for r in runs], source=str(source), closer_variant=closers.CLOSER_VARIANT,
                                      seed_offset=offset, endpoints=a.endpoints, max_per_endpoint=a.max_per_endpoint,
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
                                   lambda wanted: closers.case_leads(run['dir'], row, wanted, task['target']),
                                   slots, a.endpoints, offset)
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
        tokens = sum(x['tokens'] for x in mine)
        summary[r['run']] = dict(unanswered=len(r['cases']), cases=len(mine), closers=sum(len(x['closers']) for x in mine),
                                 rescued=sum(x['rescue'] for x in mine), solved=sum(x['solved'] for x in mine),
                                 wrong=sum(x['wrong'] for x in mine), tokens=tokens, arm_tokens=r['arm_tokens'],
                                 token_share=round(tokens / r['arm_tokens'], 4) if r['arm_tokens'] else None)
    meta.update(completed_utc=datetime.now(timezone.utc).isoformat(), wall_seconds=round(time.monotonic() - start, 1),
                stopped=stop.is_set(), errors=[x for x in rows if 'error' in x], summary=summary)
    write(out / 'metadata.json', meta)
    print(json.dumps(summary))
    return int(bool(meta['errors']) or meta['stopped'])


if __name__ == '__main__':
    raise SystemExit(main())
