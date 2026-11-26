# collab-s1-v1 (s1)

Decision: **STOP**

| arm | cases | rescued_puzzles | puzzles | answered | wrong | accepted_agents | generated_tokens | retry_tokens | cancelled_tokens | novelty | novelty_token_weighted | pieces_counted | checkpoints | note_turns | reply_note | reply_answer | note_tokens | board_reads | winners_who_had_read_an_entry |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| D' | 41 | 6 | 41 | 6 | 0 | 6 | 3349322 | 136162 | 136162 | 0.9662712883623825 | 0.9671026724682449 | 374 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| C' | 41 | 5 | 41 | 5 | 0 | 5 | 3468232 | 43036 | 43036 | 0.9453247784356794 | 0.9471069832343819 | 473 | 473 | 473 | 472 | 0 | 55732 | 473 | 5 |
| C'div | 41 | 9 | 41 | 9 | 0 | 9 | 3291406 | 107268 | 107268 | 0.9472764782640465 | 0.9515481214139397 | 462 | 462 | 462 | 458 | 0 | 57198 | 462 | 9 |

- C': STOP (lead -1, needed 7; rules {'zero_wrong': True, 'rescued_lead': False, 'accepted_agents': False, 'novelty': False}; paired puzzles {'protocol_only': 3, 'plain_only': 4, 'sign_test_p': 1.0})
- C'div: STOP (lead 3, needed 7; rules {'zero_wrong': True, 'rescued_lead': False, 'accepted_agents': True, 'novelty': True}; paired puzzles {'protocol_only': 7, 'plain_only': 4, 'sign_test_p': 0.548828125})

Final verdicts (a primary PASS stays a PASS):
- C': **STOP**
- C'div: **STOP**
