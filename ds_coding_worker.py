#!/usr/bin/env python3
"""One DeepSeek coding attempt on one coding-hard task (streamed chat, no wall-clock cutoff).

Same public task context, Python-source instruction, strict source parser and CPU sandbox grading
as the Nemotron coding agents (coding_forced, source b147453): the proposal is graded on feedback
cases and once on holdout cases. Model: native DeepSeek V4.1 via an owned tunnel; thinking on,
frontend default effort, max_tokens from the plan.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

CODING = Path(__file__).resolve().parent / '.runtime/coding-forced-source'
sys.path.insert(0, str(CODING))
from coding_forced import INSTRUCTION, SYSTEM, grade, parse_code  # noqa: E402
from coding_harness import context  # noqa: E402
from harness import Budget, Events  # noqa: E402
import ds_stream_worker as stream  # noqa: E402  (StreamClient: identical streamed transport)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--tasks', type=Path, required=True)
    p.add_argument('--tests', type=Path, required=True)
    p.add_argument('--task-id', required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--host', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--max-tokens', type=int, default=32768)
    p.add_argument('--events', required=True)
    p.add_argument('--run', action='store_true')
    a = p.parse_args(argv)
    public, private = json.loads(a.tasks.read_text()), json.loads(a.tests.read_text())
    task = next(t for t in public['tasks'] if t['id'] == a.task_id)
    if not a.run:
        print(json.dumps(dict(mode='plan', model_calls=0)))
        return 0
    events = Events(a.events, 'ds_code')
    budget = Budget(1, a.max_tokens)
    stream.SYSTEM = SYSTEM  # coding system prompt (same text the Nemotron coding agents use)
    client = stream.StreamClient(a.endpoint, a.model, budget, events, a.seed)
    events.emit('run_start', config={k: str(v) for k, v in vars(a).items()}, task_id=task['id'],
                public_sha256=hashlib.sha256(a.tasks.read_bytes()).hexdigest())
    try:
        events.emit('puzzle_start', puzzle_id=task['id'])
        client.call(0, 'code_propose', context(task) + INSTRUCTION, a.max_tokens, puzzle_id=task['id'], variant='ds_code')
        end = [json.loads(line) for line in Path(a.events).read_text().splitlines()
               if '"request_end"' in line][-1]
        answer = end.get('response') if end.get('response_received') else None
        code = parse_code(answer)
        feedback = holdout = None
        infra = client.infra_failures
        if code is not None:
            feedback, bad = grade(code, task, private['references'][task['id']]['feedback_tests'], a.host, 'feedback', events)
            infra += bad
            holdout, bad = grade(code, task, private['references'][task['id']]['holdout_tests'], a.host, 'holdout', events)
            infra += bad
        fb = bool(feedback and feedback.get('status') == 'passed')
        ho = bool(holdout and holdout.get('status') == 'passed')
        result = dict(parsed=code is not None, feedback_pass=fb, holdout_pass=ho, solved=fb and ho, code=code,
                      finish_reason=end.get('finish_reason'), grader_infrastructure_errors=infra - client.infra_failures)
        events.emit('puzzle_end', puzzle_id=task['id'], **result)
        summary = dict(solved=int(fb and ho), feedback_pass=fb, holdout_pass=ho, budget=budget.snapshot(),
                       infrastructure_failures=infra, budget_denials=0,
                       status='complete_with_errors' if infra else 'complete')
        events.emit('run_end', **summary)
        print(json.dumps(summary))
        return 0
    except BaseException as exc:
        events.emit('run_end', status='failed', error=f'{type(exc).__name__}: {exc}', budget=budget.snapshot())
        raise
    finally:
        events.close()


if __name__ == '__main__':
    raise SystemExit(main())
