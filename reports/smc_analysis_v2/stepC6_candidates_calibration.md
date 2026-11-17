# SMC Analysis v2 — Step C6: Candidate Evaluation (Calibration Only)

> [!IMPORTANT]
> **Strict Calibration Scope & Contamination Protocol**:
> All calculations in this report are conducted exclusively on the **CALIBRATION split** (2023-03-01 to 2025-05-21 08:15 UTC; $n = 689$ calendar trading days across 27 months).
> Validation and test splits were strictly **NOT TOUCHED**.
> Validation and test data remain contaminated from earlier exploration; forward clean holdout begins after 2026-11-15 15:00 UTC.

## 1. Candidate Performance Summary Table

| Candidate ID | Candidate Name / Levers | Entries (n) | Entries / Day | Mean R | Win Rate | Cluster SE | Control Percentile ($p_{99}$) | Neutral Alpha (BUY / SELL) | Max Month Share | Worst Day | Max DD | Qualified? |
| :---: | :--- | ---: | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: | :---: | :---: |
| `V2-C1` | Concurrency Expansion (MC=5) + Fast Exit Geometry (24h) | 703 | **1.020** | +0.0730 | 51.5% | ±0.1367 | 96.8% (+0.0877R) | +0.0899 / +0.0364 | 46.3% | -5.03R | 20.74R | 🔴 **NOT QUALIFIED** |
| `V2-C2` | Near-Miss Ingestion (LTF_PENALTY) + Fast Exit (24h) + MC=5 | 944 | **1.370** | +0.0627 | 51.3% | ±0.1298 | 99.0% (+0.0605R) | +0.0990 / +0.0302 | 49.3% | -5.24R | 26.51R | 🔴 **NOT QUALIFIED** |
| `V2-C3` | Friction-Geometry & Volatility Filter (Stop >= $20, High ATR) + MC=3 | 160 | **0.232** | +0.0335 | 46.2% | ±0.1660 | 60.6% (+0.1586R) | +0.2588 / -0.2556 | 133.0% | -3.05R | 25.95R | 🔴 **NOT QUALIFIED** |
| `V2-C4` | Directional Asymmetry Handling (BUY-Only, Stop >= $20, 36h Time Stop) + MC=3 | 228 | **0.331** | +0.1622 | 58.3% | ±0.1490 | 100.0% (+0.1548R) | +0.1617 / +0.0000 | 21.4% | -3.06R | 6.61R | 🔴 **NOT QUALIFIED** |

---

## 2. Gate-by-Gate Qualification Checklist

| Candidate ID | Criterion 1: Entries/Day $\ge 2.0$ | Criterion 2: Mean R $> p_{99}$ Control | Criterion 3: Alpha $> 0$ (Both/Allowed) | Criterion 4: Month $\le 25\%$, Worst Day $\ge -4R$ | Overall Verdict |
| :---: | :---: | :---: | :---: | :---: | :---: |
| `V2-C1` | FAIL (1.020 < 2.0) | FAIL (+0.0730 <= +0.0877) | PASS | FAIL (Share=46.3%, Day=-5.03R) | 🔴 **DISQUALIFIED** |
| `V2-C2` | FAIL (1.370 < 2.0) | PASS | PASS | FAIL (Share=49.3%, Day=-5.24R) | 🔴 **DISQUALIFIED** |
| `V2-C3` | FAIL (0.232 < 2.0) | FAIL (+0.0335 <= +0.1586) | FAIL | FAIL (Share=133.0%, Day=-3.05R) | 🔴 **DISQUALIFIED** |
| `V2-C4` | FAIL (0.331 < 2.0) | PASS | FAIL | PASS | 🔴 **DISQUALIFIED** |

---

## 3. Deep-Dive Candidate Diagnostics

### Candidate `V2-C1`: Concurrency Expansion (MC=5) + Fast Exit Geometry (24h)
- **Realized Entries**: 703 entries over 689 trading days = **1.020 entries/day**.
- **Expectancy & Win Rate**: Mean $R = +0.0730R$, Win Rate = $51.5\%$, Cluster-robust $SE = \pm 0.1367R$.
- **Direction-Neutral Alpha**: Total $\bar{\alpha} = +0.0714R$ (BUY $\bar{\alpha} = +0.0899R$, SELL $\bar{\alpha} = +0.0364R$).
- **Ratio-Preserving Control**: Percentile rank = **96.8\%** vs 1,000 shuffle seeds ($p_{99} = +0.0877R$).
- **Risk & Stability**: Max single month share = **46.3\%**, Worst single day = **-5.03R**, Max DD = **20.74R**.
- **Verdict**: Failed qualification: did not meet Criterion 1 (frequency < 2.0/day) and stability/risk limits.

### Candidate `V2-C2`: Near-Miss Ingestion (LTF_PENALTY) + Fast Exit (24h) + MC=5
- **Realized Entries**: 944 entries over 689 trading days = **1.370 entries/day**.
- **Expectancy & Win Rate**: Mean $R = +0.0627R$, Win Rate = $51.3\%$, Cluster-robust $SE = \pm 0.1298R$.
- **Direction-Neutral Alpha**: Total $\bar{\alpha} = +0.0738R$ (BUY $\bar{\alpha} = +0.0990R$, SELL $\bar{\alpha} = +0.0302R$).
- **Ratio-Preserving Control**: Percentile rank = **99.0\%** vs 1,000 shuffle seeds ($p_{99} = +0.0605R$).
- **Risk & Stability**: Max single month share = **49.3\%**, Worst single day = **-5.24R**, Max DD = **26.51R**.
- **Verdict**: Failed qualification: did not meet Criterion 1 (frequency < 2.0/day) and stability/risk limits.

### Candidate `V2-C3`: Friction-Geometry & Volatility Filter (Stop >= $20, High ATR) + MC=3
- **Realized Entries**: 160 entries over 689 trading days = **0.232 entries/day**.
- **Expectancy & Win Rate**: Mean $R = +0.0335R$, Win Rate = $46.2\%$, Cluster-robust $SE = \pm 0.1660R$.
- **Direction-Neutral Alpha**: Total $\bar{\alpha} = +0.0916R$ (BUY $\bar{\alpha} = +0.2588R$, SELL $\bar{\alpha} = -0.2556R$).
- **Ratio-Preserving Control**: Percentile rank = **60.6\%** vs 1,000 shuffle seeds ($p_{99} = +0.1586R$).
- **Risk & Stability**: Max single month share = **133.0\%**, Worst single day = **-3.05R**, Max DD = **25.95R**.
- **Verdict**: Failed qualification: did not meet Criterion 1 (frequency < 2.0/day) and stability/risk limits.

### Candidate `V2-C4`: Directional Asymmetry Handling (BUY-Only, Stop >= $20, 36h Time Stop) + MC=3
- **Realized Entries**: 228 entries over 689 trading days = **0.331 entries/day**.
- **Expectancy & Win Rate**: Mean $R = +0.1622R$, Win Rate = $58.3\%$, Cluster-robust $SE = \pm 0.1490R$.
- **Direction-Neutral Alpha**: Total $\bar{\alpha} = +0.1617R$ (BUY $\bar{\alpha} = +0.1617R$, SELL $\bar{\alpha} = +0.0000R$).
- **Ratio-Preserving Control**: Percentile rank = **100.0\%** vs 1,000 shuffle seeds ($p_{99} = +0.1548R$).
- **Risk & Stability**: Max single month share = **21.4\%**, Worst single day = **-3.06R**, Max DD = **6.61R**.
- **Verdict**: Failed qualification: did not meet Criterion 1 (frequency < 2.0/day) and stability/risk limits.

---

## 4. Final Step C6 Qualification Verdict

> [!CAUTION]
> **NO CANDIDATE QUALIFIED**.
> 
> Every pre-registered candidate failed Criterion 1 (**entries/day $\ge 2.0$**).
> As established by the mathematical capacity analysis in Step C4, the raw opportunity generation rate of the SMC framework (1.295 distinct setups/day) physically cannot support 2.0 entries/day under portfolio risk controls without loosening core confluence floors into random market noise.
> Per Non-Negotiable Rule 1, 2, and Step C7 instructions: **no criteria are relaxed**, no candidates are iterated upon, and execution proceeds directly to the strategy freeze and final summary.
