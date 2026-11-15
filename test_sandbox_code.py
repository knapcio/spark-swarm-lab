"""Offline checks: trusted functions and fake subprocesses only."""
import json
import shlex
import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import sandbox_code as s


class SandboxTests(unittest.TestCase):
    def test_isolated_command_and_stdin_payload_never_interpolate_candidate(self):
        code = 'def add(a,b): return a+b\n# $(touch /tmp/unsafe); `id`'
        report = dict(status="passed", total=1, tests_run=1, passed=1, failed=0)
        with patch.object(s.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout=json.dumps(report), stderr="")) as run:
            self.assertEqual(s.evaluate_code(code, "add", [{"args": [2, 3], "expected": 5}], "Spark_02"), report)
        argv = run.call_args.args[0]
        self.assertEqual(argv[:6], ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", "--"])
        docker = shlex.split(argv[-1])
        for flag, value in [("--network", "none"), ("--cap-drop", "ALL"), ("--memory", "256m"),
                            ("--pids-limit", "64"), ("--user", "65534:65534"), ("--cpus", "1"),
                            ("--security-opt", "no-new-privileges"), ("--entrypoint", "python3"), ("--pull", "never"), ("--runtime", "runc")]:
            self.assertEqual(docker[docker.index(flag) + 1], value)
        self.assertIn("--read-only", docker)
        self.assertIn("--rm", docker)
        self.assertIn(s.IMAGE, docker)
        self.assertIn("NVIDIA_VISIBLE_DEVICES=void", docker)
        self.assertTrue(any(v.startswith("/tmp:rw,noexec,nosuid,nodev,size=16m") for v in docker))
        self.assertFalse(set(docker) & {"--gpus", "--device", "--privileged", "-v", "--volume", "--mount"})
        self.assertNotIn(code, argv[-1])
        self.assertEqual(json.loads(run.call_args.kwargs["input"])["code"], code)
        self.assertEqual(run.call_args.kwargs["timeout"], 25)

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
        with patch.object(s.subprocess, "run", side_effect=[subprocess.TimeoutExpired("ssh", 25),
                         SimpleNamespace(returncode=0, stdout="", stderr="")]) as run:
            result = s.evaluate_code("def f(): pass", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertEqual(result["status"], "timeout")
        self.assertTrue(result["cleanup_ok"])
        first = shlex.split(run.call_args_list[0].args[0][-1])
        name = first[first.index("--name") + 1]
        cleanup = shlex.split(run.call_args_list[1].args[0][-1])
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
        with patch.object(s.subprocess, "run", return_value=SimpleNamespace(returncode=0, stdout="noise", stderr="")):
            result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertEqual(result["status"], "error")

    def test_failed_cleanup_is_not_reported_as_success(self):
        with patch.object(s.subprocess, "run", side_effect=[subprocess.TimeoutExpired("ssh", 25),
                         SimpleNamespace(returncode=1, stdout="", stderr="ownership mismatch")]):
            result = s.evaluate_code("unused", "f", [{"args": [], "expected": None}], "Spark_01")
        self.assertFalse(result["cleanup_ok"])

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
