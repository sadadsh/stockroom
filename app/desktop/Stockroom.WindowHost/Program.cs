using System.IO;
using System.IO.Pipes;
using System.Windows;
using System.Windows.Threading;

namespace Stockroom.WindowHost;

internal static class Program
{
    private static readonly IntPtr PerMonitorAwareV2 = new(-4);

    [STAThread]
    internal static int Main(string[] arguments)
    {
        if (!OperatingSystem.IsWindows())
        {
            return 1;
        }

        _ = NativeMethods.SetProcessDpiAwarenessContext(PerMonitorAwareV2);
        try
        {
            if (arguments.Length == 0)
            {
                return RunStandalone();
            }
            if (arguments.Length == 2 && arguments[0] == "--native-host-probe")
            {
                return NativeHostProbe.Run(arguments[1]);
            }
            var parsed = HostArguments.Parse(arguments);
            var pipe = SecureNamedPipeConnection.Connect(
                parsed.PipeName,
                parsed.ParentProcessId);
            return RunManagedChild(parsed, pipe);
        }
        catch (Exception exception)
        {
            LauncherDiagnostics.Write("native-host-failed", exception: exception);
            ShowFatal(exception.Message);
            return 1;
        }
    }

    private static int RunStandalone()
    {
        Application? application = null;
        WebViewWindowHost? host = null;
        var pendingActivation = 0;
        using var activation = SingleInstanceActivation.Acquire(
            () =>
            {
                Interlocked.Exchange(ref pendingActivation, 1);
                var dispatcher = application?.Dispatcher;
                if (dispatcher is not null)
                {
                    _ = dispatcher.BeginInvoke(
                        () =>
                        {
                            if (host is not null)
                            {
                                host.Focus();
                                Interlocked.Exchange(ref pendingActivation, 0);
                            }
                        });
                }
            });
        if (!activation.IsPrimary)
        {
            var activated = SingleInstanceActivation.ActivateExisting(
                TimeSpan.FromSeconds(5));
            LauncherDiagnostics.Write(
                activated ? "existing-window-activated" : "existing-window-activation-failed");
            return activated ? 0 : 2;
        }

        var temporaryRoot = Path.GetTempPath();
        var removed = PyInstallerTemporaryCleanup.RemoveOrphans(
            temporaryRoot,
            DateTimeOffset.UtcNow);
        if (removed > 0)
        {
            LauncherDiagnostics.Write("orphaned-bootstrap-bundles-removed", removed.ToString());
        }

        var baseDirectory = Path.GetFullPath(AppContext.BaseDirectory);
        var packageRoot = Directory.Exists(Path.Combine(baseDirectory, "Update"))
            ? baseDirectory
            : Path.GetFullPath(Path.Combine(baseDirectory, ".."));
        LauncherDiagnostics.Write(
            "native-host-starting",
            $"package={packageRoot};version={LauncherDiagnostics.ProductVersion()}");
        using var worker = PackagedWorkerRuntime.StartAsync(packageRoot)
            .GetAwaiter()
            .GetResult();
        using var bootstrap = HandoffBootstrap.CreateDirect(
            worker.ReleaseId,
            worker.BaseUri,
            worker.ApiCredential);
        application = new Application
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown,
        };
        var exitCode = 0;
        DispatcherTimer? closeTimer = null;
        application.Startup += async (_, _) =>
        {
            try
            {
                var machineConfig = MachineWindowConfig.Load();
                host = new WebViewWindowHost(
                    bootstrap,
                    machineConfig,
                    () => application.Shutdown(1));
                await host.InitializeAsync().ConfigureAwait(true);
                host.PrepareHidden(DateTimeOffset.UtcNow.AddSeconds(30).ToUnixTimeMilliseconds());
                host.Show();
                host.Focus();
                Interlocked.Exchange(ref pendingActivation, 0);
                closeTimer = new DispatcherTimer(TimeSpan.FromMilliseconds(200), DispatcherPriority.Normal, (_, _) =>
                {
                    if (host.Health().TryGetValue("close_requested", out var requested)
                        && requested is true)
                    {
                        closeTimer?.Stop();
                        host.Shutdown();
                    }
                    else if (Interlocked.Exchange(ref pendingActivation, 0) == 1)
                    {
                        host.Focus();
                    }
                }, application.Dispatcher);
                closeTimer.Start();
                LauncherDiagnostics.Write("native-host-ready", $"release={worker.ReleaseId}");
            }
            catch (Exception exception)
            {
                exitCode = 1;
                LauncherDiagnostics.Write("native-host-initialization-failed", exception: exception);
                application.Shutdown(1);
            }
        };
        try
        {
            _ = application.Run();
        }
        finally
        {
            closeTimer?.Stop();
            host?.Dispose();
            LauncherDiagnostics.Write("native-host-stopped", $"exit_code={exitCode}");
        }
        return exitCode;
    }

    private static int RunManagedChild(
        HostArguments arguments,
        NamedPipeClientStream pipe)
    {
        using var channel = new HandoffChannel(pipe);
        var bootstrapMessage = channel.Receive("bootstrap");
        using var bootstrap = BootstrapParser.Parse(bootstrapMessage);
        if (channel.HandoffId != bootstrap.HandoffId)
        {
            throw new WindowHostException("window-host channel identity changed");
        }

        var machineConfig = MachineWindowConfig.Load();
        var application = new Application
        {
            ShutdownMode = ShutdownMode.OnExplicitShutdown,
        };
        var exitCode = 0;
        Task? commandTask = null;
        WebViewWindowHost? host = null;

        void FailClosed()
        {
            Interlocked.Exchange(ref exitCode, host?.FailureExitCode ?? 1);
            host?.BeginFailureShutdown();
            try
            {
                channel.Dispose();
            }
            catch
            {
                // The supervisor owns final process reaping.
            }
            _ = application.Dispatcher.BeginInvoke(() => application.Shutdown(1));
        }

        application.Startup += async (_, _) =>
        {
            try
            {
                host = new WebViewWindowHost(bootstrap, machineConfig, FailClosed);
                await host.InitializeAsync().ConfigureAwait(true);
                var childProcessId = checked((uint)Environment.ProcessId);
                var controller = new WebViewWindowController(host, bootstrap.ProfileId);
                var session = new WindowHostSession(
                    channel,
                    bootstrap,
                    controller,
                    arguments.ParentProcessId,
                    childProcessId);
                commandTask = Task.Run(
                    () =>
                    {
                        try
                        {
                            session.Run();
                        }
                        catch
                        {
                            FailClosed();
                        }
                    });
            }
            catch
            {
                FailClosed();
            }
        };

        try
        {
            _ = application.Run();
        }
        finally
        {
            try
            {
                channel.Dispose();
            }
            catch
            {
                Interlocked.Exchange(ref exitCode, 1);
            }
            if (commandTask is not null
                && !commandTask.Wait(TimeSpan.FromSeconds(5)))
            {
                Interlocked.Exchange(ref exitCode, 1);
            }
            host?.Dispose();
        }
        return Volatile.Read(ref exitCode);
    }

    private static void ShowFatal(string detail)
    {
        try
        {
            _ = MessageBox.Show(
                "Stockroom could not start. Diagnostics were written to:\n\n"
                + LauncherDiagnostics.LogPath
                + "\n\n"
                + detail,
                "Stockroom could not start",
                MessageBoxButton.OK,
                MessageBoxImage.Error);
        }
        catch
        {
            // The durable log remains available when UI reporting also fails.
        }
    }
}
