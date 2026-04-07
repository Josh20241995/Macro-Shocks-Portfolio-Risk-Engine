// csharp/src/MacroShockDashboard/Services/RiskApiService.cs
//
// HTTP client service for the MSRE Python REST API.
// Handles deserialization, timeouts, retries, and error logging.
// The Python API (FastAPI or Flask) must be running on the configured baseUrl.

using System;
using System.Net.Http;
using System.Net.Http.Json;
using System.Text.Json;
using System.Text.Json.Serialization;
using System.Threading;
using System.Threading.Tasks;
using MacroShockDashboard.Models;

namespace MacroShockDashboard.Services
{
    public class RiskApiService : IDisposable
    {
        private readonly HttpClient _http;
        private readonly string _baseUrl;

        private static readonly JsonSerializerOptions JsonOptions = new()
        {
            PropertyNameCaseInsensitive = true,
            DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
            Converters = { new JsonStringEnumConverter(JsonNamingPolicy.CamelCase) },
        };

        public RiskApiService(string baseUrl)
        {
            _baseUrl = baseUrl.TrimEnd('/');
            _http = new HttpClient
            {
                Timeout = TimeSpan.FromSeconds(15),
                BaseAddress = new Uri(_baseUrl),
            };
            _http.DefaultRequestHeaders.Add("Accept", "application/json");
            _http.DefaultRequestHeaders.Add("X-Client", "MSRE-Dashboard/1.0");
        }

        /// <summary>
        /// Fetch the latest risk snapshot from the MSRE API.
        /// Returns null if unavailable, logs errors.
        /// </summary>
        public async Task<RiskSnapshot?> GetLatestRiskSnapshotAsync(
            CancellationToken ct = default)
        {
            try
            {
                var response = await _http.GetAsync("/api/v1/risk/latest", ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<RiskSnapshot>(JsonOptions, ct);
            }
            catch (HttpRequestException ex)
            {
                LogError("GetLatestRiskSnapshot", ex);
                return null;
            }
            catch (TaskCanceledException)
            {
                LogError("GetLatestRiskSnapshot", new TimeoutException("API request timed out."));
                return null;
            }
        }

        /// <summary>
        /// Fetch risk history for a given lookback period (hours).
        /// Used for timeline charts and trend analysis.
        /// </summary>
        public async Task<RiskSnapshot[]?> GetRiskHistoryAsync(
            int lookbackHours = 24,
            CancellationToken ct = default)
        {
            try
            {
                var response = await _http.GetAsync($"/api/v1/risk/history?hours={lookbackHours}", ct);
                response.EnsureSuccessStatusCode();
                return await response.Content.ReadFromJsonAsync<RiskSnapshot[]>(JsonOptions, ct);
            }
            catch (Exception ex)
            {
                LogError("GetRiskHistory", ex);
                return null;
            }
        }

        /// <summary>
        /// Acknowledge an alert by ID. Returns true on success.
        /// </summary>
        public async Task<bool> AcknowledgeAlertAsync(
            string alertId,
            string acknowledgedBy,
            CancellationToken ct = default)
        {
            try
            {
                var payload = new { alert_id = alertId, acknowledged_by = acknowledgedBy };
                var response = await _http.PostAsJsonAsync("/api/v1/alerts/acknowledge", payload, ct);
                return response.IsSuccessStatusCode;
            }
            catch (Exception ex)
            {
                LogError("AcknowledgeAlert", ex);
                return false;
            }
        }

        /// <summary>
        /// Health check: returns true if API is reachable and healthy.
        /// </summary>
        public async Task<bool> IsHealthyAsync(CancellationToken ct = default)
        {
            try
            {
                var response = await _http.GetAsync("/health", ct);
                return response.IsSuccessStatusCode;
            }
            catch
            {
                return false;
            }
        }

        private static void LogError(string method, Exception ex)
        {
            // In production, route to structured logging / Serilog
            Console.Error.WriteLine($"[RiskApiService.{method}] {ex.GetType().Name}: {ex.Message}");
        }

        public void Dispose() => _http.Dispose();
    }
}
