"""Bounded same-model reviewing and color-symmetry-aware consensus policies."""
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
from itertools import permutations
import time

from csp_tasks import canonical_json, verify_assignment, worker_task

SOCIAL_ARMS = ("review_elites4", "democracy4", "weighted_democracy4")


def rank_candidates(candidates):
    return sorted(candidates, key=lambda c: (-c["verification"]["fitness"][0],
                  -c["verification"]["fitness"][1], c["index"]))


def align_colors(colors, anchor, color_count):
    """Maximum agreement over all color permutations; lexicographic tie break."""
    if (type(color_count) is not int or not 2 <= color_count <= 8 or
            not isinstance(colors, list) or not isinstance(anchor, list) or len(colors) != len(anchor) or
            any(type(v) is not int or not 0 <= v < color_count for v in colors + anchor)):
        raise ValueError("equal-length valid color lists and 2..8 colors required")
    best = None
    for permutation in permutations(range(color_count)):
        aligned = [permutation[value] for value in colors]
        agreement = sum(a == b for a, b in zip(aligned, anchor))
        if best is None or agreement > best[0]:
            best = (agreement, permutation, aligned)
    return dict(agreement=best[0], permutation=list(best[1]), assignment=best[2])


def color_consensus(population, color_count, weighted=False):
    """Derived assignment, with exact rational votes and complete provenance.

    Invalid candidates do not vote. Ties prefer the anchor color, then the
    smallest color. This transforms candidates mechanically; it is not a new
    model sample, nor an oracle-provided correction.
    """
    valid = rank_candidates([c for c in population if c["verification"]["valid_schema"]])
    if not valid:
        return None
    anchor = valid[0]
    anchor_colors = anchor["payload"]["assignment"]
    votes = [[Fraction(0) for _ in range(color_count)] for _ in anchor_colors]
    aligned_sources = []
    for candidate in valid:
        aligned = align_colors(candidate["payload"]["assignment"], anchor_colors, color_count)
        weight = Fraction(1, 1 + candidate["verification"]["conflicts"]) if weighted else Fraction(1)
        for vertex, color in enumerate(aligned["assignment"]):
            votes[vertex][color] += weight
        aligned_sources.append(dict(candidate_id=candidate["id"], **aligned,
                                    weight=[weight.numerator, weight.denominator]))
    assignment = []
    for vertex, tally in enumerate(votes):
        tied = [color for color, value in enumerate(tally) if value == max(tally)]
        assignment.append(anchor_colors[vertex] if anchor_colors[vertex] in tied else min(tied))
    return dict(payload={"assignment": assignment}, anchor_id=anchor["id"],
                source_ids=[c["id"] for c in valid], alignments=aligned_sources,
                votes=[[[v.numerator, v.denominator] for v in tally] for tally in votes],
                weighted=weighted)


def run_social_search(task, arm, client, events, base_prompt, max_calls=16):
    """At most max_calls Client.call invocations, including reviewer calls.

    Every dispatched batch finishes before stopping. Reviews are model output,
    not verified facts. Derived consensuses have no model-call charge and are
    counted separately from generated assignment candidates.
    """
    if arm not in SOCIAL_ARMS:
        raise ValueError("unknown social arm")
    if type(max_calls) is not int or max_calls < 4 or max_calls % 4:
        raise ValueError("max_calls must be an integer multiple of four, at least four")
    task = worker_task(task)
    if not isinstance(base_prompt, str):
        raise ValueError("base_prompt must be text")
    start = time.monotonic()
    candidates, reviews, derived, seen = [], [], [], {}
    attempted_calls = 0
    initial_calls = client.budget.snapshot()["calls"] if hasattr(client, "budget") else None

    def elapsed():
        return time.monotonic() - start

    def context(candidate):
        return dict(id=candidate["id"], candidate=candidate["payload"],
                    verification=candidate["verification"])

    def propose(index, agent, parents, review_sources, operation):
        prompt = base_prompt
        if parents:
            prompt += "\nPrevious assignments and exact verification: " + canonical_json([context(p) for p in parents])
            prompt += "\nUse these as repair context; return one full assignment."
        usable = [r for r in review_sources if r["valid_schema"]]
        if usable:
            prompt += "\nSame-model reviewer suggestions (unverified; check them against the graph): "
            prompt += canonical_json([dict(id=r["id"], critique=r["payload"]["critique"]) for r in usable])
        payload = client.call(agent, "candidate-" + str(index), prompt,
                              puzzle_id=task["id"], candidate_index=index,
                              parent_ids=[p["id"] for p in parents],
                              review_ids=[r["id"] for r in usable], operation=operation)
        proof = verify_assignment(task, payload)
        return dict(id=f"candidate-{index}", index=index, agent=agent,
                    parents=[p["id"] for p in parents], review_ids=[r["id"] for r in usable],
                    operation=operation, origin="model", payload=payload, verification=proof,
                    sha256=hashlib.sha256(canonical_json(payload).encode()).hexdigest(),
                    verified_elapsed_seconds=elapsed())

    def emit_assignment(candidate, kind):
        events.emit(kind, puzzle_id=task["id"], **candidate)
        events.emit("reward", puzzle_id=task["id"], node_id=candidate["id"],
                    solved=candidate["verification"]["solved"],
                    reward=int(candidate["verification"]["solved"]),
                    origin=candidate["origin"],
                    elapsed_seconds=candidate["verified_elapsed_seconds"])

    def assignment_batch(jobs):
        nonlocal attempted_calls
        if attempted_calls + len(jobs) > max_calls:
            raise AssertionError("social model-call ceiling exceeded")
        attempted_calls += len(jobs)
        with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
            rows = list(pool.map(lambda job: propose(*job), jobs))
        for row in rows:
            row["duplicate_of"] = seen.get(row["sha256"])
            seen.setdefault(row["sha256"], row["id"])
            candidates.append(row)
            emit_assignment(row, "candidate")
        return rows

    def review_one(index, reviewer, elites):
        # Deliberately do not reuse the assignment-producing base prompt.
        prompt = ("Review graph-coloring assignments. Return ONLY a JSON object with exactly "
                  "one key critique containing a concise string. Do not return an assignment. "
                  "Identify concrete problems or useful repair ideas for the two target assignments. "
                  "You are the same model as the solvers; your suggestions are unverified. No tools.\nTask: "
                  + canonical_json(task) + "\nYour earlier attempt and exact verification: "
                  + canonical_json(context(reviewer)) + "\nTargets and exact verification: "
                  + canonical_json([context(p) for p in elites]))
        payload = client.call(reviewer["agent"], "review-" + str(index), prompt,
                              puzzle_id=task["id"], operation="review",
                              reviewer_candidate_id=reviewer["id"], target_ids=[p["id"] for p in elites])
        valid = (isinstance(payload, dict) and set(payload) == {"critique"}
                 and isinstance(payload["critique"], str) and 0 < len(payload["critique"]) <= 4000)
        return dict(id=f"review-{index}", index=index, agent=reviewer["agent"],
                    reviewer_candidate_id=reviewer["id"], target_ids=[p["id"] for p in elites],
                    payload=payload, valid_schema=valid, verified_fact=False,
                    completed_elapsed_seconds=elapsed())

    def review_batch(reviewers, elites):
        nonlocal attempted_calls
        if attempted_calls + len(reviewers) > max_calls:
            raise AssertionError("social model-call ceiling exceeded")
        attempted_calls += len(reviewers)
        offset = len(reviews)
        with ThreadPoolExecutor(max_workers=len(reviewers)) as pool:
            rows = list(pool.map(lambda job: review_one(*job),
                        [(offset + i, reviewer, elites) for i, reviewer in enumerate(reviewers)]))
        for row in rows:
            reviews.append(row)
            events.emit("review", puzzle_id=task["id"], **row)
        return rows

    def solved():
        return any(c["verification"]["solved"] for c in candidates + derived)

    def derive(population, generation):
        ballot = color_consensus(population, task["color_count"], arm == "weighted_democracy4")
        if ballot is None:
            events.emit("consensus_skipped", puzzle_id=task["id"], generation=generation,
                        reason="no_valid_assignment", elapsed_seconds=elapsed())
            return None
        row = dict(id=f"derived-consensus-{generation}", index=100000 + generation,
                   agent=None, parents=ballot["source_ids"], review_ids=[],
                   operation="weighted_consensus" if ballot["weighted"] else "consensus",
                   origin="derived", payload=ballot["payload"],
                   verification=verify_assignment(task, ballot["payload"]),
                   sha256=hashlib.sha256(canonical_json(ballot["payload"]).encode()).hexdigest(),
                   model_calls=0, ballot=ballot, verified_elapsed_seconds=elapsed())
        derived.append(row)
        emit_assignment(row, "derived_candidate")
        return row

    population = assignment_batch([(i, i, [], [], "fresh") for i in range(4)])
    if arm == "review_elites4":
        for generation in range(1, max_calls // 4):
            if solved():
                break
            ordered = rank_candidates(population)
            elites, reviewers = ordered[:2], ordered[2:]
            events.emit("review_delegation", puzzle_id=task["id"], generation=generation,
                        elite_ids=[p["id"] for p in elites],
                        reviewer_candidate_ids=[p["id"] for p in reviewers], elapsed_seconds=elapsed())
            round_reviews = review_batch(reviewers, elites)
            offset = len(candidates)
            children = assignment_batch([(offset + i, elite["agent"], [elite], round_reviews,
                                          "review_guided_repair") for i, elite in enumerate(elites)])
            survivors = rank_candidates(population + children)[:4]
            events.emit("selection", puzzle_id=task["id"], generation=generation,
                        survivor_ids=[p["id"] for p in survivors],
                        pruned_ids=[p["id"] for p in population + children if p not in survivors],
                        elapsed_seconds=elapsed())
            population = survivors
    else:
        for generation in range(max_calls // 4):
            if solved():
                break
            consensus = derive(population, generation)
            if solved() or generation == max_calls // 4 - 1:
                break
            offset = len(candidates)
            jobs = [(offset + i, i, [own, consensus] if consensus else [], [],
                     "consensus_guided_repair" if consensus else "fresh") for i, own in enumerate(population)]
            children = assignment_batch(jobs)
            events.emit("selection", puzzle_id=task["id"], generation=generation + 1,
                        survivor_ids=[p["id"] for p in children],
                        pruned_ids=[p["id"] for p in population],
                        reason="four_chains_advance_one_step", elapsed_seconds=elapsed())
            population = children
    best = rank_candidates(candidates + derived)[0]
    actual_calls = (client.budget.snapshot()["calls"] - initial_calls
                    if initial_calls is not None else attempted_calls)
    result = dict(solved=solved(), candidate_count=len(candidates), unique_candidates=len(seen),
                  best_candidate_id=best["id"], best_verification=best["verification"],
                  best_payload=best["payload"], best_candidate_origin=best["origin"],
                  review_count=len(reviews), derived_count=len(derived),
                  model_call_count=actual_calls, attempted_model_calls=attempted_calls,
                  elapsed_seconds=elapsed())
    events.emit("search_end", **result)
    return result
