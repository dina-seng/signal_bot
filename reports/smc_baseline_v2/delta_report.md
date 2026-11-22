# SMC Baseline v2 — Strategy-Fix Delta

**Generated:** 2026-11-22T09:31:51.899530+00:00  
**Strategy commit:** `3faf317ebd59b89170ac45d07c114046e8cb93b0`  
**Scope:** Baseline v2 (N-03 floor enforcement + N-02 LTF cadence) vs Baseline v1.  
**Execution contract:** `optionB-v1` — `execution_config_hash` verified identical in both runs.

| Metric | Baseline v1 | Baseline v2 | Delta |
| :--- | ---: | ---: | ---: |
| Accepted opportunities | 695.0 | 735.0 | +40 |
| Filled trades (portfolio-entered) | 249.0 | 258.0 | +9 |
| Voided entries | 42.0 | 42.0 | 0 |
| Avg R | 0.2092 | 0.2547 | +0.0455 |
| Total R | 52.1 | 65.71 | +13.61 |
| Profit factor | 1.42 | 1.52 | +0.1 |

> Strategy-layer fix only. No simulator execution rule, fill logic, cost model,
> R denominator, capacity filter, gap/void rule, or threshold was changed.
