#!/usr/bin/env python3
"""Thinking-workload throughput: C concurrent streamed raw completions through the vLLM-dialect endpoint.

Workload = the swarm's real shape: synthetic arithmetic puzzles (seeded, not from any evaluation set),
thinking on, temperature 0.8, fixed max_tokens, no early stop besides the model's own end. Reports
aggregate completion tok/s over the full wall, per-request decode tok/s and the server's speculative
acceptance length before/after (sglang:spec_accept_length via /metrics, if present).
"""
import argparse
import json
import random
import re
import statistics
import threading
import time
import urllib.request

SYSTEM = 'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'


def post(base, path, body, timeout=3600):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(), headers={'Content-Type': 'application/json'})
    return urllib.request.urlopen(req, timeout=timeout)


def puzzle(rng):
    nums = [rng.randint(1, 13) for _ in range(5)]
    target = rng.randint(100, 999)
    return (f'Numbers: {nums}. Target: {target}. Using each number at most once and only + - * / with positive '
            f'integer intermediate results, reach the target exactly. Return {{"steps": [...], "result": n}}.')


def metric(base, name):
    try:
        text = urllib.request.urlopen(base + '/metrics', timeout=10).read().decode()
        m = re.search(rf'^sglang:{name}{{[^}}]*}} (\S+)', text, re.M)
        return float(m.group(1)) if m else None
    except Exception:  # noqa: BLE001
        return None


def one(base, prompt, max_tokens, seed, effort, out):
    msgs = [{'role': 'system', 'content': SYSTEM}, {'role': 'user', 'content': prompt}]
    body = dict(messages=msgs, add_generation_prompt=True, chat_template_kwargs={'enable_thinking': True})
    if effort:
        body['reasoning_effort'] = effort
    ids = json.load(post(base, '/tokenize', body))['tokens']
    start = time.monotonic()
    first, n, usage, finish = None, 0, {}, None
    with post(base, '/v1/completions', dict(model='x', prompt=ids, max_tokens=max_tokens, temperature=0.8, seed=seed,
                                             stream=True, return_token_ids=True,
                                             stream_options={'include_usage': True})) as resp:
        for raw in resp:
            line = raw.decode().strip()
            if not line.startswith('data:') or line == 'data: [DONE]':
                continue
            chunk = json.loads(line[5:])
            for ch in chunk.get('choices', []):
                if ch.get('token_ids'):
                    first = first or time.monotonic()
                    n += len(ch['token_ids'])
                finish = ch.get('finish_reason') or finish
            usage = chunk.get('usage') or usage
    end = time.monotonic()
    out.append(dict(tokens=usage.get('completion_tokens', n), ttft=(first or end) - start,
                    decode_tps=(n - 1) / (end - first) if first and end > first and n > 1 else None, finish=finish))


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--base', default='http://127.0.0.1:18083')
    p.add_argument('--concurrency', type=int, default=24)
    p.add_argument('--requests', type=int, default=48)
    p.add_argument('--max-tokens', type=int, default=4096)
    p.add_argument('--effort', default=None)
    p.add_argument('--seed', type=int, default=1)
    p.add_argument('--label', default='')
    a = p.parse_args()
    rng = random.Random(a.seed)
    jobs = [(puzzle(rng), 1000 * a.seed + i) for i in range(a.requests)]
    results, lock = [], threading.Lock()
    queue = list(jobs)

    def worker():
        while True:
            with lock:
                if not queue:
                    return
                prompt, seed = queue.pop(0)
            one(a.base, prompt, a.max_tokens, seed, a.effort, results)

    acc_before = metric(a.base, 'spec_accept_length')
    start = time.monotonic()
    threads = [threading.Thread(target=worker) for _ in range(a.concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.monotonic() - start
    total = sum(r['tokens'] for r in results)
    dec = [r['decode_tps'] for r in results if r['decode_tps']]
    summary = dict(label=a.label, concurrency=a.concurrency, requests=len(results), max_tokens=a.max_tokens,
                   effort=a.effort, wall_s=round(wall, 2), completion_tokens=total,
                   aggregate_tps=round(total / wall, 1),
                   per_request_decode_tps_median=round(statistics.median(dec), 1) if dec else None,
                   ttft_median_s=round(statistics.median(r['ttft'] for r in results), 2),
                   length_finishes=sum(r['finish'] == 'length' for r in results),
                   spec_accept_length_gauge_after=metric(a.base, 'spec_accept_length'),
                   spec_accept_length_gauge_before=acc_before)
    print(json.dumps(summary))


if __name__ == '__main__':
    main()
