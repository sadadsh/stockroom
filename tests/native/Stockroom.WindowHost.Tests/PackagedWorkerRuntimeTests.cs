using System.Collections.Concurrent;
using System.Diagnostics;
using System.Text;

namespace Stockroom.WindowHost.Tests;

public sealed class PackagedWorkerRuntimeTests
{
    [Fact]
    public void StartupProofBindsTheReleaseNonceAndExactSpawnedProcess()
    {
        using var credential = SensitiveCredential.Generate();
        var release = "release-1.0.0.42";
        var processId = 4567;
        var nonce = new string('a', 64);
        var context = Encoding.ASCII.GetBytes(
            $"stockroom-packaged-worker-v1\0{release}\0{processId}\0{nonce}");
        var proof = credential.HmacHex(context);

        Assert.True(PackagedWorkerRuntime.VerifyStartupProof(
            credential,
            release,
            processId,
            nonce,
            proof));
        Assert.False(PackagedWorkerRuntime.VerifyStartupProof(
            credential,
            release,
            processId + 1,
            nonce,
            proof));
        Assert.False(PackagedWorkerRuntime.VerifyStartupProof(
            credential,
            release,
            processId,
            new string('b', 64),
            proof));
    }

    [Fact]
    public void StorePackagePassesOnlyTheMicrosoftStoreUpdateAuthority()
    {
        var root = TestDirectory();
        try
        {
            var support = Path.Combine(root, "Support");
            var releaseDirectory = Path.Combine(
                root,
                "Update",
                "Initial Release",
                "release-1.0.42.0");
            Directory.CreateDirectory(support);
            Directory.CreateDirectory(Path.Combine(releaseDirectory, "Backend"));
            File.WriteAllText(
                Path.Combine(support, "Distribution.json"),
                """
                {
                  "channel": "microsoft-store",
                  "package_name": "Sadad.Stockroom",
                  "publisher": "CN=6586C41B-410B-4C94-8631-F025DB362E47",
                  "schema": "stockroom-distribution/1",
                  "store_id": "9NQ6HP17PH4H",
                  "store_uri": "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
                  "version": "1.0.42.0"
                }
                """);
            File.WriteAllBytes(
                Path.Combine(releaseDirectory, "Backend", "Stockroom Worker.exe"),
                "MZ"u8.ToArray());

            var release = PackagedRelease.Resolve(root);
            var start = new ProcessStartInfo();
            PackagedWorkerRuntime.ConfigureUpdateEnvironment(start, release);

            Assert.Equal("release-1.0.42.0", release.ReleaseId);
            Assert.Equal("microsoft_store", release.UpdateMode);
            Assert.Equal(
                "https://apps.microsoft.com/detail/9NQ6HP17PH4H",
                release.StoreUri);
            Assert.Equal("microsoft_store", start.Environment["STOCKROOM_UPDATE_MODE"]);
            Assert.False(start.Environment.ContainsKey("STOCKROOM_UPDATE_BUNDLE_ROOT"));
            Assert.Equal(
                root,
                start.Environment["STOCKROOM_STORE_PACKAGE_ROOT"]);
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task PostReadyCrashDrainsFinalOutputBeforeDiagnosticAndHostShutdown()
    {
        var root = TestDirectory();
        var ready = Path.Combine(root, "ready");
        var exit = Path.Combine(root, "exit");
        var diagnostic = Path.Combine(root, "diagnostic.log");
        var output = new ConcurrentQueue<string>();
        var shutdown = new TaskCompletionSource<int>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var diagnosticWasDurableBeforeShutdown = false;
        using var process = StartControlledWorker(ready, exit);
        using var drains = new WorkerOutputDrains(
            process.StandardOutput,
            process.StandardError,
            (eventName, line) =>
            {
                Thread.Sleep(2);
                output.Enqueue($"{eventName}:{line}");
            });
        using var monitor = WorkerLivenessMonitor.Start(
            cancellationToken => drains.WaitForExitAsync(
                process,
                TimeSpan.FromSeconds(3),
                cancellationToken),
            workerExitCode => File.AppendAllText(
                diagnostic,
                $"worker-exited-after-ready:{workerExitCode}"),
            workerExitCode =>
            {
                diagnosticWasDurableBeforeShutdown = File.ReadAllText(diagnostic).Contains(
                    "worker-exited-after-ready:23",
                    StringComparison.Ordinal);
                shutdown.TrySetResult(workerExitCode);
                return Task.CompletedTask;
            });

        try
        {
            await WaitForFileAsync(ready, TimeSpan.FromSeconds(5));
            File.WriteAllText(exit, "exit");

            Assert.Equal(23, await shutdown.Task.WaitAsync(TimeSpan.FromSeconds(10)));
            await monitor.Completion.WaitAsync(TimeSpan.FromSeconds(5));

            Assert.True(diagnosticWasDurableBeforeShutdown);
            Assert.Contains("worker-stdout:worker-final-output", output);
            Assert.Contains("worker-stderr:worker-final-error", output);
        }
        finally
        {
            StopProcess(process);
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public async Task ProductionCloseClaimsIntentionalShutdownBeforeWorkerCanExit()
    {
        var workerExit = new TaskCompletionSource<int>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var diagnostics = new List<int>();
        var shutdowns = new List<int>();
        using var monitor = WorkerLivenessMonitor.Start(
            cancellationToken => workerExit.Task.WaitAsync(cancellationToken),
            diagnostics.Add,
            workerExitCode =>
            {
                shutdowns.Add(workerExitCode);
                return Task.CompletedTask;
            });

        monitor.BeginIntentionalShutdown(
            () => workerExit.TrySetResult(0));
        await monitor.Completion.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.Empty(diagnostics);
        Assert.Empty(shutdowns);
    }

    private static string TestDirectory()
    {
        var path = Path.Combine(
            Path.GetTempPath(),
            "Stockroom.WindowHost.Tests",
            Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(path);
        return path;
    }

    private static Process StartControlledWorker(string ready, string exit)
    {
        var script = Path.Combine(Path.GetDirectoryName(ready)!, "worker.cmd");
        File.WriteAllLines(
            script,
            [
                "@echo off",
                $"> \"{ready}\" echo ready",
                ":wait",
                $"if not exist \"{exit}\" goto wait",
                "for /L %%i in (1,1,200) do echo worker-out-%%i",
                "echo worker-final-output",
                ">&2 echo worker-final-error",
                "exit /b 23",
            ]);
        var start = new ProcessStartInfo
        {
            FileName = Path.Combine(
                Environment.GetFolderPath(Environment.SpecialFolder.System),
                "cmd.exe"),
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("/D");
        start.ArgumentList.Add("/Q");
        start.ArgumentList.Add("/C");
        start.ArgumentList.Add(script);
        return Process.Start(start)
            ?? throw new InvalidOperationException("controlled worker did not start");
    }

    private static async Task WaitForFileAsync(string path, TimeSpan timeout)
    {
        using var deadline = new CancellationTokenSource(timeout);
        while (!File.Exists(path))
        {
            await Task.Delay(10, deadline.Token);
        }
    }

    private static void StopProcess(Process process)
    {
        try
        {
            if (!process.HasExited)
            {
                process.Kill(entireProcessTree: true);
                process.WaitForExit(5_000);
            }
        }
        catch (InvalidOperationException)
        {
            // The process exited between the liveness check and cleanup.
        }
    }
}
