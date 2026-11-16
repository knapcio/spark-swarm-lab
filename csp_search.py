#!/usr/bin/env python3
"""Small, verifier-guided coloring search. No reference-solution input or tools."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import random
import time

from csp_tasks import canonical_json, load_tasks, verify_assignment, worker_task
from csp_social import SOCIAL_ARMS, run_social_search
from harness import Budget, Client, Events

CORE_ARMS = ("resample", "sequential", "parallel_repair4", "evolution4")
ARMS = CORE_ARMS + ("evolution_mutation4",) + SOCIAL_ARMS


def stage_schema(task, stage):
    """Format/domain constraints only; never encode edges or a valid coloring."""
    if stage.startswith("candidate-"):
        key, value = "assignment", dict(type="array", minItems=task["vertex_count"],
            maxItems=task["vertex_count"], items=dict(type="integer", enum=list(range(task["color_count"]))))
    elif stage.startswith("review-"):
        key, value = "critique", dict(type="string", minLength=1, maxLength=4000)
    else:
        raise ValueError("unknown structured-output stage")
    return dict(type="object", properties={key: value}, required=[key], additionalProperties=False)


def task_prompt(task):
    return ("Color every vertex of this graph. Every edge must connect different colors. "
            "Colors are integers 0 through color_count-1; vertices are indexed from zero. "
            "Return ONLY {\"assignment\":[color_for_vertex_0,...]}. No tools.\nTask: "
            + canonical_json(worker_task(task)))


def feedback(candidate):
    return {"candidate": candidate["payload"], "verification": candidate["verification"]}


def run_search(task, arm, client, events, max_calls=16):
    """At most sixteen model candidates; sequential starts with one, others four.

    Batches always finish before selection, so sibling work is charged. A solved
    batch stops future batches. Every duplicate still consumes its model call.
    Repair carries only the chain's last attempt; evolution keeps four elites.
    """
    if type(max_calls) is not int or max_calls < 4 or max_calls % 4:
        raise ValueError("max_calls must be an integer multiple of four, at least four")
    if arm not in ARMS:
        raise ValueError("unknown search arm")
    task = worker_task(task)
    if arm in SOCIAL_ARMS:
        return run_social_search(task, arm, client, events, task_prompt(task), max_calls)
    base, candidates, seen = task_prompt(task), [], {}
    start = time.monotonic()

    def propose(index, agent, parents, operation):
        prompt = base
        if parents:
            prompt += "\nEarlier complete assignment(s) and exact verifier feedback: " + canonical_json([feedback(p) for p in parents])
            if operation == "crossover":
                prompt += "\nCombine useful choices from both parents and repair conflicts. Return one full assignment."
            else:
                prompt += "\nRevise your previous assignment to remove conflicts. Return one full assignment."
        payload = client.call(agent, "candidate-" + str(index), prompt,
                              puzzle_id=task["id"], candidate_index=index,
                              parent_ids=[p["id"] for p in parents], operation=operation)
        proof = verify_assignment(task, payload)
        digest = hashlib.sha256(canonical_json(payload).encode()).hexdigest()
        return dict(id=f"candidate-{index}", index=index, agent=agent,
                    parents=[p["id"] for p in parents], operation=operation,
                    payload=payload, verification=proof, sha256=digest,
                    verified_elapsed_seconds=time.monotonic() - start)

    def batch(jobs):
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            result = list(pool.map(lambda job: propose(*job), jobs))
        for candidate in result:
            candidate["duplicate_of"] = seen.get(candidate["sha256"])
            seen.setdefault(candidate["sha256"], candidate["id"])
            candidates.append(candidate)
            events.emit("candidate", puzzle_id=task["id"], **candidate)
            events.emit("reward", puzzle_id=task["id"], node_id=candidate["id"],
                        solved=candidate["verification"]["solved"],
                        reward=int(candidate["verification"]["solved"]),
                        elapsed_seconds=candidate["verified_elapsed_seconds"])
        return result

    def successful():
        return any(c["verification"]["solved"] for c in candidates)

    def ranked(pool):
        # Stable index breaks fitness ties without consulting any witness.
        return sorted(pool, key=lambda c: (-c["verification"]["fitness"][0],
                                         -c["verification"]["fitness"][1], c["index"]))

    if arm == "sequential":
        previous = []
        for index in range(max_calls):
            previous = batch([(index, 0, previous, "repair" if previous else "fresh")])
            if successful():
                break
    else:
        population = batch([(i, i, [], "fresh") for i in range(4)])
        for generation in range(1, max_calls // 4):
            if successful():
                break
            offset = generation * 4
            if arm == "resample":
                jobs = [(offset + i, i, [], "fresh") for i in range(4)]
            elif arm == "parallel_repair4":
                jobs = [(offset + i, i, [population[i]], "repair") for i in range(4)]
            else:
                valid = [c for c in ranked(population) if c["verification"]["valid_schema"]]
                distinct = []
                for candidate in valid:
                    if candidate["sha256"] not in {c["sha256"] for c in distinct}:
                        distinct.append(candidate)
                first = valid[:1]
                second = valid[1:2] or first
                cross = distinct[:2]
                if len(cross) < 2 or arm == "evolution_mutation4":
                    cross = first
                jobs = [(offset, 0, first, "mutation" if first else "fresh"),
                        (offset + 1, 1, second, "mutation" if second else "fresh"),
                        (offset + 2, 2, cross, "crossover" if len(cross) == 2 else "mutation" if cross else "fresh"),
                        (offset + 3, 3, [], "immigrant")]
            children = batch(jobs)
            if arm in ("evolution4", "evolution_mutation4"):
                survivors = ranked(population + children)[:4]
                events.emit("selection", generation=generation,
                            survivor_ids=[c["id"] for c in survivors],
                            pruned_ids=[c["id"] for c in population + children if c not in survivors])
                population = survivors
            else:
                population = children
    best = ranked(candidates)[0]
    result = dict(solved=successful(), candidate_count=len(candidates),
                  unique_candidates=len(seen), best_candidate_id=best["id"],
                  best_verification=best["verification"], best_payload=best["payload"])
    events.emit("search_end", **result)
    return result


def classical_search(task, seed, generations=128, population_size=32):
    """Separate zero-LLM genetic baseline, with a fixed candidate-evaluation budget.

    Uniform crossover, one random vertex recoloring per child, two-way fitness
    tournaments, four elites and one fresh immigrant. No witness or exact solver.
    """
    if type(generations) is not int or generations < 0 or type(population_size) is not int or population_size < 5:
        raise ValueError("nonnegative integer generations and integer population_size >= 5 required")
    task, rng = worker_task(task), random.Random(seed)
    n, k = task["vertex_count"], task["color_count"]
    evaluated, best, trajectory = 0, None, []
    def evaluate(values):
        nonlocal evaluated, best
        evaluated += 1
        proof = verify_assignment(task, {"assignment": values})
        item = (proof["conflicts"], evaluated, values)
        if best is None or item[:2] < best[:2]:
            best = item
        return item
    fresh = lambda: [rng.randrange(k) for _ in range(n)]
    population = [evaluate(fresh()) for _ in range(population_size)]
    for generation in range(generations + 1):
        population.sort(key=lambda c: c[:2])
        trajectory.append(dict(generation=generation, evaluations=evaluated, conflicts=best[0]))
        if best[0] == 0 or generation == generations:
            break
        children = []
        while len(children) < population_size - 4 - 1:
            parents = [min(rng.sample(population, 2), key=lambda c: c[:2]) for _ in range(2)]
            values = [parents[rng.randrange(2)][2][i] for i in range(n)]
            vertex = rng.randrange(n)
            alternatives = [color for color in range(k) if color != values[vertex]]
            values[vertex] = rng.choice(alternatives)
            children.append(evaluate(values))
        population = population[:4] + children + [evaluate(fresh())]
    return dict(solved=best[0] == 0, conflicts=best[0], evaluations=evaluated,
                assignment=best[2], trajectory=trajectory, model_calls=0)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path(__file__).parent / "datasets/csp-v1/tasks.json")
    parser.add_argument("--split", choices=["development", "evaluation"], required=True)
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--arm", choices=ARMS, required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--events", type=Path, required=True)
    parser.add_argument("--model", default="nemotron-lightning")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--thinking", action="store_true")
    parser.add_argument("--guided-format", action="store_true", help="Constrain only JSON shape, cardinality and color domain")
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--max-calls", type=int, default=16)
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    tasks = [t for t in load_tasks(args.dataset, args.split) if t["id"] == args.task_id]
    if len(tasks) != 1:
        raise ValueError("unique public task required")
    events = Events(args.events, args.arm)
    budget = Budget(args.max_calls, args.max_calls * args.max_tokens)
    client = Client([args.endpoint], args.model, 4, args.max_tokens, args.timeout,
                    budget, events, args.seed, args.thinking)
    client.system_prompt = "Solve the precise graph-coloring task. Return only the requested JSON object. Do not use tools."
    if args.guided_format:
        client.schema_for_stage = lambda stage: stage_schema(tasks[0], stage)
    try:
        events.emit("run_start", task=tasks[0], seed=args.seed,
                    thinking=args.thinking, max_tokens=args.max_tokens,
                    max_calls=args.max_calls, max_completion_tokens=args.max_calls * args.max_tokens,
                    **({"structured_outputs": "json_schema_format_domain_only"} if args.guided_format else {}))
        result = run_search(tasks[0], args.arm, client, events, args.max_calls)
        events.emit("run_end", status="complete", **result, **budget.snapshot(),
                    infrastructure_failures=client.infra_failures,
                    budget_denials=client.budget_failures)
    finally:
        events.close()
    return int(client.infra_failures > 0)


if __name__ == "__main__":
    raise SystemExit(main())
