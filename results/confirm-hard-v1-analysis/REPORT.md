# Hard fresh tasks: arithmetic-hard-v1 (48 tasks x 3 seeds)

Fresh tasks generated after the protocol was frozen; every success is a plan accepted by the exact verifier. No CPU search, teacher, gold answers or communication between agents.

**Primary (paired, 144 cases):** swarm of 8 forced_explicit agents **81/144** (95% task-cluster interval 43.8%–68.8%) vs baseline 4 plain_original agents **57/144** (27.8%–52.1%); paired difference interval +4.9% to +29.2%.

Budget-matched (4 agents each, same 32,768-token ceiling): swarm 64/144 vs baseline 57/144.

| Agent type | Single-agent success | Mean completion tokens |
|---|---:|---:|
| plain_original | 104/576 (18.1%) | 7587 |
| forced_explicit | 223/1152 (19.4%) | 6986 |

| k | Baseline any-of-k (fixed / expected) | Swarm any-of-k (fixed / expected) |
|---:|---:|---:|
| 1 | 29 / 26.0 | 35 / 27.88 |
| 2 | 46 / 41.17 | 46 / 44.43 |
| 3 | 53 / 50.5 | 57 / 55.32 |
| 4 | 57 / 57.0 | 64 / 63.24 |
| 5 | — | 68 / 69.36 |
| 6 | — | 75 / 74.18 |
| 7 | — | 80 / 78.0 |
| 8 | — | 81 / 81.0 |

Swarm-unsolved cases: eva-h04ed9ea9f35 s1, eva-h04ed9ea9f35 s2, eva-h04ed9ea9f35 s3, eva-h0dd69150c87 s1, eva-h0dd69150c87 s2, eva-h0dd69150c87 s3, eva-h1541e9a4c49 s2, eva-h1541e9a4c49 s3, eva-h1d9c3f5ed23 s1, eva-h1d9c3f5ed23 s2, eva-h1d9c3f5ed23 s3, eva-h20ba0fe5261 s1, eva-h20ba0fe5261 s2, eva-h20ba0fe5261 s3, eva-h226b1c79bb2 s1, eva-h226b1c79bb2 s2, eva-h2622ab81ea2 s2, eva-h26d4054e0b2 s1, eva-h26d4054e0b2 s2, eva-h26d4054e0b2 s3, eva-h3dc5f6e813c s1, eva-h55bd9afd910 s1, eva-h55bd9afd910 s2, eva-h55bd9afd910 s3, eva-h68da152860d s1, eva-h68da152860d s2, eva-h68da152860d s3, eva-h6a3cd5f3fb5 s3, eva-h6eaa807e726 s1, eva-h6eaa807e726 s3, eva-h71b4d3a6ee2 s1, eva-h71b4d3a6ee2 s2, eva-h71b4d3a6ee2 s3, eva-h7e4fa242fcf s2, eva-h89dbebd0c3d s1, eva-h89dbebd0c3d s2, eva-h89dbebd0c3d s3, eva-h9e46a991792 s1, eva-h9e46a991792 s2, eva-h9e46a991792 s3, eva-ha14cf48ace1 s1, eva-hb13dec610c1 s1, eva-hb13dec610c1 s2, eva-hb13dec610c1 s3, eva-hb7e0beecff0 s1, eva-hb7e0beecff0 s2, eva-hb7e0beecff0 s3, eva-hbca206eaf59 s1, eva-hbca206eaf59 s2, eva-hbca206eaf59 s3, eva-hbd7ed852115 s1, eva-hbd7ed852115 s3, eva-hbe63110dd4d s1, eva-hbe63110dd4d s2, eva-hbe63110dd4d s3, eva-hcf68e8eef0d s1, eva-hcf68e8eef0d s3, eva-hd84869b8048 s1, eva-hd84869b8048 s2, eva-hd84869b8048 s3, eva-hf5554b7adb6 s1, eva-hfff0f6246ef s1, eva-hfff0f6246ef s2. Deadlines 0, infrastructure failures 0, run errors []. Batch wall 5707 s (both arms interleaved; not per-arm throughput).
