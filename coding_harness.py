#!/usr/bin/env python3
"""Feedback-only code search and one frozen holdout grade.

Democracy reviews/votes after the complete proposal batch, including candidates
passing partial feedback tests. Other policies freeze at their first feedback pass.
"""
import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed, wait
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit

import harness as h
from sandbox_code import evaluate_code


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def context(task):
    return ("Implement this pure Python 3 function using only the standard library. "
            "Do not mutate any input, do external I/O, or rely on external packages. "
            "Return exact JSON-compatible values: arrays must be Python lists; bool and int "
            "are distinct; floats are outside this corpus; preserve every ordering required by the specification.\n"
            + json.dumps({key: task[key] for key in ("id", "function_name", "spec", "examples")}, ensure_ascii=False))


def feedback(report):
    return {key: report[key] for key in ("status", "passed", "total", "error", "first_failure") if key in report}


def parse_python_response(content, stage):
    """Source-only proposals; strip an optional fence, never unescape source text."""
    if stage != "code_propose":
        return h.parse_json_response(content)
    if not isinstance(content, str):
        raise ValueError("Python response must be text")
    source = content.strip()
    if source.startswith("```"):
        lines = source.splitlines(keepends=True)
        if len(lines) < 3 or lines[0].strip().lower() not in ("```", "```python") or lines[-1].strip() != "```":
            raise ValueError("Expected a complete Python code fence")
        source = "".join(lines[1:-1]).strip()
    if not source:
        raise ValueError("Python response is empty")
    return {"code": source}


def infrastructure(report):
    if report.get("cleanup_ok") is False:
        return True
    if report.get("provenance") == "infrastructure" or str(report.get("failure_kind", "")).endswith("_infrastructure"):
        return True
    if report.get("provenance") == "candidate" or str(report.get("failure_kind", "")).startswith("candidate_"):
        return False
    return ("exit_code" in report
            or str(report.get("error", "")).startswith("Invalid runner protocol")
            or report.get("status") not in ("passed", "failed", "error", "timeout"))


def best(rows):
    unique = {}
    for row in sorted(rows, key=lambda r: (-r["report"].get("passed", 0), r["candidate_id"])):
        if not row["infrastructure_error"]:
            unique.setdefault(row["candidate_id"], row)
    return list(unique.values())[:4]


def run_experiment(args, task, private, client, events, evaluator=evaluate_code, wait_for_pending=True):
    """Serial main-thread grades; all policies share the phase/code-SHA cache.

    Infrastructure errors and timeouts are never cached. Synthesis memory is a
    separate policy feature; holdout results never select or repair candidates.
    """
    feedback_tests, holdout_tests = private["feedback_tests"], private["holdout_tests"]
    if not feedback_tests or not holdout_tests:
        raise ValueError("both feedback and holdout cases are required")
    inputs = lambda cases: {digest([case["args"], case.get("kwargs", {})]) for case in cases}
    if inputs(feedback_tests) & inputs(holdout_tests):
        raise ValueError("feedback and holdout inputs must be disjoint")
    if inputs(task["examples"]) & (inputs(feedback_tests) | inputs(holdout_tests)):
        raise ValueError("private cases must exclude public example inputs")
    pool, futures = ThreadPoolExecutor(max_workers=args.agents), []
    candidates, tracks, facts = [], {}, {}
    base, selected, infra_errors, democracy_basis = None, None, 0, None
    grade_cache, grade_counter = {}, 0  # Common exact-code cache, separate from synthesis memory.
    root = "code-root-" + task["id"]
    events.emit("node", node_id=root, parent_id=None, state=[task["function_name"]], depth=0, puzzle_id=task["id"])

    def propose(agent, round_id, own_base, shared_facts):
        instruction = ('\nReturn complete Python function source only. Do not wrap it in JSON or include explanations.'
                       if getattr(args, "code_format", "json") == "python" else
                       '\nReturn exactly a JSON object with one key "code", containing the complete implementation.')
        prompt = context(task) + instruction
        if own_base:
            prompt += "\nPrevious implementation:\n" + own_base["code"] + "\nFeedback (not holdout): " + json.dumps(feedback(own_base["report"]), ensure_ascii=False)
        if shared_facts:
            prompt += "\nVerified feedback-test observations from prior rounds (not global impossibility claims): " + json.dumps(shared_facts, ensure_ascii=False)
        parent = own_base["node_id"] if own_base else root
        events.emit("code_prompt", agent_id=agent, round=round_id, puzzle_id=task["id"], prompt=prompt)
        return client.call(agent, "code_propose", prompt, puzzle_id=task["id"], node_id=parent, round=round_id)

    def grade(row, tests, phase):
        nonlocal grade_counter
        key = (phase, row["candidate_id"])
        if key in grade_cache:
            report, source = grade_cache[key]
            events.emit("evaluation_reused", phase=phase, candidate_id=row["candidate_id"], node_id=row["node_id"], puzzle_id=task["id"], source_evaluation_id=source, report=report)
            return copy.deepcopy(report)
        grade_counter += 1
        evaluation_id = f"{task['id']}:{phase}:{grade_counter}"
        events.emit("evaluation_start", evaluation_id=evaluation_id, phase=phase, candidate_id=row["candidate_id"], node_id=row["node_id"], puzzle_id=task["id"])
        try:
            report = evaluator(row["code"], task["function_name"], tests, args.host)
        except Exception as exc:
            report = dict(status="error", error=type(exc).__name__ + ": " + str(exc)[:1000], cleanup_ok=False)
        events.emit("evaluation_end", evaluation_id=evaluation_id, phase=phase, candidate_id=row["candidate_id"], node_id=row["node_id"], puzzle_id=task["id"], report=report, infrastructure_error=infrastructure(report))
        if not infrastructure(report) and (report.get("status") in ("passed", "failed") or report.get("status") == "error" and str(report.get("error", "")).startswith(("SyntaxError:", "IndentationError:", "TabError:"))):
            grade_cache[key] = (copy.deepcopy(report), evaluation_id)
        return report

    try:
        rounds = 1 if args.method == "direct" else args.rounds
        for round_id in range(rounds):
            shared_facts = list(facts.values())[:4] if args.method in ("shared", "democracy") else []
            if args.method in ("shared", "democracy"):
                events.emit("memory_snapshot", round=round_id, puzzle_id=task["id"], base_candidate_id=base["candidate_id"] if base else None, facts=shared_facts)
            assignments = list(range(1 if args.method in ("direct", "iterative") else args.agents))
            jobs = {}
            for agent in assignments:
                own = tracks.get(agent) if args.method in ("iterative", "independent") else base
                future = pool.submit(propose, agent, round_id, own, shared_facts)
                jobs[future] = (agent, own)
                futures.append(future)
            round_rows = []
            for future in as_completed(jobs):
                agent, parent = jobs[future]
                try:
                    reply = future.result()
                except Exception as exc:
                    infra_errors += 1
                    events.emit("code_error", agent_id=agent, round=round_id, error_kind="client_infrastructure", error=str(exc)[:1000])
                    continue
                if not isinstance(reply, dict) or set(reply) != {"code"} or not isinstance(reply["code"], str) or not 0 < len(reply["code"]) <= 65536:
                    events.emit("code_error", agent_id=agent, round=round_id, error_kind="invalid_model_output")
                    continue
                code = reply["code"]
                candidate_id = hashlib.sha256(code.encode()).hexdigest()
                row = dict(candidate_id=candidate_id, code=code, agent_id=agent, round=round_id,
                           node_id=f"code-{round_id}-{agent}-{candidate_id[:12]}")
                events.emit("node", node_id=row["node_id"], parent_id=parent["node_id"] if parent else root, state=[candidate_id[:12]], depth=round_id + 1, agent_id=agent, puzzle_id=task["id"])
                events.emit("code_candidate", puzzle_id=task["id"], **row)
                row["report"] = grade(row, feedback_tests, "feedback")
                row["infrastructure_error"] = infrastructure(row["report"])
                infra_errors += int(row["infrastructure_error"])
                candidates.append(row)
                round_rows.append(row)
                if args.method != "democracy" and row["report"].get("status") == "passed" and not row["infrastructure_error"]:
                    selected = row
                    break  # Exception to round barriers: feedback pass freezes selection now.
            if selected:
                break
            # as_completed consumed every response; no next-round facts or prompts before this barrier.
            wait(jobs)
            for row in sorted(round_rows, key=lambda r: (r["agent_id"], r["candidate_id"])):
                own = best([r for r in candidates if r["agent_id"] == row["agent_id"]])
                if own:
                    tracks[row["agent_id"]] = own[0]
                failure = row["report"].get("first_failure")
                if failure and not row["infrastructure_error"] and args.method in ("shared", "democracy"):
                    key = digest([failure.get("input"), failure.get("expected")])
                    fact = dict(fact_kind="feedback_test_failure", candidate_id=row["candidate_id"], source_agent_id=row["agent_id"], failure=failure)
                    if key not in facts and len(facts) < 4:
                        facts[key] = fact
                        events.emit("memory_write", puzzle_id=task["id"], round=round_id, fact_id=key, **fact)
            passing = [row for row in candidates if row["report"].get("status") == "passed"]
            shortlist = best(passing if args.method == "democracy" and passing else candidates)
            if not shortlist:
                break
            base = shortlist[0]
            if args.method != "democracy" and round_id == rounds - 1:
                break
            if args.method == "democracy":
                display = [dict(candidate_id=r["candidate_id"], code=r["code"], feedback=feedback(r["report"])) for r in shortlist]
                prompt = context(task) + '\nReview these implementations against the specification and examples. Feedback tests are partial, not a correctness proof. Select the candidate most likely to generalize (or the best repair base if none passes feedback). Return JSON {"candidate_id":"id"}.\nCandidates:\n' + json.dumps(display, ensure_ascii=False)
                for agent in assignments:
                    events.emit("code_vote_prompt", agent_id=agent, round=round_id, puzzle_id=task["id"], prompt=prompt)
                votes = [(agent, pool.submit(client.call, agent, "code_vote", prompt, puzzle_id=task["id"], round=round_id)) for agent in assignments]
                futures.extend(f for _, f in votes)
                wait([f for _, f in votes])
                tally = {r["candidate_id"]: 0 for r in shortlist}
                for agent, future in votes:
                    try:
                        vote = future.result()
                    except Exception:
                        vote, infra_errors = None, infra_errors + 1
                    choice = vote.get("candidate_id") if isinstance(vote, dict) else None
                    valid = choice in tally
                    if valid:
                        tally[choice] += 1
                    events.emit("vote", puzzle_id=task["id"], agent_id=agent, round=round_id, candidate_id=choice, valid=valid, weight=1)
                base = max(shortlist, key=lambda row: tally[row["candidate_id"]])
                democracy_basis = "democracy_review_vote" if any(tally.values()) else "democracy_feedback_rank_fallback_no_valid_votes"
                events.emit("chosen", node_id=base["node_id"], candidate_id=base["candidate_id"], puzzle_id=task["id"], reason=democracy_basis, tally=tally)
                if base["report"].get("status") == "passed":
                    selected = base
                    break
        if selected is None:
            shortlist = best(candidates)
            selected = base if args.method == "democracy" else shortlist[0] if shortlist else None
        basis = "no_valid_candidate" if not selected else democracy_basis if args.method == "democracy" else "first_feedback_pass" if selected["report"].get("status") == "passed" else "best_feedback_score_then_code_hash"
        events.emit("candidate_selected", puzzle_id=task["id"], candidate_id=selected["candidate_id"] if selected else None, selection_basis=basis, holdout_seen=False)
        # The only holdout grade occurs after selection; no later model request or repair.
        holdout = grade(selected, holdout_tests, "holdout") if selected else None
        if holdout:
            infra_errors += int(infrastructure(holdout))
        solved = bool(holdout and holdout.get("status") == "passed" and not infrastructure(holdout))
        result = dict(task_id=task["id"], method=args.method, solved=solved,
                      candidate_id=selected["candidate_id"] if selected else None,
                      selection_basis=basis, feedback=feedback(selected["report"]) if selected else None,
                      holdout=holdout, infrastructure_failures=infra_errors + client.infra_failures,
                      budget_denials=client.budget_failures, budget=client.budget.snapshot(),
                      pending_model_calls=sum(not f.done() for f in futures))
        result["usage_complete"] = result["pending_model_calls"] == 0
        result["pending_tasks_aborted_on_cli_exit"] = 0 if wait_for_pending else result["pending_model_calls"]
        result["completion_tokens_upper_bound_at_selection"] = result["budget"]["completion_tokens_charged"] + result["budget"]["completion_tokens_reserved"]
        events.emit("selection_complete", **result)
        events.emit("reward", puzzle_id=task["id"], node_id=selected["node_id"] if selected else root, solved=solved, reward=int(solved), basis="single_frozen_holdout_grade" if holdout else "no_candidate_selected")
        return result
    finally:
        pool.shutdown(wait=wait_for_pending, cancel_futures=not wait_for_pending)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("tasks", "tests", "task-id", "endpoint", "host", "events"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--method", choices=("direct", "iterative", "independent", "shared", "democracy"), required=True)
    parser.add_argument("--agents", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--max-tokens", type=int, default=1024)
    parser.add_argument("--max-calls", type=int, default=1024)
    parser.add_argument("--maxcompletion", "--max-completion", type=int, default=131072)
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--thinking", choices=("off", "on"), default="off")
    parser.add_argument("--code-format", choices=("json", "python"), default="json")
    args = parser.parse_args(argv)
    if not all(value > 0 for value in (args.agents, args.rounds, args.max_tokens, args.max_calls, args.maxcompletion)) or args.agents > 100:
        parser.error("positive limits required; agents must be at most 100")
    if args.method in ("direct", "iterative") and args.agents != 1:
        parser.error("direct and iterative use exactly one agent")
    url = urlsplit(args.endpoint)
    if url.scheme not in ("http", "https") or url.username or url.password:
        parser.error("endpoint must be HTTP(S) without embedded credentials")
    public_file, private_file = Path(args.tasks), Path(args.tests)
    public, private_data = json.loads(public_file.read_text()), json.loads(private_file.read_text())
    task = next((row for row in public["tasks"] if row["id"] == args.task_id), None)
    if task is None or args.task_id not in private_data["references"]:
        parser.error("task-id is absent from the public/private corpus")
    events = h.Events(args.events, args.method)
    budget = h.Budget(args.max_calls, args.maxcompletion)
    client = h.Client([args.endpoint], "nemotron-lightning", args.agents, args.max_tokens, 180, budget, events, args.seed, thinking=args.thinking == "on")
    client.system_prompt = "Implement or review the specified pure Python function. Return only the requested JSON object. Do not explain or use tools."
    if args.code_format == "python":
        client.system_prompt = "Implement or review the specified pure Python function. Return complete Python source for code proposals and the requested JSON for voting. Do not explain or use tools."
        client.response_parser = parse_python_response
    events.emit("run_start", config=dict(vars(args), model=client.model), task_id=args.task_id, domain="coding",
                public_sha256=hashlib.sha256(public_file.read_bytes()).hexdigest(),
                private_sha256=hashlib.sha256(private_file.read_bytes()).hexdigest(),
                limits="Completion-token budget only; input usage is recorded separately. Holdout grades once after feedback-only selection.")
    try:
        result = run_experiment(args, task, private_data["references"][args.task_id], client, events, wait_for_pending=False)
        result["budget"] = budget.snapshot()
        status = "budget_limited" if client.budget_failures else "complete_with_errors" if result["infrastructure_failures"] else "complete"
        events.emit("run_end", status=status, **result)
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except Exception as exc:
        events.emit("run_end", status="failed", error=type(exc).__name__ + ": " + str(exc)[:1000], budget=budget.snapshot())
        return 1
    finally:
        events.close()


if __name__ == "__main__":
    code = main()
    sys.stdout.flush()
    sys.stderr.flush()
    # Holdout Docker execution has returned. Terminate only this CLI's remaining
    # HTTP threads/sockets instead of Python's ThreadPoolExecutor exit wait.
    os._exit(code)
