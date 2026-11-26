#!/usr/bin/env python3
"""Frozen plan of the idea #2 FLEET falsifier (astra, IDEAS 2026-11-26; coordinator 2026-11-27): independent whole-task
re-expression against the original input, on recorded abstentions.

Selection rule (mechanical, frozen here; reads recorded runs only, no model call):
  runs        the default-policy arithmetic runs RUNS (roll12fair, hard-v22 / v23 / v26), cases.jsonl of each run;
  abstention  a recorded case that ended with no accepted answer (cases.jsonl answered false);
  puzzle      (corpus, task_id); per puzzle its first abstention in the order run (as listed), seed, task_id;
  pins        the puzzle text and prompt_ids_sha256 of that case's first started agent (lowest slot with a plan request;
              variant xl_forced_original), so the driver can prove it sends the recorded task;
  order       the eligible puzzles sorted by sha256(SELECTION_SEED + ':' + corpus + ':' + task_id); the first
              N_PUZZLES (12) are frozen; worker seeds seed_base = SEED_OFFSET + sha256(SELECTION_SEED + ':' +
              puzzle_key) mod 10^7.
The driver (restate_replay.py on research/idea2-restate-v1) runs per puzzle two fresh workers on the original task text
and two workers on independent restatements (a separate restater per worker, generic instructions, tokens charged);
every candidate is judged on the untouched original task (original k and restated k share a judge pair label).
Seeds: pairing labels attempts only; draws are independent on this server (seeds not honoured; probe 2026-11-26
21:06Z: identical requests with the same seed gave different outputs).

Pre-registered rule (report: inkling/report_restate_screen.py): an arm rescues a puzzle if any of its candidates is
accepted by the judge AND solved by the strict exact verifier. STOP if the restated arm rescues no more puzzles than the
original arm (R <= O: no rescue advantage); otherwise PASS AS A SCREEN only (adoption needs a fresh confirmation).
Wrong acceptances, empty restatements and each arm's generated tokens (restatement included) are reported.

usage: restate_plans.py --source-revision REV --output RESTATE_SCREEN_PLAN.json [--root DIR]
"""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(HERE))
import collab_plans  # noqa: E402  (judge pins and serving identity, same as the replay screens)
from extend_plans import RUNS, case_indices, read_jsonl, sha  # noqa: E402

N_PUZZLES, SELECTION_SEED = 12, '2026112702'
SEED_OFFSET = 70_000_000
PER_NODE = 12
SOURCE_PATH = '.runtime/idea2-source'
SEED_NOTE = ('pairing labels attempts only; draws are independent on this server (per-request seeds not honoured: '
             'no deterministic inference on the launch; live probe 2026-11-26 21:06Z, identical requests with the same '
             'seed at temperature 0.8 gave different outputs)')
RESTATE_SYSTEM = ('Rewrite the task you are given completely and precisely in your own words. Keep every requirement, '
                  'constraint, given value and the required output format. Do not add assumptions, examples, hints or '
                  'advice, and do not solve the task. Return only the rewritten task.')
RESTATE_USER = 'Task:\n\n{task}'


def abstentions(root, runs=RUNS):
    """Every recorded abstention with its pins, in selection order (run, seed, task_id)."""
    out = []
    for run in runs:
        d = Path(root) / 'runs' / run
        plan, _ = case_indices(root, d)
        for r in sorted(read_jsonl(d / 'cases.jsonl'), key=lambda r: (r['seed'], r['task_id'])):
            if r.get('answered') is not False:
                continue
            for a in sorted(r['agents'], key=lambda a: a['slot']):
                trace = d / 'agents' / f"{r['task_id']}-s{r['seed']}-{r['policy']}-a{a['slot']}.jsonl"
                events = read_jsonl(trace) if trace.exists() else []
                start = next((e for e in events if e.get('type') == 'request_start' and e.get('stage') == 'plan'),
                             None)
                if start is None:
                    continue
                config = next(e for e in events if e.get('type') == 'run_start')['config']
                if config.get('variant') != 'xl_forced_original':
                    break
                numbers, target = config['puzzle'].split(':')
                out.append(dict(run=run, corpus=plan['dataset_protocol'], task_id=r['task_id'], seed=r['seed'],
                                pin_trace=str(trace.relative_to(root)), puzzle=config['puzzle'],
                                numbers=[int(n) for n in numbers.split(',')], target=int(target),
                                prompt_ids_sha256=start['prompt_ids_sha256']))
                break
    return out


def select(root, runs=RUNS, n=N_PUZZLES, seed=SELECTION_SEED):
    first = {}
    for a in abstentions(root, runs):
        first.setdefault((a['corpus'], a['task_id']), a)
    order = sorted(first, key=lambda k: sha(f'{seed}:{k[0]}:{k[1]}'))
    chosen = []
    for i, key in enumerate(order[:n]):
        puzzle_key = f'{key[0]}:{key[1]}'
        chosen.append(dict(first[key], puzzle_key=puzzle_key, item_id=f'z{i:02d}',
                           seed_base=SEED_OFFSET + int(sha(f'{seed}:{puzzle_key}'), 16) % 10_000_000))
    return chosen, len(first)


def make(root, revision):
    items, eligible = select(root)
    if len(items) < N_PUZZLES:
        raise ValueError(f'only {len(items)} eligible puzzles')
    return dict(
        protocol='restate-screen-v1', study='restate-screen-v1', status='FROZEN', screen='idea-2',
        source_revision=revision, source_path=SOURCE_PATH, driver='restate_replay.py',
        idea='astra IDEAS 2026-11-26 #2: independent, whole-task re-expression',
        runs=list(RUNS), selection_rule=__doc__.split('Selection rule (mechanical, frozen here; reads recorded runs '
                                                       'only, no model call):\n')[1].split('\n\n')[0],
        selection_seed=SELECTION_SEED, eligible_puzzles=eligible, items=items,
        restate_system=RESTATE_SYSTEM, restate_user=RESTATE_USER,
        prompt_rule=('the owner\'s generic-only prompt rule applies to mechanisms this screen adds: the restater '
                     'template (restate_system / restate_user), checked free of task-family words. The production '
                     'solver and judge prompts (forced72 system prompt and task text, run_judge prompts) are the task '
                     'harness and stay unchanged in both arms (coordinator decision 2026-11-27)'),
        arms=dict(original='two fresh workers k = 0, 1 (worker seed seed_base + k) on the original task text: thinking '
                           '30,720 + answer 2,048, forced72 xl_forced_original\'s own path',
                  restated='per worker k a separate restater (seed seed_base + 1,000,003 + k; thinking 6,144, forced '
                           'answer within 8,192; tokens charged) rewrites the complete task; a fresh worker (seed '
                           'seed_base + k, unchanged system prompt, full normal budget) solves the restatement'),
        workers_per_arm=2,
        judge=('run_variants.judge_once (one attempt, no judge-level retry), unchanged prompt, on the ORIGINAL numbers '
               'and target; the seed sent is derived from the pair (original k <-> restated k) and the judge '
               'stage only; transport retries off'),
        decision_rule=dict(rescue='an arm rescues a puzzle if any of its candidates is accepted by the judge and '
                                  'solved by the strict exact verifier (every submitted move legal, target appeared)',
                           stop='STOP if the restated arm rescues no more puzzles than the original arm (R <= O)',
                           pass_='PASS AS A SCREEN ONLY if R > O; adoption needs a fresh confirmation',
                           report='wrong acceptances, empty restatements, generated tokens per arm (restatement '
                                  'included), exact sign test over discordant puzzles'),
        seeds=SEED_NOTE, fleet=collab_plans.FLEET, per_node=PER_NODE, nodes=4,
        judge_code_sha256=collab_plans.judge_hashes(ROOT), serving=collab_plans.serving(ROOT),
        execution='restate_replay.py --plan PLAN --run --output runs/restate-screen-v1 from a clean worktree of the '
                  'source revision: fleet lease, admission, <= per_node per node, fenced drain',
        estimate='12 puzzles x 4 workers (<= 32,768 each) + 24 restatements (<= 8,192) on 4 nodes at <= 12 in flight '
                 'per node: 60-90 fleet min',
        report='inkling/report_restate_screen.py')


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
