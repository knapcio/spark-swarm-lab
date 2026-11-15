# Prompt calibration: exact finishes versus legal actions

A bounded probe compared the current JSON-example ending with a schema-only
ending on one state, `[2,3,7,8]`, target 24. Everything preceding that ending,
including the system prompt, stayed unchanged. Four sequential batches used
old/schema/schema/old, 100 proposals each, four NemotronLightning DSpark3
replicas, at most 25 requests per replica, temperature 0.8, a 192-token cap,
and thinking off. There was no voting or arithmetic search.

| Batch | Ending | Legal / 100 | Exact target / 100 |
|---|---|---:|---:|
| 1 | JSON example | 98 | 0 |
| 2 | Schema description | 42 | 4 |
| 3 | Schema description | 44 | 4 |
| 4 | JSON example | 98 | 0 |

The schema ending produced **8/200 exact finishes**, versus **0/200**, but also
**114 illegal actions**, versus **4**. All 400 responses were parseable JSON;
there were zero infrastructure errors or truncations. Actual cost was **50,400
prompt tokens + 7,248 completion tokens**. This is an observed tradeoff on a
single easy state, not evidence of a generally superior prompt or agent method.

The Client hashes the full prompt into each agent's request seed. Consequently,
changing the ending also changed the sampling seeds: this does not isolate a
causal `+`-example bias. Repeated identical per-agent prompts/seeds reproduced
the same action in 86/100 old pairs and 70/100 schema pairs. No prompt default
was changed.

The [archived report](results/prompt-calibration-20261115/REPORT.md),
[summary](results/prompt-calibration-20261115/summary.json),
[metadata](results/prompt-calibration-20261115/metadata.json), and
[raw events](results/prompt-calibration-20261115/events.jsonl) preserve all four
batches, including negative results. All 400 full request bodies and raw HTTP
responses are retained. The [manifest](results/prompt-calibration-20261115/manifest.json)
verifies byte-identical copies of those four files and the
[original diagnostic source](results/prompt-calibration-20261115/archived-source.py).
That source expects the original workspace layout; it is an archive, **not a
standalone app CLI**.

The original metadata's Git revision is empty and remains **unknown**.
[Separate provenance](results/prompt-calibration-20261115/provenance.json)
verifies that its recorded `harness.py` and `runtime.json` SHA-256 values match
Git blobs in `f551b56f97d515b4981382be4b16a06e2caa773c`; this does not retroactively
supply a Git revision for the diagnostic run.
