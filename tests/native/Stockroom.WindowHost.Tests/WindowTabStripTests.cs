using System.Runtime.ExceptionServices;
using System.Text.RegularExpressions;
using System.Windows;

namespace Stockroom.WindowHost.Tests;

/// <summary>
/// The tab strip is window chrome. These tests state what a person sees in each state: one
/// always-present Stockroom tab, a second tab only while a provider page is open, and page
/// controls that exist only when there is a page for them to act on.
/// </summary>
public sealed class WindowTabStripTests
{
    [Fact]
    public void StripIsPresentWithNoLeaseAndShowsOnlyTheStockroomTab()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();

            Assert.Equal(Visibility.Visible, strip.Root.Visibility);
            Assert.Equal(WindowTabStrip.StripHeight, strip.Root.Height);
            Assert.Equal(Visibility.Visible, strip.StockroomTab.Visibility);
            Assert.Equal(Visibility.Collapsed, strip.ProviderTab.Visibility);
            Assert.False(strip.HasProviderTab);
            Assert.True(strip.IsStockroomSelected);
            Assert.False(strip.IsProviderSelected);
        });
    }

    [Fact]
    public void NavigationControlsAreAbsentAndInertWithNoProviderPage()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();

            // Nothing dead-but-clickable: with no page open these are not on screen at all.
            foreach (var element in new UIElement[]
            {
                strip.BackButton,
                strip.ForwardButton,
                strip.RefreshButton,
                strip.UrlBox,
                strip.StatusText,
            })
            {
                Assert.Equal(Visibility.Collapsed, element.Visibility);
            }

            Assert.False(strip.BackButton.IsEnabled);
            Assert.False(strip.ForwardButton.IsEnabled);
            Assert.False(strip.RefreshButton.IsEnabled);

            // Even a page that reports history cannot light up controls that are not there.
            strip.SetNavigationState(canGoBack: true, canGoForward: true);
            Assert.False(strip.BackButton.IsEnabled);
            Assert.False(strip.ForwardButton.IsEnabled);
            Assert.False(strip.RefreshButton.IsEnabled);
        });
    }

    [Fact]
    public void ProviderTabAppearsWhenAPageOpensAndCarriesTheProviderName()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();

            strip.ShowProviderTab(
                ProviderTabLabel.Resolve("digikey", "Cart | DigiKey", "https://www.digikey.com/"));

            Assert.True(strip.HasProviderTab);
            Assert.Equal(Visibility.Visible, strip.ProviderTab.Visibility);
            Assert.Equal("DigiKey", strip.ProviderTabText);
            // Opening a page in the background does not yank the person out of Stockroom.
            Assert.True(strip.IsStockroomSelected);
            Assert.False(strip.IsProviderSelected);
        });
    }

    [Fact]
    public void SelectingEachTabShowsExactlyThatTabAsSelected()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();
            strip.ShowProviderTab("Ultra Librarian");

            strip.SelectProvider();
            Assert.True(strip.IsProviderSelected);
            Assert.False(strip.IsStockroomSelected);
            Assert.True(strip.ProviderTab.IsChecked);
            Assert.False(strip.StockroomTab.IsChecked);

            strip.SelectStockroom();
            Assert.True(strip.IsStockroomSelected);
            Assert.False(strip.IsProviderSelected);
            Assert.True(strip.StockroomTab.IsChecked);
            Assert.False(strip.ProviderTab.IsChecked);
        });
    }

    [Fact]
    public void NavigationControlsBelongToTheSelectedProviderTab()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();
            strip.ShowProviderTab("SamacSys");

            // A tab that exists but is not selected still has no page on screen to act on.
            Assert.Equal(Visibility.Collapsed, strip.BackButton.Visibility);
            Assert.Equal(Visibility.Collapsed, strip.UrlBox.Visibility);

            strip.SelectProvider();
            foreach (var element in new UIElement[]
            {
                strip.BackButton,
                strip.ForwardButton,
                strip.RefreshButton,
                strip.UrlBox,
                strip.StatusText,
            })
            {
                Assert.Equal(Visibility.Visible, element.Visibility);
            }

            Assert.True(strip.RefreshButton.IsEnabled);
            Assert.False(strip.BackButton.IsEnabled);
            strip.SetNavigationState(canGoBack: true, canGoForward: false);
            Assert.True(strip.BackButton.IsEnabled);
            Assert.False(strip.ForwardButton.IsEnabled);

            strip.SelectStockroom();
            Assert.Equal(Visibility.Collapsed, strip.BackButton.Visibility);
            Assert.False(strip.BackButton.IsEnabled);
            Assert.False(strip.RefreshButton.IsEnabled);
        });
    }

    [Fact]
    public void ReleasingTheLeaseRemovesTheProviderTabAndLeavesStockroomSelected()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();
            strip.ShowProviderTab("DigiKey");
            strip.SelectProvider();
            strip.SetUrl("https://www.digikey.com/en/products");
            strip.SetStatus("Loading");

            strip.RemoveProviderTab();

            Assert.False(strip.HasProviderTab);
            Assert.Equal(Visibility.Collapsed, strip.ProviderTab.Visibility);
            Assert.True(strip.IsStockroomSelected);
            Assert.False(strip.IsProviderSelected);
            Assert.Equal(Visibility.Visible, strip.StockroomTab.Visibility);
            Assert.Equal(Visibility.Visible, strip.Root.Visibility);
            Assert.Equal(string.Empty, strip.UrlBox.Text);
            Assert.Equal(string.Empty, strip.StatusText.Text);
            Assert.Equal(Visibility.Collapsed, strip.RefreshButton.Visibility);
        });
    }

    [Fact]
    public void SelectingTheProviderTabWithNoOpenPageFallsBackToStockroom()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();

            strip.SelectProvider();

            Assert.True(strip.IsStockroomSelected);
            Assert.False(strip.IsProviderSelected);
        });
    }

    [Fact]
    public void TabsCarryAccessibleNamesAndSelectionState()
    {
        Sta.Run(() =>
        {
            var strip = new WindowTabStrip();
            strip.ShowProviderTab("Mouser");

            Assert.Equal(
                "Stockroom",
                System.Windows.Automation.AutomationProperties.GetName(strip.StockroomTab));
            Assert.Equal(
                "Mouser",
                System.Windows.Automation.AutomationProperties.GetName(strip.ProviderTab));
            Assert.Equal(
                "stockroom-tab",
                System.Windows.Automation.AutomationProperties.GetAutomationId(strip.StockroomTab));
            Assert.Equal(
                "provider-tab",
                System.Windows.Automation.AutomationProperties.GetAutomationId(strip.ProviderTab));
            Assert.Equal(
                "Back",
                System.Windows.Automation.AutomationProperties.GetName(strip.BackButton));
            Assert.Equal(
                "Provider Page Address",
                System.Windows.Automation.AutomationProperties.GetName(strip.UrlBox));

            // Selection is real WPF toggle state, so the SelectionItem automation pattern
            // reports exactly one selected tab rather than two indistinguishable presses.
            strip.SelectProvider();
            Assert.True(strip.ProviderTab.IsChecked);
            Assert.False(strip.StockroomTab.IsChecked);
            Assert.Equal(strip.StockroomTab.GroupName, strip.ProviderTab.GroupName);
        });
    }

    [Theory]
    [InlineData("digikey", "Ignored Title", "https://www.digikey.com/", "DigiKey")]
    [InlineData("ultralibrarian", "", "", "Ultra Librarian")]
    [InlineData("cadenas", "", "", "CADENAS")]
    [InlineData("newvendor", "", "", "newvendor")]
    [InlineData("", "  Component   Search  Engine ", "", "Component Search Engine")]
    [InlineData("", "", "https://www.componentsearchengine.com/x", "componentsearchengine.com")]
    [InlineData("", "", "https://app.ultralibrarian.com/search", "app.ultralibrarian.com")]
    [InlineData("", "", "", "Provider")]
    [InlineData("", "", "about:blank", "Provider")]
    [InlineData(null, null, null, "Provider")]
    public void ProviderTabLabelPrefersTheLeasedProviderThenTheTitleThenTheHost(
        string? providerId,
        string? documentTitle,
        string? url,
        string expected)
    {
        Assert.Equal(
            expected,
            ProviderTabLabel.Resolve(providerId, documentTitle, url));
    }

    [Fact]
    public void ProviderTabLabelStaysShortEnoughToLeaveRoomForTheAddressBox()
    {
        var resolved = ProviderTabLabel.Resolve(
            providerId: null,
            documentTitle: new string('a', 200),
            url: null);

        Assert.Equal(ProviderTabLabel.MaximumLength, resolved.Length);
        Assert.EndsWith("…", resolved, StringComparison.Ordinal);
    }

    [Fact]
    public void ProviderDisplayNamesMatchTheOneAuthoritativeCatalogue()
    {
        // providers.py is the single registry every other surface reads. The native tab needs
        // the same words, so this fails the moment the two descriptions of one provider drift.
        var registry = File.ReadAllText(
            Path.Combine(
                FindRepositoryRoot(),
                "app",
                "backend",
                "stockroom",
                "providers.py"));
        var matches = Regex.Matches(
            registry,
            "key=\"(?<key>[a-z0-9]+)\",\\s*\\r?\\n\\s*label=\"(?<label>[^\"]+)\",",
            RegexOptions.CultureInvariant,
            TimeSpan.FromSeconds(5));

        Assert.NotEmpty(matches);
        Assert.Equal(matches.Count, ProviderTabLabel.KnownProviders.Count);
        foreach (Match match in matches)
        {
            var key = match.Groups["key"].Value;
            Assert.True(
                ProviderTabLabel.KnownProviders.TryGetValue(key, out var label),
                $"the native tab strip does not know the provider '{key}'");
            Assert.Equal(match.Groups["label"].Value, label);
        }
    }

    private static string FindRepositoryRoot()
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
                if (File.Exists(
                        Path.Combine(
                            current.FullName,
                            "app",
                            "backend",
                            "stockroom",
                            "providers.py")))
                {
                    return current.FullName;
                }

                current = current.Parent;
            }
        }

        throw new InvalidOperationException(
            "Stockroom repository root was not found");
    }
}

/// <summary>
/// WPF controls have thread affinity and refuse to exist outside a single-threaded apartment.
/// Each case gets its own STA thread so the chrome under test is real WPF, not a stand-in.
/// </summary>
internal static class Sta
{
    internal static void Run(Action action)
    {
        ExceptionDispatchInfo? failure = null;
        var thread = new Thread(
            () =>
            {
                try
                {
                    action();
                }
                catch (Exception exception)
                {
                    failure = ExceptionDispatchInfo.Capture(exception);
                }
            })
        {
            IsBackground = true,
        };
        thread.SetApartmentState(ApartmentState.STA);
        thread.Start();
        thread.Join();
        failure?.Throw();
    }
}
