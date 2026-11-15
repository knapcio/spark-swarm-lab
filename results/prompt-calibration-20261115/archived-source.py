#!/usr/bin/env python3
"""Bounded four-batch prompt probe. Default dry-run; --run makes exactly <=400 calls."""
import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from fractions import Fraction
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import time
import urllib.error
import urllib.request

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
sys.path.insert(0, str(ROOT / "apps/swarm-lab"))
import harness as h

ENDPOINTS = [f"http://127.0.0.1:{port}/v1" for port in range(18081, 18085)]
OLD_ENDING = 'Return {"i":0,"j":1,"op":"+"} with your chosen indices/operator.'
SCHEMA_ENDING = ('Return only a JSON object with integer indices in fields i and j and a '
                 'single-character operator in field op. The operator must be one of +, -, *, /.')
SYSTEM = 'Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.'
STATE = tuple(map(Fraction, [2, 3, 7, 8]))


class Capture:
    def call(self, agent_id, stage, prompt, **context):
        self.prompt = prompt
        return None
    def emit(self, *args, **kwargs):
        pass


def prompts():
    capture = Capture()
    experiment = h.Experiment(argparse.Namespace(agents=1, seed=1, target=24, allow_fractions=False), capture, capture)
    try:
        experiment.proposal(0, STATE, "capture", 0, "capture")
    finally:
        experiment.pool.shutdown()
    old = capture.prompt
    assert old.endswith(OLD_ENDING), "Current harness prompt changed; review probe first."
    return dict(old=old, schema=old[:-len(OLD_ENDING)] + SCHEMA_ENDING)


def request_seed(agent_id, prompt):
    return int.from_bytes(hashlib.sha256(f"1:{agent_id}:propose:{prompt}".encode()).digest()[:4], "big")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args()
    variants = prompts()
    plan = dict(order=["old", "schema", "schema", "old"], endpoints=ENDPOINTS,
                agents_per_batch=100, per_endpoint_concurrency=25, target=24, state=h.canonical(STATE),
                seed=1, stage="propose", temperature=0.8, max_tokens=192, thinking=False,
                timeout=90, max_calls=400, max_completion_tokens=76800, system=SYSTEM, prompts=variants,
                seed_rule="big-endian integer from first 4 bytes SHA256('1:{agent_id}:propose:{full_prompt}')")
    if not args.run:
        print(json.dumps(plan, indent=2))
        return
    directory = BASE / datetime.now().strftime("run-%Y%m%d-%H%M%S")
    directory.mkdir(exist_ok=False)
    runtime = ROOT / "apps/swarm-lab/runtime.json"
    revision = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True)
    metadata = dict(plan, started_utc=datetime.now(timezone.utc).isoformat(),
                    git_revision=revision.stdout.strip(), runtime=json.loads(runtime.read_text()),
                    source_sha256={p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                   for p in [Path(__file__), ROOT / "apps/swarm-lab/harness.py", runtime]},
                    note="Prompt variant also changes Client's prompt-derived random seed; a same-seed paired RNG experiment is not claimed.")
    (directory / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")
    events = h.Events(directory / "events.jsonl", "prompt_calibration")
    budget = h.Budget(400, 76800)
    client = h.Client(ENDPOINTS, "nemotron-lightning", 25, 192, 90, budget, events, 1, thinking=False)
    original_transport = urllib.request.urlopen
    batch = {}
    def wire_transport(request, timeout):
        body = json.loads(request.data)
        assert request.full_url in {endpoint + "/chat/completions" for endpoint in ENDPOINTS}
        assert body["messages"][0]["content"] == SYSTEM
        body_seed = body["seed"]
        try:
            with original_transport(request, timeout=timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            events.emit("wire_error", batch_id=batch["id"], variant=batch["variant"],
                        endpoint=request.full_url, body=body, status=exc.code,
                        raw_response=exc.read().decode("utf-8", errors="replace"))
            raise
        except Exception as exc:
            events.emit("wire_error", batch_id=batch["id"], variant=batch["variant"],
                        endpoint=request.full_url, body=body, error=f"{type(exc).__name__}: {exc}")
            raise
        events.emit("wire_response", batch_id=batch["id"], variant=batch["variant"],
                    agent_id=batch["seed_agents"][body_seed], endpoint=request.full_url,
                    body=body, status=status, raw_response=raw.decode("utf-8", errors="replace"))
        return io.BytesIO(raw)
    urllib.request.urlopen = wire_transport
    summaries = []
    try:
        with ThreadPoolExecutor(max_workers=100) as pool:
            for batch_id, variant in enumerate(plan["order"], 1):
                prompt = variants[variant]
                batch.update(id=batch_id, variant=variant,
                             seed_agents={request_seed(agent, prompt): agent for agent in range(100)})
                assert len(batch["seed_agents"]) == 100
                events.emit("batch_start", batch_id=batch_id, variant=variant, full_prompt=prompt)
                started = time.monotonic()
                actions = list(pool.map(lambda agent: client.call(agent, "propose", prompt,
                    batch_id=batch_id, variant=variant, puzzle_id="target24", node_id="root"), range(100)))
                wall = time.monotonic() - started
                legal, exact, parseable, errors = 0, 0, 0, []
                operators, legal_operators = Counter(), Counter()
                for agent, action in enumerate(actions):
                    parseable += action is not None
                    operators[str(action.get("op")) if isinstance(action, dict) else "<unparsed>"] += 1
                    try:
                        child = h.apply_action(STATE, action, allow_fractions=False)
                        legal += 1
                        legal_operators[action["op"]] += 1
                        hit = h.solved(child, 24)
                        exact += hit
                        events.emit("evaluation", batch_id=batch_id, variant=variant, agent_id=agent,
                                    action=action, legal=True, exact=hit, child_state=h.canonical(child))
                    except (ValueError, TypeError) as exc:
                        errors.append(dict(agent_id=agent, error=str(exc)))
                        events.emit("evaluation", batch_id=batch_id, variant=variant, agent_id=agent,
                                    action=action, legal=False, exact=False, error=str(exc))
                row = dict(batch_id=batch_id, variant=variant, calls=100, parseable=parseable,
                           legal=legal, exact=exact, op_distribution=dict(operators),
                           legal_op_distribution=dict(legal_operators), wall_seconds=round(wall, 6),
                           evaluation_errors=errors)
                summaries.append(row)
                events.emit("batch_end", **row)
                print(json.dumps(row), flush=True)
    finally:
        urllib.request.urlopen = original_transport
        events.close()
    records = [json.loads(line) for line in events.path.read_text().splitlines()]
    for row in summaries:
        requests = [r for r in records if r["type"] == "request_end" and r.get("batch_id") == row["batch_id"]]
        row.update(prompt_tokens=sum(r["usage"].get("prompt_tokens", 0) for r in requests),
                   completion_tokens=sum(r["usage"].get("completion_tokens", 0) for r in requests),
                   missing_usage=sum(r["usage"].get("estimated", False) for r in requests),
                   request_errors=sum(r.get("error") is not None for r in requests),
                   finish_reasons=dict(Counter(str(r.get("finish_reason")) for r in requests)))
    result = dict(batches=summaries, budget=budget.snapshot(), infrastructure_failures=client.infra_failures,
                  budget_denials=client.budget_failures, directory=str(directory))
    (directory / "summary.json").write_text(json.dumps(result, indent=2) + "\n")
    lines = ["# Prompt calibration: example versus schema", "", "Four sequential batches; one proposal per agent, no voting or search.",
             "", "| Batch | Variant | Legal / 100 | Exact / 100 | Prompt tokens | Completion tokens | Wall s |",
             "|---|---|---:|---:|---:|---:|---:|"]
    for row in summaries:
        lines.append(f"| {row['batch_id']} | {row['variant']} | {row['legal']} | {row['exact']} | {row['prompt_tokens']} | {row['completion_tokens']} | {row['wall_seconds']} |")
    lines += ["", f"Infrastructure failures: {client.infra_failures}; budget denials: {client.budget_failures}.",
              "", "Operator distributions and every response/error are retained in summary.json and events.jsonl.",
              "", "Only the final user-prompt sentence changes. Existing Client hashing derives the request seed from the full prompt, so variant changes also alter sampled RNG seeds. Repeated variants reuse agent seeds, but GPU batching may still differ. These batches concern one easy state, not held-out multi-step task quality. They do not establish a causal example-token bias, a general winning prompt, or agent-method superiority. Longer prompt length is included in actual token costs.",
              "", "Reproduce with `python3 diagnostics/swarm-prototype-20261115/prompt-calibration/probe.py --run`; default invocation prints the plan without API calls. Source hashes, exact prompts/body settings and runtime snapshot are in metadata.json; each wire_response also retains the complete request body and raw HTTP response."]
    (directory / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(directory=str(directory), infrastructure_failures=client.infra_failures,
                          budget=budget.snapshot())), flush=True)


if __name__ == "__main__":
    main()
