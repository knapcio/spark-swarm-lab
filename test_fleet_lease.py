"""The shared fleet lease (inkling/fleet_lease.py), held by arms.py, coding_arms.py and collab_replay.py."""
import json
import multiprocessing
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import fleet_lease  # noqa: E402


def hold(root, ready, release):
    with fleet_lease.lease(root, 'other runner'):
        ready.set()
        release.wait(10)


class LeaseTests(unittest.TestCase):
    def test_second_holder_fails_with_the_first_holders_description(self):
        with tempfile.TemporaryDirectory() as d:
            ctx = multiprocessing.get_context('spawn')
            ready, release = ctx.Event(), ctx.Event()
            proc = ctx.Process(target=hold, args=(d, ready, release))
            proc.start()
            try:
                self.assertTrue(ready.wait(20))
                with self.assertRaises(fleet_lease.LeaseBusy) as err:
                    with fleet_lease.lease(d, 'me'):
                        pass
                self.assertIn('other runner', str(err.exception))
            finally:
                release.set()
                proc.join(20)
            with fleet_lease.lease(d, 'me') as path:  # free again once the holder is gone
                self.assertEqual(json.loads(path.read_text())['holder'], 'me')

    def test_arms_runners_hold_the_lease(self):
        import arms
        import coding_arms
        seen = []

        class Lease:
            def __init__(self, root, holder):
                seen.append(holder)

            def __enter__(self):
                return None

            def __exit__(self, *exc):
                return False
        with tempfile.TemporaryDirectory() as d:
            plan = Path(d) / 'p.json'
            plan.write_text(json.dumps(dict(study='s', source_path='x')))
            with patch.object(arms.fleet_lease, 'lease', Lease), patch.object(arms, 'run_arm', lambda *a: 0), \
                    patch.object(coding_arms, 'run_arm', lambda *a: 0):
                arms.main(['--plan', str(plan), '--arm', 'roll12fair', '--output', str(Path(d) / 'o1')])
                coding_arms.main(['--plan', str(plan), '--output', str(Path(d) / 'o2')])
        self.assertEqual(len(seen), 2)
        self.assertTrue(seen[0].startswith('arms.py s roll12fair'))
        self.assertTrue(seen[1].startswith('coding_arms.py s'))


if __name__ == '__main__':
    unittest.main()
