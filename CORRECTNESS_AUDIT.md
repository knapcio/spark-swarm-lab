# Independent verifier and corpus audit

The arithmetic verifier and stored coding expected values pass the checks below. The coding audit also reproduces **two ways an adversarial program can forge a passing grade**, plus an ordinary test-coverage gap. These findings do not rewrite any original result. Coding scores remain outcomes under the disclosed frozen grader; independent confirmation is pending.

All work here is offline. No retained model-generated program was executed, no model API or Spark/container call was made, and no frozen method, grader, dataset or protocol was changed. The exact trusted source comes from `cbcde299716b7842536b008880a089590e9816f8`; the audit loader checks git blobs and also works without the private producer worktree.

## Arithmetic

An independent integer subset-DP solver finds an existence witness for **all 32 tasks**: eight development and 24 evaluation. It never reads saved reference witnesses. Each expression is independently replayed with `Fraction`, checking strictly positive integer intermediates, exact target equality and leaf multiplicities against the selected input indices. The largest search used 1997 operand-pair combinations; this does not prove minimum solution length or matched difficulty.

Exhaustive small-state tests compare the actual frozen transition function against a separate evaluator for **13,952 actions**, over all ordered states of length 2–4 with entries 1–4. Tests also cover swapped commutative operands, consumed duplicates, remaining-value order, zero/negative/fractional intermediates, division by zero, bool/float/string/out-of-range indices, extra/missing fields, unsupported operators and malformed proposals. A raw success claim without target presence does not pass the verifier.

## Coding expected values and negative tests

Independent implementations written from the 24 task specifications agree with **405 cases: 48 public examples plus all 357 private feedback/holdout cases**. No stored expected value disagrees with these implementations. This is finite differential evidence, not a correctness proof over each function's entire domain.

The audit checks wrong values, omitted/duplicated/reordered outputs, exact bool/int/float/list types, exceptions and input postconditions. Of 96 generic task/mutation combinations, 90 cause an effective wrong output and are rejected; six are inapplicable because the transformation does not change the relevant outputs. One plausible semantic mutant per task is also tested: **23/24 are rejected by at least one private phase**. The survivor is important:

```python
def balanced_brackets(text):
    return all(text.count(a) == text.count(b)
               for a, b in [('(', ')'), ('[', ']'), ('{', '}')])
```

This counts-only implementation passes **9/9 feedback and 9/9 holdout cases**, although `([)]` must be false and it returns true. That counterexample is already a public example. Public examples are provided to the model but are not included in the original grader's private test phases. The defect is missing nesting/order coverage in that finite private sample, not an incorrect stored expected value. The original corpus remains unchanged. Later confirmation must report original feedback, original holdout, public examples and new posthoc robustness probes in separate columns.

Metamorphic tests additionally check idempotent deduplication, duplicate-insensitive range compression, prefix/window relations, four rotations, flatten-depth composition, Unicode/ASCII boundaries, multiplicity, earliest ties and simultaneous edit coordinates. Seven trusted reference implementations are compared with independent oracles on 100 additional generated inputs each. The [test receipt](results/correctness-audit-20261115/offline-tests.json) records **63 passing offline tests**, including 13 new audit tests. Some passing tests intentionally reproduce known vulnerabilities; they do not mean those vulnerabilities are fixed.

## Grade-integrity boundary

The old grader executes candidate source and trusted test comparison inside one Python interpreter. Container isolation protects the host but does not hide oracle values from that candidate. Two deliberately authored, tiny candidates reproduce false passes using the **exact frozen trusted RUNNER**:

1. Reading `sys._getframe(1).f_locals['case']['expected']` returns each expected answer without implementing the requested function.
2. Writing a forged `{"status":"passed",...}` document to inherited protocol file descriptor 3 and exiting bypasses function evaluation and comparison entirely.

Both yield a nominal 3/3 pass locally. The [receipt and minimal source](results/correctness-audit-20261115/grader-risk-reproductions.json) record Python 3.14.6 and the pinned RUNNER hash. These are local reproductions, not a new remote container validation. A further check confirms input equality observes final state only: append-then-pop is not detected as temporary mutation. Side-effect/purity observations are not authenticated execution provenance.

The separate [independent grader](independent_code_grader.py) keeps expected values in the trusted outer parent and supplies only source/function and call arguments to the candidate child. Its outer comparator alone assigns grades. It is a new confirmation tool, not a silent change to the frozen benchmark. Child-reported values, exception names and input-after snapshots remain observations; arbitrary interpreter tampering cannot establish a universal purity guarantee. Actual independent regrading must wait until the loaded-throughput phase finishes.

## What was observed in retained programs

Static triage covers **1008 retained coding trace files, 1107 distinct source texts**, including 30 syntax-invalid texts; model code is never executed by this scan. The [audit](results/correctness-audit-20261115/audit.json) includes every trace hash and source index. It checks imports, frame/global access, dynamic execution, file/protocol manipulation and sensitive strings. The only flag is a normal `__import__('re').findall(...)` expression in a natural-sort candidate, manually inspected as unrelated to grade forgery.

The [selected-program index](results/correctness-audit-20261115/selected-primary-scan-index.json) covers all 324 primary coding cases: 323 selected source artifacts plus one no-candidate case. All 18 selected balanced-bracket sources were inspected statically; none calls `count`. **No obvious historical exploitation was observed.** Absence of these indicators does not rule out obfuscation or establish correctness outside the finite tests. Independent external comparison of the frozen selected programs is still necessary.

## Oracle exposure and future experiments

The now-public repository tracks hidden-test and reference-witness files. Prior completed-cohort prompt/selection audits found no such inputs supplied to the serving model, and the closed serving requests had no repository/tool access. Publication is nevertheless distinct from secrecy. Same-interpreter grading exposed its oracle during evaluation even without prompt leakage.

Self-improvement or genetic selection must not optimize against an evaluation set and then describe that same set as untouched confirmation. Use new development/probe data for selection and a newly frozen, untouched evaluation set for later claims. Preserve this historical corpus, all negative outcomes and original scores.

## Reproduction

```sh
python3 -m unittest test_correctness_audit test_harness test_sandbox_code test_coding_harness
python3 reproduce_grader_risks.py --output /tmp/grader-risks-new.json
python3 correctness_audit.py --output /tmp/correctness-audit-new
```

The full audit pauses if the local pipeline state has entered its automatic throughput window. Its output directory must be new. The [manifest](results/correctness-audit-20261115/manifest.json) binds final reports, scripts, tests and the manual flag assessment by SHA-256. No raw benchmark artifact is edited.


## Plan-first independent confirmation

[confirm_coding.py](confirm_coding.py) prepares all **324 primary coding cases / 323 selected artifacts**. Exact source/function/phase/test-chunk/grader/image caching reduces 1292 logical phase references to **824 unique grading jobs** across 206 source/function pairs. Identical artifact reuse is explicit; it is not an independent seed replication or a method-latency experiment.

The four named phases are `original_feedback`, `original_holdout`, `public_examples` and `posthoc_robustness`. The first two are new outer-parent grades of the original partitions, not replacements for historical grades. New probes are posthoc, derived from independent specification oracles, and include incorrect bracket order/nesting; they are not called a newly untouched holdout. One no-candidate row remains present with unobserved grade counts.

Default invocation prints a plan and performs no remote work. `--run` first calls the shared `reference_worker.verify_gate(HERE)` and fails closed until the final 45-cohort throughput receipt, original 20-development-cohort receipt, primary+solo completion, ledger/source identities and all linked hashes verify. It then validates frozen task/private/index/trace/source hashes. Four persistent host slots each run one CPU grader at a time, with at most 128 tests per call, complete phase/report provenance, explicit cache references and a global halt on infrastructure failure. Expected values stay in the outer grader. Partial/unknown results stay distinct, and final source hashes are checked.

```sh
python3 confirm_coding.py
# Only after the full throughput gate has passed; root supervises the actual run:
python3 confirm_coding.py --run --output runs/independent-coding-confirmation-v1
python3 -m unittest test_confirm_coding test_independent_code_grader
```

The [published plan](results/coding-confirmation-plan-20261115/plan.json) and [22-test offline receipt](results/coding-confirmation-plan-20261115/offline-tests.json) are preparation only. No confirmation container, model call or remote smoke was launched for this plan. JSON and CSV outputs will keep the four phases separately named, preserving candidate-resource errors, cleanup evidence and any incomplete jobs. Original benchmark artifacts are read only.

## Subsequent live qualification and transport amendment

At the idle boundary after the original throughput attempt stopped, the new outer-parent grader passed [live qualification](results/independent-grader-qualification-20261115/qualification.json) on the Sparks: six authored pass/wrong/frame-access/grade-forgery/timeout/kernel-OOM checks, plus all **405 trusted examples and private cases in 72 phase containers**. Every owned container was cleaned up on all four hosts. This executed trusted references and deliberately authored negative fixtures, with **zero model calls and no retained model-candidate execution**. The [publication manifest](results/independent-grader-qualification-20261115/manifest.json) preserves the exact receipt bytes. It validates this finite control set, not universal tamper resistance or functional correctness.

The [transport-only amendment](TRANSPORT_TIMEOUT_AMENDMENT.json) separates HTTP waiting time from the unchanged task deadline. The [refreshed confirmation plan](results/coding-confirmation-timeoutguard-plan-20261115/plan.json) has the same 324 cases, 323 artifacts and 824 grading jobs; only its gate-module source pin changed. The historical preparation plan remains intact. Actual candidate confirmation still waits for all 45 fresh timeout-guarded throughput cohorts.
