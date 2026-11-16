# bugbench: finding and fixing planted bugs in projects larger than one context

Status: **design + offline prototype (3 projects, 9 cases)**. No model has been
run on it. Nothing here is a result. The Docker grading adapter is implemented
and tested offline with a fake `ssh`; it has not yet been run against a real
host.

A third batch of three projects (`tally`, `quarry`, `trellis`, 9 more cases,
all author-reviewed only) was added on 2026-11-16 with the same conventions;
it is listed below the prototype rows in each table.

| Project | Domain | Modules / lines / ~tokens | Cases (easy / medium / hard) |
|---|---|---|---|
| `stockroom` | warehouse ledger, FIFO lots, orders, journal DSL | 10 / 1,413 / 14.2K | tier boundary / snapshot alias / rollback order |
| `inkwell` | text template engine: lexer, precedence parser, filters, includes, autoescape | 10 / 1,411 / 13.4K | round half-even / `and`-`or` precedence / line drift after whitespace trim |
| `agenda` | calendar: recurrence rules, cancel/move/split, free slots, reports, schedule DSL | 8 / 942 / 10.6K | free-slot grid default / weekday order contract / split count after cancellation |
| `tally` | double-entry bookkeeping: chart and ledger, closed periods, invoices/credit notes with per-code VAT, payments with early discounts, prepayments, reports, script DSL | 10 / 1,219 / 13.6K | discount last day / VAT rounded per line / rejected discounted payment not undone |
| `quarry` | SQL engine over in-memory tables: lexer, precedence parser, typed tables with keys, joins, 3-valued logic, grouping, ordering | 10 / 1,319 / 14.0K | DESC tie order / right-associative `-` and `/` / failed INSERT leaves keys |
| `trellis` | package resolver: semver with pre-releases, caret/tilde constraints, backtracking resolver, lock files, install order | 10 / 923 / 9.9K | caret on 0.0.x / install-order tie-break / requirement leak on backtracking |

## 1. Why this benchmark

The arithmetic and function-level coding tasks in this repository are mostly
solved, and every task there fits into a single prompt. In bugbench each task is
a complete multi-module Python project, bigger than one Nemotron call can read.
The prototype packages are 10.6K–14.2K tokens, plus about 2K of tests and README,
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
  projects/<project>/             stockroom, inkwell, agenda
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
| Ordering without concurrency | FIFO/LIFO swap, unstable sort, wrong insert position | (stockroom b3 is also an ordering bug) |
| Wrong tie-break | `>` vs `>=` on equal scores, ascending vs descending secondary key | planned |
| Unit / rounding | per-line vs per-total rounding, wrong rounding mode, cents vs units | `inkwell-b1-round-half-even` (easy) |
| Wrong default / config | default argument, missing fallback branch | `agenda-b1-slot-grid-default` (easy) |
| Cross-module contract | caller assumes sorted, inclusive or immutable input that the callee does not guarantee | `agenda-b2-weekday-order` (medium) |
| Parser / lexer | escape handling, token boundary, precedence, line-number tracking | `inkwell-b2-and-or-precedence` (medium), `inkwell-b3-trim-line-drift` (hard) |
| Semantic bookkeeping | a count or total computed under the wrong documented definition | `agenda-b3-split-cancelled-count` (hard) |

Case summaries for the two newer projects:

- `inkwell-b1`: the shared quantize helper uses `ROUND_HALF_EVEN`, so
  `12.345|number(2)` prints 12.34 (12.355 is right). Probes cover `round`,
  `number` and `percent`; fixing only `number` fails `round`.
- `inkwell-b2`: `and` and `or` share a precedence level, so
  `a or b and c` groups as `(a or b) and c`; `a and b or c` is unaffected.
- `inkwell-b3`: the lexer advances its line counter by the newlines of the
  whitespace-trimmed text, so every error after a `{%-`/`-%}` that ate
  newlines reports a too-small line. Output is correct. The symptom surfaces in
  parser, strict-undefined and include errors (2 hops from the lexer).
- `agenda-b1`: `free_slots` defaults to a 30-minute grid instead of the
  documented 15. Probes also cover `first_common_slot` and the `free` command,
  so patching one caller fails.
- `agenda-b2`: weekly weekdays are de-duplicated but not sorted, so
  `Rule.starts` yields out of order and `count`, `until`, `between` and
  `is_start` (which assume chronological order) go wrong. Sorting in the
  calendar listing hides the order but still fails every target.
- `agenda-b3`: `Calendar.split` counts only non-cancelled occurrences before
  the split point, against the documented rule that cancelled occurrences
  still count. Needs a repeating event, a cancellation before the split and
  a split; the old series loses a session and the new one gains one.

Case summaries for the third batch:

- `tally-b1` (easy, boundary): the early payment discount uses `on <
  discount_date`, so a payment on the last discount day is only partial.
  Probes use two different terms and the API, reports and script language.
- `tally-b2` (medium, rounding): VAT is rounded per line and then summed
  instead of once per VAT code (227.50 at 23 % gives 52.32, not 52.33).
  Symptom in invoice totals, the VAT report and the trial balance (2 hops).
  Computing VAT only inside `Invoice` fails the direct `tax_summary` probe.
- `tally-b3` (hard, error path): the undo after a failed posting reverses the
  payment but adds the early payment discount again. Needs a discount-earning
  payment rejected for a closed period; afterwards the invoice has lost its
  discount and the subledger disagrees with account 1100. Posting before
  settling passes; dropping the "discount once" check fails.
- `quarry-b1` (easy, tie-break): DESC is implemented as ascending sort plus
  `reverse()`, which reverses ties, and a DESC first key reverses the order of
  later keys. "Reverse, sort, reverse" passes.
- `quarry-b2` (medium, precedence): the precedence-climbing loop recurses with
  `prec` instead of `prec + 1`, so equal-precedence operators group to the
  right (`10 - 4 - 3` is 9). Associative chains are unaffected. Keeping right
  recursion for "associative" operators fails (`a * b / c`).
- `quarry-b3` (hard, error path): a multi-row INSERT that fails after its first
  row leaves the earlier rows' keys in the key index; a retry raises
  `DuplicateKey`. UPDATE and DELETE rebuild the index (decoy). Rebuilding the
  index at the start of `insert` passes.
- `trellis-b1` (easy, boundary): `minor > 0` became `minor >= 0` in the caret
  expansion, so `^0.0.3` allows `<0.1.0`.
- `trellis-b2` (medium, tie-break): packages that become ready during the
  topological sort are appended instead of inserted alphabetically. The order
  stays valid, only the documented tie-break breaks. Re-sorting passes.
- `trellis-b3` (hard, aliasing): the search state copies the requirement dict
  but shares its lists, so an abandoned candidate's requirement on an already
  required package leaks into later attempts (older versions or false
  conflicts). Building new lists in `_add_dependencies` passes.

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

**Probe strength** is measured with the `mutants` command
(`mutation_score`): every single-site mutant of the clean package under 28
operators (comparison flips, `and`/`or`, `[0]`/`[-1]`, `±1`, removed `.copy()`,
`True`/`False`, `sorted`→`list`, removed `not`, `min`/`max`, `break`/`continue`,
`lstrip`/`rstrip`, `is None`, rounding mode, and so on). Mutants that change only
comments, docstrings, string literals or f-strings are skipped, because
exception messages are not graded. A mutant is killed when any probe
observation differs or the child fails. Survivors need human review.

| Project | Mutants | Killed | Survivors reviewed |
|---|---|---|---|
| `inkwell` | 302 | 272 (90%) | 17 `frozen=True`→`False` (immutability is not observable through the documented API); 12 equivalent or reachable only with input rejected earlier (e.g. `index < best` for distinct openers, `targets[0]`/`[-1]` with one target); 1 real gap: `{#-#}` (empty comment with a dash) trims differently, undocumented |
| `agenda` | 317 | 293–294 (92–93%) | 2 `frozen`; 21 equivalent (9 `[0]`→`[-1]` on one-element lists, `sorted(set(ints))`→`list(set(ints))` which CPython already orders, zero durations rejected by `Interval` anyway, ...); 1 probabilistic: `sorted`→`list` of a shared-attendee set is killed only when the hash seed orders the set non-alphabetically |
| `stockroom` | 172 | 140 (81%) | 11 `frozen`; most others are unprobed type-validation branches (`bool`/`str` quantities, wrong-currency costs). The earlier ad-hoc count (92/95 of 114) used a narrower operator set |
| `tally` | 309 | 293 (94.8%) | 16, all reviewed as equivalent: 8 `frozen`/`eq` flags, 2 `seq ± 1` (only relative order is used), `break`→`continue` when nothing is left to allocate, 3 unreachable script length bounds, 2 `[0]`→`[-1]` on one-argument commands |
| `quarry` | 333 | 310 (93.1%) | 23, all reviewed as equivalent: 9 `frozen`, 3 defaults always passed explicitly, 8 `[0]`→`[-1]` on one-element lists or grouped columns, 2 sign tests with a zero dividend, 1 exception-message-only change |
| `trellis` | 208 | 193 (92.8%) | 13 equivalent (4 `frozen`/field flags/defaults, a one-element index, 6 sorts whose result is sorted again or already sorted, `break`→`continue`, an `or`→`and` that ends in the same error); 1 real gap: the `MAX_STEPS` limit is not probed (2 mutants) |

For the two newer projects, about 99% of behaviour-changing, non-equivalent
mutants are killed. Edge probes were added after the first run (inkwell 78%→90%,
agenda 82%→93%), before any case was frozen for evaluation. Stockroom probes
were left unchanged; add type-validation probes before using it for evaluation.

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
  Pinned for the newer projects: a hand-written half-up quantizer (inkwell b1),
  lowering `or` instead of raising `and` (b2) and deriving lines from source
  offsets (b3) pass; a `number`-only rounding fix fails `round`. In agenda,
  `step=None` → 15 (b1) and sorting inside `Rule._dates` (b2) pass; passing
  `step=15` from callers only, sorting the calendar listing, and fixing only
  the old series' count after a split all fail.
- **Defects outside a function.** `inkwell-b2` lives in a module-level
  precedence table. Its gold function is `inkwell/expr.py::<module>`, and
  `gold.claim_aliases` lets a localization claim name `PRECEDENCE` or
  `ExpressionParser._binary`.
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
   to a fresh `python3 -I -S -c CHILD`, locally or in the container (below).
   **Expected values are never sent**, and tests check the payload keys and
   contents for both backends. The child writes the files into
   its own temporary directory and imports the package. Before each probe it
   purges the package from `sys.modules`, then runs the probe under a per-probe
   `SIGALRM` deadline (default 5 s). It returns only observations, as values,
   exception type names or timeouts, on a duplicated stdout descriptor while
   candidate stdout and stderr go to `/dev/null`.
4. The **outer parent** compares observations with `expected.json` and reports
   `status` (`passed`/`failed`/`invalid_patch`/`timeout`/`error`),
   `failure_kind`, `provenance`, `hidden`/`target`/`regression` counts, broken
   regression probes, the import error, timed-out probes, execution metadata,
   duration and payload hash. `passed`/`failed`/`timeout` are candidate
   outcomes (`failure_kind` e.g. `candidate_probe_failure`, `candidate_oom`,
   `candidate_signal`, `candidate_runtime`, `candidate_protocol`);
   `error` means the grading infrastructure failed (`provenance:
   infrastructure`) and the patch must be re-graded, never scored.

`run_public_tests` is the only execution feedback agents may receive. It runs
the visible tests on a patched copy through the same child. Because public
tests pass on the buggy tree, this feedback cannot reveal the bug. It only
catches patches that break documented, visible behaviour.

**Docker executor (implemented, offline-tested).** `DockerExecutor(host)`
mirrors `sandbox_code.py`: `ssh -o BatchMode=yes -o ConnectTimeout=10 -- host
docker run --pull never --runtime runc -i --network none --read-only --cap-drop
ALL --security-opt no-new-privileges --pids-limit 64 --memory 256m
--memory-swap 256m --cpus 1 --user 65534:65534 --tmpfs
/tmp:rw,noexec,nosuid,nodev,size=16m ... python@sha256:c61c… -I -S -c CHILD`
with the payload on stdin. The image is pinned to the same digest as
`sandbox_code.py` (a test checks it). The command has no `--rm`. Each run gets
a unique name and two owned labels (`swarm-lab.code-owner=swarm-lab-bugbench-eval`,
`swarm-lab.code-task=<uuid>`). After the run, including a controller timeout,
the container is inspected only if both labels match, then removed by a
label-guarded `sh -c` cleanup. Classification:

- OOM-killed → `candidate_oom`;
- controller timeout with container evidence → `candidate_timeout`;
- exit ≥ 128 → `candidate_signal`; other exits → `candidate_runtime`;
- malformed or oversized output, or the wrong number of observations →
  `candidate_protocol`;
- ssh 255 or `OSError` → `ssh_infrastructure`; docker 125/126/127 or a state
  `Error` → `docker_infrastructure`;
- failed or foreign-label inspection → `inspection_infrastructure`;
- failed cleanup → `cleanup_infrastructure`, which keeps
  `original_failure_kind` and discards the result.

`grade(..., executor=DockerExecutor(host))`,
`run_public_tests(..., executor=...)` and the CLI `--docker-host` use it. The
patched code still shares an interpreter with the trusted probe runner inside
the container, exactly as in local mode: it can read the probe source, but no
expected value is ever sent. A fake `ssh` that runs the real CHILD locally tests
success (identical grades to local mode), timeout, OOM exit 137, signal,
cleanup failure, malformed output, ssh/docker/inspection failures and host
validation. Local mode remains for authored fixtures and offline development
only. **Grade model-generated patches only with `--docker-host`.**

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

| Item | stockroom | inkwell | agenda |
|---|---|---|---|
| Package | ~14.2K (10 modules, 1,413 lines) | ~13.4K (10 modules, 1,411 lines) | ~10.6K (8 modules, 942 lines) |
| Largest module | `journal.py` 256 lines, ~2.3K | `filters.py` 259 lines, ~2.3K | `calendar.py` 227 lines, ~2.7K |
| Public tests + README | ~2.1K | ~2.0K | ~2.2K |
| Repo map | ~3.2K | ~2.7K | ~2.0K |
| Bug reports | 0.2–0.3K | 0.2–0.4K | 0.2–0.3K |

| Item (third batch) | tally | quarry | trellis |
|---|---|---|---|
| Package | ~13.6K (10 modules, 1,219 lines) | ~14.0K (10 modules, 1,319 lines) | ~9.9K (10 modules, 923 lines) |
| Largest module | `ledger.py` 237 lines, ~2.5K | `parser.py` 254 lines, ~2.8K | `constraint.py` 151 lines, ~1.6K |
| Public tests + README | ~2.6K | ~2.4K | ~2.0K |
| Repo map | ~2.7K | ~2.0K | ~1.9K |
| Bug reports | 0.2–0.5K | 0.2–0.3K | 0.2–0.3K |
| Hidden probes | 28 | 28 | 27 |

Compress the repo map to ~1.5K for fixers by dropping dunders and errors.

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

1. **Development (now possible with this prototype)**: 9 cases, a few seeds.
   Calibrate the patch format (full-file vs search/replace), thinking budget,
   scout JSON schema and the repo-map size. Fix prompt bugs. Not reportable.
2. **Corpus**: 8 new projects × 3 cases = **24 evaluation cases** (8 easy, 8
   medium, 8 hard), plus the prototype cases kept as development. `inkwell` and
   `agenda` may instead count as 2 of the 8 projects, if a frozen manifest says
   so before any model sees them; stockroom stays development. Each case
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

- **Prototype only.** It has three projects and 9 author-reviewed cases. The
  difficulty labels are guesses until calibrated. All three projects were
  written by one author (with model assistance) on the same day, so their
  style is more uniform than real code.
- **Authoring cost.** Each project is about 1.5K lines plus probes and review.
  24 cases need about 8 projects. Model-assisted authoring is possible, but it
  must be reviewed for originality and must not use DeepSeek or Nemotron
  outputs that later appear as evaluation inputs.
- **Hidden-suite adequacy.** `mutants` kills 90–93% of all operator mutants in
  the newer projects (about 99% after removing reviewed equivalents) and 81% in
  stockroom. A fix could still break unprobed behaviour, especially stockroom
  type validation. Report this limitation, and re-run `mutants` per project
  after any probe change.
- **Spec-entailment judgement** is human and fallible (see the snapshot
  example in §6). Review every target probe against the report and docs.
- **Full-file output cost** may push thinking-on responses into truncation.
  This is the main reason for the format-calibration cohort.
- **Local grading is not a sandbox.** The Docker executor is wired up but only
  tested with a fake `ssh`. Before the first model patch: one real smoke run
  per host (clean, buggy, OOM and timeout fixtures), and confirm that the
  pinned image's Python version reproduces `expected.json`. It was frozen
  with the local interpreter, and probes compare exact values.
- **Prefill load.** 100 concurrent requests with 6–7K-token prompts is a
  different serving regime from the earlier short-JSON qualification. Measure
  it before committing to a wall-time budget.
- **Interpretation.** Success on small synthetic projects does not establish
  general software-engineering ability. The benchmark measures bug localization
  and repair under a hard context limit.

## Prototype usage

```sh
cd apps/swarm-lab
python3 -m unittest discover -s bugbench -p 'test_*.py'      # 45 offline tests
python3 -m unittest bugbench/test_bugbench.py                # 52 grader/invariant tests after the third batch
python3 bugbench/bugbench_grader.py verify                     # case invariants (all 9 cases)
python3 bugbench/bugbench_grader.py mutants inkwell            # probe strength (~1 min per project)
python3 bugbench/bugbench_grader.py materialize stockroom-b3-rollback-order /tmp/case
python3 bugbench/bugbench_grader.py reference-patch stockroom-b3-rollback-order > fix.txt
python3 bugbench/bugbench_grader.py grade stockroom-b3-rollback-order fix.txt
python3 bugbench/bugbench_grader.py grade stockroom-b3-rollback-order fix.txt --docker-host Spark_01   # model patches
python3 bugbench/bugbench_grader.py selfcheck stockroom-b3-rollback-order fix.txt
python3 bugbench/bugbench_grader.py freeze stockroom           # deliberate re-freeze only
```
