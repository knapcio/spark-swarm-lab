"""Single-call baseline: verify a proposed arithmetic plan, without search."""
import hashlib
import json

from harness import apply_action, canonical, solved


def run_direct(experiment, initial, puzzle_id, agent_id=0):
    e = experiment
    state, node_id = initial, e.node(initial, None, 0, puzzle_id, agent_id)
    maximum = min(e.args.rounds, len(state) - 1)
    rule = "positive rational" if e.args.allow_fractions else "positive integer"
    prompt = (
        f"Target {e.args.target}. Current indexed numbers: {dict(enumerate(canonical(state)))}. "
        "Give one complete plan to reach the target using any subset of numbers. "
        "Each move consumes two different indexed numbers and appends their result; "
        "remaining numbers keep their order and are reindexed from zero. "
        f"Use +,-,*,/. Every intermediate result must be {rule}. "
        f"Use at most {maximum} moves. Return only a JSON object with key moves, "
        "an array of objects with integer indices i,j and single-character operator op."
    )
    result = e.client.call(agent_id, "plan", prompt, node_id=node_id, puzzle_id=puzzle_id)
    moves = result.get("moves") if isinstance(result, dict) and set(result) == {"moves"} else None
    if not isinstance(moves, list) or not 1 <= len(moves) <= maximum:
        e.events.emit("plan_invalid", node_id=node_id, puzzle_id=puzzle_id,
                      reason="Expected a bounded nonempty moves array")
        moves = []
    for depth, action in enumerate(moves):
        fields = dict(agent_id=agent_id, node_id=node_id, parent_id=node_id, action=action,
                      puzzle_id=puzzle_id, depth=depth,
                      proposal_id=hashlib.sha256(json.dumps([
                          e.args.seed, puzzle_id, depth, agent_id, canonical(state)
                      ]).encode()).hexdigest()[:12])
        try:
            child = apply_action(state, action, e.args.allow_fractions)
        except (ValueError, TypeError) as exc:
            e.events.emit("proposal", legal=False, error=str(exc), **fields)
            break
        child_id = e.node(child, node_id, depth + 1, puzzle_id, agent_id)
        e.events.emit("proposal", legal=True, child_node_id=child_id,
                      child_state=canonical(child), **fields)
        e.events.emit("chosen", node_id=child_id, parent_id=node_id, puzzle_id=puzzle_id,
                      candidate_id=fields["proposal_id"], agent_id=agent_id, reason="verified_plan_step")
        state, node_id = child, child_id
        if solved(state, e.args.target):
            break
    success = solved(state, e.args.target)
    e.events.emit("reward", node_id=node_id, puzzle_id=puzzle_id, agent_id=agent_id,
                  solved=success, reward=int(success),
                  distance=str(min(abs(e.args.target - x) for x in state)))
    return dict(solved=success, final_state=canonical(state), node_id=node_id,
                outcomes=[dict(agent_id=agent_id, solved=success, node_id=node_id)])
