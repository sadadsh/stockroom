using System.Diagnostics;
using System.IO.Pipes;

namespace Stockroom.WindowHost.Tests;

public sealed class SingleInstanceActivationTests
{
    [Fact]
    public async Task NamedPipeAcknowledgementWaitsForTheCompletedFocusOutcome()
    {
        var pipeName = TestPipeName();
        var focusStarted = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var allowFocus = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        using var testDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var server = SingleInstanceActivation.ServeOneAsync(
            pipeName,
            async cancellationToken =>
            {
                focusStarted.TrySetResult(true);
                await allowFocus.Task.WaitAsync(cancellationToken);
                return true;
            },
            testDeadline.Token);
        var client = SingleInstanceActivation.ActivateExistingAsync(
            pipeName,
            TimeSpan.FromSeconds(2),
            testDeadline.Token);

        await focusStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.False(client.IsCompleted);

        allowFocus.TrySetResult(true);

        Assert.True(await client);
        Assert.True(await server);
    }

    [Fact]
    public async Task OneNamedPipeDeadlineCancelsTheOutstandingFocusAttempt()
    {
        var pipeName = TestPipeName();
        var focusStarted = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var focusCancelled = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        using var testDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));

        var server = SingleInstanceActivation.ServeOneAsync(
            pipeName,
            async cancellationToken =>
            {
                focusStarted.TrySetResult(true);
                try
                {
                    await Task.Delay(Timeout.InfiniteTimeSpan, cancellationToken);
                    return true;
                }
                catch (OperationCanceledException)
                    when (cancellationToken.IsCancellationRequested)
                {
                    focusCancelled.TrySetResult(true);
                    throw;
                }
            },
            testDeadline.Token);
        var stopwatch = Stopwatch.StartNew();
        var client = SingleInstanceActivation.ActivateExistingAsync(
            pipeName,
            TimeSpan.FromMilliseconds(500),
            testDeadline.Token);

        await focusStarted.Task.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.False(await client);
        Assert.False(await server);
        await focusCancelled.Task.WaitAsync(TimeSpan.FromSeconds(2));
        Assert.InRange(stopwatch.Elapsed, TimeSpan.Zero, TimeSpan.FromSeconds(3));
    }

    [Fact]
    public async Task NamedPipeResponseReadCannotOutliveTheActivationDeadline()
    {
        var pipeName = TestPipeName();
        var requestRead = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        var releaseServer = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        await using var server = new NamedPipeServerStream(
            pipeName,
            PipeDirection.InOut,
            1,
            PipeTransmissionMode.Byte,
            PipeOptions.Asynchronous);
        using var testDeadline = new CancellationTokenSource(TimeSpan.FromSeconds(5));
        var serverTask = Task.Run(
            async () =>
            {
                await server.WaitForConnectionAsync(testDeadline.Token);
                var buffer = new byte[128];
                _ = await server.ReadAsync(buffer, testDeadline.Token);
                requestRead.TrySetResult(true);
                await releaseServer.Task.WaitAsync(testDeadline.Token);
            },
            CancellationToken.None);
        var stopwatch = Stopwatch.StartNew();
        var client = SingleInstanceActivation.ActivateExistingAsync(
            pipeName,
            TimeSpan.FromMilliseconds(500),
            testDeadline.Token);

        await requestRead.Task.WaitAsync(TimeSpan.FromSeconds(2));

        Assert.False(await client);
        Assert.InRange(stopwatch.Elapsed, TimeSpan.Zero, TimeSpan.FromSeconds(3));

        releaseServer.TrySetResult(true);
        await serverTask;
    }

    private static string TestPipeName() =>
        $"Stockroom.WindowHost.Tests.{Guid.NewGuid():N}";
}
