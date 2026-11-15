"""Bounded serving probe, separate from an agent-method comparison."""
import argparse
import concurrent.futures
import json
import time
import urllib.request
from pathlib import Path


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--endpoints", nargs="+", required=True)
    p.add_argument("--per-node", type=int, default=25)
    p.add_argument("--output", type=Path, required=True)
    args = p.parse_args()
    if not 1 <= args.per_node <= 32:
        p.error("per-node must be 1..32")

    def request(task):
        node, agent = task
        body = {
            "model": "nemotron-lightning",
            "messages": [{"role": "user", "content":
                f'Return only JSON with exactly these values: {{"agent": {agent}, "answer": 42}}'}],
            "max_tokens": 64, "temperature": 0,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        start = time.monotonic()
        try:
            req = urllib.request.Request(args.endpoints[node].rstrip("/") + "/chat/completions",
                data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=180) as response:
                data = json.load(response)
            choice = data["choices"][0]
            content = choice["message"].get("content") or ""
            clean = content.strip()
            if clean.startswith("```"):
                clean = clean.split("\n", 1)[1].rsplit("```", 1)[0].strip()
            parsed = json.loads(clean)
            ok = parsed == {"agent": agent, "answer": 42} and choice.get("finish_reason") != "length"
            return {"node": node + 1, "agent": agent, "ok": ok, "content": content,
                "finish_reason": choice.get("finish_reason"), "usage": data.get("usage", {}),
                "latency_s": round(time.monotonic() - start, 3)}
        except Exception as exc:
            return {"node": node + 1, "agent": agent, "ok": False, "error": str(exc),
                "latency_s": round(time.monotonic() - start, 3)}

    tasks = [(node, node * args.per_node + slot) for node in range(len(args.endpoints))
             for slot in range(args.per_node)]
    started = time.monotonic()
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(tasks)) as pool:
        results = list(pool.map(request, tasks))
    elapsed = time.monotonic() - started
    tokens = sum(r.get("usage", {}).get("completion_tokens", 0) for r in results)
    report = {"kind": "serving_json_probe", "model": "nemotron-lightning",
        "note": "Short JSON requests; not agent task throughput or a sustained decode benchmark.",
        "endpoints": args.endpoints, "requests": len(tasks), "client_concurrency": len(tasks),
        "per_node": args.per_node, "correct": sum(r["ok"] for r in results),
        "wall_s": round(elapsed, 3), "completion_tokens": tokens,
        "output_tokens_per_wall_s": round(tokens / elapsed, 2), "results": results}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: v for k, v in report.items() if k != "results"}, indent=2))
    return 0 if all(r["ok"] for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
