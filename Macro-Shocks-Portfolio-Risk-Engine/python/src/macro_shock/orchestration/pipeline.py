"""
orchestration/pipeline.py

Main Orchestration Pipeline.

The MacroShockPipeline coordinates all modules in the correct sequence,
manages the shared PipelineRunContext, handles partial failures gracefully,
and produces a complete risk assessment from a raw event input.

Pipeline stages (in order):
  1. Event Detection & Classification
  2. Market Context Ingestion
  3. NLP / Language Intelligence
  4. Policy Surprise Vector
  5. Market Vulnerability Scoring
  6. Scenario Tree Construction
  7. Risk Scoring
  8. Portfolio Impact Translation
  9. Alert Evaluation & Routing
  10. OMS Interface (if authorized)
  11. Audit Trail
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from macro_shock.data_schema.models import (
    MacroEvent,
    MarketStateSnapshot,
    PipelineRunContext,
)
from macro_shock.event_detection.calendar import MarketCalendar
from macro_shock.event_detection.detector import EventDetector
from macro_shock.execution.oms_interface import ExecutionEnvironment, OMSInterface
from macro_shock.market_context.vulnerability_scorer import MarketVulnerabilityScorer
from macro_shock.monitoring.alert_manager import AlertManager, AuditTrail
from macro_shock.nlp.hawkish_dovish import PolicyLanguageIntelligence
from macro_shock.nlp.policy_surprise_vector import PolicySurpriseEngine
from macro_shock.portfolio_impact.impact_translator import PortfolioImpactTranslator
from macro_shock.risk_scoring.composite_scorer import CompositeRiskScorer
from macro_shock.scenario_engine.scenario_tree import ScenarioTreeBuilder

logger = structlog.get_logger(__name__)


class MacroShockPipeline:
    """
    End-to-end risk assessment pipeline.

    Designed for both real-time event processing and backtesting replay.
    All stage failures are non-fatal by default (configurable).
    The pipeline returns whatever it computed successfully; callers check
    context.failed_stages to understand completeness.
    """

    def __init__(
        self,
        config: Dict,
        environment: str = "research",
        market_data_provider=None,
    ):
        self.config = config
        self.environment = environment
        self.market_data_provider = market_data_provider

        # Initialize all module instances
        self.calendar = MarketCalendar(
            holiday_file=config.get("holiday_file"),
            early_close_file=config.get("early_close_file"),
        )
        self.event_detector = EventDetector(
            calendar=self.calendar,
            config=config.get("event_detection", {}),
        )
        self.language_intel = PolicyLanguageIntelligence(
            use_transformer=config.get("use_transformer", False),
            transformer_model=config.get("transformer_model", "all-MiniLM-L6-v2"),
        )
        self.surprise_engine = PolicySurpriseEngine(
            config=config.get("policy_surprise", {})
        )
        self.vulnerability_scorer = MarketVulnerabilityScorer(
            calibration_override=config.get("vulnerability_calibration")
        )
        self.scenario_builder = ScenarioTreeBuilder(
            config=config.get("scenario_engine", {})
        )
        self.risk_scorer = CompositeRiskScorer(
            config=config.get("risk_scoring", {})
        )
        self.portfolio_translator = PortfolioImpactTranslator(
            config=config.get("portfolio_impact", {})
        )
        self.audit_trail = AuditTrail(
            log_dir=config.get("audit_log_dir")
        )
        self.alert_manager = AlertManager(
            audit_trail=self.audit_trail,
            thresholds=config.get("alert_thresholds"),
            environment=environment,
        )
        exec_env = ExecutionEnvironment(environment) if environment in ExecutionEnvironment._value2member_map_ else ExecutionEnvironment.RESEARCH
        self.oms_interface = OMSInterface(
            environment=exec_env,
            oms_endpoint=config.get("oms_endpoint"),
            pre_trade_config=config.get("pre_trade_checks", {}),
        )

        self.fail_fast = config.get("fail_fast", False)

    # ------------------------------------------------------------------
    # Real-Time Event Processing
    # ------------------------------------------------------------------

    def process_raw_event(
        self,
        raw_event: Dict,
        market_state: Optional[MarketStateSnapshot] = None,
    ) -> PipelineRunContext:
        """
        Process a raw event dict through the full pipeline.

        Args:
            raw_event: Raw event data from event feed.
            market_state: Pre-built market state (if already available).
                         If None, will attempt to fetch from market_data_provider.

        Returns:
            PipelineRunContext with all computed artifacts.
        """
        context = PipelineRunContext(environment=self.environment)
        t_start = time.monotonic()

        logger.info(
            "pipeline_started",
            run_id=context.run_id,
            environment=self.environment,
            event_title=raw_event.get("title", "Unknown"),
        )

        # Stage 1: Event Detection & Classification
        context = self._stage_event_detection(context, raw_event)
        if context.event is None:
            logger.info("pipeline_terminated_no_event", run_id=context.run_id)
            return context

        # Stage 2: Market Context
        if market_state:
            context.market_state = market_state
            context.mark_stage_complete("market_context")
        else:
            context = self._stage_market_context(context)

        if not context.is_viable and self.fail_fast:
            logger.warning("pipeline_not_viable", run_id=context.run_id)
            return context

        # Stage 3: NLP / Language Intelligence
        context = self._stage_nlp(context, raw_event)

        # Stage 4: Policy Surprise Vector
        context = self._stage_policy_surprise(context)

        # Stage 5: Market Vulnerability (updates market_state.regime)
        vulnerability = self._stage_vulnerability(context)

        # Stage 6: Scenario Tree
        context = self._stage_scenario_tree(context, vulnerability)

        # Stage 7: Risk Scoring
        context = self._stage_risk_scoring(context, vulnerability)

        # Stage 8: Portfolio Impact
        context = self._stage_portfolio_impact(context)

        # Stage 9: Alerts
        context = self._stage_alerts(context)

        # Stage 10: OMS Interface
        context = self._stage_oms(context)

        # Audit trail entries
        if context.event:
            self.audit_trail.record_event(context.event)
        if context.risk_score:
            self.audit_trail.record_risk_score(context.risk_score)
        if context.scenario_tree:
            self.audit_trail.record_scenario_tree(context.scenario_tree)
        if context.portfolio_impact:
            self.audit_trail.record_portfolio_impact(context.portfolio_impact)

        elapsed = time.monotonic() - t_start
        logger.info(
            "pipeline_complete",
            run_id=context.run_id,
            elapsed_seconds=f"{elapsed:.3f}",
            completed_stages=context.completed_stages,
            failed_stages=context.failed_stages,
            composite_score=context.risk_score.composite_score if context.risk_score else None,
            action_level=context.portfolio_impact.action_level if context.portfolio_impact else None,
        )

        return context

    # ------------------------------------------------------------------
    # Backtest Mode
    # ------------------------------------------------------------------

    def run_backtest_mode(
        self,
        historical_event,
        pre_event_market_df,
    ) -> Optional[PipelineRunContext]:
        """
        Run the pipeline in backtest mode using historical data.
        Market data is injected from the backtest engine; no live feed access.
        """
        from macro_shock.data.ingestion import MarketStateBuilder
        builder = MarketStateBuilder()

        try:
            market_state = builder.build_from_dataframe(
                df=pre_event_market_df,
                as_of=historical_event.event_date,
                calendar=self.calendar,
            )
        except Exception as e:
            logger.warning("backtest_market_state_failed", error=str(e))
            market_state = MarketStateBuilder.build_minimal(historical_event.event_date, self.calendar)

        raw_event = {
            "title": historical_event.description,
            "institution": historical_event.institution,
            "speaker": historical_event.speaker,
            "event_time": historical_event.event_date.isoformat(),
            "raw_text": historical_event.description,
            "is_historical": True,
        }

        return self.process_raw_event(raw_event, market_state=market_state)

    # ------------------------------------------------------------------
    # Pipeline Stages
    # ------------------------------------------------------------------

    def _stage_event_detection(self, context: PipelineRunContext, raw_event: Dict) -> PipelineRunContext:
        stage = "event_detection"
        try:
            event = self.event_detector.detect_and_classify(raw_event)
            if event is None:
                context.warnings.append("Event did not meet severity threshold for processing.")
                return context
            context.event = event
            context.mark_stage_complete(stage)
            logger.debug("stage_complete", stage=stage, severity=event.severity.value)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_market_context(self, context: PipelineRunContext) -> PipelineRunContext:
        stage = "market_context"
        try:
            if self.market_data_provider is None:
                context.warnings.append("No market data provider configured; using synthetic state.")
                from macro_shock.data.ingestion import MarketStateBuilder
                context.market_state = MarketStateBuilder.build_synthetic(context.event.event_timestamp, self.calendar)
            else:
                context.market_state = self.market_data_provider.get_state_as_of(
                    context.event.event_timestamp
                )
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_nlp(self, context: PipelineRunContext, raw_event: Dict) -> PipelineRunContext:
        stage = "nlp"
        try:
            text = raw_event.get("raw_text") or raw_event.get("headline_summary") or raw_event.get("title", "")
            hd_score = self.language_intel.analyze_sections(
                prepared_remarks=raw_event.get("prepared_remarks"),
                qa_section=raw_event.get("qa_section"),
                headline_summary=raw_event.get("headline_summary") or raw_event.get("title"),
            )
            context.event.raw_text = text
            context._nlp_result = hd_score  # Temp store for next stage
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_policy_surprise(self, context: PipelineRunContext) -> PipelineRunContext:
        stage = "policy_surprise"
        try:
            hd_score = getattr(context, "_nlp_result", None)
            if hd_score is None:
                context.warnings.append("NLP result unavailable; using zero-surprise vector.")
                from macro_shock.data_schema.models import PolicySurpriseVector
                context.policy_surprise = PolicySurpriseVector(
                    event_id=context.event.event_id,
                    confidence=0.1,
                )
            else:
                context.policy_surprise = self.surprise_engine.generate(
                    event=context.event,
                    hawkish_dovish=hd_score,
                    market_state=context.market_state,
                )
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_vulnerability(self, context: PipelineRunContext):
        stage = "vulnerability_scoring"
        try:
            if context.market_state is None:
                from macro_shock.market_context.vulnerability_scorer import VulnerabilityComponents
                vuln = VulnerabilityComponents()
                context.warnings.append("No market state; using default vulnerability.")
            else:
                vuln = self.vulnerability_scorer.score(context.market_state)
            context.mark_stage_complete(stage)
            return vuln
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
            from macro_shock.market_context.vulnerability_scorer import VulnerabilityComponents
            return VulnerabilityComponents()

    def _stage_scenario_tree(self, context: PipelineRunContext, vulnerability) -> PipelineRunContext:
        stage = "scenario_tree"
        try:
            if context.policy_surprise is None:
                context.mark_stage_failed(stage, "No policy surprise vector available.")
                return context
            context.scenario_tree = self.scenario_builder.build(
                event=context.event,
                surprise_vector=context.policy_surprise,
                vulnerability=vulnerability,
                market_state=context.market_state,
            )
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_risk_scoring(self, context: PipelineRunContext, vulnerability) -> PipelineRunContext:
        stage = "risk_scoring"
        try:
            if context.scenario_tree is None or context.policy_surprise is None:
                context.mark_stage_failed(stage, "Prerequisites (scenario tree or surprise vector) missing.")
                return context

            from macro_shock.data.ingestion import MarketStateBuilder
            market_state = context.market_state or MarketStateBuilder.build_minimal(
                context.event.event_timestamp, self.calendar
            )

            context.risk_score = self.risk_scorer.score(
                event=context.event,
                surprise_vector=context.policy_surprise,
                market_state=market_state,
                vulnerability=vulnerability,
                scenario_tree=context.scenario_tree,
            )
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_portfolio_impact(self, context: PipelineRunContext) -> PipelineRunContext:
        stage = "portfolio_impact"
        try:
            if context.risk_score is None or context.scenario_tree is None:
                context.mark_stage_failed(stage, "Prerequisites missing.")
                return context

            from macro_shock.data.ingestion import MarketStateBuilder
            market_state = context.market_state or MarketStateBuilder.build_minimal(
                context.event.event_timestamp, self.calendar
            )

            context.portfolio_impact = self.portfolio_translator.generate(
                event=context.event,
                risk_score=context.risk_score,
                scenario_tree=context.scenario_tree,
                market_state=market_state,
            )
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_alerts(self, context: PipelineRunContext) -> PipelineRunContext:
        stage = "alert_evaluation"
        try:
            if not all([context.risk_score, context.scenario_tree, context.portfolio_impact]):
                context.warnings.append("Incomplete pipeline; alerts may be partial.")
                return context

            alerts = self.alert_manager.evaluate_and_alert(
                event=context.event,
                risk_score=context.risk_score,
                scenario_tree=context.scenario_tree,
                portfolio_report=context.portfolio_impact,
            )
            context.alerts = alerts
            context.mark_stage_complete(stage)
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context

    def _stage_oms(self, context: PipelineRunContext) -> PipelineRunContext:
        stage = "oms_interface"
        try:
            if context.portfolio_impact is None or context.risk_score is None:
                return context

            if context.portfolio_impact.trigger_kill_switch:
                self.oms_interface.trigger_kill_switch_review(context.event, context.risk_score)

            pending = self.oms_interface.process_portfolio_impact(
                event=context.event,
                risk_score=context.risk_score,
                portfolio_report=context.portfolio_impact,
            )
            context.mark_stage_complete(stage)

            if pending:
                logger.info(
                    "orders_awaiting_pm_authorization",
                    n_orders=len(pending),
                    run_id=context.run_id,
                )
        except Exception as e:
            context.mark_stage_failed(stage, str(e))
            logger.error("stage_failed", stage=stage, error=str(e))
        return context
