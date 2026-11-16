# Frozen adversarial API-format qualification

The 24-element probe passed (110 output tokens, stop). The 64-element probe returned HTTP200 but reached its512-token cap with an unfinished JSON object and a long whitespace prefix after the assignment key. Both responses report zero reasoning tokens. The controller stopped after this failure: the third critique probe and the84-case graph-quality cohort were not executed. All four model endpoints remained healthy/idle; source and serving configuration were unchanged.

These prompts deliberately requested ONE element while the schema required24 or64. This tests a specific adversarial format/cap contract. The result is not evidence that the backend is generally unsupported, that normal aligned graph prompts would fail, or that a graph task was attempted. No extra probes, schema tuning, speculation disabling or runtime changes followed the failure.

Exact request bodies, derived seeds, raw parsed responses and their SHA256 values are retained in the two probe records. Fleet counters show104 prompt and622 completion tokens onSpark03, with zero increments on the other three endpoints. The driver is an exact provenance snapshot tied to original private receipts; it is not a portable fresh-checkout launch command. It performs no requests without --run.
