// csharp/src/MacroShockDashboard/App.xaml.cs
//
// Application entry point and global value converters.

using System;
using System.Globalization;
using System.Windows;
using System.Windows.Data;
using System.Windows.Media;

namespace MacroShockDashboard
{
    public partial class App : Application
    {
        protected override void OnStartup(StartupEventArgs e)
        {
            base.OnStartup(e);
            // Global exception handler — log and display; never crash silently
            DispatcherUnhandledException += (s, ex) =>
            {
                Console.Error.WriteLine($"[MSRE Dashboard] Unhandled exception: {ex.Exception.Message}");
                MessageBox.Show(
                    $"An unexpected error occurred:\n\n{ex.Exception.Message}\n\nThe application will continue running.",
                    "Macro Shock Risk Engine — Error",
                    MessageBoxButton.OK,
                    MessageBoxImage.Warning
                );
                ex.Handled = true;
            };
        }
    }

    // ---------------------------------------------------------------------------
    // Value Converters
    // ---------------------------------------------------------------------------

    /// <summary>
    /// Converts a non-empty string to Visible, empty/null to Collapsed.
    /// Bound to ErrorMessage and MondayGapDisplay.
    /// </summary>
    public class NotEmptyToVisibilityConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
            => value is string s && !string.IsNullOrWhiteSpace(s)
               ? Visibility.Visible
               : Visibility.Collapsed;

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }

    /// <summary>
    /// Converts a score (0-100) to a colour brush matching severity thresholds.
    /// </summary>
    public class ScoreToBrushConverter : IValueConverter
    {
        public object Convert(object value, Type targetType, object parameter, CultureInfo culture)
        {
            if (value is double d)
            {
                if (d >= 75) return new SolidColorBrush(Color.FromRgb(220, 38, 38));
                if (d >= 55) return new SolidColorBrush(Color.FromRgb(234, 88, 12));
                if (d >= 35) return new SolidColorBrush(Color.FromRgb(202, 138, 4));
                if (d >= 15) return new SolidColorBrush(Color.FromRgb(37, 99, 235));
            }
            return new SolidColorBrush(Color.FromRgb(107, 114, 128));
        }

        public object ConvertBack(object value, Type targetType, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }

    /// <summary>
    /// Converts a composite score double to a bar width double, scaled to a max of 200px.
    /// </summary>
    public class ScoreToBarWidthConverter : IMultiValueConverter
    {
        public object Convert(object[] values, Type targetType, object parameter, CultureInfo culture)
        {
            if (values.Length == 2 && values[0] is double score && values[1] is double totalWidth)
                return Math.Max(0, Math.Min(score / 100.0 * totalWidth, totalWidth));
            return 0.0;
        }

        public object[] ConvertBack(object value, Type[] targetTypes, object parameter, CultureInfo culture)
            => throw new NotImplementedException();
    }
}
