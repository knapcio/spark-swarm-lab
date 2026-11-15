#!/usr/bin/env python3
"""Generate 8 development + 24 evaluation tasks; no API. Omit --output for dry-run."""
import argparse
from collections import Counter
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import re

from harness import apply_action, fingerprint, InvalidMove

HERE = Path(__file__).resolve().parent
PROTOCOL = "synthetic-countdown-v1"
RULES = dict(operations=["+", "-", "*", "/"], intermediate="strictly positive integers",
             exact_arithmetic="fractions.Fraction", use_subset=True, duplicate_numbers_allowed=True)


def key(numbers, target):
    return fingerprint(tuple(Fraction(n) for n in numbers), target)


def moves(state):
    result = []
    for i in range(len(state)):
        for j in range(len(state)):
            if i == j:
                continue
            for op in RULES["operations"]:
                action = dict(i=i, j=j, op=op)
                try:
                    result.append((action, apply_action(state, action)))
                except InvalidMove:
                    pass
    return result


def one_step(numbers, target):
    return any(child[-1] == target for _, child in moves(tuple(map(Fraction, numbers))))


def exclusions():
    hashes, known, manifest = set(), {}, []
    def remember(numbers, target):
        try:
            state = tuple(Fraction(str(n)) for n in numbers)
            value = Fraction(str(target))
            if not 2 <= len(state) <= 6 or any(n <= 0 or n.denominator != 1 for n in state) or value.denominator != 1:
                return
            numbers, target = sorted(map(int, state)), int(value)
            digest = key(numbers, target)
            hashes.add(digest)
            known[digest] = dict(numbers=numbers, target=target)
        except (ValueError, TypeError, ZeroDivisionError):
            pass
    def visit(obj):
        if isinstance(obj, dict):
            if "target" in obj and ("numbers" in obj or "state" in obj):
                remember(obj.get("numbers", obj.get("state")), obj["target"])
            for name, value in obj.items():
                if name == "puzzle_fingerprints" and isinstance(value, list):
                    hashes.update(s for s in value if isinstance(s, str) and re.fullmatch("[0-9a-f]{64}", s))
                if name == "puzzle" and isinstance(value, str):
                    try:
                        numbers, target = value.split(":")
                        remember(numbers.split(","), target)
                    except ValueError:
                        pass
                if name == "puzzle_witnesses" and isinstance(value, dict):
                    for puzzle in value:
                        visit(dict(puzzle=puzzle))
                visit(value)
        elif isinstance(obj, list):
            for value in obj:
                visit(value)
    for root in (HERE / "runs", HERE / "results"):
        for path in sorted(root.rglob("*")):
            if not path.is_file() or path.suffix not in (".json", ".jsonl"):
                continue
            raw = path.read_bytes()
            if path.suffix == ".jsonl":
                objects = [json.loads(line) for line in raw.splitlines() if line.strip()]
                # Only initial puzzle/configuration events, not intermediate search states.
                objects = [o for o in objects if o.get("type") in ("puzzle_start", "run_start")]
            else:
                obj = json.loads(raw)
                if isinstance(obj, dict) and obj.get("protocol") == PROTOCOL:
                    continue  # Generator output alone is not a previously executed experiment.
                objects = [obj]
            before = set(hashes)
            for obj in objects:
                visit(obj)
            if hashes != before or objects:
                manifest.append(dict(path=str(path.relative_to(HERE)), sha256=hashlib.sha256(raw).hexdigest()))
    return hashes, known, manifest


def generate(seed, excluded):
    rng, used, tasks, witnesses, attempts = random.Random(seed), set(excluded), [], {}, 0
    for split, count in (("development", 8), ("evaluation", 24)):
        for index in range(count):
            size = 4 if index % 2 == 0 else 6
            for _ in range(20000):
                attempts += 1
                numbers = [rng.randint(1, 10) for _ in range(size - 2)] + rng.sample([25, 50, 75, 100], 2)
                rng.shuffle(numbers)
                state, actions = tuple(map(Fraction, numbers)), []
                for _ in range(rng.randint(2, size - 1)):
                    options = [(a, c) for a, c in moves(state) if c[-1] <= 1000000]
                    action, state = rng.choice(options)
                    actions.append(action)
                target = int(state[-1])
                digest = key(numbers, target)
                if not 10 <= target <= 999 or target in numbers or digest in used or one_step(numbers, target):
                    continue
                used.add(digest)
                task_id = f"{split[:3]}-{digest[:12]}"
                tasks.append(dict(id=task_id, split=split, numbers=numbers, target=target))
                witnesses[task_id] = dict(actions=actions, witness_length=len(actions), final_state=list(map(str, state)))
                break
            else:
                raise RuntimeError("Generation attempt limit reached; no output written")
    return tasks, witnesses, attempts


def verify(tasks, witnesses, excluded):
    assert len(tasks) == 32 and len({key(t["numbers"], t["target"]) for t in tasks}) == 32
    assert Counter((t["split"], len(t["numbers"])) for t in tasks) == {
        ("development", 4): 4, ("development", 6): 4, ("evaluation", 4): 12, ("evaluation", 6): 12}
    for task in tasks:
        assert key(task["numbers"], task["target"]) not in excluded
        assert task["target"] not in task["numbers"] and not one_step(task["numbers"], task["target"])
        state = tuple(map(Fraction, task["numbers"]))
        for action in witnesses[task["id"]]["actions"]:
            state = apply_action(state, action)
        assert task["target"] in state
        assert list(map(str, state)) == witnesses[task["id"]]["final_state"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=20261115)
    parser.add_argument("--output", type=Path, help="New directory; refuses overwrite; otherwise dry-run")
    args = parser.parse_args(argv)
    if args.output and args.output.exists():
        parser.error("output directory already exists")
    excluded, known, manifest = exclusions()
    tasks, witnesses, attempts = generate(args.seed, excluded)
    verify(tasks, witnesses, excluded)
    assert (tasks, witnesses, attempts) == generate(args.seed, excluded), "Determinism check failed"
    common = dict(protocol=PROTOCOL, generator_seed=args.seed, rules=RULES,
                  generator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  evaluator_sha256=hashlib.sha256((HERE / "harness.py").read_bytes()).hexdigest(),
                  generation_attempts=attempts, target_range=[10, 999], intermediate_sampling_cap=1000000,
                  excluded_prior_fingerprints=sorted(excluded), exclusion_manifest=manifest,
                  limitations="Synthetic construction distribution; witnesses prove existence, not minimum solution depth or matched task difficulty.")
    dataset = dict(common, tasks=tasks)
    reference = dict(common, witnesses=witnesses, excluded_prior_tasks=known,
                     note="Reference only: never send witnesses to the model. Development/evaluation fingerprints are disjoint.")
    if args.output:
        args.output.mkdir(parents=True, exist_ok=False)
        for name, data in (("tasks.json", dataset), ("reference-witnesses.json", reference)):
            (args.output / name).write_text(json.dumps(data, indent=2) + "\n")
    print(json.dumps(dict(mode="written" if args.output else "dry_run", tasks=32,
                         splits=dict(Counter(t["split"] for t in tasks)), excluded=len(excluded),
                         attempts=attempts, verified=True, dataset_sha256=hashlib.sha256(json.dumps(dataset, sort_keys=True).encode()).hexdigest(),
                         output=str(args.output) if args.output else None)))


if __name__ == "__main__":
    main()
