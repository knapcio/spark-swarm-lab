"""Whole-plan sampling and a cheap-search-then-reasoning cascade."""
from direct_solver import run_direct
from shared_search import run_rounds


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
