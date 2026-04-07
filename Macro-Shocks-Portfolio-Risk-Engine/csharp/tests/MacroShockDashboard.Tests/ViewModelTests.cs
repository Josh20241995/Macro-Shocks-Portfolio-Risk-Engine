// csharp/tests/MacroShockDashboard.Tests/ViewModelTests.cs
//
// xUnit tests for the MSRE Dashboard ViewModels.
// Tests data binding, severity color logic, and snapshot ingestion.

using System;
using System.Collections.Generic;
using System.Threading.Tasks;
using System.Windows.Media;
using MacroShockDashboard.Models;
using MacroShockDashboard.Services;
using MacroShockDashboard.ViewModels;
using Xunit;

namespace MacroShockDashboard.Tests
{
    // ---------------------------------------------------------------------------
    // Stub API service for testing (no HTTP calls)
    // ---------------------------------------------------------------------------

    public class StubRiskApiService : RiskApiService
    {
        private readonly RiskSnapshot? _snapshot;

        public StubRiskApiService(RiskSnapshot? snapshot)
            : base("http://localhost:9999")   // Never called; stub overrides all methods
        {
            _snapshot = snapshot;
        }

        public new Task<RiskSnapshot?> GetLatestRiskSnapshotAsync(
            System.Threading.CancellationToken ct = default)
            => Task.FromResult(_snapshot);
    }

    // ---------------------------------------------------------------------------
    // Helpers
    // ---------------------------------------------------------------------------

    internal static class SnapshotFactory
    {
        public static RiskSnapshot Critical() => new()
        {
            CompositeScore = 82.0,
            Severity = "CRITICAL",
            ActionLevel = "EMERGENCY_DERISKING",
            Regime = "crisis",
            Summary = "Critical risk score. Emergency de-risking recommended.",
            WeekendGapActive = true,
            HoursUntilNextOpen = 52.0,
            MondayGapEstimatePct = -5.2,
            ExpectedEquityImpactPct = -4.8,
            TailLoss5Pct = -11.0,
            EquityGuidance = "Reduce gross equity 35-50%.",
            RatesGuidance = "Add duration in safe-haven flight.",
            CreditGuidance = "Buy CDX HY protection.",
            GeneratedAt = DateTime.UtcNow,
            DataQuality = 0.92,
            ScoreReliability = "HIGH",
            SubScores = new List<SubScoreData>
            {
                new() { Name = "Liquidity Risk", Score = 78.0, Weight = 0.28, PrimaryDriver = "Thin liquidity" },
                new() { Name = "Weekend Gap Risk", Score = 91.0, Weight = 0.03, PrimaryDriver = "55h until open" },
                new() { Name = "Volatility Risk", Score = 74.0, Weight = 0.18, PrimaryDriver = "VIX at 38" },
            },
            Scenarios = new List<ScenarioData>
            {
                new() { Name = "Disorderly Risk-Off", Probability = 0.22, EquityImpactPct = -9.4, IsTailScenario = true },
                new() { Name = "Mild Dovish Surprise", Probability = 0.08, EquityImpactPct = 1.1, IsTailScenario = false },
            },
            HedgeRecommendations = new List<HedgeData>
            {
                new()
                {
                    AssetClass = "equity",
                    Action = "BUY",
                    InstrumentDescription = "SPX put spread 2-4 week expiry",
                    Urgency = "IMMEDIATE",
                    SizingGuidance = "5-10% of equity book notional",
                    Rationale = "Tail scenario probability 22%; 5th pct loss -11%.",
                    EstimatedCostBps = 18.0,
                    RequiresPmApproval = true,
                }
            },
            RecentAlerts = new List<AlertData>
            {
                new()
                {
                    AlertId = "alert-001",
                    Level = "CRITICAL",
                    Title = "Composite Risk Score: 82.0/100",
                    Message = "Emergency de-risking recommended.",
                    GeneratedAt = DateTime.UtcNow,
                    RequiresAcknowledgment = true,
                    Acknowledged = false,
                }
            },
            CurrentEvent = new EventSummaryData
            {
                EventId = "evt-001",
                Title = "Emergency Federal Reserve Statement",
                Institution = "Federal Reserve",
                Speaker = "Jerome Powell",
                EventType = "unscheduled_emergency",
                Severity = "CRITICAL",
                SeverityScore = 92.0,
                IsWeekend = true,
                FullWeekendGap = true,
                HoursUntilNextOpen = 52.0,
                EventTimestamp = DateTime.UtcNow,
            }
        };

        public static RiskSnapshot Benign() => new()
        {
            CompositeScore = 18.0,
            Severity = "LOW",
            ActionLevel = "MONITOR",
            Regime = "risk_on_expansion",
            Summary = "Low risk. No action required.",
            WeekendGapActive = false,
            HoursUntilNextOpen = 0.0,
            MondayGapEstimatePct = 0.0,
            ExpectedEquityImpactPct = -0.3,
            TailLoss5Pct = -1.2,
            GeneratedAt = DateTime.UtcNow,
            DataQuality = 1.0,
            ScoreReliability = "HIGH",
            SubScores = new List<SubScoreData>(),
            Scenarios = new List<ScenarioData>(),
            HedgeRecommendations = new List<HedgeData>(),
            RecentAlerts = new List<AlertData>(),
        };
    }

    // ---------------------------------------------------------------------------
    // Tests
    // ---------------------------------------------------------------------------

    public class MainViewModelTests
    {
        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_UpdatesCompositeScore()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal(82.0, vm.CompositeScore);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_SeverityIsCritical()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal("CRITICAL", vm.Severity);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_WeekendGapActive()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.True(vm.WeekendGapActive);
            Assert.Equal(52.0, vm.HoursUntilOpen);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_MondayGapDisplayed()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal(-5.2, vm.MondayGapEstimatePct);
            Assert.Contains("-5.2", vm.MondayGapDisplay);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_SubScoresPopulated()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal(3, vm.SubScores.Count);
            Assert.All(vm.SubScores, ss => Assert.False(string.IsNullOrEmpty(ss.Name)));
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_ScenariosPopulated()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal(2, vm.Scenarios.Count);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_HedgesPopulated()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Single(vm.HedgeRecommendations);
            Assert.Equal("EQUITY", vm.HedgeRecommendations[0].AssetClass);
        }

        [Fact]
        public async Task RefreshAsync_CriticalSnapshot_AlertsPopulated()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Single(vm.Alerts);
            Assert.True(vm.HasCriticalAlerts);
            Assert.Equal(1, vm.CriticalAlertCount);
        }

        [Fact]
        public async Task RefreshAsync_BenignSnapshot_NoCriticalAlerts()
        {
            var vm = CreateVm(SnapshotFactory.Benign());
            await vm.RefreshAsync();
            Assert.False(vm.HasCriticalAlerts);
            Assert.Equal(0, vm.CriticalAlertCount);
        }

        [Fact]
        public async Task RefreshAsync_BenignSnapshot_WeekendGapInactive()
        {
            var vm = CreateVm(SnapshotFactory.Benign());
            await vm.RefreshAsync();
            Assert.False(vm.WeekendGapActive);
        }

        [Fact]
        public async Task RefreshAsync_NullSnapshot_SetsErrorMessage()
        {
            var vm = CreateVm(null);
            await vm.RefreshAsync();
            Assert.False(string.IsNullOrEmpty(vm.ErrorMessage));
        }

        [Theory]
        [InlineData("CRITICAL", true)]
        [InlineData("HIGH", false)]
        [InlineData("MEDIUM", false)]
        [InlineData("LOW", false)]
        [InlineData("INFORMATIONAL", false)]
        public async Task SeverityLabel_ContainsExpectedPrefix(string severity, bool hasCriticalPrefix)
        {
            var snapshot = SnapshotFactory.Benign();
            snapshot.Severity = severity;
            var vm = CreateVm(snapshot);
            await vm.RefreshAsync();
            Assert.Equal(hasCriticalPrefix, vm.SeverityLabel.Contains("⚠"));
        }

        [Fact]
        public async Task RefreshAsync_UpdatesLastUpdated()
        {
            var before = DateTime.UtcNow.AddSeconds(-1);
            var vm = CreateVm(SnapshotFactory.Benign());
            await vm.RefreshAsync();
            Assert.True(vm.LastUpdated >= before);
        }

        [Fact]
        public async Task RefreshAsync_EventPopulated()
        {
            var vm = CreateVm(SnapshotFactory.Critical());
            await vm.RefreshAsync();
            Assert.Equal("Emergency Federal Reserve Statement", vm.EventTitle);
            Assert.Equal("Federal Reserve", vm.EventInstitution);
        }

        private static MainViewModel CreateVm(RiskSnapshot? snapshot)
        {
            // Use reflection-based stub to avoid HTTP calls
            // In a real test setup, use Moq or NSubstitute
            var api = new StubApiAdapter(snapshot);
            return new MainViewModel(api);
        }

        // Minimal adapter that wraps a fixed snapshot for VM consumption
        private class StubApiAdapter : RiskApiService
        {
            private readonly RiskSnapshot? _s;
            public StubApiAdapter(RiskSnapshot? s) : base("http://stub") => _s = s;
            public new Task<RiskSnapshot?> GetLatestRiskSnapshotAsync(
                System.Threading.CancellationToken ct = default)
                => Task.FromResult(_s);
        }
    }
}
