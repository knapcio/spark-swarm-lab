#!/usr/bin/env python3
"""One line per bugbench attempt: selected patch hidden result, oracle, localization, cost."""
import json
import sys

for line in open(sys.argv[1]):
    d = json.loads(line)
    g = d.get('selected_grade') or {}
    o = d.get('oracle') or {}
    loc = d.get('localization') or {}
    print(f"{d['case_id'][:30]:30} {d['policy']:3} s{d['seed']} {d['status']:9} cand={d['selection'].get('candidates')} "
          f"selected={'PASS' if g.get('status') == 'passed' else g.get('status')} "
          f"oracle_any={o.get('any_passed')} loc={loc.get('correct_file', loc)} "
          f"calls={d['budget']['calls']} tok={d['budget']['completion_tokens']} wall={d.get('wall_s')}")
