# Shared memory in this prototype

Shared memory means **explicit application data held by the coordinator**, with
JSONL events recording what was published and read. It does not mean a shared
GPU memory pool or automatic access to another agent's hidden reasoning.

## Arithmetic: shared states

`shared_search.run_rounds(..., shared=True)` keeps a dictionary of verified
states on the coordinator. All proposals in a round finish before the next
snapshot is published. Exact arithmetic checks each proposed transition; equal
remaining-number multisets are deduplicated. At most four distinct states form
the next frontier, chosen by a deterministic seed/depth/state hash. Workers are
assigned those states with round-robin rotation, so an agent can continue a state
another agent discovered.

`memory_write` records the state, originating node and agent, action, and verified
transition. `memory_snapshot` records the next readable frontier. The dictionary
is scoped to the current puzzle. `duplicate_state` and `frontier_limit` mean
exploration was skipped, not that a state is mathematically impossible.

This policy changes deduplication and frontier selection as well as information
sharing. It is **shared-frontier search**, not a pure memory-only ablation.

## Coding: shared feedback facts

The coding shared policy publishes up to four prior feedback-test failures with
their input, expected result, observed result or error, and source candidate and
agent. A snapshot supplies those facts and a feedback-ranked implementation as
the next repair base. Failures describe that implementation on that test; they
do not prove the task is unsolvable. Full transcripts are not broadcast.

Feedback tests support search. Holdout tests are graded once, after candidate
selection is frozen, and never supply a repair prompt or vote input. All methods
also use the same separate exact-code verification cache: matching code SHA and
grading phase may reuse a prior passed/failed or syntax-error result.
Infrastructure failures and timeouts are not reused. That common cache is not
the shared synthesis-memory treatment.

The current single coordinator needs only ordinary Python dictionaries and the
event log. No Redis, vector database, or cross-machine database service is needed
for these experiments. JSONL is the audit trail; dictionaries hold the working
state during a run.

## GPU KV and prefix caching are different

The saved serving recipe already enables vLLM automatic prefix caching and
Mamba `align` caching. Prefix caching reuses computation for matching prompt
prefixes; it does not add facts to another prompt. Its direct saving is in
prefill, rather than generating new tokens. See
[vLLM 0.27.1 Automatic Prefix Caching](https://docs.vllm.ai/en/v0.27.1/features/automatic_prefix_caching/).

Nemotron's hybrid model has attention caches and Mamba state, with distinct
cache settings described in
[vLLM 0.27.1 cache configuration](https://docs.vllm.ai/en/v0.27.1/api/vllm/config/cache/).
The four replicas maintain separate engine caches. This prototype neither
implements nor validates cross-replica cache migration for Mamba plus DSpark3.
Shared logical facts travel through explicit prompts; matching-prefix reuse can
save repeated prefill within an engine, but its benefit must be measured for
the actual prompt lengths and scheduling.
