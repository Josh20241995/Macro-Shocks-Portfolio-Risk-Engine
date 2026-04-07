// csharp/src/MacroShockDashboard/ViewModels/MainViewModel.cs
//
// MVVM ViewModel for the MSRE Operational Dashboard.
// Binds risk score data, scenario tree, alerts, and hedge recommendations
// to the WPF UI via INotifyPropertyChanged.

using System;
using System.Collections.ObjectModel;
using System.ComponentModel;
using System.Linq;
using System.Runtime.CompilerServices;
using System.Threading.Tasks;
using System.Windows.Media;
using MacroShockDashboard.Models;
using MacroShockDashboard.Services;

namespace MacroShockDashboard.ViewModels
{
    public class MainViewModel : INotifyPropertyChanged
    {
        private readonly RiskApiService _api;

        public event PropertyChangedEventHandler? PropertyChanged;

        public MainViewModel(RiskApiService api)
        {
            _api = api;
            Scenarios = new ObservableCollection<ScenarioViewModel>();
            HedgeRecommendations = new ObservableCollection<HedgeRecommendationViewModel>();
            Alerts = new ObservableCollection<AlertViewModel>();
            SubScores = new ObservableCollection<SubScoreViewModel>();
        }

        // ---------------------------------------------------------------------------
        // Composite Score
        // ---------------------------------------------------------------------------

        private double _compositeScore;
        public double CompositeScore
        {
            get => _compositeScore;
            set { _compositeScore = value; OnPropertyChanged(); OnPropertyChanged(nameof(SeverityColor)); OnPropertyChanged(nameof(SeverityLabel)); }
        }

        private string _severity = "INFORMATIONAL";
        public string Severity
        {
            get => _severity;
            set { _severity = value; OnPropertyChanged(); }
        }

        private string _actionLevel = "NO_ACTION";
        public string ActionLevel
        {
            get => _actionLevel;
            set { _actionLevel = value; OnPropertyChanged(); }
        }

        private string _regime = "unknown";
        public string Regime
        {
            get => _regime;
            set { _regime = value; OnPropertyChanged(); }
        }

        private string _summaryText = "Awaiting data...";
        public string SummaryText
        {
            get => _summaryText;
            set { _summaryText = value; OnPropertyChanged(); }
        }

        private DateTime _lastUpdated;
        public DateTime LastUpdated
        {
            get => _lastUpdated;
            set { _lastUpdated = value; OnPropertyChanged(); OnPropertyChanged(nameof(LastUpdatedDisplay)); }
        }

        public string LastUpdatedDisplay => LastUpdated == default ? "Never" : LastUpdated.ToString("HH:mm:ss") + " UTC";

        // Derived
        public string SeverityLabel => Severity switch
        {
            "CRITICAL" => "⚠ CRITICAL",
            "HIGH"     => "▲ HIGH",
            "MEDIUM"   => "● MEDIUM",
            "LOW"      => "○ LOW",
            _          => "— INFO",
        };

        public Brush SeverityColor => Severity switch
        {
            "CRITICAL" => new SolidColorBrush(Color.FromRgb(220, 38, 38)),
            "HIGH"     => new SolidColorBrush(Color.FromRgb(234, 88, 12)),
            "MEDIUM"   => new SolidColorBrush(Color.FromRgb(202, 138, 4)),
            "LOW"      => new SolidColorBrush(Color.FromRgb(37, 99, 235)),
            _          => new SolidColorBrush(Color.FromRgb(107, 114, 128)),
        };

        // ---------------------------------------------------------------------------
        // Weekend Gap Status
        // ---------------------------------------------------------------------------

        private bool _weekendGapActive;
        public bool WeekendGapActive
        {
            get => _weekendGapActive;
            set { _weekendGapActive = value; OnPropertyChanged(); OnPropertyChanged(nameof(WeekendGapLabel)); OnPropertyChanged(nameof(WeekendGapColor)); }
        }

        private double _hoursUntilOpen;
        public double HoursUntilOpen
        {
            get => _hoursUntilOpen;
            set { _hoursUntilOpen = value; OnPropertyChanged(); OnPropertyChanged(nameof(WeekendGapLabel)); }
        }

        private double _mondayGapEstimatePct;
        public double MondayGapEstimatePct
        {
            get => _mondayGapEstimatePct;
            set { _mondayGapEstimatePct = value; OnPropertyChanged(); OnPropertyChanged(nameof(MondayGapDisplay)); }
        }

        public string WeekendGapLabel => WeekendGapActive
            ? $"⚠ WEEKEND GAP CORRIDOR ACTIVE  |  {HoursUntilOpen:F1}h to open"
            : "Market corridor: Normal";

        public string MondayGapDisplay => MondayGapEstimatePct != 0
            ? $"Monday gap estimate: {MondayGapEstimatePct:+0.0;-0.0}%"
            : string.Empty;

        public Brush WeekendGapColor => WeekendGapActive
            ? new SolidColorBrush(Color.FromRgb(220, 38, 38))
            : new SolidColorBrush(Color.FromRgb(34, 197, 94));

        // ---------------------------------------------------------------------------
        // Sub-Scores
        // ---------------------------------------------------------------------------

        public ObservableCollection<SubScoreViewModel> SubScores { get; }

        // ---------------------------------------------------------------------------
        // Scenarios
        // ---------------------------------------------------------------------------

        public ObservableCollection<ScenarioViewModel> Scenarios { get; }

        private double _expectedEquityImpact;
        public double ExpectedEquityImpact
        {
            get => _expectedEquityImpact;
            set { _expectedEquityImpact = value; OnPropertyChanged(); OnPropertyChanged(nameof(ExpectedEquityDisplay)); }
        }

        private double _tailLoss5Pct;
        public double TailLoss5Pct
        {
            get => _tailLoss5Pct;
            set { _tailLoss5Pct = value; OnPropertyChanged(); OnPropertyChanged(nameof(TailLossDisplay)); }
        }

        public string ExpectedEquityDisplay => $"{ExpectedEquityImpact:+0.0;-0.0}%";
        public string TailLossDisplay => $"{TailLoss5Pct:0.0}% (5th pct)";

        // ---------------------------------------------------------------------------
        // Portfolio Hedges
        // ---------------------------------------------------------------------------

        public ObservableCollection<HedgeRecommendationViewModel> HedgeRecommendations { get; }

        private string _equityGuidance = string.Empty;
        public string EquityGuidance { get => _equityGuidance; set { _equityGuidance = value; OnPropertyChanged(); } }

        private string _ratesGuidance = string.Empty;
        public string RatesGuidance { get => _ratesGuidance; set { _ratesGuidance = value; OnPropertyChanged(); } }

        private string _creditGuidance = string.Empty;
        public string CreditGuidance { get => _creditGuidance; set { _creditGuidance = value; OnPropertyChanged(); } }

        // ---------------------------------------------------------------------------
        // Alerts
        // ---------------------------------------------------------------------------

        public ObservableCollection<AlertViewModel> Alerts { get; }

        private int _criticalAlertCount;
        public int CriticalAlertCount
        {
            get => _criticalAlertCount;
            set { _criticalAlertCount = value; OnPropertyChanged(); OnPropertyChanged(nameof(HasCriticalAlerts)); }
        }

        public bool HasCriticalAlerts => CriticalAlertCount > 0;

        // ---------------------------------------------------------------------------
        // Event Info
        // ---------------------------------------------------------------------------

        private string _eventTitle = "No active event";
        public string EventTitle { get => _eventTitle; set { _eventTitle = value; OnPropertyChanged(); } }

        private string _eventInstitution = string.Empty;
        public string EventInstitution { get => _eventInstitution; set { _eventInstitution = value; OnPropertyChanged(); } }

        private string _eventType = string.Empty;
        public string EventType { get => _eventType; set { _eventType = value; OnPropertyChanged(); } }

        // ---------------------------------------------------------------------------
        // Data Refresh
        // ---------------------------------------------------------------------------

        private bool _isLoading;
        public bool IsLoading
        {
            get => _isLoading;
            set { _isLoading = value; OnPropertyChanged(); }
        }

        private string _errorMessage = string.Empty;
        public string ErrorMessage { get => _errorMessage; set { _errorMessage = value; OnPropertyChanged(); } }

        public async Task RefreshAsync()
        {
            IsLoading = true;
            ErrorMessage = string.Empty;
            try
            {
                var snapshot = await _api.GetLatestRiskSnapshotAsync();
                if (snapshot == null)
                {
                    ErrorMessage = "No risk data available from API.";
                    return;
                }

                UpdateFromSnapshot(snapshot);
                LastUpdated = DateTime.UtcNow;
            }
            catch (Exception ex)
            {
                ErrorMessage = $"API error: {ex.Message}";
            }
            finally
            {
                IsLoading = false;
            }
        }

        private void UpdateFromSnapshot(RiskSnapshot snapshot)
        {
            // Composite score
            CompositeScore = snapshot.CompositeScore;
            Severity = snapshot.Severity;
            ActionLevel = snapshot.ActionLevel;
            Regime = snapshot.Regime;
            SummaryText = snapshot.Summary;

            // Weekend gap
            WeekendGapActive = snapshot.WeekendGapActive;
            HoursUntilOpen = snapshot.HoursUntilNextOpen;
            MondayGapEstimatePct = snapshot.MondayGapEstimatePct;

            // Sub-scores
            SubScores.Clear();
            foreach (var ss in snapshot.SubScores ?? Enumerable.Empty<SubScoreData>())
            {
                SubScores.Add(new SubScoreViewModel
                {
                    Name = ss.Name,
                    Score = ss.Score,
                    PrimaryDriver = ss.PrimaryDriver,
                    BarColor = ScoreToColor(ss.Score),
                    BarWidth = ss.Score * 2,  // Scale to 200px max
                });
            }

            // Scenarios
            Scenarios.Clear();
            foreach (var sc in snapshot.Scenarios ?? Enumerable.Empty<ScenarioData>())
            {
                Scenarios.Add(new ScenarioViewModel
                {
                    Name = sc.Name,
                    Probability = sc.Probability,
                    ProbabilityDisplay = $"{sc.Probability:P1}",
                    EquityImpact = sc.EquityImpactPct,
                    EquityImpactDisplay = $"{sc.EquityImpactPct:+0.0;-0.0}%",
                    Yield10YDisplay = $"{sc.Yield10YChangeBps:+0;-0}bps",
                    VixChangeDisplay = $"{sc.VixChange:+0.0;-0.0}",
                    IsTail = sc.IsTailScenario,
                    RowBackground = sc.IsTailScenario
                        ? new SolidColorBrush(Color.FromRgb(254, 242, 242))
                        : new SolidColorBrush(Colors.White),
                });
            }

            ExpectedEquityImpact = snapshot.ExpectedEquityImpactPct;
            TailLoss5Pct = snapshot.TailLoss5Pct;

            // Hedges
            HedgeRecommendations.Clear();
            foreach (var h in snapshot.HedgeRecommendations ?? Enumerable.Empty<HedgeData>())
            {
                HedgeRecommendations.Add(new HedgeRecommendationViewModel
                {
                    AssetClass = h.AssetClass.ToUpper(),
                    Action = h.Action,
                    Instrument = h.InstrumentDescription,
                    Urgency = h.Urgency,
                    Sizing = h.SizingGuidance,
                    UrgencyColor = h.Urgency == "IMMEDIATE"
                        ? new SolidColorBrush(Color.FromRgb(220, 38, 38))
                        : new SolidColorBrush(Color.FromRgb(234, 88, 12)),
                });
            }

            EquityGuidance = snapshot.EquityGuidance;
            RatesGuidance = snapshot.RatesGuidance;
            CreditGuidance = snapshot.CreditGuidance;

            // Alerts
            Alerts.Clear();
            CriticalAlertCount = 0;
            foreach (var a in snapshot.RecentAlerts ?? Enumerable.Empty<AlertData>())
            {
                Alerts.Add(new AlertViewModel
                {
                    Level = a.Level,
                    Title = a.Title,
                    Message = a.Message,
                    Timestamp = a.GeneratedAt,
                    TimestampDisplay = a.GeneratedAt.ToString("HH:mm:ss"),
                    LevelColor = a.Level == "CRITICAL"
                        ? new SolidColorBrush(Color.FromRgb(220, 38, 38))
                        : a.Level == "HIGH"
                            ? new SolidColorBrush(Color.FromRgb(234, 88, 12))
                            : new SolidColorBrush(Color.FromRgb(202, 138, 4)),
                });
                if (a.Level == "CRITICAL") CriticalAlertCount++;
            }

            // Event
            if (snapshot.CurrentEvent != null)
            {
                EventTitle = snapshot.CurrentEvent.Title;
                EventInstitution = snapshot.CurrentEvent.Institution;
                EventType = snapshot.CurrentEvent.EventType;
            }
        }

        private static Brush ScoreToColor(double score) => score switch
        {
            >= 75 => new SolidColorBrush(Color.FromRgb(220, 38, 38)),
            >= 55 => new SolidColorBrush(Color.FromRgb(234, 88, 12)),
            >= 35 => new SolidColorBrush(Color.FromRgb(202, 138, 4)),
            >= 15 => new SolidColorBrush(Color.FromRgb(37, 99, 235)),
            _     => new SolidColorBrush(Color.FromRgb(107, 114, 128)),
        };

        protected void OnPropertyChanged([CallerMemberName] string? name = null)
            => PropertyChanged?.Invoke(this, new PropertyChangedEventArgs(name));
    }

    // ---------------------------------------------------------------------------
    // Child ViewModels
    // ---------------------------------------------------------------------------

    public class SubScoreViewModel : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler? PropertyChanged;
        public string Name { get; set; } = string.Empty;
        public double Score { get; set; }
        public string PrimaryDriver { get; set; } = string.Empty;
        public Brush BarColor { get; set; } = Brushes.Gray;
        public double BarWidth { get; set; }
        public string ScoreDisplay => $"{Score:F0}";
    }

    public class ScenarioViewModel : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler? PropertyChanged;
        public string Name { get; set; } = string.Empty;
        public double Probability { get; set; }
        public string ProbabilityDisplay { get; set; } = string.Empty;
        public double EquityImpact { get; set; }
        public string EquityImpactDisplay { get; set; } = string.Empty;
        public string Yield10YDisplay { get; set; } = string.Empty;
        public string VixChangeDisplay { get; set; } = string.Empty;
        public bool IsTail { get; set; }
        public Brush RowBackground { get; set; } = Brushes.White;
    }

    public class HedgeRecommendationViewModel : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler? PropertyChanged;
        public string AssetClass { get; set; } = string.Empty;
        public string Action { get; set; } = string.Empty;
        public string Instrument { get; set; } = string.Empty;
        public string Urgency { get; set; } = string.Empty;
        public string Sizing { get; set; } = string.Empty;
        public Brush UrgencyColor { get; set; } = Brushes.Orange;
    }

    public class AlertViewModel : INotifyPropertyChanged
    {
        public event PropertyChangedEventHandler? PropertyChanged;
        public string Level { get; set; } = string.Empty;
        public string Title { get; set; } = string.Empty;
        public string Message { get; set; } = string.Empty;
        public DateTime Timestamp { get; set; }
        public string TimestampDisplay { get; set; } = string.Empty;
        public Brush LevelColor { get; set; } = Brushes.Orange;
    }
}
