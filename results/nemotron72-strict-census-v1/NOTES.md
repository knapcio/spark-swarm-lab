# Strict reasoning census — already-seen exploratory analysis

The strong claim that truncated reasoning usually contains a correct plan is **not established by this census**. One of 292 retained length-truncated responses contains a complete, exact plan in the narrowly frozen grammar. The other responses cannot be classified as lacking a solution: 2,594 of 2,595 detected numbered blocks are unsupported formats. No unsupported format was added after observing outcomes.

| Method | Retained responses | Length responses | Strict verified reasoning plans | Originally failed cases with a strict plan |
|---|---:|---:|---:|---:|
| Direct thinking 8k | 72 | 52 | 0 | 0 |
| Two independent thinking plans | 110 | 72 | 0 | 0 |
| Four independent thinking plans | 144 | 94 | 0 | 0 |
| Strong sequential refinement | 123 | 74 | 1 | 1 |

Accepted-content replay agrees with all 449 retained outcomes, including 148 verified successes. None of those 148 successful content responses has a reasoning block recognized as a solution by this narrow grammar. This underlines its limited coverage; it is a strict positive-evidence detector, not an estimator of reasoning solution prevalence. The one detected solution belongs to an originally unsuccessful strong-solo case, and demonstrates a single recoverable instance without proving an automatic extraction method would improve future results.

The grammar admits only physically contiguous standalone `Move N: a op b = c` or `Step N: a op b = c` lines, numbered exactly from 1. Every equation in the entire block must be valid from the initial multiset in its stated order. Signed integer and fraction literals are parsed, but the frozen verifier still enforces positive integer intermediate values, distinct available operand occurrences, and original operation semantics. Later invalid steps reject the whole block even when an earlier step reached the target. No equations were corrected, skipped, reordered, combined across blocks, or searched. Blank-separated steps, markdown, explanatory suffixes, bare numbered lists and other forms remain unsupported or not detected.

`BLOCK_EVIDENCE.json` preserves exact reasoning substrings, zero-based end-exclusive character spans, request/agent/node/revision lineage and trace line references. Character positions are not token positions. The request SHA binds retained request-start JSONL metadata, not an uncaptured HTTP request body. No raw request-body reconstruction is claimed. Extracted solutions are audit evidence only and must not be inserted into future Nemotron prompts.

The 449 responses come from 654 dispatched requests. The 205 without retained responses remain unexamined: 178 belong to early-success-stopped E2/E4 cases and 27 to strong-solo deadline cases. These labels do not prove backend cancellation or zero work. No missing text was recovered or inferred. Original scores remain direct 18/72, E2 36/72, E4 49/72 and strong solo 45/72.

`GRAMMAR.json` was written and source-hashed before the corpus pass. Twenty-two authored tests cover exact replay, multiplicity/reuse, noncommutative order, false arithmetic, negative/fraction/zero intermediates, division by zero, unsupported chains, missing/reordered/skipped steps, invalid continuation after success and isolated hypothetical equations. `CHECKS.json` records a fresh exact-span/source-hash readback. Paths in the records are provenance in the original workspace, not portable reproduction commands. Running the source requires the original frozen verifier and diagnostic inputs and refuses to overwrite census outputs.
