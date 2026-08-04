namespace Stockroom.WindowHost.Tests;

public sealed class ProviderDownloadStagingTests
{
    private const string StagingRoot = @"C:\Capture\Downloads\task-1";
    private const string OperationId = "6f1a5f5e-1a2b-4c3d-8e4f-9a0b1c2d3e4f";

    [Theory]
    [InlineData(@"..\..\..\Windows\System32\evil.dll", "evil.dll")]
    [InlineData("../../etc/passwd", "passwd")]
    [InlineData(@"C:\Users\Person\Downloads\Part.step", "Part.step")]
    [InlineData("..", ProviderDownloadStaging.FallbackFileName)]
    [InlineData(".", ProviderDownloadStaging.FallbackFileName)]
    [InlineData("", ProviderDownloadStaging.FallbackFileName)]
    [InlineData("    ", ProviderDownloadStaging.FallbackFileName)]
    [InlineData("Part<>|?*.step", "Part_____.step")]
    [InlineData("Part\"name.step", "Part_name.step")]
    [InlineData("C:Part.step", "Part.step")]
    [InlineData("Part.step:$DATA", "$DATA")]
    [InlineData("Part\u0000\u0007\u001f.step", "Part___.step")]
    [InlineData("Part\r\nname.step", "Part__name.step")]
    [InlineData("Part.step.  ", "Part.step")]
    [InlineData("Part.step...", "Part.step")]
    [InlineData("CON", "_CON")]
    [InlineData("con.step", "_con.step")]
    [InlineData("COM9.zip", "_COM9.zip")]
    [InlineData("lpt1.STEP", "_lpt1.STEP")]
    [InlineData("nul", "_nul")]
    [InlineData("COM0.zip", "COM0.zip")]
    [InlineData("CONSOLE.zip", "CONSOLE.zip")]
    [InlineData("Exact Part.step", "Exact Part.step")]
    public void HostileSuggestedNamesReduceToOnePlainPhysicalFileName(
        string suggested,
        string expected)
    {
        Assert.Equal(expected, ProviderDownloadStaging.SanitizeFileName(suggested));
    }

    [Fact]
    public void AnOverLongNameIsCappedWhileKeepingItsExtension()
    {
        var sanitized = ProviderDownloadStaging.SanitizeFileName(
            new string('a', 4096) + ".step");

        Assert.Equal(ProviderDownloadStaging.MaximumFileNameLength, sanitized.Length);
        Assert.EndsWith(".step", sanitized, StringComparison.Ordinal);
        Assert.DoesNotContain('.', sanitized[..^5]);
    }

    [Fact]
    public void AnOverLongNameWithNoUsableStemFallsBackWhileKeepingItsExtension()
    {
        var sanitized = ProviderDownloadStaging.SanitizeFileName(
            new string('.', 200) + new string('z', 200));

        Assert.StartsWith(
            ProviderDownloadStaging.FallbackFileName,
            sanitized,
            StringComparison.Ordinal);
        Assert.True(sanitized.Length <= ProviderDownloadStaging.MaximumFileNameLength);
    }

    [Fact]
    public void ANullSuggestionStillNamesAFile()
    {
        Assert.Equal(
            ProviderDownloadStaging.FallbackFileName,
            ProviderDownloadStaging.SanitizeFileName(null));
    }

    [Fact]
    public void TheDestinationIsAlwaysADirectChildOfOneOperationDirectory()
    {
        Assert.True(
            ProviderDownloadStaging.TryResolveDestination(
                StagingRoot,
                OperationId,
                "Exact Part.step",
                out var destination));

        Assert.Equal(
            Path.Combine(StagingRoot, OperationId, "Exact Part.step"),
            destination);
    }

    [Theory]
    [InlineData(@"..\..\..\Windows\System32\evil.dll")]
    [InlineData("../../../etc/passwd")]
    [InlineData(@"C:\Users\Person\Downloads\Part.step")]
    [InlineData("..")]
    public void ANameThatWouldEscapeTheStagingRootStillLandsInsideIt(string suggested)
    {
        Assert.True(
            ProviderDownloadStaging.TryResolveDestination(
                StagingRoot,
                OperationId,
                suggested,
                out var destination));

        Assert.Equal(
            Path.Combine(StagingRoot, OperationId),
            Path.GetDirectoryName(destination));
        Assert.StartsWith(
            StagingRoot + Path.DirectorySeparatorChar,
            destination,
            StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("..")]
    [InlineData(@"..\..")]
    [InlineData(@"nested\operation")]
    [InlineData(".")]
    [InlineData(@"C:\Elsewhere")]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData("operation\u0001id")]
    public void ContainmentRefusesAnOperationDirectoryThatIsNotADirectChild(string operationId)
    {
        Assert.False(
            ProviderDownloadStaging.TryResolveDestination(
                StagingRoot,
                operationId,
                "Part.step",
                out var destination));
        Assert.Equal(string.Empty, destination);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("")]
    [InlineData("   ")]
    [InlineData(@"Relative\Staging")]
    [InlineData(@"\NoDrive\Staging")]
    [InlineData("C:\u0001\\Staging")]
    public void NoUsableStagingRootMeansNoDestination(string? stagingRoot)
    {
        Assert.False(
            ProviderDownloadStaging.TryResolveDestination(
                stagingRoot,
                OperationId,
                "Part.step",
                out var destination));
        Assert.Equal(string.Empty, destination);
    }

    [Theory]
    [InlineData("attachment; filename=\"CON.step\"", "CON.step", "_CON.step")]
    [InlineData("attachment; filename=\"Part<>|.step\"", "Part<>|.step", "Part___.step")]
    [InlineData("attachment; filename=\"NUL.zip\"", "NUL.zip", "_NUL.zip")]
    public void TheSuggestedNameStaysVerbatimWhileOnlyTheDiskNameIsSanitized(
        string contentDisposition,
        string expectedMetadataName,
        string expectedDiskName)
    {
        var suggested = ProviderDownloadName.Resolve(
            contentDisposition,
            "https://provider.example.test/download",
            @"C:\Capture\opaque");
        var journal = new ProviderLeaseJournal();
        var context = new ProviderLeaseContext(
            StagingRoot,
            "component-9",
            "Exact Manufacturer",
            "MPN-9",
            "digikey");
        var lease = journal.Begin("lease-a", context);
        Assert.True(
            ProviderDownloadStaging.TryResolveDestination(
                context.StagingRoot,
                OperationId,
                suggested,
                out var destination));

        var recorded = journal.Record(
            lease,
            context,
            OperationId,
            "started",
            "in_progress",
            "https://provider.example.test/download",
            suggested,
            destination,
            "model/step",
            string.Empty,
            -1,
            0);

        Assert.Equal(expectedMetadataName, recorded.SuggestedFileName);
        Assert.Equal(expectedDiskName, Path.GetFileName(recorded.ResultFilePath));
        Assert.NotEqual(recorded.SuggestedFileName, Path.GetFileName(recorded.ResultFilePath));
    }

    [Fact]
    public void AReservedDeviceNameIsWrittenAsAnOrdinaryFileInsideTheStagingRoot()
    {
        Assert.True(
            ProviderDownloadStaging.TryResolveDestination(
                StagingRoot,
                OperationId,
                "CON.step",
                out var destination));

        Assert.Equal(
            Path.Combine(StagingRoot, OperationId, "_CON.step"),
            destination);
    }
}
