#!/usr/bin/env python3
"""Idea #1 CONFIRMATION plan generator (prepared 2026-11-27; NOT frozen): if the idea #1 screen (EXTEND_SCREEN_PLAN.json,
runs/extend-screen-v1) passes, confirm it on 12 FRESH failures of a NEW corpus run with the screen's frozen rule.

Selection: inkling/extend_plans.py's rule unchanged (failure = a length-forced agent at the 30,720 cap with its thinking
open, whose forced answer the judge rejected, in a case the run never solved; first failure per distinct puzzle in the
order run, seed, task_id, slot; puzzles ordered by sha256(extend_plans.SELECTION_SEED + ':' + corpus + ':' + task_id);
the first 12), applied to CONFIRM_RUNS only (the roll12fair baseline on arithmetic-hard-v27, a corpus generated after
the screen was frozen, so no confirmation puzzle can be a screen puzzle). Arms, budgets, judge, driver
(extend_replay.py) and the decision formula are the screen's: E > F is a PASS (confirmation), E <= F a STOP.

By default the plan is written with status DRAFT and cannot be run (extend_replay.py refuses a plan that is not FROZEN).
--freeze writes status FROZEN only if all of these hold, and refuses otherwise:
  * the screen report (results/extend-screen-v1/report.json) is complete and its decision is a PASS;
  * every confirmation run is complete: cases.jsonl holds every planned case (tasks x seeds of its metadata) once,
    none with an infrastructure fault;
  * exactly 12 eligible puzzles are selected and none is a screen puzzle.

One 96-case run is expected to yield fewer than 12 eligible puzzles (the screen's three runs gave 21); add further new
corpus runs with --run (repeatable, in order) before freezing.

usage: extend_confirm_plans.py --source-revision REV --output EXTEND_CONFIRM_PLAN.json [--root DIR] [--run NAME ...]
                               [--freeze]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import collab_plans  # noqa: E402
import extend_plans as ep  # noqa: E402

CONFIRM_RUNS = ('swarm-baseline-hard27-v1-roll12fair',)
STUDY = 'extend-confirm-v1'
SCREEN_PLAN, SCREEN_REPORT = 'EXTEND_SCREEN_PLAN.json', 'results/extend-screen-v1/report.json'


def run_problems(root, runs=CONFIRM_RUNS):
    problems = []
    for run in runs:
        d = Path(root) / 'runs' / run
        if not (d / 'cases.jsonl').exists():
            problems.append(f'{run}: no cases.jsonl')
            continue
        plan, indices = ep.case_indices(root, d)
        rows = ep.read_jsonl(d / 'cases.jsonl')
        keys = [(r['task_id'], r['seed']) for r in rows]
        if sorted(keys) != sorted(indices):
            problems.append(f'{run}: {len(set(keys))} of {len(indices)} planned cases recorded'
                            + (' (duplicates)' if len(keys) != len(set(keys)) else ''))
        if any(r.get('infra') for r in rows):
            problems.append(f'{run}: cases with infrastructure faults')
    return problems


def screen_problems(root):
    path = Path(root) / SCREEN_REPORT
    if not path.exists():
        return ['the screen has no report']
    report = json.loads(path.read_text())
    if report.get('status') != 'complete' or not str(report.get('decision', '')).startswith('PASS'):
        return [f"the screen did not pass: {report.get('decision')}"]
    return []


def make(root, revision, runs=CONFIRM_RUNS, freeze=False):
    items, eligible = ep.select(root, runs=runs)
    items = [dict(i, item_id=f'c{n:02d}') for n, i in enumerate(items)]
    screen = json.loads((Path(root) / SCREEN_PLAN).read_text()) if (Path(root) / SCREEN_PLAN).exists() else None
    overlap = sorted({i['puzzle_key'] for i in items} & {i['puzzle_key'] for i in (screen or {}).get('items', [])})
    problems = run_problems(root, runs) + ([f'puzzles shared with the screen: {overlap}'] if overlap else []) + \
        ([f'only {len(items)} eligible puzzles (12 required)'] if len(items) < ep.N_PUZZLES else [])
    if freeze:
        problems += screen_problems(root)
        if problems:
            raise ValueError('refusing to freeze: ' + '; '.join(problems))
    return dict(
        protocol='extend-screen-v1', study=STUDY, status='FROZEN' if freeze else 'DRAFT', screen='idea-1-confirmation',
        confirmation_of='extend-screen-v1', source_revision=revision, source_path=ep.SOURCE_PATH,
        driver='extend_replay.py',
        idea='astra IDEAS 2026-11-26 #1: confirmation on fresh failures of a new corpus (same frozen rule)',
        runs=list(runs), selection_rule=('inkling/extend_plans.py rule, unchanged (selection seed '
                                         f'{ep.SELECTION_SEED}), applied to {", ".join(runs)}'),
        selection_seed=ep.SELECTION_SEED, eligible_puzzles=eligible, items=items,
        draft_problems=[] if freeze else problems,
        arms=dict(extension='the same agent\'s recorded 30,720 thinking ids + another 30,720 thinking tokens, then '
                            'forced72\'s answer path within the 2,048 reserve (a replacement\'s 32,768 budget)',
                  fresh='a fresh agent (worker seed agent_seed + 1,000,003 k), thinking 30,720 + answer 2,048'),
        attempts_per_arm=2,
        judge=('run_variants.judge_once (one attempt, no judge-level retry), unchanged prompt; the dispatched seed is '
               'derived from the attempt pair and judge stage only; transport retries off'),
        decision_rule=dict(rescue='a puzzle is rescued by an arm if any of its attempts is accepted by the judge and '
                                  'solved by the strict exact verifier (every submitted move legal, target appeared)',
                           stop='STOP if extensions rescue no more puzzles than fresh agents (E <= F)',
                           pass_='PASS (confirmation) if E > F',
                           report='wrong acceptances per arm, exact sign test over discordant puzzles'),
        fleet=collab_plans.FLEET, per_node=ep.PER_NODE, nodes=4,
        judge_code_sha256=collab_plans.judge_hashes(ROOT), serving=collab_plans.serving(ROOT),
        execution=f'extend_replay.py --plan PLAN --run --output runs/{STUDY} from a clean worktree of the source '
                  'revision: fleet lease, admission, <= per_node per node, fenced drain',
        report='inkling/report_extend_screen.py')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--run', action='append', dest='runs', help=f'confirmation run (default {CONFIRM_RUNS})')
    p.add_argument('--freeze', action='store_true')
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.source_revision):
        p.error('--source-revision must be a full commit hash')
    if a.output.exists():
        p.error('output exists')
    try:
        plan = make(a.root, a.source_revision, runs=tuple(a.runs or CONFIRM_RUNS), freeze=a.freeze)
    except ValueError as exc:
        p.error(str(exc))
    a.output.write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps(dict(status=plan['status'], items=[i['puzzle_key'] for i in plan['items']],
                          eligible=plan['eligible_puzzles'], problems=plan['draft_problems'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
