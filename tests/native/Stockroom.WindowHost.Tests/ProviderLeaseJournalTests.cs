namespace Stockroom.WindowHost.Tests;

public sealed class ProviderLeaseJournalTests
{
    private static readonly ProviderLeaseContext Context = new(
        @"C:\Capture\Downloads\task-1",
        "component-9",
        "Exact Manufacturer",
        "MPN-9",
        "digikey");

    [Theory]
    [InlineData("attachment; filename*=UTF-8''Exact%20Part.zip", "https://example.test/download", @"C:\Capture\opaque", "Exact Part.zip")]
    [InlineData("", "https://example.test/files/Exact%20Part.step", @"C:\Capture\opaque", "Exact Part.step")]
    [InlineData("", "https://example.test/download", @"C:\Capture\opaque.zip", "opaque.zip")]
    public void DownloadNamePrefersHttpEvidenceOverOpaqueResultPath(
        string contentDisposition,
        string uri,
        string resultFilePath,
        string expected)
    {
        Assert.Equal(
            expected,
            ProviderDownloadName.Resolve(contentDisposition, uri, resultFilePath));
    }

    [Fact]
    public void StaleReleaseCannotEndTheCurrentGeneration()
    {
        var journal = new ProviderLeaseJournal();
        var first = journal.Begin("lease-a");

        Assert.False(journal.Release(new ProviderLeaseIdentity("lease-a", first.Generation + 1)));
        Assert.Equal(first, journal.RequireActive());
        Assert.True(journal.Release(first));

        var second = journal.Begin("lease-b");
        Assert.True(second.Generation > first.Generation);
        Assert.False(journal.Release(first));
        Assert.Equal(second, journal.RequireActive());
    }

    [Fact]
    public void DownloadEventsRemainBoundToTheirLeaseAndCursor()
    {
        var journal = new ProviderLeaseJournal();
        var first = journal.Begin("lease-a", Context);
        var started = Record(journal, first, Context, "operation-a", "started", "in_progress", 0);
        var terminal = Record(journal, first, Context, "operation-a", "terminal", "completed", 120);
        Assert.True(journal.Release(first));
        var second = journal.Begin("lease-b", Context);
        Record(journal, second, Context, "operation-b", "started", "in_progress", 0);

        Assert.Equal([started, terminal], journal.After(first, 0));
        Assert.Equal([terminal], journal.After(first, started.Sequence));
        Assert.Empty(journal.After(first, terminal.Sequence));
        Assert.Single(journal.After(second, 0));
    }

    [Fact]
    public void EveryEventCarriesTheComponentIdentityOfItsOwnLease()
    {
        var journal = new ProviderLeaseJournal();
        var lease = journal.Begin("lease-a", Context);

        var recorded = Record(journal, lease, Context, "operation-a", "progress", "in_progress", 4);

        Assert.Equal("component-9", recorded.ComponentId);
        Assert.Equal("Exact Manufacturer", recorded.Manufacturer);
        Assert.Equal("MPN-9", recorded.Mpn);
        Assert.Equal("digikey", recorded.ProviderId);
    }

    [Fact]
    public void ALateEventStaysWithItsOwnLeaseAndGenerationAfterAnotherComponentBecomesActive()
    {
        var otherContext = new ProviderLeaseContext(
            @"C:\Capture\Downloads\task-2",
            "component-other",
            "Other Manufacturer",
            "MPN-OTHER",
            "mouser");
        var journal = new ProviderLeaseJournal();
        var first = journal.Begin("lease-a", Context);
        Assert.True(journal.Release(first));
        var second = journal.Begin("lease-a", otherContext);

        // The interrupted download from the first lease reports long after a different component
        // became active. It must not attach to the lease that is live now.
        var late = Record(journal, first, Context, "operation-a", "terminal", "interrupted", 4);

        Assert.Equal([late], journal.After(first, 0));
        Assert.Empty(journal.After(second, 0));
        Assert.Equal("component-9", late.ComponentId);
        Assert.Equal(first.Generation, late.Generation);
    }

    [Theory]
    [InlineData("started")]
    [InlineData("progress")]
    [InlineData("terminal")]
    public void TheAllowedPhaseVocabularyIsExactlyStartedProgressTerminal(string phase)
    {
        var journal = new ProviderLeaseJournal();
        var lease = journal.Begin("lease-a", Context);

        Assert.Equal(
            phase,
            Record(journal, lease, Context, "operation-a", phase, "in_progress", 1).Phase);
    }

    [Theory]
    [InlineData("")]
    [InlineData("Started")]
    [InlineData("cancelled")]
    public void AnUnknownPhaseIsRefusedRatherThanJournalled(string phase)
    {
        var journal = new ProviderLeaseJournal();
        var lease = journal.Begin("lease-a", Context);

        Assert.Throws<WindowHostException>(
            () => Record(journal, lease, Context, "operation-a", phase, "in_progress", 1));
        Assert.Empty(journal.After(lease, 0));
    }

    [Theory]
    [InlineData(@"Relative\Staging")]
    [InlineData(@" C:\Capture")]
    [InlineData("C:\\Capture\u0001")]
    public void AMalformedStagingRootIsRefusedAtLeaseBeginRatherThanAtDownloadTime(
        string stagingRoot)
    {
        var journal = new ProviderLeaseJournal();

        Assert.Throws<WindowHostException>(
            () => journal.Begin(
                "lease-a",
                new ProviderLeaseContext(stagingRoot, string.Empty, string.Empty, string.Empty, string.Empty)));
    }

    [Fact]
    public void AnUnknownStagingRootIsAllowedSoTheDownloadItselfCanRefuse()
    {
        var journal = new ProviderLeaseJournal();

        var lease = journal.Begin("lease-a", ProviderLeaseContext.Empty);

        Assert.Equal(lease, journal.RequireActive());
        Assert.False(
            ProviderDownloadStaging.TryResolveDestination(
                ProviderLeaseContext.Empty.StagingRoot,
                "operation-a",
                "model.zip",
                out _));
    }

    [Theory]
    [InlineData("component\u0001id")]
    [InlineData("aaaaaaaaaa")]
    public void ComponentIdentityIsValidatedAtLeaseBegin(string componentId)
    {
        var journal = new ProviderLeaseJournal();
        var value = componentId.Length == 10
            ? string.Concat(Enumerable.Repeat(componentId, 26))
            : componentId;

        Assert.Throws<WindowHostException>(
            () => journal.Begin(
                "lease-a",
                new ProviderLeaseContext(
                    @"C:\Capture\Downloads\task-1",
                    value,
                    string.Empty,
                    string.Empty,
                    string.Empty)));
    }

    [Fact]
    public void OneThrottledDownloadCannotExhaustTheBoundedJournal()
    {
        var journal = new ProviderLeaseJournal();
        var lease = journal.Begin("lease-a", Context);
        var throttle = new ProviderDownloadProgressThrottle(0);
        var totalBytes = 64L * 1024 * 1024;

        Record(journal, lease, Context, "operation-a", "started", "in_progress", 0);
        // A byte update per 4 KiB buffer across the whole transfer, arriving every millisecond.
        for (var received = 4096L; received <= totalBytes; received += 4096)
        {
            if (throttle.TryAcquire(received / 4096, received, totalBytes))
            {
                Record(journal, lease, Context, "operation-a", "progress", "in_progress", received);
            }
        }
        Record(journal, lease, Context, "operation-a", "progress", "in_progress", totalBytes);
        Record(journal, lease, Context, "operation-a", "terminal", "completed", totalBytes);

        var events = journal.After(lease, 0);
        Assert.True(throttle.Emitted <= ProviderDownloadProgressThrottle.MaximumProgressEvents);
        Assert.True(events.Count < ProviderLeaseJournal.MaximumRetainedEvents);
        Assert.True(events.Count <= 128);
        Assert.Equal("started", events[0].Phase);
        Assert.Equal("progress", events[^2].Phase);
        Assert.Equal("terminal", events[^1].Phase);
        Assert.Equal(totalBytes, events[^2].BytesReceived);
    }

    [Fact]
    public void ManyByteUpdatesProduceFewJournalEntries()
    {
        var throttle = new ProviderDownloadProgressThrottle(0);
        var emitted = 0;

        // Ten thousand buffer callbacks inside one second of a ten-megabyte transfer.
        for (var index = 1; index <= 10_000; index += 1)
        {
            if (throttle.TryAcquire(index / 10, index * 1024L, 10L * 1024 * 1024))
            {
                emitted += 1;
            }
        }

        Assert.Equal(throttle.Emitted, emitted);
        Assert.InRange(emitted, 1, 8);
    }

    [Fact]
    public void ProgressNeedsBothAQuarterSecondAndOnePercentMoreBytes()
    {
        var throttle = new ProviderDownloadProgressThrottle(0);
        const long total = 100_000;

        Assert.False(throttle.TryAcquire(249, 50_000, total));
        Assert.False(
            throttle.TryAcquire(
                ProviderDownloadProgressThrottle.MinimumIntervalMilliseconds,
                999,
                total));
        Assert.True(
            throttle.TryAcquire(
                ProviderDownloadProgressThrottle.MinimumIntervalMilliseconds,
                1_000,
                total));
        Assert.False(throttle.TryAcquire(400, 2_000, total));
        Assert.True(throttle.TryAcquire(600, 2_000, total));
    }

    [Fact]
    public void AnUndeclaredTotalStillReportsGeometricallyRatherThanPerBuffer()
    {
        var throttle = new ProviderDownloadProgressThrottle(0);
        var emitted = 0;

        for (var index = 1; index <= 20_000; index += 1)
        {
            if (throttle.TryAcquire(index, index * 512L, -1))
            {
                emitted += 1;
            }
        }

        Assert.InRange(emitted, 1, ProviderDownloadProgressThrottle.MaximumProgressEvents);
    }

    [Fact]
    public void OneOperationCanNeverPublishMoreThanItsProgressBudget()
    {
        var throttle = new ProviderDownloadProgressThrottle(0);

        for (var index = 1; index <= 100_000; index += 1)
        {
            throttle.TryAcquire(index * 1_000L, index * 1_000_000L, -1);
        }

        Assert.Equal(
            ProviderDownloadProgressThrottle.MaximumProgressEvents,
            throttle.Emitted);
    }

    private static ProviderDownloadEvent Record(
        ProviderLeaseJournal journal,
        ProviderLeaseIdentity lease,
        ProviderLeaseContext context,
        string operationId,
        string phase,
        string state,
        long bytesReceived) =>
        journal.Record(
            lease,
            context,
            operationId,
            phase,
            state,
            "https://provider.example.test/model.zip",
            "model.zip",
            @"C:\Capture\Downloads\task-1\operation-a\model.zip",
            "application/zip",
            string.Empty,
            120,
            bytesReceived);
}
