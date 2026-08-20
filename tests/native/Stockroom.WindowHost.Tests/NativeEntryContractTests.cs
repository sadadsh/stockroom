namespace Stockroom.WindowHost.Tests;

public sealed class NativeEntryContractTests
{
    [Fact]
    public void EmptyArgumentsSelectTheStandaloneNativeEntry()
    {
        var source = File.ReadAllText(
            Path.Combine(
                AppContext.BaseDirectory,
                "..", "..", "..", "..", "..", "..",
                "app", "desktop", "Stockroom.WindowHost", "Program.cs"));

        Assert.Contains("if (arguments.Length == 0)", source, StringComparison.Ordinal);
        Assert.Contains("return RunStandalone();", source, StringComparison.Ordinal);
        Assert.Contains("PackagedWorkerRuntime.StartAsync", source, StringComparison.Ordinal);
        Assert.DoesNotContain("stockroom.launcher.launch", source, StringComparison.Ordinal);
    }

    [Fact]
    public void OrphanCleanupOnlyRemovesOldBrandedMeiDirectories()
    {
        var root = Path.Combine(Path.GetTempPath(), $"Stockroom Native Host Test {Guid.NewGuid():N}");
        Directory.CreateDirectory(root);
        try
        {
            var oldBranded = Directory.CreateDirectory(Path.Combine(root, "_MEIold"));
            File.WriteAllText(Path.Combine(oldBranded.FullName, "stockroom-build-identity.json"), "{}");
            oldBranded.LastWriteTimeUtc = DateTime.UtcNow.AddHours(-2);
            var oldForeign = Directory.CreateDirectory(Path.Combine(root, "_MEIforeign"));
            oldForeign.LastWriteTimeUtc = DateTime.UtcNow.AddHours(-2);
            var recentBranded = Directory.CreateDirectory(Path.Combine(root, "_MEIrecent"));
            File.WriteAllText(Path.Combine(recentBranded.FullName, "stockroom-build-identity.json"), "{}");

            var removed = PyInstallerTemporaryCleanup.RemoveOrphans(
                root,
                DateTimeOffset.UtcNow);

            Assert.Equal(1, removed);
            Assert.False(Directory.Exists(oldBranded.FullName));
            Assert.True(Directory.Exists(oldForeign.FullName));
            Assert.True(Directory.Exists(recentBranded.FullName));
        }
        finally
        {
            Directory.Delete(root, recursive: true);
        }
    }

    [Fact]
    public void GuidedSetupFolderPurposesCrossThePackagedHostBridge()
    {
        var source = File.ReadAllText(
            Path.Combine(
                AppContext.BaseDirectory,
                "..", "..", "..", "..", "..", "..",
                "app", "desktop", "Stockroom.WindowHost", "WebViewWindowHost.cs"));

        Assert.Contains("\"catalog\"", source, StringComparison.Ordinal);
        Assert.Contains("\"kicad-config\"", source, StringComparison.Ordinal);
        Assert.Contains("Choose A Catalog Repository Folder", source, StringComparison.Ordinal);
        Assert.Contains("Choose The KiCad Configuration Folder", source, StringComparison.Ordinal);
        Assert.Contains("STOCKROOM_LIBRARY_ROOT_BOUNDARY", source, StringComparison.Ordinal);
        Assert.Contains("dialog.InitialDirectory = boundary", source, StringComparison.Ordinal);
        Assert.Contains("Path.GetRelativePath(boundary, selected)", source, StringComparison.Ordinal);
    }

    [Fact]
    public void NativeHostCarriesOneCoherentProductVersion()
    {
        Assert.Equal("1.0.0.0", LauncherDiagnostics.ProductVersion());
    }
}
