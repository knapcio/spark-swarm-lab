"""Budget-forced coding agent: one pure-function proposal, graded in the CPU sandbox.

Same transport and forcing rule as forced72 (thinking up to 7168 tokens; if cut without closing
thinking, append "\n</think>\n" and continue the same sequence within 8192). code_plain is the
one-call baseline (8192, no second call). The answer must be Python source (an optional fence is
stripped; nothing else is repaired). The proposal is graded on the FEEDBACK cases; the HOLDOUT
cases are graded once for every parsed proposal so per-agent correctness is known, but only the
feedback result may select a proposal in any swarm analysis. Agents see only the public task.
"""
from coding_harness import context, infrastructure, parse_python_response
from forced72 import END_THINK, TOTAL, THINK_CAP, ForcedClient
from sandbox_code import evaluate_code

VARIANTS = ('code_forced', 'code_plain')
SYSTEM = ('Implement or review the specified pure Python function. Return complete Python source for '
          'code proposals and the requested JSON for voting. Do not explain or use tools.')
INSTRUCTION = '\nReturn complete Python function source only. Do not wrap it in JSON or include explanations.'


class CodingClient(ForcedClient):
    def chat_prompt_ids(self, prompt):
        import json
        messages = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
        with self.post('/tokenize', dict(model=self.model, messages=messages, add_generation_prompt=True,
                                         chat_template_kwargs={'enable_thinking': True}), 60) as response:
            return json.load(response)['tokens']


def parse_code(answer):
    if answer is None:
        return None
    try:
        return parse_python_response(answer, 'code_propose')['code']
    except ValueError:
        return None


def propose(client, task, variant, events, agent_id=0):
    """Returns (code or None, details). Mirrors forced72.run_forced without arithmetic replay."""
    if variant not in VARIANTS:
        raise ValueError('unknown variant')
    plain = variant == 'code_plain'
    prompt_ids = client.chat_prompt_ids(context(task) + INSTRUCTION)
    first = client.complete(agent_id, 'code_propose', prompt_ids, TOTAL if plain else THINK_CAP,
                            puzzle_id=task['id'], variant=variant, followup_phase='think')
    code, second, forced = parse_code(first['answer']), None, False
    eligible = (not plain and code is None and first['response_received'] and first['finish_reason'] == 'length'
                and len(first['token_ids']) > 0 and first['error'] is None)
    if eligible:
        forced = first['answer'] is None
        remaining = TOTAL - client.budget.snapshot()['completion_tokens_charged']
        events.emit('budget_forced' if forced else 'answer_continued', puzzle_id=task['id'], variant=variant,
                    parent_request_id=first['request_id'], forced_after_tokens=len(first['token_ids']),
                    remaining_completion_tokens=remaining)
        second = client.complete(agent_id, 'code_forced_answer' if forced else 'code_continued_answer',
                                 prompt_ids + first['token_ids'] + (client.force_ids() if forced else []), remaining,
                                 thinking_closed=True, puzzle_id=task['id'], variant=variant,
                                 followup_phase='forced_answer' if forced else 'continued_answer',
                                 parent_request_id=first['request_id'])
        answer = second['answer']
        if not forced:
            answer = first['answer'] + (second['text'] if END_THINK not in second['text'] else second['answer'])
        code = parse_code(answer)
    return code, dict(first_request_id=first['request_id'], first_finish_reason=first['finish_reason'],
                      budget_forced=forced, answer_continued=bool(second) and not forced,
                      forced_request_id=second['request_id'] if second else None,
                      forced_finish_reason=second['finish_reason'] if second else None)


def grade(code, task, tests, host, phase, events, evaluator=evaluate_code):
    events.emit('evaluation_start', phase=phase, puzzle_id=task['id'])
    try:
        report = evaluator(code, task['function_name'], tests, host)
    except Exception as exc:  # grader/transport failure is infrastructure, not a candidate outcome
        report = dict(status='error', error=type(exc).__name__ + ': ' + str(exc)[:500], cleanup_ok=False)
    infra = infrastructure(report)
    events.emit('evaluation_end', phase=phase, puzzle_id=task['id'], report=report, infrastructure_error=infra)
    return report, infra


def run_agent(client, task, private, host, variant, events, evaluator=evaluate_code):
    code, details = propose(client, task, variant, events)
    feedback = holdout = None
    infra = 0
    if code is not None:
        feedback, bad = grade(code, task, private['feedback_tests'], host, 'feedback', events, evaluator)
        infra += bad
        holdout, bad = grade(code, task, private['holdout_tests'], host, 'holdout', events, evaluator)
        infra += bad
    feedback_pass = bool(feedback and feedback.get('status') == 'passed')
    holdout_pass = bool(holdout and holdout.get('status') == 'passed')
    return dict(details, code=code, parsed=code is not None, feedback_pass=feedback_pass, holdout_pass=holdout_pass,
                feedback_report=feedback, holdout_report=holdout, grader_infrastructure_errors=infra,
                # Convenience flag for the generic runner: this agent would be selected AND is correct.
                solved=feedback_pass and holdout_pass)
