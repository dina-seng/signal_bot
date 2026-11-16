"""Quality Tier Classification for CRT Signals.

Tiers:
- A+ (>= 85.0 and all qualification gates passed): Highest conviction, full alert.
- A  (>= 75.0 and all qualification gates passed): Standard institutional setup, alert.
- B  (>= 65.0): Secondary setup, dashboard/watchlist only, NO Telegram alert.
- C  (< 65.0): Sub-threshold setup.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class QualityTierResult:
    """Result of Quality Tier classification."""
    tier: str  # "A+", "A", "B", "C"
    tier_label: str
    is_actionable: bool
    should_alert_telegram: bool
    description: str


def determine_quality_tier(score: float, gatekeeper_passed: bool) -> QualityTierResult:
    """Determine setup quality tier based on confluence score and qualification gates."""
    if not gatekeeper_passed:
        if score >= 65.0:
            return QualityTierResult(
                tier="B",
                tier_label="🥈 B Quality (Dashboard Only)",
                is_actionable=False,
                should_alert_telegram=False,
                description="Moderate confluence or pending minor gate; displayed on dashboard only.",
            )
        return QualityTierResult(
            tier="C",
            tier_label="⚪ C Quality (Unqualified)",
            is_actionable=False,
            should_alert_telegram=False,
            description="Sub-threshold score or failed gate.",
        )

    if score >= 85.0:
        return QualityTierResult(
            tier="A+",
            tier_label="💎 A+ Quality (High Conviction)",
            is_actionable=True,
            should_alert_telegram=True,
            description="Pristine confluence across Structure, Liquidity, and Price Action.",
        )
    elif score >= 75.0:
        return QualityTierResult(
            tier="A",
            tier_label="🥇 A Quality (Standard Institutional)",
            is_actionable=True,
            should_alert_telegram=True,
            description="Solid institutional setup meeting all core SMC criteria.",
        )
    elif score >= 65.0:
        return QualityTierResult(
            tier="B",
            tier_label="🥈 B Quality (Dashboard Only)",
            is_actionable=False,
            should_alert_telegram=False,
            description="Qualified secondary setup; restricted to dashboard/watchlist only.",
        )
    else:
        return QualityTierResult(
            tier="C",
            tier_label="⚪ C Quality (Unqualified)",
            is_actionable=False,
            should_alert_telegram=False,
            description="Score below minimum qualification threshold.",
        )

