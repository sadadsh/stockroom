using System.IO;
using System.IO.Pipes;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;

namespace Stockroom.WindowHost;

internal sealed class SingleInstanceActivation : IDisposable
{
    private static readonly string IdentitySuffix = CurrentIdentitySuffix();
    private static readonly string MutexName = @"Local\Stockroom.NativeHost." + IdentitySuffix;
    private static readonly string PipeName = "Stockroom.NativeHost.Activate." + IdentitySuffix;
    private const string Request = "activate\n";
    private const string Response = "activated\n";
    private const int MaximumMessageBytes = 64;

    private readonly Mutex? _mutex;
    private readonly CancellationTokenSource? _stop;
    private readonly Task? _server;

    private SingleInstanceActivation(
        bool isPrimary,
        Mutex? mutex,
        CancellationTokenSource? stop,
        Task? server)
    {
        IsPrimary = isPrimary;
        _mutex = mutex;
        _stop = stop;
        _server = server;
    }

    internal bool IsPrimary { get; }

    internal static SingleInstanceActivation Acquire(Action activate)
    {
        ArgumentNullException.ThrowIfNull(activate);
        var mutex = new Mutex(initiallyOwned: true, MutexName, out var createdNew);
        if (!createdNew)
        {
            mutex.Dispose();
            return new SingleInstanceActivation(false, null, null, null);
        }

        var stop = new CancellationTokenSource();
        var server = Task.Run(
            () => ServeAsync(activate, stop.Token),
            CancellationToken.None);
        return new SingleInstanceActivation(true, mutex, stop, server);
    }

    internal static bool ActivateExisting(TimeSpan timeout)
    {
        try
        {
            using var client = new NamedPipeClientStream(
                ".",
                PipeName,
                PipeDirection.InOut,
                PipeOptions.Asynchronous,
                TokenImpersonationLevel.Identification);
            client.Connect(checked((int)timeout.TotalMilliseconds));
            var request = Encoding.ASCII.GetBytes(Request);
            client.Write(request, 0, request.Length);
            client.Flush();
            var response = ReadMessage(client);
            return string.Equals(response, Response, StringComparison.Ordinal);
        }
        catch
        {
            return false;
        }
    }

    public void Dispose()
    {
        _stop?.Cancel();
        try
        {
            _server?.Wait(TimeSpan.FromSeconds(2));
        }
        catch
        {
            // Process teardown owns the final pipe close.
        }
        _stop?.Dispose();
        _mutex?.ReleaseMutex();
        _mutex?.Dispose();
    }

    private static async Task ServeAsync(Action activate, CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                await using var server = CreateServer();
                await server.WaitForConnectionAsync(stop).ConfigureAwait(false);
                if (!string.Equals(ReadMessage(server), Request, StringComparison.Ordinal))
                {
                    continue;
                }
                activate();
                var response = Encoding.ASCII.GetBytes(Response);
                await server.WriteAsync(response, stop).ConfigureAwait(false);
                await server.FlushAsync(stop).ConfigureAwait(false);
            }
            catch (OperationCanceledException) when (stop.IsCancellationRequested)
            {
                return;
            }
            catch (Exception exception)
            {
                LauncherDiagnostics.Write("activation-server-failed", exception: exception);
            }
        }
    }

    private static NamedPipeServerStream CreateServer()
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
            PipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous,
            4096,
            4096,
            security);
    }

    private static string CurrentIdentitySuffix()
    {
        var identity = WindowsIdentity.GetCurrent().User
            ?? throw new WindowHostException("current Windows identity is unavailable");
        return identity.Value.Replace('-', '_');
    }

    private static string ReadMessage(Stream stream)
    {
        var buffer = new byte[MaximumMessageBytes];
        var length = 0;
        while (length < buffer.Length)
        {
            var read = stream.Read(buffer, length, buffer.Length - length);
            if (read <= 0)
            {
                break;
            }
            length += read;
            if (buffer.AsSpan(0, length).Contains((byte)'\n'))
            {
                break;
            }
        }
        return Encoding.ASCII.GetString(buffer, 0, length);
    }
}
