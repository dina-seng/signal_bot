# SMC Strategy & Portfolio Protocol Freeze v2

**Freeze Date**: 2026-11-17  
**Commit Hash**: `87509a43ef6af26b6bb69de5310e5e2d44fb0581`  
**Status**: **FROZEN — NO FURTHER PARAMETER, SCORING, OR THRESHOLD CHANGES PERMITTED**.

---

## 1. Frozen Production Parameters & Thresholds

All live parameters in `server/app/services/strategies/smc_strategy.py` and `server/app/services/signals/evaluators.py` are permanently frozen at production defaults:

| Parameter | Frozen Value | Source Location | Description |
| :--- | :---: | :--- | :--- |
| `DEFAULT_MIN_SCORE` | `60.0` pts | [server/app/services/strategies/smc_strategy.py:32](file:///D:/trade/server/app/services/strategies/smc_strategy.py#L32) | Baseline composite acceptance threshold for B-tier setups |
| `LTF_UNCONFIRMED_PENALTY` | `5.0` pts | [server/app/services/strategies/smc_strategy.py:36](file:///D:/trade/server/app/services/strategies/smc_strategy.py#L36) | Flat score deduction when 15m structure does not confirm |
| `DIRECTIONAL_CONFLICT_PENALTY` | `15.0` pts | [server/app/services/signals/evaluators.py:31](file:///D:/trade/server/app/services/signals/evaluators.py#L31) | Flat score deduction when an opposing pillar signal exists |
| `PA_FLOOR` | `10.0` pts | [server/app/services/signals/evaluators.py:473](file:///D:/trade/server/app/services/signals/evaluators.py#L473) | Hard gate: Price action score must be $\ge 10.0$ |
| `CONFLUENCE_FLOOR` | `20.0` pts | [server/app/services/signals/evaluators.py:544](file:///D:/trade/server/app/services/signals/evaluators.py#L544) | Hard gate: Structure + Liquidity scores must be $\ge 20.0$ |
| `STRUCTURE_WEIGHT` | `35.0` pts | [server/app/services/signals/evaluators.py:54](file:///D:/trade/server/app/services/signals/evaluators.py#L54) | Maximum points allocated to Market Structure pillar |
| `LIQUIDITY_WEIGHT` | `40.0` pts | [server/app/services/signals/evaluators.py:42](file:///D:/trade/server/app/services/strategies/smc_strategy.py#L42) | Maximum points allocated to Liquidity / SMC pillar |
| `PRICE_ACTION_WEIGHT` | `25.0` pts | [server/app/services/signals/evaluators.py:416](file:///D:/trade/server/app/services/signals/evaluators.py#L416) | Maximum points allocated to Price Action pillar |
| `ROUND_TRIP_SPREAD` | `0.40` price units per position unit, round trip | `server/scripts/smc_replay.py` (`--spread`, ~:822) | Fixed round-trip execution cost, deducted once per trade. See Baseline v1 pointer below. |

---

## 2. Frozen Portfolio Rules (Benchmark Specification)

The portfolio rules defined in Phase C govern position acceptance and sizing across all evaluations:

| Rule Name | Frozen Setting | Description |
| :--- | :---: | :--- |
| `MAX_CONCURRENT` | `3` | Maximum simultaneous open positions across the asset class |
| `ONE_ENTRY_PER_SWEEP` | `True` | Exactly one entry per unique liquidity sweep / opportunity key |
| `MIN_ENTRY_SEPARATION` | `1.0 x ATR` or `1h` | Same-direction entry requires $\ge 1.0 \times \text{ATR}(14, 15\text{m})$ price distance from all open same-direction entries OR $\ge 1\text{ hour}$ elapsed since last entry |
| `DAILY_LOSS_STOP` | `-3.0 R` | Realized daily loss stop per UTC trading day (halts new entries for the rest of that day) |
| `RISK_PER_POSITION` | `1.0 R` | Risk normalized to $1.0R$ per position (independent of account balance or lot sizing) |

---

## 3. Fixed Dataset Splits & Contamination Audit

The evaluation dataset boundaries remain strictly fixed across all analyses:

| Split Name | Share | Start Timestamp (UTC) | End Timestamp (UTC) | Calendar Trading Days | Contamination Status |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **Calibration** | 60% | 2023-03-01 00:00 | 2025-05-21 08:15 | 689 days | Clean training sample |
| **Validation** | 20% | 2025-05-21 08:15 | 2026-02-16 03:00 | 233 days | **Contaminated** (inspected in earlier rounds) |
| **Test** | 20% | 2026-02-16 03:00 | 2026-11-15 15:00 | 231 days | **Contaminated** (inspected in earlier rounds) |
| **Forward Holdout** | — | **2026-11-15 15:00** | Forward Live Data | Ongoing | **STRICTLY CLEAN** (unseen out-of-sample data) |

---

## 4. Phase C2 Candidate Qualification Verdict

In Step C6 ([reports/smc_analysis_v2/stepC6_candidates_calibration.md](file:///D:/trade/reports/smc_analysis_v2/stepC6_candidates_calibration.md)), all 4 pre-registered candidates were evaluated on the Calibration split under the fixed criteria:

| Candidate ID | Name | Entries/Day | Mean R | Shuffle Control | Neutral Alpha | Status |
| :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| `V2-C1` | Concurrency Expansion (MC=5) + Fast Exit (24h) | 1.020 | +0.0730R | 96.8% | +0.0714R | 🔴 **DISQUALIFIED** (Frequency < 2.0/day) |
| `V2-C2` | Near-Miss Ingestion (`LTF_PENALTY`) + Fast Exit (24h) + MC=5 | 1.370 | +0.0627R | 99.0% | +0.0738R | 🔴 **DISQUALIFIED** (Frequency < 2.0/day) |
| `V2-C3` | Friction-Geometry Filter (Stop $\ge \$20$, High ATR) + MC=3 | 0.232 | +0.0335R | 60.6% | +0.0916R | 🔴 **DISQUALIFIED** (Frequency < 2.0/day) |
| `V2-C4` | Directional Asymmetry Handling (BUY-Only, Stop $\ge \$20$, 36h) | 0.331 | +0.1622R | 100.0% | +0.1617R | 🔴 **DISQUALIFIED** (Frequency < 2.0/day) |

Per Step C7 instruction:
> *"If none qualified, say so plainly, do not relax any criterion, and go to the final summary."*

**No candidate qualified.** Consequently:
- Validation and test sets are **not touched** for candidate evaluation.
- No changes to live strategy defaults or production scanner logic are deployed.
- Core production code remains untouched.

---

## 5. Clean Forward-Holdout Evaluation Plan

To evaluate the strategy in a strictly uncontaminated setting, a single one-shot evaluation will be conducted on forward data strictly **after 2026-11-15 15:00 UTC** once sufficient sample size has accumulated.

### A. Sample Size Requirements & Power Analysis

Empirical parameters measured on the Calibration portfolio entries ($n = 332$ entered trades):
- Per-entry standard deviation: $\sigma_R = 1.2604 R$
- IID Standard Error: $SE_{\text{iid}} = 0.0692 R$
- Cluster-robust Standard Error (cluster = day): $SE_{\text{cluster}} = 0.1564 R$
- Variance Inflation Factor: $\text{VIF} = \left(\frac{SE_{\text{cluster}}}{SE_{\text{iid}}}\right)^2 = \left(\frac{0.1564}{0.0692}\right)^2 = \mathbf{5.114}$

#### Sample Size Formula to Detect $\Delta = +0.05R$ with $80\%$ Power at $\alpha = 0.05$ (Two-Sided)

$$N_{\text{iid}} = \frac{(z_{\alpha/2} + z_{\beta})^2 \cdot \sigma_R^2}{\Delta^2} = \frac{(1.960 + 0.8416)^2 \cdot (1.2604)^2}{(0.05)^2} = \frac{7.8490 \cdot 1.5886}{0.0025} \approx \mathbf{4,988\text{ trades}}$$

Adjusting for intra-day clustering ($\text{VIF} = 5.114$):

$$N_{\text{cluster}} = N_{\text{iid}} \times \text{VIF} = 4,988 \times 5.114 \approx \mathbf{25,508\text{ trades}}$$

#### Statistical Power of the Pre-Registered Forward Checkpoint ($N = 150$ New Entries)

With $N = 150$ new portfolio entries accumulating post-freeze:
- Under the target rate of $\approx 2.0\text{ entries/day}$, 150 entries require **$\approx 75$ calendar trading days** ($\approx 3.5$ months).
- Under the measured baseline portfolio rate of $0.467\text{ entries/day}$, 150 entries require **$\approx 321$ calendar trading days** ($\approx 15$ months).
- **Minimum Detectable Effect (MDE)** at $80\%$ power with $N = 150$:

$$\text{MDE} = (z_{\alpha/2} + z_{\beta}) \cdot \frac{\sigma_R}{\sqrt{N}} \cdot \sqrt{\text{VIF}} = 2.8016 \cdot \frac{1.2604}{\sqrt{150}} \cdot \sqrt{5.114} = 2.8016 \cdot 0.1029 \cdot 2.261 \approx \mathbf{+0.652R}$$

A sample of $N = 150$ trades is adequately powered to detect a large edge ($\ge +0.65R$), but cannot resolve small drift-scale edges ($+0.05R$).

### B. Holdout Protocol Rules
1. Accumulate closed candles strictly after `2026-11-15 15:00 UTC`.
2. Execute a single-pass replay using the frozen portfolio simulator without parameter adjustments.
3. Report: realized entries/day, mean $R$, cluster-robust $SE$, direction-neutral alpha, and ratio-preserving shuffle percentile rank.
4. Pass standard: entries/day $\ge 2.0$, mean $R > 0$, shuffle percentile $\ge 97.5\%$, direction-neutral alpha $> 0$.

---

## 6. Documented Production Changes (Reference Only)

Because no candidate passed all qualification gates, production scanner logic remains unchanged. For future development, the exact changes required to implement portfolio-level concurrency in the production scanner are documented below:

1. **Scanner Active Position Concurrency Block**:
   - File: [server/app/services/telegram/scanner.py:273](file:///D:/trade/server/app/services/telegram/scanner.py#L273)
   - Current Code:
     ```python
     if paper_service.has_active_position(symbol):
         logger.info("Signal suppressed: active position already open")
         return
     ```
   - Target Implementation (Behind default-OFF flag):
     ```python
     if settings.ENABLE_PORTFOLIO_CONCURRENCY:
         active_count = len(paper_service.get_open_positions(symbol))
         if active_count >= settings.PORTFOLIO_MAX_CONCURRENT:
             logger.info(f"Signal suppressed: concurrency cap reached ({active_count}/{settings.PORTFOLIO_MAX_CONCURRENT})")
             return
     else:
         if paper_service.has_active_position(symbol):
             return
     ```

2. **Cooldown De-Duplication**:
   - File: [server/app/services/telegram/scanner.py:38](file:///D:/trade/server/app/services/telegram/scanner.py#L38)
   - Current Code: `SIGNAL_COOLDOWN_HOURS = 2`
   - Target Implementation (Behind default-OFF flag):
     ```python
     # Replace flat 2h cooldown with ATR-based separation and sweep key de-duplication
     if settings.ENABLE_PORTFOLIO_CONCURRENCY:
         # Suppress only if within 1.0x ATR of an open same-direction entry AND < 1h elapsed
         pass
     ```

---

## 7. Baseline v1 artifact pointer (2026-11-22)

The canonical execution contract and regenerated artifacts are:

- Contract: `execution_contract_final.md`; readiness: `implementation_checklist.md`, `implementation_status.md`
- Primary headline: `reports/smc_baseline_v1/report.md` (2025 window)
- Provenance: `reports/smc_baseline_v1/manifest.yaml`
- Migration delta: `reports/smc_baseline_v1/delta_report.md`
- Supplementary full range: `reports/smc_baseline_v1/full_range/`

Execution convention `optionB-v1`: signal at a closed 15m bar, fill at the next
eligible 15m open, structural SL/TP fixed at signal time, planned risk as the R
denominator, deterministic entry voids, and a flat 0.40 price-unit-per-position
round trip cost. The forward holdout after 2026-11-15 15:00 is contaminated on
the current snapshot; no edge claim is made.
