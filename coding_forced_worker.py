#!/usr/bin/env python3
"""One budget-forced (or plain) coding agent on one task. Plan-only unless --run is supplied."""
import argparse
import hashlib
import json
from pathlib import Path

from harness import Budget, Events
from coding_forced import VARIANTS, CodingClient, run_agent


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant', choices=VARIANTS, required=True)
    p.add_argument('--tasks', type=Path, required=True)
    p.add_argument('--tests', type=Path, required=True)
    p.add_argument('--task-id', required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--host', required=True)
    p.add_argument('--model', default='nemotron-lightning')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--events', required=True)
    p.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    public, private = json.loads(args.tasks.read_text()), json.loads(args.tests.read_text())
    task = next((t for t in public['tasks'] if t['id'] == args.task_id), None)
    if task is None or args.task_id not in private['references']:
        p.error('task-id absent from corpus')
    if not args.run:
        print(json.dumps(dict(mode='plan', task=args.task_id, variant=args.variant, model_calls=0)))
        return 0
    events = Events(args.events, args.variant)
    budget = Budget(2, 8192)
    client = CodingClient(args.endpoint, args.model, budget, events, args.seed)
    events.emit('run_start', config={k: str(v) for k, v in vars(args).items()}, budget=budget.snapshot(), task_id=task['id'],
                public_sha256=hashlib.sha256(args.tasks.read_bytes()).hexdigest(),
                private_sha256=hashlib.sha256(args.tests.read_bytes()).hexdigest(),
                scope='Budget-forced coding agent; feedback grade selects, holdout graded once per parsed proposal')
    try:
        events.emit('puzzle_start', puzzle_id=task['id'])
        result = run_agent(client, task, private['references'][task['id']], args.host, args.variant, events)
        events.emit('puzzle_end', puzzle_id=task['id'], **result)
        status = ('complete_with_errors' if client.infra_failures or result['grader_infrastructure_errors'] else
                  'budget_limited' if client.budget_failures else 'complete')
        summary = dict(solved=int(result['solved']), feedback_pass=result['feedback_pass'], holdout_pass=result['holdout_pass'],
                       budget=budget.snapshot(), infrastructure_failures=client.infra_failures + result['grader_infrastructure_errors'],
                       budget_denials=client.budget_failures, status=status)
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
