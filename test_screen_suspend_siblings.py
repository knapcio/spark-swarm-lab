"""Offline screen of idea #5 (suspend siblings while acceptance is pending) on synthetic recorded runs."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / 'inkling'))
import screen_suspend_siblings as s  # noqa: E402


def agent(slot, start, finish, tokens, verdict=None, judged=None, cancelled=False):
    return dict(slot=slot, started=True, started_s=start, finished_s=finish, tokens=tokens, verdict=verdict,
                judged_s=judged, cancelled=cancelled, judge_skipped=False)


class ScreenTests(unittest.TestCase):
    def test_arithmetic_saving_and_pessimistic_recompute(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            # winner slot 0 exits at 100, judged at 140; slot 1 generates 10 tok/s over 0..200 (400 tokens in the
            # window); slot 2 was rejected (judged 50..60) while slots 0 and 1 were in flight
            rows = [dict(selected_slot=0, agents=[agent(0, 0, 100, 1000, True, 140), agent(1, 0, 200, 2000),
                                                  agent(2, 0, 50, 500, False, 60)])]
            (d / 'cases.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
            r = s.arith_run(d)
            self.assertAlmostEqual(r['saved'], 400.0)
            self.assertEqual((r['accepted_windows'], r['rejected_windows']), (1, 1))
            # slots 0 and 1 paused during 50..60: contexts 600 + 10*50 each
            self.assertAlmostEqual(r['recompute'], 2 * (s.ARITH_PROMPT_TOKENS + 500))
            self.assertAlmostEqual(r['delay_s'], 20.0)

    def test_coding_judge_window_and_cancelled_stream_rate(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            t = lambda sec: f'2026-11-27T00:00:{sec:02d}+00:00'
            win = [dict(type='request_start', request_id='a', timestamp=t(0)),
                   dict(type='request_end', request_id='a', timestamp=t(10), usage=dict(completion_tokens=100)),
                   dict(type='judge_start', timestamp=t(10)),
                   dict(type='acceptance', accepted=True, timestamp=t(30))]
            sib = [dict(type='request_start', request_id='b', timestamp=t(0)),
                   dict(type='controller_stop', timestamp=t(40))]  # cancelled: tokens unknown, median rate 10/s
            (d / 'w.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in win))
            (d / 's.jsonl').write_text(''.join(json.dumps(e) + '\n' for e in sib))
            summary = [dict(task_id='t', seed=1, agent=0, events=str(d / 'w.jsonl'), winner=True),
                       dict(task_id='t', seed=1, agent=1, events=str(d / 's.jsonl'), winner=False)]
            (d / 'summary.json').write_text(json.dumps(summary))
            r = s.coding_run(d, 'judge')
            self.assertAlmostEqual(r['saved'], 200.0)  # 20 s of the sibling at the median 10 tok/s
            self.assertEqual(r['accepted_windows'], 1)

    def test_frozen_rule(self):
        self.assertEqual(s.THRESHOLD, 0.02)


if __name__ == '__main__':
    unittest.main()
