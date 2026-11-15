#!/usr/bin/env python3
"""Prospective corpus/plan preparation only; no programs, model or grading calls."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time

from csp_tasks import PROTOCOL, canonical_json, generate, graph_digest, load_tasks, verify_assignment, worker_task

HERE = Path(__file__).resolve().parent
SEEDS = list(range(2026111601, 2026111609))
DATASET = HERE / 'datasets/program-confirmation-v1/tasks.json'
SELECTION = HERE / 'PROGRAM_CONFIRMATION_SELECTION.json'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def encoded(value):
    return (json.dumps(value, indent=2, ensure_ascii=False)+'\n').encode()


def prepare():
    original = load_tasks(HERE / 'datasets/csp-v1/tasks.json')
    upstream = json.loads((HERE / 'PROGRAM_SEARCH_SELECTION.json').read_text())
    for name, expected in upstream['source_sha256'].items():
        if sha(HERE / name) != expected:
            raise ValueError('Existing program-search source changed: '+name)
    seen = {graph_digest(task) for task in original}
    tasks, cells, validated = [], {}, 0
    for seed in SEEDS:
        public, private = generate(seed)  # EXACT existing dev4-first/eval12 RNG procedure.
        if len(public['tasks']) != 16 or [t['split'] for t in public['tasks']] != ['development']*4+['evaluation']*12:
            raise ValueError('Existing generator task order changed')
        for task in public['tasks']:
            witness = {'assignment': private['witnesses'][task['id']]['assignment']}
            if not verify_assignment(task, witness)['solved']:
                raise ValueError('Generated witness validation failed')
            validated += 1
        for task, design in zip(public['tasks'][4:], public['generator']['evaluation_design']):
            task = dict(task, id=f'confirm-s{seed}-'+task['id'])
            digest = graph_digest(task)
            if digest in seen:
                raise ValueError('Exact labeled-graph duplicate: refuse corpus freeze; no retries or seed replacement')
            seen.add(digest);tasks.append(task);cells[task['id']] = design
        del private, witness  # No witness file; no reference is retained in corpus/plan.
    expected_cells = {(n,k,d) for n in (24,40,64) for k in (3,4) for d in (20,40)}
    counts = Counter(tuple(cell) for cell in cells.values())
    if validated != 128 or len(tasks) != 96 or set(counts) != expected_cells or set(counts.values()) != {8}:
        raise ValueError('Expected128 witnesses/96 graphs/12 factorial cells times8 seeds')
    corpus = dict(protocol=PROTOCOL, generator=dict(protocol='fresh-program-confirmation-v1', seeds=SEEDS,
        procedure='Existing csp_tasks.generate(seed), all16 tasks in original order; discard dev4 after validating all16 witnesses, retain evaluation12 with seed-prefixed IDs.',
        evaluation_cells=cells, density_definition='Percentage of eligible cross-class pairs, rounded half up; original generator unchanged.',
        duplicate_policy='Reject any exact labeled-graph duplicate against original16 or within96; no retries, replacement seeds or isomorphism claim.',
        witness_policy='All128 generated witnesses verified in memory then discarded; no witness file or author-prompt input.',
        author_information='This corpus, its seeds and all outcomes are excluded from program-author prompts/feedback. Programs are trained only on the original4 development graphs.'), tasks=tasks)
    source_names = ['prepare_program_confirmation.py','csp_tasks.py','csp_program_grader.py','independent_code_grader.py',
                    'program_search.py','PROGRAM_SEARCH_SELECTION.json','datasets/csp-v1/tasks.json']
    plan = dict(protocol='prospective-fresh-program-confirmation-v1', prepared_utc=datetime.now(timezone.utc).isoformat(),
        status='PLAN_AND_CORPUS_ONLY; prepared before program-search outcomes. No runner, program execution, inference or confirmation grade has occurred.',
        dataset='datasets/program-confirmation-v1/tasks.json', dataset_sha256=hashlib.sha256(encoded(corpus)).hexdigest(),
        source_sha256={name:sha(HERE/name) for name in source_names}, generator_seeds=SEEDS,
        generation_validation=dict(original_graphs=16, generated_witnesses_checked=validated, retained_graphs=96,
            factorial_cells=12, graphs_per_cell=8, duplicate_graphs=0, witness_files_written=0),
        original_development=dict(dataset='datasets/csp-v1/tasks.json', dataset_sha256=sha(HERE/'datasets/csp-v1/tasks.json'),
            graphs=4, task_ids=[t['id']for t in json.loads((HERE/'datasets/csp-v1/tasks.json').read_text())['tasks']if t['split']=='development'],
            policy='Original4 development graphs unchanged; no new training, repairs, guidance or model calls.'),
        program_population=dict(arms=upstream['arms'], trained_seeds=upstream['seeds'], programs=8,
            policy='Evaluate ALL8 originally selected programs regardless of their original12 outcomes. Never select, repair, replace, retry or filter programs/graphs using fresh96 outcomes.',
            selected_source_sha256=None, binding_requirement='Before any fresh graph grade, persist and verify all8 original selected-source SHA256 values plus original development selection receipts. No fresh-result reselection.'),
        execution=dict(runner_prepared=False, model_calls=0, fresh_cpu_grades=768, fresh_container_per_graph=True,
            cpu_workers=4, scheduling='One serial CPU grading worker per node; all8 programs on all96 graphs exactly once.',
            timeout_seconds=10, memory_mib=256, cpu_per_container=1,
            image='python@sha256:c61cffc3bacb94ed026ff8b45d5114b7693dd0420baca0a1ace0e3d0ce9035fd',
            grader='csp_program_grader.evaluate_program; qualified independent_code_grader transport unchanged',
            failures='Candidate timeout/OOM/runtime/protocol/mutation/invalid/wrong assignments remain failures. Infrastructure, source drift or cleanup faults halt and preserve partial/unknown outcomes.',
            evidence='Retain exact source, original graph, candidate_output, outer graph proof, hashes, wall and cleanup/provenance; independently replay observed assignments. Remote CPU seconds remain unknown.'),
        admission=dict(automatic_launch=False, mandatory_precedence='Finish original study45, independent coding confirmation and CSP/program study first. Preserve mandatory reference/restoration scheduling; optional confirmation cannot displace them.',
            timing='Only after ALL8 programs have frozen source and completed original12 evaluation. May follow program stage if sufficient time and all Nemotron endpoints idle; otherwise after references during a separately qualified idle window.',
            cost='Nominal candidate-time ceiling768x10/4=1920s(32min), plus startup/SSH/inspection/cleanup. Provisionally allow45-60min plus fault review; not a measured ETA.',
            source_gate='Source/corpus/protocol freeze before program outcomes; later runner must verify original gates, all8 source bindings, exact grader/image, no unrelated work and owned cleanup before admission.'),
        inference=dict(scope='Same planted generator distribution and fixed12 factorial cells;96 fresh graph instances, not a new task contract or general solver correctness proof.',
            comparisons='Paired same96 graph blocks for all8 programs, retaining correlations among4 paired training seeds/episodes and shared task cells;768 grades are not768 independent tasks.',
            uncertainty='Report finite corpus counts, paired contrasts and graph/episode-aware uncertainty. If all pass, empirical bootstrap may degenerate; disclose that it gives no universal100% guarantee.',
            original_results='Keep original12 results and this later96-graph confirmation separately labeled. Fresh confirmation never replaces original scores.'))
    return corpus, plan


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write',action='store_true',help='Write only the new fixed corpus and plan; never run a program')
    args=parser.parse_args(argv);start=time.monotonic();corpus,plan=prepare()
    if args.write:
        if DATASET.exists() or SELECTION.exists():
            raise FileExistsError('Refusing existing corpus/selection; no overwrite or reseeding')
        DATASET.parent.mkdir(parents=True,exist_ok=True)
        with DATASET.open('xb')as stream:stream.write(encoded(corpus))
        with SELECTION.open('xb')as stream:stream.write(encoded(plan))
        if [worker_task(t)for t in corpus['tasks']]!=load_tasks(DATASET):
            raise AssertionError('Written public corpus did not round-trip through exact loader')
    print(json.dumps(dict(mode='write_plan_and_corpus'if args.write else'plan',graphs=96,witnesses_checked=128,
        program_grades_executed=0,model_calls=0,dataset_sha256=plan['dataset_sha256'],preparation_wall_seconds=time.monotonic()-start)))
    return 0


if __name__=='__main__':raise SystemExit(main())
