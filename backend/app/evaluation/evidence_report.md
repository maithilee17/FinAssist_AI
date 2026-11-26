# Phase 6 Evidence and Claim Verification Evaluation

Generated: 2026-11-03T14:46:26.027588+00:00

Eight versioned synthetic cases compare the Phase 5-style ungated baseline, evidence gating, and evidence plus claim verification.

| Experiment | Evidence P/R | Claim P/R | Unsupported claims | Abstention P/R | Citation correctness | Answer correctness | Extra retrieval | Verify latency |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| A — No verification | 0.625/1.000 | 0.667/1.000 | 0.500 | 0.000/0.000 | 0.600 | 0.375 | 0.000 | 0.000 ms |
| B — Evidence check | 1.000/1.000 | 0.667/1.000 | 0.333 | 1.000/1.000 | 0.833 | 0.750 | 0.375 | 0.642 ms |
| C — Evidence + claims | 1.000/1.000 | 1.000/1.000 | 0.000 | 0.600/1.000 | 1.000 | 0.750 | 0.375 | 0.443 ms |

Candidate answers are fixed fixtures, so no LLM provider was called and cost is reported as unavailable. These small synthetic results validate behavior; they do not establish calibrated real-world accuracy.
