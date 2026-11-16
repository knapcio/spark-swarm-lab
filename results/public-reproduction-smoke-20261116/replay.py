import hashlib, json
from pathlib import Path
from csp_tasks import load_tasks, verify_assignment
from report_completed_studies import crossed_program_statistics

base = Path('results/program-confirmation-v1-analysis')
manifest = json.loads((base / 'manifest.json').read_text())
for name, expected in manifest['files'].items():
    assert hashlib.sha256((base / name).read_bytes()).hexdigest() == expected, name
tasks = {t['id']: t for t in load_tasks(base / 'evidence/corpus.json', 'evaluation')}
grades = [json.loads(line) for line in (base / 'evidence/grades.jsonl').read_text().splitlines()]
assert len(grades) == len({(r['seed'], r['arm'], r['task_id']) for r in grades}) == 768
for row in grades:
    report = row['report']
    assert row['infrastructure'] is False and report['cleanup_ok'] is True
    source = base / f"evidence/selected-s{row['seed']}-{row['arm']}.py"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == row['code_sha256']
    if report.get('proof') is not None:
        assert verify_assignment(tasks[row['task_id']], report['candidate_output']) == report['proof']
    assert row['solved'] is report['solved']
rows = [{k: r[k] for k in ('task_id', 'seed', 'arm', 'solved')} for r in grades]
print(json.dumps(crossed_program_statistics(rows, 5000, 20261115), indent=2))
