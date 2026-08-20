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
        var powershell = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.System),
            "WindowsPowerShell",
            "v1.0",
            "powershell.exe");
        var script = string.Join(
            "; ",
            "$ErrorActionPreference = 'Stop'",
            $"[IO.File]::WriteAllText('{Ps(ready)}', 'ready')",
            $"while (-not [IO.File]::Exists('{Ps(exit)}')) {{ Start-Sleep -Milliseconds 10 }}",
            "1..200 | ForEach-Object { [Console]::Out.WriteLine(\"worker-out-$_\") }",
            "[Console]::Out.WriteLine('worker-final-output')",
            "[Console]::Error.WriteLine('worker-final-error')",
            "exit 23");
        var start = new ProcessStartInfo
        {
            FileName = powershell,
            UseShellExecute = false,
            CreateNoWindow = true,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
        };
        start.ArgumentList.Add("-NoLogo");
        start.ArgumentList.Add("-NoProfile");
        start.ArgumentList.Add("-NonInteractive");
        start.ArgumentList.Add("-Command");
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

    private static string Ps(string value) => value.Replace("'", "''", StringComparison.Ordinal);
}
