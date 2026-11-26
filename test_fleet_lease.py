"""The shared fleet lease (inkling/fleet_lease.py), held by arms.py, coding_arms.py and collab_replay.py."""
import json
import multiprocessing
import subprocess
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


def repo_with_worktree(d):
    """A git repository at d/main with a second worktree at d/wt."""
    main = Path(d) / 'main'
    main.mkdir()
    git = lambda *a: subprocess.run(['git', '-C', str(main), *a], check=True, capture_output=True)
    git('init', '-q')
    git('config', 'user.email', 't@t')
    git('config', 'user.name', 't')
    (main / 'f').write_text('x')
    git('add', 'f')
    git('commit', '-q', '-m', 'f')
    git('worktree', 'add', '-q', str(Path(d) / 'wt'))
    return main, Path(d) / 'wt'


class LeaseTests(unittest.TestCase):
    def test_runners_in_different_worktrees_contend_for_one_lock(self):
        with tempfile.TemporaryDirectory() as d:
            main, wt = repo_with_worktree(d)
            self.assertEqual(fleet_lease.lease_path(main), fleet_lease.lease_path(wt))
            ctx = multiprocessing.get_context('spawn')
            ready, release = ctx.Event(), ctx.Event()
            proc = ctx.Process(target=hold, args=(str(main), ready, release))
            proc.start()
            try:
                self.assertTrue(ready.wait(20))
                with self.assertRaises(fleet_lease.LeaseBusy):
                    with fleet_lease.lease(wt, 'runner in another worktree'):
                        pass
            finally:
                release.set()
                proc.join(20)
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):  # never a per-directory fallback lock
                with fleet_lease.lease(d, 'outside any repository'):
                    pass

    def test_second_holder_fails_with_the_first_holders_description(self):
        with tempfile.TemporaryDirectory() as d:
            d, _ = repo_with_worktree(d)
            ctx = multiprocessing.get_context('spawn')
            ready, release = ctx.Event(), ctx.Event()
            proc = ctx.Process(target=hold, args=(str(d), ready, release))
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
