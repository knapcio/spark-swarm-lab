# Recommendation: pushing Nemotron 3.5 Lightning toward 72/72 on the arithmetic suite

## Bottom line

The binding constraint is not voting, selection or bad arithmetic. Nemotron usually finds a correct plan inside its reasoning and then fails to emit it before the 8,192-token cap. In the 23 unsolved four-plan (E4) cases, 91 of 92 calls ended as reasoning-only truncations. Plans that were actually emitted passed the exact verifier about 49 times in 50.

So the cheapest lever is a commit step plus a prompt that removes the ambiguity the model ruminates on. A non-voting result is what the evidence supports.

Scope of this analysis: Read/Grep only. Nothing was executed and no model was called. I did not open `reference-witnesses.json`. Counts labelled "proxy" are regex matches over raw traces, not replayed proofs. Paths are relative to `apps/swarm-lab`.

## 1. Binding failure modes

| Mode | Evidence | Status |
|---|---|---|
| Reasoning truncation | Single plan: 52/72 calls `finish_reason=length`; of the 20 that stopped, 18 solved. E4: 94 length finishes in 144 completed calls. Refinement: 74 (`results/solo-control-v2/complete-comparison/solo-comparison/summary.csv`). | Observed, dominant |
| Found but not emitted | `results/evaluation-v2/arithmetic-s1/eva-c25dd13868a8-direct_thinking_8k-s1.jsonl` line 5: the reasoning states "This seems perfect", then re-traces indices until the cap. Same pattern in `…/eva-8955514173a5-ensemble4_thinking_8k-s1.jsonl` lines 12 and 15, and `…/arithmetic-s2/eva-e40959c347a7-ensemble4_thinking_8k-s2.jsonl` lines 18 and 21 (cut while writing the moves array). | Observed in six read calls |
| Rumination on semantics | Tails debate whether leftover numbers are allowed, whether the target must be the final number, and operand order of `i`,`j` (`…/arithmetic-s1/eva-6b194524eb19-ensemble4_thinking_8k-s1.jsonl` lines 15, 21; `…/arithmetic-s2/eva-66b495db2b77-direct_thinking_8k-s2.jsonl` line 5). Proxy: 84/94 truncated E4 calls contain leftover or use-all wording. | Observed; causal role is a hypothesis |
| Index-format loss | The prompt requires indices into a list that is reindexed after each move (`.runtime/evaluation-v2-source/direct_solver.py:13-21`). The only stop-but-failed single plans (`eva-d75177564d41`, seeds 1 and 3) hit "intermediate results must be positive"; the seed-1 plan computes 1−150 instead of 150−1. | Observed, rare (4 illegal moves in about 326 completed full-plan calls) |
| Genuine search difficulty | `…/arithmetic-s2/eva-eea066d2b2d7-ensemble4_thinking_8k-s2.jsonl`: all four tails are text enumeration or factorisation with no solution. One call in the `e40959` file (line 12) degenerates into a repetition loop. | Observed, minority |
| Controller constraints | See below. | Observed in source |

Controller constraints found in source and traces:

- **Refinement never gets four attempts.** All 27 failures are 180-second deadline cases. In `results/solo-control-v2/evaluation-s2/eva-c25dd13868a8-solo_refine_thinking_8k-s2.jsonl`, two truncated calls took 69.0 s and 67.4 s, and the third was killed.
- **Refinement feedback after truncation is empty.** It passes the verifier error, the initial state and a null plan (`.runtime/solo-control-v2-source/ensemble_solver.py:27-33`). The 8K of reasoning is discarded.
- **E4 exhausts the case ceiling.** Four calls at 8,192 tokens equal the 32,768 ceiling exactly, so any follow-up call is denied (`harness.py:105-108`).
- **Each case is pinned to one Spark.** E4 uses 4 of 100 available slots (`run_benchmark.py:277-284`).

Correlated sampling is partly real, but it is correlated non-termination, not correlated wrong answers:

- Pooled, E4 matches independent draws: 1 − 0.75⁴ = 0.684 against 49/72 = 0.681.
- Three tasks (`c25dd`, `8955`, `eea066`) fail E4 on all three seeds, and six tasks account for 15 of 23 failures.
- On `c25dd`, 11 of 12 truncated E4 calls state an equation equal to the target (proxy).
- Across seven tasks, 100 of 116 truncated calls do (proxy; this over-counts hypotheticals such as "300 + 57 = 357").
- On three tasks, 28 of 36 truncated E4 calls state it within the first 9,000 characters. I did not measure token offsets.

Other context:

- The native DeepSeek reference used about 1,100 completion tokens per call on the same prompt, against about 7,170 for Nemotron (different tokenizers).
- Truncation hits trivial tasks too: `eva-6b194524eb19` (sum of three numbers) fails E4 on two seeds while cheap stepwise methods solve it every time.

**Hypotheses, not established:** that a commit call converts most truncated calls; that the leftover and operand-order ambiguity causes the rumination rather than general verbosity; that a value-based format shortens reasoning.

## 2. Six ranked approaches

**1. Scribe commit call on truncation (category A).**
- **Algorithm:** when a plan call returns no content with `finish_reason=length`, send one thinking-off call (cap 256) containing the original prompt plus that call's own reasoning, asking only for the JSON. Verify with the unchanged verifier.
- **Change:** add per-call `thinking`/`max_tokens` overrides and a metadata return to `Client.call`. Do not copy the cascade's attribute mutation (`ensemble_solver.py:29-39`); it is not thread-safe under `run_ensemble`.
- **Cost:** matched budget is 4 × (7,936 + 256) = 32,768. Up to 8 requests per case and about 33K extra input tokens per failed case. Added latency is unmeasured; I'd expect a few seconds.
- **Ablation:** E4 replicate, E4 + scribe with full notes, E4 + scribe with a tail only, and a no-notes scribe control.
- **Stop:** drop it if fewer than 20% of truncated development calls convert.

```python
def run_direct_scribe(e, initial, puzzle_id, agent_id=0):
    state, node_id = initial, e.node(initial, None, 0, puzzle_id, agent_id)
    prompt = build_prompt(e, state)                      # original text, unchanged
    plan, meta = e.client.call(agent_id, "plan", prompt, return_meta=True,
                               max_tokens=7936, node_id=node_id, puzzle_id=puzzle_id)
    if plan is None and meta["finish_reason"] == "length" and meta["reasoning"]:
        notes = meta["reasoning"]
        scribe = (prompt + "\n\nYour own unfinished working notes follow. Do not start over. "
                  "Write the sequence they contain as the requested JSON object now.\nNOTES:\n" + notes)
        plan, _ = e.client.call(agent_id, "scribe", scribe, return_meta=True,
                                thinking=False, max_tokens=256, node_id=node_id,
                                puzzle_id=puzzle_id, parent_request_id=meta["request_id"],
                                notes_sha256=sha256(notes))
    return verify_plan(e, state, node_id, plan, puzzle_id, agent_id)   # existing loop
```

**2. Explicit verifier semantics and value-addressed moves (category A).**
- **Algorithm:** state what the verifier already enforces: leftovers are fine, stop when the target appears, and `a op b` is computed as written. Ask for `{"a":50,"op":"+","b":4}`. The controller compiles values to indices and calls the frozen `apply_action`.
- **Rules:** unchanged. No operand swapping and no retries in the compiler.
- **Cost:** same requests as baseline. Lower token use is the hypothesis under test.
- **Ablation:** 2×2 of {index, value} × {original wording, explicit wording}, single call.
- **Stop:** drop it if stop-finish rate and tokens-to-finish do not improve on development tasks.

```python
def compile_move(state, mv):
    if set(mv) != {"a", "op", "b"} or type(mv["a"]) is not int or type(mv["b"]) is not int:
        raise InvalidMove("move requires integer a, b and op")
    i = next((k for k, x in enumerate(state) if x == mv["a"]), None)
    j = next((k for k, x in enumerate(state) if x == mv["b"] and k != i), None)
    if i is None or j is None:
        raise InvalidMove("operand not available")
    return {"i": i, "j": j, "op": mv["op"]}
```

**3. Budget reshaping: restarts and early commit (category A).**
- **Rationale:** completion lengths of successful single plans run from about 1.7K to 8.0K tokens, which looks heavy-tailed. That favours more, shorter attempts.
- **Algorithm:** choose K and cap from the measured offset of the first verifiable plan, for example 16 × (1,792 + 256) = 32,768. Later, stream the reasoning and trigger the scribe once it states an equation equal to the public target.
- **Cost:** 8–32 requests, same token ceiling. Streaming needs roughly 60 lines.
- **Ablation:** fixed total tokens, varying K × cap.
- **Stop:** drop it if the offset distribution shows solutions arrive late.

**4. Zero-call mechanical salvage (A with mechanical extraction; hybrid at the loose level).**
- **Algorithm:** parse "Move k: a op b = c" sequences from truncated reasoning and verify them.
- **Levels:** report a strict level (contiguous stated plans) separately from a loose level (chaining any stated equations). The loose level is a CPU search over a model-enumerated graph and must not be labelled as Nemotron planning.
- **Role:** primarily a measurement tool for approaches 1 and 3.

**5. Notes-carrying refinement and a strategy portfolio (category A).**
- **Algorithm:** feed the tail of the model's own truncated reasoning into the next refinement attempt. Give parallel agents different task-agnostic strategies (work backward from factors, largest product first, small subsets first).
- **Evidence:** thin. Only `eea066`-type failures, about 3–5 of 23 cases, look search-limited.
- **Stop:** skip it if the residual after approaches 1–2 is at most 2 cases.

**6. Category B, separately labelled.**
- **B0:** classical CPU exhaustive search. It is finite and complete for at most six numbers under these rules, so it guarantees every solvable task. An independent subset-DP solver already found witnesses for all 32 tasks (`CORRECTNESS_AUDIT.md:9`).
- **B1:** Nemotron writes a solver once and CPU executes it, reusing the sandbox.
- **Labelling:** neither is "Nemotron 100%". As with the 376/384 graph result, B1 is a bundled contrast (representation plus CPU execution).

**Not worth adding now:**
- **Voting, democracy and reputation:** with an exact verifier and roughly 98% valid emitted plans, selection has no headroom.
- **Critic/repair and prefix backtracking:** these address about 1% of calls.
- **Beam or MCTS with transpositions over cheap proposals:** this converges on CPU search.
- **Evolution and unrestricted shared memory:** no evidence that information is missing within a context.

## 3. First three experiments

Fleet experiments need a new owner-authorised Nemotron window. Native DeepSeek is serving, and the historical `fleet.sh restore` must not be run.

1. **Offline census (CPU only, no fleet).** Classify every full-plan `request_end` in the immutable traces: stopped-valid, stopped-invalid, truncated with a strict verifiable plan, truncated with a loose chain, or none. Record the offset of the first verifiable plan and flag rumination, enumeration and loops. Write to a new results directory.
2. **Scribe test on the 8 development tasks × 3 seeds,** with the four arms listed under approach 1.
3. **The 2×2 prompt and format test,** single call, same tasks. This is 96 calls, about 30 minutes at one case per node.

## 4. Fresh corpus and controls

Any gain on these 24 tasks is exploratory tuning.

**Corpus (arithmetic-v2):**
- Same generator, a new seed, all v1 fingerprints excluded.
- For example 16 development and 48 evaluation tasks × 3 seeds.
- A sealed CPU-derived stratum label (minimum moves, whether all numbers are needed), used only for reporting.
- A handful of sealed tasks proven unsolvable, as a scoring-bug tripwire.
- Freeze dataset hash, source, prompts, budgets, arms and the one primary contrast before any call.

**Arms, all at 32,768 completion tokens and 180 s after admission:**
- The original single plan, E4 and refinement.
- E4 + scribe.
- E4 with the new prompt.
- The combination.
- Solo with the same scribe and prompt. Without this control, a swarm gain is confounded with the prompt fix.

**Reporting:**
- Task-cluster bootstrap and paired contrasts.
- Server counters including cancelled work and drain.
- Input tokens separately, since notes make them material.
- Do not present democracy-off against full-plan-on as a voting effect.
- 72/72 is not guaranteed: at 98% per case the chance of a clean sweep is about 23%, and at 99.5% about 70%.

## 5. Evidence gaps

- Nemotron prompts are reconstructed from source; there is no wire-level capture.
- There is no cap sweep above 8K and no temperature sweep.
- The effect of DSpark3 on reasoning length is unknown: `results/thinking-budget-20261115.json` has n=4.
- The refinement control was deadline-limited, so 45/72 understates a token-matched sequential baseline.
- The shared frontier used hash-random selection only.
- I did not verify the snapshot revisions with git.

## 6. Recommended sequence

1. Run the offline census.
2. Implement the scribe and the value compiler as new modules, leaving frozen files untouched.
3. Run experiments 2 and 3 on development tasks.
4. Freeze, then confirm on arithmetic-v2.

**Labelling:** report results as "Nemotron plans, mechanical verifier", with category B and the DeepSeek reference in separate rows.

**Validation checks:**
- The runtime never opens the witness file (keep the loader rejection at `run_benchmark.py:248`, and test with the file absent).
- Prompts are byte-identical across tasks once numbers and target are removed.
- Scribe notes come only from the same request lineage, with a hash logged.
- Cross-task notes and no-notes controls solve nothing beyond chance.
- The compiler is tested exhaustively against `apply_action` on small states, including duplicates and operand order.
- The extractor drops wrong equations rather than correcting them.
- Every success replays from the root under the independent audit.
- There are zero `budget_exhausted` events.
- The unsolvable tasks stay unsolved.