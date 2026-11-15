#!/usr/bin/env python3
"""Deterministic planted-coloring corpus and exact verifier; no model execution.

Generation alone reads/creates witnesses. Workers use load_tasks/worker_task,
which accept only the public task schema and never open a sibling file.
The public generation seed makes witnesses reproducible, not secret. Keeping
them outside worker inputs is an experimental information boundary.
"""
import argparse
import hashlib
import json
from pathlib import Path
import random

PROTOCOL = "planted-coloring-csp-v1"
GENERATION_SEED = 2026111501
TASK_KEYS = {"id", "split", "vertex_count", "color_count", "edges"}
WORKER_KEYS = TASK_KEYS - {"split"}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def graph_digest(task):
    return hashlib.sha256(canonical_json({key: task[key] for key in
        ("vertex_count", "color_count", "edges")}).encode()).hexdigest()


def validate_graph(task):
    """Reject malformed task data; do not silently repair a constraint graph."""
    if not isinstance(task, dict) or set(task) not in (TASK_KEYS, WORKER_KEYS):
        raise ValueError("unexpected task fields (reference data is forbidden)")
    if not isinstance(task["id"], str) or not task["id"]:
        raise ValueError("nonempty task id required")
    if "split" in task and task["split"] not in ("development", "evaluation"):
        raise ValueError("unknown split")
    n, k = task["vertex_count"], task["color_count"]
    if type(n) is not int or type(k) is not int or not 2 <= k <= n:
        raise ValueError("integer vertex/color counts with 2 <= colors <= vertices required")
    edges = task["edges"]
    if not isinstance(edges, list):
        raise ValueError("edges must be a list")
    seen = set()
    for edge in edges:
        if (not isinstance(edge, list) or len(edge) != 2 or
                any(type(v) is not int for v in edge) or not 0 <= edge[0] < edge[1] < n):
            raise ValueError("edges must contain two distinct in-range integer vertices in increasing order")
        pair = tuple(edge)
        if pair in seen:
            raise ValueError("duplicate edge")
        seen.add(pair)


def verify_assignment(task, candidate):
    """Check every vertex/domain and every edge. Return no suggested repair.

    Only {"assignment": [integer_color, ...]} is accepted. Color labels range
    from zero through color_count-1; unused colors are allowed. Booleans are
    not integer labels. Fitness is valid_schema first, then fewer conflicts.
    A malformed assignment receives no partial edge score.
    """
    validate_graph(task)
    error = None
    if not isinstance(candidate, dict) or set(candidate) != {"assignment"}:
        error = "expected exactly one assignment field"
    else:
        values = candidate["assignment"]
        if not isinstance(values, list) or len(values) != task["vertex_count"]:
            error = "assignment must give exactly one color per vertex"
        elif any(type(v) is not int or not 0 <= v < task["color_count"] for v in values):
            error = "every color must be an integer in the allowed domain"
    if error:
        return dict(solved=False, valid_schema=False, conflicts=None,
                    violating_edges=[], error=error, fitness=[0, 0])
    conflicts = [index for index, (u, v) in enumerate(task["edges"]) if values[u] == values[v]]
    return dict(solved=not conflicts, valid_schema=True, conflicts=len(conflicts),
                violating_edges=conflicts, error=None, fitness=[1, -len(conflicts)])


def worker_task(task):
    """Strict public-only view, including a fresh copy of each edge."""
    validate_graph(task)
    return {"id": task["id"], "vertex_count": task["vertex_count"],
            "color_count": task["color_count"], "edges": [list(e) for e in task["edges"]]}


def load_tasks(path, split=None):
    """Open ONLY the specified public JSON; fail closed on reference fields."""
    if split not in (None, "development", "evaluation"):
        raise ValueError("unknown requested split")
    with Path(path).open(encoding="utf-8") as stream:
        document = json.load(stream)
    if (not isinstance(document, dict) or set(document) != {"protocol", "generator", "tasks"}
            or document["protocol"] != PROTOCOL or not isinstance(document["tasks"], list)):
        raise ValueError("not a public CSP corpus")
    ids, graphs, result = set(), set(), []
    for task in document["tasks"]:
        if not isinstance(task, dict) or set(task) != TASK_KEYS:
            raise ValueError("public task schema required; reference data is forbidden")
        validate_graph(task)
        digest = graph_digest(task)
        if task["id"] in ids or digest in graphs:
            raise ValueError("duplicate task id or labeled graph")
        ids.add(task["id"])
        graphs.add(digest)
        if split is None or task["split"] == split:
            result.append(worker_task(task))
    return result


def connected(n, edges):
    neighbors = [set() for _ in range(n)]
    for u, v in edges:
        neighbors[u].add(v)
        neighbors[v].add(u)
    reached, pending = {0}, [0]
    while pending:
        for vertex in neighbors[pending.pop()] - reached:
            reached.add(vertex)
            pending.append(vertex)
    return len(reached) == n


def generate(seed=GENERATION_SEED):
    rng, tasks, references, seen = random.Random(seed), [], {}, set()
    development = [(24, 3, 20), (24, 4, 40), (40, 3, 40), (40, 4, 20)]
    evaluation = [(n, k, density) for n in (24, 40, 64)
                  for k in (3, 4) for density in (20, 40)]
    for split, design in (("development", development), ("evaluation", evaluation)):
        for n, k, density in design:
            # Balanced planted classes are permuted, avoiding index-mod-k answers.
            assignment = [i % k for i in range(n)]
            rng.shuffle(assignment)
            eligible = [(u, v) for u in range(n) for v in range(u + 1, n)
                        if assignment[u] != assignment[v]]
            # Density refers to eligible cross-class pairs, not all vertex pairs.
            edge_count = (len(eligible) * density + 50) // 100
            for _ in range(10000):
                edges = sorted(map(list, rng.sample(eligible, edge_count)))
                if not connected(n, edges):
                    continue
                task = dict(id="pending", split=split, vertex_count=n, color_count=k, edges=edges)
                digest = graph_digest(task)
                if digest not in seen:
                    break
            else:
                raise RuntimeError("could not sample a unique connected planted graph")
            task["id"] = f"{split[:3]}-csp-{digest[:16]}"
            seen.add(digest)
            witness = {"assignment": assignment}
            if not verify_assignment(task, witness)["solved"]:
                raise AssertionError("invalid generated witness")
            tasks.append(task)
            references[task["id"]] = dict(assignment=assignment,
                eligible_pair_density_percent=density, eligible_pair_count=len(eligible),
                edge_count=edge_count, graph_sha256=digest)
    generator = dict(seed=seed, algorithm="balanced planted classes; uniformly sample fixed-count cross-class edges conditioned on connectivity",
        development_design=[list(row) for row in development], evaluation_design=[list(row) for row in evaluation],
        density_definition="percentage of eligible cross-class pairs; rounded half up",
        evaluation_policy="untouched by model calls at generation; reproducible, not cryptographically hidden",
        limitations=["planted distribution only; no hardness guarantee", "uniqueness is labeled-graph equality, not graph-isomorphism screening",
                    "colorability witnesses never enter worker inputs"])
    public = dict(protocol=PROTOCOL, generator=generator, tasks=tasks)
    private = dict(protocol=PROTOCOL, role="reference validation only; never load in workers",
                   generation_seed=seed, witnesses=references)
    return public, private


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    public, private = generate()
    if args.output:
        args.output.mkdir(parents=True, exist_ok=True)
        for name, value in (("tasks.json", public), ("reference-witnesses.json", private)):
            path = args.output / name
            data = json.dumps(value, indent=2, ensure_ascii=False) + "\n"
            if path.exists() and path.read_text() != data:
                raise FileExistsError(f"refusing to overwrite different frozen corpus: {path}")
            path.write_text(data)
    print(json.dumps(dict(protocol=PROTOCOL, seed=GENERATION_SEED, tasks=len(public["tasks"]),
                          development=4, evaluation=12, model_calls=0)))


if __name__ == "__main__":
    main()
