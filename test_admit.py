"""Offline tests for inkling/admit.py container-name support (ssh, docker and HTTP mocked)."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import admit  # noqa: E402

METRICS = 'vllm:num_requests_running{x="1"} 0\nvllm:num_requests_waiting{x="1"} 0\n'


class Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class AdmitContainerTests(unittest.TestCase):
    def run_admit(self, serving, oom=False):
        inspected = []

        def inspect(node, name):
            inspected.append((node, name))
            return dict(hostname=f'spark-{node}', container_id='abc', image=['sha256:img'], local_image_id='x',
                        running=True, started_at='t', oom=oom and name.endswith('shim'), restarts=0,
                        cmd=['python3', '--mem-fraction-static', '0.75'], entrypoint=None, env=[])
        shim_sha = admit.hashlib.sha256((admit.HERE / 'shim.py').read_bytes()).hexdigest()
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / 'plan.json'
            plan.write_text(json.dumps(dict(status='FROZEN', source_revision='x', serving=serving)))
            out = Path(d) / 'adm.json'
            with patch.object(admit, 'inspect', inspect), \
                    patch.object(admit.runner, 'validate_source', lambda *a: None), \
                    patch.object(admit.subprocess, 'check_output', lambda *a, **k: f'{shim_sha}  shim.py\n'), \
                    patch.object(admit.urllib.request, 'urlopen', lambda url, timeout=10: Response(METRICS.encode())), \
                    contextlib.redirect_stdout(io.StringIO()):
                code = admit.main(['--plan', str(plan), '--source', d, '--output', str(out)])
            receipt = json.loads(out.read_text())
        return code, receipt, inspected

    def test_default_names(self):
        code, receipt, inspected = self.run_admit({})
        self.assertEqual(code, 0)
        self.assertTrue(receipt['verified'])
        self.assertEqual(sorted({n for _, n in inspected}), ['swarm-inkling', 'swarm-inkling-shim'])
        self.assertEqual(receipt['containers'], dict(server='swarm-inkling', shim='swarm-inkling-shim'))

    def test_plan_names_are_used_with_the_same_checks(self):
        serving = dict(container='swarm-inkling-v29', shim_container='swarm-inkling-v29-shim', mem_fraction='0.75')
        code, receipt, inspected = self.run_admit(serving)
        self.assertEqual(code, 0)
        self.assertEqual(sorted({n for _, n in inspected}), ['swarm-inkling-v29', 'swarm-inkling-v29-shim'])
        self.assertEqual(len(inspected), 8)
        code, receipt, _ = self.run_admit(serving, oom=True)  # unchanged checks still apply
        self.assertEqual((code, receipt['verified']), (1, False))
        code, receipt, _ = self.run_admit(dict(serving, mem_fraction='0.80'))
        self.assertFalse(receipt['verified'])

    def test_invalid_names_are_refused(self):
        for serving in (dict(container='x; rm -rf ~'), dict(container='a', shim_container='a'), dict(shim_container='')):
            with self.assertRaises(SystemExit):
                self.run_admit(serving)


if __name__ == '__main__':
    unittest.main()
