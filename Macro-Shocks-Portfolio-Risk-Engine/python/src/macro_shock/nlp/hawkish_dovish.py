"""
nlp/hawkish_dovish.py

Policy Language Intelligence Engine.

Two-stage architecture:
  Stage 1: Rule-based lexicon scoring (fast, interpretable, always available)
  Stage 2: Transformer embedding similarity (richer context, ~2-5s latency)

The lexicon scorer is always the operative Layer 1 signal. The transformer
layer is additive and produces a confidence-weighted ensemble when available.

Design note: We do NOT use LLMs for real-time scoring in the critical path.
LLMs are used offline for corpus analysis and lexicon improvement.
For sub-second latency requirements, the lexicon stage alone is used.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import structlog

from macro_shock.data_schema.models import HawkishDovishScore, PolicyStance

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Hawkish / Dovish Lexicons
# ---------------------------------------------------------------------------
# Scores are in [-1, +1] per phrase. Positive = hawkish, Negative = dovish.
# Weights reflect magnitude of typical market impact of that phrase.

HAWKISH_LEXICON: Dict[str, float] = {
    # Rate signals
    "raise rates": 0.90,
    "increase rates": 0.90,
    "rate hike": 0.90,
    "hike rates": 0.90,
    "tighten policy": 0.85,
    "tightening": 0.75,
    "restrictive policy": 0.80,
    "sufficiently restrictive": 0.85,
    "further firming": 0.80,
    "higher for longer": 0.90,
    "not cutting rates": 0.80,
    "premature to cut": 0.75,
    "not done yet": 0.70,
    "more work to do": 0.65,
    "additional increases": 0.85,
    # Inflation signals
    "inflation too high": 0.75,
    "persistent inflation": 0.70,
    "inflation not under control": 0.80,
    "above target": 0.65,
    "inflation expectations unanchored": 0.90,
    "wage-price spiral": 0.80,
    "second-round effects": 0.75,
    "core inflation elevated": 0.70,
    # Economy signals (strong = less room to cut)
    "labor market strong": 0.50,
    "robust growth": 0.45,
    "overheating": 0.70,
    "tight labor market": 0.60,
    "strong consumer": 0.40,
    # Balance sheet / QT
    "balance sheet reduction": 0.60,
    "quantitative tightening": 0.65,
    "runoff": 0.55,
    "reducing holdings": 0.55,
}

DOVISH_LEXICON: Dict[str, float] = {
    # Rate signals
    "cut rates": -0.90,
    "lower rates": -0.90,
    "rate cut": -0.90,
    "reduce rates": -0.85,
    "ease policy": -0.85,
    "easing": -0.75,
    "accommodative": -0.70,
    "pause rate hikes": -0.75,
    "hold rates": -0.50,
    "patient approach": -0.55,
    "data dependent": -0.35,
    # Emergency / crisis signals  
    "emergency rate cut": -1.0,
    "intermeeting cut": -1.0,
    "emergency action": -1.0,
    "extraordinary measures": -0.95,
    "crisis measures": -0.95,
    "backstop": -0.80,
    "lender of last resort": -0.85,
    "unlimited purchases": -0.90,
    "whatever it takes": -1.0,
    # Inflation / growth dovish signals
    "inflation declining": -0.65,
    "inflation cooling": -0.60,
    "inflation under control": -0.70,
    "inflation approaching target": -0.65,
    "slowing growth": -0.60,
    "recession risk": -0.65,
    "growth concerns": -0.55,
    "labor market softening": -0.60,
    "unemployment rising": -0.65,
    # QE signals
    "asset purchases": -0.70,
    "quantitative easing": -0.80,
    "expand balance sheet": -0.75,
    "bond purchases": -0.70,
    "securities purchases": -0.65,
}

CRISIS_LANGUAGE: List[str] = [
    "systemic risk",
    "financial stability",
    "market dysfunction",
    "disorderly markets",
    "liquidity crisis",
    "bank failure",
    "bank run",
    "contagion",
    "circuit breaker",
    "market closure",
    "trading halt",
    "emergency",
    "unprecedented",
    "extraordinary",
    "crisis",
    "severe stress",
    "financial stress",
    "market dislocation",
]

POLICY_REVERSAL_PHRASES: List[str] = [
    "reverse course",
    "pivot",
    "change direction",
    "reconsider",
    "adjust our view",
    "update our assessment",
    "new information",
    "recalibrate",
    "reassess",
    "fundamentally different",
]

FORWARD_GUIDANCE_CHANGE_PHRASES: List[str] = [
    "no longer expect",
    "changed our outlook",
    "updated guidance",
    "removing forward guidance",
    "conditional on",
    "no longer committed",
    "may not",
    "open question",
]

UNCERTAINTY_PHRASES: List[str] = [
    "highly uncertain",
    "significant uncertainty",
    "difficult to predict",
    "unusual uncertainty",
    "unprecedented uncertainty",
    "uncertain path",
    "wide range of outcomes",
    "depend on data",
]

URGENCY_PHRASES: List[str] = [
    "act quickly",
    "immediate action",
    "urgent",
    "without delay",
    "promptly",
    "as soon as possible",
    "imminent",
    "no time to waste",
    "must act now",
    "act decisively",
]


# ---------------------------------------------------------------------------
# Lexicon Scorer
# ---------------------------------------------------------------------------

class LexiconScorer:
    """
    Rule-based hawkish/dovish scorer.

    Scans text for known policy phrases and computes a weighted aggregate score.
    Always available, sub-millisecond latency, fully interpretable.
    Used as primary signal and fallback when transformer unavailable.
    """

    def __init__(self, custom_lexicon: Optional[Dict[str, float]] = None):
        self.hawkish = dict(HAWKISH_LEXICON)
        self.dovish = dict(DOVISH_LEXICON)
        if custom_lexicon:
            # Custom entries override defaults
            for phrase, score in custom_lexicon.items():
                if score > 0:
                    self.hawkish[phrase] = score
                else:
                    self.dovish[phrase] = score

    def score(
        self,
        text: str,
        section_weights: Optional[Dict[str, float]] = None,
    ) -> HawkishDovishScore:
        """
        Score a policy text document.

        Args:
            text: Full or partial transcript / statement text
            section_weights: Dict mapping section names to weights.
                             e.g., {"prepared_remarks": 1.2, "qa": 0.8}
                             Not used in base implementation; provided for subclass use.

        Returns:
            HawkishDovishScore with component breakdown and evidence list.
        """
        if not text or not text.strip():
            return HawkishDovishScore(
                overall_score=0.0,
                stance=PolicyStance.AMBIGUOUS,
                confidence=0.0,
                method="lexicon",
            )

        text_lower = text.lower()
        text_lower = re.sub(r"[^\w\s\-']", " ", text_lower)

        hawkish_hits: List[Tuple[str, float]] = []
        dovish_hits: List[Tuple[str, float]] = []

        # Count phrase occurrences with diminishing returns for repetition
        def _find_hits(lexicon: Dict[str, float]) -> List[Tuple[str, float]]:
            hits = []
            for phrase, weight in sorted(lexicon.items(), key=lambda x: len(x[0]), reverse=True):
                count = text_lower.count(phrase)
                if count > 0:
                    # Diminishing returns: sqrt of count beyond first hit
                    effective_count = 1 + (count - 1) ** 0.5 if count > 1 else 1
                    hits.append((phrase, weight * effective_count))
            return hits

        hawkish_hits = _find_hits(self.hawkish)
        dovish_hits = _find_hits(self.dovish)

        # Compute raw scores
        raw_hawkish = sum(w for _, w in hawkish_hits)
        raw_dovish = sum(abs(w) for _, w in dovish_hits)

        total_signal = raw_hawkish + raw_dovish
        if total_signal < 0.01:
            overall_score = 0.0
            confidence = 0.1
        else:
            # Normalize to [-1, +1]
            overall_score = np.clip(
                (raw_hawkish - raw_dovish) / max(total_signal, 1.0), -1.0, 1.0
            )
            # Confidence scales with total signal volume
            confidence = min(total_signal / 5.0, 1.0)  # 5.0 chosen as saturation point

        # Component scores
        rate_path_score = self._component_score(
            text_lower,
            ["rate hike", "raise rates", "cut rates", "rate cut", "lower rates",
             "higher for longer", "premature to cut", "pause rate hikes"],
        )
        inflation_concern_score = self._component_score(
            text_lower,
            ["inflation too high", "persistent inflation", "inflation not under control",
             "inflation declining", "inflation cooling", "approaching target"],
        )
        growth_concern_score = self._component_score(
            text_lower,
            ["slowing growth", "recession risk", "robust growth", "overheating",
             "growth concerns", "strong consumer"],
        )
        financial_stability_score = self._component_score(
            text_lower,
            ["financial stability", "systemic risk", "market dysfunction",
             "contagion", "disorderly"],
        )

        # Urgency score (always positive)
        urgency_score = min(
            sum(1.0 for p in URGENCY_PHRASES if p in text_lower) / 3.0, 1.0
        )

        # Boolean flags
        crisis_language = any(p in text_lower for p in CRISIS_LANGUAGE)
        policy_reversal = any(p in text_lower for p in POLICY_REVERSAL_PHRASES)
        forward_guidance_change = any(p in text_lower for p in FORWARD_GUIDANCE_CHANGE_PHRASES)

        stance = self._score_to_stance(overall_score, crisis_language)

        return HawkishDovishScore(
            overall_score=float(overall_score),
            stance=stance,
            confidence=float(confidence),
            rate_path_score=rate_path_score,
            inflation_concern_score=inflation_concern_score,
            growth_concern_score=growth_concern_score,
            financial_stability_score=financial_stability_score,
            urgency_score=urgency_score,
            hawkish_phrases=[p for p, _ in sorted(hawkish_hits, key=lambda x: abs(x[1]), reverse=True)[:5]],
            dovish_phrases=[p for p, _ in sorted(dovish_hits, key=lambda x: abs(x[1]), reverse=True)[:5]],
            crisis_language_detected=crisis_language,
            policy_reversal_language=policy_reversal,
            forward_guidance_change=forward_guidance_change,
            method="lexicon",
        )

    def _component_score(self, text: str, phrases: List[str]) -> float:
        """Score a single thematic component from a list of indicator phrases."""
        total = 0.0
        count = 0
        for phrase in phrases:
            if phrase in text:
                score = self.hawkish.get(phrase, self.dovish.get(phrase, 0.0))
                total += score
                count += 1
        if count == 0:
            return 0.0
        return float(np.clip(total / max(count, 1), -1.0, 1.0))

    @staticmethod
    def _score_to_stance(score: float, is_crisis: bool) -> PolicyStance:
        if is_crisis and score < -0.3:
            return PolicyStance.CRISIS_EASING
        if score >= 0.60:
            return PolicyStance.VERY_HAWKISH
        if score >= 0.25:
            return PolicyStance.HAWKISH
        if score <= -0.60:
            return PolicyStance.VERY_DOVISH
        if score <= -0.25:
            return PolicyStance.DOVISH
        if abs(score) < 0.15:
            return PolicyStance.NEUTRAL
        return PolicyStance.AMBIGUOUS


# ---------------------------------------------------------------------------
# Transformer Scorer (Optional Enhancement)
# ---------------------------------------------------------------------------

class TransformerScorer:
    """
    Embedding-based semantic scorer using sentence-transformers.

    Computes cosine similarity between the input text and a curated set of
    anchor sentences representing the extremes of the hawkish-dovish spectrum.

    Requires: sentence-transformers library (optional dependency).
    Falls back gracefully to None if not available.

    Latency: ~2-5 seconds per document on CPU; ~200ms on GPU.
    NOT used in the real-time critical path.
    """

    # Anchor sentences for each pole
    HAWKISH_ANCHORS = [
        "We will raise interest rates as many times as necessary to bring inflation under control.",
        "Price stability is our primary mandate and we will not cut rates prematurely.",
        "The labor market remains tight and monetary policy must remain restrictive.",
        "Inflation expectations becoming unanchored would be very damaging.",
        "We will be data dependent but we are far from done with rate increases.",
    ]

    DOVISH_ANCHORS = [
        "We are prepared to cut rates aggressively to support the economy.",
        "The risks to the downside have grown significantly and we must act.",
        "We will provide whatever accommodation is necessary to stabilize financial conditions.",
        "The balance sheet will be expanded to ensure adequate liquidity in the system.",
        "Emergency measures are warranted given the severe deterioration in financial conditions.",
    ]

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        self.model = None
        self.model_name = model_name
        self._hawkish_embeddings: Optional[np.ndarray] = None
        self._dovish_embeddings: Optional[np.ndarray] = None
        self._initialize()

    def _initialize(self) -> None:
        try:
            from sentence_transformers import SentenceTransformer
            self.model = SentenceTransformer(self.model_name)
            self._hawkish_embeddings = self.model.encode(self.HAWKISH_ANCHORS)
            self._dovish_embeddings = self.model.encode(self.DOVISH_ANCHORS)
            logger.info("transformer_scorer_initialized", model=self.model_name)
        except ImportError:
            logger.warning(
                "sentence_transformers_not_available",
                fallback="transformer scoring disabled",
            )

    def is_available(self) -> bool:
        return self.model is not None

    def score(self, text: str) -> Optional[float]:
        """
        Returns a float in [-1, +1] or None if not available.
        Positive = hawkish, Negative = dovish.
        """
        if not self.is_available():
            return None

        # Embed the first 512 tokens of input (chunking for long docs)
        text_embedding = self.model.encode([text[:2048]])[0]

        hawkish_sim = float(np.mean(
            [self._cosine_sim(text_embedding, h) for h in self._hawkish_embeddings]
        ))
        dovish_sim = float(np.mean(
            [self._cosine_sim(text_embedding, d) for d in self._dovish_embeddings]
        ))

        score = (hawkish_sim - dovish_sim) / max(hawkish_sim + dovish_sim, 1e-8)
        return float(np.clip(score, -1.0, 1.0))

    @staticmethod
    def _cosine_sim(a: np.ndarray, b: np.ndarray) -> float:
        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-8))


# ---------------------------------------------------------------------------
# Ensemble Scorer
# ---------------------------------------------------------------------------

class PolicyLanguageIntelligence:
    """
    Facade combining lexicon and transformer scores.

    Produces a HawkishDovishScore and downstream PolicySurpriseVector.
    The lexicon score is always computed. Transformer score is added
    as a weighted correction if available.
    """

    TRANSFORMER_ENSEMBLE_WEIGHT = 0.25  # Transformer gets 25% weight when available

    def __init__(
        self,
        use_transformer: bool = True,
        transformer_model: str = "all-MiniLM-L6-v2",
        custom_lexicon: Optional[Dict[str, float]] = None,
    ):
        self.lexicon_scorer = LexiconScorer(custom_lexicon=custom_lexicon)
        self.transformer_scorer = TransformerScorer(transformer_model) if use_transformer else None

    def analyze(
        self,
        text: str,
        prior_stance: Optional[PolicyStance] = None,
    ) -> HawkishDovishScore:
        """
        Primary entry point for language analysis.

        Args:
            text: Policy text (transcript, prepared remarks, Q&A, headline)
            prior_stance: The stance from the prior communication (for surprise calculation)

        Returns:
            HawkishDovishScore
        """
        lexicon_result = self.lexicon_scorer.score(text)

        # Attempt transformer enhancement
        transformer_score = None
        if self.transformer_scorer and self.transformer_scorer.is_available():
            try:
                transformer_score = self.transformer_scorer.score(text)
            except Exception as e:
                logger.warning("transformer_score_failed", error=str(e))

        if transformer_score is not None:
            # Ensemble: lexicon is primary (75%), transformer is correction (25%)
            w_t = self.TRANSFORMER_ENSEMBLE_WEIGHT
            ensemble_score = (
                (1 - w_t) * lexicon_result.overall_score
                + w_t * transformer_score
            )
            lexicon_result.overall_score = float(np.clip(ensemble_score, -1.0, 1.0))
            lexicon_result.stance = LexiconScorer._score_to_stance(
                lexicon_result.overall_score,
                lexicon_result.crisis_language_detected,
            )
            lexicon_result.method = "ensemble"

        return lexicon_result

    def analyze_sections(
        self,
        prepared_remarks: Optional[str] = None,
        qa_section: Optional[str] = None,
        headline_summary: Optional[str] = None,
    ) -> HawkishDovishScore:
        """
        Analyze a multi-section document with section-specific weighting.
        Prepared remarks are weighted higher than Q&A (more deliberate language).
        Headline summary gets high weight due to editorial distillation.
        """
        section_weights = {
            "headline": 1.5,    # Most distilled / market-moving
            "prepared": 1.2,    # Deliberate, board-approved language
            "qa": 0.8,          # Ad-hoc, less precise
        }

        sections = []
        if headline_summary:
            sections.append((headline_summary, section_weights["headline"]))
        if prepared_remarks:
            sections.append((prepared_remarks, section_weights["prepared"]))
        if qa_section:
            sections.append((qa_section, section_weights["qa"]))

        if not sections:
            return HawkishDovishScore(
                overall_score=0.0,
                stance=PolicyStance.AMBIGUOUS,
                confidence=0.0,
            )

        # Weight-average the component scores
        weighted_overall = 0.0
        total_weight = 0.0
        all_hawkish_phrases = []
        all_dovish_phrases = []
        crisis_detected = False
        policy_reversal = False

        for text, weight in sections:
            result = self.analyze(text)
            weighted_overall += result.overall_score * weight * result.confidence
            total_weight += weight * result.confidence
            all_hawkish_phrases.extend(result.hawkish_phrases)
            all_dovish_phrases.extend(result.dovish_phrases)
            crisis_detected = crisis_detected or result.crisis_language_detected
            policy_reversal = policy_reversal or result.policy_reversal_language

        if total_weight < 0.01:
            final_score = 0.0
            final_confidence = 0.1
        else:
            final_score = float(np.clip(weighted_overall / total_weight, -1.0, 1.0))
            final_confidence = min(total_weight / sum(w for _, w in sections), 1.0)

        # Use full text for detailed component scores
        full_text = " ".join(t for t, _ in sections)
        detailed = self.analyze(full_text)
        detailed.overall_score = final_score
        detailed.confidence = final_confidence
        detailed.stance = LexiconScorer._score_to_stance(final_score, crisis_detected)
        detailed.hawkish_phrases = list(set(all_hawkish_phrases))[:10]
        detailed.dovish_phrases = list(set(all_dovish_phrases))[:10]
        detailed.crisis_language_detected = crisis_detected
        detailed.policy_reversal_language = policy_reversal

        return detailed
