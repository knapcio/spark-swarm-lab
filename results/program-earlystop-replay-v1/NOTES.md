# Posthoc early-stop trace replay

This counterfactual was specified after seeing original and fresh-confirmation outcomes. It was not executed as an early-stop run and is not new independent quality evidence. Sequential stops after a fully scored proposal; independent4 stops only after all four model responses and all sixteen development assessments in the batch complete. No already-dispatched sibling is counted as saved. If no 4/4 development success occurs, all sixteen calls and the actual best source are retained.

| Arm | Seed | Calls retained | Calls prospectively not dispatched | Same frozen source | Observed prefix client input / output | Actual prefix CPU development grades |
|---|---:|---:|---:|---|---:|---:|
| independent4 | 1 | 4 | 12 | yes | 11116 / 5483 | 12 |
| independent4 | 2 | 4 | 12 | yes | 11116 / 5838 | 8 |
| independent4 | 3 | 4 | 12 | yes | 11116 / 3061 | 16 |
| independent4 | 4 | 8 | 8 | yes | 29281 / 8978 | 16 |
| sequential16 | 1 | 1 | 15 | yes | 2779 / 773 | 4 |
| sequential16 | 2 | 16 | 0 | yes | 74507 / 26595 | 44 |
| sequential16 | 3 | 16 | 0 | yes | 74530 / 27459 | 60 |
| sequential16 | 4 | 16 | 0 | yes | 72564 / 25512 | 64 |

All eight frozen selected-source SHA values are identical. Across the original128 model calls, this rule retains 69 and prospectively avoids dispatching 59. Existing fresh96 outcomes apply to these same source bytes, not to a newly sampled training run. A shared seed does not guarantee a new run reproduces the observed trajectory.

Prefix client tokens are measurements from the already executed full traces, not prospective server-token savings. CPU counts include only actual development grader calls, excluding parse skips; the unchanged evaluation grades are separate. No server-token savings, GPU-time savings, latency, billed cost or new-run quality is estimated. Observed all-development CPU grade counts are retained in the CSV.
