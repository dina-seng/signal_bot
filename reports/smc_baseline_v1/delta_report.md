# SMC Baseline v1 — Pre/Post Migration Delta

**Generated:** 2026-11-22  
**Scope:** 2025 portfolio window (primary comparable headline). Full-range results are supplementary and live under `full_range/`.  
**Contract:** `execution_contract_final.md` (Option B, fixed geometry, planned-risk R, flat 0.40 cost, deterministic voids).

> This is a truthfulness migration, **not** a strategy optimisation. No SMC rule, threshold, TP geometry, risk rule, or parameter was changed.

---

## 1. Headline comparison

| Metric | Historical (`reports/exp_2025_smc_portfolio/report.md`) | Baseline v1 (`reports/smc_baseline_v1/report.md`) | Delta |
| :--- | ---: | ---: | ---: |
| Accepted 15m bars | 2,687 | 2,673 | −14 |
| Distinct opportunities | 688 | 695 | +7 |
| Voided at entry (excluded) | not modelled | 42 | new |
| Portfolio-entered trades | 249 | 249 | 0 |
| Avg R | +0.2059 | **+0.2092** | +0.0033 |
| Total R | +51.26 | **+52.10** | +0.84 |
| Profit factor | 1.42 | 1.419 | ≈0 |
| Max drawdown (R) | 22.45 | **23.72** | +1.27 |
| Win rate | 47.0% | 46.6% | −0.4 pp |
| Shuffle control (val / test) | 34.5% / 84.8% **FAIL** | 29.9% / 78.8% **FAIL** | still failing |
| Coin control (val / test) | not in headline | 28.5% / 65.2% **FAIL** | failing |

---

## 2. Void outcomes (new, previously fabricated as trades)

From the manifest verification log:

| Reason | Count |
| :--- | ---: |
| `NO_FILL_SESSION_BOUNDARY` | 27 |
| `NO_FILL_MISSING_NEXT_BAR` | 8 |
| `VOID_ENTRY_BEYOND_SL` | 4 |
| `VOID_ENTRY_BEYOND_TP` | 3 |
| **Total** | **42** |

These produced no position, no R, and no cost. Historically, cross-session/stale or invalid-entry cases could be filled at a fabricated price.

---

## 3. What changed and why

| Change | Mechanism | Expected effect |
| :--- | :--- | :--- |
| No signal-bar management | Fill at next 15m open; management starts there | Removes impossible pre-entry SL/TP exits (BT-004) |
| Gap fills | SL at adverse open; TP no worse than limit | Worse stopped trades, better gapped targets (BT-006) |
| Fixed structural geometry | SL/TP/risk written at signal time | Prevents strategy drift from execution noise |
| Planned-risk R denominator | Fixed before fill | Gap cost appears in numerator, never hidden by denominator change |
| Deterministic voids | No entry beyond SL/TP, no cross-session fills | Removes fabricated entries |
| Cost label | 0.40 **price units per position unit**, round trip | Disclosure only; number unchanged |
| Day-cluster CI | Replaces IID bootstrap | Wider, more honest uncertainty |
| Timestamp ordering | Parse-then-order (mixed source formats) | Correct chronology; 9,355 identical duplicates collapsed |
| Snapshot drift | Current DB (110,280 rows) vs old report snapshot (100,408) | **Confounds the comparison** — see §4 |

---

## 4. Interpretation limits

1. **The delta is not execution-only.** The historical report was produced from an older DB snapshot (100,408 rows, ending 2026-11-15 15:00); this run uses 110,280 rows ending 2026-11-19 05:30. Differences in counts can come from either execution fixes or new data. This is disclosed rather than silently attributed.
2. **Drawdown worsened** (+1.27R), consistent with adverse gap fills now being modelled instead of filled at the exact stop.
3. **Net R barely moved** (+0.84R total / +0.0033R per trade): removal of impossible exits and addition of gap losses/voids largely offset across this window. This is not evidence that the fixes were immaterial — it is evidence the old number was the product of offsetting biases.
4. **Controls still FAIL** on both validation and test (29.9% / 78.8% vs the 97.5% threshold). Per the contract, the result is **descriptive only**. No edge claim is made.
5. **Forward holdout is contaminated.** The declared clean window after 2026-11-15 15:00 is covered by the current snapshot (`holdout.status: contaminated_current_snapshot` in the manifest). No one-shot holdout verdict is issued.

---

## 5. Provenance

- Engine commit: `3a9053027738c0a1f205fce1aff82c11f0fa8fbd`
- Data SHA-256: `34b740025988355e3c624791d262b0e8998598fa658d893e76507ceef82d9ae1`
- Execution convention: `optionB-v1`
- Full manifest: `reports/smc_baseline_v1/manifest.yaml`
- Historical artifacts were re-hashed and are byte-identical (no overwrite).
