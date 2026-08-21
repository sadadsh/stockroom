namespace Stockroom.WindowHost.Tests;

public sealed class ProviderBrowserContractTests
{
    [Theory]
    [InlineData("https://www.digikey.com/en/products", true)]
    [InlineData("https://challenges.cloudflare.com/turnstile/v0/", true)]
    [InlineData("https://accounts.example.test/oauth/authorize", true)]
    [InlineData("about:blank#stockroom-provider-proof", true)]
    [InlineData("http://www.digikey.com/en/products", false)]
    [InlineData("https://person:secret@example.test/", false)]
    [InlineData("file:///C:/Windows/System32/calc.exe", false)]
    [InlineData("javascript:alert(1)", false)]
    public void TopLevelProviderNavigationAllowsHttpsIdentityFlowsButRejectsUnsafeSchemes(
        string value,
        bool expected)
    {
        Assert.Equal(
            expected,
            ProviderNavigationPolicy.IsAllowedTopLevel(value));
    }

    [Fact]
    public void ProviderBrowserExposesNoAutomationEndpointToProveOwnershipOf()
    {
        // The previous contract proved that a loopback CDP endpoint belonged to THIS WebView,
        // which was only ever a way to make an unavoidable hole less dangerous. The hole is gone:
        // the provider browser opens no debugging port, so there is no endpoint to attach to, no
        // ownership to prove, and no proof helper to keep correct. Absence is the stronger claim,
        // and it is asserted over the whole production source rather than over one call site.
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs"));

        Assert.DoesNotContain(
            "ProviderCdpProof",
            source,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "VerifyProviderCdpEndpointAsync",
            source,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "ReserveLoopbackPort",
            source,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "AdditionalBrowserArguments",
            source,
            StringComparison.Ordinal);
        // The persistent provider profile and its single-owner guarantee are unchanged.
        Assert.Contains(
            "ExclusiveUserDataFolderAccess = true",
            source,
            StringComparison.Ordinal);
    }

    [Fact]
    public void ProductionSourceKeepsProviderLazyAndDoesNotFilterSubframes()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs"));
        var initializeStart = source.IndexOf(
            "internal async Task InitializeAsync()",
            StringComparison.Ordinal);
        var prepareHiddenStart = source.IndexOf(
            "internal void PrepareHidden(",
            initializeStart,
            StringComparison.Ordinal);
        var initializeBody = source[initializeStart..prepareHiddenStart];

        Assert.DoesNotContain(
            "EnsureProviderBrowserReadyAsync",
            initializeBody,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "FrameNavigationStarting += OnProviderNavigationStarting",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "eventArguments.NewWindow = popup.CoreWebView2;",
            source,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "core.Navigate(eventArguments.Uri)",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "core.WebMessageReceived += OnWebMessageReceived;",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "OriginPolicy.IsAllowedNavigation(\n                eventArguments.Source",
            source.Replace("\r\n", "\n", StringComparison.Ordinal),
            StringComparison.Ordinal);
        Assert.Contains(
            "new OpenFolderDialog",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "ResetProviderBrowser();\n        _webView.Dispose();",
            source.Replace("\r\n", "\n", StringComparison.Ordinal),
            StringComparison.Ordinal);
        Assert.Equal(
            1,
            CountOccurrences(
                source,
                "core.ProcessFailed += OnProviderProcessFailed;"));
    }

    [Fact]
    public void LazyProviderControlIsLoadedBeforeWebView2Initialization()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs")).Replace("\r\n", "\n", StringComparison.Ordinal);
        var start = source.IndexOf(
            "private async Task InitializeProviderBrowserAttemptAsync()",
            StringComparison.Ordinal);
        var end = source.IndexOf(
            "private void SyncProviderTab()",
            start,
            StringComparison.Ordinal);
        var method = source[start..end];

        var load = method.IndexOf(
            "_providerSurface.Visibility = Visibility.Hidden;",
            StringComparison.Ordinal);
        var initialize = method.IndexOf(
            "await providerWebView.EnsureCoreWebView2Async(environment)",
            StringComparison.Ordinal);
        var restore = method.IndexOf(
            "_providerSurface.Visibility = priorVisibility;",
            StringComparison.Ordinal);
        Assert.True(load >= 0 && initialize > load && restore > initialize);
    }

    [Fact]
    public void ProviderTabsNeverOverlapTwoWebViewSurfaces()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs"));

        Assert.Contains(
            "private readonly WebView2 _webView;",
            source,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "WebView2CompositionControl",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "var providerWebView = new WebView2",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "_webView.Visibility = Visibility.Collapsed;\n        _providerSurface.Visibility = Visibility.Visible;\n        _tabStrip.Root.Visibility = Visibility.Visible;",
            source.Replace("\r\n", "\n", StringComparison.Ordinal),
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "_webView.Visibility = Visibility.Visible;\n                _providerSurface.Visibility = Visibility.Visible;",
            source.Replace("\r\n", "\n", StringComparison.Ordinal),
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "_tabStrip.Root.IsHitTestVisible = false;",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "_tabStrip.StockroomTab.Checked += (_, _) => HideProviderBrowser();",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "_tabStrip.ProviderTab.Checked += (_, _) => ShowActiveProviderBrowser();",
            source,
            StringComparison.Ordinal);
    }

    [Fact]
    public void FirstValidRendererViewportRestoresAProviderHiddenByEarlyShow()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs")).Replace("\r\n", "\n", StringComparison.Ordinal);

        Assert.Contains(
            "else\n                {\n                    // A provider-show can arrive before React has committed measurable bounds.",
            source,
            StringComparison.Ordinal);
        Assert.Contains("ShowActiveProviderBrowser();", source, StringComparison.Ordinal);
    }

    [Fact]
    public void ProviderFanOutAllowsOnlyTaskBoundMultipleDownloads()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs")).Replace("\r\n", "\n", StringComparison.Ordinal);
        var handlerStart = source.IndexOf(
            "private void OnProviderPermissionRequested(",
            StringComparison.Ordinal);
        var handlerEnd = source.IndexOf(
            "private void OnProviderProcessFailed(",
            handlerStart,
            StringComparison.Ordinal);
        var handler = source[handlerStart..handlerEnd];

        Assert.Contains(
            "eventArguments.PermissionKind\n                == CoreWebView2PermissionKind.MultipleAutomaticDownloads",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "_providerLeases.TryGetActive(out _)",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "eventArguments.State = CoreWebView2PermissionState.Allow;",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "eventArguments.SavesInProfile = false;",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "eventArguments.State = CoreWebView2PermissionState.Deny;",
            handler,
            StringComparison.Ordinal);
    }

    [Fact]
    public void ProductionSourceStagesEveryProviderDownloadAndNeverFallsBackToDownloads()
    {
        var source = File.ReadAllText(
            Path.Combine(
                FindProjectDirectory(),
                "WebViewWindowHost.cs")).Replace("\r\n", "\n", StringComparison.Ordinal);
        var handlerStart = source.IndexOf(
            "private void OnProviderDownloadStarting(",
            StringComparison.Ordinal);
        var handlerEnd = source.IndexOf(
            "private static void OnProviderDefaultDownloadDialogOpenChanged(",
            handlerStart,
            StringComparison.Ordinal);
        var handler = source[handlerStart..handlerEnd];

        // The destination is decided by the staging resolver alone; there is no other assignment
        // to ResultFilePath and no path that lets WebView2 keep its own default location.
        Assert.Equal(1, CountOccurrences(source, "eventArguments.ResultFilePath ="));
        Assert.Contains(
            "ProviderDownloadStaging.TryResolveDestination(",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "Directory.CreateDirectory(Path.GetDirectoryName(destination)!);\n            eventArguments.ResultFilePath = destination;",
            handler,
            StringComparison.Ordinal);
        Assert.Equal(3, CountOccurrences(handler, "eventArguments.Cancel = true;"));
        Assert.Contains(
            "operation.BytesReceivedChanged += bytesReceivedChanged;",
            handler,
            StringComparison.Ordinal);
        Assert.Contains(
            "\"progress\",\n                operation,\n                suggestedFileName);\n            RecordProviderDownload(\n                lease,\n                context,\n                operationId,\n                \"terminal\",",
            handler,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "SpecialFolder",
            source,
            StringComparison.Ordinal);
    }

    [Fact]
    public void BoundedCancellationRecordsTerminalInterruptionBeforeNativeCancel()
    {
        var source = File.ReadAllText(
            Path.Combine(FindProjectDirectory(), "WebViewWindowHost.cs"));
        var methodStart = source.IndexOf(
            "private int CancelProviderDownloadsCore",
            StringComparison.Ordinal);
        var methodEnd = source.IndexOf(
            "internal IReadOnlyList<ProviderDownloadEvent>",
            methodStart,
            StringComparison.Ordinal);
        var method = source[methodStart..methodEnd];

        var terminal = method.IndexOf("\"terminal\"", StringComparison.Ordinal);
        var reason = method.IndexOf("\"CancelledByStockroom\"", StringComparison.Ordinal);
        var cancel = method.IndexOf("operation.Cancel()", StringComparison.Ordinal);
        Assert.True(terminal >= 0 && reason > terminal && cancel > reason);
    }

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
