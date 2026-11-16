"""Scribe agents with explicit rule wording; frozen followup72 modules stay byte-identical.

scribe_explicit: index_explicit prompt (states the verifier's existing rules: leftovers allowed,
stop when the target appears, compute operands in the stated order), thinking ON capped at 7936;
only if the parsed result is exactly None, a response was received, finish_reason=length and own
reasoning is non-empty, one thinking-OFF call capped at 256 with ALL own notes.
scribe_explicit_short: same, first call capped at 3840 (more, shorter attempts per token).
"""
from direct_solver import replay_plan
from followup72 import COMMIT, NOTES, prompt_for, sha

VARIANTS = ('scribe_explicit', 'scribe_explicit_short')
FIRST_CAP = {'scribe_explicit': 7936, 'scribe_explicit_short': 3840}


def run_agent(experiment, initial, puzzle_id, variant, agent_id=0):
    """Budget(2,8192), original verifier/rules; no CPU search or cross-case memory."""
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    e = experiment
    if e.args.allow_fractions:
        raise ValueError('frozen positive-integer rules only')
    budget = e.client.budget.snapshot()
    if (budget['max_calls'] != 2 or budget['max_completion_tokens'] != 8192
            or budget['calls'] != 0 or budget['completion_tokens_reserved'] != 0):
        raise ValueError('fresh case Budget(2,8192) required')
    root = e.node(initial, None, 0, puzzle_id, agent_id)
    prompt = prompt_for(e, initial, 'index_explicit')
    plan, first = e.client.call(agent_id, 'plan', prompt, thinking=True, max_tokens=FIRST_CAP[variant],
                                return_meta=True, node_id=root, puzzle_id=puzzle_id, variant=variant,
                                followup_phase='draft')
    first_parsed, commit, lineage = plan, None, {}
    reasoning = first.get('reasoning')
    eligible = (plan is None and first.get('response_received') is True
                and first.get('finish_reason') == 'length'
                and isinstance(reasoning, str) and bool(reasoning.strip()))
    skip_reason = (None if eligible else 'parsed_result_non_none' if plan is not None else
                   'response_not_received' if first.get('response_received') is not True else
                   'finish_reason_not_length' if first.get('finish_reason') != 'length' else
                   'reasoning_empty_or_missing')
    if eligible:
        lineage = dict(parent_request_id=first['request_id'], full_reasoning_sha256=sha(reasoning),
                       selected_notes_sha256=sha(reasoning), note_char_length=len(reasoning), notes_mode='full')
        e.events.emit('scribe_commit', node_id=root, puzzle_id=puzzle_id, variant=variant, **lineage)
        plan, commit = e.client.call(agent_id, 'scribe', prompt + COMMIT + NOTES + reasoning,
                                     thinking=False, max_tokens=256, return_meta=True, node_id=root,
                                     puzzle_id=puzzle_id, variant=variant, followup_phase='commit', **lineage)
    result = replay_plan(e, initial, root, plan, puzzle_id, agent_id)
    result.update(method=variant, variant=variant, first_request_id=first['request_id'],
                  first_parsed_result=first_parsed, scribe_skip_reason=skip_reason,
                  first_finish_reason=first.get('finish_reason'), first_response_received=first.get('response_received'),
                  scribe_triggered=eligible,
                  commit_request_id=commit['request_id'] if commit and commit.get('request_dispatched') else None,
                  commit_dispatched=bool(commit and commit.get('request_dispatched')),
                  commit_error=commit.get('error') if commit else None,
                  commit_finish_reason=commit.get('finish_reason') if commit else None, **lineage)
    return result
