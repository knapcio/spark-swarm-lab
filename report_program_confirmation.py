#!/usr/bin/env python3
"""Offline fresh-program confirmation report; plan-only until complete and independently audited."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import shutil
import sys

from csp_tasks import graph_digest, load_tasks
from report_completed_studies import crossed_program_statistics, program_report, save_report
from run_program_confirmation import PLAN_SHA, completed_programs, validate_report

HERE = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
read = lambda p: json.loads(Path(p).read_text())

def require(condition, message):
    if not condition:
        raise ValueError(message)

def validate(directory, audit, expected_graphs=96):
    """Read grades only after complete metadata and an independently hash-bound audit."""
    directory, audit = Path(directory), Path(audit)
    meta, receipt = read(directory/'metadata.json'), read(audit)
    require(meta.get('complete') is True and meta.get('verified') is True and meta.get('incomplete') is False
        and meta.get('completed_jobs') == meta.get('planned_jobs') == expected_graphs*8
        and meta.get('missing_jobs') == 0 and not meta.get('faults') and meta.get('completed_utc'), 'Incomplete or faulty confirmation')
    require(receipt.get('verified') is True and receipt.get('complete') is True
        and receipt.get('completed_jobs') == expected_graphs*8, 'Independent complete audit PASS required')
    pins = receipt.get('input_sha256', {})
    files = [directory/n for n in ('metadata.json','summary.json','grades.jsonl','bindings.json','corpus.json')]
    for p in files:
        keys = [str(p), str(p.resolve())]
        if p.resolve().is_relative_to(HERE): keys.append(str(p.resolve().relative_to(HERE)))
        require(any(pins.get(k) == sha(p) for k in keys), 'Independent audit hash missing/changed: '+p.name)
    selection = HERE/'PROGRAM_CONFIRMATION_SELECTION.json'
    require(sha(selection) == PLAN_SHA == meta.get('upstream_plan_sha256')
        and read(selection)['dataset_sha256'] == meta.get('dataset_sha256'), 'Prospective corpus/plan mismatch')
    before = meta.get('source_before')
    require(before and before == meta.get('source_after') and meta.get('source_changed_during_run') is False,
        'Source before/after mismatch')
    for name, expected in before.items():
        require(expected is not None and Path(name).is_file() and sha(name) == expected, 'Bound source changed/missing: '+name)
    identity = meta.get('runner_source', {})
    require(identity == meta.get('runner_source_after') and identity.get('tracked_clean') is True
        and identity.get('source_files_tracked') is True, 'Confirmation runner identity missing/changed')
    require(meta.get('model_calls') == 0 and len(meta.get('final_idle_health', [])) == 4
        and all(x.get('idle') is True and x.get('healthy') is True for x in meta['final_idle_health']), 'Zero-model/final drain receipt missing')
    require(sha(directory/'corpus.json') == meta.get('corpus_sha256') == meta.get('dataset_sha256')
        and sha(directory/'bindings.json') == meta.get('bindings_sha256'), 'Corpus/bindings SHA mismatch')
    tasks = load_tasks(directory/'corpus.json', 'evaluation'); by_task = {t['id']:t for t in tasks}
    require(len(tasks) == len(by_task) == len({graph_digest(t) for t in tasks}) == expected_graphs, 'Exact unique corpus grid required')
    bindings = read(directory/'bindings.json'); by_program = {(b['seed'],b['arm']):b for b in bindings}
    require(len(bindings) == len(by_program) == 8 and {s for s,a in by_program} == {1,2,3,4}
        and {a for s,a in by_program} == {'sequential16','independent4'}, 'All eight original programs required')
    rows = [json.loads(line) for line in (directory/'grades.jsonl').read_text().splitlines() if line.strip()]
    seen, job_ids = set(), set()
    for row in rows:
        key = (row['seed'],row['arm'],row['task_id']); program = by_program.get(key[:2]); task = by_task.get(key[2])
        require(key not in seen and row.get('job_id') not in job_ids and program and task, 'Duplicate/foreign grade')
        seen.add(key); job_ids.add(row['job_id'])
        require(row.get('infrastructure') is False and type(row.get('solved')) is bool, 'Missing/true infrastructure or outcome flag')
        source = directory/f"selected-s{key[0]}-{key[1]}.py"; code = source.read_text()
        require(row.get('host') == program['host'] == f'Spark_{key[0]:02d}' and row.get('code_sha256') == program['code_sha256'] == sha(source)
            and row.get('graph_sha256') == graph_digest(task), 'Program/graph/host binding mismatch')
        identity = {k:row[k] for k in ('seed','arm','host','task_id','graph_sha256','code_sha256')}
        require(hashlib.sha256(json.dumps(identity,sort_keys=True).encode()).hexdigest() == row['job_id'], 'Job identity hash mismatch')
        grade = row['report']; validate_report(task, grade)
        if grade.get('proof') is not None:
            require(grade['solved'] is grade['proof']['solved'], 'Negative grade conflicts with exact proof')
        payload = json.dumps(dict(code=code,function_name='solve',calls=[dict(args=[task['vertex_count'],task['color_count'],task['edges']],kwargs={})],timeout=10),allow_nan=False)
        require(grade.get('child_payload_sha256') == hashlib.sha256(payload.encode()).hexdigest()
            and grade.get('cleanup_ok') is True and row['solved'] is grade['solved'], 'Payload/cleanup/outer grade mismatch')
    require(len(rows) == len(seen) == expected_graphs*8 and seen == {(s,a,t) for s,a in by_program for t in by_task}, 'Incomplete exact 768-job grid')
    summary = read(directory/'summary.json')
    for arm in ('sequential16','independent4'):
        arm_rows = [r for r in rows if r['arm'] == arm]; stored = summary['arms'][arm]
        require(stored == dict(planned_jobs=expected_graphs*4,recorded_jobs=len(arm_rows),known_solved=sum(r['solved'] for r in arm_rows),
            known_unsolved=sum(not r['solved'] for r in arm_rows),unknown_outcomes=0), 'Summary count mismatch')
    return meta, bindings, rows, files

def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__); p.add_argument('input', type=Path)
    p.add_argument('--audit', type=Path); p.add_argument('--output', type=Path)
    p.add_argument('--run', action='store_true'); p.add_argument('--plot', action='store_true')
    args = p.parse_args(argv)
    if not args.run:
        print(json.dumps(dict(mode='plan',input=str(args.input),graphs=96,programs=8,grades=768,model_calls=0,
            required='Complete verified metadata, independent hash-bound Astra audit PASS and root CPU window',bootstrap_repetitions=5000)))
        return 0
    require(args.audit and args.output and not args.output.exists(), 'Audit receipt and new output directory required')
    meta, bindings, rows, files = validate(args.input, args.audit)
    master = Path(meta['program_run']); expected, original_files = completed_programs(master, {'arms':['sequential16','independent4']})
    require(bindings == expected, 'Original frozen program bindings differ')
    original, _ = program_report(master, 5000)  # Audit original training once; never pool its twelve graphs with fresh96.
    report = crossed_program_statistics([dict(task_id=r['task_id'],seed=r['seed'],arm=r['arm'],solved=r['solved']) for r in rows],5000,20261115)
    report.update(training_costs=original['training_costs'],additional_model_calls=0,original_training_model_calls=128,
        original12_report='results/program-search-v1-analysis',dataset_sha256=meta['dataset_sha256'],source=meta['runner_source'],
        scope='Fresh96 same-generator graphs; four paired frozen-program training seeds. Task-only intervals condition on frozen programs; crossed intervals resample graph and training-seed labels. All-pass bootstrap intervals can degenerate and do not imply true/general100% correctness. Original12 remain separate. Historical training charged once/program; zero additional model calls; remote CPU cost unknown.',
        grade_status_counts=dict(Counter(r['report']['status'] for r in rows)),remote_cpu_seconds=None)
    files += [args.audit] + original_files + [args.input/f"selected-s{b['seed']}-{b['arm']}.py" for b in bindings]
    inputs = {str(f):sha(f) for f in files}; report['input_sha256'] = dict(original['input_sha256'], **inputs)
    args.output.mkdir(parents=True); save_report(args.output/'fresh96',report,args.plot)
    evidence = args.output/'evidence'; evidence.mkdir()
    for f in files[:5] + files[-8:]: shutil.copyfile(f,evidence/f.name)
    shutil.copyfile(args.audit,evidence/'independent-audit.json')
    manifest = dict(scope=report['scope'],command=['python3','report_program_confirmation.py',*sys.argv[1:]],input_sha256=report['input_sha256'],
        source_sha256={n:sha(HERE/n) for n in ('report_program_confirmation.py','test_report_program_confirmation.py','report_completed_studies.py','run_program_confirmation.py','csp_tasks.py')},
        files={str(f.relative_to(args.output)):sha(f) for f in args.output.rglob('*') if f.is_file()},raw_inputs_modified=False,evidence_copies='Byte-identical grade/corpus/bindings/metadata/summary and eight selected-source copies; original twelve graphs not pooled')
    require(all(sha(f) == h for f,h in inputs.items()), 'Raw inputs changed during reporting')
    (args.output/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n'); print('Wrote',args.output)
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
