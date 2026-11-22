#!/usr/bin/env python3
"""One budget-forced agent on one arithmetic case. Plan-only unless --run is supplied."""
import argparse
import json
from pathlib import Path

from harness import Budget, Events, Experiment, canonical, fingerprint, parse_puzzle
from forced72 import CAPS, VARIANTS, ForcedClient, run_forced


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--variant', choices=sorted(VARIANTS), required=True)
    p.add_argument('--puzzle', required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--model', default='nemotron-lightning')
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--events', required=True)
    p.add_argument('--extra-file', type=Path, help='text appended to the task prompt (strategy / critique / board)')
    p.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    extra_text = args.extra_file.read_text() if args.extra_file else ''
    args.extra_file = str(args.extra_file) if args.extra_file else None  # JSON-serializable config
    initial, args.target = parse_puzzle(args.puzzle)
    if any(x.denominator != 1 or x <= 0 for x in initial) or len(initial) not in (4, 6):
        p.error('Study tasks require four or six strictly positive integers')
    args.agents, args.allow_fractions, args.thinking = 1, False, True
    args.rounds, args.max_tokens = 5, 8192
    args.max_calls, args.max_completion_tokens = 2, CAPS[args.variant][1]
    if not args.run:
        print(json.dumps(dict(mode='plan', config=vars(args), model_calls=0)))
        return 0
    events = Events(args.events, args.variant)
    budget = Budget(args.max_calls, args.max_completion_tokens)
    client = ForcedClient(args.endpoint, args.model, budget, events, args.seed)
    client.loop_watch = args.variant == 'xl_forced_watchdog'
    experiment = Experiment(args, client, events)
    puzzle_id = 'p0-' + fingerprint(initial, args.target)[:10]
    events.emit('run_start', config=vars(args), budget=budget.snapshot(),
                scope='Budget-forced agent: no external advisor, no CPU puzzle search, no wall-clock quality limit')
    try:
        events.emit('puzzle_start', puzzle_id=puzzle_id, target=args.target, state=canonical(initial))
        events.emit('extra_prompt', text=extra_text)
        result = run_forced(experiment, initial, puzzle_id, args.variant, extra=extra_text)
        events.emit('puzzle_end', puzzle_id=puzzle_id, **result)
        summary = dict(run_id=events.run_id, solved=int(result['solved']), puzzles=1,
                       budget=budget.snapshot(), events=str(events.path),
                       infrastructure_failures=client.infra_failures,
                       budget_denials=client.budget_failures)
        summary['status'] = ('complete_with_errors' if client.infra_failures else
                             'budget_limited' if client.budget_failures else 'complete')
        events.emit('run_end', **summary)
        print(json.dumps(summary))
        return 0
    except BaseException as exc:
        events.emit('run_end', status='failed', error=f'{type(exc).__name__}: {exc}',
                    budget=budget.snapshot())
        raise
    finally:
        experiment.pool.shutdown(wait=True, cancel_futures=True)
        events.close()


if __name__ == '__main__':
    raise SystemExit(main())
