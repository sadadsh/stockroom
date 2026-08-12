namespace Stockroom.WindowHost.Tests;

public sealed class PackagingAndSecurityContractTests
{
    [Fact]
    public void StartupFailureStagesAreStableNonsecretExitCodes()
    {
        Assert.Equal(21, (int)WindowHostFailureStage.Environment);
        Assert.Equal(22, (int)WindowHostFailureStage.WebViewControl);
        Assert.Equal(23, (int)WindowHostFailureStage.Navigation);
        Assert.Equal(24, (int)WindowHostFailureStage.RendererProbe);
        Assert.Equal(25, (int)WindowHostFailureStage.Runtime);
    }

    [Theory]
    [InlineData(true, false, false, true)]
    [InlineData(false, false, false, false)]
    [InlineData(true, true, false, false)]
    [InlineData(true, false, true, false)]
    public void OnlyAReadyVisibleWindowCanRequestUserClose(
        bool initialized,
        bool hidden,
        bool shuttingDown,
        bool expected)
    {
        Assert.Equal(
            expected,
            WindowClosePolicy.ShouldRequestClose(
                initialized,
                hidden,
                shuttingDown));
    }

    [Fact]
    public void DedicatedReleaseMemberHasOneCanonicalExecutableContract()
    {
        Assert.Equal(
            "window-host",
            WindowHostPackagingContract.ManifestMemberKind);
        Assert.Equal(
            "WindowHost/Stockroom.WindowHost.exe",
            WindowHostPackagingContract.RelativeExecutablePath);
        Assert.Equal(
            "Stockroom.WindowHost.exe",
            WindowHostPackagingContract.ExecutableName);
    }

    [Fact]
    public void ProductionSourceKeepsRendererSecretsOutAndOpensNoRemoteDebuggingPort()
    {
        var projectDirectory = FindProjectDirectory();
        var sources = Directory
            .EnumerateFiles(
                projectDirectory,
                "*.cs",
                SearchOption.AllDirectories)
            .Where(
                static path =>
                    !path.Contains(
                        $"{Path.DirectorySeparatorChar}obj{Path.DirectorySeparatorChar}",
                        StringComparison.OrdinalIgnoreCase))
            .Select(File.ReadAllText)
            .ToArray();
        var allSource = string.Join("\n", sources);

        // Was: EXACTLY ONE remote-debugging port, scoped to the provider WebView. That bounded a
        // hole rather than closing it - any local process that could reach the loopback port could
        // drive the person's signed-in provider session. Native download staging and the lease
        // journal made the port unnecessary, so the contract is now ZERO: no source file may open
        // a debugging port, on any WebView, for any reason.
        Assert.DoesNotContain(
            "--remote-debugging-port=",
            allSource,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "AdditionalBrowserArguments",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "ProviderProfileDirectory",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "_webView.Visibility = Visibility.Collapsed;",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "_webView.Visibility = Visibility.Visible;",
            allSource,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "window.__STOCKROOM_TOKEN__",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "WebResourceRequested",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "\"Authorization\"",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "AreDevToolsEnabled = false",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "IsWebMessageEnabled = true",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "eventArguments.Source,\n                _bootstrap.BaseUri",
            allSource.Replace("\r\n", "\n", StringComparison.Ordinal),
            StringComparison.Ordinal);
        Assert.Equal(
            4,
            allSource.Split(
                "webview.postMessage({",
                StringSplitOptions.None).Length - 1);
        Assert.Equal(
            1,
            allSource.Split(
                "PostWebMessageAsJson",
                StringSplitOptions.None).Length - 1);
        Assert.Contains(
            "stockroom.host.folder-request",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.folder-result",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.file-request",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.file-result",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.provider-viewport",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "stockroom.host.provider-command",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "value.schema !== request.expectedSchema",
            allSource,
            StringComparison.Ordinal);
        Assert.DoesNotContain(
            "})());",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "})();",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "DownloadStarting",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "BasicAuthenticationRequested",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "BrowserProcessExited",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "ProcessFailed",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "Opacity = 0",
            allSource,
            StringComparison.Ordinal);
        Assert.Contains(
            "_window.Hide();",
            allSource,
            StringComparison.Ordinal);
    }

    [Fact]
    public void ProjectPinsWebView2AndPublishesTheCanonicalExeName()
    {
        var projectDirectory = FindProjectDirectory();
        var project = File.ReadAllText(
            Path.Combine(
                projectDirectory,
                "Stockroom.WindowHost.csproj"));

        Assert.Contains(
            "Microsoft.Web.WebView2\" Version=\"1.0.4078.44",
            project,
            StringComparison.Ordinal);
        Assert.Contains(
            "<OutputType>WinExe</OutputType>",
            project,
            StringComparison.Ordinal);
        Assert.Contains(
            "<AssemblyName>Stockroom.WindowHost</AssemblyName>",
            project,
            StringComparison.Ordinal);
    }

    private static string FindProjectDirectory()
    {
        var candidates = new[]
        {
            Directory.GetCurrentDirectory(),
            AppContext.BaseDirectory,
        };
        foreach (var candidate in candidates)
        {
            var current = new DirectoryInfo(candidate);
            while (current is not null)
            {
                var projectDirectory = Path.Combine(
                    current.FullName,
                    "app",
                    "desktop",
                    "Stockroom.WindowHost");
                if (File.Exists(
                        Path.Combine(
                            projectDirectory,
                            "Stockroom.WindowHost.csproj")))
                {
                    return projectDirectory;
                }

                current = current.Parent;
            }
        }

        throw new InvalidOperationException(
            "Stockroom.WindowHost project directory was not found");
    }
}
