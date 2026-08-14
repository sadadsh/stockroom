using System.IO;
using System.Reflection;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal static class LauncherDiagnostics
{
    private const long MaximumLogBytes = 5 * 1024 * 1024;
    private const int MaximumTextLength = 4096;
    private static readonly object Sync = new();

    internal static string LogPath => Path.Combine(
        Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
        "Stockroom",
        "Logs",
        "Native Host.jsonl");

    internal static void Write(
        string eventName,
        string detail = "",
        Exception? exception = null)
    {
        if (string.IsNullOrWhiteSpace(eventName))
        {
            return;
        }

        try
        {
            lock (Sync)
            {
                var path = LogPath;
                var directory = Path.GetDirectoryName(path)
                    ?? throw new InvalidOperationException("diagnostic log directory is unavailable");
                Directory.CreateDirectory(directory);
                RotateIfNeeded(path);
                var document = new Dictionary<string, object?>
                {
                    ["schema"] = "stockroom-native-host-log/1",
                    ["timestamp_utc"] = DateTimeOffset.UtcNow.ToString("O"),
                    ["event"] = Limit(eventName),
                    ["detail"] = Limit(detail),
                    ["process_id"] = Environment.ProcessId,
                    ["version"] = ProductVersion(),
                    ["exception_type"] = exception?.GetType().FullName ?? string.Empty,
                    ["exception_message"] = Limit(exception?.Message ?? string.Empty),
                };
                File.AppendAllText(
                    path,
                    JsonSerializer.Serialize(document) + Environment.NewLine);
            }
        }
        catch
        {
            // Diagnostics must never become another startup failure.
        }
    }

    internal static string ProductVersion() =>
        Assembly.GetExecutingAssembly().GetName().Version?.ToString(4)
        ?? "0.0.0.0";

    private static string Limit(string value) =>
        value.Length <= MaximumTextLength
            ? value
            : value[^MaximumTextLength..];

    private static void RotateIfNeeded(string path)
    {
        if (!File.Exists(path) || new FileInfo(path).Length < MaximumLogBytes)
        {
            return;
        }

        var prior = path + ".1";
        File.Delete(prior);
        File.Move(path, prior);
    }
}
