# Claude Fable 5.2 high-effort design consultation

The owner requested this model and full repository/workspace read access after the overnight study closed. The actual response model and all tool calls were checked. The adviser used only Read, Glob and Grep; its final recommendation is preserved verbatim in RECOMMENDATIONS.md. PROVENANCE.json records the request, actual identity, access, source hashes and provider-reported usage.

This is design advice, not experimental evidence of an improved Nemotron score. The original 24 evaluation tasks and their outcomes were visible to the adviser, so follow-up gains on them are exploratory tuning. Any new generalization test needs a separate frozen corpus. Stronger-model design consultation is distinct from a stronger-model runtime adviser; the latter is excluded from the proposed Nemotron inference runs.

The independent diagnostic confirms that missing answer content after 8,192-token reasoning truncation dominates retained failures, and that the stronger solo control hit its 180-second deadline before a fourth attempt. It does NOT yet establish the adviser's stronger claim that most truncated notes contain a valid solution. That needs exact mechanical replay; regex matches to the target are insufficient.

Several proposed validation statements need care: budget exhaustion is a legitimate failure outcome rather than an automatic infrastructure error; no-notes/cross-notes controls can still solve from the original task; a common token ceiling does not equal matched actual compute. Complete-domainCPU search and generated-solver execution must be reported separately from model-generated plans.

The recommendation's statement that no model was called means the adviser initiated no extra benchmark inference; this advisory conversation itself used the Claude API, as the provenance records. No original result/source/score is changed by this report. The earlier tools-disabled call was superseded when the owner expanded access; its usage remains unknown.

The subsequent [strict census](../nemotron72-strict-census-v1/NOTES.md) found one exact supported plan in 292 truncated responses; its narrow grammar also detectednone of 148 known accepted-content successes. Its low coverage cannot validate or refute usually-correct hidden notes. The pooled 1−(1−p)^4 calculation is descriptive, not a test of independent draws across heterogeneous tasks. These qualifications preserve the verbatim recommendation and motivate a prospective scribe experiment.
