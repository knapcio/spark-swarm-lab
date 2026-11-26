"""strict_verify and the strict-verifier audit (synthetic runs)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import audit_strict_verifier as audit  # noqa: E402
import strict_verify as sv  # noqa: E402

GOOD = {'moves': [{'i': 0, 'j': 1, 'op': '+'}]}
TRAILING = {'moves': [{'i': 0, 'j': 1, 'op': '+'}, {'i': 5, 'j': 6, 'op': '-'}]}


class StrictTests(unittest.TestCase):
    def test_trailing_illegal_move(self):
        self.assertEqual((sv.lenient_solved([2, 3, 7], 5, TRAILING), sv.strict_solved([2, 3, 7], 5, TRAILING)),
                         (True, False))
        self.assertTrue(sv.strict_solved([2, 3, 7], 5, GOOD))
        self.assertTrue(sv.strict_solved([2, 3, 7], 5, {'moves': [{'i': 0, 'j': 1, 'op': '+'},
                                                                   {'i': 0, 'j': 1, 'op': '+'}]}))  # legal after it
        self.assertFalse(sv.strict_solved([2, 3, 7], 5, {'moves': [], 'x': 1}))

    def test_audit_counts_flips(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            run = root / 'runs' / 'swarm-x-hard21-v1-roll12fair'
            run.mkdir(parents=True)
            data = root / 'datasets' / 'c' / 'tasks.json'
            data.parent.mkdir(parents=True)
            data.write_text(json.dumps(dict(tasks=[dict(id='t', numbers=[2, 3, 7], target=5)])))
            (run / 'metadata.json').write_text(json.dumps(dict(protocol=dict(dataset='datasets/c/tasks.json'))))
            (run / 'cases.jsonl').write_text(json.dumps(dict(task_id='t', seed=1, agents=[
                dict(slot=0, verdict=True, plan=GOOD), dict(slot=1, verdict=True, plan=TRAILING),
                dict(slot=2, verdict=False, plan=TRAILING)])) + '\n')
            r = audit.audit(root / 'runs', root)
            self.assertEqual(r['total'], dict(accepted=2, lenient_solved=2, strict_solved=1, flips=1))
            self.assertEqual(r['runs'][0]['flipped'], ['t-s1-a1'])


if __name__ == '__main__':
    unittest.main()
