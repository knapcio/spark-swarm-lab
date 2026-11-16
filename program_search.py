#!/usr/bin/env python3
"""Optional generic coloring-program experiment. Plan-only without --run."""
import argparse
import ast
from concurrent.futures import ThreadPoolExecutor
import csv
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import threading
import time

from csp_tasks import canonical_json, graph_digest, load_tasks, verify_assignment
from harness import Budget, Client, Events
from reference_worker import verify_gate
from run_benchmark import drain, read_trace, server_cost

HERE = Path(__file__).resolve().parent
ARMS = ("sequential16", "independent4")
REVIEW_ARM = "review_elites4"
PLAN_FILE = "PROGRAM_REVIEW_ELITES_SELECTION.json"
REVIEW_SYSTEM = "Review the supplied Python coloring solver. Return plaintext criticism and repair suggestions only. Do not use tools."
SEEDS = (1, 2, 3, 4)
POST_REQUIRED_STAGES = frozenset(("coding-confirmation-v1", "csp-classical-v1",
    "csp-core_off16-development-s1", "csp-core_off16-evaluation-s1",
    "csp-core_off16-evaluation-s2", "csp-core_off16-evaluation-s3"))
POST_OPTIONAL_STAGES = frozenset(("csp-extended_off64-evaluation-s1", "csp-extended_off64-evaluation-s2",
    "csp-extended_off64-evaluation-s3", "csp-thinking_on16-evaluation-s1"))
LIMITS = dict(max_model_calls=16, per_call_max_tokens=2048, max_completion_tokens=32768,
              request_timeout_seconds=210, graph_timeout_seconds=10, memory_limit_mib=256,
              cpu_limit_per_container=1, episode_deadline_seconds=None)
SYSTEM = "Write a complete standalone Python program defining solve(n,k,edges). Return only Python source. Do not use tools."
FILES = ("program_search.py", "test_program_search.py", "csp_program_grader.py",
         "test_csp_program_grader.py", "harness.py", "csp_tasks.py", "independent_code_grader.py",
         "reference_worker.py", "run_benchmark.py", "runtime.json", "datasets/csp-v1/tasks.json",
         "test_program_review_elites.py", "PROGRAM_REVIEW_ELITES.md", PLAN_FILE)


def sha(path): return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def text_sha(text): return hashlib.sha256(text.encode()).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def require(ok, message):
    if not ok: raise RuntimeError(message)


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)


def atomic_json(path, value):
    temporary = Path(str(path) + ".tmp")
    write_new(temporary, value)
    temporary.replace(path)


def source_hashes():
    return {name: sha(HERE / name) for name in FILES}


def source_identity():
    revision = subprocess.check_output(["git", "-C", str(HERE), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(["git", "-C", str(HERE), "status", "--porcelain", "--untracked-files=no"], text=True).strip()
    tracked = set(subprocess.check_output(["git", "-C", str(HERE), "ls-files"], text=True).splitlines())
    return dict(revision=revision, tracked_clean=not dirty, source_files_tracked=set(FILES) <= tracked,
                sha256=source_hashes())


def parse_program(content, stage=None):
    """Syntax inspection only. Generated Python is NEVER executed on this host."""
    if stage and stage.startswith("review-"):
        raw = content if isinstance(content, str) else None
        return dict(raw=raw, critique=(raw or "")[:8192], truncated=len(raw or "") > 8192)
    raw = content if isinstance(content, str) else None
    code = raw.strip() if raw is not None else ""
    if code.startswith("```python\n") and code.endswith("```"):
        code = code[len("```python\n"):-3].strip()
    elif code.startswith("```\n") and code.endswith("```"):
        code = code[4:-3].strip()
    error = None
    try:
        if len(code.encode()) > 65536: raise ValueError("source exceeds64KiB")
        tree = ast.parse(code)
        functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "solve"]
        if len(functions) != 1: raise ValueError("exactly one top-level solve function required")
        arguments = functions[0].args
        if (len(arguments.posonlyargs + arguments.args) != 3 or arguments.vararg or arguments.kwarg
                or arguments.kwonlyargs):
            raise ValueError("solve must accept exactly three positional parameters")
    except (SyntaxError, ValueError, RecursionError, MemoryError) as exc:
        error = type(exc).__name__ + ": " + str(exc)[:300]
    return dict(raw=raw, code=code, parse_error=error)


def author_prompt(development, previous=None):
    prompt = ("Implement solve(n,k,edges) for colorable undirected graphs with n<=64 and k in {3,4}. "
              "Vertices are0..n-1, colors0..k-1. Return exactly {'assignment':[one integer color per vertex]}; "
              "edge endpoints must differ. Do not mutate input edges. Python standard library only; no network, "
              "files or tools. Each graph runs in a fresh process with10seconds and256MiB. "
              "Write a generic solver, not a lookup table. Return complete Python source, not a patch.\n"
              "The only development graphs available to you are:\n" + canonical_json(development))
    if previous is not None:
        prompt += "\nYour own immediately previous source:\n" + previous["code"]
        prompt += "\nIts development-only constraint feedback:\n" + canonical_json(previous["feedback"])
        prompt += "\nRepair or improve your generic solver. No evaluation results are available."
    return prompt


def infrastructure(report):
    return (not isinstance(report, dict) or report.get("provenance") == "infrastructure"
            or str(report.get("failure_kind", "")).endswith("_infrastructure")
            or report.get("cleanup_ok") is not True)


def compact_feedback(task, report):
    proof = report.get("proof") or {}
    return dict(task_id=task["id"], solved=report.get("solved") is True,
                conflicts=proof.get("conflicts"), valid_assignment=proof.get("valid_schema") is True,
                conflicting_edge_indices=proof.get("violating_edges", [])[:16],
                status=report.get("status"), failure_kind=report.get("failure_kind"),
                error=str(report.get("error") or proof.get("error") or "")[:300])


def penalty(task, report):
    if report.get("solved") is True: return 0
    proof = report.get("proof") or {}
    if (proof.get("valid_schema") is True and type(proof.get("conflicts")) is int
            and report.get("input_unchanged") is True and report.get("status") == "failed"):
        return proof["conflicts"]
    return len(task["edges"]) + 1


def run_episode(development, evaluation, arm, seed, host, client, events, directory,
                evaluator, stop=None):
    """Sixteen calls including every development success; one frozen final program."""
    require(arm in (*ARMS, REVIEW_ARM) and len(development) == 4 and len(evaluation) == 12, "Expected fixed arm and4/12 split")
    stop = stop or threading.Event()
    directory = Path(directory)
    candidates, evaluation_rows = [], []
    start = time.monotonic()
    result = dict(arm=arm, seed=seed, host=host, status="running", complete=False,
                  selected_sha256=None, evaluation_solved=None, evaluation_graphs=12)
    grade_calls, grade_wall, parent_cpu = 0, 0.0, 0.0
    selected = None

    def grade(code, task, phase, candidate_index):
        nonlocal grade_calls, grade_wall, parent_cpu
        require(not stop.is_set(), "global infrastructure stop")
        identity = dict(phase=phase, candidate_index=candidate_index, task_id=task["id"],
                        code_sha256=text_sha(code), graph_sha256=graph_digest(task),
                        input_sha256=text_sha(canonical_json([task["vertex_count"], task["color_count"], task["edges"]])),
                        host=host, timeout_seconds=10)
        events.emit("program_grade_start", **identity)
        began = time.monotonic()
        report = evaluator(code, task, host, timeout=10)
        elapsed = time.monotonic() - began
        grade_calls += 1; grade_wall += elapsed
        if isinstance(report, dict) and type(report.get("parent_cpu_seconds")) in (int, float):
            parent_cpu += report["parent_cpu_seconds"]
        events.emit("program_grade_end", **identity, report=report, controller_wall_seconds=elapsed)
        if infrastructure(report):
            stop.set()
            raise RuntimeError("program grading infrastructure/cleanup failure")
        require(report.get("grading_authority") == "outer_parent" and report.get("oracle_sent_to_child") is False,
                "unqualified program grader authority")
        require(report.get("graph_sha256") == graph_digest(task), "grader checked a different graph")
        if report.get("proof") is not None:
            require("candidate_output" in report and verify_assignment(task, report["candidate_output"]) == report["proof"],
                    "returned graph proof cannot be independently replayed")
        if report.get("solved") is True:
            require(report.get("status") == "passed" and report.get("input_unchanged") is True
                    and report.get("proof", {}).get("solved") is True, "false-positive program grade")
        return report

    def propose(index, agent, previous):
        value = client.call(agent, "program-" + str(index), author_prompt(development, previous),
                            candidate_index=index, chain=agent, phase="development",
                            previous_candidate_index=previous["index"] if previous else None)
        parsed = value if isinstance(value, dict) and set(value) == {"raw", "code", "parse_error"} else parse_program(None)
        return dict(index=index, chain=agent, parent_index=previous["index"] if previous else None, **parsed)

    def score_rows(rows):
        for row in rows:
            with (directory / f"candidate-{row['index']:02d}.raw.txt").open("x") as stream:
                stream.write(row["raw"] or "")
            with (directory / f"candidate-{row['index']:02d}.py").open("x") as stream:
                stream.write(row["code"])
            row["code_sha256"] = text_sha(row["code"])
            events.emit("program_candidate", **row)
        if getattr(client, "infra_failures", 0) or getattr(client, "budget_failures", 0):
            stop.set(); raise RuntimeError("model transport or budget dispatch failure")
        for row in rows:
            feedback, reports = [], []
            for task in development:
                if row["parse_error"]:
                    report = dict(status="error", solved=False, proof=None, failure_kind="candidate_parse",
                                  error=row["parse_error"], grading_performed=False)
                    events.emit("program_grade_skipped", candidate_index=row["index"], task_id=task["id"],
                                phase="development", reason="candidate_parse", code_sha256=row["code_sha256"])
                else:
                    report = grade(row["code"], task, "development", row["index"])
                feedback.append(compact_feedback(task, report)); reports.append(report)
            row.update(feedback=feedback, development_solved=sum(r.get("solved") is True for r in reports),
                       development_penalty=sum(penalty(t, r) for t, r in zip(development, reports)))
            candidates.append(row)
            events.emit("development_candidate_scored", candidate_index=row["index"], chain=row["chain"],
                        solved=row["development_solved"], penalty=row["development_penalty"], feedback=feedback)
    rank = lambda row: (-row["development_solved"], row["development_penalty"], row["index"])

    def review_round(population, generation):
        ordered = sorted(population, key=rank)
        pairs = list(zip(ordered[2:], ordered[:2]))
        events.emit("review_population", generation=generation,
                    candidate_indices=[r["index"] for r in ordered], ranking="development only")
        def review(pair):
            reviewer, target = pair
            review_id = f"r{generation}-c{reviewer['index']}-t{target['index']}"
            prompt = ("Critique the target generic solver using only the following four development graphs. "
                      "Your own source is candidate context, not an autonomous persistent identity. "
                      "Neither your criticism nor suggestions are verified facts. No evaluation data are available.\n"
                      + canonical_json(development) + "\nYour context source:\n" + reviewer["code"]
                      + "\nIts development feedback:\n" + canonical_json(reviewer["feedback"])
                      + "\nTarget source:\n" + target["code"] + "\nTarget development feedback:\n"
                      + canonical_json(target["feedback"]) + "\nReturn plaintext critique only; do not return replacement code.")
            value = client.call(reviewer["index"], "review-" + review_id, prompt, phase="development_review",
                                review_id=review_id, reviewer_candidate_index=reviewer["index"],
                                target_candidate_index=target["index"], candidate_index=None)
            value = value if isinstance(value, dict) and "critique" in value else dict(raw=None, critique="", truncated=False)
            events.emit("program_review", review_id=review_id, generation=generation,
                        reviewer_candidate_index=reviewer["index"], target_candidate_index=target["index"],
                        reviewer_sha256=reviewer["code_sha256"], target_sha256=target["code_sha256"],
                        critique_verified=False, **value)
            write_new(directory / ("review-" + review_id + ".json"), value)
            return target, review_id, value["critique"]
        original_system = getattr(client, "system_prompt", SYSTEM)
        client.system_prompt = REVIEW_SYSTEM
        try:
            with ThreadPoolExecutor(max_workers=2) as pool: reviews = list(pool.map(review, pairs))
        finally: client.system_prompt = original_system
        require(not getattr(client, "infra_failures", 0) and not getattr(client, "budget_failures", 0),
                "model review transport or budget dispatch failure")
        def repair(job):
            index, (target, review_id, critique) = job
            prompt = author_prompt(development, target) + "\nUnverified peer critique (may be wrong):\n" + critique
            value = client.call(target["chain"], "program-" + str(index), prompt, candidate_index=index,
                                chain=target["chain"], phase="development", previous_candidate_index=target["index"],
                                review_id=review_id, repair_target_index=target["index"])
            parsed = value if isinstance(value, dict) and set(value) == {"raw", "code", "parse_error"} else parse_program(None)
            return dict(index=index, chain=target["chain"], parent_index=target["index"], review_id=review_id, **parsed)
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows = list(pool.map(repair, enumerate(reviews, start=4 + (generation-1)*2)))
        score_rows(rows)
        # The old four plus two repairs compete; no reviewer is globally declared wrong.
        retained = sorted(population + rows, key=rank)[:4]
        events.emit("review_population_selected", generation=generation,
                    retained_indices=[r["index"] for r in retained],
                    not_retained_indices=[r["index"] for r in population + rows if r not in retained],
                    reason="development_rank_not_mathematical_incorrectness")
        return retained

    try:
        if arm == REVIEW_ARM:
            with ThreadPoolExecutor(max_workers=4) as pool:
                population = list(pool.map(lambda i: propose(i, i, None), range(4)))
            score_rows(population)
            for generation in range(1, 4):
                require(not stop.is_set(), "global infrastructure stop")
                population = review_round(population, generation)
            require(len(candidates) == 10 and not stop.is_set(), "incomplete10-candidate/6-review episode")
        else:
            width = 1 if arm == "sequential16" else 4
            previous = [None] * width
            for generation in range(16 // width):
                require(not stop.is_set(), "global infrastructure stop")
                jobs = [(generation * width + chain, chain, previous[chain]) for chain in range(width)]
                with ThreadPoolExecutor(max_workers=width) as pool:
                    rows = list(pool.map(lambda job: propose(*job), jobs))
                score_rows(rows)
                for row in rows: previous[row["chain"]] = row
            require(len(candidates) == 16 and not stop.is_set(), "incomplete training episode")
        selected = min(candidates, key=rank)
        selected_path = directory / "selected.py"
        with selected_path.open("x") as stream: stream.write(selected["code"])
        selection = dict(arm=arm, seed=seed, candidate_index=selected["index"], code_sha256=selected["code_sha256"],
                         parse_error=selected["parse_error"], development_solved=selected["development_solved"],
                         development_penalty=selected["development_penalty"], selected_utc=now(), evaluation_seen=False,
                         model_calls_at_selection=client.budget.snapshot()["calls"],
                         selection_rule="development solved descending, conflict/error penalty ascending, earliest index")
        require(selection["model_calls_at_selection"] == 16, "fixed16-call training allocation not realized")
        write_new(directory / "selection.json", selection)
        events.emit("program_selected", **selection)
        result.update(selected_sha256=selection["code_sha256"], selected_candidate_index=selected["index"],
                      development_solved=selection["development_solved"])
        # No call to client occurs below this boundary.
        for task in evaluation:
            require(sha(selected_path) == selection["code_sha256"], "selected program changed during evaluation")
            report = grade(selected["code"], task, "evaluation", selected["index"])
            row = dict(task_id=task["id"], graph_sha256=graph_digest(task), selected_sha256=selection["code_sha256"], report=report)
            evaluation_rows.append(row)
            write_new(directory / f"evaluation-{task['id']}.json", row)
            require(client.budget.snapshot()["calls"] == 16, "evaluation made an unexpected model call")
        require(sha(selected_path) == selection["code_sha256"], "selected program changed after evaluation")
        result.update(status="complete", complete=True, selected_sha256=selection["code_sha256"],
                      selected_candidate_index=selected["index"], development_solved=selection["development_solved"],
                      evaluation_solved=sum(r["report"].get("solved") is True for r in evaluation_rows))
    except Exception as exc:
        stop.set()
        result.update(status="requires_review", error=type(exc).__name__ + ": " + str(exc)[:500])
    finally:
        result.update(training_candidates_scored=len(candidates), evaluation_completed=len(evaluation_rows),
                      model_budget=client.budget.snapshot(), grading_calls=grade_calls,
                      grading_wall_seconds=grade_wall, parent_cpu_seconds_overlapping_threads=parent_cpu,
                      remote_solver_cpu_seconds=None, remote_cpu_reason="qualified container transport does not measure remote CPU time",
                      cpu_limit_per_container=1, memory_limit_mib=256, graph_timeout_seconds=10,
                      wall_seconds=time.monotonic() - start)
        events.emit("program_episode_end", **result)
    return result


def load_plan(gate_root, output):
    selection = json.loads((HERE / PLAN_FILE).read_text())
    require(selection["protocol"] == "reusable-coloring-program-review-elites4-v1", "unexpected program protocol")
    require(selection.get("limits") == LIMITS and selection.get("arms") == [REVIEW_ARM]
            and selection.get("seeds") == list(SEEDS), "program allocation differs from fixed implementation")
    require(set(selection["source_sha256"]) == set(FILES) - {PLAN_FILE}, "incomplete program source pin set")
    for name, digest in selection["source_sha256"].items():
        require(sha(HERE / name) == digest, "program source pin changed: " + name)
    dataset = HERE / "datasets/csp-v1/tasks.json"
    development, evaluation = load_tasks(dataset, "development"), load_tasks(dataset, "evaluation")
    require(len(development) == 4 and len(evaluation) == 12, "fixed4/12 corpus required")
    pairs = [dict(seed=seed, host=f"Spark_{seed:02d}", endpoint=f"http://127.0.0.1:{18080+seed}/v1",
                  arms=[REVIEW_ARM]) for seed in SEEDS]
    return dict(protocol=selection["protocol"], selection_sha256=sha(HERE / PLAN_FILE),
                dataset_sha256=sha(dataset), development_tasks=4, evaluation_tasks=12, pairs=pairs,
                output=str(Path(output).resolve()), gate_root=str(Path(gate_root).resolve()),
                planned_selected_programs=4, planned_evaluation_results=48,
                source=source_identity(), runtime=json.loads((HERE / "runtime.json").read_text()),
                limits=selection["limits"], scope=selection["scope"]), development, evaluation


def followup_gate(root):
    throughput = verify_gate(root)
    base = root / ".runtime/post-throughput-overnight-v1"
    state = json.loads((base / "state.json").read_text())
    require(state.get("status") == "complete" and state.get("ledger_sha256") == sha(base / "ledger.json"),
            "post-throughput controller must be completely verified before program search")
    entries = json.loads((base / "ledger.json").read_text())
    expected = POST_REQUIRED_STAGES | POST_OPTIONAL_STAGES
    require(len(entries) == len(expected) and {e.get("name") for e in entries} == expected,
            "post-throughput ledger must contain each expected stage exactly once")
    require(all((e.get("status") == "skipped_time_cutoff" and e["name"] in POST_OPTIONAL_STAGES) or
            (e.get("status") == "complete" and e.get("verified") is True and e.get("returncode") == 0) for e in entries),
            "mandatory post-throughput stages must complete; only optional stages may be time-skipped")
    return dict(throughput=throughput, post_state_sha256=sha(base / "state.json"), post_ledger_sha256=sha(base / "ledger.json"))


def request_usage(records):
    starts = [r for r in records if r.get("type") == "request_start"]
    ends = [r for r in records if r.get("type") == "request_end"]
    complete = len(starts) == len(ends) and all(all(type(r.get("usage", {}).get(k)) is int for k in
                   ("prompt_tokens", "completion_tokens")) for r in ends)
    return dict(calls=len(starts), completed_calls=len(ends), unfinished_calls=len(starts)-len(ends),
                prompt_tokens=sum(r.get("usage", {}).get("prompt_tokens", 0) for r in ends),
                completion_tokens=sum(r.get("usage", {}).get("completion_tokens", 0) for r in ends),
                length_finishes=sum(r.get("finish_reason") == "length" for r in ends),
                response_errors=sum(bool(r.get("error")) for r in ends),
                client_usage_complete=complete, client_totals_are_lower_bounds=not complete)


def qualify_program_grader(evaluator, host, directory):
    """Three authored tiny-graph container smokes after the completed-study gate."""
    task = dict(id="program-grader-authored-triangle", vertex_count=3, color_count=3,
                edges=[[0, 1], [0, 2], [1, 2]])
    fixtures = [
        ("valid", "def solve(n,k,edges): return {'assignment':[0,1,2]}", "passed", None),
        ("wrong", "def solve(n,k,edges): return {'assignment':[0,0,0]}", "failed", "candidate_graph_failure"),
        ("forged_grade", "import os\ndef solve(n,k,edges):\n os.write(3,b'{\"status\":\"passed\",\"passed\":1}')\n os._exit(0)",
         "error", "candidate_protocol")]
    rows = []
    path = Path(directory) / "program-grader-qualification.json"
    for name, code, expected_status, expected_failure in fixtures:
        report = evaluator(code, task, host, timeout=10)
        rows.append(dict(name=name, code=code, code_sha256=text_sha(code), task=task, report=report))
        atomic_json(path, dict(verified=False, host=host, model_calls=0, rows=rows))
        require(not infrastructure(report) and report.get("grading_authority") == "outer_parent"
                and report.get("oracle_sent_to_child") is False, "program grader smoke infrastructure/authority failure")
        require(report.get("status") == expected_status and report.get("failure_kind") == expected_failure
                and report.get("solved") is (name == "valid"), "program grader smoke classification/false-pass failure")
        if name != "forged_grade":
            require(report.get("proof") == verify_assignment(task, report.get("candidate_output")), "program smoke proof replay failed")
    result = dict(verified=True, host=host, model_calls=0, rows=rows, completed_utc=now())
    atomic_json(path, result)
    return result


def run_master(plan, development, evaluation, gate):
    from csp_program_grader import evaluate_program
    directory = Path(plan["output"]); directory.mkdir(parents=True, exist_ok=False)
    rows, lock, stop = [], threading.Lock(), threading.Event()
    began = time.monotonic()
    meta = dict(plan, mode="run", gate=gate, started_utc=now(), complete=False)
    atomic_json(directory / "metadata.json", meta)
    write_new(directory / "development-inputs.json", development)
    write_new(directory / "evaluation-inputs.json", evaluation)
    with ThreadPoolExecutor(max_workers=4) as pool:
        initial = list(pool.map(lambda pair: drain(pair["endpoint"]), plan["pairs"]))
    meta["initial_idle_checks"] = [dict(endpoint=pair["endpoint"], metrics=value[0], idle=value[1], drain_seconds=value[2])
                                   for pair, value in zip(plan["pairs"], initial)]
    if any(value[1] is not True for value in initial):
        meta.update(status="requires_review", error="all four endpoints must be idle", complete=False, verified=False)
        atomic_json(directory / "metadata.json", meta)
        return 1
    atomic_json(directory / "metadata.json", meta)
    try:
        meta["grader_qualification"] = qualify_program_grader(evaluate_program, "Spark_04", directory)
        require(source_hashes() == plan["source"]["sha256"], "source changed during grader qualification")
    except Exception as exc:
        meta.update(status="requires_review", error=type(exc).__name__ + ": " + str(exc)[:500], complete=False, verified=False)
        atomic_json(directory / "metadata.json", meta)
        return 1
    atomic_json(directory / "metadata.json", meta)

    def pair_work(pair):
        for arm in pair["arms"]:
            if stop.is_set(): return
            require(source_hashes() == plan["source"]["sha256"], "source changed before episode")
            before, idle, _ = drain(pair["endpoint"])
            require(idle is True, "endpoint must be idle before episode")
            episode = directory / f"seed-{pair['seed']}-{arm}"; episode.mkdir()
            events = Events(episode / "events.jsonl", arm)
            budget = Budget(16, 32768)
            client = Client([pair["endpoint"]], plan["runtime"]["served_model_name"], 4, 2048, 210, budget, events, pair["seed"], False)
            client.system_prompt, client.response_parser = SYSTEM, parse_program
            try:
                row = run_episode(development, evaluation, arm, pair["seed"], pair["host"], client, events, episode, evaluate_program, stop)
            finally:
                events.close()
            after, final_idle, drain_seconds = drain(pair["endpoint"])
            records, malformed = read_trace(episode / "events.jsonl")
            usage = request_usage(records)
            row.update(usage, endpoint=pair["endpoint"], server_idle_after=final_idle, drain_seconds=drain_seconds,
                       server_metrics_before=before, server_metrics_after=after, malformed_lines=malformed,
                       **server_cost(before, after, final_idle, usage))
            if final_idle is not True or malformed or source_hashes() != plan["source"]["sha256"]:
                row.update(complete=False, status="requires_review", error="idle, trace or source integrity failure")
                stop.set()
            write_new(episode / "result.json", row)
            with lock:
                rows.append(row)
                atomic_json(directory / "results.json", rows)

    def pair_worker(pair):
        try:
            pair_work(pair)
        except Exception:
            stop.set()
            raise

    faults = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(pair_worker, pair) for pair in plan["pairs"]]
        for future in futures:
            try: future.result()
            except Exception as exc:
                stop.set(); faults.append(type(exc).__name__ + ": " + str(exc)[:500])
    final = source_identity()
    verified = (len(rows) == sum(len(pair["arms"]) for pair in plan["pairs"]) and all(r["complete"] for r in rows) and not faults
                and final == plan["source"] and not stop.is_set())
    meta.update(completed_utc=now(), wall_seconds=time.monotonic()-began, source_after=final,
                recorded_episodes=len(rows), completed_programs=sum(r["complete"] for r in rows),
                complete=verified, verified=verified, faults=faults)
    atomic_json(directory / "results.json", rows)
    atomic_json(directory / "metadata.json", meta)
    fields = ["seed", "arm", "status", "complete", "selected_sha256", "development_solved", "evaluation_solved",
              "evaluation_completed", "calls", "prompt_tokens", "completion_tokens", "client_usage_complete",
              "server_prompt_tokens", "server_completion_tokens", "server_cost_known", "grading_calls",
              "grading_wall_seconds", "remote_solver_cpu_seconds", "wall_seconds"]
    with (directory / "results.csv").open("x", newline="") as stream:
        writer = csv.DictWriter(stream, fields); writer.writeheader()
        writer.writerows({k: "null" if row.get(k) is None else row[k] for k in fields} for row in rows)
    return 0 if verified else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gate-root", type=Path, default=HERE)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--run", action="store_true")
    args = parser.parse_args(argv)
    root = args.gate_root.resolve()
    output = (args.output or root / "runs/program-review-elites4-v1").resolve()
    plan, development, evaluation = load_plan(root, output)
    if not args.run:
        print(json.dumps(dict(plan, mode="plan"), indent=2)); return 0
    require(not output.exists() and output.is_relative_to(root / "runs"), "new output under gate-root/runs required")
    require(plan["source"]["tracked_clean"] and plan["source"]["source_files_tracked"], "clean committed source snapshot required")
    return run_master(plan, development, evaluation, followup_gate(root))


if __name__ == "__main__": raise SystemExit(main())
