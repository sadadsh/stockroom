using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal sealed class PackagedWorkerRuntime : IDisposable
{
    private const int StartupTimeoutSeconds = 120;
    private readonly Process _process;
    private readonly WindowsProcessJob _job;
    private readonly CancellationTokenSource _loggingStop = new();
    private readonly Task _stdout;
    private readonly Task _stderr;
    private bool _disposed;

    private PackagedWorkerRuntime(
        Process process,
        WindowsProcessJob job,
        Uri baseUri,
        string releaseId,
        SensitiveCredential apiCredential)
    {
        _process = process;
        _job = job;
        BaseUri = baseUri;
        ReleaseId = releaseId;
        ApiCredential = apiCredential;
        _stdout = DrainAsync(process.StandardOutput, "worker-stdout", _loggingStop.Token);
        _stderr = DrainAsync(process.StandardError, "worker-stderr", _loggingStop.Token);
    }

    internal Uri BaseUri { get; }
    internal string ReleaseId { get; }
    internal SensitiveCredential ApiCredential { get; }

    internal static async Task<PackagedWorkerRuntime> StartAsync(
        string packageRoot,
        string? packageProbeScope = null,
        CancellationToken cancellationToken = default)
    {
        var release = PackagedRelease.Resolve(packageRoot);
        var port = ReserveLoopbackPort();
        var token = SensitiveCredential.Generate();
        var start = new ProcessStartInfo
        {
            FileName = release.WorkerExecutable,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardError = true,
            RedirectStandardOutput = true,
            WorkingDirectory = release.ReleaseDirectory,
        };
        start.ArgumentList.Add("--port");
        start.ArgumentList.Add(port.ToString(CultureInfo.InvariantCulture));
        start.Environment["STOCKROOM_HANDOFF_TOKEN"] = token.CreateEphemeralString();
        start.Environment["STOCKROOM_RELEASE_ID"] = release.ReleaseId;
        start.Environment["STOCKROOM_SERVICE_MODE"] = "coordinator";
        start.Environment["STOCKROOM_SERVICE_CONTROL_TOKEN"] = string.Empty;
        start.Environment["STOCKROOM_UPDATE_MODE"] = "production";
        start.Environment["STOCKROOM_UPDATE_BUNDLE_ROOT"] = release.UpdateRoot;
        if (!string.IsNullOrWhiteSpace(packageProbeScope))
        {
            start.Environment["STOCKROOM_PACKAGE_PROBE_SCOPE"] = packageProbeScope;
        }
        var localAppData = Environment.GetEnvironmentVariable("LOCALAPPDATA");
        if (string.IsNullOrWhiteSpace(localAppData))
        {
            localAppData = Environment.GetFolderPath(
                Environment.SpecialFolder.LocalApplicationData);
        }
        var serviceRoot = Path.Combine(localAppData, "Stockroom", "Service State");
        start.Environment["STOCKROOM_CONTROL_DATABASE"] = Path.Combine(serviceRoot, "Control.sqlite");
        start.Environment["STOCKROOM_WORKFLOW_DATABASE"] = Path.Combine(serviceRoot, "Workflow.sqlite");
        var converter = Path.Combine(
            release.ReleaseDirectory,
            "Tools",
            "CadConverter",
            "Stockroom.CadConverter.exe");
        if (File.Exists(converter))
        {
            start.Environment["STOCKROOM_CAD_CONVERTER"] = converter;
        }

        var process = Process.Start(start)
            ?? throw new WindowHostException("packaged worker could not be started");
        WindowsProcessJob job;
        try
        {
            job = WindowsProcessJob.Own(process);
        }
        catch
        {
            process.Kill(entireProcessTree: true);
            process.Dispose();
            token.Dispose();
            throw;
        }
        var runtime = new PackagedWorkerRuntime(
            process,
            job,
            new Uri($"http://127.0.0.1:{port}/", UriKind.Absolute),
            release.ReleaseId,
            token);
        try
        {
            await runtime.WaitUntilReadyAsync(cancellationToken).ConfigureAwait(false);
            LauncherDiagnostics.Write(
                "worker-ready",
                $"release={release.ReleaseId};pid={process.Id}");
            return runtime;
        }
        catch
        {
            runtime.Dispose();
            throw;
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        _loggingStop.Cancel();
        try
        {
            if (!_process.HasExited)
            {
                _process.Kill(entireProcessTree: true);
                _process.WaitForExit(10_000);
            }
        }
        catch (Exception exception)
        {
            LauncherDiagnostics.Write("worker-stop-failed", exception: exception);
        }
        try
        {
            Task.WaitAll([_stdout, _stderr], TimeSpan.FromSeconds(2));
        }
        catch
        {
            // Logging is best effort during process teardown.
        }
        _process.Dispose();
        _job.Dispose();
        _loggingStop.Dispose();
        ApiCredential.Dispose();
    }

    private async Task WaitUntilReadyAsync(CancellationToken cancellationToken)
    {
        using var client = new HttpClient
        {
            BaseAddress = BaseUri,
            Timeout = TimeSpan.FromSeconds(5),
        };
        var deadline = DateTimeOffset.UtcNow.AddSeconds(StartupTimeoutSeconds);
        while (DateTimeOffset.UtcNow < deadline)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (_process.HasExited)
            {
                throw new WindowHostException(
                    $"packaged worker exited during startup with code {_process.ExitCode}");
            }
            try
            {
                using var response = await client.GetAsync("api/health", cancellationToken)
                    .ConfigureAwait(false);
                if (response.StatusCode == HttpStatusCode.OK)
                {
                    using var document = JsonDocument.Parse(
                        await response.Content.ReadAsByteArrayAsync(cancellationToken)
                            .ConfigureAwait(false));
                    var root = document.RootElement;
                    if (
                        root.GetProperty("status").GetString() == "ok"
                        && root.GetProperty("release_id").GetString() == ReleaseId
                        && root.GetProperty("service_mode").GetString() == "coordinator"
                        && root.GetProperty("coordinator_status").GetString() == "active")
                    {
                        return;
                    }
                }
            }
            catch (Exception exception)
                when (exception is HttpRequestException
                    or TaskCanceledException
                    or JsonException
                    or KeyNotFoundException)
            {
                // The worker is still binding or building its first context.
            }
            await Task.Delay(100, cancellationToken).ConfigureAwait(false);
        }
        throw new WindowHostException("packaged worker readiness timed out");
    }

    private static int ReserveLoopbackPort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

    private static async Task DrainAsync(
        StreamReader reader,
        string eventName,
        CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            string? line;
            try
            {
                line = await reader.ReadLineAsync(stop).ConfigureAwait(false);
            }
            catch (OperationCanceledException)
            {
                return;
            }
            if (line is null)
            {
                return;
            }
            if (!string.IsNullOrWhiteSpace(line))
            {
                LauncherDiagnostics.Write(eventName, line);
            }
        }
    }
}

internal sealed record PackagedRelease(
    string ReleaseId,
    string ReleaseDirectory,
    string WorkerExecutable,
    string UpdateRoot)
{
    internal static PackagedRelease Resolve(string packageRoot)
    {
        var updateRoot = Path.GetFullPath(Path.Combine(packageRoot, "Update"));
        var descriptorPath = Path.Combine(updateRoot, "Update Feed.json");
        using var descriptor = JsonDocument.Parse(File.ReadAllBytes(descriptorPath));
        var releaseId = descriptor.RootElement
            .GetProperty("current_release_id")
            .GetString();
        if (string.IsNullOrWhiteSpace(releaseId)
            || releaseId.IndexOfAny(Path.GetInvalidFileNameChars()) >= 0)
        {
            throw new WindowHostException("packaged release identity is invalid");
        }
        var releaseDirectory = Path.GetFullPath(
            Path.Combine(updateRoot, "Initial Release", releaseId));
        if (!releaseDirectory.StartsWith(
                updateRoot + Path.DirectorySeparatorChar,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new WindowHostException("packaged release escaped its update root");
        }
        var worker = Path.Combine(releaseDirectory, "Backend", "Stockroom Worker.exe");
        if (!File.Exists(worker))
        {
            throw new WindowHostException("packaged worker is unavailable");
        }
        return new PackagedRelease(releaseId, releaseDirectory, worker, updateRoot);
    }
}

internal static class PyInstallerTemporaryCleanup
{
    internal static int RemoveOrphans(string temporaryRoot, DateTimeOffset now)
    {
        if (!Directory.Exists(temporaryRoot))
        {
            return 0;
        }
        var removed = 0;
        foreach (var directory in Directory.EnumerateDirectories(temporaryRoot, "_MEI*"))
        {
            try
            {
                var info = new DirectoryInfo(directory);
                if (now - info.LastWriteTimeUtc < TimeSpan.FromHours(1)
                    || !File.Exists(Path.Combine(directory, "stockroom-build-identity.json")))
                {
                    continue;
                }
                Directory.Delete(directory, recursive: true);
                removed += 1;
            }
            catch
            {
                // An active or protected extraction is not an orphan we may remove.
            }
        }
        return removed;
    }
}
