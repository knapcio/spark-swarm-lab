# Reproducing published evidence

The public checkout supports offline analysis of the completed primary exports
and standalone arithmetic/graph experiments on compatible endpoints.
Full fleet orchestration remains specific to the original four-Spark study.

## Fresh checkout and offline checks

Use Python 3.12+ for the optional plotting environment. Core offline CI tests
Python 3.10 and 3.12. These commands do not contact a model or change a server:

```sh
git clone https://github.com/knapcio/spark-swarm-lab.git
cd spark-swarm-lab
git checkout study-20261116
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-plot.txt
.venv/bin/python -m unittest -q
.venv/bin/python export_benchmark.py --self-test
.venv/bin/python validate_frozen_corpora.py
```

Package installation downloads plotting dependencies; subsequent commands use local fixtures/data only. Fetch full Git history when cloning elsewhere;
offline source audits inspect historical frozen commits/tags.

## Rebuild primary tables and figures without GPUs

The published ledger identifies six completed cohorts. Seeds stay clustered by task.
Run from the repository root, using new output directories:

```sh
for domain in arithmetic coding; do
  .venv/bin/python aggregate_evaluation.py \
    results/evaluation-v2/${domain}-s1 \
    results/evaluation-v2/${domain}-s2 \
    results/evaluation-v2/${domain}-s3 \
    --domain "$domain" \
    --ledger results/evaluation-v2/primary-aggregate/verified-ledger.json \
    --bootstrap 5000 --bootstrap-seed 20261115 \
    --output "runs/replay-primary-${domain}" --plot
done
.venv/bin/python server.py --runs-dir results/evaluation-v2/arithmetic-s1 --port 18777
```

Open http://127.0.0.1:18777 for arithmetic traces. Rebuilt tables use the same
statistical inputs/seed; paths, figure metadata/fonts and library versions can change bytes.
Existing `curate.py`/`audit.py` snapshots inside result folders may
require original private paths and write their original destinations; they are
provenance records, not fresh-checkout commands. Export manifests retain hashes
and reversible path-normalization records.

**Coding tables above are the original frozen same-interpreter grades.** They
remain separate from later independent confirmation and additional test probes.
The original grader can expose expected values through candidate frame access.
For new coding work, the public API supports
`coding_harness.run_experiment(..., evaluator=independent_code_grader.evaluate_code)`;
this must be an explicit argument because its default evaluator is already bound.
It requires an authorized SSH host with the pinned ARM64 Python container image
and owner-scoped cleanup qualification. `coding_harness.py` and
`run_coding_benchmark.py` CLIs still default to the original grading authority;
there is currently no turnkey portable hardened coding CLI.

## Standalone runs on your endpoint (these commands generate model calls)

Replace `OWN_MODEL` and the endpoint with your compatible served alias/address.
The client uses OpenAI chat completions plus `chat_template_kwargs.enable_thinking`;
record provider differences rather than assume equivalent reasoning or seeds.

```sh
.venv/bin/python harness.py --method direct --agents 1 --model OWN_MODEL \
  --endpoint http://127.0.0.1:8000/v1 --thinking --puzzle '1,2:3' \
  --max-tokens 8192 --max-calls 1280 --max-completion-tokens 32768 \
  --timeout 210 --seed 1 --events runs/own-arithmetic.jsonl
task_id=$(.venv/bin/python -c 'import json; print(next(t["id"] for t in json.load(open("datasets/csp-v1/tasks.json"))["tasks"] if t["split"] == "development"))')
.venv/bin/python csp_search.py --split development --task-id "$task_id" \
  --arm sequential --model OWN_MODEL --endpoint http://127.0.0.1:8000/v1 \
  --max-calls 16 --max-tokens 512 --timeout 210 --seed 1 \
  --events runs/own-csp.jsonl
```

These single-case commands have request limits/timeouts, not the study's 180s whole-case
controller. They are new experiments, not a replay of frozen results.
`fleet.sh`/`connect.sh` operate the original hardware and are not deployment tools
for an arbitrary endpoint.

## Replay fresh-program confirmation without running candidate code

The published fresh confirmation includes all 768 grade records, the 96 graphs
and all eight frozen source copies. This command hashes source bytes and checks
returned assignments; it never imports or executes those candidate programs,
contacts a model, or launches a container:

```sh
.venv/bin/python - <<'PY'
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
PY
```

This reproduces finite stored outcomes and the graph/training-seed bootstrap.
It does not rerun the CPU solvers or authenticate the original child process.
Original 12-graph outcomes remain separate. Full audit snapshots retain original
absolute paths and require the original study environment; this portable command
uses only the public evidence copies.

## Study-bound orchestration and published archive

`run_csp_search.py`, `program_search.py`, `confirm_coding.py`, `run_references.py`,
`run_program_confirmation.py`, `report_program_confirmation.py --run`
and `report_completed_studies.py --run` require original study receipts/gates;
a fresh checkout cannot execute those complete pipelines. Do not fabricate gates.
The [published evidence archive](EVIDENCE_RELEASE.md) contains exact orchestration sources, source hashes, canonical ledgers/receipts and completed exports. Original absolute paths and admissions remain provenance rather than portable launch commands. Download and verify the release manifests before using archived evidence.
