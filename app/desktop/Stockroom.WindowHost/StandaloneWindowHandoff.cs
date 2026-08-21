using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;

namespace Stockroom.WindowHost;

/// <summary>
/// Binds the packaged Python worker back to the standalone WPF process that launched it.
/// The normal managed-window protocol remains the only provider lease/download protocol; this
/// class only reverses which process owns the first-instance pipe.
/// </summary>
internal sealed class StandaloneWindowHandoff : IDisposable
{
    private const int ConnectionTimeoutSeconds = 30;
    private readonly NamedPipeServerStream _server;
    private HandoffChannel? _channel;
    private HandoffBootstrap? _bootstrap;
    private Task? _sessionTask;
    private uint _workerProcessId;
    private bool _disposed;

    private StandaloneWindowHandoff(string pipeName, NamedPipeServerStream server)
    {
        PipeName = pipeName;
        _server = server;
    }

    internal string PipeName { get; }

    internal static StandaloneWindowHandoff Create()
    {
        var pipeName = "Stockroom.WindowHandoff." + Guid.NewGuid().ToString("N");
        return new StandaloneWindowHandoff(pipeName, CreateServer(pipeName));
    }

    internal void BindWorker(PackagedWorkerRuntime worker)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(worker);
        if (_channel is not null)
        {
            throw new WindowHostException("standalone window handoff was already bound");
        }

        using var timeout = new CancellationTokenSource(
            TimeSpan.FromSeconds(ConnectionTimeoutSeconds));
        try
        {
            _server.WaitForConnectionAsync(timeout.Token)
                .GetAwaiter()
                .GetResult();
        }
        catch (OperationCanceledException)
        {
            throw new WindowHostException(
                "packaged worker did not connect to the native window handoff");
        }

        if (!NativeMethods.GetNamedPipeClientProcessId(
                _server.SafePipeHandle,
                out var clientProcessId)
            || clientProcessId != checked((uint)worker.ProcessId))
        {
            throw new WindowHostException(
                "native window handoff client did not match the packaged worker");
        }
        WindowsPipeSecurity.RequireCurrentSidOnly(_server.SafePipeHandle);

        var channel = new HandoffChannel(_server);
        HandoffBootstrap? parsed = null;
        try
        {
            var bootstrapMessage = channel.Receive("bootstrap");
            parsed = BootstrapParser.Parse(bootstrapMessage);
            if (channel.HandoffId != parsed.HandoffId
                || parsed.ReleaseId != worker.ReleaseId
                || parsed.BaseUri != worker.BaseUri
                || !parsed.ApiCredential.FixedTimeEquals(worker.ApiCredential))
            {
                throw new WindowHostException(
                    "standalone window handoff identity changed");
            }
            _workerProcessId = clientProcessId;
            _channel = channel;
            _bootstrap = parsed;
        }
        catch
        {
            parsed?.Dispose();
            channel.Dispose();
            throw;
        }
    }

    internal void StartSession(WebViewWindowHost host, string profileId)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        ArgumentNullException.ThrowIfNull(host);
        var channel = _channel
            ?? throw new WindowHostException("standalone window handoff is not bound");
        var bootstrap = _bootstrap
            ?? throw new WindowHostException("standalone window bootstrap is unavailable");
        if (_sessionTask is not null)
        {
            throw new WindowHostException("standalone window handoff session already started");
        }

        var controller = new WebViewWindowController(host, profileId);
        var session = new WindowHostSession(
            channel,
            bootstrap,
            controller,
            _workerProcessId,
            checked((uint)Environment.ProcessId));
        _sessionTask = Task.Run(
            () =>
            {
                try
                {
                    session.Run();
                }
                catch (Exception exception)
                {
                    if (!_disposed)
                    {
                        LauncherDiagnostics.Write(
                            "standalone-window-handoff-failed",
                            exception: exception);
                    }
                }
            });
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
            _channel?.Dispose();
        }
        catch (Exception exception)
        {
            LauncherDiagnostics.Write(
                "standalone-window-handoff-close-failed",
                exception: exception);
        }
        if (_channel is null)
        {
            _server.Dispose();
        }
        _bootstrap?.Dispose();
        if (_sessionTask is not null
            && !_sessionTask.Wait(TimeSpan.FromSeconds(5)))
        {
            LauncherDiagnostics.Write("standalone-window-handoff-stop-timeout");
        }
    }

    private static NamedPipeServerStream CreateServer(string pipeName)
    {
        var identity = WindowsIdentity.GetCurrent().User
            ?? throw new WindowHostException("current Windows identity is unavailable");
        var security = new PipeSecurity();
        security.SetAccessRuleProtection(isProtected: true, preserveInheritance: false);
        security.SetOwner(identity);
        security.AddAccessRule(
            new PipeAccessRule(
                identity,
                PipeAccessRights.ReadWrite | PipeAccessRights.CreateNewInstance,
                AccessControlType.Allow));
        return NamedPipeServerStreamAcl.Create(
            pipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous,
            64 * 1024,
            64 * 1024,
            security);
    }
}
