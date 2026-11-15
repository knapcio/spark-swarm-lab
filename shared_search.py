"""Round-synchronous paths or shared-frontier search; standard library only.

Shared mode changes deduplication and beam selection as well as state handoff.
It is a search-policy comparison, not a pure memory ablation. GPU caches are
unmodified; the coordinator owns the dictionary and logs its snapshots/writes.
"""
from concurrent.futures import wait
from fractions import Fraction
import hashlib
import json


def _key(state):
    return tuple(sorted(Fraction(x) for x in state))


def _state(state):
    return [str(Fraction(x)) for x in state]


def _solved(row, target):
    return Fraction(target) in row["state"]


def run_rounds(experiment, initial, puzzle_id, shared=False):
    """Use existing verified proposals and client budgets, with one call/worker/round."""
    e, args = experiment, experiment.args
    policy = "shared_frontier_search" if shared else "independent_rounds"
    root = dict(node_id=e.node(initial, None, 0, puzzle_id), state=tuple(initial),
                agent_id=None, parent_id=None)
    paths = {agent: dict(root, agent_id=agent) for agent in range(args.agents)}
    frontier, memory = [root], {_key(initial): root}
    winner = root if _solved(root, args.target) else None

    def choose(row, reason):
        e.events.emit("chosen", node_id=row["node_id"], parent_id=row["parent_id"],
                      candidate_id=row.get("candidate_id"), agent_id=row["agent_id"],
                      puzzle_id=puzzle_id, reason=reason)

    def prune(row, reason):
        e.events.emit("pruned", node_id=row["node_id"], parent_id=row["parent_id"],
                      agent_id=row["agent_id"], puzzle_id=puzzle_id, reason=reason)

    if winner is not None:
        choose(winner, "exact_target_verified")
    for depth in range(args.rounds):
        if winner is not None:
            break
        if shared:
            ready = [row for row in frontier if len(row["state"]) >= 2]
            if not ready:
                break
            # A frozen previous-round frontier; no fastest-response preference.
            assignments = [(agent, ready[(agent + args.seed + depth) % len(ready)])
                           for agent in range(args.agents)]
            e.events.emit("memory_snapshot", puzzle_id=puzzle_id, round=depth,
                          policy=policy, memory_states=len(memory),
                          frontier=[dict(node_id=r["node_id"], state=_state(r["state"]),
                                         source_agent_id=r["agent_id"]) for r in ready])
        else:
            assignments = [(agent, row) for agent, row in sorted(paths.items())
                           if len(row["state"]) >= 2 and not row.get("stopped")]
        if not assignments:
            break
        futures = [e.pool.submit(e.proposal, agent, row["state"], row["node_id"],
                                 depth, puzzle_id) for agent, row in assignments]
        wait(futures)  # No publication or next-round requests until every proposal finishes.
        proposals = []
        for (agent, parent), future in zip(assignments, futures):
            proposal = future.result()
            if proposal is None:
                if not shared:
                    paths[agent]["stopped"] = True
                continue
            row = dict(proposal, agent_id=agent, parent_id=parent["node_id"])
            proposals.append(row)
            if shared:
                memory.setdefault(_key(row["state"]), row)
                e.events.emit("memory_write", puzzle_id=puzzle_id, round=depth,
                              policy=policy, node_id=row["node_id"],
                              parent_id=row["parent_id"], source_agent_id=agent,
                              candidate_id=row.get("candidate_id"),
                              action=row["action"], state=_state(row["state"]),
                              verified_transition=True)
        # Exact acceptance precedes deduplication/hash selection, in both policies.
        winner = next((row for row in proposals if _solved(row, args.target)), None)
        if winner is not None:
            choose(winner, "exact_target_verified")
            for row in proposals:
                if row is not winner:
                    prune(row, "verified_solution_found")
            if shared:
                frontier = [winner]
            else:
                # Credit every actually generated path, including other exact solutions.
                for row in proposals:
                    paths[row["agent_id"]] = row
            break
        if not proposals:
            break
        if not shared:
            for row in proposals:
                paths[row["agent_id"]] = row
                choose(row, "independent_round_transition")
            continue
        unique = {}
        for row in proposals:
            key = _key(row["state"])
            if key in unique:
                prune(row, "duplicate_state")
            else:
                unique[key] = row

        def rank(row):
            payload = [args.seed, depth, _state(_key(row["state"]))]
            return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).digest()

        ordered = sorted(unique.values(), key=rank)
        frontier = [memory[_key(row["state"])] for row in ordered[:4]]
        for row in frontier:
            choose(row, "shared_frontier_hash_selection")
        for row in ordered[4:]:
            prune(row, "frontier_limit")

    def outcome(row, agent_id):
        success = _solved(row, args.target)
        distance = str(min(abs(Fraction(args.target) - Fraction(x)) for x in row["state"]))
        e.events.emit("reward", node_id=row["node_id"], puzzle_id=puzzle_id,
                      agent_id=agent_id, solved=success, reward=int(success), distance=distance)
        return dict(agent_id=agent_id, solved=success, node_id=row["node_id"],
                    state=_state(row["state"]), distance=distance)

    if shared:
        final = [outcome(row, row["agent_id"]) for row in frontier]
        return dict(solved=winner is not None, policy=policy,
                    node_id=(winner or frontier[0])["node_id"], frontier=final,
                    memory_states=len(memory))
    outcomes = [outcome(row, agent) for agent, row in sorted(paths.items())]
    return dict(solved=winner is not None, policy=policy,
                node_id=(winner or root)["node_id"], outcomes=outcomes)
