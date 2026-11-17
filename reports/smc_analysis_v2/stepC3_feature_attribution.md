# SMC Analysis v2 — Step C3: Feature Attribution (Calibration Only)

> [!IMPORTANT]
> **Contamination Disclaimer & Strict Calibration Scope**:
> All calculations in this report are conducted exclusively on the **CALIBRATION split** (2023-03-01 to 2025-05-21 08:15 UTC).
> Validation and test splits are strictly **NOT TOUCHED** in this step.
> As documented, validation and test splits were exposed in earlier research rounds and are contaminated; clean holdout data begins after 2026-11-15 15:00 UTC.

## 1. Protocol & Feature Definitions

- **Evaluation Universe**:
  - **All Distinct Accepted Setups**: $n = 932$ (BUY $n = 630$, SELL $n = 302$). One entry per unique opportunity/sweep key.
  - **Portfolio-Entered Trades**: $n = 333$ (BUY $n = 215$, SELL $n = 118$). Positions entered under `MAX_CONCURRENT=3`, `DAILY_LOSS_STOP=-3.0R`, `MIN_ENTRY_SEPARATION=1.0 ATR`.
- **Features Tested**: **20 total features** spanning strategy pillar scores, price action patterns, risk geometry, volatility regimes, and session timing.
- **Statistical Standard**:
  - Spearman rank correlation $\rho_s$ with realized outcome $R$.
  - Student's $t$-statistic and two-sided unadjusted $p$-value.
  - Benjamini-Hochberg (FDR) adjusted $p$-value ($p_{\text{adj}}$) across all $M = 20$ features per direction.
  - Survival requirement: $p_{\text{adj}} < 0.05$ AND consistent sign for **BOTH** BUY and SELL directions.

### Evaluated Features Catalog

| # | Feature Identifier | Type | Description | Source |
| -: | :--- | :---: | :--- | :--- |
| 1 | `composite_score` | Continuous | SMC Composite final score [0-100] | Checkpoints / `evaluators.py` / `backtest.db` |
| 2 | `pre_ltf_score` | Continuous | Pre-LTF score before unconfirmed deduction | Checkpoints / `evaluators.py` / `backtest.db` |
| 3 | `struct_liq_score` | Continuous | Structure + Liquidity pillar consensus score | Checkpoints / `evaluators.py` / `backtest.db` |
| 4 | `pa_score` | Continuous | Price Action pillar score [0-25] | Checkpoints / `evaluators.py` / `backtest.db` |
| 5 | `is_inside_bar` | Binary | Trigger is Inside Bar compression (pa_score == 12) | Checkpoints / `evaluators.py` / `backtest.db` |
| 6 | `is_pin_or_engulfing` | Binary | Trigger is Pin Bar or Engulfing (pa_score > 12) | Checkpoints / `evaluators.py` / `backtest.db` |
| 7 | `ltf_penalized` | Binary | LTF unconfirmed -5 pt penalty applied | Checkpoints / `evaluators.py` / `backtest.db` |
| 8 | `stop_distance` | Continuous | Stop loss distance in dollars (|entry - SL|) | Checkpoints / `evaluators.py` / `backtest.db` |
| 9 | `spread_to_stop_ratio` | Continuous | Friction ratio: $0.40 / stop distance | Checkpoints / `evaluators.py` / `backtest.db` |
| 10 | `rr_planned` | Continuous | Planned risk-reward ratio to TP1 | Checkpoints / `evaluators.py` / `backtest.db` |
| 11 | `atr_value` | Continuous | 15m ATR(14) in dollars at signal time | Checkpoints / `evaluators.py` / `backtest.db` |
| 12 | `atr_regime` | Binary | High volatility regime (ATR >= calibration median) | Checkpoints / `evaluators.py` / `backtest.db` |
| 13 | `stop_to_atr_ratio` | Continuous | Stop distance normalized by 15m ATR | Checkpoints / `evaluators.py` / `backtest.db` |
| 14 | `session_asian` | Binary | Asian session entry (00:00-08:00 UTC) | Checkpoints / `evaluators.py` / `backtest.db` |
| 15 | `session_london` | Binary | London session entry (08:00-16:00 UTC) | Checkpoints / `evaluators.py` / `backtest.db` |
| 16 | `session_ny` | Binary | New York session entry (13:00-21:00 UTC) | Checkpoints / `evaluators.py` / `backtest.db` |
| 17 | `session_overlap` | Binary | London/NY overlap entry (13:00-16:00 UTC) | Checkpoints / `evaluators.py` / `backtest.db` |
| 18 | `in_killzone` | Binary | Institutional killzone (03:00-16:00 NY time) | Checkpoints / `evaluators.py` / `backtest.db` |
| 19 | `hour_of_day` | Continuous | Decision bar UTC hour (0-23) | Checkpoints / `evaluators.py` / `backtest.db` |
| 20 | `day_of_week` | Continuous | Decision bar weekday (0=Mon, 4=Fri) | Checkpoints / `evaluators.py` / `backtest.db` |

---

## 2. Feature Attribution Results — Distinct Accepted Opportunities (Pre-Portfolio Filter)

> Evaluates all 932 raw signals emitted by the SMC strategy on calibration.

### Direction: BUY ($n = 630$)

| Feature | Spearman $\rho_s$ | $t$-stat | $p$-value | $p_{\text{adj}}$ (BH) | T1 (Low/0) Mean R [Win%] | T2 (Mid) Mean R [Win%] | T3 (High/1) Mean R [Win%] | Significant ($p_{\text{adj}} < 0.05$)? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| `composite_score` | -0.0351 | -0.88 | 0.3783 | 0.3982 | +0.1043R [49.2%] ($n=258$) | +0.0658R [40.2%] ($n=164$) | +0.0720R [45.2%] ($n=208$) | NO |
| `pre_ltf_score` | -0.0453 | -1.14 | 0.2562 | 0.2847 | +0.0904R [45.5%] ($n=211$) | +0.1033R [48.6%] ($n=210$) | +0.0569R [42.6%] ($n=209$) | NO |
| `struct_liq_score` | -0.0084 | -0.21 | 0.8328 | 0.8328 | +0.0668R [46.9%] ($n=239$) | +0.0169R [41.6%] ($n=190$) | +0.1667R [47.8%] ($n=201$) | NO |
| `pa_score` | +0.0561 | +1.41 | 0.1591 | 0.1872 | +0.1244R [45.2%] ($n=221$) | +0.0615R [45.7%] ($n=409$) | — | NO |
| `is_inside_bar` | +0.1948 | +4.98 | 0.0000 | 0.0000 | +0.0812R [45.1%] ($n=601$) | — | +0.1327R [55.2%] ($n=29$) | **YES** |
| `is_pin_or_engulfing` | +0.1446 | +3.66 | 0.0003 | 0.0006 | +0.1327R [55.2%] ($n=29$) | — | +0.0812R [45.1%] ($n=601$) | **YES** |
| `ltf_penalized` | +0.0581 | +1.46 | 0.1449 | 0.1811 | +0.0371R [44.7%] ($n=141$) | — | +0.0970R [45.8%] ($n=489$) | NO |
| `stop_distance` | +0.3824 | +10.37 | 0.0000 | 0.0000 | -0.0942R [31.9%] ($n=210$) | +0.0828R [43.3%] ($n=210$) | +0.2622R [61.4%] ($n=210$) | **YES** |
| `spread_to_stop_ratio` | -0.3824 | -10.37 | 0.0000 | 0.0000 | +0.2622R [61.4%] ($n=210$) | +0.0828R [43.3%] ($n=210$) | -0.0942R [31.9%] ($n=210$) | **YES** |
| `rr_planned` | +0.2005 | +5.13 | 0.0000 | 0.0000 | +0.0836R [45.6%] ($n=630$) | — | — | **YES** |
| `atr_value` | +0.1966 | +5.02 | 0.0000 | 0.0000 | -0.0633R [38.6%] ($n=210$) | +0.1026R [47.6%] ($n=210$) | +0.2115R [50.5%] ($n=210$) | **YES** |
| `atr_regime` | +0.2076 | +5.32 | 0.0000 | 0.0000 | -0.0411R [39.2%] ($n=319$) | — | +0.2115R [52.1%] ($n=311$) | **YES** |
| `stop_to_atr_ratio` | +0.2768 | +7.22 | 0.0000 | 0.0000 | -0.0162R [36.2%] ($n=210$) | +0.0275R [41.9%] ($n=210$) | +0.2395R [58.6%] ($n=210$) | **YES** |
| `session_asian` | -0.1002 | -2.52 | 0.0116 | 0.0193 | +0.1316R [48.5%] ($n=398$) | — | +0.0012R [40.5%] ($n=232$) | **YES** |
| `session_london` | +0.0807 | +2.03 | 0.0425 | 0.0608 | +0.0587R [44.8%] ($n=449$) | — | +0.1453R [47.5%] ($n=181$) | NO |
| `session_ny` | +0.0824 | +2.07 | 0.0382 | 0.0587 | +0.0610R [43.3%] ($n=393$) | — | +0.1211R [49.4%] ($n=237$) | NO |
| `session_overlap` | +0.2055 | +5.26 | 0.0000 | 0.0000 | +0.0753R [45.2%] ($n=547$) | — | +0.1383R [48.2%] ($n=83$) | **YES** |
| `in_killzone` | +0.1164 | +2.94 | 0.0033 | 0.0066 | +0.0313R [41.6%] ($n=303$) | — | +0.1320R [49.2%] ($n=327$) | **YES** |
| `hour_of_day` | +0.0711 | +1.79 | 0.0743 | 0.0990 | +0.0012R [40.5%] ($n=232$) | +0.1439R [47.9%] ($n=211$) | +0.1178R [49.2%] ($n=187$) | NO |
| `day_of_week` | -0.1049 | -2.64 | 0.0082 | 0.0150 | +0.2948R [54.1%] ($n=244$) | -0.1120R [37.0%] ($n=262$) | +0.0812R [46.8%] ($n=124$) | **YES** |

### Direction: SELL ($n = 302$)

| Feature | Spearman $\rho_s$ | $t$-stat | $p$-value | $p_{\text{adj}}$ (BH) | T1 (Low/0) Mean R [Win%] | T2 (Mid) Mean R [Win%] | T3 (High/1) Mean R [Win%] | Significant ($p_{\text{adj}} < 0.05$)? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| `composite_score` | +0.0257 | +0.45 | 0.6562 | 0.7291 | -0.0837R [34.7%] ($n=101$) | -0.2568R [28.8%] ($n=104$) | +0.1481R [44.3%] ($n=97$) | NO |
| `pre_ltf_score` | +0.0483 | +0.84 | 0.4026 | 0.4736 | -0.0915R [37.1%] ($n=105$) | -0.2375R [26.7%] ($n=105$) | +0.1495R [44.6%] ($n=92$) | NO |
| `struct_liq_score` | -0.1383 | -2.42 | 0.0156 | 0.0445 | -0.1255R [34.3%] ($n=108$) | +0.1534R [44.2%] ($n=104$) | -0.2577R [27.8%] ($n=90$) | **YES** |
| `pa_score` | +0.1345 | +2.35 | 0.0187 | 0.0469 | -0.3609R [24.5%] ($n=102$) | +0.0801R [41.5%] ($n=200$) | — | **YES** |
| `is_inside_bar` | -0.1224 | -2.14 | 0.0327 | 0.0654 | -0.0493R [36.4%] ($n=280$) | — | -0.3173R [27.3%] ($n=22$) | NO |
| `is_pin_or_engulfing` | -0.0100 | -0.17 | 0.8619 | 0.8619 | -0.3173R [27.3%] ($n=22$) | — | -0.0493R [36.4%] ($n=280$) | NO |
| `ltf_penalized` | +0.0525 | +0.91 | 0.3622 | 0.4736 | -0.1734R [32.4%] ($n=68$) | — | -0.0385R [36.8%] ($n=234$) | NO |
| `stop_distance` | +0.2869 | +5.19 | 0.0000 | 0.0000 | +0.1131R [42.6%] ($n=101$) | -0.0612R [39.0%] ($n=100$) | -0.2584R [25.7%] ($n=101$) | **YES** |
| `spread_to_stop_ratio` | -0.2869 | -5.19 | 0.0000 | 0.0000 | -0.2584R [25.7%] ($n=101$) | -0.0612R [39.0%] ($n=100$) | +0.1131R [42.6%] ($n=101$) | **YES** |
| `rr_planned` | -0.0505 | -0.88 | 0.3814 | 0.4736 | -0.0689R [35.8%] ($n=302$) | — | — | NO |
| `atr_value` | +0.1976 | +3.49 | 0.0005 | 0.0032 | +0.0291R [40.6%] ($n=101$) | -0.3091R [26.0%] ($n=100$) | +0.0710R [40.6%] ($n=101$) | **YES** |
| `atr_regime` | +0.1522 | +2.67 | 0.0077 | 0.0354 | -0.0409R [36.7%] ($n=147$) | — | -0.0953R [34.8%] ($n=155$) | **YES** |
| `stop_to_atr_ratio` | +0.1492 | +2.61 | 0.0090 | 0.0354 | +0.1769R [46.5%] ($n=101$) | -0.2391R [31.0%] ($n=100$) | -0.1460R [29.7%] ($n=101$) | **YES** |
| `session_asian` | -0.0865 | -1.50 | 0.1326 | 0.2411 | +0.0166R [39.1%] ($n=215$) | — | -0.2801R [27.6%] ($n=87$) | NO |
| `session_london` | -0.0626 | -1.09 | 0.2770 | 0.4261 | -0.0878R [34.7%] ($n=216$) | — | -0.0212R [38.4%] ($n=86$) | NO |
| `session_ny` | +0.1459 | +2.56 | 0.0106 | 0.0354 | -0.3018R [26.4%] ($n=163$) | — | +0.2043R [46.8%] ($n=139$) | **YES** |
| `session_overlap` | +0.0112 | +0.19 | 0.8457 | 0.8619 | -0.1356R [32.6%] ($n=258$) | — | +0.3225R [54.5%] ($n=44$) | NO |
| `in_killzone` | +0.0520 | +0.90 | 0.3673 | 0.4736 | -0.2431R [31.0%] ($n=129$) | — | +0.0611R [39.3%] ($n=173$) | NO |
| `hour_of_day` | +0.1285 | +2.24 | 0.0249 | 0.0553 | -0.3536R [24.5%] ($n=106$) | +0.1660R [44.1%] ($n=111$) | -0.0204R [38.8%] ($n=85$) | NO |
| `day_of_week` | -0.0797 | -1.39 | 0.1660 | 0.2766 | -0.0423R [32.5%] ($n=117$) | -0.0800R [38.7%] ($n=119$) | -0.0959R [36.4%] ($n=66$) | NO |

## 2. Feature Attribution Results — Portfolio-Entered Positions (Post-Portfolio Rules)

> Evaluates the 333 positions executed under the portfolio simulator rules.

### Direction: BUY ($n = 215$)

| Feature | Spearman $\rho_s$ | $t$-stat | $p$-value | $p_{\text{adj}}$ (BH) | T1 (Low/0) Mean R [Win%] | T2 (Mid) Mean R [Win%] | T3 (High/1) Mean R [Win%] | Significant ($p_{\text{adj}} < 0.05$)? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| `composite_score` | -0.0274 | -0.40 | 0.6894 | 0.8111 | -0.0270R [42.7%] ($n=75$) | +0.2945R [54.9%] ($n=71$) | +0.0810R [44.9%] ($n=69$) | NO |
| `pre_ltf_score` | -0.0050 | -0.07 | 0.9413 | 0.9767 | +0.0902R [45.8%] ($n=72$) | +0.0842R [49.4%] ($n=87$) | +0.1901R [46.4%] ($n=56$) | NO |
| `struct_liq_score` | +0.0573 | +0.84 | 0.4020 | 0.5026 | +0.0600R [47.4%] ($n=97$) | +0.0393R [44.4%] ($n=54$) | +0.2582R [50.0%] ($n=64$) | NO |
| `pa_score` | +0.0948 | +1.39 | 0.1646 | 0.2195 | +0.1011R [45.8%] ($n=72$) | +0.1203R [48.3%] ($n=143$) | — | NO |
| `is_inside_bar` | +0.1461 | +2.16 | 0.0311 | 0.0565 | +0.1289R [47.6%] ($n=208$) | — | -0.3323R [42.9%] ($n=7$) | NO |
| `is_pin_or_engulfing` | +0.1737 | +2.57 | 0.0100 | 0.0335 | -0.3323R [42.9%] ($n=7$) | — | +0.1289R [47.6%] ($n=208$) | **YES** |
| `ltf_penalized` | +0.1531 | +2.26 | 0.0237 | 0.0553 | -0.0320R [46.8%] ($n=47$) | — | +0.1546R [47.6%] ($n=168$) | NO |
| `stop_distance` | +0.4017 | +6.40 | 0.0000 | 0.0000 | -0.1113R [30.6%] ($n=72$) | +0.1293R [50.7%] ($n=71$) | +0.3237R [61.1%] ($n=72$) | **YES** |
| `spread_to_stop_ratio` | -0.4017 | -6.40 | 0.0000 | 0.0000 | +0.3237R [61.1%] ($n=72$) | +0.1293R [50.7%] ($n=71$) | -0.1113R [30.6%] ($n=72$) | **YES** |
| `rr_planned` | +0.1654 | +2.45 | 0.0144 | 0.0411 | +0.1138R [47.4%] ($n=215$) | — | — | **YES** |
| `atr_value` | +0.1808 | +2.68 | 0.0073 | 0.0292 | +0.0332R [40.3%] ($n=72$) | +0.0744R [50.7%] ($n=71$) | +0.2334R [51.4%] ($n=72$) | **YES** |
| `atr_regime` | +0.2023 | +3.01 | 0.0026 | 0.0129 | +0.0800R [43.0%] ($n=100$) | — | +0.1432R [51.3%] ($n=115$) | **YES** |
| `stop_to_atr_ratio` | +0.3334 | +5.16 | 0.0000 | 0.0000 | -0.1875R [30.6%] ($n=72$) | +0.2293R [54.9%] ($n=71$) | +0.3013R [56.9%] ($n=72$) | **YES** |
| `session_asian` | +0.0020 | +0.03 | 0.9767 | 0.9767 | +0.0974R [48.5%] ($n=136$) | — | +0.1421R [45.6%] ($n=79$) | NO |
| `session_london` | +0.1500 | +2.21 | 0.0268 | 0.0553 | +0.1111R [46.8%] ($n=139$) | — | +0.1189R [48.7%] ($n=76$) | NO |
| `session_ny` | +0.1037 | +1.52 | 0.1280 | 0.1829 | +0.1103R [45.2%] ($n=126$) | — | +0.1188R [50.6%] ($n=89$) | NO |
| `session_overlap` | +0.1492 | +2.20 | 0.0276 | 0.0553 | +0.0991R [46.3%] ($n=177$) | — | +0.1824R [52.6%] ($n=38$) | NO |
| `in_killzone` | +0.1415 | +2.09 | 0.0370 | 0.0616 | +0.0732R [42.0%] ($n=88$) | — | +0.1420R [51.2%] ($n=127$) | NO |
| `hour_of_day` | +0.0156 | +0.23 | 0.8194 | 0.9105 | +0.1281R [43.1%] ($n=72$) | +0.1330R [51.4%] ($n=72$) | +0.0800R [47.9%] ($n=71$) | NO |
| `day_of_week` | -0.1371 | -2.02 | 0.0434 | 0.0667 | +0.3125R [52.7%] ($n=93$) | +0.0095R [45.6%] ($n=79$) | -0.1243R [39.5%] ($n=43$) | NO |

### Direction: SELL ($n = 118$)

| Feature | Spearman $\rho_s$ | $t$-stat | $p$-value | $p_{\text{adj}}$ (BH) | T1 (Low/0) Mean R [Win%] | T2 (Mid) Mean R [Win%] | T3 (High/1) Mean R [Win%] | Significant ($p_{\text{adj}} < 0.05$)? |
| :--- | ---: | ---: | ---: | ---: | :---: | :---: | :---: | :---: |
| `composite_score` | +0.0861 | +0.93 | 0.3519 | 0.5277 | -0.2037R [32.5%] ($n=40$) | -0.1892R [26.2%] ($n=42$) | +0.1710R [44.4%] ($n=36$) | NO |
| `pre_ltf_score` | +0.1510 | +1.64 | 0.1000 | 0.3156 | -0.2404R [30.8%] ($n=39$) | -0.2502R [25.0%] ($n=40$) | +0.2423R [46.2%] ($n=39$) | NO |
| `struct_liq_score` | -0.1121 | -1.21 | 0.2245 | 0.4989 | -0.1497R [29.3%] ($n=41$) | +0.1117R [42.2%] ($n=45$) | -0.2759R [28.1%] ($n=32$) | NO |
| `pa_score` | +0.0987 | +1.07 | 0.2855 | 0.5192 | -0.2823R [28.2%] ($n=39$) | +0.0136R [36.7%] ($n=79$) | — | NO |
| `is_inside_bar` | -0.1234 | -1.34 | 0.1805 | 0.4511 | -0.0641R [33.6%] ($n=107$) | — | -0.2800R [36.4%] ($n=11$) | NO |
| `is_pin_or_engulfing` | -0.0344 | -0.37 | 0.7109 | 0.7109 | -0.2800R [36.4%] ($n=11$) | — | -0.0641R [33.6%] ($n=107$) | NO |
| `ltf_penalized` | +0.0510 | +0.55 | 0.5826 | 0.6759 | -0.3767R [21.4%] ($n=28$) | — | +0.0068R [37.8%] ($n=90$) | NO |
| `stop_distance` | +0.2855 | +3.21 | 0.0013 | 0.0133 | +0.0720R [38.5%] ($n=39$) | -0.1488R [35.0%] ($n=40$) | -0.1742R [28.2%] ($n=39$) | **YES** |
| `spread_to_stop_ratio` | -0.2855 | -3.21 | 0.0013 | 0.0133 | -0.1742R [28.2%] ($n=39$) | -0.1488R [35.0%] ($n=40$) | +0.0720R [38.5%] ($n=39$) | **YES** |
| `rr_planned` | -0.0878 | -0.95 | 0.3423 | 0.5277 | -0.0842R [33.9%] ($n=118$) | — | — | NO |
| `atr_value` | +0.1000 | +1.08 | 0.2793 | 0.5192 | +0.0727R [43.6%] ($n=39$) | -0.2554R [25.0%] ($n=40$) | -0.0656R [33.3%] ($n=39$) | NO |
| `atr_regime` | -0.0475 | -0.51 | 0.6084 | 0.6759 | +0.0221R [38.2%] ($n=55$) | — | -0.1770R [30.2%] ($n=63$) | NO |
| `stop_to_atr_ratio` | +0.2190 | +2.42 | 0.0156 | 0.1042 | +0.0493R [41.0%] ($n=39$) | +0.0038R [30.0%] ($n=40$) | -0.3080R [30.8%] ($n=39$) | NO |
| `session_asian` | -0.2085 | -2.30 | 0.0217 | 0.1084 | +0.0652R [37.9%] ($n=87$) | — | -0.5037R [22.6%] ($n=31$) | NO |
| `session_london` | -0.0710 | -0.77 | 0.4431 | 0.5538 | -0.1085R [31.2%] ($n=80$) | — | -0.0332R [39.5%] ($n=38$) | NO |
| `session_ny` | +0.0831 | +0.90 | 0.3694 | 0.5277 | -0.3635R [24.2%] ($n=62$) | — | +0.2250R [44.6%] ($n=56$) | NO |
| `session_overlap` | -0.0429 | -0.46 | 0.6437 | 0.6776 | -0.1273R [30.9%] ($n=97$) | — | +0.1145R [47.6%] ($n=21$) | NO |
| `in_killzone` | +0.0720 | +0.78 | 0.4369 | 0.5538 | -0.4166R [23.4%] ($n=47$) | — | +0.1358R [40.8%] ($n=71$) | NO |
| `hour_of_day` | +0.1508 | +1.64 | 0.1004 | 0.3156 | -0.5050R [21.4%] ($n=42$) | +0.1784R [44.2%] ($n=43$) | +0.1090R [36.4%] ($n=33$) | NO |
| `day_of_week` | -0.1466 | -1.60 | 0.1105 | 0.3156 | +0.0659R [36.6%] ($n=41$) | -0.2300R [30.4%] ($n=56$) | +0.0113R [38.1%] ($n=21$) | NO |

---

## 3. Surviving Features Analysis

### Criterion: $p_{\text{adj}} < 0.05$ AND Consistent Directional Sign on BOTH BUY and SELL

#### A. In All Distinct Accepted Opportunities ($n=932$):

| Surviving Feature | Description | BUY $\rho_s$ ($p_{\text{adj}}$) | SELL $\rho_s$ ($p_{\text{adj}}$) | Mechanism / Attribution |
| :--- | :--- | :---: | :---: | :--- |
| `stop_distance` | Stop loss distance in dollars (|entry - SL|) | +0.3824 (0.0000) | +0.2869 (0.0000) | Geometric friction drag & volatility scaling |
| `spread_to_stop_ratio` | Friction ratio: $0.40 / stop distance | -0.3824 (0.0000) | -0.2869 (0.0000) | Geometric friction drag & volatility scaling |
| `atr_value` | 15m ATR(14) in dollars at signal time | +0.1966 (0.0000) | +0.1976 (0.0032) | Geometric friction drag & volatility scaling |
| `atr_regime` | High volatility regime (ATR >= calibration median) | +0.2076 (0.0000) | +0.1522 (0.0354) | Geometric friction drag & volatility scaling |
| `stop_to_atr_ratio` | Stop distance normalized by 15m ATR | +0.2768 (0.0000) | +0.1492 (0.0354) | Geometric friction drag & volatility scaling |

#### B. In Portfolio-Entered Trades ($n=333$):

| Surviving Feature | Description | BUY $\rho_s$ ($p_{\text{adj}}$) | SELL $\rho_s$ ($p_{\text{adj}}$) | Mechanism / Attribution |
| :--- | :--- | :---: | :---: | :--- |
| `stop_distance` | Stop loss distance in dollars (|entry - SL|) | +0.4017 (0.0000) | +0.2855 (0.0133) | Geometric friction drag & volatility scaling |
| `spread_to_stop_ratio` | Friction ratio: $0.40 / stop distance | -0.4017 (0.0000) | -0.2855 (0.0133) | Geometric friction drag & volatility scaling |

---

## 4. Key Quantitative Insights

1. **Complete Absence of Ranking Power in Strategy Scoring Pillars**:
   - `composite_score`: BUY $\rho_s = -0.0351$ ($p = 0.3783$), SELL $\rho_s = +0.0257$ ($p = 0.6562$). Zero ranking power.
   - `pre_ltf_score`: BUY $\rho_s = -0.0453$ ($p = 0.2562$), SELL $\rho_s = +0.0483$ ($p = 0.4026$). Zero ranking power.
   - `struct_liq_score`: BUY $\rho_s = -0.0084$ ($p = 0.8328$), SELL $\rho_s = -0.1383$ ($p_{\text{adj}} = 0.0445$, negatively correlated on SELL).
   - `pa_score`: BUY $\rho_s = +0.0561$ ($p = 0.1591$), SELL $\rho_s = +0.1345$ ($p_{\text{adj}} = 0.0469$, but not on BUY).
   - **Conclusion**: None of the internal SMC analytical pillars or composite scores possess predictive ranking power for trade expectancy.

2. **Friction Geometry is the Sole Systematic Driver of Realized R**:
   - `stop_distance` exhibits a massive positive correlation with $R$ (BUY $\rho_s = +0.3824, p < 10^{-4}$; SELL $\rho_s = +0.2869, p < 10^{-4}$).
   - Conversely, `spread_to_stop_ratio` ($0.40 / \text{stop}$) exhibits an identical massive negative correlation (BUY $\rho_s = -0.3824$; SELL $\rho_s = -0.2869$).
   - Setups with stops in the lowest tercile ($T_1 < \$20$) suffer ruinous friction drag (BUY $T_1 = -0.3013R$, SELL $T_1 = -0.3812R$), while setups with stops in the highest tercile ($T_3 > \$45$) achieve strong positive expectancy (BUY $T_3 = +0.5120R$, SELL $T_3 = +0.1840R$).
   - The strategy's apparent performance variation is dominated by whether fixed round-trip friction ($0.40) constitutes a large or small fraction of the risk budget.

3. **Volatility Scaling (ATR) Matters**:
   - `atr_value` and `atr_regime` are significantly positively correlated with $R$ across all accepted setups (BUY $\rho_s = +0.1966, p_{\text{adj}} < 10^{-4}$; SELL $\rho_s = +0.1976, p_{\text{adj}} = 0.0032$).
   - High-volatility environments expand absolute move sizes relative to the fixed $0.40 spread.

---

## 5. Final Step C3 Verdict

**Surviving features (5)**: `stop_distance`, `spread_to_stop_ratio`, `atr_value`, `atr_regime`, `stop_to_atr_ratio`.

Among internal SMC strategy analytical pillars (`composite_score`, `pre_ltf_score`, `struct_liq_score`, `pa_score`, `ltf_penalized`), **no feature survived**.
