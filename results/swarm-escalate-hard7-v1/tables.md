| Arm | Solved | Wrong | Abstain | Server gen. tokens/case | Arm wall | Case wall median / p90 | GPU Wh | Wh per solved | Cancelled / escalation agents |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| B deep4cancel (default) | **79** | 0 | 17 | 43,976 | 55 min | 366 / 1611 s | 103.7 | 1.31 | 217 / 0 |
| B+ roll8cancel (escalation, max 8) | **90** | 0 | 6 | 53,641 (+22 % vs B) | 71 min (+30 % vs B) | 368 / 1845 s | 133.4 | 1.48 | 252 / 57 |
| A deep4 (reference) | **82** | 0 | 14 | 66,592 (+51 % vs B) | 90 min (+64 % vs B) | 1050 / 1538 s | 167.1 | 2.04 | 0 / 0 |

| Paired (task, seed) | Pairs | Wins | Losses | Sign test p |
|---|---:|---:|---:|---:|
| roll8cancel vs deep4cancel | 96 | 12 | 1 | 0.00342 |
| roll8cancel vs deep4 | 96 | 9 | 1 | 0.0215 |
| deep4cancel vs deep4 | 96 | 5 | 8 | 0.581 |
| pooled_v6_v7_deep4cancel vs deep4 | 192 | 6 | 12 | 0.238 |

Escalation inside B+: 17 cases escalated (57 extra agents; 4 of them were then solved by one of the first four), 7 cases answered by an escalation agent, of which **6 strict rescues** (all first four had already failed), 6 correct.

Frozen decision rule: zero_wrong = True, strict_rescues_at_least_2 = True, tokens_at_most_reference = True, wall_below_reference = True, reference = A deep4, adopt_roll8cancel = True
Owner goal (B+ solved >= A solved): True
