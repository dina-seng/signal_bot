# SMC Analysis — Step 1: Baseline Controls & Edge Evaluation

## 1. Overview and Protocol Verification

- **Production Source Code**: `server/scripts/smc_replay.py:build_market_trade` and `server/scripts/crt_replay.py:simulate_outcome`
- **Friction Model**: Flat \$0.40 round-trip spread deduction per trade (exact `simulate_outcome` parity)
- **Checkpoints**: `reports/smc_replay_extended/checkpoints/` (45 monthly files, 2023-03 through 2026-11)
- **Walk-forward Boundaries**:
  - Calibration: 2023-03-01 00:00 → 2025-05-21 08:15 UTC (60%)
  - Validation: 2025-05-21 08:15 → 2026-02-16 03:00 UTC (20%)
  - Test: 2026-02-16 03:00 → 2026-11-15 15:00 UTC (20%)
- **Data Hygiene Warning**: Validation and test sets were observed during earlier exploratory iterations (commits `4424a64`, `5b88873`, `2db6eb1`) and are **no longer clean out-of-sample data**.
- **Edge Definition**: Edge is demonstrated **ONLY** if the real accepted trade mean R achieves a percentile rank $\ge 97.5\%$ on **BOTH** validation and test splits against the random-direction control.

---

## 2. Seed List
- **Number of Seeds**: 1,000 seeds
- **Seed Values**: Integers 1 through 1000 inclusive (`range(1, 1001)`)
- **Full Seed List**:
`1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81, 82, 83, 84, 85, 86, 87, 88, 89, 90, 91, 92, 93, 94, 95, 96, 97, 98, 99, 100, 101, 102, 103, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118, 119, 120, 121, 122, 123, 124, 125, 126, 127, 128, 129, 130, 131, 132, 133, 134, 135, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 150, 151, 152, 153, 154, 155, 156, 157, 158, 159, 160, 161, 162, 163, 164, 165, 166, 167, 168, 169, 170, 171, 172, 173, 174, 175, 176, 177, 178, 179, 180, 181, 182, 183, 184, 185, 186, 187, 188, 189, 190, 191, 192, 193, 194, 195, 196, 197, 198, 199, 200, 201, 202, 203, 204, 205, 206, 207, 208, 209, 210, 211, 212, 213, 214, 215, 216, 217, 218, 219, 220, 221, 222, 223, 224, 225, 226, 227, 228, 229, 230, 231, 232, 233, 234, 235, 236, 237, 238, 239, 240, 241, 242, 243, 244, 245, 246, 247, 248, 249, 250, 251, 252, 253, 254, 255, 256, 257, 258, 259, 260, 261, 262, 263, 264, 265, 266, 267, 268, 269, 270, 271, 272, 273, 274, 275, 276, 277, 278, 279, 280, 281, 282, 283, 284, 285, 286, 287, 288, 289, 290, 291, 292, 293, 294, 295, 296, 297, 298, 299, 300, 301, 302, 303, 304, 305, 306, 307, 308, 309, 310, 311, 312, 313, 314, 315, 316, 317, 318, 319, 320, 321, 322, 323, 324, 325, 326, 327, 328, 329, 330, 331, 332, 333, 334, 335, 336, 337, 338, 339, 340, 341, 342, 343, 344, 345, 346, 347, 348, 349, 350, 351, 352, 353, 354, 355, 356, 357, 358, 359, 360, 361, 362, 363, 364, 365, 366, 367, 368, 369, 370, 371, 372, 373, 374, 375, 376, 377, 378, 379, 380, 381, 382, 383, 384, 385, 386, 387, 388, 389, 390, 391, 392, 393, 394, 395, 396, 397, 398, 399, 400, 401, 402, 403, 404, 405, 406, 407, 408, 409, 410, 411, 412, 413, 414, 415, 416, 417, 418, 419, 420, 421, 422, 423, 424, 425, 426, 427, 428, 429, 430, 431, 432, 433, 434, 435, 436, 437, 438, 439, 440, 441, 442, 443, 444, 445, 446, 447, 448, 449, 450, 451, 452, 453, 454, 455, 456, 457, 458, 459, 460, 461, 462, 463, 464, 465, 466, 467, 468, 469, 470, 471, 472, 473, 474, 475, 476, 477, 478, 479, 480, 481, 482, 483, 484, 485, 486, 487, 488, 489, 490, 491, 492, 493, 494, 495, 496, 497, 498, 499, 500, 501, 502, 503, 504, 505, 506, 507, 508, 509, 510, 511, 512, 513, 514, 515, 516, 517, 518, 519, 520, 521, 522, 523, 524, 525, 526, 527, 528, 529, 530, 531, 532, 533, 534, 535, 536, 537, 538, 539, 540, 541, 542, 543, 544, 545, 546, 547, 548, 549, 550, 551, 552, 553, 554, 555, 556, 557, 558, 559, 560, 561, 562, 563, 564, 565, 566, 567, 568, 569, 570, 571, 572, 573, 574, 575, 576, 577, 578, 579, 580, 581, 582, 583, 584, 585, 586, 587, 588, 589, 590, 591, 592, 593, 594, 595, 596, 597, 598, 599, 600, 601, 602, 603, 604, 605, 606, 607, 608, 609, 610, 611, 612, 613, 614, 615, 616, 617, 618, 619, 620, 621, 622, 623, 624, 625, 626, 627, 628, 629, 630, 631, 632, 633, 634, 635, 636, 637, 638, 639, 640, 641, 642, 643, 644, 645, 646, 647, 648, 649, 650, 651, 652, 653, 654, 655, 656, 657, 658, 659, 660, 661, 662, 663, 664, 665, 666, 667, 668, 669, 670, 671, 672, 673, 674, 675, 676, 677, 678, 679, 680, 681, 682, 683, 684, 685, 686, 687, 688, 689, 690, 691, 692, 693, 694, 695, 696, 697, 698, 699, 700, 701, 702, 703, 704, 705, 706, 707, 708, 709, 710, 711, 712, 713, 714, 715, 716, 717, 718, 719, 720, 721, 722, 723, 724, 725, 726, 727, 728, 729, 730, 731, 732, 733, 734, 735, 736, 737, 738, 739, 740, 741, 742, 743, 744, 745, 746, 747, 748, 749, 750, 751, 752, 753, 754, 755, 756, 757, 758, 759, 760, 761, 762, 763, 764, 765, 766, 767, 768, 769, 770, 771, 772, 773, 774, 775, 776, 777, 778, 779, 780, 781, 782, 783, 784, 785, 786, 787, 788, 789, 790, 791, 792, 793, 794, 795, 796, 797, 798, 799, 800, 801, 802, 803, 804, 805, 806, 807, 808, 809, 810, 811, 812, 813, 814, 815, 816, 817, 818, 819, 820, 821, 822, 823, 824, 825, 826, 827, 828, 829, 830, 831, 832, 833, 834, 835, 836, 837, 838, 839, 840, 841, 842, 843, 844, 845, 846, 847, 848, 849, 850, 851, 852, 853, 854, 855, 856, 857, 858, 859, 860, 861, 862, 863, 864, 865, 866, 867, 868, 869, 870, 871, 872, 873, 874, 875, 876, 877, 878, 879, 880, 881, 882, 883, 884, 885, 886, 887, 888, 889, 890, 891, 892, 893, 894, 895, 896, 897, 898, 899, 900, 901, 902, 903, 904, 905, 906, 907, 908, 909, 910, 911, 912, 913, 914, 915, 916, 917, 918, 919, 920, 921, 922, 923, 924, 925, 926, 927, 928, 929, 930, 931, 932, 933, 934, 935, 936, 937, 938, 939, 940, 941, 942, 943, 944, 945, 946, 947, 948, 949, 950, 951, 952, 953, 954, 955, 956, 957, 958, 959, 960, 961, 962, 963, 964, 965, 966, 967, 968, 969, 970, 971, 972, 973, 974, 975, 976, 977, 978, 979, 980, 981, 982, 983, 984, 985, 986, 987, 988, 989, 990, 991, 992, 993, 994, 995, 996, 997, 998, 999, 1000`

---

## 3. Results by Split

### A. Real Strategy Performance (Baseline)
| Split | Opportunities (n) | Win Rate | Mean R | Total R |
| :--- | ---: | ---: | ---: | ---: |
| Calibration | 932 | 42.38% | +0.0342 | +31.87R |
| Validation | 266 | 49.25% | +0.2999 | +79.77R |
| Test | 293 | 43.00% | +0.0716 | +20.98R |
| **Pooled** | **1,491** | **43.73%** | **+0.0890** | **+132.63R** |

---

### B. Control (a): Random Direction (1,000 Seeds)
Each accepted trade retains its identical entry timestamp, entry price, stop distance, and TP geometry ($TP1=2.0R, TP2=3.0R$), with direction drawn uniformly at random ($p=0.5$).

| Split | Real Mean R | Random Dist Mean | Dist Std | Dist [Min, Max] | 5% - 95% CI | Win Rate (Dist Mean) | Percentile Rank | Edge Pass? ($\ge 97.5\%$) |
| :--- | ---: | ---: | ---: | :---: | :---: | ---: | ---: | :---: |
| Calibration | +0.0342 | -0.0249 | 0.0347 | [-0.1172, +0.0880] | [-0.0838, +0.0328] | 38.97% | **95.5%** | NO |
| Validation | +0.2999 | -0.0124 | 0.0695 | [-0.2374, +0.1937] | [-0.1257, +0.1016] | 37.85% | **100.0%** | YES |
| Test | +0.0716 | +0.1114 | 0.0717 | [-0.1241, +0.3602] | [-0.0083, +0.2268] | 42.75% | **27.8%** | **NO** |
| **Pooled** | **+0.0890** | **+0.0027** | **0.0285** | **[-0.0858, +0.0813]** | **[-0.0440, +0.0496]** | **39.47%** | **100.0%** | NO |

---

### C. Control (b): Always-BUY vs Always-SELL (Drift Controls)
Evaluates directional drift by simulating a 100% BUY or 100% SELL allocation across the identical accepted signal timestamps and stop distances.

| Split | Real Strategy Mean R (WR) | Always-BUY Mean R (WR) | Always-SELL Mean R (WR) | Drift Bias Observed |
| :--- | :--- | :--- | :--- | :--- |
| Calibration | +0.0342 (42.38%) | +0.1346 (46.78%) | -0.1834 (31.22%) | Strong Bull Drift (Always-BUY outperforms Real by +0.1004R) |
| Validation | +0.2999 (49.25%) | +0.4894 (56.39%) | -0.5180 (19.17%) | Severe Bull Drift (Always-BUY outperforms Real by +0.1895R) |
| Test | +0.0716 (43.00%) | -0.0686 (37.88%) | +0.2853 (47.44%) | Bear Drift / Chop (Always-SELL outperforms Real by +0.2137R) |
| **Pooled** | **+0.0890 (43.73%)** | **+0.1580 (46.75%)** | **-0.1510 (32.26%)** | Overall Upward Drift Dominance |

---

### D. Control (c): Random Timestamps (1,000 Seeds)
Matches the exact number of monthly trades $N_m$ drawn uniformly from open-market 15m bars, using the empirical monthly stop distances and the pooled accepted BUY/SELL ratio ($66.0\%$ BUY).

| Split | Real Mean R | Random TS Dist Mean | Dist Std | Dist [Min, Max] | 5% - 95% CI | Win Rate (Dist Mean) | Percentile Rank |
| :--- | ---: | ---: | ---: | :---: | :---: | ---: | ---: |
| Calibration | +0.0342 | +0.0673 | 0.0426 | [-0.0684, +0.2434] | [-0.0012, +0.1358] | 41.92% | **22.5%** |
| Validation | +0.2999 | +0.1962 | 0.0755 | [-0.0045, +0.4725] | [+0.0775, +0.3283] | 46.04% | **90.8%** |
| Test | +0.0716 | -0.0523 | 0.0768 | [-0.2696, +0.1977] | [-0.1711, +0.0734] | 37.32% | **94.5%** |
| **Pooled** | **+0.0890** | **+0.0710** | **0.0341** | **[-0.0314, +0.1777]** | **[+0.0149, +0.1255]** | **41.90%** | **69.4%** |

---

## 4. Edge Verdict

> **NON-NEGOTIABLE CRITERION**: "Define 'edge demonstrated' ONLY as percentile $\ge 97.5$ on BOTH validation and test (and state calibration too)."

- **Calibration Random Direction Percentile**: **95.5%** (Failed; $< 97.5\%$)
- **Validation Random Direction Percentile**: **100.0%** (Passed; $\ge 97.5\%$)
- **Test Random Direction Percentile**: **27.8%** (Failed; far below $97.5\%$)

### Verdict Line:
**EDGE NOT DEMONSTRATED**. The SMC strategy fails the required $\ge 97.5\%$ percentile benchmark on the test split (27.8%) and on the calibration split (95.5%). On the test split, flipping a coin for direction yields an average return of +0.1114R, outperforming the actual SMC signals (+0.0716R). The strategy's positive returns in validation (+0.2999R) are entirely explained by underlying market drift (Always-BUY returned +0.4894R at the same timestamps).

---

## 5. Summary Table

| Control Check | Calibration | Validation | Test | Target ($\ge 97.5\%$) | Verdict |
| :--- | :---: | :---: | :---: | :---: | :---: |
| **Random Direction Percentile** | 95.5% | 100.0% | 27.8% | Both Val & Test $\ge 97.5\%$ | **FAIL (No Edge Demonstrated)** |
| **Always-BUY Outperformed Real?** | YES (+0.1346 vs +0.0342) | YES (+0.4894 vs +0.2999) | NO (-0.0686 vs +0.0716) | N/A | Market Drift Explains Gains |
| **Always-SELL Outperformed Real?** | NO (-0.1834 vs +0.0342) | NO (-0.5180 vs +0.2999) | YES (+0.2853 vs +0.0716) | N/A | Regime Inversion on Test |
