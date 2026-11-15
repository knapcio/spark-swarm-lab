"""Offline checks: trusted functions and fake subprocesses only."""
import json
import shlex
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sandbox_code as s


def remote(run_result, state=None, cleanup_code=0, inspection_code=0):
    """Fake the run -> owned state inspection -> guarded removal protocol."""
    labels = {}
    def invoke(argv, **kwargs):
        command = shlex.split(argv[-1])
        if command[:2] == ["docker", "run"]:
            labels.update(dict(command[i + 1].split("=", 1) for i, value in enumerate(command) if value == "--label"))
            if isinstance(run_result, Exception):
                raise run_result
            return run_result
        if command[:2] == ["docker", "inspect"]:
            value = dict(Config=dict(Labels=labels), State=state or dict(OOMKilled=False, ExitCode=0, Error="", Running=False))
            return SimpleNamespace(returncode=inspection_code, stdout=json.dumps(value), stderr="inspection unavailable" if inspection_code else "")
        if command[:2] == ["sh", "-c"]:
            return SimpleNamespace(returncode=cleanup_code, stdout="", stderr="ownership mismatch" if cleanup_code else "")
        raise AssertionError(command)
    return invoke


class SandboxTests(unittest.TestCase):
    def test_isolated_command_and_stdin_payload_never_interpolate_candidate(self):
        code = 'def add(a,b): return a+b\n# $(touch /tmp/unsafe); `id`'
        report = dict(status="passed", total=1, tests_run=1, passed=1, failed=0)
        with patch.object(s.subprocess, "run", side_effect=remote(SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr=""))) as run:
            result = s.evaluate_code(code, "add", [{"args": [2, 3], "expected": 5}], "Spark_02")
            self.assertEqual({key: result[key] for key in report}, report)
            self.assertTrue(result["cleanup_ok"])
        call = run.call_args_list[0]
        argv = call.args[0]
        self.assertEqual(argv[:6], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--"])
        docker = shlex.split(argv[-1])
        for flag, value in [("--network", "none"), ("--cap-drop", "ALL"), ("--memory", "256m"),
                            ("--pids-limit", "64"), ("--user", "65534:65534"), ("--cpus", "1"),
                            ("--security-opt", "no-new-privileges"), ("--entrypoint", "python3"), ("--pull", "never"), ("--runtime", "runc")]:
            self.assertEqual(docker[docker.index(flag) + 1], value)
        self.assertIn("--read-only", docker)
        self.assertNotIn("--rm", docker)  # Preserve OOM state until inspection.
        self.assertIn(s.IMAGE, docker)
        self.assertIn("NVIDIA_VISIBLE_DEVICES=void", docker)
        self.assertTrue(any(v.startswith("/tmp:rw,noexec,nosuid,nodev,size=16m") for v in docker))
        self.assertFalse(set(docker) & {"--gpus", "--device", "--privileged", "-v", "--volume", "--mount"})
        self.assertNotIn(code, argv[-1])
        self.assertEqual(json.loads(call.kwargs["input"])["code"], code)
        self.assertEqual(call.kwargs["timeout"], 25)
        self.assertEqual(shlex.split(run.call_args_list[1].args[0][-1])[:2], ["docker", "inspect"])
        self.assertEqual(len(run.call_args_list), 3)

    def test_trusted_function_cases_clone_inputs_and_report_first_failure(self):
        def trusted(items, scale=1):
            items.append(99)
            return len(items) * scale
        tests = [{"args": [[1]], "kwargs": {"scale": 2}, "expected": 4, "check_input_unchanged": False},
                 {"args": [[1]], "expected": 100, "check_input_unchanged": False},
                 {"args": [[1]], "expected": 2, "check_input_unchanged": False}]
        report = s._run_cases(trusted, tests)
        self.assertEqual((report["passed"], report["failed"]), (2, 1))
        self.assertEqual(report["first_failure"]["test_index"], 1)
        self.assertEqual(report["first_failure"]["actual"], 2)
        self.assertEqual(tests[0]["args"], [[1]])

    def test_expected_exceptions_and_bounded_diagnostics(self):
        def trusted(value):
            raise ValueError(value)
        cases = [{"args": ["ok"], "expected_exception": "ValueError"},
                 {"args": ["x" * 5000], "expected_exception": "TypeError"}]
        result = s._run_cases(trusted, cases)
        self.assertEqual(result["passed"], 1)
        self.assertLess(len(json.dumps(result)), 4000)

    def test_timeout_cleanup_requires_both_owned_task_labels_and_exact_name(self):
        with patch.object(s.subprocess, "run", side_effect=remote(subprocess.TimeoutExpired("ssh", 25))) as run:
            result = s.evaluate_code("def f(): pass", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["cleanup_ok"])
        first = shlex.split(run.call_args_list[0].args[0][-1])
        name = first[first.index("--name") + 1]
        cleanup = shlex.split(run.call_args_list[2].args[0][-1])
        self.assertEqual(cleanup[:2], ["sh", "-c"])
        self.assertIn('swarm-lab.code-owner', cleanup[2])
        self.assertIn('swarm-lab.code-task', cleanup[2])
        self.assertIn(s.OWNER, cleanup[2])
        self.assertIn("docker rm -f " + name, cleanup[2])
        self.assertNotIn("docker ps", cleanup[2])

    def test_invalid_arguments_do_not_contact_host(self):
        with patch.object(s.subprocess, "run") as run:
            for function, cases, host in [("bad()", [{"args": [], "expected": 0}], "Spark_01"),
                ("f", [{"args": [], "expected": 0}], "host; id"),
                ("f", [{"args": [], "expected": 0, "expected_exception": "ValueError"}], "Spark_01")]:
                with self.assertRaises(ValueError):
                    s.evaluate_code("unused", function, cases, host)
            run.assert_not_called()

    def test_malformed_runner_response_is_not_a_passing_grade(self):
        with patch.object(s.subprocess, "run", side_effect=remote(SimpleNamespace(returncode=0, stdout="noise", stderr=""))):
            result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertEqual(result["status"], "error")

    def test_failed_cleanup_is_not_reported_as_success(self):
        with patch.object(s.subprocess, "run", side_effect=remote(subprocess.TimeoutExpired("ssh", 25), cleanup_code=1)):
            result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertFalse(result["cleanup_ok"])
        self.assertEqual(result["failure_kind"], "cleanup_infrastructure")

    def test_oom_and_signal_are_candidate_failures_not_empty_stderr_transport_failures(self):
        for oom, kind in [(True, "candidate_oom"), (False, "candidate_signal")]:
            state = dict(OOMKilled=oom, ExitCode=137, Error="", Running=False)
            with patch.object(s.subprocess, "run", side_effect=remote(SimpleNamespace(returncode=137, stdout="", stderr=""), state)):
                result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_04")
            self.assertEqual(result["failure_kind"], kind)
            self.assertEqual(result["provenance"], "candidate")
            self.assertEqual(result["container_state"]["OOMKilled"], oom)
            self.assertTrue(result["cleanup_ok"])

    def test_docker_start_ssh_and_inspection_failures_remain_infrastructure(self):
        cases = [(125, dict(OOMKilled=False, ExitCode=0, Error="runtime failed", Running=False), 0, "docker_infrastructure"),
                 (255, None, 0, "ssh_infrastructure"), (0, None, 1, "inspection_infrastructure")]
        for exit_code, state, inspect_code, kind in cases:
            with self.subTest(kind=kind), patch.object(s.subprocess, "run", side_effect=remote(
                    SimpleNamespace(returncode=exit_code, stdout='{"status":"passed"}', stderr="failure"), state, inspection_code=inspect_code)):
                result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_04")
            self.assertEqual(result["failure_kind"], kind)
            self.assertEqual(result["provenance"], "infrastructure")
            self.assertTrue(result["cleanup_ok"])

    def test_state_inspection_rejects_foreign_ownership(self):
        container = dict(Config=dict(Labels={"swarm-lab.code-owner": s.OWNER, "swarm-lab.code-task": "foreign"}), State=dict(OOMKilled=True))
        with patch.object(s, "_ssh", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(container), stderr="")):
            state, error = s._inspect_owned("Spark_04", "swarm-code-own", "own")
        self.assertIsNone(state)
        self.assertIn("ownership", error)

    def test_static_remote_runner_compiles_without_running_candidate_locally(self):
        compile(s.RUNNER, "<trusted-runner>", "exec")

    def test_json_type_confusion_and_container_shape_are_rejected(self):
        for actual, expected in [(True, 1), (1.0, 1), (1, 1.0), ([True], [1]),
                                 ({"value": False}, {"value": 0}), ((1, 2), [1, 2]),
                                 ({"a": 1, "extra": 2}, {"a": 1})]:
            with self.subTest(actual=actual, expected=expected):
                report = s._run_cases(lambda: actual, [{"args": [], "expected": expected}])
                self.assertEqual(report["failed"], 1)
        self.assertTrue(s._json_equal({"value": [1, 2.0, True, None]}, {"value": [1, 2.0, True, None]}))

    def test_input_postcondition_is_checked_even_on_expected_exception(self):
        def trusted(items):
            items.append(9)
            return 2
        result = s._run_cases(trusted, [{"args": [[1]], "expected": 2}])
        self.assertEqual(result["passed"], 0)
        self.assertEqual(result["first_failure"]["failure_kind"], "input_mutation")
        self.assertEqual(result["first_failure"]["input_after"]["args"], [[1, 9]])
        def trusted_raise(*, items):
            items.clear()
            raise ValueError("after mutation")
        case = {"args": [], "kwargs": {"items": [1]}, "expected_exception": "ValueError"}
        result = s._run_cases(trusted_raise, [case])
        self.assertEqual(result["failed"], 1)
        self.assertFalse(result["first_failure"]["input_unchanged"])
        self.assertEqual(s._run_cases(trusted_raise, [dict(case, check_input_unchanged=False)])["passed"], 1)

    def test_dictionary_order_is_optional_and_recursive(self):
        actual = {"outer": {"b": 2, "a": 1}}
        case = {"args": [], "expected": {"outer": {"a": 1, "b": 2}}}
        self.assertEqual(s._run_cases(lambda: actual, [case])["passed"], 1)
        self.assertEqual(s._run_cases(lambda: actual, [dict(case, ordered_dict=True)])["failed"], 1)
        self.assertEqual(s._run_cases(lambda: {"outer": {"a": 1, "b": 2}}, [dict(case, ordered_dict=True)])["passed"], 1)

    def test_case_flags_must_be_boolean_before_any_remote_call(self):
        with patch.object(s.subprocess, "run") as run:
            for flag in ("check_input_unchanged", "ordered_dict"):
                with self.assertRaises(ValueError):
                    s.evaluate_code("unused", "f", [{"args": [], "expected": 1, flag: "false"}], "Spark_01")
            run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
