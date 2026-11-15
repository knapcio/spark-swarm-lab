#!/usr/bin/env python3
"""Plan-first zero-LLM coloring controls; no witness, API, GPU or tool execution."""
import argparse
import csv
from datetime import datetime, timezone
import hashlib
import inspect
import json
from pathlib import Path
import platform
import random
import time
from types import FunctionType

from csp_search import classical_search
from csp_tasks import canonical_json, load_tasks, verify_assignment, worker_task

HERE = Path(__file__).resolve().parent
SEEDS = (1, 2, 3)
PARAMETERS = {
    'genetic': dict(population_size=32, generations=128, max_fitness_evaluations=3616),
    'random_assignment': dict(scored_assignments=16),
    'min_conflicts': dict(restarts=4, steps_per_restart=1024, colors_scored='all, including current; full assignment fitness'),
}
WALL_SECONDS = 30


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def digest(value):
    return hashlib.sha256(canonical_json(value).encode()).hexdigest()


class WorkBudget(Exception):
    pass


class Scorer:
    """Every scored assignment gets the full exact verifier; no fitness shortcuts."""
    def __init__(self, task, seconds=WALL_SECONDS, clock=time.monotonic):
        self.task, self.clock, self.seconds = worker_task(task), clock, seconds
        self.start, self.cpu_start = clock(), time.process_time()
        self.evaluations, self.best, self.first_solution_seconds = 0, None, None

    def evaluate(self, values):
        if self.clock() - self.start >= self.seconds:
            raise WorkBudget('wall deadline')
        proof = verify_assignment(self.task, {'assignment': values})
        self.evaluations += 1
        elapsed = self.clock() - self.start
        if self.best is None or proof['conflicts'] < self.best['verification']['conflicts']:
            self.best = dict(assignment=list(values), verification=proof)
        if elapsed >= self.seconds:
            raise WorkBudget('wall deadline')  # Work completed late cannot become an in-budget success.
        if proof['solved'] and self.first_solution_seconds is None:
            self.first_solution_seconds = elapsed
        return proof


def _genetic(task, seed, scorer):
    # Reuse the existing GA bytecode with a private verifier binding. No shared
    # module global is patched, and its sampling/selection logic is unchanged.
    def counted_verify(public, candidate):
        return scorer.evaluate(candidate['assignment'])
    globals_copy = dict(classical_search.__globals__, verify_assignment=counted_verify)
    algorithm = FunctionType(classical_search.__code__, globals_copy, classical_search.__name__)
    return algorithm(task, seed, generations=128, population_size=32)


def _random_assignment(task, rng, scorer):
    # Exactly sixteen samples, including duplicates and any samples after a solution.
    for _ in range(16):
        scorer.evaluate([rng.randrange(task['color_count']) for _ in range(task['vertex_count'])])


def _min_conflicts(task, rng, scorer):
    n, k = task['vertex_count'], task['color_count']
    for _ in range(4):
        values = [rng.randrange(k) for _ in range(n)]
        proof = scorer.evaluate(values)
        for _ in range(1024):
            if proof['solved']:
                return
            vertices = sorted({v for edge in proof['violating_edges'] for v in task['edges'][edge]})
            vertex = rng.choice(vertices)
            choices = []
            for color in range(k):
                alternative = list(values)
                alternative[vertex] = color
                choices.append((alternative, scorer.evaluate(alternative)))
            minimum = min(p['conflicts'] for _, p in choices)
            values, proof = rng.choice([pair for pair in choices if pair[1]['conflicts'] == minimum])
            if proof['solved']:
                return


def run_control(task, arm, seed, seconds=WALL_SECONDS, clock=time.monotonic):
    if arm not in PARAMETERS or type(seed) is not int or not 0 < seconds <= WALL_SECONDS:
        raise ValueError('Known control, integer seed and positive wall cap at most30s required')
    task, rng = worker_task(task), random.Random(seed)
    scorer, status = Scorer(task, seconds, clock), 'complete'
    try:
        if arm == 'genetic':
            _genetic(task, seed, scorer)
        elif arm == 'random_assignment':
            _random_assignment(task, rng, scorer)
        else:
            _min_conflicts(task, rng, scorer)
    except WorkBudget:
        status = 'budget_exhausted'
    # Final independent full-assignment check is explicit and charged separately.
    final = verify_assignment(task, {'assignment': scorer.best['assignment']}) if scorer.best else None
    solved = bool(final and final['solved'] and scorer.first_solution_seconds is not None)
    wall = clock() - scorer.start
    return dict(arm=arm, seed=seed, status=status, solved=solved,
                best_assignment=scorer.best['assignment'] if scorer.best else None,
                verification=final, fitness_evaluations=scorer.evaluations,
                final_verifier_calls=int(final is not None),
                fitness_edge_constraint_checks=scorer.evaluations * len(task['edges']),
                fitness_vertex_domain_checks=scorer.evaluations * task['vertex_count'],
                final_edge_constraint_checks=len(task['edges']) if final else 0,
                first_verified_solution_seconds=scorer.first_solution_seconds,
                wall_seconds=wall, cpu_seconds=time.process_time() - scorer.cpu_start,
                wall_budget_seconds=seconds, model_calls=0,
                work_scope='Full fitness assignments and graph-edge/domain checks; not CPU instructions or LLM-call equivalents. Wall cap checked at fitness boundaries; final verification overhead included.')


def source_hashes():
    return {name: sha(HERE / name) for name in ['csp_classical.py', 'csp_search.py', 'csp_tasks.py', 'csp_social.py', 'harness.py', 'reference_worker.py']}


def make_plan(dataset):
    tasks = load_tasks(dataset)
    # Read only this public corpus to retain its split labels; never sibling witnesses.
    public = json.loads(dataset.read_text())
    splits = {t['id']: t['split'] for t in public['tasks']}
    if sum(splits[t['id']] == 'development' for t in tasks) != 4 or sum(splits[t['id']] == 'evaluation' for t in tasks) != 12:
        raise ValueError('Expected all4 development and12 evaluation tasks')
    cases = [dict(index=i, task_id=task['id'], split=splits[task['id']], seed=seed, arm=arm, task_sha256=digest(task))
             for i, (seed, task, arm) in enumerate((seed, task, arm) for seed in SEEDS for task in tasks for arm in PARAMETERS)]
    return dict(protocol='zero-llm-csp-controls-v1', dataset=str(dataset.resolve()), dataset_sha256=sha(dataset),
                parameters=PARAMETERS, parameters_sha256=digest(dict(controls=PARAMETERS, wall_seconds=WALL_SECONDS, seeds=list(SEEDS))), wall_seconds_per_case=WALL_SECONDS,
                seeds=list(SEEDS), cases=cases, source_sha256=source_hashes(),
                genetic_function_sha256=hashlib.sha256(inspect.getsource(classical_search).encode()).hexdigest(),
                output_scope='Separate CPU controls, never fed to LLM agents. No primitive-work or mutation count equals an LLM call.'), {t['id']: t for t in tasks}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=HERE / 'datasets/csp-v1/tasks.json')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--gate-root', type=Path, default=HERE)
    parser.add_argument('--plan', action='store_true')
    parser.add_argument('--run', action='store_true')
    args = parser.parse_args(argv)
    plan, tasks = make_plan(args.dataset)
    if not args.run or args.plan:
        print(json.dumps(dict(mode='plan', **plan), indent=2))
        return 0
    if args.output is None:
        parser.error('--run requires a new --output directory')
    from reference_worker import verify_gate
    gate = verify_gate(args.gate_root)
    args.output.mkdir(parents=True, exist_ok=False)
    with (args.output / 'plan.json').open('x') as stream:
        json.dump(dict(plan, gate=gate), stream, indent=2)
    started = datetime.now(timezone.utc).isoformat()
    rows = []
    try:
        for case in plan['cases']:
            if source_hashes() != plan['source_sha256'] or sha(args.dataset) != plan['dataset_sha256']:
                raise RuntimeError('Classical source/data changed; partial outputs retained')
            row = dict(case, **run_control(tasks[case['task_id']], case['arm'], case['seed']))
            with (args.output / f"case-{case['index']:03d}.json").open('x') as stream:
                json.dump(row, stream, indent=2)
            rows.append(row)
    finally:
        final_dataset_sha256 = sha(args.dataset) if args.dataset.is_file() else None
        source_changed = source_hashes() != plan['source_sha256']
        data_changed = final_dataset_sha256 != plan['dataset_sha256']
        incomplete = len(rows) != len(plan['cases']) or source_changed or data_changed
        with (args.output / 'results.json').open('x') as stream:
            json.dump(rows, stream, indent=2)
        fields = ['index','task_id','split','arm','seed','status','solved','fitness_evaluations',
                  'final_verifier_calls','fitness_edge_constraint_checks','fitness_vertex_domain_checks',
                  'first_verified_solution_seconds','wall_seconds','cpu_seconds','model_calls']
        with (args.output / 'results.csv').open('x', newline='') as stream:
            writer = csv.DictWriter(stream, fields, extrasaction='ignore'); writer.writeheader(); writer.writerows(rows)
        with (args.output / 'metadata.json').open('x') as stream:
            json.dump(dict(started_utc=started, completed_utc=datetime.now(timezone.utc).isoformat(),
                           completed_cases=len(rows), planned_cases=len(plan['cases']), incomplete=incomplete, verified=not incomplete,
                           python=platform.python_version(), platform=platform.platform(),
                           source_changed=source_changed, final_dataset_sha256=final_dataset_sha256,
                           data_changed=data_changed, gate=gate), stream, indent=2)
    return int(incomplete)


if __name__ == '__main__':
    raise SystemExit(main())
