"""
nlp/policy_surprise_vector.py

Policy Surprise Vector Generator.

Translates a HawkishDovishScore and event context into a structured
multi-dimensional PolicySurpriseVector that captures how much the event
deviated from market expectations along key policy dimensions.

The surprise vector is the bridge between NLP output and the Risk Scoring Engine.
It answers: "How surprised should markets be, and along which dimensions?"
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Dict, Optional

import numpy as np
import structlog

from macro_shock.data_schema.models import (
    HawkishDovishScore,
    MacroEvent,
    MarketStateSnapshot,
    PolicyStance,
    PolicySurpriseVector,
)

logger = structlog.get_logger(__name__)

# Prior FOMC meeting stance and expected rate path are normally sourced
# from futures market pricing (Fed funds futures). In the absence of
# live market data, we use a conservative neutral prior.

DEFAULT_PRIOR_STANCE = PolicyStance.NEUTRAL
DEFAULT_PRIOR_RATE_PATH_SCORE = 0.0   # Market expects no change


# ---------------------------------------------------------------------------
# Surprise Magnitude Calibration
# (Empirically estimated from 2010-2024 FOMC events)
# ---------------------------------------------------------------------------

# Market consensus priors by stance -> expected score range
PRIOR_SCORE_RANGES: Dict[PolicyStance, tuple] = {
    PolicyStance.VERY_HAWKISH:   (0.6, 1.0),
    PolicyStance.HAWKISH:        (0.2, 0.6),
    PolicyStance.NEUTRAL:        (-0.2, 0.2),
    PolicyStance.DOVISH:         (-0.6, -0.2),
    PolicyStance.VERY_DOVISH:    (-1.0, -0.6),
    PolicyStance.CRISIS_EASING:  (-1.0, -0.5),
    PolicyStance.AMBIGUOUS:      (-0.3, 0.3),
}


def compute_surprise_magnitude(
    actual_score: float,
    prior_stance: PolicyStance,
    prior_rate_path: float = DEFAULT_PRIOR_RATE_PATH_SCORE,
) -> float:
    """
    Estimate the market surprise as the distance between the actual NLP
    score and the market's prior expectation range.

    Returns a magnitude in [0, 1] (0 = fully expected, 1 = maximum surprise).
    """
    if prior_stance in PRIOR_SCORE_RANGES:
        lo, hi = PRIOR_SCORE_RANGES[prior_stance]
        midpoint = (lo + hi) / 2.0
        range_width = hi - lo
    else:
        midpoint = prior_rate_path
        range_width = 0.4  # default ± 0.2 tolerance

    # How far outside the expected range?
    if lo <= actual_score <= hi:
        # Within expected range: small surprise
        distance = abs(actual_score - midpoint) / (range_width / 2)
        surprise = distance * 0.3  # max 0.3 when at edge of range
    else:
        # Outside expected range: larger surprise
        edge = lo if actual_score < lo else hi
        overshoot = abs(actual_score - edge)
        surprise = min(0.3 + overshoot * 1.4, 1.0)

    return float(np.clip(surprise, 0.0, 1.0))


def compute_net_direction(
    actual_score: float,
    prior_stance: PolicyStance,
) -> float:
    """
    Net direction of surprise: positive = more hawkish than expected,
    negative = more dovish than expected.
    """
    if prior_stance in PRIOR_SCORE_RANGES:
        expected = sum(PRIOR_SCORE_RANGES[prior_stance]) / 2
    else:
        expected = DEFAULT_PRIOR_RATE_PATH_SCORE

    return float(np.clip(actual_score - expected, -1.0, 1.0))


class PolicySurpriseEngine:
    """
    Generates the PolicySurpriseVector from NLP scores and event context.

    This is the final NLP layer output before risk scoring.
    All outputs must be accompanied by interpretable notes.
    """

    def __init__(self, config: Optional[Dict] = None):
        self.config = config or {}

    def generate(
        self,
        event: MacroEvent,
        hawkish_dovish: HawkishDovishScore,
        market_state: Optional[MarketStateSnapshot] = None,
        prior_stance: Optional[PolicyStance] = None,
        market_implied_rate_path: Optional[float] = None,
    ) -> PolicySurpriseVector:
        """
        Generate the PolicySurpriseVector.

        Args:
            event: The detected macro event.
            hawkish_dovish: NLP score from language intelligence engine.
            market_state: Pre-event market context (used for calibration).
            prior_stance: The consensus prior stance before the event.
            market_implied_rate_path: Rate path implied by futures pricing (-1 to +1).
        """
        prior_stance = prior_stance or DEFAULT_PRIOR_STANCE
        prior_rate = market_implied_rate_path or DEFAULT_PRIOR_RATE_PATH_SCORE

        # Core surprise dimensions
        rate_path_surprise = compute_net_direction(
            hawkish_dovish.rate_path_score, prior_stance
        )
        inflation_surprise = self._inflation_dimension_surprise(hawkish_dovish)
        growth_surprise = self._growth_dimension_surprise(hawkish_dovish)
        balance_sheet_surprise = self._balance_sheet_surprise(hawkish_dovish)
        financial_stability_surprise = self._financial_stability_surprise(hawkish_dovish)
        forward_guidance_surprise = (
            0.5 if hawkish_dovish.forward_guidance_change else 0.0
        ) * np.sign(hawkish_dovish.overall_score + 1e-9)

        urgency_surprise = hawkish_dovish.urgency_score

        # Weekend / emergency amplification
        if event.full_weekend_gap:
            urgency_surprise = min(urgency_surprise + 0.2, 1.0)

        if hawkish_dovish.crisis_language_detected:
            financial_stability_surprise = min(
                abs(financial_stability_surprise) + 0.3, 1.0
            ) * (-1.0)  # Always dovish when crisis language present

        # Composite magnitude
        dimension_scores = [
            abs(rate_path_surprise),
            abs(inflation_surprise),
            abs(growth_surprise),
            abs(balance_sheet_surprise),
            abs(financial_stability_surprise),
            abs(forward_guidance_surprise),
            urgency_surprise,
        ]
        composite_magnitude = float(np.clip(
            np.average(
                dimension_scores,
                weights=[0.30, 0.20, 0.15, 0.10, 0.15, 0.05, 0.05]
            ),
            0.0,
            1.0,
        ))

        # Boost magnitude for emergency events
        if event.is_weekend or event.full_weekend_gap:
            composite_magnitude = min(composite_magnitude * 1.3, 1.0)

        net_direction = compute_net_direction(hawkish_dovish.overall_score, prior_stance)

        interpretation = self._build_interpretation(
            hawkish_dovish, event, prior_stance, composite_magnitude, net_direction
        )

        vector = PolicySurpriseVector(
            event_id=event.event_id,
            rate_path_surprise=float(rate_path_surprise),
            inflation_outlook_surprise=float(inflation_surprise),
            growth_outlook_surprise=float(growth_surprise),
            balance_sheet_surprise=float(balance_sheet_surprise),
            financial_stability_surprise=float(financial_stability_surprise),
            forward_guidance_surprise=float(forward_guidance_surprise),
            urgency_surprise=float(urgency_surprise),
            composite_surprise_magnitude=composite_magnitude,
            net_direction=float(net_direction),
            hawkish_dovish=hawkish_dovish,
            key_phrases=(hawkish_dovish.hawkish_phrases + hawkish_dovish.dovish_phrases)[:10],
            interpretation_notes=interpretation,
            confidence=hawkish_dovish.confidence,
        )

        logger.info(
            "surprise_vector_generated",
            event_id=event.event_id,
            composite_magnitude=f"{composite_magnitude:.3f}",
            net_direction=f"{net_direction:+.3f}",
            stance=hawkish_dovish.stance,
            crisis_language=hawkish_dovish.crisis_language_detected,
        )

        return vector

    def _inflation_dimension_surprise(self, hd: HawkishDovishScore) -> float:
        """How much did the inflation commentary deviate from expectations?"""
        base = hd.inflation_concern_score
        # Upside inflation surprise is hawkish surprise
        return float(np.clip(base * 0.8, -1.0, 1.0))

    def _growth_dimension_surprise(self, hd: HawkishDovishScore) -> float:
        """Growth concern surprise: negative growth surprise is dovish shock."""
        base = hd.growth_concern_score
        return float(np.clip(base * 0.7, -1.0, 1.0))

    def _balance_sheet_surprise(self, hd: HawkishDovishScore) -> float:
        """QE/QT surprise dimension."""
        # Crude: hawkish text = QT signal, dovish text = QE signal
        overall = hd.overall_score
        return float(np.clip(overall * 0.6, -1.0, 1.0))

    def _financial_stability_surprise(self, hd: HawkishDovishScore) -> float:
        """Financial stability concern surprise."""
        base = hd.financial_stability_score
        if hd.crisis_language_detected:
            return float(np.clip(base - 0.4, -1.0, 1.0))  # Crisis = dovish bias
        return float(np.clip(base * 0.5, -1.0, 1.0))

    def _build_interpretation(
        self,
        hd: HawkishDovishScore,
        event: MacroEvent,
        prior_stance: PolicyStance,
        magnitude: float,
        direction: float,
    ) -> str:
        """Build a human-readable interpretation of the surprise vector."""
        lines = []

        direction_word = "hawkish" if direction > 0.1 else "dovish" if direction < -0.1 else "neutral"
        magnitude_word = (
            "highly significant" if magnitude > 0.7
            else "significant" if magnitude > 0.45
            else "moderate" if magnitude > 0.25
            else "minimal"
        )

        lines.append(
            f"Policy communication assessed as {magnitude_word} {direction_word} surprise "
            f"(magnitude={magnitude:.2f}, direction={direction:+.2f})."
        )
        lines.append(
            f"Prior expected stance: {prior_stance.value}. "
            f"Actual assessed stance: {hd.stance.value}."
        )

        if hd.crisis_language_detected:
            lines.append("ALERT: Crisis language detected. Financial stability concerns raised.")
        if hd.policy_reversal_language:
            lines.append("Policy reversal language present — prior guidance may be invalidated.")
        if hd.forward_guidance_change:
            lines.append("Forward guidance has been revised or removed.")
        if event.full_weekend_gap:
            lines.append(
                "Event occurred during weekend gap corridor. "
                "First price discovery deferred to next futures session / Monday open."
            )

        if hd.hawkish_phrases:
            lines.append(f"Key hawkish phrases: {', '.join(hd.hawkish_phrases[:3])}.")
        if hd.dovish_phrases:
            lines.append(f"Key dovish phrases: {', '.join(hd.dovish_phrases[:3])}.")

        return " ".join(lines)
