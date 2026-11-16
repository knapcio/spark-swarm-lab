# Program-context reviewers: late exploratory results

Four stateless bottom-ranked program contexts reviewed top-ranked candidates.
Each training episode spent all16 calls:10 programs and6 plaintext critiques.
The original12 graphs and operator-known96 graphs are reported separately.

| Evaluation scope | Passed | Task-only95% interval | Crossed graph/training-seed95% |
|---|---:|---:|---:|
| Original12 graphs ×4 frozen programs |47/48 (97.9%)|93.75%–100%|87.5%–100%|
| Separate known96 graphs ×4 same programs |376/384 (97.9%)|96.35%–99.22%|92.97%–100%|

Intervals use5,000 bootstrap resamples, seed20261115. Task-only intervals
condition on these four frozen programs; crossed intervals additionally resample
four training-seed labels. Repeated graph/program outcomes are not independent
tasks. These finite suites do not prove general correctness. The96-graph suite
retains eight timeouts as failures; all384 cleanups passed, with no infrastructure
failure or unknown outcome. It made zero new model calls.

The historical independent4 arm also passed47/48 original and376/384 known-graph
outcomes. These are separate runs, not a randomized isolated estimate of the
reviewer's causal effect; they are not pooled here. Review training used64 calls,
290,793 input and66,718 output tokens versus the historical independent arm's
247,144 input and69,935 output. Known server/client token coverage is4/4 episodes.

The four-node review stage took214.822seconds, including endpoint drain and
three qualification containers. Its188 episode containers plus3 qualification
containers total191 actual executions;20 parse-skipped checks were not executed.
The separate384-grade CPU stage took288.705seconds, excluding historical training
and admission. Remote solver CPU time is unknown; wall time is not model-call work.

[Original12 report](original12/REPORT.md) and [known96 report](known96/REPORT.md)
include CSV outcomes, per-seed totals, training costs and exportable PNG/SVG
interval charts. Their manifests bind raw inputs, independent audits and derived
files. Original input/runtime/body interpretation follows the frozen source and
captured events; there was no wire-level request capture.

[Seed1 lineage](original12/seed1-lineage.svg) is a **posthoc figure selected by the
lowest training-seed label**, min(seed)=1, not by outcome rank and not a random or
representative sample. It retains all10 program and6 critique nodes and24 own-
parent/context/target/guidance edges, including unretained programs. Initial
program3 was selected for evaluation. The readable projection omits call, grade,
fitness and population nodes; the byte-identical detailed404-node/700-edge
independent audit is preserved in evidence. Its24 raw critiques are reconciled
and copied. Suggestions remain unverified; non-retention does not mean incorrect.

Reproduce the derived files in a new directory directly under `results/` by
copying `report.py` there and running it from the repository with the original raw run/audit inputs
available. Default execution is plan-only; `--run` reports original12, and
`--run --fresh-audit <absolute-audit-path>` reports known96 only after a complete,
hash-bound independent audit. Existing output directories are never overwritten.
