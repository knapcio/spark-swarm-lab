# Nemotron follow-up: committing useful reasoning

The owner requested a new phase targeting 72/72 on the original arithmetic suite. Original source/results remain frozen at `study-20261116`; the new experiment has no quality results yet.

[Actual Claude Fable 5.2 high-effort review](results/fable52-advisory-20261116/README.md) · [independent failure diagnostic](results/nemotron72-diagnostic-v1/NOTES.md) · [strict reasoning census](results/nemotron72-strict-census-v1/NOTES.md) · [frozen protocol](FOLLOWUP72_DEVELOPMENT_PLAN.json) · [final precall audit](results/nemotron72-precall-audit-v1/FINAL_PRECALL.json).

## Why this experiment

The diagnostic confirms that answer emission is a useful hypothesis to test. Of 54 unsuccessful direct cases, 52 returned no answer after using 8,192 tokens in reasoning. The 23 unsuccessful E4 cases contain 91 such responses and one legal-but-unsuccessful emitted plan. All 27 unsuccessful sequential-refinement cases hit 180 seconds during the third request; none dispatched a fourth.

This does not prove that most truncated notes already contain a solution. The strict census detected one exact supported plan among 292 truncated responses, but its narrow grammar also failed to detect reasoning plans in all 148 known accepted-content successes. Unsupported text is not evidence of absent solutions.

The nine existing methods jointly solve 63/72 task/seed pairs in hindsight; somewhere across seeds they cover all 24 tasks. This is not a newly executed portfolio, a cached 72/72 result or a budget-matched comparison.

## Frozen development matrix

Eight original development tasks, three sampling seeds and seven variants give 168 cases. Each case has an 8,192-completion-token ceiling and 180-second controller deadline; HTTP timeout 210 seconds. A common ceiling does not match realized input, completion or server cost.

| Variant | First call | Conditional second call |
|---|---|---|
| index_original | Original indexed prompt, reasoning on, 8192 tokens | None |
| index_explicit | Indexed prompt plus explicit existing semantics,8192 | None |
| value_original | Literal operand values instead of indices,8192 | None |
| value_explicit | Literal values plus explicit existing semantics,8192 | None |
| scribe_full | Original indexed prompt, reasoning on, 7936 | Reasoning off, 256; all own notes |
| scribe_tail | Same first call | Reasoning off, 256; final 4096 Unicode characters |
| scribe_empty | Same first call | Reasoning off, 256; no notes, complete task retained |

The commit trigger requires parser result exactly None, received response, finish_reason=length and nonempty own reasoning. A parsed-but-invalid plan is not repaired. Notes come only from the same case/request, with explicit lineage and hashes. The no-notes control can legitimately solve from the original task; it is not expected to score zero.

All model-proposed moves pass the original exact arithmetic verifier. Value addressing deterministically selects available operand occurrences without swapping, correcting or searching. Leftovers are allowed, intermediate results must be positive integers, and success occurs when the target appears. No CPU puzzle search, witness file, per-task hint bank or stronger runtime adviser is used.

Scheduling uses 24 seven-variant blocks, one active case per node, with balanced host assignment and a barrier between blocks. This is recipe profiling rather than a fleet-throughput measurement. Controlled deadlines remain task outcomes; actual controller/transport/source/accounting faults stop new case admission while retaining partial evidence.

Select a new recipe only after the full audited development cohort and only if it strictly improves verified successes over the original index control. The fixed tie-break rules and cost-coverage requirements are in the protocol. No outcome-based reordering or retries are permitted.

## Source and validation

Code is frozen on branch `research/nemotron72-followup-v1`, tag `nemotron72-development-v1`, commit `638b9f335a7aa7011a9b7d122abcaa04f45e17a5`. [Source snapshot](https://github.com/knapcio/spark-swarm-lab/tree/nemotron72-development-v1) · [source receipt](results/nemotron72-preparation-v1/FROZEN_SOURCE.json).

The new Client subclass leaves the original harness byte-identical. The full 296-test suite passed, and independent review checked 192 baseline parity fixtures plus controller-fault, source-drift and matrix falsifiers. The controller stop defect found during review was fixed before any model calls.

Fresh serving admission remains separate from source review. Do not fabricate admission records or use historical native restoration scripts. The new driver is plan-only by default; complete execution requires the authorized fleet environment.

## Confirmation and claims

The old 24 evaluation tasks and their outcomes were visible during design. Any later 72/72 on them is finite exploratory benchmark tuning. A proposed new 16-development/48-evaluation corpus has not yet been generated or called; its fingerprints, sources, seeds, selected methods and budgets must be frozen before confirmation. Unsolvable tripwires belong in a separate control denominator.

The aim is repeatable verified solutions per actual cost, not merely a higher score obtained with unreported retries. Classical exhaustive search and generated-solver workflows remain separately labelled baselines.
