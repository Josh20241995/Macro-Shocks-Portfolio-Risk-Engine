// csharp/src/MacroShockDashboard/Views/MainWindow.xaml.cs
//
// Macro Shock Risk Engine — Operational Dashboard
// WPF .NET 6 application for analysts and portfolio managers.
//
// Features:
// - Live composite risk score gauge
// - Sub-score heatmap
// - Scenario tree probability table
// - Event timeline
// - Hedge recommendation panel
// - Alert notification system
// - Monday gap corridor status bar
//
// Data source: MSRE REST API (Python FastAPI or Flask server)
// Update cadence: poll every 30 seconds; push on new events via WebSocket

using System;
using System.Collections.ObjectModel;
using System.Linq;
using System.Net.Http;
using System.Text.Json;
using System.Threading;
using System.Threading.Tasks;
using System.Windows;
using System.Windows.Media;
using MacroShockDashboard.Models;
using MacroShockDashboard.Services;
using MacroShockDashboard.ViewModels;

namespace MacroShockDashboard.Views
{
    public partial class MainWindow : Window
    {
        private readonly MainViewModel _viewModel;
        private readonly RiskApiService _apiService;
        private Timer? _refreshTimer;
        private const int RefreshIntervalMs = 30_000;

        public MainWindow()
        {
            InitializeComponent();
            _apiService = new RiskApiService(
                baseUrl: Environment.GetEnvironmentVariable("MSRE_API_URL") ?? "http://localhost:8000"
            );
            _viewModel = new MainViewModel(_apiService);
            DataContext = _viewModel;

            Loaded += OnLoaded;
            Closed += OnClosed;
        }

        private async void OnLoaded(object sender, RoutedEventArgs e)
        {
            await _viewModel.RefreshAsync();
            _refreshTimer = new Timer(
                async _ => await Dispatcher.InvokeAsync(_viewModel.RefreshAsync),
                null,
                RefreshIntervalMs,
                RefreshIntervalMs
            );
        }

        private void OnClosed(object? sender, EventArgs e)
        {
            _refreshTimer?.Dispose();
        }
    }
}
