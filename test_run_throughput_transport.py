"""The transport must not expire before the controller's task deadline."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class TransportBudgetTests(unittest.TestCase):
    def test_all_policy_plans_keep_task_budget_and_transport_margin(self):
        root = Path(__file__).resolve().parent
        arms = json.loads((root / "THROUGHPUT_DEVELOPMENT.json").read_text())["arms"]
        arms += ["independent32", "independent100", "democracy32", "shared8"]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "not-created-by-plan"
            for arm in arms:
                result = subprocess.run([sys.executable, str(root / "run_throughput.py"),
                    "--dataset", str(root / "datasets/arithmetic-v1/tasks.json"),
                    "--split", "development", "--seeds", "1", "--arm", arm,
                    "--jobs-per-node", "8", "--output", str(output)],
                    capture_output=True, text=True, check=True)
                plan = json.loads(result.stdout)
                self.assertEqual(plan["case_deadline_after_admission_seconds"], 180)
                self.assertEqual(plan["request_timeout_seconds"], 210)
                self.assertGreater(plan["request_timeout_seconds"], plan["case_deadline_after_admission_seconds"])
                for case in plan["cases"]:
                    command = case["command"]
                    self.assertEqual(command[command.index("--timeout") + 1], "210")
                    self.assertEqual(command[command.index("--max-completion-tokens") + 1], "32768")
                self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
