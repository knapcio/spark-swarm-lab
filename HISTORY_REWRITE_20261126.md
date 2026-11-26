# History rewrite 2026-11-26

On 2026-11-26 the commit messages of six commits on main (2026-11-25) were edited to remove trailer lines that should
not have been there. Only the messages changed: every tree, author, committer and date is byte-identical. Their
descendants received new hashes as a consequence. Old hashes cited in reports and plans map to new ones below.

Old main tip: 55b44bc62f5fd622bfdae4ae63bde3b8224db1a1

| old | new | subject |
|---|---|---|
| a0ed1c7a981e | fff07cb6f23c | report_aot: require complete pairing and list transport retries per arm; add report_aot_coding (code_xl vs code_aot under R2) |
| 63cf6756b4a7 | 8a4964ecccc2 | report_aot_coding: R2 cancellations are not faults; pair only plans with equal agent count; report_aot: document the lost-attempt lower bound |
| 12dc0e3329fa | c58b24867267 | Merge night/aot: generic AoT reports (arithmetic + coding; reviewed) |
| 58257fb75ce8 | da70f53b9a2c | Freeze swarm-aot-hard21-v1 (generic AoT decomposition, owner-approved; plain vs AoT agents under roll12wide on v2.9.2 recipe serving; credit Teng et al. 2025 and alkimiadev) before arithmetic-hard-v21 exists |
| 2c32bcc3fd99 | 3bede9312514 | arithmetic-hard-v21 (seed 2026112521), generated after the swarm-aot-hard21-v1 plans |
| 3e7bf6aab1b0 | 5e189c1e6a25 | Freeze coding-aot-v1 (generic AoT on coding: code_xl vs code_aot under R2, seeds 25-27, v2.9.2 serving) before any call |
| b258dcc938cd | 22d5c1db5d17 | swarm-aot-hard21-v1: generic AoT 82 vs plain 89 of 96 (0 wrong both, p = 0.016, 2.1x tokens) -> not adopted |
| f7e93b105778 | b3e1543d5592 | Merge night/notests: no-provided-tests coding variant (self-tests / judge acceptance; reviewed) |
| c7d282900df5 | ad7a34841d30 | Freeze coding-notests-v1 (public tests vs own tests vs judge acceptance, scored on hidden tests; seeds 22-24) before any call |
| 190126c3d2aa | 2226332f1690 | inkling/report_reserve_coding.py: report for coding-reserve-v1 (R2 code_xl vs R2 with the elastic answer reserve) |
| 6c0314c982c1 | 603ca5e78265 | report_reserve_coding: allow only code_elastic's declared per-agent cap as a plan difference |
| 7eda8077b8e4 | fd1c312f5485 | Merge night/reserve: coding answer-reserve report (reviewed) |
| 8b54e67290ab | 45961c586371 | coding-aot-v1 (AoT 66 vs 68, not adopted) and coding-notests-v1 (no provided tests: judge 70, own tests 68 vs public 69 of 72; ~2x cost) |
| c38fa992e30d | 64fd32d5e280 | roll12fair: water-filling admission (FairSlots) + inkling/report_fair.py (roll12wide vs roll12fair) |
| 60b2eddfa50e | 0e3b56c21fd4 | roll12fair: a controller start failure halts the arm instead of deadlocking |
| fe9b8c91d49c | 4319764b180a | Merge night/fair: roll12fair water-filling admission + report (reviewed) |
| 87333ec13029 | 23543dcf0875 | Freeze swarm-fair-hard22-v1 (roll12wide vs roll12fair water-filling admission) before arithmetic-hard-v22 exists |
| a3f12baab70b | ea2c3d7589bf | arithmetic-hard-v22 (seed 2026112522), generated after the swarm-fair-hard22-v1 plan |
| e0a13a7a637c | cce6877bb8ad | ds_switch_inkling: start-deepseek (native start + health wait without stopping any swarm container) |
| 3366004fbf48 | 6d7bb3dafe58 | ds_switch_inkling: stop-native; start-deepseek executes the hashed bytes and needs explicit health |
| 6238b51de408 | 14f968c65dcf | ds_switch_inkling: start-deepseek --official (official-tokenizer launcher, its own pinned sha) |
| fd549301275e | 79d3be573a32 | Merge night/ds-official: ds_switch start-deepseek / stop-native (reviewed) for the official-1017 production switch |
| fcc421b20829 | 7b3d2a9ca91d | Freeze coding-reserve-v1 (R2 vs R2 + code_reserve picked by the frozen replay screen, 19-row N rerun merged; seeds 28-30) before any call |
| 8f65da926569 | c2556663ef8c | swarm-fair-hard22-v1 (roll12fair replaces roll12wide: 82 vs 80, 0 wrong, wall 0.91x) and coding-reserve-v1 (code_reserve adopted: 71 vs 70, tokens 0.82x) |
| 64f3370a3b75 | bff745f9a371 | Freeze coding-reserve-v2 (replication of coding-reserve-v1: R2 vs R2 + code_reserve, seeds 31-33) before any call |
| 66999b737994 | add67d750912 | Freeze swarm-fair-hard23-v1 (replication: roll12wide vs roll12fair) before arithmetic-hard-v23 exists |
| 83c198496cf2 | 996c30ef618c | arithmetic-hard-v23 (seed 2026112623), generated after the swarm-fair-hard23-v1 plan |
| 55b44bc62f5f | d0383c19c45a | coding-reserve-v2: replication failed (66/6 wrong vs 71/1); code_reserve adoption reverted, coding default back to plain R2 |

Full hashes (old new):

```
a0ed1c7a981e950178bedc292e128d26c70582ba fff07cb6f23c41ac420d2186e549cb717dc558c8
63cf6756b4a7956bf336cd3d0ca917aa3b9adae6 8a4964ecccc25a559738616478cd622fc854cdbf
12dc0e3329faa2ad4292d47b89727554f4fd82c0 c58b24867267412a5a7dca484782736e603914ca
58257fb75ce8b7b5bb67b033ad4c6441d9d0703c da70f53b9a2c87ce78e46058295f9e4a88df6593
2c32bcc3fd99a92ad22d4fa446e48499fb356f81 3bede9312514b4746ef5b30e8ec3752e6b87558d
3e7bf6aab1b07a478eddd78d1be8c7feb6484194 5e189c1e6a2511aa90c8bb62a98f30080b8082d1
b258dcc938cd0d2d397a4bde3a3d0da748a628a4 22d5c1db5d17999468789c25278ac96ae261ce1d
f7e93b105778b25ef3d65f467ccc5c3cae6415d2 b3e1543d5592a369400a96d95beedee2494ba4f9
c7d282900df5e07e713e88d97b433e35abad9c50 ad7a34841d30acf405e563851c220dcf3f94fff8
190126c3d2aa23f7d7b2d59b576588bc5e73fa1b 2226332f16906157a6a59ca4723abcc2a08ef838
6c0314c982c121b06245ab0dc0406a6789e0c6c3 603ca5e7826514ac282693b4e5fbe4d79a0cd544
7eda8077b8e40fe637afde7442ccee9a3afdb970 fd1c312f548534002f8da86d909fcd55f9ac6ddc
8b54e67290abab7418e4ede8a3e8ac8923cb6ff5 45961c58637179aa3c479c0e11b6b65e6b3c5f5d
c38fa992e30db9f7a17aa689c73082af2d4551a6 64fd32d5e2802915777007f04932336c13bdad9a
60b2eddfa50eabe23620f7f2a4798cb722cd14e1 0e3b56c21fd4c89247e1ba21cf956b7a3d5f1d07
fe9b8c91d49c6b7669540350908479a38b097e75 4319764b180a78a9bd7d70e93d3d823f3a7ff54a
87333ec130299b68943acbfb888af7cf14a45261 23543dcf08751502ffa12726a2467a591b4d3ed8
a3f12baab70b396bff37abcc3e5e95e8d9a7c3bf ea2c3d7589bf942bc59e729b0e9c2d0424023e6f
e0a13a7a637c328edbd660ff5f2be76776059d90 cce6877bb8ad9bdd940cfd09112d041e102f0c0f
3366004fbf4818825b700bbc5edf576d08a7ba14 6d7bb3dafe582b3c73cfdd06f0e268250ff90366
6238b51de408638297129e63b5840517dfd8a33d 14f968c65dcf0cc6ce81959563f8080f45239373
fd549301275e5ea0b76f176754c9f60f7f460e4e 79d3be573a329e6bdbc717bee208857928174eb4
fcc421b20829531aedcbfa3e3ead1919b5682eb7 7b3d2a9ca91d46e1f071aeb1a3fd41d0914f20cb
8f65da9265699328fd610496b6f1feac38fadd6e c2556663ef8c35ab9eef95ca084c63ee0350b48a
64f3370a3b754a03897df7c28cdeb1b1b98cb8f1 bff745f9a3712241eee24f6e69638c41a53b9325
66999b7379940b4123265799bbc05bfdaa0d8285 add67d750912418db410043f3a0acbd098df50bf
83c198496cf2a5b3471e8118d976ba43c8e9f1ba 996c30ef618cfc2ae8f15b5cf2566c9cd59565a0
55b44bc62f5fd622bfdae4ae63bde3b8224db1a1 d0383c19c45a9148a590c202392c916990bf3af1
```
