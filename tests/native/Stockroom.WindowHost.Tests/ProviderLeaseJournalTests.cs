namespace Stockroom.WindowHost.Tests;

public sealed class ProviderLeaseJournalTests
{
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
        var first = journal.Begin("lease-a");
        var started = journal.Record(
            first,
            "operation-a",
            "started",
            "in_progress",
            "https://provider.example.test/model.zip",
            "model.zip",
            @"C:\Capture\model.zip",
            "application/zip",
            string.Empty,
            120,
            0);
        var terminal = journal.Record(
            first,
            "operation-a",
            "terminal",
            "completed",
            "https://provider.example.test/model.zip",
            "model.zip",
            @"C:\Capture\model.zip",
            "application/zip",
            string.Empty,
            120,
            120);
        Assert.True(journal.Release(first));
        var second = journal.Begin("lease-b");
        journal.Record(
            second,
            "operation-b",
            "started",
            "in_progress",
            "https://provider.example.test/other.zip",
            "other.zip",
            @"C:\Capture\other.zip",
            "application/zip",
            string.Empty,
            -1,
            0);

        Assert.Equal([started, terminal], journal.After(first, 0));
        Assert.Equal([terminal], journal.After(first, started.Sequence));
        Assert.Empty(journal.After(first, terminal.Sequence));
        Assert.Single(journal.After(second, 0));
    }
}
