# swarm-round3-hard17-v1

**Scope (owner rule, 2026-11-24 07:05 Warsaw).** The swarm must be a generic solution for any problem; prompt tuning toward the benchmark tasks is out of scope. Arm L (the sentence 'Unused numbers are allowed; stop as soon as the target appears.') passed its frozen rule but is a task-specific prompt change and is NOT adopted. The recall pass (R) lists target +/- x and the closers (C) use an arithmetic wanted list and task wording, so both are task-specific as implemented: R failed its screen anyway (0/30), C was not run on hard-v17 and its dev screen is a measurement only. Add-on X (more agents, no prompt change) is a generic mechanism and stands (cap 20 in its stage-A form; the live load-gated version is the next study). Arm D uses the default roll12strategy, whose escalation strategy hints are also task-specific; a generic default without hints is proposed separately.


## D vs L

| arm | status | cases | solved | wrong | abstain | server tokens/case | tokens/solved | wall s | Wh |
|---|---|---|---|---|---|---|---|---|---|
| D | complete | 96 | 87 | 0 | 9 | 74,409.3 | 82,106.8 | 5,776.3 | 183.4 |
| L | complete | 96 | 88 | 0 | 8 | 73,650.6 | 80,346.1 | 5,778.8 | 182.9 |

Paired: L-only solved 4, D-only 3, exact sign test p = 1.0.

### Mechanism: tokens after discovery (winners that leave a number unused)

Discovery = the first thinking line of the accepted plan's stream with an arithmetically true equation (exact Fraction evaluation, offline analysis only) whose result is the target; tokens after it are counted only within that stream (rest of the discovery request, estimated by characters, plus its continuation).

| arm | leftover winners | measured | median | p90 |
|---|---|---|---|---|
| D | 8 | 5 | 11,606.0 | 26,449.1 |
| L | 10 | 8 | 3,430.6 | 18,573.3 |

## Add-ons on D's clean abstentions

| add-on | status | cases | rescued | wrong | server tokens | share of D | Wh |
|---|---|---|---|---|---|---|---|
| X | complete | 9 | 2 | 0 | 1,978,572.0 | 0.277 | 51.1 |
| C | not run | - | - | - | - | - | - |
| R | not run | - | - | - | - | - | - |

Rescued overlap: {}; in all: 2; union: 2.

## Screens

- closer: not run
- recall: not run

## Decision rules

- L: {"zero_wrong": true, "solved_within_noise": true, "cheaper_per_solved": true, "adopt_sentence": true, "rejected_pending_review": false}
- X: {"rescued_at_least_2": true, "zero_wrong": true, "outcome": "cap 20"}
- C: "incomplete - C: not run"
- R: "incomplete - R: not run"

### Frozen rules (plans)

- D: None
- L: L replaces the default prompt if 0 wrong in L, L solved >= D solved - 2 (noise band), and L server tokens per solved case < D (mechanism: shorter post-discovery thinking). If L solved <= D - 3 the sentence is rejected pending review.
- X: Cap 20 becomes the accuracy default (to be made load-gated in a stage-B study) if X rescues >= 2 of D's abstentions and 0 wrong; cap 16 instead if all rescues come from slots 12-15. Tokens and energy are reported (owner priority: quality).
- C: Closers become part of the default if 0 wrong, >= 2 of D's abstentions rescued, and closer server tokens <= 10 % of D's server tokens.
- R: The recall pass becomes part of the default worker if 0 wrong, >= 2 of D's abstentions rescued, and recall server tokens <= 10 % of D's server tokens; if both C and R pass, the one with more rescues (ties: fewer tokens) is adopted first and the other is re-tested on top.

## Accounting disclosure

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.
