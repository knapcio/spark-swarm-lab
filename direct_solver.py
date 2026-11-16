"""Single-call baseline: verify a proposed arithmetic plan, without search."""
import hashlib
import json

from harness import apply_action, canonical, solved


def build_prompt(e, state, feedback_text=""):
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
    if feedback_text:
        prompt += "\n" + feedback_text[:3999]
    return prompt


def run_direct(experiment, initial, puzzle_id, agent_id=0, feedback_text="", plan_revision=None):
    e = experiment
    node_id = e.node(initial, None, 0, puzzle_id, agent_id)
    prompt = build_prompt(e, initial, feedback_text)
    revision_fields = {} if plan_revision is None else dict(phase="sequential_full_plan_refinement", plan_revision=plan_revision)
    result = e.client.call(agent_id, "plan", prompt, node_id=node_id, puzzle_id=puzzle_id, **revision_fields)
    return replay_plan(e, initial, node_id, result, puzzle_id, agent_id, plan_revision)


def replay_plan(e, initial, node_id, result, puzzle_id, agent_id=0, plan_revision=None, compile_action=None):
    state = initial
    maximum = min(e.args.rounds, len(state) - 1)
    revision_fields = {} if plan_revision is None else dict(phase="sequential_full_plan_refinement", plan_revision=plan_revision)
    validation_error = None
    moves = result.get("moves") if isinstance(result, dict) and set(result) == {"moves"} else None
    if not isinstance(moves, list) or not 1 <= len(moves) <= maximum:
        validation_error = "Expected a bounded nonempty moves array"
        e.events.emit("plan_invalid", node_id=node_id, puzzle_id=puzzle_id,
                      reason=validation_error, **revision_fields)
        moves = []
    for depth, action in enumerate(moves):
        identity = [e.args.seed, puzzle_id, depth, agent_id, canonical(state)]
        if plan_revision is not None:
            identity.append(plan_revision)
        fields = dict(agent_id=agent_id, node_id=node_id, parent_id=node_id, action=action,
                      puzzle_id=puzzle_id, depth=depth,
                      proposal_id=hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:12], **revision_fields)
        try:
            if compile_action is not None:
                fields["model_action"] = action
                action = compile_action(state, action)
                fields["action"] = action
            child = apply_action(state, action, e.args.allow_fractions)
        except (ValueError, TypeError) as exc:
            validation_error = str(exc)
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
    if success:
        validation_error = None
    elif validation_error is None:
        validation_error = "The verified plan ended without reaching the target"
    e.events.emit("reward", node_id=node_id, puzzle_id=puzzle_id, agent_id=agent_id,
                  solved=success, reward=int(success),
                  distance=str(min(abs(e.args.target - x) for x in state)))
    return dict(solved=success, final_state=canonical(state), node_id=node_id,
                plan=result, validation_error=validation_error,
                outcomes=[dict(agent_id=agent_id, solved=success, node_id=node_id)])
