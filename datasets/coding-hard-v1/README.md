# coding-hard-v1

A harder companion to `coding-v1`, built because `coding-v1` is saturated
(most policies pass 52-54 of 54 holdout cases) and no longer separates
methods. It has 8 development and 24 evaluation pure-Python-function tasks.
The JSON schema and protocol string (`original-python-functions-v1`) are the
same as `coding-v1`, so `coding_harness.py` reads this corpus unchanged. A
top-level `corpus: "coding-hard-v1"` field tells the two corpora apart.

- `tasks.json`: the public specifications plus two examples per task. This is
  the only file a model sees.
- `hidden-tests.json`: the feedback and holdout cases, reference A's source
  and hash, and a `validation` block that pins reference B. Never show this
  file to a model.

Regenerate with `python3 make_coding_hard.py --output datasets/coding-hard-v1`.
The command refuses to overwrite existing JSON files. Check the corpus with
`python3 -m unittest test_make_coding_hard`.

## Tasks

| Split | Function | What it asks for |
|---|---|---|
| dev | `repeating_expansion` | Exact expansion of num/den in base 2-36, with the shortest and earliest repeating block in parentheses |
| dev | `wrap_hyphen` | Greedy line wrapping that can break after hyphens and hard-splits words longer than the width |
| dev | `semver_sort` | Validate SemVer 2.0 strings, then sort them by precedence with a stable order for ties |
| dev | `stack_vm` | Stack-machine interpreter with calls, truncating DIV/MOD, a step limit and ordered error codes |
| dev | `cidr_merge` | Normalize IPv4 CIDR blocks and return the minimal exact cover |
| dev | `nth_distinct_permutation` | Unrank the n-th distinct permutation of a multiset string (up to 20 characters) |
| dev | `glob_match` | Full-match glob with classes, negation, ranges, escapes and invalid-pattern detection |
| dev | `add_business_days` | Add or subtract business days with holidays, date validation and year bounds |
| eval | `rational_eval` | Exact rational expression evaluator: precedence, right-associative `^`, unary minus, errors |
| eval | `shell_words` | POSIX-like word splitting with quotes, escapes, `$VAR`/`${VAR}` expansion and rules for dropping empty words |
| eval | `cron_next` | Next minute that matches a 5-field cron expression, including the day-of-month/day-of-week OR rule and a 5-year search limit |
| eval | `date_diff_ymd` | Years, months and days between two dates, defined by month-end clamping |
| eval | `monthly_occurrences` | Monthly recurrences such as `day:-N` and `nth:K:WD`; months that lack the day are skipped |
| eval | `schedule_jobs` | Non-preemptive multi-worker scheduling simulation with three tie-break levels |
| eval | `lex_shortest_path` | Minimum-cost path; ties go to the lexicographically smallest node sequence |
| eval | `stable_topo` | Topological order in input-priority order, with remaining nodes split into cyclic and blocked |
| eval | `order_book` | Limit/market order matching engine with price-time priority, cancels and invalid-op filtering |
| eval | `ledger` | Account simulation with ordered rejection reasons, overdrafts, fees and daily counters |
| eval | `spreadsheet_eval` | Formula cells with SUM ranges, cycle detection and first-error propagation |
| eval | `poly_expand` | Parse a polynomial in x, expand it and print it in exact canonical form |
| eval | `bool_minterms` | Boolean formula parser (5 precedence levels, right-associative `->`) that returns the truth-table minterms |
| eval | `csv_parse` | Strict CSV tokenizer: quotes, CRLF vs lone CR, final terminators, invalid stray quotes |
| eval | `league_table` | League standings with head-to-head tie-breaks inside groups level on points |
| eval | `canonical_huffman` | Deterministic Huffman code lengths (keyed tie-break), then canonical codes |
| eval | `token_bucket` | Rate limiter with exact integer refills; partial progress is discarded while the bucket is full |
| eval | `json_select` | Small JSONPath-like selector: keys, quoted keys, negative indexes, `[*]`, pre-order `..name` |
| eval | `common_free_slots` | Shared free time across calendars with per-person UTC offsets, clipping and a minimum slot length |
| eval | `min_coins_lex` | Fewest-coins change; ties go to the lexicographically largest multiset (greedy fails) |
| eval | `render_table` | Markdown-style table rendering: alignment, centre bias, escaping, minimum width 3 |
| eval | `decode_repeat` | Nested `N[...]` decoder with escapes and a 10,000-character limit that must be checked without building the string |
| eval | `grid_portals` | Grid BFS where stepping onto a portal teleports you as part of the same move |
| eval | `lru_ttl` | LRU cache with TTL expiry, purge-before-insert, and deletion via ttl <= 0 |

## Why it is harder than coding-v1

The coding-v1 tasks are mostly one-line transformations. Each task here
combines several of these:

- a small parser or tokenizer with explicit precedence and error rules
- calendar arithmetic, such as month-end clamping, leap days and the cron OR rule
- a simulation with ordered tie-breaks and ordered rejection checks
- an exact output format, such as canonical polynomials, tables, Huffman codes or repeating decimals
- a performance trap, where enumeration or building the full output fails (`nth_distinct_permutation`, `decode_repeat`)

Each task also has an "obvious" library shortcut whose behaviour differs from
the spec, such as `shlex`, `csv`, `fnmatch` or `ipaddress` used naively.
Feedback and holdout cases mix hand-picked edge cases with seeded random
inputs. A task counts as solved only if the frozen selection passes every
holdout case, so a single missed rule fails the task.

## Validation

- Reference A is the trusted source stored in `hidden-tests.json`. Each
  reference is self-contained, with its imports inside the function.
- Reference B is `coding_hard_second_refs.py`. Another author wrote it from
  the public specs and examples alone, without seeing reference A.
- The build fails if the two references disagree on any example, feedback
  case or holdout case.
- The build checks that no reference mutates its inputs and that every output
  is JSON-typed.
- Inputs are disjoint across examples, feedback and holdout. Disjointness is
  checked with the harness's own `sort_keys` digest.
- The output is deterministic, and the test file pins the hashes of the
  corpus files.

## Limitations

- **Calibration:** difficulty is not yet calibrated on any model. The
  30-60 % single-call target for Nemotron is a design goal, not a
  measurement. Run the development split first.
- **Correctness:** two agreeing references reduce spec ambiguity but do not
  prove the specs or the expected values correct. Hand-picked edge cases
  were chosen by the same author as reference A.
- **Coverage:** passing a finite holdout set does not prove a solution
  correct on all inputs. Some tasks have many invalid-input cases (`None` or
  `"error"`) by design.
- **Wording:** specs are dense, and a few rules are stated as algorithms (for
  example `wrap_hyphen`, `token_bucket` and `canonical_huffman`). A model
  that misreads one sentence fails the whole task, which is part of the
  intended difficulty but also measures reading precision.
- **Speed:** the 10-second grader limit covers a whole phase. References run
  each phase in well under 0.1 s. Brute-force candidates for
  `nth_distinct_permutation`, `decode_repeat` and `cron_next` may time out
  by design.
