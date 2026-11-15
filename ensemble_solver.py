"""Whole-plan sampling, sequential refinement, and a cheap/reasoning cascade."""
import json

from direct_solver import run_direct
from shared_search import run_rounds


def run_refine(experiment, initial, puzzle_id):
    """At most four own full plans, using exact verification feedback only."""
    e, feedback_text, attempts = experiment, "", []
    if e.args.agents != 1:
        raise ValueError("refine requires exactly one agent")
    e.events.emit("phase_start", puzzle_id=puzzle_id, phase="sequential_full_plan_refinement",
                  agents=1, max_plans=4, thinking=e.client.thinking, max_tokens=e.client.max_tokens)
    for revision in range(4):
        e.events.emit("plan_revision", puzzle_id=puzzle_id, agent_id=0,
                      phase="sequential_full_plan_refinement", plan_revision=revision,
                      feedback_text=feedback_text)
        result = run_direct(e, initial, puzzle_id, agent_id=0,
                            feedback_text=feedback_text, plan_revision=revision)
        attempts.append(result)
        e.events.emit("plan_revision_complete", puzzle_id=puzzle_id, agent_id=0,
                      plan_revision=revision, solved=result["solved"],
                      validation_error=result["validation_error"], final_state=result["final_state"])
        if result["solved"] or revision == 3:
            break
        feedback_text = (
            f"Full-plan attempt {revision + 2} of 4. Revise only your own previous plan. "
            "The following is exact verification feedback, not a proof that other plans are impossible.\n"
            f"Verifier error: {result['validation_error']}\n"
            f"Verified final state: {json.dumps(result['final_state'])}\n"
            f"Your previous parsed plan: {json.dumps(result['plan'], ensure_ascii=False)}"
        )[:3999]
    e.events.emit("phase_end", puzzle_id=puzzle_id, phase="sequential_full_plan_refinement",
                  solved=result["solved"], plans=len(attempts))
    return dict(result, policy="sequential_full_plan_refinement", plan_attempts=len(attempts))


def run_ensemble(experiment, initial, puzzle_id):
    e = experiment
    e.events.emit("phase_start", puzzle_id=puzzle_id, phase="parallel_full_plans",
                  agents=e.args.agents, thinking=e.client.thinking,
                  max_tokens=e.client.max_tokens)
    futures = [e.pool.submit(run_direct, e, initial, puzzle_id, agent)
               for agent in range(e.args.agents)]
    results = [future.result() for future in futures]
    winner = next((row for row in results if row["solved"]), results[0])
    return dict(solved=any(row["solved"] for row in results), node_id=winner["node_id"],
                policy="parallel_full_plans", outcomes=[row["outcomes"][0] for row in results])


def run_cascade(experiment, initial, puzzle_id):
    e = experiment
    e.events.emit("phase_start", puzzle_id=puzzle_id, phase="cheap_parallel_search",
                  agents=e.args.agents, thinking=e.client.thinking,
                  max_tokens=e.client.max_tokens)
    cheap = run_rounds(e, initial, puzzle_id, shared=False)
    e.events.emit("phase_end", puzzle_id=puzzle_id, phase="cheap_parallel_search",
                  solved=cheap["solved"])
    if cheap["solved"]:
        return dict(cheap, policy="cheap_then_reason", fallback_used=False)
    previous = e.client.thinking, e.client.max_tokens
    try:
        e.client.thinking, e.client.max_tokens = True, 8192
        e.events.emit("phase_start", puzzle_id=puzzle_id, phase="reasoning_full_plan",
                      agents=1, thinking=True, max_tokens=8192,
                      note="Original task; no reference witness or solver hints")
        result = run_direct(e, initial, puzzle_id)
        return dict(result, policy="cheap_then_reason", fallback_used=True,
                    cheap_outcomes=cheap["outcomes"])
    finally:
        e.client.thinking, e.client.max_tokens = previous
