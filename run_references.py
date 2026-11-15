#!/usr/bin/env python3
"""Separate quality references, plan-only by default. No service lifecycle actions."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import importlib
import json
from pathlib import Path
import sys
import threading
import time
from urllib.parse import urlsplit

from reference_worker import HERE, OPUS, SENTINEL, require, sha, source_pin, verify_gate

METADATA = {'arithmetic': 'runs/evaluation-v2-arithmetic-s1/metadata.json', 'coding': 'runs/evaluation-v2-coding-s1/metadata.json'}
CURATED_METADATA = {domain: f'results/evaluation-v2/{domain}-s1/metadata.json' for domain in METADATA}
ARMS = {'arithmetic': 'direct_thinking_8k', 'coding': 'direct_thinking'}


def replace_arg(command, flag, value):
    result = list(command)
    result[result.index(flag) + 1] = str(value)
    return result


def build_cases(provider, model, endpoint, output, source, cli):
    """Copy frozen direct case templates; replace transport/output/replicate only."""
    cases, metadata_hashes = [], {}
    for domain, relative in METADATA.items():
        path = HERE / relative
        if not path.is_file():
            relative = CURATED_METADATA[domain]
            path = HERE / relative
        meta = json.loads(path.read_text())
        metadata_hashes[relative] = sha(path)
        templates = [c for c in meta['cases'] if c['arm'] == ARMS[domain]]
        require(len(templates) == (24 if domain == 'arithmetic' else 18), 'Frozen direct template matrix mismatch')
        require(len({c['task_id'] for c in templates}) == len(templates), 'Duplicate direct task template')
        for seed in (1, 2, 3):
            for template in templates:
                case = dict(template)
                stem = f"{domain}-{case['task_id']}-s{seed}"
                forwarded = list(case['command'][2:])
                for flag, value in [('--seed', seed), ('--endpoint', endpoint), ('--events', output / (stem + '.jsonl'))]:
                    forwarded = replace_arg(forwarded, flag, value)
                if domain == 'arithmetic':
                    forwarded = replace_arg(forwarded, '--model', model)
                else:
                    for flag, filename in [('--tasks', 'tasks.json'), ('--tests', 'hidden-tests.json')]:
                        forwarded = replace_arg(forwarded, flag, source / 'datasets/coding-v1' / filename)
                require(forwarded[forwarded.index('--max-tokens') + 1] == '8192', 'Frozen direct output cap mismatch')
                command = [sys.executable, str(HERE / 'reference_worker.py'), '--run', '--provider', provider,
                           '--source', str(source), '--domain', domain, '--model', model, '--cli', cli,
                           '--transport-record', str(output / (stem + '.transport.jsonl')), '--'] + forwarded
                case.update(domain=domain, seed=seed, endpoint=endpoint, arm=ARMS[domain], command=command,
                            events=str(output / (stem + '.jsonl')), stdout=str(output / (stem + '.stdout.log')),
                            stderr=str(output / (stem + '.stderr.log')), shared_endpoint=True, stop_on_solution=False, server_metrics=False)
                cases.append(case)
    require(len(cases) == 126, 'Reference matrix must contain 126 cases')
    return cases, metadata_hashes


def assess_attempt(row, records):
    """Separate a dispatched task exhausting its budget from observed infrastructure.

    A killed coding grade still needs owner-scoped cleanup before any next case.
    Missing end-of-run counters/usage remain unknown; no zero is substituted.
    """
    starts = [e for e in records if e.get('type') == 'request_start']
    ends = [e for e in records if e.get('type') == 'request_end']
    deadline = row.get('deadline') is True
    result = dict(reference_attempt_status='task_budget_exhausted' if deadline else 'completed',
                  reference_operational_halt_reason=None,
                  reference_infrastructure_count_unknown=row.get('infrastructure_failures') is None,
                  reference_usage_complete=not row.get('unfinished_calls') and not row.get('missing_prompt_usage') and not row.get('missing_completion_usage'),
                  reference_output_cap_reached=True if row.get('length_finishes') else
                      False if ends and all(e.get('finish_reason') is not None for e in ends) else None)
    fault = None
    if row.get('controller_error') or row.get('malformed_lines') or row.get('infrastructure_failures') or any(
            e.get('infrastructure_error') or e.get('kind') == 'client_infrastructure' for e in records):
        fault = 'observed_controller_protocol_or_infrastructure_fault'
    elif any(e.get('error') and e.get('response') is None and e.get('finish_reason') != 'length' for e in ends):
        fault = 'observed_or_ambiguous_transport_failure'
    elif not (row.get('calls') == len(starts) == 1 and starts[0].get('request_id')
              and row.get('completed_calls') == len(ends) <= 1
              and row.get('unfinished_calls') == 1 - len(ends)
              and all(e.get('request_id') == starts[0]['request_id'] for e in ends)):
        fault = 'missing_or_inconsistent_single_call_dispatch_evidence'
    elif deadline:
        if not (row.get('controller_stop') is True and row.get('status') == 'deadline'
                and row.get('returncode') in (0, -15, -9, 143, 137)
                and any(e.get('type') == 'controller_stop' and e.get('deadline') is True
                        and e.get('returncode') == row.get('returncode') for e in records)):
            fault = 'deadline_without_expected_controlled_process_exit'
        elif row.get('solved') and not any(e.get('type') in ('reward', 'puzzle_end', 'run_end') and e.get('solved') for e in records):
            fault = 'verified_outcome_missing_from_trace'
    elif not (row.get('status') == 'complete' and row.get('returncode') == 0 and len(ends) == 1
              and row.get('infrastructure_failures') == 0):
        fault = 'unexpected_process_or_completion_state'
    if fault:
        result.update(reference_attempt_status='requires_review', reference_operational_halt_reason=fault)
    elif row.get('domain') == 'coding':
        active = {e.get('evaluation_id') for e in records if e.get('type') == 'evaluation_start'}
        ended = {e.get('evaluation_id') for e in records if e.get('type') == 'evaluation_end'}
        if active - ended:
            result['reference_operational_halt_reason'] = 'active_coding_grade_requires_exact_owner_cleanup_review'
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--provider', choices=['opus', 'deepseek'], required=True)
    parser.add_argument('--model', help='Exact verified served model ID; Opus defaults to pinned preflight ID')
    parser.add_argument('--endpoint', help='Verified local DeepSeek OpenAI /v1 endpoint; never restored by this script')
    parser.add_argument('--source', type=Path, default=HERE / '.runtime/evaluation-v2-source')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--cli', default=str(Path.home() / '.local/bin/claude'))
    parser.add_argument('--run', action='store_true')
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args(argv)
    model = args.model or (OPUS if args.provider == 'opus' else None)
    require(model is not None, 'DeepSeek needs an exact verified served --model')
    endpoint = SENTINEL if args.provider == 'opus' else args.endpoint
    require(endpoint is not None, 'DeepSeek needs its later verified --endpoint')
    url = urlsplit(endpoint)
    require(url.scheme in ('http', 'https') and url.hostname and not url.username and not url.password and not url.query and not url.fragment, 'Endpoint must contain no credentials/query/fragment')
    if args.provider == 'opus':
        require(model == OPUS, 'Opus model must match exact preflight ID')
    output = (args.output or HERE / 'runs' / ('reference-' + args.provider + '-PLANNED')).resolve()
    source = args.source.resolve()
    cases, templates = build_cases(args.provider, model, endpoint, output, source, args.cli)
    plan = dict(protocol='separate-strong-model-reference-v1', mode='run' if args.run and not args.plan else 'plan',
                provider=args.provider, model=model, endpoint=endpoint, cases=cases, template_sha256=templates,
                output=str(output), source=str(source), attempts=126, replicates=[1, 2, 3], distinct_tasks=dict(arithmetic=24, coding=18),
                scheduling='Four persistent case slots share one provider endpoint; coding retains its original paired grader host',
                task_deadline_seconds=180, stop_on_solution=False, server_metrics=False,
                budget_accounting='Dispatched controlled180s deadlines are task-budget outcomes; retain verifier proof/partial traces and unknown cost. Observed faults halt. A killed coding grade requires owner cleanup review.',
                cost_scope='Completed client/provider usage only; global/server token cost unknown. No vLLM metrics or exclusive-endpoint claim.',
                comparison_scope='Separate quality reference, never pooled with Nemotron; Opus effort/seed/temperature and four-GPU DeepSeek resources are not equivalent settings.',
                gate=str(HERE / 'runs/throughput-followup-v2-complete.json'))
    if not args.run or args.plan:
        print(json.dumps(plan, indent=2))
        return 0
    gate = verify_gate(HERE)
    pin = source_pin(source)
    require(not output.exists(), 'Reference output exists; no implicit overwrite/resume')
    # Import execution/accounting from the same frozen source as the task templates.
    sys.path.insert(0, str(source))
    benchmark = importlib.import_module('run_benchmark')
    coding = importlib.import_module('run_coding_benchmark')
    own_pins = {name: sha(HERE / name) for name in ['reference_worker.py', 'run_references.py']}
    output.mkdir(parents=True)
    metadata_path, summary_path = output / 'metadata.json', output / 'summary.json'
    metadata = dict(plan, started_utc=datetime.now(timezone.utc).isoformat(), source_pin=pin, adapter_sha256=own_pins, completion_gate=gate,
                    usage_note='Missing usage stays unknown; no CLI cost estimate is treated as billed cost; seeds are repetition labels where unsupported.')
    metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    rows, errors, lock = [], [], threading.Lock()
    start = time.monotonic()
    def worker(slot):
        for case in [c for c in cases if c['slot'] == slot]:
            with lock:
                if errors:
                    break
            try:
                require(all(sha(HERE / n) == h for n, h in own_pins.items()) and source_pin(source) == pin, 'Adapter/frozen source changed')
                row = benchmark.execute(case, 180)
                row.update(domain=case['domain'], provider=args.provider, reference_model=model)
                if case['domain'] == 'coding':
                    row = coding.coding_metrics(case, row)
            except Exception as exc:
                with lock:
                    errors.append(dict(task_id=case['task_id'], seed=case['seed'], failure_classification=type(exc).__name__, reason='Reference controller/source exception; remaining cases halted'))
                return
            records, _ = benchmark.read_trace(Path(case['events']))
            row.update(assess_attempt(row, records))
            failed = row['reference_operational_halt_reason'] is not None
            with lock:
                rows.append(row)
                if failed:
                    errors.append(dict(task_id=case['task_id'], seed=case['seed'], status=row.get('status'), reason=row['reference_operational_halt_reason']))
                summary_path.write_text(json.dumps(rows, indent=2) + '\n')
                print(json.dumps(dict(completed=len(rows), total=126, task_id=case['task_id'], domain=case['domain'], status=row.get('status'))), flush=True)
    try:
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(worker, range(4)))
    finally:
        try:
            final_pin = source_pin(source)
        except Exception:
            final_pin = None
            errors.append(dict(reason='Final frozen source verification failed'))
        metadata.update(completed_utc=datetime.now(timezone.utc).isoformat(), batch_wall_seconds=time.monotonic() - start,
                        completed_cases=len(rows), incomplete=len(rows) != 126, errors=errors,
                        task_budget_exhausted_cases=sum(r.get('reference_attempt_status') == 'task_budget_exhausted' for r in rows),
                        usage_incomplete_cases=sum(not r.get('reference_usage_complete') for r in rows),
                        infrastructure_count_unknown_cases=sum(r.get('reference_infrastructure_count_unknown', False) for r in rows),
                        final_source_pin=final_pin, final_adapter_sha256={n: sha(HERE / n) for n in own_pins})
        metadata['output_sha256'] = {p.name: sha(p) for p in output.iterdir() if p.is_file() and p != metadata_path}
        metadata['source_changed_during_run'] = metadata['final_source_pin'] != pin or metadata['final_adapter_sha256'] != own_pins
        metadata_path.write_text(json.dumps(metadata, indent=2) + '\n')
    return int(bool(errors) or len(rows) != 126 or metadata['source_changed_during_run'])


if __name__ == '__main__':
    raise SystemExit(main())
