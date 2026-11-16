# bugbench: finding and fixing planted bugs in projects larger than one context

Status: **design + offline prototype (1 project, 3 cases)**. No model has been
run on it. Nothing here is a result.

## 1. Why this benchmark

The arithmetic and function-level coding tasks in this repository are mostly
solved, and every task there fits into a single prompt. In bugbench each task is
a complete multi-module Python project, bigger than one Nemotron call can read.
The prototype package is about 14K tokens, plus about 2K of tests and README,
against a prompt budget of about 7.5K. An agent therefore has to choose what to
read. Splitting reading, localization, fixing and review across agents becomes a
real design choice rather than a re-labelled ensemble.

The question stays the same as in the rest of the repository: at matched,
measured cost, do swarms of small agents fix more bugs than strong single-agent
baselines? DeepSeek V4.1 serves as an unmatched-compute reference.

## 2. Task format

A **project** is original, standard-library-only Python with 4–10 modules,
400–1,500 package lines, at most ~250 lines per module, and a README with the
business rules. It has its own visible test suite, which passes on every buggy
variant, and a hidden probe suite.

A **case** is a project, one or more planted mutations, and one public bug report.

```
bugbench/
  bugbench_grader.py            offline grader, materializer, CLI
  test_bugbench.py              offline tests of grader and prototype invariants
  projects/<project>/
    project.json                package name, editable globs, canary
    clean/                      reference project (agents never see it unmodified)
    hidden/probes.py            behavioural probes, no expected values      [hidden]
    hidden/expected.json        observations frozen from clean/             [hidden]
    cases/<case_id>/case.json   mutation, gold location, target probes      [hidden]
    cases/<case_id>/report.md   the bug report                              [visible]
```

Agent-visible bundle (`agent_bundle`, `materialize`): the buggy tree (all files,
including `tests/` and `README.md`), `REPORT.md`, a generated `REPO_MAP.txt`, the
list of editable paths and the patch-format instructions. The buggy tree is
derived on the fly by applying `case.json` mutations to `clean/`. That keeps the
diff minimal and makes the inverse of the mutation the reference fix. Nothing in
the bundle mentions probes, the canary, the gold location or the mutation. Tests
enforce this.

### Hint variant: (a) user-visible bug report, primary

| Variant | Verdict |
|---|---|
| **(a) user report**: steps to reproduce, expected vs actual, no file or function names | **Primary.** Realistic, and it pins down the intended behaviour, so one fix is uniquely implied. Localization stays non-trivial because the symptom usually surfaces in a different module than the defect (for example, a report symptom maps to a defect in `inventory.py`). |
| (b) failing public test output | Later **easier tier/ablation** only. A traceback names the failing call path and often the file, which mostly removes localization, the part where swarms could plausibly help. Use it as a control for how much of the difficulty is localization. |
| (c) no hint, find any bug | **Rejected for scoring.** "A bug" is ambiguous: design choices, undocumented edge cases and planted bugs are indistinguishable, and grading would need the hidden tests to define intent. It may later work as an exploratory audit task scored only by planted-bug recall. |

Report-writing rules: describe observable behaviour through the public API or
journal language; give exact numbers; name the documented rule being violated
when one exists; never name the defective file or function. Mention a nearby
case that behaves correctly when that helps exclude wrong hypotheses.

## 3. Bug taxonomy

| Class | Typical mutation | Prototype case |
|---|---|---|
| Off-by-one / boundary | `>=`→`>`, `range(n)`→`range(n-1)`, half-open vs closed ranges | `stockroom-b1-tier-boundary` (easy) |
| State mutation / aliasing | shallow copy, shared default, returning internal list | `stockroom-b2-snapshot-alias` (medium) |
| Error-path / rollback | partial update before raise, rollback in wrong order or position | `stockroom-b3-rollback-order` (hard) |
| Ordering without concurrency | FIFO/LIFO swap, unstable sort, wrong insert position | (b3 is also an ordering bug) |
| Wrong tie-break | `>` vs `>=` on equal scores, ascending vs descending secondary key | planned |
| Unit / rounding | per-line vs per-total rounding, wrong rounding mode, cents vs units | planned |
| Wrong default / config | default argument, missing fallback branch | planned |
| Cross-module contract | caller assumes sorted, inclusive or immutable input that the callee does not guarantee | planned |
| Parser / lexer | escape handling, token boundary, line-number off-by-one | planned |

Excluded: concurrency and timing bugs (non-deterministic grading), performance
bugs, security bugs, and anything needing network, files outside the tree or
wall-clock time.

## 4. Difficulty control

Each case records these axes in `case.json` and later analysis:

1. **Distance**: call-graph hops from the module where the symptom appears to
   the defective function (`call_hops_symptom_to_bug`). b1 = 0, b2/b3 = 2.
2. **Reachability**: the input sequence needed to trigger the bug. A single call
   is easy; a failed multi-line shipment that used up a whole lot is hard.
3. **Report specificity**: whether a documented rule is quoted and whether a
   correct neighbouring case is given.
4. **Decoys**: similar-looking code elsewhere (for example, sort keys in
   `reports.py`, or `_insert_lot` used correctly in `receive`).
5. **Public-test proximity**: whether visible tests exercise the buggy function
   on a non-triggering input. In all three prototype cases they do; that is
   realistic and discourages "the tested code must be fine".
6. **Project size**: modules and approximate tokens vs the per-call prompt budget.

Calibrate on development cases only. Run (i) DeepSeek with the whole repository
in context and (ii) a single Nemotron navigator. Aim for evaluation cases where
DeepSeek succeeds and the single Nemotron agent does not always succeed. A case
nobody solves, or everybody solves, carries little signal. Report per-difficulty
results and never retune a case after evaluation outcomes are known.

## 5. Planting bugs: mutation plus human review

1. **Author** the clean project, README rules, public tests and hidden probes.
   Freeze `expected.json` from the clean tree (`freeze`). This is an explicit,
   reviewed step that records the tree hash, probes hash and Python version.
2. **Generate candidates** two ways: operator mutants (comparison flips, slice
   bounds, removed `.copy()`, swapped sort keys, `insert`→`append`, rounding
   modes) and hand-written semantic mutations for the taxonomy classes
   operators miss.
3. **Filter automatically** (`verify`). A candidate must:
   - fail at least one hidden probe;
   - fail *exactly* the declared target probes, with no collateral regressions;
   - pass the public tests;
   - be fixed by its inverse (reference patch passes 27/27);
   - change at most a few lines inside one function, and be non-equivalent.
4. **Write the report** from the actual buggy behaviour. A test re-runs the
   report scenario and checks the quoted expected and actual numbers.
5. **Independent review** by someone other than the author: realism (would a
   person write this?), no tell-tale comments, report-to-spec entailment (§6),
   alternative-fix analysis, and difficulty labels. Record the reviewer in
   `case.json.review`. The prototype cases are author-reviewed only.

The prototype includes an ad-hoc measure of hidden-suite strength. There are
114 single-operator mutants of the clean package (comparison flips, `and`/`or`,
`[0]`/`[-1]`, removed `.copy()`, and so on). The probes kill 92. Of the 22
survivors, 17 only change docstrings and 2 are equivalent. That leaves
**92/95 (~97%)** of behaviour-changing mutants caught. The 3 real gaps are two
journal mutants for a backslash at the end of a line and a rejected zero list
price. Add this check as a reusable `mutants` command before scaling the corpus.

## 6. Ambiguity control

A fix counts if and only if **all hidden probes pass**. No string match to the
reference patch is required. To make that fair:

- **Target probes are entailed by report + documentation.** Every target probe
  checks behaviour that the report, README rules or a public docstring state.
  Example from the prototype: a probe checking that *mutating* a snapshot does
  not change inventory was removed. That reverse direction is not required by
  the report, and a correct copy-on-write fix would have failed it.
- **Generalization probes** use different numbers, products, currencies and
  entry points (direct API and journal), so special-casing the report example
  fails. Tested: hard-coding `quantity == 10` fails b1.
- **Regression probes** cover the whole project. Every buggy variant passes all
  of them, so any regression-probe failure is collateral damage from the patch.
- **Alternative fixes are allowed and tested.** The b2 copy-on-write fix in
  `_take` passes, as does a b3 "append then sort" fix in `restore`.
  Symptom-masking fixes fail on documented guarantees: a Store-only deep copy
  fails because `Inventory.snapshot` documents the same guarantee, and sorting
  inside `_take` fails because `Inventory.lots()` documents FIFO order. Both
  outcomes are pinned in tests and explained in `case.json.notes`.
- **Exceptions are compared by type only**, not message. Values use exact JSON
  types: int ≠ float ≠ bool, as in the existing coding grader.

## 7. Patch format: full-file replacement

```
=== FILE: stockroom/inventory.py ===
<complete new file content>
=== END FILE ===
```

Up to 3 existing editable files (`stockroom/*.py`). No new files and no edits to
tests or README. Text outside blocks is ignored, and one Markdown fence inside a
block is tolerated.

Why full-file replacement rather than unified diff, for small models:

- **No hunk arithmetic or exact context.** Generated unified diffs commonly fail
  on `@@` line counts, wrong context lines and whitespace drift. Each of these
  is a format failure, not a reasoning failure. This repository already learned
  the same lesson with JSON-escaped code: format errors masquerade as inability.
- **Plain text, no escaping.** The block markers survive any content, so no
  JSON or newline escaping is needed.
- **Bounded cost by construction.** Modules are capped at ~250 lines (≤ ~2.4K
  tokens). One rewritten file fits beside the reasoning within an 8K completion
  budget.
- **Mechanically checkable.** The grader converts every patch to a unified diff
  for records and metrics: lines changed, `diff_sha256`, functions touched via
  an AST diff, and an elision flag for patches containing
  `# ... rest unchanged` placeholders.

Known costs: output tokens (~2K per file, versus ~100 for a diff); the risk of
silent collateral edits, caught by regression probes and the diff-size metric;
and truncation when reasoning uses up the budget (a missing `END FILE` reports
"truncated output?"). A **format-calibration cohort** on development cases
should compare full-file with search/replace blocks before freezing, analogous
to the raw-vs-JSON calibration in `CODING_EXPERIMENT.md`.

## 8. Grading pipeline

`grade(case_id, patch_text)` in `bugbench_grader.py`:

1. Materialize the buggy tree in memory, then parse and validate the patch.
   Invalid patches get `invalid_patch` and are never executed.
2. Compute the diff, changed lines, touched functions (AST segment diff),
   gold-file and gold-function hits, and the elision flag.
3. Send `{mode, package, files, probes, probe_names, probe_timeout}` over stdin
   to a fresh `python3 -I -S -c CHILD`. **Expected values are never sent**, and
   a test checks the payload keys and contents. The child writes the files into
   its own temporary directory and imports the package. Before each probe it
   purges the package from `sys.modules`, then runs the probe under a per-probe
   `SIGALRM` deadline (default 5 s). It returns only observations, as values,
   exception type names or timeouts, on a duplicated stdout descriptor while
   candidate stdout and stderr go to `/dev/null`.
4. The **outer parent** compares observations with `expected.json` and reports
   `status` (`passed`/`failed`/`invalid_patch`/`timeout`/`error`),
   `hidden`/`target`/`regression` counts, broken regression probes, the import
   error, timed-out probes, duration and payload hash.

`run_public_tests` is the only execution feedback agents may receive. It runs
the visible tests on a patched copy through the same child. Because public
tests pass on the buggy tree, this feedback cannot reveal the bug. It only
catches patches that break documented, visible behaviour.

**Docker TODO.** `container_argv()` builds the same pinned ARM64
`python@sha256:c61c…` command with the isolation flags of
`independent_code_grader.py`: runc, no network, read-only root, `/tmp` tmpfs
16 MiB, 256 MiB memory with no swap, 64 PIDs, 1 CPU, UID 65534, dropped
capabilities, no-new-privileges. The payload is identical, so only the
transport changes. Ownership-labelled inspection, OOM classification and
cleanup should be reused from `independent_code_grader.py` when this is wired
up. Until then, local mode is for authored fixtures and offline development
only. **Model-generated patches must not be graded locally.**

## 9. Contamination and originality

- All project code, reports and probes are original, written for this
  benchmark, and not derived from an existing repository (`project.json` →
  `authorship`). Domain vocabulary is deliberately ordinary, but names, rules
  and numbers are bespoke.
- Hidden files carry a canary string (`BUGBENCH-HIDDEN-CANARY …`) so training
  corpora can be screened.
- Hidden material stays private until the frozen evaluation has finished. Once
  published, a case is **burned** for future headline claims and is replaced by
  fresh projects, not mutated variants of the same project.
- `expected.json` pins clean-tree and probe hashes; tests fail if either drifts
  without a deliberate re-freeze.
- Remaining risk: generic bug patterns (FIFO, tier boundary) are common in
  training data. Contamination of the *specific* code is controlled; familiarity
  with the *pattern* is not, and is arguably part of the skill measured.

## 10. Metrics

Primary:

- **Fix rate**: the selected final patch passes all hidden probes. Report it
  per case and per difficulty tier, with task-clustered bootstrap intervals
  (seeds nested in cases) and paired differences against the baseline arm.

Secondary:

- **Localization accuracy**: (i) an explicit claim (`{"file", "function"}`,
  scored by `score_localization`) made *before* any patch, top-1 file and
  function; (ii) whether the final patch touched the gold function. Alternative
  valid fix sites are listed in `case.json` and reported separately.
- **Target-pass without fix**: some target probes fixed but regressions broken,
  or overfit.
- **Regression-break rate**: patches that break any regression probe.
- **Invalid-patch rate** and **truncation rate**: format health.
- **Oracle gap**: whether any patch generated in the attempt would have passed,
  versus the selected patch. This separates generation from selection, as in
  the existing coding study. It requires grading every unique candidate after
  the selection is frozen, never feeding results back.
- **Cost**: model calls, prompt and completion tokens as reported by the server
  (missing usage charged at `max_tokens`), wall time, grader calls, and
  completion tokens per solved case.

## 11. Context budgets

| Item | Approx. tokens (prototype) |
|---|---|
| Package (10 modules, 1,413 lines) | ~14.2K |
| Largest module (`inventory.py`, 232 lines) | ~2.4K |
| Public tests + README | ~2.1K |
| Repo map (all signatures + first doc lines) | ~3.2K (compress to ~1.5K by dropping dunders/errors for fixers) |
| Bug report | 0.2–0.3K |

Per call: **prompt ≤ 7.5K, completion ≤ 8K** (thinking on, so reasoning and
answer share the cap), 16K window. A scout prompt (instructions 0.6K, report,
map, one module) is ≈ 6.5K. A fixer prompt (instructions, report, ≤ 1K notes,
two modules) is ≈ 6–7K. Fixers do not get the full map. Token counts here are
`len/3.6` estimates; real counts come from server usage.

## 12. Baselines (single agent)

All arms share prompts, budgets, the patch format and the same
`run_public_tests` self-check tool.

- **S1 Navigator.** One agent, sequential. Step 1 reads report + map and picks
  ≤ 2 files and a hypothesis. Each further step sees the report, its own notes
  (≤ 1K tokens, written by the previous call) and ≤ 2 requested files. It may
  either request other files or emit a localization claim plus a patch. After a
  patch it may run the self-check once and repair. Stops at a passing
  self-check or the budget.
- **S2 Navigator with repair**: S1 run to the full call budget of the swarm arm
  it is compared with. Sequential refinement was the strongest cheap control in
  the arithmetic study.
- **S3 Independent best-of-k**: k = 8 independent S1 chains with no
  communication. Selection: valid patch, then passing self-check, then the
  largest cluster of identical normalized diffs, then the earliest. This is the
  "independent ensemble" control that a swarm must beat to claim cooperation
  helps.
- **R DeepSeek V4.1 reference**: the whole bundle (≈ 20K tokens) in one prompt,
  one patch, one self-check repair. Different model, context and compute. It is
  a reference ceiling, not an equal-cost competitor.

## 13. Swarm policies

Budgets are per case; "calls" are Nemotron calls.

- **W1 Module sharding (map-reduce).** One scout per module (≈ 10) reads report,
  compressed map and its module. It returns JSON
  `{suspicion: 0–1, function, evidence ≤ 80 words, also_check: [file]}`. The
  aggregator ranks (file, function) by summed suspicion, with a tie going to
  more independent mentions. 4 fixers each get the top-2 modules and the top-3
  evidence notes, and produce patches. Selection is as in S3, then 2 reviewers
  vote on the top two distinct passing patches. ≈ 16–20 calls.
- **W2 Localization voting (crowd).** 16 scouts each see the report, the map and
  a random pair of modules (each module covered ≥ 3 times). Each casts approval
  votes for up to 2 (file, function) candidates. Borda aggregation picks the
  location, then 4 fixers patch it and 2 reviewers pick. Tests whether
  redundancy beats assignment. ≈ 22 calls.
- **W3 Shared findings board (blackboard).** Up to 3 rounds. In each round, 8
  agents read the board (≤ 12 entries, ≤ 1.2K tokens) plus one assigned
  module. Each posts a hypothesis with evidence, or endorses or refutes an
  existing entry; entries are ranked by endorsements minus refutations. After
  any round where the top entry leads by ≥ 2 votes, fixers start. Mirrors
  `SHARED_MEMORY.md`. ≤ 36 calls.
- **W4 Propose–review–repair.** 6 fixers (S1-style, 3 calls each) produce
  patches. Each unique patch gets 2 fresh reviewers who see only report, diff
  and the touched module, and return accept/reject with a reason. Each rejected
  patch gets one repair with the review text. The final pick is the most
  accepted patch with a passing self-check. Tests whether independent review
  catches overfit or collateral damage. ≈ 30–40 calls.

The common cap for every swarm arm and its matched S2 control is **48 calls,
256K completion tokens and 15 minutes wall time per case**. Prompt tokens are
recorded, not capped. Report actual usage. Equal agent counts are **not** equal
compute.

## 14. Recommended first experiment

1. **Development (now possible with this prototype)**: 3 cases, a few seeds.
   Calibrate the patch format (full-file vs search/replace), thinking budget,
   scout JSON schema and the repo-map size. Fix prompt bugs. Not reportable.
2. **Corpus**: 8 new projects × 3 cases = **24 evaluation cases** (8 easy, 8
   medium, 8 hard), plus the 3 prototype cases kept as development. Each case
   gets independent review and a frozen manifest with hashes before any
   evaluation call.
3. **Arms**: S2 (budget-matched sequential), S3 (independent-8), W1 (sharding)
   and W4 (review). W2 and W3 stay development-only until one of them shows a
   development win. Plus R (DeepSeek) once per case and seed.
4. **Scale**: 24 cases × 3 seeds × 4 Nemotron arms = **288 attempts**.
   - Expected mean of ≈ 35 calls and ≈ 3K completion tokens per call, so
     ≈ 30M completion tokens.
   - At an assumed 1.2–1.5K aggregate output tok/s on four replicas with
     6–7K-token prompts, that is **≈ 6–7 h**. This is below the 1.77K tok/s
     serving qualification because of longer prompts and prefill. Measure it in
     development.
   - Grading costs ≈ 0.5 s per patch locally, ≈ 2–3 s in a container, at most
     ~10 grades per attempt.
   - The DeepSeek reference (72 calls with ≈ 20K-token prompts) runs in a
     separate serving window.
5. **Protocol**: freeze a selection JSON as for the other studies (arms,
   budgets, prompts, seeds, case hashes, grader hash). Exactly one hidden grade
   is the score of the frozen selection; oracle-gap grades come after.

## 15. Risks and open questions

- **Prototype only.** It has one project and 3 author-reviewed cases. The
  difficulty labels are guesses until calibrated.
- **Authoring cost.** Each project is about 1.5K lines plus probes and review.
  24 cases need about 8 projects. Model-assisted authoring is possible, but it
  must be reviewed for originality and must not use DeepSeek or Nemotron
  outputs that later appear as evaluation inputs.
- **Hidden-suite adequacy.** The prototype kills ~97% of behaviour-changing
  single-operator mutants. A fix could still break unprobed behaviour. Report
  this limitation, and keep running a mutation-score check per project.
- **Spec-entailment judgement** is human and fallible (see the snapshot
  example in §6). Review every target probe against the report and docs.
- **Full-file output cost** may push thinking-on responses into truncation.
  This is the main reason for the format-calibration cohort.
- **Local grading is not a sandbox.** Wire `container_argv` up before any model
  patch is executed.
- **Prefill load.** 100 concurrent requests with 6–7K-token prompts is a
  different serving regime from the earlier short-JSON qualification. Measure
  it before committing to a wall-time budget.
- **Interpretation.** Success on small synthetic projects does not establish
  general software-engineering ability. The benchmark measures bug localization
  and repair under a hard context limit.

## Prototype usage

```sh
cd apps/swarm-lab
python3 -m unittest discover -s bugbench -p 'test_*.py'      # 29 offline tests
python3 bugbench/bugbench_grader.py verify                     # case invariants
python3 bugbench/bugbench_grader.py materialize stockroom-b3-rollback-order /tmp/case
python3 bugbench/bugbench_grader.py reference-patch stockroom-b3-rollback-order > fix.txt
python3 bugbench/bugbench_grader.py grade stockroom-b3-rollback-order fix.txt
python3 bugbench/bugbench_grader.py selfcheck stockroom-b3-rollback-order fix.txt
python3 bugbench/bugbench_grader.py freeze stockroom           # deliberate re-freeze only
```
