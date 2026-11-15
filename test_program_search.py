import contextlib
import io
import json
from pathlib import Path
import re
import tempfile
import threading
import unittest
from unittest.mock import patch

from csp_tasks import graph_digest, verify_assignment
from harness import Budget
import program_search as p


DEV = [dict(id=f"dev_fixture_{i}", vertex_count=3, color_count=3, edges=[[0, 1], [1, 2], [0, 2]]) for i in range(4)]
EVAL = [dict(id=f"eval_secret_{i}", vertex_count=4, color_count=3, edges=[[0, 1], [1, 2], [2, 3]]) for i in range(12)]
CODE = "def solve(n,k,edges):\n return {'assignment':[i%k for i in range(n)]}\n"


class Events:
    def __init__(self): self.rows = []
    def emit(self, kind, **fields): self.rows.append(dict(type=kind, **fields))


class FakeClient:
    def __init__(self, fail_at=None, code=CODE):
        self.budget, self.calls, self.lock = Budget(16, 32768), [], threading.Lock()
        self.infra_failures = self.budget_failures = 0
        self.fail_at, self.code = fail_at, code
    def call(self, agent, stage, prompt, **context):
        assert self.budget.reserve(2048)
        with self.lock: self.calls.append(dict(agent=agent, stage=stage, prompt=prompt, **context))
        self.budget.settle(2048, 10)
        if context["candidate_index"] == self.fail_at:
            self.infra_failures += 1
            return None
        return p.parse_program(self.code + f"# candidate {context['candidate_index']}\n")


def report(task, solved=True):
    values = [i % task["color_count"] for i in range(task["vertex_count"])] if solved else [0] * task["vertex_count"]
    output = {"assignment": values}
    proof = verify_assignment(task, output)
    return dict(solved=proof["solved"], status="passed" if proof["solved"] else "failed",
                proof=proof, candidate_output=output, input_unchanged=True, cleanup_ok=True, provenance="candidate",
                grading_authority="outer_parent", oracle_sent_to_child=False, graph_sha256=graph_digest(task),
                failure_kind=None if proof["solved"] else "candidate_graph_failure", parent_cpu_seconds=0.01)


class ProgramSearchTests(unittest.TestCase):
    def episode(self, directory, arm, evaluator=None, client=None):
        client, events = client or FakeClient(), Events()
        evaluator = evaluator or (lambda code, task, host, timeout: report(task))
        result = p.run_episode(DEV, EVAL, arm, 1, "Spark_01", client, events, Path(directory), evaluator)
        return result, client, events

    def test_ast_parser_never_executes_source_and_requires_complete_solve(self):
        with patch("os.system", side_effect=AssertionError("source executed")):
            parsed = p.parse_program("import os\nos.system('forbidden')\n" + CODE)
        self.assertIsNone(parsed["parse_error"])
        for code in ("not Python!", "x=1", "def solve(a): return a", "async def solve(n,k,e): return None", CODE + CODE):
            self.assertIsNotNone(p.parse_program(code)["parse_error"])
        self.assertEqual(p.parse_program("```python\n" + CODE + "```")["code"], CODE.strip())

    def test_both_arms_use_all16_calls_after_immediate_development_success(self):
        for arm in p.ARMS:
            with self.subTest(arm=arm), tempfile.TemporaryDirectory() as directory:
                grades = []
                def evaluate(code, task, host, timeout):
                    grades.append((task["id"], host, timeout)); return report(task)
                result, client, events = self.episode(directory, arm, evaluate)
                self.assertTrue(result["complete"])
                self.assertEqual(result["evaluation_solved"], 12)
                self.assertEqual(len(client.calls), 16)
                self.assertEqual(len(grades), 16 * 4 + 12)
                self.assertEqual(result["selected_candidate_index"], 0)
                self.assertEqual(result["model_budget"]["max_completion_tokens"], 32768)
                self.assertTrue(all(host == "Spark_01" and timeout == 10 for _, host, timeout in grades))
                self.assertIsNone(result["remote_solver_cpu_seconds"])

    def test_writer_context_is_own_last_candidate_and_never_evaluation_inputs(self):
        for arm, width in (("sequential16", 1), ("independent4", 4)):
            with tempfile.TemporaryDirectory() as directory:
                _, client, _ = self.episode(directory, arm)
                for call in client.calls:
                    index = call["candidate_index"]
                    expected = index - width if index >= width else None
                    self.assertEqual(call["previous_candidate_index"], expected)
                    for task in EVAL: self.assertNotIn(task["id"], call["prompt"])
                    if expected is None:
                        self.assertNotIn("Your own immediately", call["prompt"])
                    else:
                        self.assertIn(f"# candidate {expected}\n", call["prompt"])
                        self.assertEqual(re.findall(r"# candidate (\d+)", call["prompt"]), [str(expected)])

    def test_selection_is_persisted_before_evaluation_and_no_later_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            client, observed = FakeClient(), []
            def evaluate(code, task, host, timeout):
                index = int(re.search(r"# candidate (\d+)", code).group(1))
                if task["id"].startswith("eval_"):
                    selection = json.loads((Path(directory) / "selection.json").read_text())
                    self.assertFalse(selection["evaluation_seen"])
                    self.assertEqual(selection["candidate_index"], 1)
                    self.assertEqual(selection["code_sha256"], p.sha(Path(directory) / "selected.py"))
                    self.assertEqual(len(client.calls), 16)
                    observed.append(task["id"])
                return report(task, solved=index >= 1)
            result, _, events = self.episode(directory, "sequential16", evaluate, client)
            self.assertTrue(result["complete"])
            self.assertEqual(len(observed), 12)
            selected = next(i for i, row in enumerate(events.rows) if row["type"] == "program_selected")
            evaluations = [i for i, row in enumerate(events.rows) if row["type"] == "program_grade_start" and row["phase"] == "evaluation"]
            self.assertTrue(all(i > selected for i in evaluations))

    def test_conflict_penalties_and_errors_have_fixed_order(self):
        task = DEV[0]
        self.assertEqual(p.penalty(task, report(task)), 0)
        self.assertEqual(p.penalty(task, report(task, False)), 3)
        self.assertEqual(p.penalty(task, dict(status="error", solved=False)), 4)
        changed = report(task); changed.update(solved=False, status="failed", input_unchanged=False)
        self.assertEqual(p.penalty(task, changed), 4)

    def test_true_infrastructure_stops_without_selection_or_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            result, client, events = self.episode(directory, "independent4", client=FakeClient(fail_at=5))
            self.assertFalse(result["complete"])
            self.assertEqual(len(client.calls), 8)  # Entire dispatched batch charged.
            self.assertEqual(result["evaluation_completed"], 0)
            self.assertFalse((Path(directory) / "selection.json").exists())
            self.assertTrue((Path(directory) / "candidate-07.raw.txt").exists())

    def test_candidate_timeouts_are_failures_not_infrastructure(self):
        with tempfile.TemporaryDirectory() as directory:
            def evaluate(code, task, host, timeout):
                value = report(task, False)
                value.update(status="timeout", solved=False, failure_kind="candidate_timeout", proof=None)
                return value
            result, client, _ = self.episode(directory, "sequential16", evaluate)
            self.assertTrue(result["complete"])
            self.assertEqual(len(client.calls), 16)
            self.assertEqual(result["evaluation_solved"], 0)

    def test_selected_file_mutation_halts_remaining_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            def evaluate(code, task, host, timeout):
                if task["id"] == EVAL[0]["id"]:
                    (Path(directory) / "selected.py").write_text("changed")
                return report(task)
            result, _, _ = self.episode(directory, "sequential16", evaluate)
            self.assertFalse(result["complete"])
            self.assertEqual(result["evaluation_completed"], 1)
            self.assertIsNotNone(result["selected_sha256"])
            self.assertIn("changed", result["error"])

    def test_forged_success_proof_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            def evaluate(code, task, host, timeout):
                value = report(task, False); value["proof"]["solved"] = True
                return value
            result, _, _ = self.episode(directory, "sequential16", evaluate)
            self.assertFalse(result["complete"])
            self.assertIn("replayed", result["error"])

    def test_plan_mode_never_reads_live_gate_or_runs_master(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(p, "load_plan", return_value=({"protocol": "fixture"}, DEV, EVAL)), \
                    patch.object(p, "followup_gate") as gate, patch.object(p, "run_master") as run, \
                    contextlib.redirect_stdout(io.StringIO()) as output:
                self.assertEqual(p.main(["--gate-root", directory]), 0)
            gate.assert_not_called(); run.assert_not_called()
            self.assertEqual(json.loads(output.getvalue())["mode"], "plan")

    def test_post_controller_gate_requires_complete_hash_linked_ledger(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(p, "verify_gate", return_value={"mock": True}):
            root = Path(directory); folder = root / ".runtime/post-throughput-overnight-v1"; folder.mkdir(parents=True)
            entries = [dict(status="complete", verified=True, returncode=0)] * 10
            (folder / "ledger.json").write_text(json.dumps(entries))
            state = dict(status="complete", ledger_sha256=p.sha(folder / "ledger.json"))
            (folder / "state.json").write_text(json.dumps(state))
            self.assertIn("post_state_sha256", p.followup_gate(root))
            state["status"] = "running"; (folder / "state.json").write_text(json.dumps(state))
            with self.assertRaises(RuntimeError): p.followup_gate(root)

    def test_master_assigns_one_pair_per_endpoint_and_alternates_arm_order(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); output = root / "run"
            identity = dict(revision="fixture", tracked_clean=True, source_files_tracked=True, sha256={"fixture": "same"})
            pairs = [dict(seed=seed, host=f"Spark_{seed:02d}", endpoint=f"http://unused-{seed}/v1",
                          arms=list(p.ARMS if seed % 2 else reversed(p.ARMS))) for seed in p.SEEDS]
            plan = dict(output=str(output), source=identity, runtime={"served_model_name": "fixture"}, pairs=pairs)
            order, active, lock = {}, set(), threading.Lock()
            def episode(dev, evaluation, arm, seed, host, client, events, folder, evaluator, stop):
                with lock:
                    self.assertNotIn(seed, active); active.add(seed)
                    order.setdefault(seed, []).append(arm)
                self.assertEqual(host, f"Spark_{seed:02d}")
                self.assertEqual(client.endpoints, [f"http://unused-{seed}/v1"])
                self.assertEqual(client.max_tokens, 2048)
                self.assertEqual(client.timeout, 210)
                self.assertFalse(client.thinking)
                with lock: active.remove(seed)
                return dict(seed=seed, arm=arm, status="complete", complete=True, evaluation_completed=12,
                            evaluation_solved=12, selected_sha256="fixture", development_solved=4)
            with patch.object(p, "source_hashes", return_value=identity["sha256"]), \
                    patch.object(p, "source_identity", return_value=identity), \
                    patch.object(p, "drain", return_value=({"prompt": 0, "completion": 0, "running": 0, "waiting": 0}, True, 0.0)), \
                    patch.object(p, "qualify_program_grader", return_value={"verified": True}), \
                    patch.object(p, "run_episode", side_effect=episode), \
                    patch("csp_program_grader.evaluate_program", side_effect=AssertionError("CPU execution forbidden")):
                self.assertEqual(p.run_master(plan, DEV, EVAL, {"fixture": True}), 0)
            self.assertEqual(order, {pair["seed"]: pair["arms"] for pair in pairs})
            self.assertEqual(len(json.loads((output / "results.json").read_text())), 8)
            self.assertTrue(json.loads((output / "metadata.json").read_text())["verified"])

    def test_master_refuses_busy_fleet_before_any_episode(self):
        with tempfile.TemporaryDirectory() as directory:
            plan = dict(output=str(Path(directory) / "run"), pairs=[{"endpoint": str(i)} for i in range(4)])
            with patch.object(p, "drain", return_value=({"running": 1}, False, 0.0)), \
                    patch.object(p, "run_episode") as episode:
                self.assertEqual(p.run_master(plan, DEV, EVAL, {}), 1)
            episode.assert_not_called()

    def test_authored_live_qualification_logic_with_fake_grades_only(self):
        with tempfile.TemporaryDirectory() as directory:
            def evaluate(code, task, host, timeout):
                if "os.write" in code:
                    value = report(task, False)
                    value.update(status="error", failure_kind="candidate_protocol", proof=None)
                    return value
                return report(task, "[0,1,2]" in code)
            result = p.qualify_program_grader(evaluate, "Spark_04", directory)
            self.assertTrue(result["verified"])
            self.assertEqual(len(result["rows"]), 3)
            self.assertEqual(result["model_calls"], 0)
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(RuntimeError):
                p.qualify_program_grader(lambda code, task, host, timeout: report(task), "Spark_04", directory)
            self.assertFalse(json.loads((Path(directory) / "program-grader-qualification.json").read_text())["verified"])


if __name__ == "__main__": unittest.main()
