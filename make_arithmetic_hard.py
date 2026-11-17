#!/usr/bin/env python3
"""Generate the arithmetic-hard-v1 corpus: 16 development + 48 evaluation tasks. No model calls.

Same rules and verifier as arithmetic-v1 (positive-integer intermediates, + - * /, leftovers
allowed, success when the target appears). Difficulty is selected with an exact CPU subset DP
(arith_difficulty.py) that agents never see:
  4-number tasks: the target needs all four numbers and has at most 2 derivation trees in total;
  6-number tasks: the target needs at least five numbers and has at most 2 derivation trees at
  that minimum size.
Targets are uniform in [100, 999]. Historical puzzles (make_tasks.exclusions scan of runs/ and
results/ plus every datasets/*/tasks.json) are excluded. Plan-only unless --output is given.
"""
import argparse
import hashlib
import json
import random
from collections import Counter
from fractions import Fraction
from pathlib import Path

import arith_difficulty as difficulty
from harness import apply_action
from make_tasks import RULES, exclusions, key

HERE = Path(__file__).resolve().parent
PROTOCOL = 'arithmetic-hard-v1'
SEED = 2026111602
COUNTS = (('development', 16), ('evaluation', 48))


def hard(numbers, target):
    stats = difficulty.stats(numbers, target)
    if stats['min_numbers'] is None:
        return None
    if len(numbers) == 4 and stats['min_numbers'] == 4 and stats['derivations_total'] <= 2:
        return stats
    if len(numbers) == 6 and stats['min_numbers'] >= 5 and stats['derivations_at_min'] <= 2:
        return stats
    return None


def dataset_fingerprints(root):
    found = set()
    for path in sorted((root / 'datasets').glob('*/tasks.json')):
        for task in json.loads(path.read_text()).get('tasks', []):
            if 'numbers' in task and 'target' in task:
                found.add(key(task['numbers'], task['target']))
    return found


def generate(seed, excluded):
    rng, used, tasks, private, attempts = random.Random(seed), set(excluded), [], {}, 0
    for split, count in COUNTS:
        for index in range(count):
            size = 4 if index % 2 == 0 else 6
            for _ in range(100000):
                attempts += 1
                numbers = [rng.randint(1, 10) for _ in range(size - 2)] + rng.sample([25, 50, 75, 100], 2)
                rng.shuffle(numbers)
                target = rng.randint(100, 999)
                digest = key(numbers, target)
                if target in numbers or digest in used:
                    continue
                stats = hard(numbers, target)
                if stats is None:
                    continue
                used.add(digest)
                task_id = f'{split[:3]}-h{digest[:11]}'
                tasks.append(dict(id=task_id, split=split, numbers=numbers, target=target))
                private[task_id] = dict(difficulty=stats, witness=difficulty.witness(numbers, target))
                break
            else:
                raise RuntimeError('attempt limit reached; nothing written')
    return tasks, private, attempts


def verify(tasks, private, excluded):
    assert len(tasks) == 64 == len({key(t['numbers'], t['target']) for t in tasks})
    assert Counter((t['split'], len(t['numbers'])) for t in tasks) == {
        ('development', 4): 8, ('development', 6): 8, ('evaluation', 4): 24, ('evaluation', 6): 24}
    for task in tasks:
        assert key(task['numbers'], task['target']) not in excluded
        assert hard(task['numbers'], task['target']) == private[task['id']]['difficulty']
        state = tuple(map(Fraction, task['numbers']))
        moves = private[task['id']]['witness']
        assert len(moves) == private[task['id']]['difficulty']['min_moves']
        for move in moves:
            state = apply_action(state, move)
        assert task['target'] in state


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path)
    p.add_argument('--seed', type=int, default=SEED)
    p.add_argument('--protocol', default=PROTOCOL)
    a = p.parse_args(argv)
    if a.output is None:
        print(json.dumps(dict(mode='plan', protocol=a.protocol, seed=a.seed, counts=dict(COUNTS), tasks_generated=0)))
        return 0
    if a.output.exists():
        raise SystemExit('output exists')
    history, _, manifest = exclusions()
    excluded = history | dataset_fingerprints(HERE)
    tasks, private, attempts = generate(a.seed, excluded)
    verify(tasks, private, excluded)
    source = {name: hashlib.sha256((HERE / name).read_bytes()).hexdigest()
              for name in ('make_arithmetic_hard.py', 'arith_difficulty.py', 'make_tasks.py', 'harness.py')}
    common = dict(protocol=a.protocol, generator_seed=a.seed, rules=RULES, generation_attempts=attempts,
                  selection='4-number: needs all four numbers, <=2 derivation trees in total; 6-number: needs >=5 numbers, '
                            '<=2 derivation trees at the minimum size. Targets uniform 100..999. Difficulty from an exact CPU '
                            'subset DP used only to SELECT tasks; never shown to agents.',
                  excluded_fingerprints=len(excluded), exclusion_manifest=manifest, source_sha256=source)
    a.output.mkdir(parents=True)
    (a.output / 'tasks.json').write_text(json.dumps(dict(common, tasks=tasks), indent=2) + '\n')
    (a.output / 'reference-private.json').write_text(json.dumps(dict(
        common, note='Private: difficulty statistics and one minimal witness per task. Never load in a model worker.',
        tasks=private), indent=2) + '\n')
    print(json.dumps(dict(mode='generated', tasks=len(tasks), attempts=attempts, output=str(a.output))))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
