import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from csp_tasks import verify_assignment
import run_csp_search as runner


def fixture(case, max_calls=16, deadline=False, unknown_cost=False):
    records = [dict(type="run_start", task=case["task"])]
    payload = {"assignment": [0] * case["task"]["vertex_count"]}
    proof = verify_assignment(case["task"], payload)
    for index in range(max_calls):
        context = dict(request_id=f"r{index}", agent_id=0, stage=f"candidate-{index}", puzzle_id=case["task_id"])
        records.append(dict(type="request_start", **context))
        if deadline and index == max_calls - 1:
            continue
        records.append(dict(type="request_end", **context, response=json.dumps(payload), error=None,
                            usage={"prompt_tokens": 10, "completion_tokens": 5}, finish_reason="stop"))
        records.append(dict(type="candidate", id=f"candidate-{index}", payload=payload,
                            verification=proof, verified_elapsed_seconds=index + .1))
        records.append(dict(type="reward", node_id=f"candidate-{index}", solved=proof["solved"]))
    if deadline:
        records.append(dict(type="controller_stop", deadline=True, returncode=-15))
    else:
        records.append(dict(type="run_end", solved=False, calls=max_calls, max_calls=max_calls,
                            candidate_count=max_calls))
    row = {k: case[k] for k in ("task_id", "split", "arm", "seed", "endpoint", "events")}
    row.update(solved=False, observed_solved=False, calls=max_calls, completed_calls=max_calls - int(deadline),
               unfinished_calls=int(deadline), status="deadline" if deadline else "complete",
               controller_error=None, malformed_lines=0, infrastructure_failures=None if deadline else 0,
               returncode=-15 if deadline else 0, deadline=deadline, controller_stop=deadline,
               server_idle_after=True, server_cost_known=not unknown_cost,
               server_prompt_tokens=None if unknown_cost else max_calls * 10,
               server_completion_tokens=None if unknown_cost else max_calls * 5,
               missing_prompt_usage=0, missing_completion_usage=0, budget_denials=0,
               prompt_tokens=(max_calls - int(deadline)) * 10,
               completion_tokens=(max_calls - int(deadline)) * 5, wall_seconds=1.0)
    return row, records


class RunCSPTests(unittest.TestCase):
    def plan(self, directory, profile="core_off16", split="development", seed=1):
        return runner.build_plan(profile, split, seed, Path(directory) / "runs" / "cohort", Path(directory))

    def identity(self):
        return dict(revision="test-revision", tracked_clean=True, source_files_tracked=True,
                    sha256={"test": "unchanged"})

    def test_balanced_profiles_and_budget_arguments(self):
        for profile, arms, calls, cap, deadline in (("core_off16", 7, 16, 512, 180),
                ("extended_off64", 8, 64, 512, 600), ("thinking_on16", 8, 16, 4096, 900)):
            plan = self.plan("/tmp/unused-csp-plan", profile, "evaluation")
            self.assertEqual(len(plan["cases"]), 12 * arms)
            self.assertEqual(plan["recipe"]["deadline_seconds"], deadline)
            self.assertEqual(plan["recipe"]["request_timeout_seconds"], deadline + 30)
            mapping = {}
            for case in plan["cases"]:
                mapping.setdefault(case["task_id"], set()).add(case["arm"])
                command = case["command"]
                self.assertEqual(command[command.index("--max-calls") + 1], str(calls))
                self.assertEqual(command[command.index("--max-tokens") + 1], str(cap))
                self.assertEqual(command[command.index("--timeout") + 1], str(deadline + 30))
                self.assertEqual("--thinking" in command, profile == "thinking_on16")
                self.assertFalse(case["stop_on_solution"])
                self.assertTrue(case["server_metrics"])
            self.assertEqual(len(mapping), 12)
            self.assertTrue(all(len(values) == arms for values in mapping.values()))

    def test_rotation_is_reproducible_and_keeps_task_endpoint_owned(self):
        first = self.plan("/tmp/unused-csp-plan", split="evaluation", seed=1)
        again = self.plan("/tmp/unused-csp-plan", split="evaluation", seed=1)
        second = self.plan("/tmp/unused-csp-plan", split="evaluation", seed=2)
        self.assertEqual(first["cases"], again["cases"])
        self.assertNotEqual([c["task_id"] for c in first["cases"]], [c["task_id"] for c in second["cases"]])
        for plan in (first, second):
            for task_id in {c["task_id"] for c in plan["cases"]}:
                self.assertEqual(len({c["endpoint"] for c in plan["cases"] if c["task_id"] == task_id}), 1)

    def test_preregistered_split_seed_limits(self):
        for profile, split, seed in (("extended_off64", "development", 1),
                ("thinking_on16", "evaluation", 2), ("core_off16", "development", 2),
                ("core_off16", "evaluation", 4)):
            with self.assertRaises(ValueError):
                self.plan("/tmp/unused-csp-plan", profile, split, seed)

    def test_plan_only_never_calls_gate_metrics_or_executor_and_writes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(runner, "verify_gate") as gate, patch.object(runner, "drain") as drain, \
                    patch.object(runner, "execute") as execute, contextlib.redirect_stdout(io.StringIO()) as output:
                rc = runner.main(["--profile", "core_off16", "--split", "development", "--seed", "1",
                                  "--gate-root", directory])
            self.assertEqual(rc, 0)
            self.assertEqual(json.loads(output.getvalue())["mode"], "plan")
            gate.assert_not_called(); drain.assert_not_called(); execute.assert_not_called()
            self.assertFalse((Path(directory) / "runs").exists())

    def test_valid_deadline_preserves_unknown_usage_and_cost(self):
        case = self.plan("/tmp/unused-csp-plan")["cases"][0]
        row, records = fixture(case, deadline=True, unknown_cost=True)
        result = runner.assess_attempt(case, row, records, 16)
        self.assertTrue(result["case_valid"])
        self.assertFalse(result["client_usage_complete"])
        self.assertIsNone(row["infrastructure_failures"])
        self.assertIsNone(row["server_completion_tokens"])
        broken = copy.deepcopy(records)
        broken[-1]["returncode"] = 1
        self.assertFalse(runner.assess_attempt(case, row, broken, 16)["case_valid"])

    def test_proof_transport_request_and_idle_faults_are_rejected(self):
        case = self.plan("/tmp/unused-csp-plan")["cases"][0]
        row, records = fixture(case)
        self.assertTrue(runner.assess_attempt(case, row, records, 16)["case_valid"])
        proof_forgery = copy.deepcopy(records)
        next(r for r in proof_forgery if r["type"] == "candidate")["verification"]["solved"] = True
        self.assertEqual(runner.assess_attempt(case, row, proof_forgery, 16)["halt_reason"], "candidate_verification_replay_mismatch")
        transport = copy.deepcopy(records)
        next(r for r in transport if r["type"] == "request_end").update(error="ConnectionResetError", response=None)
        self.assertEqual(runner.assess_attempt(case, row, transport, 16)["halt_reason"], "observed_or_ambiguous_transport_failure")
        duplicate = copy.deepcopy(records)
        requests = [r for r in duplicate if r["type"] == "request_start"]
        requests[1]["request_id"] = requests[0]["request_id"]
        self.assertEqual(runner.assess_attempt(case, row, duplicate, 16)["halt_reason"], "request_accounting_mismatch")
        self.assertEqual(runner.assess_attempt(case, dict(row, server_idle_after=None), records, 16)["halt_reason"], "endpoint_not_confirmed_idle")
        self.assertEqual(runner.assess_attempt(case, dict(row, solved=True), records, 16)["halt_reason"], "summary_success_without_exact_proof")

    def test_exact_derived_proof_is_accepted_but_unbacked_reward_is_not(self):
        case = self.plan("/tmp/unused-csp-plan")["cases"][0]
        case["task"] = dict(id=case["task_id"], vertex_count=2, color_count=2, edges=[[0, 1]])
        row, records = fixture(case)
        proof = dict(type="derived_candidate", id="derived-0", payload={"assignment": [0, 1]},
                     verification=verify_assignment(case["task"], {"assignment": [0, 1]}), verified_elapsed_seconds=2.0)
        records[-1:-1] = [proof, dict(type="reward", node_id="derived-0", solved=True)]
        row["solved"] = records[-1]["solved"] = True
        result = runner.assess_attempt(case, row, records, 16)
        self.assertTrue(result["case_valid"])
        self.assertEqual(result["derived_count"], 1)
        self.assertEqual(result["first_candidate_verified_seconds"], 2.0)
        records.remove(proof)
        self.assertEqual(runner.assess_attempt(case, row, records, 16)["halt_reason"], "reward_without_preceding_exact_proof")

    def mocked_run(self, plan, executor, drain_result=None, hashes=None):
        identity = self.identity()
        with patch.object(runner, "source_hashes", side_effect=hashes or (lambda: identity["sha256"])), \
             patch.object(runner, "source_identity", return_value=identity), \
             patch.object(runner, "server_metrics", return_value={"running": 0, "waiting": 0}), \
             patch.object(runner, "drain", return_value=drain_result or ({"running": 0, "waiting": 0}, True, 0.0)), \
             patch.object(runner, "execute", side_effect=executor):
            return runner.run_cohort(plan, identity, {"verified": "mock-gate"})

    def test_complete_cohort_is_atomic_and_endpoint_serial_with_null_costs(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(directory)
            active, lock = set(), threading.Lock()
            def executor(case, deadline):
                self.assertEqual(deadline, 180)
                with lock:
                    self.assertNotIn(case["endpoint"], active)
                    active.add(case["endpoint"])
                row, records = fixture(case, unknown_cost=True)
                Path(case["events"]).write_text("".join(json.dumps(r) + "\n" for r in records))
                time.sleep(.001)
                with lock: active.remove(case["endpoint"])
                return row
            self.assertEqual(self.mocked_run(plan, executor), 0)
            output = Path(plan["output"])
            metadata = json.loads((output / "metadata.json").read_text())
            summary = json.loads((output / "summary.json").read_text())
            self.assertTrue(metadata["verified"])
            self.assertEqual(metadata["completed_cases"], 28)
            self.assertTrue(all(r["server_completion_tokens"] is None for r in summary))
            self.assertIn("null", (output / "summary.csv").read_text())
            self.assertEqual(list(output.glob("*.tmp")), [])
            with self.assertRaises(FileExistsError): self.mocked_run(plan, executor)

    def test_initial_idle_gate_and_source_change_prevent_dispatch(self):
        for fault in ("idle", "source"):
            with tempfile.TemporaryDirectory() as directory:
                plan = self.plan(directory)
                calls = []
                def forbidden(*args): calls.append(args); raise AssertionError("must not dispatch")
                kwargs = {"drain_result": ({"running": 1, "waiting": 0}, False, 0.0)} if fault == "idle" else {"hashes": lambda: {"test": "changed"}}
                self.assertEqual(self.mocked_run(plan, forbidden, **kwargs), 1)
                self.assertEqual(calls, [])
                metadata = json.loads((Path(plan["output"]) / "metadata.json").read_text())
                self.assertTrue(metadata["incomplete"])
                self.assertFalse(metadata["verified"])

    def test_request_margin_never_extends_controller_deadline(self):
        for profile, deadline in (("core_off16", 180), ("extended_off64", 600), ("thinking_on16", 900)):
            with self.subTest(profile=profile), tempfile.TemporaryDirectory() as directory:
                plan = self.plan(directory, profile, "evaluation")
                plan["cases"] = plan["cases"][:1]
                plan["planned_cases"] = 1
                observed = []
                def executor(case, controller_deadline):
                    observed.append(controller_deadline)
                    self.assertEqual(case["command"][case["command"].index("--timeout") + 1], str(deadline + 30))
                    row, records = fixture(case, max_calls=plan["recipe"]["max_calls"])
                    Path(case["events"]).write_text("".join(json.dumps(r) + "\n" for r in records))
                    return row
                self.assertEqual(self.mocked_run(plan, executor), 0)
                self.assertEqual(observed, [deadline])

    def test_fault_stops_following_cases_but_retains_raw_and_invalid_row(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = self.plan(directory)
            # A single owned slot makes post-fault dispatch deterministic in this fixture.
            plan["cases"] = [dict(c, slot=0) for c in plan["cases"][:2]]
            seen = []
            def executor(case, deadline):
                seen.append(case["events"])
                row, records = fixture(case)
                row["controller_error"] = "authored fixture failure"
                Path(case["events"]).write_text("".join(json.dumps(r) + "\n" for r in records))
                return row
            self.assertEqual(self.mocked_run(plan, executor), 1)
            self.assertEqual(len(seen), 1)
            summary = json.loads((Path(plan["output"]) / "summary.json").read_text())
            self.assertEqual(len(summary), 1)
            self.assertFalse(summary[0]["case_valid"])
            self.assertTrue(Path(seen[0]).exists())

    def test_run_calls_original_gate_root_and_refuses_existing_output(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--profile", "core_off16", "--split", "development", "--seed", "1", "--gate-root", directory, "--run"]
            with patch.object(runner, "source_identity", return_value=self.identity()), \
                    patch.object(runner, "verify_gate", return_value={"mock": True}) as gate, \
                    patch.object(runner, "run_cohort", return_value=0) as run:
                self.assertEqual(runner.main(args), 0)
                gate.assert_called_once_with(Path(directory).resolve())
                self.assertEqual(run.call_args.args[0]["gate_root"], str(Path(directory).resolve()))
                output = Path(run.call_args.args[0]["output"])
                output.mkdir(parents=True)
                with self.assertRaises(FileExistsError): runner.main(args)
                self.assertEqual(gate.call_count, 1)

    def test_real_worker_event_schema_passes_controller_audit_with_local_transport_stub(self):
        from csp_search import ARMS, run_search
        from harness import Budget, Client, Events
        from run_benchmark import metrics
        with tempfile.TemporaryDirectory() as directory:
            template = self.plan(directory)["cases"][0]
            for arm in ARMS:
                case = dict(template, arm=arm, events=str(Path(directory) / (arm + ".jsonl")))
                events = Events(Path(case["events"]), arm)
                budget = Budget(16, 8192)
                client = Client(["http://unused.invalid/v1"], "fixture", 4, 512, 1, budget, events, 1)
                def transport(request, timeout):
                    body = json.loads(request.data)
                    review = "one key critique" in body["messages"][-1]["content"]
                    payload = {"critique": "Check the conflicting edge."} if review else {
                        "assignment": [0] * case["task"]["vertex_count"]}
                    return io.BytesIO(json.dumps({"choices": [{"message": {"content": json.dumps(payload)},
                        "finish_reason": "stop"}], "usage": {"prompt_tokens": 10, "completion_tokens": 5}}).encode())
                try:
                    events.emit("run_start", task=case["task"])
                    with patch("harness.urllib.request.urlopen", side_effect=transport):
                        result = run_search(case["task"], arm, client, events)
                    events.emit("run_end", status="complete", **result, **budget.snapshot(),
                                infrastructure_failures=client.infra_failures)
                finally:
                    events.close()
                records, malformed = runner.read_trace(Path(case["events"]))
                row = dict(metrics(records), returncode=0, controller_error=None, malformed_lines=malformed,
                           server_idle_after=True, controller_stop=False)
                with self.subTest(arm=arm):
                    self.assertTrue(runner.assess_attempt(case, row, records, 16)["case_valid"])


if __name__ == "__main__":
    unittest.main()
