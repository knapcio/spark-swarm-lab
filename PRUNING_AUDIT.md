# Democracy pruning audit — 2026-11-15

Offline inspection of six recorded runs; no API requests or implementation
changes. These are diagnostic observations, not a comparison of model quality or
agent methods.

## Scope and counting rules

Read each JSONL in `runs/`. The current path consists of the root and successive
`chosen.node_id` states. A round is a distinct input `node_id` with proposal
records, including a round that produces no legal proposal. A completed election
has a `chosen` record. Counts below include duplicate legal proposals before
state deduplication.

Parse state values and target as exact `fractions.Fraction`. For a one-step
finish, enumerate every ordered pair of distinct indices and each operator
`+`, `-`, `*`, `/` using `harness.apply_action` with `allow_fractions=False`:
consume the two operands, require a strictly positive integer result, reject
zero division, and retain all unused numbers. A finish requires the newly
computed value to equal the target exactly. Using a subset of the original
numbers is valid. This is bounded one-operation inspection, not a full puzzle
solver. Examine legal proposal children separately for an existing target and
for a possible one-step finish; follow `chosen` and `pruned` records to distinguish
selection from deduplication.

| Trace in `runs/` | Rounds / elections | Legal proposals | Exact-target proposal children |
|---|---:|---:|---:|
| `pipeline-check-deepseek-4.jsonl` | 3 / 3 | 12 | 0 |
| `20261115-111910-democracy-4.jsonl` | 3 / 3 | 11 | 0 |
| `20261115-111919-democracy-100.jsonl` | 5 / 5 | 483 | 0 |
| `nemotron-thinking-smoke-4.jsonl` | 1 / 0 | 0 | 0 |
| `20261115-112934-democracy-100.jsonl` | 3 / 3 | 296 | 98 |
| `20261115-130712-democracy-100.jsonl` | 5 / 5 | 489 | 0 |
| **Total** | **20 / 19** | **1,291** | **98** |

Event IDs below refer to the named file, not a cross-run global identifier.

## Findings

**No election rejected an already proposed exact target.** All 98 exact-target
children occurred in the final round of `20261115-112934-democracy-100.jsonl`.
The input was `[2,8]`; deduplication retained one target representative and
`chosen` event **2394** selected it with **100/100 votes**. Thus there was one
round with an exact-target candidate and zero such rounds lost by voting.

**Root opportunities and selected-state opportunities differ.** Three roots
were `[2,3,7,8]`, target 24, with the immediate move `i=1,j=3,op="*"`:

- DeepSeek pipeline: root event **3**, node `8ec39bd00eff`; **0/4** proposals
  reached 24. Event **35** chose `[2,8,21]`.
- Nemotron four-agent run `111910`: root event **3**, node `c50a855eda04`;
  **0/4** proposals reached 24. Event **34** chose `[2,8,10]`.
- Thinking smoke: root event **3**, node `8bcb478d800a`; zero legal proposals.
  Request-end events **8, 10, 12, 14** each report `finish_reason="length"` and
  **1,024 completion tokens**, with no parseable answer. **No vote stage or
  election occurred**; this is truncation, not a voting rejection.

Only one previously selected child admitted an immediate finish: in `112934`,
event **1592** selected `[2,8]`, node `1509ba3344c6`; the next round succeeded
at event **2394**. Therefore **0/1 selected-state opportunities were missed**.
Across root and selected input states together, four rounds admitted an immediate
finish and three did not finish, including the truncated round.

**One shorter continuation was voted down, without losing the game.** In
`112934`, legal proposal event **283**, agent 64, candidate `5dba050e90f3`,
produced `[2,3,5]`, allowing `2*5=10` next. It received **6 votes**. Event **796**
chose `[1,2,7]` with **40 votes**. The elected path still reached 10, in three
moves rather than the available two. Across all six traces, two rounds had a
proposed child admitting a one-step finish; one selected a longer continuation.

**Both 952 failures lacked terminal candidates.** The old `111919` run had
**483/500** legal proposals; the new `130712` run had **489/500**. Neither
produced an exact-target child or visited a current-path state admitting an
immediate finish. The observed failures therefore do not demonstrate harmful
pruning of terminal solutions. This bounded audit does not determine full
reachability of their earlier states.

## Next hypothesis — not implemented

Accepting any verified terminal proposal before voting could save calls, but
would rescue **zero observed failures** here; it could skip the final 100 votes
in `112934`. An explicit **symbolic one-step finish tool**, available identically
to every method, would address the missed root opportunities. It must be reported
as an additional arithmetic tool, not as improved LLM democracy. One-step
lookahead over proposed children could also favor the shorter path above, but
adds evaluator knowledge and warrants a separate experimental arm. These traces
do not establish that reputation weighting alone would fix the 952 failures.
