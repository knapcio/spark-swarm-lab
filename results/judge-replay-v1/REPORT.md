# Judge replay screens

## Coding: generic judge as a second acceptance key

Status: complete

- wrong winners (hidden tests fail) rejected by the judge: 20 of 31 (accepted 11)
- correct winners wrongly rejected: 61 of 684 (by task: {'eva-rational_eval': 7, 'eva-order_book': 5, 'eva-decode_repeat': 8, 'eva-cron_next': 6, 'eva-poly_expand': 7, 'eva-min_coins_lex': 1, 'eva-monthly_occurrences': 3, 'eva-spreadsheet_eval': 5, 'eva-date_diff_ymd': 2, 'eva-stable_topo': 2, 'eva-json_select': 8, 'eva-render_table': 1, 'eva-bool_minterms': 2, 'eva-canonical_huffman': 1, 'eva-grid_portals': 1, 'eva-lex_shortest_path': 1, 'eva-common_free_slots': 1})
- no parseable verdict: 0; forced winners: 30
- cost: client judge tokens 4,324,980; server generated 4,324,980.0, prompt 6,254,586.0, prefill computed 929,786.0, 176.6 Wh, 5,923.8 s

## Arithmetic: a second judge for forced answers

Status: complete
- forced: 0 of 54 valid accepted plans rejected by the second judge (0 invalid accepted, 0 without verdict)
- control: 1 of 54 valid accepted plans rejected by the second judge (0 invalid accepted, 0 without verdict)
- forced plans the first judge rejected: false accepts by the second judge 0 of 2787 invalid
- cost: client judge tokens 2,541,739; server generated 2,535,595.0, prompt 1,126,959.0, 86.2 Wh

Frozen rule: Screen only (recorded candidates). A live study of the coding judge as a second key is planned only if it rejects at least half of the wrong winners while rejecting at most 5 % of the correct winners; a live second judge on forced answers only if it would turn at least 1 false accept into a reject per 1,000 forced plans without rejecting more than 1 % of valid accepted plans. Cost reported.

## Disclosures

Weaknesses that remain in arms.py-driven arms (arms.py is pinned; disclose in reports): flush_caches ignores the ssh exit status and the HTTP status (only the response text is recorded), delta() accepts negative deltas after a counter reset, parse() counts a missing counter as 0 and accepts non-finite values, wait_idle() returns a busy snapshot after its limit without failing, and an energy failure does not change the exit code.

The hidden-test / verifier results are copied from the recorded runs for scoring only.
