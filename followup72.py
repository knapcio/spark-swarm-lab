"""One strict arithmetic plan, optionally committed from its own truncated reasoning."""
import hashlib
from harness import InvalidMove, canonical
from direct_solver import build_prompt, replay_plan

VARIANTS = ('index_original', 'index_explicit', 'value_original',
            'value_explicit', 'scribe_full', 'scribe_tail', 'scribe_empty')
COMMIT = ('\n\nWrite the requested complete JSON plan now. Do not explain or start over. '
          'Return only the JSON object, without commentary.')
NOTES = '\nYour own unfinished notes from the immediately preceding request (unverified):\n'
sha = lambda text: hashlib.sha256(text.encode('utf-8')).hexdigest()


def compile_value_move(state, move):
    """Map literal operands to first available distinct occurrences; never repair."""
    if (not isinstance(move, dict) or set(move) != {'a', 'b', 'op'}
            or type(move['a']) is not int or type(move['b']) is not int):
        raise InvalidMove('value move requires exactly integer a, integer b, and op')
    i = next((k for k, value in enumerate(state) if value == move['a']), None)
    j = next((k for k, value in enumerate(state) if k != i and value == move['b']), None)
    if i is None or j is None:
        raise InvalidMove('stated operand occurrence is unavailable')
    return dict(i=i, j=j, op=move['op'])


def prompt_for(e, state, variant):
    prompt = build_prompt(e, state)
    values = variant.startswith('value_')
    if values:
        prompt = prompt.replace(f'Current indexed numbers: {dict(enumerate(canonical(state)))}.',
                                f'Current numbers: {canonical(state)}.')
        prompt = prompt.replace('Each move consumes two different indexed numbers and appends their result; '
            'remaining numbers keep their order and are reindexed from zero.',
            'Each move consumes two different available occurrences of the stated values and appends their result; '
            'remaining numbers keep their order.')
        prompt = prompt.replace('an array of objects with integer indices i,j and single-character operator op.',
            'an array of objects with integer operand values a,b and single-character operator op.')
    if variant in ('index_explicit', 'value_explicit'):
        operands = 'a op b' if values else 'the value at i op the value at j'
        prompt += (' Leftover numbers are allowed. Stop as soon as the target appears anywhere among the '
                   'remaining numbers; it need not be the only remaining number. '
                   f'Compute {operands} literally in that order; do not swap operands.')
    return prompt


def run_followup(experiment, initial, puzzle_id, variant, agent_id=0):
    """Budget(2,8192), original verifier/rules; no CPU search or cross-case memory."""
    if variant not in VARIANTS:
        raise ValueError('unknown followup variant')
    e = experiment
    if e.args.allow_fractions:
        raise ValueError('followup72 uses the frozen positive-integer rules')
    budget = e.client.budget.snapshot()
    if (budget['max_calls'] != 2 or budget['max_completion_tokens'] != 8192
            or budget['calls'] != 0 or budget['completion_tokens_reserved'] != 0):
        raise ValueError('fresh case Budget(2,8192) required')
    root = e.node(initial, None, 0, puzzle_id, agent_id)
    prompt = prompt_for(e, initial, variant)
    scribe = variant.startswith('scribe_')
    plan, first = e.client.call(agent_id, 'plan', prompt, thinking=True,
        max_tokens=7936 if scribe else 8192, return_meta=True,
        node_id=root, puzzle_id=puzzle_id, variant=variant, followup_phase='draft')
    first_parsed = plan
    commit = None
    lineage = {}
    reasoning = first.get('reasoning')
    eligible = (scribe and plan is None and first.get('response_received') is True
                and first.get('finish_reason') == 'length'
                and isinstance(reasoning, str) and bool(reasoning.strip()))
    skip_reason = (None if eligible else 'not_scribe_variant' if not scribe else
                   'parsed_result_non_none' if plan is not None else
                   'response_not_received' if first.get('response_received') is not True else
                   'finish_reason_not_length' if first.get('finish_reason') != 'length' else
                   'reasoning_empty_or_missing')
    if eligible:
        mode = variant.removeprefix('scribe_')
        notes = reasoning if mode == 'full' else reasoning[-4096:] if mode == 'tail' else ''
        lineage = dict(parent_request_id=first['request_id'], full_reasoning_sha256=sha(reasoning),
                       selected_notes_sha256=sha(notes), note_char_length=len(notes), notes_mode=mode)
        e.events.emit('scribe_commit', node_id=root, puzzle_id=puzzle_id, variant=variant, **lineage)
        plan, commit = e.client.call(agent_id, 'scribe', prompt + COMMIT + (NOTES + notes if notes else ''),
            thinking=False, max_tokens=256, return_meta=True, node_id=root, puzzle_id=puzzle_id,
            variant=variant, followup_phase='commit', **lineage)
    result = replay_plan(e, initial, root, plan, puzzle_id, agent_id,
                         compile_action=compile_value_move if variant.startswith('value_') else None)
    result.update(method=variant, variant=variant, first_request_id=first['request_id'],
                  first_parsed_result=first_parsed, scribe_skip_reason=skip_reason,
                  first_finish_reason=first.get('finish_reason'), first_response_received=first.get('response_received'),
                  scribe_triggered=eligible, commit_request_id=commit['request_id'] if commit and commit.get('request_dispatched') else None,
                  commit_dispatched=bool(commit and commit.get('request_dispatched')),
                  commit_error=commit.get('error') if commit else None,
                  commit_finish_reason=commit.get('finish_reason') if commit else None, **lineage)
    return result
