using System.Windows.Input;

namespace Stockroom.WindowHost.Tests;

/// <summary>
/// The provider page's chrome as behaviour rather than as controls: where a new-window request is
/// allowed to end up, and which keys move through the page's history.
///
/// Note what these deliberately do NOT claim. Every case here is about the WPF host in
/// <c>app/desktop</c>, which runs only when a frozen release owns the native window. The host the
/// owner launches is <c>python -m stockroom.host.run</c>, whose chrome is covered by
/// <c>tests/backend/host/test_window_chrome.py</c>. A strip test that passes here has never said
/// anything about the window that opens there, and that gap is what let a tested strip coexist
/// with a person seeing no strip at all.
/// </summary>
public sealed class ProviderWindowChromeTests
{
    [Theory]
    // A normal provider link becomes a popup while one can be built, and the page itself goes
    // there when one cannot. Either way it stays in this window under this lease.
    [InlineData("https://www.digikey.com/en/models/1", true, true, "Popup")]
    [InlineData("https://www.digikey.com/en/models/1", true, false, "NavigateInPlace")]
    // A script-opened blank document is a real popup and nothing else: navigating the page a
    // person is working on to about:blank loses their click rather than honouring it.
    [InlineData("about:blank", true, true, "Popup")]
    [InlineData("about:blank", true, false, "Refuse")]
    // Anything the operating system would route to another program is refused outright.
    [InlineData("http://www.digikey.com/x", true, true, "Refuse")]
    [InlineData("ms-windows-store://pdp/", true, true, "Refuse")]
    [InlineData("file:///C:/Windows/System32/calc.exe", true, true, "Refuse")]
    [InlineData("javascript:alert(1)", true, true, "Refuse")]
    [InlineData("https://person:secret@example.test/", true, true, "Refuse")]
    [InlineData("", true, true, "Refuse")]
    [InlineData(null, true, true, "Refuse")]
    // With no lease there is no provider work for a new window to belong to.
    [InlineData("https://www.digikey.com/en/models/1", false, true, "Refuse")]
    [InlineData("https://www.digikey.com/en/models/1", false, false, "Refuse")]
    public void ANewWindowRequestStaysInsideStockroomOrIsRefused(
        string? uri,
        bool hasActiveLease,
        bool canCreatePopup,
        string expected)
    {
        Assert.Equal(
            expected,
            ProviderNewWindowPolicy
                .Resolve(uri, hasActiveLease, canCreatePopup)
                .ToString());
    }

    [Fact]
    public void NoNewWindowOutcomeEverLeavesStockroom()
    {
        // Exhaustive over the enum: there is no "open in the person's browser" outcome to reach,
        // whatever a provider page requests.
        var outcomes = Enum.GetValues<ProviderNewWindowAction>();

        Assert.Equal(3, outcomes.Length);
        Assert.Contains(ProviderNewWindowAction.Refuse, outcomes);
        Assert.Contains(ProviderNewWindowAction.Popup, outcomes);
        Assert.Contains(ProviderNewWindowAction.NavigateInPlace, outcomes);
    }

    [Theory]
    [InlineData("https://www.digikey.com/x", true)]
    [InlineData("https://componentsearchengine.com", true)]
    [InlineData("about:blank", false)]
    [InlineData("http://www.digikey.com/x", false)]
    [InlineData("https://person:secret@example.test/", false)]
    [InlineData("https:///nohost", false)]
    [InlineData(null, false)]
    public void OnlyARealHttpsPageIsSomewhereTheOpenViewCanSimplyGo(string? uri, bool expected)
    {
        Assert.Equal(expected, ProviderNavigationPolicy.IsNavigableInPlace(uri));
    }

    [Theory]
    // WPF reports a modified arrow as Key.System and carries the arrow in SystemKey.
    [InlineData(Key.System, Key.Left, ModifierKeys.Alt, "Back")]
    [InlineData(Key.System, Key.Right, ModifierKeys.Alt, "Forward")]
    [InlineData(Key.Left, Key.None, ModifierKeys.Alt, "Back")]
    [InlineData(Key.Right, Key.None, ModifierKeys.Alt, "Forward")]
    // Unmodified arrows belong to the page, and other combinations mean other things on Windows.
    [InlineData(Key.Left, Key.None, ModifierKeys.None, "None")]
    [InlineData(Key.System, Key.Left, ModifierKeys.Control | ModifierKeys.Alt, "None")]
    [InlineData(Key.System, Key.Left, ModifierKeys.Shift | ModifierKeys.Alt, "None")]
    [InlineData(Key.System, Key.Up, ModifierKeys.Alt, "None")]
    [InlineData(Key.F4, Key.None, ModifierKeys.Alt, "None")]
    public void AltLeftAndAltRightAreTheOnlyHistoryKeys(
        Key key,
        Key systemKey,
        ModifierKeys modifiers,
        string expected)
    {
        Assert.Equal(
            expected,
            ProviderHistoryShortcut.Resolve(key, systemKey, modifiers).ToString());
    }

    [Fact]
    public void TheHostConsumesEveryNewWindowRequestBeforeItDecidesAnything()
    {
        var handler = ProviderNewWindowHandlerSource();

        // Handled comes first, unconditionally. Every later branch is therefore a choice between
        // outcomes inside this window; none of them can fall through to the Windows shell.
        var handledOffset = handler.IndexOf(
            "eventArguments.Handled = true;",
            StringComparison.Ordinal);
        var decisionOffset = handler.IndexOf(
            "ProviderNewWindowPolicy.Resolve(",
            StringComparison.Ordinal);
        Assert.True(handledOffset >= 0);
        Assert.True(decisionOffset > handledOffset);
        Assert.DoesNotContain("Process.Start", handler, StringComparison.Ordinal);
        Assert.DoesNotContain("UseShellExecute", handler, StringComparison.Ordinal);
    }

    [Fact]
    public void AFailedPopupFallsBackToTheOpenPageRatherThanSwallowingTheClick()
    {
        var handler = ProviderNewWindowHandlerSource();
        var catchOffset = handler.IndexOf("catch", StringComparison.Ordinal);

        Assert.True(catchOffset > 0);
        Assert.Contains(
            "NavigateActiveProviderInPlace(eventArguments.Uri);",
            handler[catchOffset..],
            StringComparison.Ordinal);
    }

    [Fact]
    public void HistoryKeysArePreviewedOnTheWindowSoThePageCannotEatThem()
    {
        var source = HostSource();

        Assert.Contains(
            "_window.PreviewKeyDown += OnWindowPreviewKeyDown;",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "ProviderHistoryShortcut.Resolve(",
            source,
            StringComparison.Ordinal);
    }

    [Fact]
    public void FocusedProviderEscapeRequestsAnIdentityBoundAcknowledgedClose()
    {
        var source = HostSource();

        Assert.Contains("eventArguments.Key == Key.Escape", source, StringComparison.Ordinal);
        Assert.Contains("PostProviderCloseRequested", source, StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.provider-close-requested",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom:provider-close-requested",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "providerCommand(request)",
            source,
            StringComparison.Ordinal);
    }

    [Fact]
    public void TheLegacyStripControllerIsMountedButItsWindowChromeIsCollapsed()
    {
        var source = HostSource();
        var constructorStart = source.IndexOf(
            "internal WebViewWindowHost(",
            StringComparison.Ordinal);
        var constructorEnd = source.IndexOf(
            "internal IntPtr WindowHandle =>",
            constructorStart,
            StringComparison.Ordinal);
        var constructor = source[constructorStart..constructorEnd];

        // The controller remains mounted for rolling host compatibility, while the visible
        // controls have moved into the component-scoped Manage Models workspace.
        Assert.Contains("_tabStrip = new WindowTabStrip();", constructor, StringComparison.Ordinal);
        Assert.Contains(
            "_root.Children.Add(_tabStrip.Root);",
            constructor,
            StringComparison.Ordinal);
        Assert.Contains("Grid.SetRow(_tabStrip.Root, 0);", constructor, StringComparison.Ordinal);
        Assert.Contains(
            "_tabStrip.Root.Visibility = Visibility.Collapsed;",
            constructor,
            StringComparison.Ordinal);
    }

    [Fact]
    public void TheDownloadPipelineIsUnchangedByTheNewWindowFallback()
    {
        var source = HostSource().Replace("\r\n", "\n", StringComparison.Ordinal);

        // The in-place fallback navigates and nothing else: it does not touch the staging
        // resolver, the journal, or the one assignment that decides where bytes land.
        var fallbackStart = source.IndexOf(
            "private void NavigateActiveProviderInPlace(",
            StringComparison.Ordinal);
        var fallbackEnd = source.IndexOf(
            "private void OnProviderPopupCloseRequested(",
            fallbackStart,
            StringComparison.Ordinal);
        Assert.True(fallbackStart > 0);
        Assert.True(fallbackEnd > fallbackStart);
        var fallback = source[fallbackStart..fallbackEnd];
        Assert.DoesNotContain("ResultFilePath", fallback, StringComparison.Ordinal);
        Assert.DoesNotContain("_providerLeases", fallback, StringComparison.Ordinal);
        Assert.DoesNotContain("RecordProviderDownload", fallback, StringComparison.Ordinal);

        // And the pipeline itself is still wired exactly once, from DownloadStarting through
        // staging to the journal.
        Assert.Equal(
            1,
            CountOccurrences(source, "core.DownloadStarting += OnProviderDownloadStarting;"));
        Assert.Equal(1, CountOccurrences(source, "eventArguments.ResultFilePath = destination;"));
        Assert.Contains(
            "ProviderDownloadStaging.TryResolveDestination(",
            source,
            StringComparison.Ordinal);
    }

    private static string ProviderNewWindowHandlerSource()
    {
        var source = HostSource().Replace("\r\n", "\n", StringComparison.Ordinal);
        var start = source.IndexOf(
            "private async void OnProviderNewWindowRequested(",
            StringComparison.Ordinal);
        var end = source.IndexOf(
            "private void NavigateActiveProviderInPlace(",
            start,
            StringComparison.Ordinal);
        Assert.True(start >= 0);
        Assert.True(end > start);
        return source[start..end];
    }

    private static string HostSource() =>
        File.ReadAllText(
            Path.Combine(FindProjectDirectory(), "WebViewWindowHost.cs"));

    private static string FindProjectDirectory()
    {
        var directory = new DirectoryInfo(AppContext.BaseDirectory);
        while (directory is not null)
        {
            var candidate = Path.Combine(
                directory.FullName,
                "app",
                "desktop",
                "Stockroom.WindowHost",
                "Stockroom.WindowHost.csproj");
            if (File.Exists(candidate))
            {
                return Path.GetDirectoryName(candidate)!;
            }
            directory = directory.Parent;
        }
        throw new InvalidOperationException(
            "Stockroom.WindowHost project directory was not found");
    }

    private static int CountOccurrences(string source, string value)
    {
        var count = 0;
        var offset = 0;
        while ((offset = source.IndexOf(value, offset, StringComparison.Ordinal)) >= 0)
        {
            count += 1;
            offset += value.Length;
        }
        return count;
    }
}
