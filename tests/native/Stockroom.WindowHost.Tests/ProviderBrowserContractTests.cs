using System.Text;

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
    public void CdpProofRequiresTheExpectedLoopbackPortAndOwnedPageMarker()
    {
        const int port = 43127;
        const string marker =
            "about:blank#stockroom-provider-2ed594a5e46d4fc0aecb17ca94aab32f";
        var version = Encoding.UTF8.GetBytes(
            $$"""
              {
                "Browser": "Edg/140.0.0.0",
                "webSocketDebuggerUrl": "ws://localhost:{{port}}/devtools/browser/proof"
              }
              """);
        var targets = Encoding.UTF8.GetBytes(
            $$"""
              [
                {
                  "type": "page",
                  "url": "{{marker}}",
                  "webSocketDebuggerUrl": "ws://127.0.0.1:{{port}}/devtools/page/proof"
                }
              ]
              """);

        ProviderCdpProof.RequireVersion(version, port);
        ProviderCdpProof.RequireOwnedTarget(targets, marker);
    }

    [Fact]
    public void CdpProofRejectsAValidChromiumEndpointOnTheWrongPort()
    {
        var version = Encoding.UTF8.GetBytes(
            """
              {
                "Browser": "Edg/140.0.0.0",
                "webSocketDebuggerUrl": "ws://127.0.0.1:43128/devtools/browser/foreign"
              }
              """);

        Assert.Throws<WindowHostException>(
            () => ProviderCdpProof.RequireVersion(version, 43127));
    }

    [Fact]
    public void CdpProofRejectsAChromiumEndpointWithoutThisWebViewsMarker()
    {
        var targets = Encoding.UTF8.GetBytes(
            """
              [
                {
                  "type": "page",
                  "url": "https://example.test/foreign"
                }
              ]
              """);

        Assert.Throws<WindowHostException>(
            () => ProviderCdpProof.RequireOwnedTarget(
                targets,
                "about:blank#stockroom-provider-expected"));
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
            "ProviderCdpProof.RequireVersion",
            source,
            StringComparison.Ordinal);
        Assert.Contains(
            "ProviderCdpProof.RequireOwnedTarget",
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
