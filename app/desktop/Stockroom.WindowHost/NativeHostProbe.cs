using System.IO;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal static class NativeHostProbe
{
    internal static int Run(string receiptPath)
    {
        var fullPath = Path.GetFullPath(receiptPath);
        if (File.Exists(fullPath) || Directory.Exists(fullPath))
        {
            throw new WindowHostException("native host probe receipt path is unsafe");
        }
        var baseDirectory = Path.GetFullPath(AppContext.BaseDirectory);
        var packageRoot = Directory.Exists(Path.Combine(baseDirectory, "Update"))
            ? baseDirectory
            : Path.GetFullPath(Path.Combine(baseDirectory, ".."));
        using var worker = PackagedWorkerRuntime.StartAsync(
                packageRoot,
                $"Probe{Environment.ProcessId}")
            .GetAwaiter()
            .GetResult();
        var document = new
        {
            schema = "stockroom-native-host-launch/1",
            release_id = worker.ReleaseId,
            host_package_version = LauncherDiagnostics.ProductVersion(),
            worker_base_uri = worker.BaseUri.AbsoluteUri,
            native_host = true,
            packaged_worker = true,
        };
        Directory.CreateDirectory(Path.GetDirectoryName(fullPath)!);
        var temporary = fullPath + $".{Environment.ProcessId}.tmp";
        File.WriteAllText(
            temporary,
            JsonSerializer.Serialize(document, new JsonSerializerOptions { WriteIndented = true }) + "\n");
        File.Move(temporary, fullPath);
        return 0;
    }
}
