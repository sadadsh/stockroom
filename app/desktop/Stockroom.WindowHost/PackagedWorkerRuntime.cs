using System.Diagnostics;
using System.IO;
using System.Globalization;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal sealed class PackagedWorkerRuntime : IDisposable
{
    private const int StartupTimeoutSeconds = 120;
    private readonly Process _process;
    private readonly WindowsProcessJob _job;
    private readonly WorkerOutputDrains _output;
    private SensitiveCredential? _startupProofCredential;
    private bool _disposed;

    private PackagedWorkerRuntime(
        Process process,
        WindowsProcessJob job,
        Uri baseUri,
        string releaseId,
        SensitiveCredential apiCredential,
        SensitiveCredential startupProofCredential)
    {
        _process = process;
        _job = job;
        BaseUri = baseUri;
        ReleaseId = releaseId;
        ApiCredential = apiCredential;
        _startupProofCredential = startupProofCredential;
        _output = new WorkerOutputDrains(
            process.StandardOutput,
            process.StandardError,
            (eventName, detail) => LauncherDiagnostics.Write(eventName, detail));
    }

    internal Uri BaseUri { get; }
    internal string ReleaseId { get; }
    internal SensitiveCredential ApiCredential { get; }
    internal int ProcessId => _process.Id;

    internal Task<int> WaitForExitAsync(CancellationToken cancellationToken = default)
    {
        return _output.WaitForExitAsync(
            _process,
            TimeSpan.FromSeconds(2),
            cancellationToken);
    }

    internal static async Task<PackagedWorkerRuntime> StartAsync(
        string packageRoot,
        string? packageProbeScope = null,
        string? attachedWindowPipe = null,
        uint attachedWindowProcessId = 0,
        CancellationToken cancellationToken = default)
    {
        var release = PackagedRelease.Resolve(packageRoot);
        var port = ReserveLoopbackPort();
        var token = SensitiveCredential.Generate();
        var startupProof = SensitiveCredential.Generate();
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
        start.Environment["STOCKROOM_STARTUP_PROOF_TOKEN"] =
            startupProof.CreateEphemeralString();
        start.Environment["STOCKROOM_RELEASE_ID"] = release.ReleaseId;
        start.Environment["STOCKROOM_SERVICE_MODE"] = "coordinator";
        start.Environment["STOCKROOM_SERVICE_CONTROL_TOKEN"] = string.Empty;
        if (string.IsNullOrWhiteSpace(attachedWindowPipe) != (attachedWindowProcessId == 0))
        {
            throw new WindowHostException("attached native window identity is incomplete");
        }
        if (!string.IsNullOrWhiteSpace(attachedWindowPipe))
        {
            start.Environment["STOCKROOM_ATTACHED_WINDOW_PIPE"] = attachedWindowPipe;
            start.Environment["STOCKROOM_ATTACHED_WINDOW_PID"] =
                attachedWindowProcessId.ToString(CultureInfo.InvariantCulture);
        }
        ConfigureUpdateEnvironment(start, release);
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

        Process process;
        try
        {
            process = Process.Start(start)
                ?? throw new WindowHostException("packaged worker could not be started");
        }
        catch
        {
            startupProof.Dispose();
            token.Dispose();
            throw;
        }
        WindowsProcessJob job;
        try
        {
            job = WindowsProcessJob.Own(process);
        }
        catch
        {
            process.Kill(entireProcessTree: true);
            process.Dispose();
            startupProof.Dispose();
            token.Dispose();
            throw;
        }
        var runtime = new PackagedWorkerRuntime(
            process,
            job,
            new Uri($"http://127.0.0.1:{port}/", UriKind.Absolute),
            release.ReleaseId,
            token,
            startupProof);
        try
        {
            await runtime.WaitUntilReadyAsync(cancellationToken).ConfigureAwait(false);
            runtime.RetireStartupProof();
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

    internal static void ConfigureUpdateEnvironment(
        ProcessStartInfo start,
        PackagedRelease release)
    {
        start.Environment["STOCKROOM_UPDATE_MODE"] = release.UpdateMode;
        if (release.UpdateMode == "microsoft_store")
        {
            start.Environment.Remove("STOCKROOM_UPDATE_BUNDLE_ROOT");
            start.Environment["STOCKROOM_STORE_URI"] = release.StoreUri;
            start.Environment["STOCKROOM_STORE_PACKAGE_ROOT"] = Path.GetFullPath(
                Path.Combine(release.UpdateRoot, ".."));
            return;
        }
        start.Environment.Remove("STOCKROOM_STORE_URI");
        start.Environment.Remove("STOCKROOM_STORE_PACKAGE_ROOT");
        start.Environment["STOCKROOM_UPDATE_BUNDLE_ROOT"] = release.UpdateRoot;
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
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
            _ = _output.CompleteAsync(TimeSpan.FromSeconds(2))
                .GetAwaiter()
                .GetResult();
        }
        catch (Exception exception)
        {
            LauncherDiagnostics.Write("worker-output-drain-failed", exception: exception);
        }
        _output.Dispose();
        _process.Dispose();
        _job.Dispose();
        _startupProofCredential?.Dispose();
        _startupProofCredential = null;
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
        var nonce = Convert.ToHexStringLower(RandomNumberGenerator.GetBytes(32));
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
                using var request = new HttpRequestMessage(HttpMethod.Get, "api/health");
                request.Headers.Add("X-Stockroom-Startup-Nonce", nonce);
                using var response = await client.SendAsync(request, cancellationToken)
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
                        && root.GetProperty("coordinator_status").GetString() == "active"
                        && root.GetProperty("startup_process_id").GetInt32() == _process.Id
                        && VerifyStartupProof(
                            _startupProofCredential
                                ?? throw new WindowHostException(
                                    "packaged worker startup proof was unavailable"),
                            ReleaseId,
                            _process.Id,
                            nonce,
                            root.GetProperty("startup_proof").GetString() ?? string.Empty))
                    {
                        return;
                    }
                }
            }
            catch (Exception exception)
                when (exception is HttpRequestException
                    or TaskCanceledException
                    or JsonException
                    or KeyNotFoundException
                    or InvalidOperationException
                    or FormatException)
            {
                // The worker is still binding or building its first context.
            }
            await Task.Delay(100, cancellationToken).ConfigureAwait(false);
        }
        throw new WindowHostException("packaged worker readiness timed out");
    }

    private void RetireStartupProof()
    {
        _startupProofCredential?.Dispose();
        _startupProofCredential = null;
    }

    internal static bool VerifyStartupProof(
        SensitiveCredential credential,
        string releaseId,
        int processId,
        string nonce,
        string proof)
    {
        ArgumentNullException.ThrowIfNull(credential);
        if (nonce.Length != 64 || nonce.Any(
                character => character is not (>= '0' and <= '9')
                    and not (>= 'a' and <= 'f')))
        {
            return false;
        }
        var message = Encoding.ASCII.GetBytes(
            $"stockroom-packaged-worker-v1\0{releaseId}\0{processId}\0{nonce}");
        try
        {
            return credential.VerifyHmacHex(message, proof);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(message);
        }
    }

    private static int ReserveLoopbackPort()
    {
        using var listener = new TcpListener(IPAddress.Loopback, 0);
        listener.Start();
        return ((IPEndPoint)listener.LocalEndpoint).Port;
    }

}

internal sealed class WorkerOutputDrains : IDisposable
{
    private readonly CancellationTokenSource _stop = new();
    private readonly Action<string, string> _write;
    private readonly Task _completion;
    private readonly object _sync = new();
    private Task<bool>? _finish;
    private bool _disposed;

    internal WorkerOutputDrains(
        StreamReader standardOutput,
        StreamReader standardError,
        Action<string, string> write)
    {
        ArgumentNullException.ThrowIfNull(standardOutput);
        ArgumentNullException.ThrowIfNull(standardError);
        ArgumentNullException.ThrowIfNull(write);
        _write = write;
        _completion = Task.WhenAll(
            DrainAsync(standardOutput, "worker-stdout", _stop.Token),
            DrainAsync(standardError, "worker-stderr", _stop.Token));
    }

    internal async Task<int> WaitForExitAsync(
        Process process,
        TimeSpan drainTimeout,
        CancellationToken cancellationToken)
    {
        ArgumentNullException.ThrowIfNull(process);
        await process.WaitForExitAsync(cancellationToken).ConfigureAwait(false);
        _ = await CompleteAsync(drainTimeout).ConfigureAwait(false);
        return process.ExitCode;
    }

    internal Task<bool> CompleteAsync(TimeSpan timeout)
    {
        lock (_sync)
        {
            ObjectDisposedException.ThrowIf(_disposed, this);
            return _finish ??= CompleteCoreAsync(timeout);
        }
    }

    private async Task<bool> CompleteCoreAsync(TimeSpan timeout)
    {
        try
        {
            await _completion.WaitAsync(timeout).ConfigureAwait(false);
            return true;
        }
        catch (TimeoutException)
        {
            _write("worker-output-drain-timeout", string.Empty);
            _stop.Cancel();
            try
            {
                await _completion.WaitAsync(TimeSpan.FromMilliseconds(250))
                    .ConfigureAwait(false);
            }
            catch
            {
                // The bounded output-drain deadline already records this loss.
            }
            return false;
        }
        catch (Exception exception)
        {
            _write("worker-output-drain-failed", exception.Message);
            return false;
        }
    }

    private async Task DrainAsync(
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
                _write(eventName, line);
            }
        }
    }

    public void Dispose()
    {
        lock (_sync)
        {
            if (_disposed)
            {
                return;
            }
            _disposed = true;
        }
        if (!_completion.IsCompleted)
        {
            _stop.Cancel();
        }
        try
        {
            _completion.Wait(TimeSpan.FromMilliseconds(250));
        }
        catch
        {
            // Output draining is already bounded and best effort at final disposal.
        }
        _stop.Dispose();
    }
}

internal sealed class WorkerLivenessMonitor : IDisposable
{
    private const int Running = 0;
    private const int IntentionalShutdown = 1;
    private const int UnexpectedExit = 2;

    private readonly CancellationTokenSource _stop = new();
    private readonly Action<int> _recordUnexpectedExit;
    private readonly Func<int, Task> _shutdownHost;
    private int _state;
    private bool _disposed;

    private WorkerLivenessMonitor(
        Func<CancellationToken, Task<int>> waitForExit,
        Action<int> recordUnexpectedExit,
        Func<int, Task> shutdownHost)
    {
        _recordUnexpectedExit = recordUnexpectedExit;
        _shutdownHost = shutdownHost;
        Completion = ObserveAsync(waitForExit);
    }

    internal Task Completion { get; }

    internal static WorkerLivenessMonitor Start(
        Func<CancellationToken, Task<int>> waitForExit,
        Action<int> recordUnexpectedExit,
        Func<int, Task> shutdownHost)
    {
        ArgumentNullException.ThrowIfNull(waitForExit);
        ArgumentNullException.ThrowIfNull(recordUnexpectedExit);
        ArgumentNullException.ThrowIfNull(shutdownHost);
        return new WorkerLivenessMonitor(
            waitForExit,
            recordUnexpectedExit,
            shutdownHost);
    }

    internal void BeginIntentionalShutdown()
    {
        if (Interlocked.CompareExchange(
                ref _state,
                IntentionalShutdown,
                Running) == Running)
        {
            _stop.Cancel();
        }
    }

    internal void BeginIntentionalShutdown(Action beginHostShutdown)
    {
        ArgumentNullException.ThrowIfNull(beginHostShutdown);
        BeginIntentionalShutdown();
        beginHostShutdown();
    }

    private async Task ObserveAsync(Func<CancellationToken, Task<int>> waitForExit)
    {
        int exitCode;
        try
        {
            exitCode = await waitForExit(_stop.Token).ConfigureAwait(false);
        }
        catch (OperationCanceledException) when (_stop.IsCancellationRequested)
        {
            return;
        }
        if (Interlocked.CompareExchange(
                ref _state,
                UnexpectedExit,
                Running) != Running)
        {
            return;
        }
        _recordUnexpectedExit(exitCode);
        await _shutdownHost(exitCode).ConfigureAwait(false);
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }
        _disposed = true;
        BeginIntentionalShutdown();
        try
        {
            Completion.Wait(TimeSpan.FromSeconds(2));
        }
        catch
        {
            // The owner observes and records completion before final disposal.
        }
        _stop.Dispose();
    }
}

internal sealed record PackagedRelease(
    string ReleaseId,
    string ReleaseDirectory,
    string WorkerExecutable,
    string UpdateRoot,
    string UpdateMode,
    string StoreUri)
{
    internal static PackagedRelease Resolve(string packageRoot)
    {
        var updateRoot = Path.GetFullPath(Path.Combine(packageRoot, "Update"));
        var markerPath = Path.Combine(packageRoot, "Support", "Distribution.json");
        string? releaseId;
        string updateMode;
        string storeUri;
        if (File.Exists(markerPath))
        {
            using var marker = JsonDocument.Parse(File.ReadAllBytes(markerPath));
            var root = marker.RootElement;
            var keys = root.EnumerateObject().Select(property => property.Name).ToHashSet(
                StringComparer.Ordinal);
            var expectedKeys = new HashSet<string>(
                [
                    "channel",
                    "package_name",
                    "publisher",
                    "schema",
                    "store_id",
                    "store_uri",
                    "version",
                ],
                StringComparer.Ordinal);
            var version = root.GetProperty("version").GetString();
            storeUri = root.GetProperty("store_uri").GetString() ?? string.Empty;
            if (!keys.SetEquals(expectedKeys)
                || root.GetProperty("schema").GetString() != "stockroom-distribution/1"
                || root.GetProperty("channel").GetString() != "microsoft-store"
                || root.GetProperty("package_name").GetString() != "Sadad.Stockroom"
                || root.GetProperty("publisher").GetString()
                    != "CN=6586C41B-410B-4C94-8631-F025DB362E47"
                || root.GetProperty("store_id").GetString() != "9NQ6HP17PH4H"
                || storeUri != "https://apps.microsoft.com/detail/9NQ6HP17PH4H"
                || string.IsNullOrWhiteSpace(version)
                || File.Exists(Path.Combine(updateRoot, "Update Feed.json")))
            {
                throw new WindowHostException("Microsoft Store distribution marker is invalid");
            }
            releaseId = $"release-{version}";
            updateMode = "microsoft_store";
        }
        else
        {
            var descriptorPath = Path.Combine(updateRoot, "Update Feed.json");
            using var descriptor = JsonDocument.Parse(File.ReadAllBytes(descriptorPath));
            releaseId = descriptor.RootElement
                .GetProperty("current_release_id")
                .GetString();
            updateMode = "production";
            storeUri = string.Empty;
        }
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
        return new PackagedRelease(
            releaseId,
            releaseDirectory,
            worker,
            updateRoot,
            updateMode,
            storeUri);
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
