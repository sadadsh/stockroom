using System.Globalization;
using System.Windows;
using System.Windows.Automation;
using System.Windows.Controls;
using System.Windows.Media;

namespace Stockroom.WindowHost;

/// <summary>
/// The label the provider tab wears.
///
/// Stockroom already knows which provider a lease is for - the lease carries
/// <see cref="ProviderLeaseContext.ProviderId"/> - so the tab is named after the provider
/// rather than after whatever the page happens to call itself that minute. A provider the
/// registry does not know still gets a tab under its own key; only a lease that names no
/// provider at all falls back to the document title, then the host name, then a plain word.
/// </summary>
internal static class ProviderTabLabel
{
    internal const string Fallback = "Provider";

    /// <summary>Long enough for "Ultra Librarian" and a real page title, short enough that
    /// the tab never eats the address box.</summary>
    internal const int MaximumLength = 40;

    /// <summary>
    /// Mirrors the labels in <c>app/backend/stockroom/providers.py</c>, which stays the one
    /// authoritative catalogue. <c>WindowTabStripTests</c> reads that file and fails if the
    /// two ever drift, so the duplication cannot go stale quietly.
    /// </summary>
    private static readonly Dictionary<string, string> DisplayNames =
        new(StringComparer.Ordinal)
        {
            ["digikey"] = "DigiKey",
            ["mouser"] = "Mouser",
            ["ultralibrarian"] = "Ultra Librarian",
            ["samacsys"] = "SamacSys",
            ["snapmagic"] = "SnapMagic",
            ["manufacturer"] = "Manufacturer",
            ["traceparts"] = "TraceParts",
            ["cadenas"] = "CADENAS",
        };

    internal static IReadOnlyDictionary<string, string> KnownProviders => DisplayNames;

    internal static string Resolve(
        string? providerId,
        string? documentTitle,
        string? url)
    {
        var key = Collapse(providerId);
        if (key.Length > 0)
        {
            return Truncate(
                DisplayNames.TryGetValue(key, out var label) ? label : key);
        }

        var title = Collapse(documentTitle);
        if (title.Length > 0)
        {
            return Truncate(title);
        }

        var host = HostLabel(url);
        return host.Length > 0 ? Truncate(host) : Fallback;
    }

    private static string HostLabel(string? url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var parsed)
            || string.IsNullOrWhiteSpace(parsed.IdnHost))
        {
            return string.Empty;
        }

        var host = parsed.IdnHost;
        return host.StartsWith("www.", StringComparison.OrdinalIgnoreCase)
            ? host[4..]
            : host;
    }

    private static string Collapse(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }

        var builder = new System.Text.StringBuilder(value.Length);
        var pendingSpace = false;
        foreach (var character in value)
        {
            if (char.IsControl(character) || char.IsWhiteSpace(character))
            {
                pendingSpace = builder.Length > 0;
                continue;
            }

            if (pendingSpace)
            {
                _ = builder.Append(' ');
                pendingSpace = false;
            }

            _ = builder.Append(character);
        }

        return builder.ToString();
    }

    private static string Truncate(string value) =>
        value.Length <= MaximumLength
            ? value
            : string.Create(
                CultureInfo.InvariantCulture,
                $"{value[..(MaximumLength - 1)]}…");
}

/// <summary>
/// Stockroom's window chrome: one browser-style tab strip that is part of the window, not part
/// of the page.
///
/// The Stockroom tab is always there and is selected whenever Stockroom's own UI is showing.
/// A second tab appears only while a provider page is actually open, and there is never more
/// than one - the single-lease, generation-fenced design is what makes a download provably
/// belong to one component, and a second concurrent provider tab would be a second way to be
/// wrong. Popups a provider spawns (an OAuth window) stack over that one page under the same
/// lease; they are not separate tabs, because they are not separate work.
///
/// Back / Forward / Refresh / the address box / the loading and error text belong to the
/// provider page. With no page selected they are collapsed rather than greyed: there is no
/// honest thing for them to do, so they are not there to be clicked.
/// </summary>
internal sealed class WindowTabStrip
{
    internal const double StripHeight = 44;
    private const string TabGroupName = "StockroomWindowTabs";

    private static readonly Color SurfaceColor = Color.FromRgb(17, 21, 29);
    private static readonly Color IdleTabColor = Color.FromRgb(23, 28, 37);
    private static readonly Color HoverTabColor = Color.FromRgb(31, 38, 50);
    private static readonly Color SelectedTabColor = Color.FromRgb(38, 46, 60);
    private static readonly Color IdleTextColor = Color.FromRgb(148, 160, 176);
    private static readonly Color SelectedTextColor = Color.FromRgb(233, 238, 245);
    private static readonly Color ControlTextColor = Color.FromRgb(205, 214, 225);
    private static readonly Color ControlSurfaceColor = Color.FromRgb(27, 33, 44);
    private static readonly Color EdgeColor = Color.FromRgb(55, 65, 81);
    private static readonly Color AccentColor = Color.FromRgb(96, 165, 250);

    private readonly ControlTemplate _tabTemplate;

    internal WindowTabStrip()
    {
        _tabTemplate = BuildTabTemplate();
        Root = new Grid
        {
            Height = StripHeight,
            Margin = new Thickness(24, 0, 24, 0),
            Background = new SolidColorBrush(SurfaceColor),
        };
        AutomationProperties.SetName(Root, "Stockroom Window Tabs");
        AutomationProperties.SetAutomationId(Root, "stockroom-window-tabs");
        for (var column = 0; column < 5; column += 1)
        {
            Root.ColumnDefinitions.Add(
                new ColumnDefinition { Width = GridLength.Auto });
        }

        Root.ColumnDefinitions.Add(
            new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        Root.ColumnDefinitions.Add(
            new ColumnDefinition { Width = GridLength.Auto });

        StockroomTab = BuildTab("Stockroom", "stockroom-tab");
        AutomationProperties.SetHelpText(
            StockroomTab,
            "Show Stockroom");
        StockroomTab.IsChecked = true;
        ProviderTab = BuildTab(ProviderTabLabel.Fallback, "provider-tab");
        AutomationProperties.SetHelpText(
            ProviderTab,
            "Show the open provider page");
        ProviderTab.Visibility = Visibility.Collapsed;

        BackButton = BuildNavigationButton("Back", "provider-back");
        ForwardButton = BuildNavigationButton("Forward", "provider-forward");
        RefreshButton = BuildNavigationButton("Refresh", "provider-refresh");
        // The person drives the provider page, so the chrome shows them where they are and
        // lets them go somewhere: a real address box, policy-checked like every other
        // provider navigation (https only, no userinfo).
        UrlBox = new TextBox
        {
            Background = new SolidColorBrush(ControlSurfaceColor),
            Foreground = new SolidColorBrush(ControlTextColor),
            CaretBrush = new SolidColorBrush(ControlTextColor),
            BorderBrush = new SolidColorBrush(EdgeColor),
            FontFamily = new FontFamily("Segoe UI"),
            FontSize = 11,
            Padding = new Thickness(8, 3, 8, 3),
            Margin = new Thickness(8, 9, 0, 9),
            VerticalContentAlignment = VerticalAlignment.Center,
        };
        AutomationProperties.SetName(UrlBox, "Provider Page Address");
        AutomationProperties.SetAutomationId(UrlBox, "provider-url");
        StatusText = new TextBlock
        {
            Text = string.Empty,
            Foreground = new SolidColorBrush(Color.FromRgb(132, 145, 162)),
            FontFamily = new FontFamily("Segoe UI"),
            FontSize = 11,
            VerticalAlignment = VerticalAlignment.Center,
            HorizontalAlignment = HorizontalAlignment.Right,
            Margin = new Thickness(12, 0, 14, 0),
        };
        AutomationProperties.SetName(StatusText, "Provider Page Status");
        AutomationProperties.SetAutomationId(StatusText, "provider-status");
        AutomationProperties.SetLiveSetting(StatusText, AutomationLiveSetting.Polite);

        Place(StockroomTab, 0);
        Place(ProviderTab, 1);
        Place(BackButton, 2);
        Place(ForwardButton, 3);
        Place(RefreshButton, 4);
        Place(UrlBox, 5);
        Place(StatusText, 6);
        ApplyTabAppearance();
        ApplyProviderControlVisibility();
    }

    /// <summary>The strip itself, mounted in the window's first row from startup onward.</summary>
    internal Grid Root { get; }

    internal RadioButton StockroomTab { get; }

    internal RadioButton ProviderTab { get; }

    internal Button BackButton { get; }

    internal Button ForwardButton { get; }

    internal Button RefreshButton { get; }

    internal TextBox UrlBox { get; }

    internal TextBlock StatusText { get; }

    /// <summary>True only while a provider page is open under the one active lease.</summary>
    internal bool HasProviderTab =>
        ProviderTab.Visibility == Visibility.Visible;

    internal bool IsProviderSelected =>
        HasProviderTab && ProviderTab.IsChecked == true;

    internal bool IsStockroomSelected => StockroomTab.IsChecked == true;

    internal string ProviderTabText => (string)ProviderTab.Content;

    /// <summary>
    /// Give the open provider page a tab. Deliberately does not steal the selection: a lease
    /// can begin while the person is still reading Stockroom, and the page becomes visible
    /// only when Stockroom or the person asks for it.
    /// </summary>
    internal void ShowProviderTab(string label)
    {
        SetProviderTabLabel(label);
        ProviderTab.Visibility = Visibility.Visible;
        ApplyTabAppearance();
        ApplyProviderControlVisibility();
    }

    internal void SetProviderTabLabel(string label)
    {
        var text = string.IsNullOrWhiteSpace(label)
            ? ProviderTabLabel.Fallback
            : label;
        ProviderTab.Content = text;
        AutomationProperties.SetName(ProviderTab, text);
    }

    /// <summary>The page is gone, so the tab is gone and Stockroom is what is left.</summary>
    internal void RemoveProviderTab()
    {
        ProviderTab.Visibility = Visibility.Collapsed;
        ProviderTab.IsChecked = false;
        SetProviderTabLabel(ProviderTabLabel.Fallback);
        StockroomTab.IsChecked = true;
        SetNavigationState(canGoBack: false, canGoForward: false);
        SetStatus(string.Empty);
        SetUrl(string.Empty);
        ApplyTabAppearance();
        ApplyProviderControlVisibility();
    }

    internal void SelectStockroom()
    {
        ProviderTab.IsChecked = false;
        StockroomTab.IsChecked = true;
        ApplyTabAppearance();
        ApplyProviderControlVisibility();
    }

    internal void SelectProvider()
    {
        if (!HasProviderTab)
        {
            SelectStockroom();
            return;
        }

        StockroomTab.IsChecked = false;
        ProviderTab.IsChecked = true;
        ApplyTabAppearance();
        ApplyProviderControlVisibility();
    }

    internal void SetNavigationState(bool canGoBack, bool canGoForward)
    {
        BackButton.IsEnabled = IsProviderSelected && canGoBack;
        ForwardButton.IsEnabled = IsProviderSelected && canGoForward;
        RefreshButton.IsEnabled = IsProviderSelected;
    }

    internal void SetStatus(string text)
    {
        StatusText.Text = text ?? string.Empty;
    }

    internal void SetUrl(string url)
    {
        UrlBox.Text = url ?? string.Empty;
    }

    private void ApplyProviderControlVisibility()
    {
        // Back / Forward / Refresh / address / status describe a page. With no page selected
        // they are collapsed, not greyed-out decoration the person can try to click.
        var visibility = IsProviderSelected
            ? Visibility.Visible
            : Visibility.Collapsed;
        BackButton.Visibility = visibility;
        ForwardButton.Visibility = visibility;
        RefreshButton.Visibility = visibility;
        UrlBox.Visibility = visibility;
        StatusText.Visibility = visibility;
        if (!IsProviderSelected)
        {
            BackButton.IsEnabled = false;
            ForwardButton.IsEnabled = false;
            RefreshButton.IsEnabled = false;
        }
        else
        {
            RefreshButton.IsEnabled = true;
        }
    }

    private void ApplyTabAppearance()
    {
        ApplyTabAppearance(StockroomTab, StockroomTab.IsChecked == true);
        ApplyTabAppearance(ProviderTab, ProviderTab.IsChecked == true);
    }

    private static void ApplyTabAppearance(RadioButton tab, bool selected)
    {
        tab.Background = new SolidColorBrush(
            selected ? SelectedTabColor : IdleTabColor);
        tab.Foreground = new SolidColorBrush(
            selected ? SelectedTextColor : IdleTextColor);
        tab.BorderBrush = new SolidColorBrush(
            selected ? AccentColor : EdgeColor);
        tab.BorderThickness = selected
            ? new Thickness(1, 1, 1, 2)
            : new Thickness(1, 1, 1, 1);
    }

    private RadioButton BuildTab(string label, string automationId)
    {
        // A RadioButton, not a plain Button: WPF hands it a SelectionItem automation pattern,
        // so exactly one tab reports itself selected to a screen reader instead of the strip
        // being a row of identical unlabelled presses.
        var tab = new RadioButton
        {
            Content = label,
            GroupName = TabGroupName,
            Template = _tabTemplate,
            FontFamily = new FontFamily("Segoe UI Semibold"),
            FontSize = 11,
            Padding = new Thickness(14, 5, 14, 5),
            Margin = new Thickness(0, 8, 6, 0),
            VerticalAlignment = VerticalAlignment.Bottom,
            Cursor = System.Windows.Input.Cursors.Hand,
        };
        AutomationProperties.SetName(tab, label);
        AutomationProperties.SetAutomationId(tab, automationId);
        tab.MouseEnter += (_, _) =>
        {
            if (tab.IsChecked != true)
            {
                tab.Background = new SolidColorBrush(HoverTabColor);
                tab.Foreground = new SolidColorBrush(ControlTextColor);
            }
        };
        tab.MouseLeave += (_, _) => ApplyTabAppearance(tab, tab.IsChecked == true);
        tab.Checked += (_, _) => ApplyTabAppearance(tab, selected: true);
        tab.Unchecked += (_, _) => ApplyTabAppearance(tab, selected: false);
        return tab;
    }

    private static Button BuildNavigationButton(string label, string automationId)
    {
        var idleForeground = new SolidColorBrush(ControlTextColor);
        var idleBackground = new SolidColorBrush(ControlSurfaceColor);
        var hoverForeground = new SolidColorBrush(SurfaceColor);
        var hoverBackground = new SolidColorBrush(ControlTextColor);
        var button = new Button
        {
            Content = label,
            Foreground = idleForeground,
            Background = idleBackground,
            BorderBrush = new SolidColorBrush(EdgeColor),
            FontFamily = new FontFamily("Segoe UI Semibold"),
            FontSize = 11,
            Padding = new Thickness(10, 4, 10, 4),
            Margin = new Thickness(8, 7, 0, 7),
            VerticalAlignment = VerticalAlignment.Center,
            IsEnabled = false,
            Visibility = Visibility.Collapsed,
        };
        AutomationProperties.SetName(button, label);
        AutomationProperties.SetAutomationId(button, automationId);
        // Windows' default Button visual state paints a light hover surface. Keep the label
        // readable instead of letting the inherited dark foreground disappear under the cursor.
        button.MouseEnter += (_, _) =>
        {
            button.Foreground = hoverForeground;
            button.Background = hoverBackground;
        };
        button.MouseLeave += (_, _) =>
        {
            button.Foreground = idleForeground;
            button.Background = idleBackground;
        };
        return button;
    }

    private void Place(UIElement element, int column)
    {
        Grid.SetColumn(element, column);
        _ = Root.Children.Add(element);
    }

    private static ControlTemplate BuildTabTemplate()
    {
        var border = new FrameworkElementFactory(typeof(Border));
        border.SetValue(
            Border.BackgroundProperty,
            new TemplateBindingExtension(Control.BackgroundProperty));
        border.SetValue(
            Border.BorderBrushProperty,
            new TemplateBindingExtension(Control.BorderBrushProperty));
        border.SetValue(
            Border.BorderThicknessProperty,
            new TemplateBindingExtension(Control.BorderThicknessProperty));
        border.SetValue(
            Border.PaddingProperty,
            new TemplateBindingExtension(Control.PaddingProperty));
        border.SetValue(
            Border.CornerRadiusProperty,
            new CornerRadius(5, 5, 0, 0));
        var presenter = new FrameworkElementFactory(typeof(ContentPresenter));
        presenter.SetValue(
            ContentPresenter.HorizontalAlignmentProperty,
            HorizontalAlignment.Center);
        presenter.SetValue(
            ContentPresenter.VerticalAlignmentProperty,
            VerticalAlignment.Center);
        border.AppendChild(presenter);
        return new ControlTemplate(typeof(RadioButton)) { VisualTree = border };
    }
}
