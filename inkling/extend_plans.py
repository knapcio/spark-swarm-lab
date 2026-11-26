#!/usr/bin/env python3
"""Frozen plan of the idea #1 FLEET screen (astra, IDEAS 2026-11-26; coordinator 2026-11-27): extend a length-forced,
rejected agent with a replacement's budget, against fresh equal-budget agents.

Selection rule (mechanical, frozen here; reads recorded runs only, no model call):
  runs       the default-policy arithmetic runs RUNS (roll12fair, hard-v22 / v23 / v26), their base segment;
  failure    an agent whose plan request used the whole thinking budget (finish length, 30,720 recorded ids, thinking
             still open), whose trace has budget_forced, whose forced answer the judge REJECTED (verdict false), in a
             case the run never solved (cases.jsonl solved false);
  puzzle     (corpus, task_id); per puzzle its first failure in the order run (as listed), seed, task_id, slot;
  order      the eligible puzzles sorted by sha256(SELECTION_SEED + ':' + corpus + ':' + task_id); the first N_PUZZLES
             (12) are frozen.
Per selected failure the driver (extend_replay.py on research/idea1-extend-v1) runs two private extensions (the same
agent's recorded thinking ids + another 30,720 thinking tokens, then the normal forced answer) and two fresh agents (new
seeds, full normal budget), all judged on the original task (judge seeds paired by attempt).

Pre-registered rule (report: inkling/report_extend_screen.py): per puzzle, an arm rescues it if any of its two
attempts is accepted by the judge AND solves the puzzle (exact verifier); STOP if the extensions rescue no more
puzzles than the fresh agents (E <= F, clustered by puzzle); otherwise PASS AS A SCREEN only (adoption needs a fresh
confirmation). Wrong acceptances (accepted, not solved) are reported per arm.

usage: extend_plans.py --source-revision REV --output EXTEND_SCREEN_PLAN.json [--root DIR]
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import collab_plans  # noqa: E402  (judge pins and serving identity, same as the replay screens)

RUNS = ('swarm-fair-hard22-v1-roll12fair', 'swarm-fair-hard23-v1-roll12fair', 'swarm-baseline-hard26-v1-roll12fair')
N_PUZZLES, SELECTION_SEED = 12, '2026112701'
THINK, PER_NODE = 30720, 12  # 48 attempts, at most 12 in flight per node (<= 20)
STEM = re.compile(r'^(?P<task>.+)-s(?P<seed>\d+)-(?P<policy>[A-Za-z0-9_]+)-a(?P<slot>\d+)$')
SOURCE_PATH = '.runtime/idea1-source'


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def read_jsonl(path):
    out = []
    for line in Path(path).read_text().splitlines():
        try:
            out.append(json.loads(line))
        except ValueError:
            pass
    return out


def case_indices(root, run_dir):
    plan = json.loads((run_dir / 'metadata.json').read_text())['protocol']
    data = json.loads((Path(root) / plan['dataset']).read_text())
    tasks = [t for t in data['tasks'] if t['split'] == plan['split']]
    if plan.get('task_ids'):
        tasks = [t for t in tasks if t['id'] in plan['task_ids']]
    if plan.get('numbers_count'):
        tasks = [t for t in tasks if len(t['numbers']) == plan['numbers_count']]
    return plan, {(t['id'], s): si * len(tasks) + ti for si, s in enumerate(plan['seeds']) for ti, t in enumerate(tasks)}


def failures(root, runs=RUNS):
    """Every eligible failure in selection order (run, seed, slot), with its replay fields."""
    out = []
    for run in runs:
        d = Path(root) / 'runs' / run
        plan, indices = case_indices(root, d)
        rows = [r for r in read_jsonl(d / 'cases.jsonl')]
        for r in sorted(rows, key=lambda r: (r['seed'], r['task_id'])):
            if r.get('solved'):
                continue
            for a in sorted(r['agents'], key=lambda a: a['slot']):
                if a.get('verdict') is not False:
                    continue
                stem = f"{r['task_id']}-s{r['seed']}-{r['policy']}-a{a['slot']}"
                trace = d / 'agents' / f'{stem}.jsonl'
                events = read_jsonl(trace)
                if not any(e.get('type') == 'budget_forced' for e in events):
                    continue
                start = next((e for e in events if e.get('type') == 'request_start' and e.get('stage') == 'plan'), None)
                end = next((e for e in events if e.get('type') == 'request_end' and start
                            and e.get('request_id') == start.get('request_id')), None)
                ids = (end or {}).get('token_ids') or []
                if not (end and end.get('finish_reason') == 'length' and not end.get('closed_thinking')
                        and len(ids) == THINK and not end.get('error')):
                    continue
                config = next(e for e in events if e.get('type') == 'run_start')['config']
                numbers, target = config['puzzle'].split(':')
                out.append(dict(run=run, corpus=plan['dataset_protocol'], task_id=r['task_id'], seed=r['seed'],
                                slot=a['slot'], case_index=indices[(r['task_id'], r['seed'])], stem=stem,
                                trace=str(trace.relative_to(root)), puzzle=config['puzzle'],
                                numbers=[int(n) for n in numbers.split(',')], target=int(target),
                                agent_seed=config['seed'], prompt_ids_sha256=start['prompt_ids_sha256'],
                                prefix_ids_sha256=sha(json.dumps(ids)), recorded_tokens=len(ids)))
    return out


def select(root, runs=RUNS, n=N_PUZZLES, seed=SELECTION_SEED):
    first = {}
    for f in failures(root, runs):
        first.setdefault((f['corpus'], f['task_id']), f)
    order = sorted(first, key=lambda k: sha(f'{seed}:{k[0]}:{k[1]}'))
    chosen = [dict(first[k], puzzle_key=f'{k[0]}:{k[1]}', item_id=f'x{i:02d}') for i, k in enumerate(order[:n])]
    return chosen, len(first)


def make(root, revision):
    items, eligible = select(root)
    if len(items) < N_PUZZLES:
        raise ValueError(f'only {len(items)} eligible puzzles')
    return dict(
        protocol='extend-screen-v1', study='extend-screen-v1', status='FROZEN', screen='idea-1',
        source_revision=revision, source_path=SOURCE_PATH, driver='extend_replay.py',
        idea='astra IDEAS 2026-11-26 #1: transfer a replacement\'s budget into deeper private reasoning',
        runs=list(RUNS), selection_rule=__doc__.split('Selection rule (mechanical, frozen here; reads recorded runs '
                                                       'only, no model call):\n')[1].split('\n\n')[0],
        selection_seed=SELECTION_SEED, eligible_puzzles=eligible, items=items,
        arms=dict(extension='the same agent\'s recorded 30,720 thinking ids + another 30,720 thinking tokens, then '
                            'forced72\'s answer path within the 2,048 reserve (a replacement\'s 32,768 budget)',
                  fresh='a fresh agent (worker seed agent_seed + 1,000,003 k), thinking 30,720 + answer 2,048'),
        attempts_per_arm=2, judge='run_variants.judge_with_reason, unchanged; seeds paired by attempt',
        decision_rule=dict(rescue='a puzzle is rescued by an arm if any of its attempts is accepted by the judge and '
                                  'solved by the exact verifier',
                           stop='STOP if extensions rescue no more puzzles than fresh agents (E <= F)',
                           pass_='PASS AS A SCREEN ONLY if E > F; adoption needs a fresh confirmation',
                           report='wrong acceptances per arm, exact sign test over discordant puzzles'),
        fleet=collab_plans.FLEET, per_node=PER_NODE, nodes=4,
        judge_code_sha256=collab_plans.judge_hashes(ROOT), serving=collab_plans.serving(ROOT),
        execution='extend_replay.py --plan PLAN --run --output runs/extend-screen-v1 from a clean worktree of the '
                  'source revision: fleet lease, admission, <= per_node per node, fenced drain',
        estimate='48 attempts x <= 32,768 generated tokens on 4 nodes at <= 12 in flight per node: 45-75 fleet min',
        report='inkling/report_extend_screen.py')


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('--root', type=Path, default=ROOT)
    p.add_argument('--source-revision', required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args(argv)
    if not re.fullmatch(r'[0-9a-f]{40}', a.source_revision):
        p.error('--source-revision must be a full commit hash')
    if a.output.exists():
        p.error('output exists')
    plan = make(a.root, a.source_revision)
    a.output.write_text(json.dumps(plan, indent=1) + '\n')
    print(json.dumps(dict(items=[i['puzzle_key'] for i in plan['items']], eligible=plan['eligible_puzzles'])))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
