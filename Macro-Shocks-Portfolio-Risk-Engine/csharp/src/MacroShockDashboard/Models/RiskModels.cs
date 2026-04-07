// csharp/src/MacroShockDashboard/Models/RiskModels.cs
//
// Data transfer objects for the MSRE dashboard.
// These mirror the Python Pydantic models serialized by the REST API.

using System;
using System.Collections.Generic;
using System.Text.Json.Serialization;

namespace MacroShockDashboard.Models
{
    // ---------------------------------------------------------------------------
    // Top-Level Risk Snapshot (API response root)
    // ---------------------------------------------------------------------------

    public class RiskSnapshot
    {
        [JsonPropertyName("composite_score")]
        public double CompositeScore { get; set; }

        [JsonPropertyName("severity")]
        public string Severity { get; set; } = "INFORMATIONAL";

        [JsonPropertyName("action_level")]
        public string ActionLevel { get; set; } = "NO_ACTION";

        [JsonPropertyName("regime")]
        public string Regime { get; set; } = "unknown";

        [JsonPropertyName("summary")]
        public string Summary { get; set; } = string.Empty;

        [JsonPropertyName("weekend_gap_active")]
        public bool WeekendGapActive { get; set; }

        [JsonPropertyName("hours_until_next_open")]
        public double HoursUntilNextOpen { get; set; }

        [JsonPropertyName("monday_gap_estimate_pct")]
        public double MondayGapEstimatePct { get; set; }

        [JsonPropertyName("expected_equity_impact_pct")]
        public double ExpectedEquityImpactPct { get; set; }

        [JsonPropertyName("tail_loss_5pct")]
        public double TailLoss5Pct { get; set; }

        [JsonPropertyName("equity_guidance")]
        public string EquityGuidance { get; set; } = string.Empty;

        [JsonPropertyName("rates_guidance")]
        public string RatesGuidance { get; set; } = string.Empty;

        [JsonPropertyName("credit_guidance")]
        public string CreditGuidance { get; set; } = string.Empty;

        [JsonPropertyName("sub_scores")]
        public List<SubScoreData>? SubScores { get; set; }

        [JsonPropertyName("scenarios")]
        public List<ScenarioData>? Scenarios { get; set; }

        [JsonPropertyName("hedge_recommendations")]
        public List<HedgeData>? HedgeRecommendations { get; set; }

        [JsonPropertyName("recent_alerts")]
        public List<AlertData>? RecentAlerts { get; set; }

        [JsonPropertyName("current_event")]
        public EventSummaryData? CurrentEvent { get; set; }

        [JsonPropertyName("generated_at")]
        public DateTime GeneratedAt { get; set; }

        [JsonPropertyName("data_quality")]
        public double DataQuality { get; set; } = 1.0;

        [JsonPropertyName("score_reliability")]
        public string ScoreReliability { get; set; } = "HIGH";
    }

    // ---------------------------------------------------------------------------
    // Sub-Score
    // ---------------------------------------------------------------------------

    public class SubScoreData
    {
        [JsonPropertyName("name")]
        public string Name { get; set; } = string.Empty;

        [JsonPropertyName("score")]
        public double Score { get; set; }

        [JsonPropertyName("weight")]
        public double Weight { get; set; }

        [JsonPropertyName("weighted_contribution")]
        public double WeightedContribution { get; set; }

        [JsonPropertyName("primary_driver")]
        public string PrimaryDriver { get; set; } = string.Empty;

        [JsonPropertyName("contributing_factors")]
        public List<string>? ContributingFactors { get; set; }

        [JsonPropertyName("confidence")]
        public double Confidence { get; set; } = 1.0;
    }

    // ---------------------------------------------------------------------------
    // Scenario
    // ---------------------------------------------------------------------------

    public class ScenarioData
    {
        [JsonPropertyName("name")]
        public string Name { get; set; } = string.Empty;

        [JsonPropertyName("description")]
        public string Description { get; set; } = string.Empty;

        [JsonPropertyName("probability")]
        public double Probability { get; set; }

        [JsonPropertyName("equity_impact_pct")]
        public double EquityImpactPct { get; set; }

        [JsonPropertyName("yield_10y_change_bps")]
        public double Yield10YChangeBps { get; set; }

        [JsonPropertyName("yield_2y_change_bps")]
        public double Yield2YChangeBps { get; set; }

        [JsonPropertyName("credit_hy_change_bps")]
        public double CreditHyChangeBps { get; set; }

        [JsonPropertyName("vix_change")]
        public double VixChange { get; set; }

        [JsonPropertyName("is_tail_scenario")]
        public bool IsTailScenario { get; set; }

        [JsonPropertyName("liquidity_impairment")]
        public double LiquidityImpairment { get; set; }

        [JsonPropertyName("trading_halt_probability")]
        public double TradingHaltProbability { get; set; }

        [JsonPropertyName("forced_deleveraging_risk")]
        public double ForcedDeleveragingRisk { get; set; }
    }

    // ---------------------------------------------------------------------------
    // Hedge Recommendation
    // ---------------------------------------------------------------------------

    public class HedgeData
    {
        [JsonPropertyName("asset_class")]
        public string AssetClass { get; set; } = string.Empty;

        [JsonPropertyName("instrument_description")]
        public string InstrumentDescription { get; set; } = string.Empty;

        [JsonPropertyName("action")]
        public string Action { get; set; } = string.Empty;

        [JsonPropertyName("urgency")]
        public string Urgency { get; set; } = string.Empty;

        [JsonPropertyName("sizing_guidance")]
        public string SizingGuidance { get; set; } = string.Empty;

        [JsonPropertyName("rationale")]
        public string Rationale { get; set; } = string.Empty;

        [JsonPropertyName("estimated_cost_bps")]
        public double? EstimatedCostBps { get; set; }

        [JsonPropertyName("estimated_protection_value")]
        public string? EstimatedProtectionValue { get; set; }

        [JsonPropertyName("requires_pm_approval")]
        public bool RequiresPmApproval { get; set; } = true;
    }

    // ---------------------------------------------------------------------------
    // Alert
    // ---------------------------------------------------------------------------

    public class AlertData
    {
        [JsonPropertyName("alert_id")]
        public string AlertId { get; set; } = string.Empty;

        [JsonPropertyName("level")]
        public string Level { get; set; } = string.Empty;

        [JsonPropertyName("title")]
        public string Title { get; set; } = string.Empty;

        [JsonPropertyName("message")]
        public string Message { get; set; } = string.Empty;

        [JsonPropertyName("composite_score")]
        public double? CompositeScore { get; set; }

        [JsonPropertyName("generated_at")]
        public DateTime GeneratedAt { get; set; }

        [JsonPropertyName("triggered_thresholds")]
        public List<string>? TriggeredThresholds { get; set; }

        [JsonPropertyName("requires_acknowledgment")]
        public bool RequiresAcknowledgment { get; set; }

        [JsonPropertyName("acknowledged")]
        public bool Acknowledged { get; set; }
    }

    // ---------------------------------------------------------------------------
    // Event Summary
    // ---------------------------------------------------------------------------

    public class EventSummaryData
    {
        [JsonPropertyName("event_id")]
        public string EventId { get; set; } = string.Empty;

        [JsonPropertyName("title")]
        public string Title { get; set; } = string.Empty;

        [JsonPropertyName("institution")]
        public string Institution { get; set; } = string.Empty;

        [JsonPropertyName("speaker")]
        public string? Speaker { get; set; }

        [JsonPropertyName("event_type")]
        public string EventType { get; set; } = string.Empty;

        [JsonPropertyName("severity")]
        public string Severity { get; set; } = string.Empty;

        [JsonPropertyName("severity_score")]
        public double SeverityScore { get; set; }

        [JsonPropertyName("is_weekend")]
        public bool IsWeekend { get; set; }

        [JsonPropertyName("full_weekend_gap")]
        public bool FullWeekendGap { get; set; }

        [JsonPropertyName("hours_until_next_open")]
        public double? HoursUntilNextOpen { get; set; }

        [JsonPropertyName("event_timestamp")]
        public DateTime EventTimestamp { get; set; }
    }
}
