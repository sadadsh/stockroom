using System.Diagnostics;
using System.IO.Pipes;
using System.Windows;

namespace Stockroom.WindowHost;

internal static class Program
{
    private static readonly IntPtr PerMonitorAwareV2 =
        new(-4);

    [STAThread]
    internal static int Main(string[] arguments)
    {
        if (!OperatingSystem.IsWindows())
        {
            return 1;
        }

        try
        {
            _ = NativeMethods.SetProcessDpiAwarenessContext(
                PerMonitorAwareV2);
            var parsed = HostArguments.Parse(arguments);
            var pipe = SecureNamedPipeConnection.Connect(
                parsed.PipeName,
                parsed.ParentProcessId);
            return RunApplication(parsed, pipe);
        }
        catch
        {
            return 1;
        }
    }

    private static int RunApplication(
        HostArguments arguments,
        NamedPipeClientStream pipe)
    {
        using var channel = new HandoffChannel(pipe);
        var bootstrapMessage = channel.Receive("bootstrap");
        using var bootstrap = BootstrapParser.Parse(
            bootstrapMessage);
        if (channel.HandoffId != bootstrap.HandoffId)
        {
            throw new WindowHostException(
                "window-host channel identity changed");
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
            Interlocked.Exchange(
                ref exitCode,
                host?.FailureExitCode ?? 1);
            host?.BeginFailureShutdown();
            try
            {
                channel.Dispose();
            }
            catch
            {
                // The supervisor owns final process reaping.
            }

            _ = application.Dispatcher.BeginInvoke(
                () => application.Shutdown(1));
        }

        application.Startup += async (_, _) =>
        {
            try
            {
                host = new WebViewWindowHost(
                    bootstrap,
                    machineConfig,
                    FailClosed);
                await host.InitializeAsync()
                    .ConfigureAwait(true);
                var childProcessId = checked(
                    (uint)Environment.ProcessId);
                var controller = new WebViewWindowController(
                    host,
                    bootstrap.ProfileId);
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
}
