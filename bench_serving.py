#!/usr/bin/env python3
"""Finite OpenAI-compatible serving load test; stdout is one JSON report."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import json
import os
import time
import urllib.error
import urllib.request


TASKS = [
    ("json_multiply", "Return only valid JSON with exactly one key, result, whose value is the integer product of 37 and 19. No Markdown.", {"result": 703}),
    ("code_group", "Write a Python function group_by(items, key) returning a dict of lists. Preserve item order within each group, accept a callable key, and do not mutate items. Include three small examples.", None),
    ("logic_order", "Three jobs A, B and C run one at a time. A must precede C; B must immediately follow A. List every valid order and briefly explain why the list is complete.", None),
    ("review_mutation", "Review this Python function for correctness, identify a failing input, then provide a corrected implementation: def remove_even(xs):\n    for x in xs:\n        if x % 2 == 0:\n            xs.remove(x)\n    return xs\nThe corrected function must return a new list and leave its input unchanged.", None),
    ("json_sum", "Return only valid JSON with exactly one key, result, whose value is the integer sum of 128, 47, 305 and 20. No explanation or Markdown.", {"result": 500}),
    ("code_intervals", "Implement a Python function merge_intervals(intervals) for closed integer intervals. Sort the output, merge overlaps, preserve the caller's input, and describe the behavior for an empty list. Include one edge-case example.", None),
    ("review_queue", "A worker reads a task from a queue, writes its result, then acknowledges it. The process may crash between these steps. Explain how duplicate processing can happen and give a minimal idempotent design using a task ID. Keep the explanation concrete.", None),
    ("json_arithmetic", "Return only valid JSON with exactly one key, result, whose value is the integer value of (144 - 36) / 9 + 17. No Markdown or extra keys.", {"result": 29}),
]


def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number


def exact_json_check(content, expected):
    if expected is None:
        return None
    try:
        parsed = json.loads(content)
    except (ValueError, TypeError) as exc:
        return {"passed": False, "expected": expected, "error": "Invalid JSON: " + str(exc)}
    passed = (
        isinstance(parsed, dict)
        and parsed.keys() == expected.keys()
        and type(parsed.get("result")) is int
        and parsed == expected
    )
    return {"passed": passed, "expected": expected, "actual": parsed}


def request_one(args, index, phase, run_id):
    task, prompt, expected = TASKS[index % len(TASKS)]
    marker = f"{run_id}:{phase}:{index:06d}"
    payload = {
        "model": args.model,
        "messages": [
            {"role": "system", "content": "Follow the task precisely. The request marker is metadata; do not include it in your answer."},
            {"role": "user", "content": prompt + "\n\nRequest marker: " + marker},
        ],
        "max_tokens": args.max_tokens,
        "temperature": 0,
        "stream": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    headers = {"Content-Type": "application/json"}
    if os.environ.get("SWARM_API_KEY"):
        headers["Authorization"] = "Bearer " + os.environ["SWARM_API_KEY"]
    request = urllib.request.Request(args.url, data=json.dumps(payload).encode(), headers=headers)
    row = {"index": index, "phase": phase, "task": task, "marker": marker,
           "prompt": prompt, "usage": None, "content": None,
           "finish_reason": None, "error": None, "json_arithmetic_check": None}
    started = time.perf_counter()
    try:
        with urllib.request.urlopen(request, timeout=180) as response:
            row["http_status"] = response.status
            answer = json.load(response)
        row["usage"] = answer.get("usage")
        choice = answer["choices"][0]
        message = choice["message"]
        row["content"] = message.get("content")
        row["reasoning"] = message.get("reasoning", message.get("reasoning_content"))
        row["finish_reason"] = choice.get("finish_reason")
        row["json_arithmetic_check"] = exact_json_check(row["content"], expected)
    except urllib.error.HTTPError as exc:
        row["http_status"] = exc.code
        row["error"] = f"HTTP {exc.code}: " + exc.read(4000).decode("utf-8", errors="replace")
    except Exception as exc:
        row["error"] = type(exc).__name__ + ": " + str(exc)
    row["latency_seconds"] = time.perf_counter() - started
    return row


def summarize(rows, wall_seconds):
    successes = [r for r in rows if r["error"] is None]
    usages = [r["usage"] for r in successes if isinstance(r["usage"], dict)]
    completions = [u["completion_tokens"] for u in usages if type(u.get("completion_tokens")) is int]
    prompts = [u["prompt_tokens"] for u in usages if type(u.get("prompt_tokens")) is int]
    checks = [r["json_arithmetic_check"] for r in successes if r["json_arithmetic_check"] is not None]
    latencies = sorted(r["latency_seconds"] for r in rows)
    finish_reasons = {}
    for row in successes:
        reason = str(row["finish_reason"])
        finish_reasons[reason] = finish_reasons.get(reason, 0) + 1
    def percentile(fraction):
        if not latencies:
            return None
        return latencies[round((len(latencies) - 1) * fraction)]
    return {
        "requests": len(rows), "successful_requests": len(successes),
        "errors": len(rows) - len(successes), "wall_seconds": wall_seconds,
        "completion_tokens": sum(completions), "prompt_tokens": sum(prompts),
        "requests_with_completion_usage": len(completions),
        "requests_missing_completion_usage": len(successes) - len(completions),
        "output_tokens_per_second": sum(completions) / wall_seconds if wall_seconds else None,
        "latency_seconds_p50": percentile(0.50), "latency_seconds_p95": percentile(0.95),
        "finish_reasons": finish_reasons,
        "json_arithmetic_checks": {"checked": len(checks), "passed": sum(c["passed"] for c in checks),
                                   "failed": sum(not c["passed"] for c in checks)},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("endpoint", help="Base URL, /v1 URL, or full /v1/chat/completions URL")
    parser.add_argument("--model", default="nemotron-lightning")
    parser.add_argument("--concurrency", type=positive, default=25)
    parser.add_argument("--requests", type=positive, default=100)
    parser.add_argument("--max-tokens", type=positive, default=256)
    args = parser.parse_args()
    base = args.endpoint.rstrip("/")
    args.url = base if base.endswith("/chat/completions") else base + ("/chat/completions" if base.endswith("/v1") else "/v1/chat/completions")
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    warmup_start = time.perf_counter()
    warmup = [request_one(args, i, "warmup", run_id) for i in range(4)]
    warmup_wall = time.perf_counter() - warmup_start
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        futures = [executor.submit(request_one, args, i, "measured", run_id) for i in range(args.requests)]
        results = [future.result() for future in as_completed(futures)]
    wall = time.perf_counter() - started
    results.sort(key=lambda row: row["index"])
    report = {
        "run_id_utc": run_id, "endpoint": args.url, "model": args.model,
        "configuration": {"concurrency": args.concurrency, "requests": args.requests,
                          "max_tokens": args.max_tokens, "temperature": 0,
                          "enable_thinking": False, "timeout_seconds": 180,
                          "stream": False, "warmup_requests": 4},
        "notes": [
            "Measured wall time excludes warmup; completion-token throughput includes all measured scheduling, HTTP and prefill time.",
            "Usage comes from the server. Missing completion usage is reported and makes output throughput incomplete.",
            "The output cap is deliberate. A length finish is recorded, and is not an automatic code-task failure.",
            "Only three constrained JSON arithmetic task types are graded; no general code or reasoning quality score is computed.",
            "Latency covers each HTTP request; TTFT is not measured. Unique request markers are placed after the task.",
        ],
        "warmup_summary": summarize(warmup, warmup_wall), "warmup_results": warmup,
        "summary": summarize(results, wall), "results": results,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
