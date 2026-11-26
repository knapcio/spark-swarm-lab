#!/usr/bin/env python3
"""Frozen plan of the idea #4 FLEET falsifier (astra, IDEAS 2026-11-26; coordinator 2026-11-27): fork unfinished
private prefixes (two 8K stems, four 24K continuations) against four fresh 32K attempts.

Selection rule (mechanical, frozen here; reads recorded runs only, no model call):
  runs       the default-policy arithmetic runs RUNS (roll12fair, hard-v22 / v23 / v26), cases.jsonl of each run;
  judged     a recorded agent with a judge verdict (true or false; cancelled and unstarted agents have none);
  win        a judged agent accepted by the judge and solved by the exact verifier;
  contested  a puzzle (corpus, task_id) with >= MIN_JUDGED judged agents over the run's seeds and a win rate
             0 < wins / judged <= MAX_WIN_RATE (four fresh attempts neither surely fail nor surely succeed);
  pins       the puzzle text and prompt_ids_sha256 of its first judged agent (order seed, slot; variant
             xl_forced_original), so the driver can prove it sends the recorded prompt;
  order      the contested puzzles sorted by sha256(SELECTION_SEED + ':' + corpus + ':' + task_id); the first
             N_PUZZLES (12) are frozen; fresh worker seeds seed_base = SEED_OFFSET + sha256(SELECTION_SEED + ':' +
             puzzle_key) mod 10^7 (never a recorded seed).
The driver (fork_replay.py on research/idea4-fork-v1) runs per puzzle four fresh attempts and two stems with two
continuations each; every candidate is judged on the original task (fresh j and leaf j share a judge pair label).
Seeds: pairing labels attempts only; draws are independent on this server (seeds not honoured; probe 2026-11-26
21:06Z: identical requests with the same seed gave different outputs), so there are no common random numbers.

Pre-registered rule (report: inkling/report_fork_screen.py): an arm COVERS a puzzle if any of its candidates is
accepted by the judge AND solved by the strict exact verifier. G(arm) = the arm's generated tokens (agent completion
tokens of every call, stems counted once, plus judge tokens). STOP if the fork arm covers fewer puzzles than the fresh
arm (lower coverage) or G(fork) >= G(fresh) (no net compute saving); otherwise PASS AS A SCREEN only (adoption needs a
fresh confirmation). Wrong acceptances (accepted, not strictly solved) are reported per arm. All units run to the end
(no sibling cancellation), so G measures the policies' full generation, not a cancelling swarm's.

usage: fork_plans.py --source-revision REV --output FORK_SCREEN_PLAN.json [--root DIR]
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

N_PUZZLES, SELECTION_SEED = 12, '2026112704'
MIN_JUDGED, MAX_WIN_RATE = 4, 0.5
SEED_OFFSET = 60_000_000
STEM_THINK, CONT_THINK, THINK, TOTAL = 8192, 22528, 30720, 32768
PER_NODE = 20
SOURCE_PATH = '.runtime/idea4-source'
SEED_NOTE = ('pairing labels attempts only; draws are independent on this server (per-request seeds not honoured: '
             'no deterministic inference on the launch; live probe 2026-11-26 21:06Z, identical requests with the same '
             'seed at temperature 0.8 gave different outputs)')


def contested(root, runs=RUNS):
    """{(corpus, task_id): puzzle row} of every contested puzzle, with its pins."""
    out = {}
    for run in runs:
        d = Path(root) / 'runs' / run
        plan, _ = case_indices(root, d)
        rows = sorted(read_jsonl(d / 'cases.jsonl'), key=lambda r: (r['seed'], r['task_id']))
        tasks = {}
        for r in rows:
            tasks.setdefault(r['task_id'], []).append(r)
        for task_id, cases in tasks.items():
            judged = [(r, a) for r in cases for a in sorted(r['agents'], key=lambda a: a['slot'])
                      if a.get('verdict') is not None]
            wins = sum(1 for _, a in judged if a['verdict'] is True and a.get('verifier_solved') is True)
            if len(judged) < MIN_JUDGED or not 0 < wins / len(judged) <= MAX_WIN_RATE:
                continue
            r, a = judged[0]
            stem = f"{task_id}-s{r['seed']}-{r['policy']}-a{a['slot']}"
            trace = d / 'agents' / f'{stem}.jsonl'
            events = read_jsonl(trace)
            config = next(e for e in events if e.get('type') == 'run_start')['config']
            start = next(e for e in events if e.get('type') == 'request_start' and e.get('stage') == 'plan')
            if config.get('variant') != 'xl_forced_original':
                continue
            numbers, target = config['puzzle'].split(':')
            key = (plan['dataset_protocol'], task_id)
            out.setdefault(key, dict(run=run, corpus=key[0], task_id=task_id, judged=len(judged), wins=wins,
                                     pin_trace=str(trace.relative_to(root)), puzzle=config['puzzle'],
                                     numbers=[int(n) for n in numbers.split(',')], target=int(target),
                                     prompt_ids_sha256=start['prompt_ids_sha256']))
    return out


def select(root, runs=RUNS, n=N_PUZZLES, seed=SELECTION_SEED):
    pool = contested(root, runs)
    order = sorted(pool, key=lambda k: sha(f'{seed}:{k[0]}:{k[1]}'))
    chosen = []
    for i, key in enumerate(order[:n]):
        puzzle_key = f'{key[0]}:{key[1]}'
        chosen.append(dict(pool[key], puzzle_key=puzzle_key, item_id=f'y{i:02d}',
                           seed_base=SEED_OFFSET + int(sha(f'{seed}:{puzzle_key}'), 16) % 10_000_000))
    return chosen, len(pool)


def make(root, revision):
    items, eligible = select(root)
    if len(items) < N_PUZZLES:
        raise ValueError(f'only {len(items)} eligible puzzles')
    return dict(
        protocol='fork-screen-v1', study='fork-screen-v1', status='FROZEN', screen='idea-4',
        source_revision=revision, source_path=SOURCE_PATH, driver='fork_replay.py',
        idea='astra IDEAS 2026-11-26 #4: fork unfinished private prefixes to amortize repeated reasoning',
        runs=list(RUNS), selection_rule=__doc__.split('Selection rule (mechanical, frozen here; reads recorded runs '
                                                       'only, no model call):\n')[1].split('\n\n')[0],
        selection_seed=SELECTION_SEED, min_judged=MIN_JUDGED, max_win_rate=MAX_WIN_RATE,
        eligible_puzzles=eligible, items=items, stem_think=STEM_THINK, cont_think=CONT_THINK,
        arms=dict(fresh='four fresh attempts j = 0..3 (worker seed seed_base + j): thinking 30,720 + answer 2,048, '
                        'forced72 xl_forced_original\'s own path; <= 131,072 generated tokens per puzzle',
                  fork='two stems s = 0, 1 (worker seed seed_base + 2 s, a label only) of 8,192 '
                       'thinking tokens; each unfinished stem forks into two continuations (own seeds) of 22,528 '
                       'thinking tokens + the forced answer within 2,048 (lineage 32,768); a stem that closes its '
                       'thinking is a finished attempt (leaf 2 s; leaf 2 s + 1 not run); <= 114,688 per puzzle'),
        judge=('run_variants.judge_once (one attempt, no judge-level retry), unchanged prompt, on the original task; '
               'the seed sent is derived from the pair (fresh j <-> leaf j) and the judge stage only; transport '
               'retries off'),
        decision_rule=dict(cover='an arm covers a puzzle if any of its candidates is accepted by the judge and solved '
                                 'by the strict exact verifier (every submitted move legal, target appeared)',
                           compute='G(arm) = agent completion tokens of every call (stems once) + judge tokens',
                           stop='STOP if C(fork) < C(fresh) (lower coverage) or G(fork) >= G(fresh) (no net saving)',
                           pass_='PASS AS A SCREEN ONLY otherwise; adoption needs a fresh confirmation',
                           report='wrong acceptances per arm, exact sign test over discordant puzzles, G per puzzle'),
        seeds=SEED_NOTE, fleet=collab_plans.FLEET, per_node=PER_NODE, nodes=4,
        judge_code_sha256=collab_plans.judge_hashes(ROOT), serving=collab_plans.serving(ROOT),
        execution='fork_replay.py --plan PLAN --run --output runs/fork-screen-v1 from a clean worktree of the source '
                  'revision: fleet lease, admission, <= per_node per node, fenced drain',
        estimate='12 puzzles: 48 fresh attempts, 24 stems, 48 continuations (<= 2.95M generated tokens) on 4 nodes at '
                 '<= 20 in flight per node: 60-90 fleet min',
        report='inkling/report_fork_screen.py')


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
