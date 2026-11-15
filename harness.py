#!/usr/bin/env python3
"""Small, auditable Countdown swarm experiment; Python standard library only."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import random
import threading
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone


class InvalidMove(ValueError):
    pass


def canonical(state):
    return [str(Fraction(x)) for x in state]


def apply_action(state, action, allow_fractions=False):
    """Consume exactly two indexed values. No evaluation of model-written code."""
    if not isinstance(action, dict) or set(action) != {"i", "j", "op"}:
        raise InvalidMove("action requires exactly i, j, op")
    i, j, op = action["i"], action["j"], action["op"]
    if type(i) is not int or type(j) is not int or i == j:
        raise InvalidMove("i and j must be distinct integer indices")
    if not (0 <= i < len(state) and 0 <= j < len(state)):
        raise InvalidMove("index out of range")
    if op not in ("+", "-", "*", "/"):
        raise InvalidMove("unsupported operator")
    a, b = Fraction(state[i]), Fraction(state[j])
    if op == "/" and b == 0:
        raise InvalidMove("division by zero")
    value = {"+": lambda: a + b, "-": lambda: a - b,
             "*": lambda: a * b, "/": lambda: a / b}[op]()
    if value <= 0:
        raise InvalidMove("intermediate results must be positive")
    if not allow_fractions and value.denominator != 1:
        raise InvalidMove("intermediate results must be integers")
    return tuple(Fraction(x) for k, x in enumerate(state) if k not in (i, j)) + (value,)


def solved(state, target):
    return Fraction(target) in state


def parse_json_response(content):
    if not isinstance(content, str):
        raise ValueError("response content must be a string")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines[-1].strip() != "```":
            raise ValueError("unterminated JSON fence")
        text = "\n".join(lines[1:-1])
    result = json.loads(text)
    if not isinstance(result, dict):
        raise ValueError("response must be one JSON object")
    return result


class Events:
    def __init__(self, path, method, run_id=None):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.file = self.path.open("x", encoding="utf-8")
        self.lock = threading.Lock()
        self.run_id = run_id or uuid.uuid4().hex[:12]
        self.method = method
        self.counter = 0

    def emit(self, kind, **fields):
        with self.lock:
            self.counter += 1
            event = dict(event_id=self.counter,
                         timestamp=datetime.now(timezone.utc).isoformat(),
                         run_id=self.run_id, method=self.method, type=kind)
            event.update(fields)
            self.file.write(json.dumps(event, ensure_ascii=False) + "\n")
            self.file.flush()
        return event

    def close(self):
        self.file.close()


class Budget:
    """Reserve completion capacity before dispatch, then settle reported usage.

    max_tokens counts completion tokens, not prompt tokens. Missing usage conservatively
    charges the full reservation. A server overrunning its requested cap is logged and
    stops subsequent reservations; an in-flight response cannot be undone.
    """
    def __init__(self, max_calls, max_tokens):
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.calls = self.tokens = self.reserved = 0
        self.lock = threading.Lock()

    def reserve(self, requested):
        with self.lock:
            if self.calls >= self.max_calls or self.tokens + self.reserved + requested > self.max_tokens:
                return False
            self.calls += 1
            self.reserved += requested
            return True

    def settle(self, requested, reported=None):
        with self.lock:
            self.reserved -= requested
            self.tokens += requested if reported is None else reported

    def snapshot(self):
        with self.lock:
            return dict(calls=self.calls, completion_tokens_charged=self.tokens,
                        completion_tokens_reserved=self.reserved,
                        max_calls=self.max_calls, max_completion_tokens=self.max_tokens)


class Client:
    def __init__(self, endpoints, model, concurrency, max_tokens, timeout, budget, events, seed, thinking=False):
        self.endpoints = endpoints
        self.model = model
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.thinking = thinking
        self.budget, self.events, self.seed = budget, events, seed
        self.limits = [threading.BoundedSemaphore(concurrency) for _ in endpoints]
        self.failure_lock = threading.Lock()
        self.infra_failures = self.budget_failures = 0

    def call(self, agent_id, stage, prompt, **context):
        endpoint_index = agent_id % len(self.endpoints)
        endpoint = self.endpoints[endpoint_index].rstrip("/")
        url = endpoint if endpoint.endswith("/chat/completions") else endpoint + "/chat/completions"
        request_id = uuid.uuid4().hex[:12]
        # Wait outside the budget so queued requests do not hold token reservations.
        with self.limits[endpoint_index]:
            if not self.budget.reserve(self.max_tokens):
                with self.failure_lock:
                    self.budget_failures += 1
                self.events.emit("budget_exhausted", agent_id=agent_id, stage=stage, **context)
                return None
            start = time.monotonic()
            self.events.emit("request_start", request_id=request_id, agent_id=agent_id,
                             endpoint_index=endpoint_index, stage=stage, **context)
            usage, error, content = {}, None, None
            reasoning, finish_reason, response_received = None, None, False
            try:
                material = f"{self.seed}:{agent_id}:{stage}:{prompt}"
                request_seed = int.from_bytes(hashlib.sha256(material.encode()).digest()[:4], "big")
                body = dict(model=self.model, messages=[
                    {"role": "system", "content": getattr(self, "system_prompt", "Solve the precise arithmetic task. Return only the requested JSON object. Do not explain or use tools.")},
                    {"role": "user", "content": prompt}], max_tokens=self.max_tokens,
                    temperature=0.8, seed=request_seed, stream=False,
                    chat_template_kwargs={"enable_thinking": self.thinking})
                request = urllib.request.Request(url, data=json.dumps(body).encode(),
                                                 headers={"Content-Type": "application/json"})
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    data = json.load(response)
                raw_usage = data.get("usage") or {}
                for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = raw_usage.get(name)
                    if type(value) is int and value >= 0:
                        usage[name] = value
                choice = data["choices"][0]
                message = choice["message"]
                content = message.get("content")
                finish_reason = choice.get("finish_reason")
                reasoning = message.get("reasoning_content", message.get("reasoning"))
                response_received = True
                result = parse_json_response(content)
            except Exception as exc:
                # No request headers, credentials or full HTTP bodies are recorded.
                error = f"{type(exc).__name__}: {str(exc)[:300]}"
                if not response_received:
                    with self.failure_lock:
                        self.infra_failures += 1
                result = None
            reported = usage.get("completion_tokens")
            self.budget.settle(self.max_tokens, reported)
            usage["estimated"] = reported is None
            self.events.emit("request_end", request_id=request_id, agent_id=agent_id,
                             endpoint_index=endpoint_index, stage=stage,
                             latency_ms=round((time.monotonic() - start) * 1000, 2),
                             usage=usage, completion_tokens_charged=self.max_tokens if reported is None else reported,
                             error=error, response=content, reasoning=reasoning,
                             finish_reason=finish_reason, **context)
            return result


class Experiment:
    def __init__(self, args, client, events, reputation=None):
        self.args, self.client, self.events = args, client, events
        self.reputation = reputation or {}
        self.pool = ThreadPoolExecutor(max_workers=args.agents)

    def node(self, state, parent_id, depth, puzzle_id, agent_id=None):
        node_id = uuid.uuid4().hex[:12]
        self.events.emit("node", node_id=node_id, parent_id=parent_id,
                         state=canonical(state), depth=depth, puzzle_id=puzzle_id, agent_id=agent_id)
        return node_id

    def proposal(self, agent_id, state, node_id, depth, puzzle_id):
        rule = "positive rational" if self.args.allow_fractions else "positive integer"
        prompt = (f"Target {self.args.target}. Current indexed numbers: "
                  f"{dict(enumerate(canonical(state)))}. Combine two different indices with +,-,*,/. "
                  f"All intermediate results must be {rule}. Reach the target using any subset of numbers. "
                  'Return {"i":0,"j":1,"op":"+"} with your chosen indices/operator.')
        action = self.client.call(agent_id, "propose", prompt, node_id=node_id, puzzle_id=puzzle_id)
        proposal_id = hashlib.sha256(json.dumps([
            self.args.seed, puzzle_id, depth, agent_id, canonical(state)
        ]).encode()).hexdigest()[:12]
        fields = dict(agent_id=agent_id, node_id=node_id, parent_id=node_id,
                      proposal_id=proposal_id, action=action, puzzle_id=puzzle_id, depth=depth)
        try:
            child = apply_action(state, action, self.args.allow_fractions)
        except (ValueError, TypeError) as exc:
            self.events.emit("proposal", legal=False, error=str(exc), **fields)
            return None
        child_id = self.node(child, node_id, depth + 1, puzzle_id, agent_id)
        self.events.emit("proposal", legal=True, child_node_id=child_id,
                         child_state=canonical(child), **fields)
        return dict(candidate_id=proposal_id, node_id=child_id, state=child, action=action,
                    agent_id=agent_id)

    def weight(self, agent_id):
        row = self.reputation.get(str(agent_id), {})
        return (row.get("successes", 0) + 1) / (row.get("games", 0) + 2)

    def vote(self, agent_id, state, candidates, node_id, puzzle_id, weighted):
        display = [dict(candidate_id=c["candidate_id"], action=c["action"],
                        resulting_numbers=canonical(c["state"])) for c in candidates]
        # All proposals are complete before this vote stage starts. Ordering is
        # independently shuffled per voter to reduce shared first-choice bias.
        random.Random(f"{self.args.seed}:{agent_id}:{canonical(state)}").shuffle(display)
        prompt = (f"Target {self.args.target}. Current numbers {canonical(state)}. "
                  "Choose the next move offering the best chance to reach the target. "
                  f"Candidates: {json.dumps(display)}. Return only "
                  '{"candidate_id":"the chosen candidate_id"}.')
        result = self.client.call(agent_id, "vote", prompt, node_id=node_id, puzzle_id=puzzle_id)
        candidate_id = result.get("candidate_id") if result else None
        valid = any(c["candidate_id"] == candidate_id for c in candidates)
        weight = self.weight(agent_id) if weighted else 1.0
        self.events.emit("vote", node_id=node_id, puzzle_id=puzzle_id, agent_id=agent_id,
                         candidate_id=candidate_id, valid=valid, weight=weight)
        return (candidate_id, weight) if valid else None

    def independent_agent(self, agent_id, initial, root_id, puzzle_id):
        state, node_id = initial, root_id
        for depth in range(self.args.rounds):
            if solved(state, self.args.target) or len(state) < 2:
                break
            candidate = self.proposal(agent_id, state, node_id, depth, puzzle_id)
            if candidate is None:
                break
            self.events.emit("chosen", node_id=candidate["node_id"], parent_id=node_id,
                             candidate_id=candidate["candidate_id"], agent_id=agent_id, puzzle_id=puzzle_id)
            state, node_id = candidate["state"], candidate["node_id"]
        success = solved(state, self.args.target)
        distance = min(abs(Fraction(self.args.target) - x) for x in state)
        self.events.emit("reward", node_id=node_id, puzzle_id=puzzle_id, agent_id=agent_id,
                         solved=success, reward=int(success), distance=str(distance))
        return dict(agent_id=agent_id, solved=success, node_id=node_id, distance=str(distance))

    def run(self, initial, puzzle_id, method):
        if method in ("ensemble", "cascade"):
            from ensemble_solver import run_ensemble, run_cascade
            return (run_ensemble if method == "ensemble" else run_cascade)(self, initial, puzzle_id)
        if method == "direct":
            from direct_solver import run_direct
            return run_direct(self, initial, puzzle_id)
        if method in ("independent_rounds", "shared"):
            from shared_search import run_rounds
            return run_rounds(self, initial, puzzle_id, shared=method == "shared")
        root = self.node(initial, None, 0, puzzle_id)
        if method in ("independent", "calibrate"):
            futures = [self.pool.submit(self.independent_agent, a, initial, root, puzzle_id)
                       for a in range(self.args.agents)]
            outcomes = [f.result() for f in futures]
            return dict(solved=any(o["solved"] for o in outcomes), outcomes=outcomes)
        state, node_id = initial, root
        for depth in range(self.args.rounds):
            if solved(state, self.args.target) or len(state) < 2:
                break
            futures = [self.pool.submit(self.proposal, a, state, node_id, depth, puzzle_id)
                       for a in range(self.args.agents)]
            proposals = [f.result() for f in futures]
            candidates, seen = [], set()
            for proposal in proposals:
                if proposal is None:
                    continue
                key = tuple(sorted(proposal["state"]))
                if key in seen:
                    self.events.emit("pruned", node_id=proposal["node_id"], parent_id=node_id,
                                     puzzle_id=puzzle_id, reason="duplicate_state")
                else:
                    seen.add(key)
                    candidates.append(proposal)
            if not candidates:
                self.events.emit("halt", node_id=node_id, puzzle_id=puzzle_id, reason="no_legal_proposals")
                break
            if getattr(self.args, "accept_verified_solution", False):
                winner = next((c for c in candidates if solved(c["state"], self.args.target)), None)
                if winner is not None:
                    self.events.emit("chosen", node_id=winner["node_id"], parent_id=node_id,
                                     puzzle_id=puzzle_id, candidate_id=winner["candidate_id"],
                                     reason="exact_target_verified")
                    for candidate in candidates:
                        if candidate is not winner:
                            self.events.emit("pruned", node_id=candidate["node_id"], parent_id=node_id,
                                             puzzle_id=puzzle_id, reason="verified_solution_found")
                    state, node_id = winner["state"], winner["node_id"]
                    break
            futures = [self.pool.submit(self.vote, a, state, candidates, node_id, puzzle_id,
                                       method == "weighted") for a in range(self.args.agents)]
            votes = [f.result() for f in futures]
            tally = {c["candidate_id"]: 0.0 for c in candidates}
            for vote in votes:
                if vote is not None:
                    tally[vote[0]] += vote[1]
            if not any(tally.values()):
                self.events.emit("halt", node_id=node_id, puzzle_id=puzzle_id, reason="no_valid_votes")
                break
            winner = max(candidates, key=lambda c: tally[c["candidate_id"]])
            self.events.emit("chosen", node_id=winner["node_id"], parent_id=node_id,
                             puzzle_id=puzzle_id, candidate_id=winner["candidate_id"], tally=tally)
            for candidate in candidates:
                if candidate is not winner:
                    self.events.emit("pruned", node_id=candidate["node_id"], parent_id=node_id,
                                     puzzle_id=puzzle_id, reason="vote_loser")
            state, node_id = winner["state"], winner["node_id"]
        success = solved(state, self.args.target)
        self.events.emit("reward", node_id=node_id, puzzle_id=puzzle_id, agent_id=None,
                         solved=success, reward=int(success),
                         distance=str(min(abs(Fraction(self.args.target) - x) for x in state)))
        return dict(solved=success, final_state=canonical(state), node_id=node_id)


def parse_puzzle(text):
    numbers, target = text.split(":")
    state = tuple(Fraction(int(n)) for n in numbers.split(","))
    if not 2 <= len(state) <= 6 or any(n <= 0 or n > 1000000 for n in state):
        raise ValueError("puzzle requires 2–6 positive integers <= 1000000")
    return state, int(target)


def load_reputation(path, model, agents, puzzle_fingerprint, seed=None, allow_fractions=None, thinking=None):
    data = json.loads(Path(path).read_text())
    if data.get("model") != model or data.get("agents") != agents:
        raise ValueError("reputation model and agent count must match this run")
    if seed is not None and data.get("seed") != seed:
        raise ValueError("reputation seed must match stable agent identities")
    if allow_fractions is not None and data.get("allow_fractions") != allow_fractions:
        raise ValueError("reputation arithmetic rules must match")
    if thinking is not None and data.get("thinking") != thinking:
        raise ValueError("reputation thinking mode must match")
    if puzzle_fingerprint in data.get("puzzle_fingerprints", []):
        raise ValueError("evaluation puzzle overlaps calibration puzzles")
    rows = data.get("scores")
    if not isinstance(rows, dict) or set(rows) != {str(i) for i in range(agents)}:
        raise ValueError("reputation must contain every agent")
    for row in rows.values():
        if (not isinstance(row, dict) or type(row.get("games")) is not int or
                type(row.get("successes")) is not int or row["games"] < 1 or
                not 0 <= row["successes"] <= row["games"]):
            raise ValueError("invalid objective calibration scores")
    return rows


def fingerprint(state, target):
    return hashlib.sha256(json.dumps([sorted(canonical(state)), target]).encode()).hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--method", choices=["direct", "ensemble", "cascade", "independent", "independent_rounds", "shared",
                                           "democracy", "weighted", "calibrate"], required=True)
    parser.add_argument("--endpoint", action="append", required=True, help="Repeat OpenAI base URLs ending /v1")
    parser.add_argument("--model", required=True)
    parser.add_argument("--puzzle", default="25,50,75,100,3,6:952")
    parser.add_argument("--calibration-puzzles", help="Semicolon-separated numbers:target; required for calibrate")
    parser.add_argument("--reputation", help="Calibration JSON input (weighted) or new output (calibrate)")
    parser.add_argument("--agents", type=int, default=100)
    parser.add_argument("--per-endpoint-concurrency", type=int, default=8)
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--max-tokens", type=int, default=192)
    parser.add_argument("--max-calls", type=int, default=1000)
    parser.add_argument("--max-completion-tokens", type=int, default=192000)
    parser.add_argument("--timeout", type=float, default=90)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--allow-fractions", action="store_true")
    parser.add_argument("--thinking", action="store_true", help="Enable model reasoning; default off, prompt unchanged")
    parser.add_argument("--accept-verified-solution", action="store_true",
                        help="Accept an already-proposed exact target before voting; default off")
    parser.add_argument("--events", required=True, help="New JSONL file; refuses overwrite")
    args = parser.parse_args(argv)
    if args.method == "direct" and args.agents != 1:
        parser.error("direct is the single-call baseline; use --agents 1")
    if any(x <= 0 for x in (args.agents, args.per_endpoint_concurrency, args.rounds,
                            args.max_tokens, args.max_calls, args.max_completion_tokens, args.timeout)):
        parser.error("counts, limits and timeout must be positive")
    if args.agents > 1000 or args.rounds > 5:
        parser.error("prototype limits: <=1000 agents and <=5 rounds")
    try:
        initial, args.target = parse_puzzle(args.puzzle)
        evaluation_fingerprint = fingerprint(initial, args.target)
        reputation = None
        if args.method == "weighted":
            if not args.reputation:
                parser.error("weighted requires --reputation from an earlier calibration run")
            reputation = load_reputation(args.reputation, args.model, args.agents, evaluation_fingerprint,
                                         args.seed, args.allow_fractions, args.thinking)
        if args.method == "calibrate":
            if not args.calibration_puzzles or not args.reputation:
                parser.error("calibrate requires --calibration-puzzles and --reputation output")
            if Path(args.reputation).exists():
                parser.error("reputation output already exists")
            puzzles = [parse_puzzle(x) for x in args.calibration_puzzles.split(";")]
            if len({fingerprint(s, t) for s, t in puzzles}) != len(puzzles):
                parser.error("calibration puzzles must be distinct")
        else:
            puzzles = [(initial, args.target)]
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    events = Events(args.events, args.method)
    budget = Budget(args.max_calls, args.max_completion_tokens)
    client = Client(args.endpoint, args.model, args.per_endpoint_concurrency,
                    args.max_tokens, args.timeout, budget, events, args.seed, args.thinking)
    experiment = Experiment(args, client, events, reputation)
    scores = {str(i): dict(games=0, successes=0) for i in range(args.agents)}
    events.emit("run_start", config={k: v for k, v in vars(args).items() if k != "endpoint"},
                endpoint_count=len(args.endpoint), budget=budget.snapshot(),
                limits="Completion budget only; full reservation charged when usage missing. Methods have different call counts.")
    if reputation is not None:
        for agent_id in range(args.agents):
            events.emit("reputation", agent_id=agent_id, **reputation[str(agent_id)],
                        weight=experiment.weight(agent_id), source="prior_exact_games")
    try:
        results = []
        for index, (state, target) in enumerate(puzzles):
            args.target = target
            puzzle_id = f"p{index}-{fingerprint(state, target)[:10]}"
            events.emit("puzzle_start", puzzle_id=puzzle_id, target=target, state=canonical(state))
            result = experiment.run(state, puzzle_id, args.method)
            results.append(result)
            events.emit("puzzle_end", puzzle_id=puzzle_id, **result)
            if args.method == "calibrate":
                for outcome in result["outcomes"]:
                    row = scores[str(outcome["agent_id"])]
                    row["games"] += 1
                    row["successes"] += int(outcome["solved"])
        if args.method == "calibrate":
            if client.infra_failures or client.budget_failures:
                raise RuntimeError("calibration incomplete: infrastructure or budget failure; reputation not written")
            artifact = dict(schema_version=1, model=args.model, agents=args.agents, seed=args.seed,
                            allow_fractions=args.allow_fractions, thinking=args.thinking,
                            source_run_id=events.run_id, reward="exact_target_reached_binary",
                            puzzle_fingerprints=[fingerprint(s, t) for s, t in puzzles], scores=scores)
            with Path(args.reputation).open("x") as output:
                json.dump(artifact, output, indent=2)
        summary = dict(run_id=events.run_id, solved=sum(r["solved"] for r in results),
                       puzzles=len(results), budget=budget.snapshot(), events=str(events.path))
        summary["infrastructure_failures"] = client.infra_failures
        summary["budget_denials"] = client.budget_failures
        status = "budget_limited" if client.budget_failures else ("complete_with_errors" if client.infra_failures else "complete")
        summary["status"] = status
        events.emit("run_end", **summary)
        print(json.dumps(summary))
        return 0
    except BaseException as exc:
        experiment.pool.shutdown(wait=True, cancel_futures=True)
        events.emit("run_end", status="failed", error=f"{type(exc).__name__}: {exc}", budget=budget.snapshot())
        raise
    finally:
        experiment.pool.shutdown(wait=True, cancel_futures=True)
        events.close()


if __name__ == "__main__":
    raise SystemExit(main())
