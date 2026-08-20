using System.IO;
using System.IO.Pipes;
using System.Globalization;
using System.Security.AccessControl;
using System.Security.Principal;
using System.Text;

namespace Stockroom.WindowHost;

internal sealed class SingleInstanceActivation : IDisposable
{
    private static readonly string IdentitySuffix = CurrentIdentitySuffix();
    private static readonly string MutexName = @"Local\Stockroom.NativeHost." + IdentitySuffix;
    private static readonly string PipeName = "Stockroom.NativeHost.Activate." + IdentitySuffix;
    private const string RequestPrefix = "activate ";
    private const string Response = "activated\n";
    private const int MaximumMessageBytes = 96;

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

    internal static SingleInstanceActivation Acquire(
        Func<CancellationToken, Task<bool>> activate)
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
        return ActivateExistingAsync(
                PipeName,
                timeout,
                CancellationToken.None)
            .GetAwaiter()
            .GetResult();
    }

    internal static async Task<bool> ActivateExistingAsync(
        string pipeName,
        TimeSpan timeout,
        CancellationToken cancellationToken = default)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        if (timeout <= TimeSpan.Zero)
        {
            return false;
        }
        try
        {
            using var deadlineStop = CancellationTokenSource.CreateLinkedTokenSource(
                cancellationToken);
            deadlineStop.CancelAfter(timeout);
            var deadlineUtc = DateTimeOffset.UtcNow.Add(timeout).ToUnixTimeMilliseconds();
            using var client = new NamedPipeClientStream(
                ".",
                pipeName,
                PipeDirection.InOut,
                PipeOptions.Asynchronous,
                TokenImpersonationLevel.Identification);
            await client.ConnectAsync(deadlineStop.Token).ConfigureAwait(false);
            var request = Encoding.ASCII.GetBytes(
                RequestPrefix
                + deadlineUtc.ToString(CultureInfo.InvariantCulture)
                + "\n");
            await client.WriteAsync(request, deadlineStop.Token).ConfigureAwait(false);
            await client.FlushAsync(deadlineStop.Token).ConfigureAwait(false);
            var response = await ReadMessageAsync(client, deadlineStop.Token)
                .ConfigureAwait(false);
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

    private static async Task ServeAsync(
        Func<CancellationToken, Task<bool>> activate,
        CancellationToken stop)
    {
        while (!stop.IsCancellationRequested)
        {
            try
            {
                _ = await ServeOneAsync(PipeName, activate, stop).ConfigureAwait(false);
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

    internal static async Task<bool> ServeOneAsync(
        string pipeName,
        Func<CancellationToken, Task<bool>> activate,
        CancellationToken stop)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(pipeName);
        ArgumentNullException.ThrowIfNull(activate);
        await using var server = CreateServer(pipeName);
        await server.WaitForConnectionAsync(stop).ConfigureAwait(false);
        return await ProcessRequestAsync(server, server, activate, stop)
            .ConfigureAwait(false);
    }

    private static async Task<bool> ProcessRequestAsync(
        Stream input,
        Stream output,
        Func<CancellationToken, Task<bool>> activate,
        CancellationToken stop)
    {
        var message = await ReadMessageAsync(input, stop).ConfigureAwait(false);
        if (!TryParseDeadline(message, out var deadlineUtc))
        {
            return false;
        }
        var remaining = deadlineUtc - DateTimeOffset.UtcNow;
        if (remaining <= TimeSpan.Zero)
        {
            return false;
        }
        using var requestStop = CancellationTokenSource.CreateLinkedTokenSource(stop);
        requestStop.CancelAfter(remaining);
        try
        {
            var activated = await activate(requestStop.Token)
                .WaitAsync(requestStop.Token)
                .ConfigureAwait(false);
            if (!activated)
            {
                return false;
            }
            var response = Encoding.ASCII.GetBytes(Response);
            await output.WriteAsync(response, requestStop.Token).ConfigureAwait(false);
            await output.FlushAsync(requestStop.Token).ConfigureAwait(false);
            return true;
        }
        catch (OperationCanceledException)
            when (!stop.IsCancellationRequested && requestStop.IsCancellationRequested)
        {
            return false;
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

    private static bool TryParseDeadline(
        string message,
        out DateTimeOffset deadlineUtc)
    {
        deadlineUtc = default;
        if (!message.StartsWith(RequestPrefix, StringComparison.Ordinal)
            || !message.EndsWith('\n'))
        {
            return false;
        }
        var encodedDeadline = message[RequestPrefix.Length..^1];
        return long.TryParse(
                encodedDeadline,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var deadlineMilliseconds)
            && TryUnixMilliseconds(deadlineMilliseconds, out deadlineUtc);
    }

    private static bool TryUnixMilliseconds(
        long milliseconds,
        out DateTimeOffset value)
    {
        try
        {
            value = DateTimeOffset.FromUnixTimeMilliseconds(milliseconds);
            return true;
        }
        catch (ArgumentOutOfRangeException)
        {
            value = default;
            return false;
        }
    }

    private static async Task<string> ReadMessageAsync(
        Stream stream,
        CancellationToken cancellationToken)
    {
        var buffer = new byte[MaximumMessageBytes];
        var length = 0;
        while (length < buffer.Length)
        {
            var read = await stream.ReadAsync(
                    buffer.AsMemory(length, buffer.Length - length),
                    cancellationToken)
                .ConfigureAwait(false);
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
