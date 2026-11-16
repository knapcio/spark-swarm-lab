#!/usr/bin/env python3
"""One DeepSeek reference call on one arithmetic case, streamed (no wall-clock quality cutoff).

Exactly the frozen index_original method of followup72 (source 638b9f3, imported unchanged):
same prompt, system prompt, max_tokens 8192, temperature 0.8, request-seed derivation, thinking on,
strict JSON parser and exact verifier. Only the transport differs: stream=True, and a gap of
IDLE_TIMEOUT seconds without any streamed byte is a hung-server infrastructure failure.
"""
import argparse
import hashlib
import json
import sys
import time
import urllib.request
import uuid
from pathlib import Path

FROZEN = Path(__file__).resolve().parent / '.runtime/nemotron72-followup-source'
sys.path.insert(0, str(FROZEN))
from direct_solver import replay_plan  # noqa: E402
from followup72 import prompt_for  # noqa: E402
from harness import Budget, Events, Experiment, canonical, fingerprint, parse_json_response, parse_puzzle  # noqa: E402

SYSTEM = 'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'
IDLE_TIMEOUT = 120
WALL_LIMIT = 1800


class StreamClient:
    def __init__(self, endpoint, model, budget, events, seed):
        self.url = endpoint.rstrip('/') + '/chat/completions'
        self.model, self.budget, self.events, self.seed = model, budget, events, seed
        self.infra_failures = self.budget_failures = 0

    def call(self, agent_id, stage, prompt, max_tokens, **context):
        request_id = uuid.uuid4().hex[:12]
        if not self.budget.reserve(max_tokens):
            self.budget_failures += 1
            return None
        material = f'{self.seed}:{agent_id}:{stage}:{prompt}'  # identical to the frozen client
        seed = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], 'big')
        body = dict(model=self.model, messages=[{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}],
                    max_tokens=max_tokens, temperature=0.8, seed=seed, stream=True,
                    stream_options={'include_usage': True}, chat_template_kwargs={'enable_thinking': True})
        wire = json.dumps(body).encode()
        self.events.emit('request_start', request_id=request_id, agent_id=agent_id, endpoint_index=0, stage=stage,
                         request_body=body, request_body_sha256=hashlib.sha256(wire).hexdigest(),
                         request_max_tokens=max_tokens, request_thinking=True, **context)
        start = time.monotonic()
        content, reasoning, finish, usage, error, received = '', '', None, {}, None, False
        try:
            request = urllib.request.Request(self.url, data=wire, headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(request, timeout=IDLE_TIMEOUT) as response:
                for raw in response:
                    if time.monotonic() - start > WALL_LIMIT:
                        raise TimeoutError(f'wall limit {WALL_LIMIT}s exceeded')
                    line = raw.decode().strip()
                    if not line.startswith('data:') or line == 'data: [DONE]':
                        continue
                    chunk = json.loads(line[5:])
                    if chunk.get('error'):
                        raise ConnectionError(str(chunk['error'])[:200])
                    for choice in chunk.get('choices', []):
                        delta = choice.get('delta') or {}
                        content += delta.get('content') or ''
                        reasoning += delta.get('reasoning_content') or delta.get('reasoning') or ''
                        finish = choice.get('finish_reason') or finish
                    if chunk.get('usage'):
                        usage = {k: v for k, v in chunk['usage'].items()
                                 if k in ('prompt_tokens', 'completion_tokens', 'total_tokens') and type(v) is int}
            received = finish is not None
            if not received:
                raise ConnectionError('stream ended without finish_reason')
        except Exception as exc:
            error = f'{type(exc).__name__}: {str(exc)[:300]}'
            self.infra_failures += 1
        reported = usage.get('completion_tokens')
        self.budget.settle(max_tokens, reported)
        usage['estimated'] = reported is None
        result = None
        if received:
            try:
                result = parse_json_response(content)
            except (ValueError, json.JSONDecodeError):
                result = None
        self.events.emit('request_end', request_id=request_id, agent_id=agent_id, endpoint_index=0, stage=stage,
                         latency_ms=round((time.monotonic() - start) * 1000, 2), usage=usage,
                         completion_tokens_charged=max_tokens if reported is None else reported, error=error,
                         response=content, reasoning=reasoning, finish_reason=finish, response_received=received, **context)
        return result


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--puzzle', required=True)
    p.add_argument('--endpoint', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--seed', type=int, required=True)
    p.add_argument('--events', required=True)
    p.add_argument('--run', action='store_true')
    args = p.parse_args(argv)
    initial, args.target = parse_puzzle(args.puzzle)
    args.agents, args.allow_fractions, args.thinking, args.rounds = 1, False, True, 5
    if not args.run:
        print(json.dumps(dict(mode='plan', model_calls=0)))
        return 0
    events = Events(args.events, 'index_original_stream')
    budget = Budget(1, 8192)
    client = StreamClient(args.endpoint, args.model, budget, events, args.seed)
    experiment = Experiment(args, client, events)
    puzzle_id = 'p0-' + fingerprint(initial, args.target)[:10]
    events.emit('run_start', config=vars(args), budget=budget.snapshot(),
                scope='DeepSeek reference: frozen index_original method, streamed transport')
    try:
        events.emit('puzzle_start', puzzle_id=puzzle_id, target=args.target, state=canonical(initial))
        root = experiment.node(initial, None, 0, puzzle_id, 0)
        plan = client.call(0, 'plan', prompt_for(experiment, initial, 'index_original'), 8192,
                           node_id=root, puzzle_id=puzzle_id, variant='index_original')
        result = replay_plan(experiment, initial, root, plan, puzzle_id, 0)
        result.update(method='index_original_stream', variant='index_original')
        events.emit('puzzle_end', puzzle_id=puzzle_id, **result)
        summary = dict(solved=int(result['solved']), puzzles=1, budget=budget.snapshot(),
                       infrastructure_failures=client.infra_failures, budget_denials=client.budget_failures,
                       status='complete_with_errors' if client.infra_failures else 'complete')
        events.emit('run_end', **summary)
        print(json.dumps(summary))
        return 0
    except BaseException as exc:
        events.emit('run_end', status='failed', error=f'{type(exc).__name__}: {exc}', budget=budget.snapshot())
        raise
    finally:
        experiment.pool.shutdown(wait=True, cancel_futures=True)
        events.close()


if __name__ == '__main__':
    raise SystemExit(main())
