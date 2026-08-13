using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
using System.Windows.Input;
using System.Windows.Interop;
using System.Windows.Media;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;
using Microsoft.Win32;

namespace Stockroom.WindowHost;

internal sealed record RendererReadiness(
    bool ApiHealthy,
    bool EventStreamHealthy);

internal enum WindowHostFailureStage
{
    Environment = 21,
    WebViewControl = 22,
    Navigation = 23,
    RendererProbe = 24,
    Runtime = 25,
}

internal sealed class WebViewWindowHost : IDisposable
{
    private const int InitializationTimeoutSeconds = 30;
    private const int ProviderInitializationAttempts = 3;

    private readonly HandoffBootstrap _bootstrap;
    private readonly MachineWindowConfig _machineConfig;
    private readonly Action _fatalFailure;
    private readonly Window _window;
    private readonly WebView2 _webView;
    private readonly Grid _root;
    private readonly WindowTabStrip _tabStrip;
    private readonly Grid _providerSurface;
    private readonly Grid _providerContent;
    private readonly Dictionary<WebView2, ProviderLeaseIdentity> _providerPopups = [];
    private readonly ProviderLeaseJournal _providerLeases = new();
    private readonly WindowsShellSurface _shell = new();
    private readonly TaskCompletionSource<bool> _navigationCompletion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly string _probeNonce;

    private CoreWebView2Environment? _environment;
    private CoreWebView2Environment? _providerEnvironment;
    private WebView2? _providerWebView;
    private IntPtr _windowHandle;
    private ResolvedWindowGeometry? _resolvedGeometry;
    private RendererReadiness? _readiness;
    private Exception? _fatalException;
    private bool _initialized;
    private bool _providerLoading;
    private string _providerNavigationError = string.Empty;
    private ProviderViewportRequest? _providerViewportRequest;
    private bool _hidden = true;
    private volatile bool _shuttingDown;
    private bool _closeRequested;
    private bool _disposed;
    private int _failureExitCode =
        (int)WindowHostFailureStage.Environment;

    internal WebViewWindowHost(
        HandoffBootstrap bootstrap,
        MachineWindowConfig machineConfig,
        Action fatalFailure)
    {
        _bootstrap = bootstrap
            ?? throw new ArgumentNullException(nameof(bootstrap));
        _machineConfig = machineConfig
            ?? throw new ArgumentNullException(nameof(machineConfig));
        _fatalFailure = fatalFailure
            ?? throw new ArgumentNullException(nameof(fatalFailure));
        _probeNonce = Convert.ToHexStringLower(
            RandomNumberGenerator.GetBytes(16));
        _webView = new WebView2
        {
            AllowDrop = false,
            CreationProperties = new CoreWebView2CreationProperties(),
        };
        _root = new Grid();
        _root.RowDefinitions.Add(
            new RowDefinition { Height = GridLength.Auto });
        _root.RowDefinitions.Add(
            new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        Grid.SetRow(_webView, 1);
        _root.Children.Add(_webView);
        // The tab strip is window chrome, not page chrome: it is mounted once, stays visible
        // for the life of the window, and shows a single Stockroom tab until a provider page
        // is actually open.
        _tabStrip = new WindowTabStrip();
        // Provider navigation now lives inside CAD Models > Manage Models. Keep the proven
        // navigation controller during rolling compatibility, but remove its window-level UI.
        _tabStrip.Root.Visibility = Visibility.Collapsed;
        _tabStrip.Root.IsHitTestVisible = false;
        _tabStrip.StockroomTab.Click += (_, _) => HideProviderBrowser();
        _tabStrip.ProviderTab.Click += (_, _) => ShowActiveProviderBrowser();
        _tabStrip.BackButton.Click += (_, _) => NavigateProviderHistory(back: true);
        _tabStrip.ForwardButton.Click += (_, _) => NavigateProviderHistory(back: false);
        _tabStrip.RefreshButton.Click += (_, _) => RefreshActiveProvider();
        _tabStrip.UrlBox.KeyDown += OnProviderUrlBoxKeyDown;
        Grid.SetRow(_tabStrip.Root, 0);
        _root.Children.Add(_tabStrip.Root);
        _providerSurface = BuildProviderSurface(out _providerContent);
        Grid.SetRow(_providerSurface, 1);
        _root.Children.Add(_providerSurface);
        _window = new Window
        {
            Title = "Stockroom",
            Width = 1280,
            Height = 800,
            MinWidth = 960,
            MinHeight = 640,
            WindowStartupLocation = WindowStartupLocation.CenterScreen,
            ShowInTaskbar = false,
            ShowActivated = false,
            Visibility = Visibility.Hidden,
            Opacity = 0,
            AllowDrop = false,
            Content = _root,
        };
        _window.Closing += OnWindowClosing;
        // Window-level and previewed, so the two history keys work whether the focus is in the
        // strip or inside the provider page.
        _window.PreviewKeyDown += OnWindowPreviewKeyDown;
    }

    internal IntPtr WindowHandle =>
        _windowHandle != IntPtr.Zero
            ? _windowHandle
            : throw new WindowHostException(
                "window handle is not ready");

    internal int FailureExitCode =>
        Volatile.Read(ref _failureExitCode);

    internal async Task InitializeAsync()
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        if (_initialized)
        {
            throw new WindowHostException(
                "native window was initialized twice");
        }

        _windowHandle = new WindowInteropHelper(_window).EnsureHandle();
        if (_windowHandle == IntPtr.Zero)
        {
            throw new WindowHostException(
                "native window handle could not be created");
        }

        _resolvedGeometry = WindowsWindowGeometry.ApplyHidden(
            _windowHandle,
            _machineConfig.Geometry);
        // The WPF WebView2 control deliberately gates initialization until
        // FrameworkElement.Loaded.  Load it through a fully transparent,
        // non-activating, taskbar-free top-level window, then return the HWND
        // to the actual hidden state before the child sends hello-hidden.
        _window.Show();
        var profileDirectory = _machineConfig.ProfileDirectory(
            _bootstrap.ProfileId);
        var options = new CoreWebView2EnvironmentOptions
        {
            ExclusiveUserDataFolderAccess = true,
        };
        _environment = await CoreWebView2Environment.CreateAsync(
                browserExecutableFolder: null,
                userDataFolder: profileDirectory,
                options)
            .ConfigureAwait(true);
        _environment.BrowserProcessExited += OnBrowserProcessExited;
        SetFailureStage(WindowHostFailureStage.WebViewControl);
        await _webView.EnsureCoreWebView2Async(_environment)
            .ConfigureAwait(true);
        ConfigureCoreWebView(_webView.CoreWebView2);
        await AddMachineUiBootstrapAsync(_webView.CoreWebView2)
            .ConfigureAwait(true);
        _webView.CoreWebView2.NavigationCompleted +=
            OnNavigationCompleted;
        SetFailureStage(WindowHostFailureStage.Navigation);
        _webView.Source = _bootstrap.BaseUri;

        try
        {
            await _navigationCompletion.Task.WaitAsync(
                    TimeSpan.FromSeconds(
                        InitializationTimeoutSeconds))
                .ConfigureAwait(true);
            ThrowIfFatal();
            SetFailureStage(WindowHostFailureStage.RendererProbe);
            _readiness = await RunAuthenticatedRendererProbesAsync(
                    _webView.CoreWebView2)
                .WaitAsync(
                    TimeSpan.FromSeconds(
                        InitializationTimeoutSeconds))
                .ConfigureAwait(true);
        }
        catch (TimeoutException exception)
        {
            throw new WindowHostException(
                "native WebView2 readiness timed out",
                exception);
        }

        if (!_readiness.ApiHealthy
            || !_readiness.EventStreamHealthy
            || !OriginPolicy.IsAllowedNavigation(
                _webView.Source?.AbsoluteUri,
                _bootstrap.BaseUri))
        {
            throw new WindowHostException(
                "native WebView2 readiness did not pass");
        }

        _window.Hide();
        _window.Opacity = 1;
        _window.ShowInTaskbar = false;
        _hidden = true;
        SetFailureStage(WindowHostFailureStage.Runtime);
        _initialized = true;
    }

    internal void PrepareHidden(long deadlineUnixMilliseconds)
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                if (DateTimeOffset.UtcNow.ToUnixTimeMilliseconds()
                    > deadlineUnixMilliseconds)
                {
                    throw new WindowHostException(
                        "managed-window prepare deadline expired");
                }

                _window.Hide();
                _window.ShowInTaskbar = false;
                _hidden = true;
            });
    }

    internal void Show()
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                _window.Opacity = 0;
                _window.ShowInTaskbar = true;
                _window.Show();
                _resolvedGeometry = WindowsWindowGeometry.ApplyHidden(
                    _windowHandle,
                    _machineConfig.Geometry);
                WindowsWindowGeometry.Show(
                    _windowHandle,
                    _resolvedGeometry);
                _window.Opacity = 1;
                _hidden = false;
            });
    }

    internal void Focus()
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                if (_hidden)
                {
                    throw new WindowHostException(
                        "cannot focus a hidden managed window");
                }

                WindowsWindowGeometry.Focus(_windowHandle);
                _window.Activate();
            });
    }

    internal IReadOnlyDictionary<string, object?> Health()
    {
        return InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                var currentUrl = _webView.Source?.AbsoluteUri;
                if (!OriginPolicy.IsAllowedNavigation(
                        currentUrl,
                        _bootstrap.BaseUri))
                {
                    throw new WindowHostException(
                        "managed window left the Stockroom origin");
                }

                return new Dictionary<string, object?>
                {
                    ["hwnd"] = _windowHandle.ToInt64(),
                    ["current_url"] = currentUrl,
                    ["hidden"] = _hidden,
                    ["visible"] = !_hidden,
                    ["renderer"] = "edgechromium",
                    ["close_requested"] = _closeRequested,
                };
            });
    }

    internal IReadOnlyDictionary<string, object?> BeginProviderLease(
        string leaseId,
        ProviderLeaseContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        return InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                await EnsureProviderBrowserReadyAsync().ConfigureAwait(true);
                var lease = _providerLeases.Begin(leaseId, context);
                SyncProviderTab();
                return new Dictionary<string, object?>
                {
                    ["lease_id"] = lease.LeaseId,
                    ["generation"] = lease.Generation,
                };
            });
    }

    internal bool ReleaseProviderLease(string leaseId, long generation)
    {
        return InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                var lease = new ProviderLeaseIdentity(leaseId, generation);
                if (!_providerLeases.Release(lease))
                {
                    return false;
                }
                foreach (var popup in _providerPopups
                    .Where(item => item.Value == lease)
                    .Select(static item => item.Key)
                    .ToArray())
                {
                    RemoveProviderPopup(popup);
                }
                // The page is closed, so its tab is gone and the Stockroom tab is what is
                // left selected. The strip itself stays exactly where it was.
                _tabStrip.RemoveProviderTab();
                _providerSurface.Visibility = Visibility.Collapsed;
                _webView.Visibility = Visibility.Visible;
                _webView.Focus();
                return true;
            });
    }

    internal IReadOnlyList<ProviderDownloadEvent> ProviderDownloadEvents(
        string leaseId,
        long generation,
        long afterSequence)
    {
        return _providerLeases.After(
            new ProviderLeaseIdentity(leaseId, generation),
            afterSequence);
    }

    internal void ShowProviderBrowser(string leaseId, long generation)
    {
        InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                await EnsureProviderBrowserReadyAsync()
                    .ConfigureAwait(true);
                SyncProviderTab();
                if (!TryApplyProviderViewport())
                {
                    _providerSurface.Visibility = Visibility.Collapsed;
                    _webView.Visibility = Visibility.Visible;
                    return true;
                }
                _webView.Visibility = Visibility.Visible;
                _providerSurface.Visibility = Visibility.Visible;
                _tabStrip.SelectProvider();
                UpdateProviderChrome();
                _providerWebView?.Focus();
                return true;
            });
    }

    internal void HideProviderBrowser()
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                ShowStockroomTab();
            });
    }

    internal void HideProviderBrowser(string leaseId, long generation)
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                ShowStockroomTab();
            });
    }

    /// <summary>
    /// Selecting Stockroom returns to Stockroom's own UI. The provider page is not closed by
    /// looking away from it - the lease and the tab both survive, exactly as a browser tab
    /// survives switching to another one.
    /// </summary>
    private void ShowStockroomTab()
    {
        _providerSurface.Visibility = Visibility.Collapsed;
        _webView.Visibility = Visibility.Visible;
        _tabStrip.SelectStockroom();
        _webView.Focus();
    }

    private void ShowActiveProviderBrowser()
    {
        if (!_providerLeases.TryGetActive(out _))
        {
            _tabStrip.SelectStockroom();
            return;
        }

        _webView.Visibility = Visibility.Collapsed;
        _providerSurface.Visibility = Visibility.Visible;
        _tabStrip.SelectProvider();
        UpdateProviderChrome();
        ActiveProviderWebView()?.Focus();
    }

    internal string ProviderCurrentUrl(string leaseId, long generation)
    {
        return InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                await EnsureProviderBrowserReadyAsync().ConfigureAwait(true);
                return _providerWebView?.Source?.AbsoluteUri ?? string.Empty;
            });
    }

    internal void NavigateProviderBrowser(string leaseId, long generation, string url)
    {
        if (!Uri.TryCreate(url, UriKind.Absolute, out var destination)
            || destination.Scheme is not ("http" or "https"))
        {
            throw new WindowHostException("provider URL is invalid");
        }
        InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                await EnsureProviderBrowserReadyAsync().ConfigureAwait(true);
                _providerWebView!.CoreWebView2.Navigate(destination.AbsoluteUri);
                return true;
            });
    }

    internal void RefreshProviderBrowser(string leaseId, long generation)
    {
        InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                RefreshActiveProvider();
                return true;
            });
    }

    internal IReadOnlyDictionary<string, object?> ProviderState(
        string leaseId,
        long generation)
    {
        return InvokeOnDispatcher(
            () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                return (IReadOnlyDictionary<string, object?>)
                    new Dictionary<string, object?>
                    {
                        ["url"] = ActiveProviderWebView()?.Source?.AbsoluteUri
                            ?? string.Empty,
                        ["loading"] = _providerLoading,
                        ["navigation_error"] = _providerNavigationError,
                    };
            });
    }

    internal IReadOnlyDictionary<string, object?> ProviderDocumentState(
        string leaseId,
        long generation,
        IReadOnlyList<string> readySelectors,
        IReadOnlyList<string> readyTexts)
    {
        ArgumentNullException.ThrowIfNull(readySelectors);
        ArgumentNullException.ThrowIfNull(readyTexts);
        return InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                _providerLeases.RequireActive(
                    new ProviderLeaseIdentity(leaseId, generation));
                await EnsureProviderBrowserReadyAsync().ConfigureAwait(true);
                var selectors = JsonSerializer.Serialize(readySelectors);
                var texts = JsonSerializer.Serialize(
                    readyTexts.Select(static value => value.ToLowerInvariant()));
                var script = $$"""
                    (() => {
                      const title = String(document.title || "").toLowerCase();
                      const body = String(document.body?.innerText || "").toLowerCase();
                      const selectors = {{selectors}};
                      const readyTexts = {{texts}};
                      const isVisible = (element) => {
                        if (!element) return false;
                        const style = window.getComputedStyle(element);
                        const rect = element.getBoundingClientRect();
                        return style.display !== "none" && style.visibility !== "hidden"
                          && Number(style.opacity || "1") > 0 && rect.width > 4 && rect.height > 4;
                      };
                      const challengeFrame = Array.from(document.querySelectorAll(
                        'iframe[src*="challenges.cloudflare.com"], iframe[title*="challenge" i]'
                      )).some(isVisible);
                      const accountVerification = [
                        "verify your phone number",
                        "phone verification is required",
                      ].some((value) => title.includes(value) || body.includes(value));
                      const providerError = [
                        "oh snap! we've experienced an error",
                        "oh snap! we’ve experienced an error",
                      ].some((value) => title.includes(value) || body.includes(value));
                      const challengeText = [
                        "verify you are human",
                        "verifying you are human",
                        "performing security verification",
                        "checking your browser",
                        "security verification",
                      ].some((value) => title.includes(value) || body.includes(value));
                      const selectorReady = selectors.some((selector) => {
                        try { return Array.from(document.querySelectorAll(selector)).some(isVisible); }
                        catch (_) { return false; }
                      });
                      const textReady = readyTexts.some((value) => body.includes(value));
                      return {
                        ready: document.readyState === "interactive" || document.readyState === "complete",
                        challenge: challengeFrame || accountVerification
                          || (challengeText && !(selectorReady || textReady)),
                        account_verification: accountVerification,
                        provider_error: providerError,
                        provider_ready: selectors.length === 0 && readyTexts.length === 0
                          ? true
                          : selectorReady || textReady,
                      };
                    })()
                    """;
                var encoded = await _providerWebView!.CoreWebView2
                    .ExecuteScriptAsync(script)
                    .ConfigureAwait(true);
                using var document = JsonDocument.Parse(encoded);
                var root = document.RootElement;
                HandoffCodec.RequireExactObject(
                    root,
                    "provider document state",
                    "ready",
                    "challenge",
                    "account_verification",
                    "provider_error",
                    "provider_ready");
                return new Dictionary<string, object?>
                {
                    ["ready"] = root.GetProperty("ready").GetBoolean(),
                    ["challenge"] = root.GetProperty("challenge").GetBoolean(),
                    ["account_verification"] = root.GetProperty("account_verification").GetBoolean(),
                    ["provider_error"] = root.GetProperty("provider_error").GetBoolean(),
                    ["provider_ready"] = root.GetProperty("provider_ready").GetBoolean(),
                };
            });
    }

    internal IReadOnlyDictionary<string, object?> ExportSession()
    {
        return InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                var script = """
                    (() => ({
                      ui_export:
                        typeof window.__STOCKROOM_EXPORT_UI_SESSION__ === "function"
                          ? window.__STOCKROOM_EXPORT_UI_SESSION__()
                          : null,
                      theme:
                        document.documentElement.dataset.theme === "light"
                          ? "light"
                          : "dark"
                    }))()
                    """;
                var encoded = await _webView.CoreWebView2
                    .ExecuteScriptAsync(script)
                    .ConfigureAwait(true);
                using var document = JsonDocument.Parse(encoded);
                var root = document.RootElement;
                HandoffCodec.RequireExactObject(
                    root,
                    "renderer session export",
                    "ui_export",
                    "theme");
                var theme = HandoffCodec.GetRequiredString(
                    root,
                    "theme");
                if (theme is not ("dark" or "light")
                    || theme != _machineConfig.Theme)
                {
                    throw new WindowHostException(
                        "rendered theme does not match machine continuity");
                }

                var uiExport = root.GetProperty("ui_export").Clone();
                SnapshotSanitizer.RequireNonSecret(
                    uiExport,
                    _bootstrap.ApiCredential,
                    _bootstrap.HandoffCredential);
                var geometry = WindowsWindowGeometry.Capture(
                    _windowHandle);
                var readiness = _readiness
                    ?? throw new WindowHostException(
                        "renderer readiness is unavailable");
                return (IReadOnlyDictionary<string, object?>)
                    new Dictionary<string, object?>
                    {
                        ["ui_export"] = uiExport,
                        ["theme"] = theme,
                        ["api_healthy"] = readiness.ApiHealthy,
                        ["event_stream_healthy"] =
                            readiness.EventStreamHealthy,
                        ["geometry"] = geometry,
                    };
            });
    }

    /// <summary>
    /// The EDA applications this machine really carries.
    /// </summary>
    /// <remarks>
    /// Off the dispatcher on purpose: this reads the registry and the file system, touches no
    /// WPF object, and is asked for while a menu is opening.
    /// </remarks>
    internal IReadOnlyList<EdaApplication> DetectedEdaApplications() =>
        _shell.DetectedEdaApplications();

    /// <summary>Open the file browser at a directory the backend resolved inside its own root.</summary>
    internal void RevealDirectory(string root, string path) =>
        _shell.RevealDirectory(root, path);

    /// <summary>Start one detected EDA application on a file inside a backend-resolved root.</summary>
    internal void OpenFileWith(string applicationId, string root, string path) =>
        _shell.OpenFileWith(applicationId, root, path);

    internal void Shutdown()
    {
        InvokeOnDispatcher(
            () =>
            {
                if (_shuttingDown)
                {
                    return;
                }

                _shuttingDown = true;
                _hidden = true;
                ResetProviderBrowser();
                _webView.Dispose();
                _window.Close();
                Application.Current.Shutdown(0);
            });
    }

    internal void BeginFailureShutdown()
    {
        _shuttingDown = true;
    }

    private void SetFailureStage(WindowHostFailureStage stage)
    {
        Volatile.Write(ref _failureExitCode, (int)stage);
    }

    private void ConfigureCoreWebView(CoreWebView2 core)
    {
        var settings = core.Settings;
        settings.AreBrowserAcceleratorKeysEnabled = false;
        settings.AreDefaultContextMenusEnabled = false;
        settings.AreDefaultScriptDialogsEnabled = false;
        settings.AreDevToolsEnabled = false;
        settings.AreHostObjectsAllowed = false;
        settings.IsBuiltInErrorPageEnabled = false;
        settings.IsGeneralAutofillEnabled = false;
        settings.IsPasswordAutosaveEnabled = false;
        settings.IsStatusBarEnabled = false;
        // The only native renderer bridge is a same-origin, exact-schema folder request. Host
        // objects remain disabled; WebMessageReceived validates the sender before showing UI.
        settings.IsWebMessageEnabled = true;
        settings.IsZoomControlEnabled = false;

        core.AddWebResourceRequestedFilter(
            new Uri(_bootstrap.BaseUri, "api/*").AbsoluteUri,
            CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += OnWebResourceRequested;
        core.WebMessageReceived += OnWebMessageReceived;
        core.NavigationStarting += OnNavigationStarting;
        core.FrameNavigationStarting += OnFrameNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.DownloadStarting += OnDownloadStarting;
        core.PermissionRequested += OnPermissionRequested;
        core.BasicAuthenticationRequested +=
            OnBasicAuthenticationRequested;
        core.ProcessFailed += OnProcessFailed;
    }

    private async Task EnsureProviderBrowserReadyAsync()
    {
        if (_providerWebView?.CoreWebView2 is not null)
        {
            return;
        }

        Exception? lastFailure = null;
        for (var attempt = 0; attempt < ProviderInitializationAttempts; attempt += 1)
        {
            ResetProviderBrowser();
            try
            {
                await InitializeProviderBrowserAttemptAsync()
                    .ConfigureAwait(true);
                SyncProviderTab();
                return;
            }
            catch (Exception exception)
            {
                lastFailure = exception;
                ResetProviderBrowser();
            }
        }

        throw new WindowHostException(
            "embedded provider browser could not be initialized",
            lastFailure
                ?? new InvalidOperationException(
                    "provider browser initialization did not report a failure"));
    }

    private async Task InitializeProviderBrowserAttemptAsync()
    {
        var providerWebView = new WebView2
        {
            AllowDrop = false,
            CreationProperties = new CoreWebView2CreationProperties(),
        };
        _providerWebView = providerWebView;
        _providerContent.Children.Add(providerWebView);
        var options = new CoreWebView2EnvironmentOptions
        {
            // Capture is leased across release activation, so only the active host initializes
            // this browser. Exclusive access keeps a second host out of the profile while the
            // stable user-data folder preserves provider sign-in state between launches. No
            // remote-debugging port is opened: nothing outside this process may drive this
            // browser, and the person operating it is the only source of input.
            ExclusiveUserDataFolderAccess = true,
        };
        var environment = await CoreWebView2Environment.CreateAsync(
                browserExecutableFolder: null,
                userDataFolder: _machineConfig.ProviderProfileDirectory(),
                options)
            .ConfigureAwait(true);
        _providerEnvironment = environment;
        environment.BrowserProcessExited += OnProviderBrowserProcessExited;
        await providerWebView.EnsureCoreWebView2Async(environment)
            .ConfigureAwait(true);
        ConfigureProviderCoreWebView(providerWebView.CoreWebView2);
        _providerSurface.Visibility = Visibility.Collapsed;
    }

    /// <summary>
    /// Keep the tab strip telling the truth about the one provider page: a tab exists exactly
    /// while an active lease has a live provider browser behind it, and it is named after the
    /// provider that lease is for.
    /// </summary>
    private void SyncProviderTab()
    {
        if (_providerLeases.TryGetActive(out var lease, out var context)
            && lease is not null
            && _providerWebView?.CoreWebView2 is not null)
        {
            _tabStrip.ShowProviderTab(ResolveProviderTabLabel(context));
            return;
        }

        _tabStrip.RemoveProviderTab();
    }

    private void UpdateProviderTabLabel()
    {
        if (!_tabStrip.HasProviderTab
            || !_providerLeases.TryGetActive(out var lease, out var context)
            || lease is null)
        {
            return;
        }

        _tabStrip.SetProviderTabLabel(ResolveProviderTabLabel(context));
    }

    private string ResolveProviderTabLabel(ProviderLeaseContext context)
    {
        var view = ActiveProviderWebView() ?? _providerWebView;
        return ProviderTabLabel.Resolve(
            context.ProviderId,
            view?.CoreWebView2?.DocumentTitle,
            view?.Source?.AbsoluteUri);
    }

    private void OnProviderUrlBoxKeyDown(object sender, KeyEventArgs eventArguments)
    {
        if (eventArguments.Key != Key.Enter)
        {
            return;
        }

        eventArguments.Handled = true;
        var typed = _tabStrip.UrlBox.Text?.Trim() ?? string.Empty;
        if (typed.Length == 0)
        {
            return;
        }

        // A bare host is a normal thing to type; everything still has to survive the same
        // top-level policy the page's own navigations do.
        if (!typed.Contains("://", StringComparison.Ordinal))
        {
            typed = "https://" + typed;
        }

        if (!ProviderNavigationPolicy.IsAllowedTopLevel(typed))
        {
            _providerNavigationError = "Provider URL Is Invalid";
            UpdateProviderChrome();
            return;
        }

        var core = ActiveProviderWebView()?.CoreWebView2;
        if (core is null)
        {
            return;
        }

        _providerNavigationError = string.Empty;
        core.Navigate(typed);
    }

    private void OnWindowPreviewKeyDown(object sender, KeyEventArgs eventArguments)
    {
        if (!_tabStrip.IsProviderSelected)
        {
            return;
        }

        var step = ProviderHistoryShortcut.Resolve(
            eventArguments.Key,
            eventArguments.SystemKey,
            Keyboard.Modifiers);
        if (step == ProviderHistoryStep.None)
        {
            return;
        }

        eventArguments.Handled = true;
        NavigateProviderHistory(back: step == ProviderHistoryStep.Back);
    }

    private void RefreshActiveProvider()
    {
        var core = ActiveProviderWebView()?.CoreWebView2;
        if (core is null)
        {
            return;
        }

        _providerNavigationError = string.Empty;
        core.Reload();
    }

    private void UpdateProviderChrome()
    {
        UpdateProviderNavigationButtons();
        UpdateProviderTabLabel();
        _tabStrip.SetStatus(
            _providerNavigationError.Length > 0
                ? _providerNavigationError
                : _providerLoading
                    ? "Loading"
                    : string.Empty);
        if (!_tabStrip.UrlBox.IsKeyboardFocusWithin)
        {
            var source = ActiveProviderWebView()?.Source?.AbsoluteUri ?? string.Empty;
            if (!source.StartsWith("about:", StringComparison.OrdinalIgnoreCase))
            {
                _tabStrip.SetUrl(source);
            }
        }
    }

    private static Grid BuildProviderSurface(out Grid providerContent)
    {
        var surface = new Grid
        {
            HorizontalAlignment = HorizontalAlignment.Left,
            VerticalAlignment = VerticalAlignment.Top,
            Background = new SolidColorBrush(Color.FromRgb(17, 21, 29)),
            Visibility = Visibility.Collapsed,
        };
        providerContent = new Grid();
        surface.Children.Add(providerContent);
        return surface;
    }

    private bool TryApplyProviderViewport()
    {
        if (_providerViewportRequest is not ProviderViewportRequest request
            || !_providerLeases.TryGetActive(out _, out var context)
            || !ProviderViewportLayout.TryResolve(
                request,
                context.ComponentId,
                _webView.ActualWidth,
                _webView.ActualHeight,
                out var layout)
            || layout is null)
        {
            return false;
        }

        _providerSurface.Margin = new Thickness(layout.X, layout.Y, 0, 0);
        _providerSurface.Width = layout.Width;
        _providerSurface.Height = layout.Height;
        return true;
    }

    private WebView2? ActiveProviderWebView()
    {
        return _providerContent.Children
            .OfType<WebView2>()
            .Reverse()
            .FirstOrDefault(view =>
                view.Visibility == Visibility.Visible
                && view.CoreWebView2 is not null);
    }

    private void NavigateProviderHistory(bool back)
    {
        var core = ActiveProviderWebView()?.CoreWebView2;
        if (core is null)
        {
            return;
        }
        if (back && core.CanGoBack)
        {
            core.GoBack();
        }
        else if (!back && core.CanGoForward)
        {
            core.GoForward();
        }
        UpdateProviderNavigationButtons();
    }

    private void UpdateProviderNavigationButtons()
    {
        var core = ActiveProviderWebView()?.CoreWebView2;
        _tabStrip.SetNavigationState(
            core?.CanGoBack == true,
            core?.CanGoForward == true);
    }

    private void ConfigureProviderCoreWebView(CoreWebView2 core)
    {
        var settings = core.Settings;
        settings.AreBrowserAcceleratorKeysEnabled = true;
        settings.AreDefaultContextMenusEnabled = true;
        settings.AreDefaultScriptDialogsEnabled = true;
        settings.AreDevToolsEnabled = false;
        settings.AreHostObjectsAllowed = false;
        settings.IsBuiltInErrorPageEnabled = true;
        settings.IsGeneralAutofillEnabled = true;
        settings.IsPasswordAutosaveEnabled = true;
        settings.IsStatusBarEnabled = false;
        settings.IsWebMessageEnabled = false;
        settings.IsZoomControlEnabled = true;
        core.NavigationStarting += OnProviderNavigationStarting;
        core.NavigationCompleted += OnProviderNavigationCompleted;
        core.SourceChanged += OnProviderSourceChanged;
        core.DocumentTitleChanged += OnProviderDocumentTitleChanged;
        core.HistoryChanged += OnProviderHistoryChanged;
        core.NewWindowRequested += OnProviderNewWindowRequested;
        core.DownloadStarting += OnProviderDownloadStarting;
        core.IsDefaultDownloadDialogOpenChanged +=
            OnProviderDefaultDownloadDialogOpenChanged;
        core.PermissionRequested += OnProviderPermissionRequested;
        core.BasicAuthenticationRequested +=
            OnBasicAuthenticationRequested;
        core.ProcessFailed += OnProviderProcessFailed;
    }

    private void OnProviderDocumentTitleChanged(object? sender, object eventArguments)
    {
        _ = sender;
        _ = eventArguments;
        // Only ever a fallback: a lease that names its provider keeps that name regardless of
        // what the page retitles itself to mid-flow.
        UpdateProviderTabLabel();
    }

    private void OnProviderHistoryChanged(object? sender, object eventArguments)
    {
        _ = sender;
        _ = eventArguments;
        UpdateProviderNavigationButtons();
    }

    private void OnProviderNavigationStarting(
        object? sender,
        CoreWebView2NavigationStartingEventArgs eventArguments)
    {
        if (!ProviderNavigationPolicy.IsAllowedTopLevel(eventArguments.Uri))
        {
            eventArguments.Cancel = true;
            return;
        }

        _providerLoading = true;
        _providerNavigationError = string.Empty;
        UpdateProviderChrome();
    }

    private void OnProviderNavigationCompleted(
        object? sender,
        CoreWebView2NavigationCompletedEventArgs eventArguments)
    {
        _providerLoading = false;
        // ConnectionAborted is the person cancelling or leaving mid-load - not a page
        // failure worth an error banner. Everything else is surfaced plainly; the built-in
        // error page still renders inside the view for detail.
        if (!eventArguments.IsSuccess
            && eventArguments.WebErrorStatus
                != CoreWebView2WebErrorStatus.ConnectionAborted)
        {
            _providerNavigationError = string.Create(
                CultureInfo.InvariantCulture,
                $"Page Failed To Load ({eventArguments.WebErrorStatus})");
        }

        UpdateProviderChrome();
    }

    private void OnProviderSourceChanged(
        object? sender,
        CoreWebView2SourceChangedEventArgs eventArguments)
    {
        _ = eventArguments;
        UpdateProviderChrome();
    }

    private async void OnProviderNewWindowRequested(
        object? sender,
        CoreWebView2NewWindowRequestedEventArgs eventArguments)
    {
        // Consumed before anything is decided: whatever follows, this request does not reach the
        // Windows shell and therefore cannot become a page in the person's own browser.
        eventArguments.Handled = true;
        var hasLease = _providerLeases.TryGetActive(out var lease) && lease is not null;
        var environment = _providerEnvironment;
        switch (ProviderNewWindowPolicy.Resolve(
            eventArguments.Uri,
            hasLease,
            canCreatePopup: environment is not null))
        {
            case ProviderNewWindowAction.Refuse:
                return;
            case ProviderNewWindowAction.NavigateInPlace:
                NavigateActiveProviderInPlace(eventArguments.Uri);
                return;
        }

        var deferral = eventArguments.GetDeferral();
        WebView2? popup = null;
        try
        {
            // Preserve real popup/opener semantics for OAuth while keeping the entire flow inside
            // Stockroom. The popup shares only the provider profile/environment and is stacked over
            // the originating page; unsafe schemes were consumed before this point.
            popup = new WebView2
            {
                AllowDrop = false,
                CreationProperties = new CoreWebView2CreationProperties(),
            };
            _providerPopups.Add(popup, lease!);
            _providerContent.Children.Add(popup);
            await popup.EnsureCoreWebView2Async(environment)
                .ConfigureAwait(true);
            ConfigureProviderCoreWebView(popup.CoreWebView2);
            popup.CoreWebView2.WindowCloseRequested +=
                OnProviderPopupCloseRequested;
            eventArguments.NewWindow = popup.CoreWebView2;
        }
        catch
        {
            if (popup is not null)
            {
                RemoveProviderPopup(popup);
            }

            // The popup could not be built. The person still clicked a link, so honour it in the
            // page they are already on rather than dropping the click on the floor.
            if (ProviderNewWindowPolicy.Resolve(
                    eventArguments.Uri,
                    hasLease,
                    canCreatePopup: false)
                == ProviderNewWindowAction.NavigateInPlace)
            {
                NavigateActiveProviderInPlace(eventArguments.Uri);
            }
        }
        finally
        {
            deferral.Complete();
        }
    }

    /// <summary>
    /// Send the open provider view to <paramref name="uri"/> itself: same window, same lease, same
    /// download journal. Nothing about the lease changes, because looking at another page of the
    /// same provider is not another piece of work.
    /// </summary>
    private void NavigateActiveProviderInPlace(string? uri)
    {
        var core = ActiveProviderWebView()?.CoreWebView2;
        if (core is null || !ProviderNavigationPolicy.IsNavigableInPlace(uri))
        {
            return;
        }

        _providerNavigationError = string.Empty;
        core.Navigate(uri!);
    }

    private void OnProviderPopupCloseRequested(object? sender, object eventArguments)
    {
        _ = eventArguments;
        var popup = _providerPopups.Keys.FirstOrDefault(
            candidate => ReferenceEquals(candidate.CoreWebView2, sender));
        if (popup is not null)
        {
            RemoveProviderPopup(popup);
        }
    }

    private void RemoveProviderPopup(WebView2 popup)
    {
        if (!_providerPopups.Remove(popup))
        {
            return;
        }
        if (popup.CoreWebView2 is CoreWebView2 core)
        {
            core.WindowCloseRequested -= OnProviderPopupCloseRequested;
            core.ProcessFailed -= OnProviderProcessFailed;
        }
        _providerContent.Children.Remove(popup);
        popup.Dispose();
    }

    private void OnProviderDownloadStarting(
        object? sender,
        CoreWebView2DownloadStartingEventArgs eventArguments)
    {
        eventArguments.Handled = true;
        SuppressProviderDownloadDialogs();
        if (!_providerLeases.TryGetActive(out var lease, out var context) || lease is null)
        {
            eventArguments.Cancel = true;
            return;
        }

        var operation = eventArguments.DownloadOperation;
        var operationId = Guid.NewGuid().ToString("D", CultureInfo.InvariantCulture);
        // Resolved once, from the evidence available before the destination is rewritten, and
        // carried verbatim through every event. Sanitizing happens only on the way to disk.
        var suggestedFileName = ProviderDownloadName.Resolve(
            operation.ContentDisposition ?? string.Empty,
            operation.Uri ?? string.Empty,
            operation.ResultFilePath ?? string.Empty);
        if (!ProviderDownloadStaging.TryResolveDestination(
                context.StagingRoot,
                operationId,
                suggestedFileName,
                out var destination))
        {
            // No proven Stockroom-owned destination means no download. The person's Downloads
            // folder is not an acceptable fallback for untrusted provider bytes.
            eventArguments.Cancel = true;
            return;
        }

        try
        {
            Directory.CreateDirectory(Path.GetDirectoryName(destination)!);
            eventArguments.ResultFilePath = destination;
        }
        catch (Exception exception) when (
            exception is IOException
                or UnauthorizedAccessException
                or ArgumentException
                or NotSupportedException)
        {
            eventArguments.Cancel = true;
            return;
        }

        RecordProviderDownload(
            lease,
            context,
            operationId,
            "started",
            operation,
            suggestedFileName);

        var throttle = new ProviderDownloadProgressThrottle(Environment.TickCount64);
        var terminalRecorded = false;
        EventHandler<object>? bytesReceivedChanged = null;
        EventHandler<object>? stateChanged = null;
        bytesReceivedChanged = (_, _) =>
        {
            if (terminalRecorded
                || !throttle.TryAcquire(
                    Environment.TickCount64,
                    checked((long)operation.BytesReceived),
                    ProviderDownloadTotalBytes(operation)))
            {
                return;
            }
            RecordProviderDownload(
                lease,
                context,
                operationId,
                "progress",
                operation,
                suggestedFileName);
        };
        stateChanged = (_, _) =>
        {
            if (operation.State is not (
                CoreWebView2DownloadState.Completed
                or CoreWebView2DownloadState.Interrupted))
            {
                return;
            }
            if (terminalRecorded)
            {
                return;
            }
            terminalRecorded = true;
            operation.StateChanged -= stateChanged;
            operation.BytesReceivedChanged -= bytesReceivedChanged;
            // One last progress entry regardless of the throttle, so a reader always sees the
            // final byte count as progress immediately before the terminal entry.
            RecordProviderDownload(
                lease,
                context,
                operationId,
                "progress",
                operation,
                suggestedFileName);
            RecordProviderDownload(
                lease,
                context,
                operationId,
                "terminal",
                operation,
                suggestedFileName);
            SuppressProviderDownloadDialogs();
        };
        operation.BytesReceivedChanged += bytesReceivedChanged;
        operation.StateChanged += stateChanged;
        if (operation.State is CoreWebView2DownloadState.Completed
            or CoreWebView2DownloadState.Interrupted)
        {
            stateChanged(operation, EventArgs.Empty);
        }
    }

    private static void OnProviderDefaultDownloadDialogOpenChanged(
        object? sender,
        object eventArguments)
    {
        _ = eventArguments;
        if (sender is not CoreWebView2 core || !core.IsDefaultDownloadDialogOpen)
        {
            return;
        }

        // DownloadStarting.Handled suppresses the normal path, but Browser-domain capture can
        // make WebView2 announce the transient GUID target a moment later. Close it on the exact
        // state transition instead of waiting for a timer to notice an already-visible flyout.
        core.CloseDefaultDownloadDialog();
    }

    private async void SuppressProviderDownloadDialogs()
    {
        // Browser-domain interception names the transient file by GUID. WebView2 can open its
        // default tray after DownloadStarting returns, and a child provider WebView can own that
        // tray even when the root received the event. Poll every lease-owned WebView for a short,
        // bounded window and close only the tray; the download operation and broker remain live.
        for (var attempt = 0; attempt < 30 && !_shuttingDown; attempt += 1)
        {
            foreach (var providerView in _providerContent.Children.OfType<WebView2>().ToArray())
            {
                if (providerView.CoreWebView2 is not CoreWebView2 core)
                {
                    continue;
                }
                try
                {
                    if (core.IsDefaultDownloadDialogOpen)
                    {
                        core.CloseDefaultDownloadDialog();
                    }
                }
                catch (InvalidOperationException)
                {
                    // This provider WebView closed between enumeration and inspection.
                }
            }
            await Task.Delay(100).ConfigureAwait(true);
        }
    }

    private void RecordProviderDownload(
        ProviderLeaseIdentity lease,
        ProviderLeaseContext context,
        string operationId,
        string phase,
        CoreWebView2DownloadOperation operation,
        string suggestedFileName)
    {
        _providerLeases.Record(
            lease,
            context,
            operationId,
            phase,
            ProviderDownloadStateName(operation.State),
            operation.Uri ?? string.Empty,
            suggestedFileName,
            operation.ResultFilePath ?? string.Empty,
            operation.MimeType ?? string.Empty,
            operation.State == CoreWebView2DownloadState.Interrupted
                ? operation.InterruptReason.ToString()
                : string.Empty,
            ProviderDownloadTotalBytes(operation),
            checked((long)operation.BytesReceived));
    }

    private static long ProviderDownloadTotalBytes(
        CoreWebView2DownloadOperation operation) =>
        operation.TotalBytesToReceive is ulong totalBytes
            && totalBytes <= long.MaxValue
                ? (long)totalBytes
                : -1;

    private static string ProviderDownloadStateName(CoreWebView2DownloadState state) =>
        state switch
        {
            CoreWebView2DownloadState.InProgress => "in_progress",
            CoreWebView2DownloadState.Completed => "completed",
            CoreWebView2DownloadState.Interrupted => "interrupted",
            _ => "unknown",
        };

    private static void OnProviderPermissionRequested(
        object? sender,
        CoreWebView2PermissionRequestedEventArgs eventArguments)
    {
        eventArguments.State = CoreWebView2PermissionState.Deny;
        eventArguments.SavesInProfile = false;
    }

    private void OnProviderProcessFailed(
        object? sender,
        CoreWebView2ProcessFailedEventArgs eventArguments)
    {
        _ = eventArguments;
        var belongsToProvider =
            _providerWebView?.CoreWebView2 is CoreWebView2 current
            && ReferenceEquals(sender, current);
        belongsToProvider = belongsToProvider
            || _providerPopups.Keys.Any(
                popup => ReferenceEquals(
                    popup.CoreWebView2,
                    sender));
        if (!belongsToProvider)
        {
            return;
        }
        _window.Dispatcher.BeginInvoke(ResetProviderBrowser);
    }

    private void OnProviderBrowserProcessExited(
        object? sender,
        CoreWebView2BrowserProcessExitedEventArgs eventArguments)
    {
        _ = eventArguments;
        if (!ReferenceEquals(sender, _providerEnvironment))
        {
            return;
        }
        _window.Dispatcher.BeginInvoke(ResetProviderBrowser);
    }

    private void ResetProviderBrowser()
    {
        _tabStrip.RemoveProviderTab();
        _providerSurface.Visibility = Visibility.Collapsed;
        _webView.Visibility = Visibility.Visible;
        foreach (var popup in _providerPopups.Keys.ToArray())
        {
            RemoveProviderPopup(popup);
        }
        var providerWebView = _providerWebView;
        _providerWebView = null;
        if (providerWebView is not null)
        {
            if (providerWebView.CoreWebView2 is CoreWebView2 core)
            {
                core.ProcessFailed -= OnProviderProcessFailed;
            }
            _providerContent.Children.Remove(providerWebView);
            providerWebView.Dispose();
        }
        if (_providerEnvironment is not null)
        {
            _providerEnvironment.BrowserProcessExited -=
                OnProviderBrowserProcessExited;
            _providerEnvironment = null;
        }
    }

    private async Task AddMachineUiBootstrapAsync(CoreWebView2 core)
    {
        var themeJson = JsonSerializer.Serialize(
            _machineConfig.Theme);
        var script = string.Create(
            CultureInfo.InvariantCulture,
            $$"""
              (() => {
                const theme = {{themeJson}};
                const current =
                  window.__STOCKROOM_UI__ &&
                  typeof window.__STOCKROOM_UI__ === "object"
                    ? window.__STOCKROOM_UI__
                    : {};
                window.__STOCKROOM_UI__ = Object.freeze({
                  ...current,
                  theme
                });
                const webview = globalThis.chrome?.webview;
                if (webview && typeof webview.postMessage === "function") {
                  const pending = new Map();
                  webview.addEventListener("message", (event) => {
                    const value = event.data;
                    if (
                      !value ||
                      (value.schema !== "stockroom.host.folder-result" &&
                       value.schema !== "stockroom.host.file-result") ||
                      typeof value.id !== "string" ||
                      !Array.isArray(value.paths) ||
                      !value.paths.every((path) => typeof path === "string")
                    ) return;
                    const request = pending.get(value.id);
                    if (!request || value.schema !== request.expectedSchema) return;
                    pending.delete(value.id);
                    clearTimeout(request.timer);
                    if (typeof value.error === "string" && value.error) {
                      request.reject(new Error(value.error));
                    } else {
                      request.resolve(value.paths);
                    }
                  });
                  window.__STOCKROOM_HOST__ = Object.freeze({
                    pickFolder(purpose) {
                      if (purpose !== "project" && purpose !== "stm-cubemx") {
                        return Promise.reject(new Error("Unknown Stockroom folder purpose."));
                      }
                      const id = crypto.randomUUID();
                      return new Promise((resolve, reject) => {
                        const timer = setTimeout(() => {
                          pending.delete(id);
                          reject(new Error("The Stockroom folder picker did not respond."));
                        }, 300000);
                        pending.set(id, {
                          resolve,
                          reject,
                          timer,
                          expectedSchema: "stockroom.host.folder-result"
                        });
                        webview.postMessage({
                          schema: "stockroom.host.folder-request",
                          id,
                          purpose
                        });
                      });
                    },
                    pickFiles(purpose) {
                      if (purpose !== "cad-recovery") {
                        return Promise.reject(new Error("Unknown Stockroom file purpose."));
                      }
                      const id = crypto.randomUUID();
                      return new Promise((resolve, reject) => {
                        const timer = setTimeout(() => {
                          pending.delete(id);
                          reject(new Error("The Stockroom file picker did not respond."));
                        }, 300000);
                        pending.set(id, {
                          resolve,
                          reject,
                          timer,
                          expectedSchema: "stockroom.host.file-result"
                        });
                        webview.postMessage({
                          schema: "stockroom.host.file-request",
                          id,
                          purpose
                        });
                      });
                    },
                    setProviderViewport(viewport) {
                      if (
                        !viewport ||
                        typeof viewport.componentId !== "string" ||
                        typeof viewport.visible !== "boolean" ||
                        ![viewport.x, viewport.y, viewport.width, viewport.height]
                          .every(Number.isFinite)
                      ) {
                        throw new Error("Invalid provider viewport.");
                      }
                      webview.postMessage({
                        schema: "stockroom.host.provider-viewport",
                        component_id: viewport.componentId,
                        visible: viewport.visible,
                        x: viewport.x,
                        y: viewport.y,
                        width: viewport.width,
                        height: viewport.height
                      });
                    },
                    providerCommand(request) {
                      if (
                        !request ||
                        typeof request.componentId !== "string" ||
                        !["back", "forward", "reload", "close"].includes(request.command)
                      ) {
                        throw new Error("Invalid provider browser command.");
                      }
                      webview.postMessage({
                        schema: "stockroom.host.provider-command",
                        component_id: request.componentId,
                        command: request.command
                      });
                    }
                  });
                }
                document.documentElement.dataset.theme = theme;
              })();
              """);
        _ = await core.AddScriptToExecuteOnDocumentCreatedAsync(
                script)
            .ConfigureAwait(true);
    }

    private async Task<RendererReadiness>
        RunAuthenticatedRendererProbesAsync(
        CoreWebView2 core)
    {
        var nonce = JsonSerializer.Serialize(_probeNonce);
        var releaseId = JsonSerializer.Serialize(
            _bootstrap.ReleaseId);
        var script = $$"""
            void (async () => {
              const nonce = {{nonce}};
              const expectedRelease = {{releaseId}};
              const publish = (apiHealthy, streamHealthy) => {
                window.__STOCKROOM_NATIVE_PROBE_RESULT__ = {
                  schema: "stockroom.window-host-probe",
                  nonce,
                  api_healthy: apiHealthy,
                  event_stream_healthy: streamHealthy
                };
              };
              window.__STOCKROOM_NATIVE_PROBE_RESULT__ = null;
              const run = async (suffix, accept) => {
                const response = await fetch(
                  `/api/system/identity?window-host-probe=${suffix}`,
                  {
                    cache: "no-store",
                    credentials: "same-origin",
                    headers: { Accept: accept }
                  }
                );
                if (!response.ok || !response.body) {
                  return { api: false, stream: false };
                }
                const reader = response.body.getReader();
                const decoder = new TextDecoder();
                let body = "";
                let chunkCount = 0;
                let bytes = 0;
                for (;;) {
                  const next = await reader.read();
                  if (next.done) break;
                  chunkCount += 1;
                  bytes += next.value.byteLength;
                  if (bytes > 65536) {
                    await reader.cancel();
                    return { api: false, stream: false };
                  }
                  body += decoder.decode(next.value, { stream: true });
                }
                body += decoder.decode();
                const identity = JSON.parse(body);
                return {
                  api: identity.release_id === expectedRelease,
                  stream: chunkCount > 0 && bytes > 0
                };
              };
              try {
                const api = await run("api", "application/json");
                const stream = await run(
                  "stream",
                  "text/event-stream"
                );
                publish(
                  api.api,
                  stream.api && stream.stream
                );
              } catch {
                publish(false, false);
              }
            })();
            """;
        _ = await core.ExecuteScriptAsync(script)
            .ConfigureAwait(true);
        while (true)
        {
            var encoded = await core.ExecuteScriptAsync(
                    "window.__STOCKROOM_NATIVE_PROBE_RESULT__ ?? null")
                .ConfigureAwait(true);
            using var document = JsonDocument.Parse(encoded);
            if (document.RootElement.ValueKind == JsonValueKind.Null)
            {
                await Task.Delay(50).ConfigureAwait(true);
                continue;
            }

            var readiness = ParseRendererProbe(
                document.RootElement);
            _ = await core.ExecuteScriptAsync(
                    "delete window.__STOCKROOM_NATIVE_PROBE_RESULT__")
                .ConfigureAwait(true);
            return readiness;
        }
    }

    private RendererReadiness ParseRendererProbe(
        JsonElement root)
    {
        HandoffCodec.RequireExactObject(
            root,
            "renderer probe",
            "schema",
            "nonce",
            "api_healthy",
            "event_stream_healthy");
        if (HandoffCodec.GetRequiredString(
                root,
                "schema")
            != "stockroom.window-host-probe"
            || HandoffCodec.GetRequiredString(
                root,
                "nonce")
            != _probeNonce
            || root.GetProperty("api_healthy").ValueKind
                is not (JsonValueKind.True or JsonValueKind.False)
            || root.GetProperty("event_stream_healthy").ValueKind
                is not (JsonValueKind.True or JsonValueKind.False))
        {
            throw new WindowHostException(
                "renderer readiness proof is invalid");
        }

        return new RendererReadiness(
            root.GetProperty("api_healthy").GetBoolean(),
            root.GetProperty("event_stream_healthy")
                .GetBoolean());
    }

    private void OnWebResourceRequested(
        object? sender,
        CoreWebView2WebResourceRequestedEventArgs eventArguments)
    {
        if (_shuttingDown
            || !OriginPolicy.IsApiRequest(
                eventArguments.Request.Uri,
                _bootstrap.BaseUri))
        {
            return;
        }

        var credential = _bootstrap.ApiCredential
            .CreateEphemeralString();
        eventArguments.Request.Headers.SetHeader(
            "Authorization",
            "Bearer " + credential);
    }

    private void OnWebMessageReceived(
        object? sender,
        CoreWebView2WebMessageReceivedEventArgs eventArguments)
    {
        if (sender is not CoreWebView2 core
            || !OriginPolicy.IsAllowedNavigation(
                eventArguments.Source,
                _bootstrap.BaseUri))
        {
            return;
        }

        string id;
        string purpose;
        var fileRequest = false;
        try
        {
            using var document = JsonDocument.Parse(
                eventArguments.WebMessageAsJson);
            var root = document.RootElement;
            if (root.TryGetProperty("schema", out var commandSchema)
                && commandSchema.ValueKind == JsonValueKind.String
                && commandSchema.GetString() == "stockroom.host.provider-command")
            {
                HandoffCodec.RequireExactObject(
                    root,
                    "provider browser command",
                    "schema",
                    "component_id",
                    "command");
                var componentId = HandoffCodec.GetRequiredString(root, "component_id");
                var commandValue = HandoffCodec.GetRequiredString(root, "command");
                if (!_providerLeases.TryGetActive(out _, out var activeContext)
                    || !string.Equals(
                        componentId,
                        activeContext.ComponentId,
                        StringComparison.Ordinal))
                {
                    return;
                }
                if (!ProviderBrowserCommandCodec.TryParse(commandValue, out var command))
                {
                    return;
                }
                switch (command)
                {
                    case ProviderBrowserCommand.Back:
                        NavigateProviderHistory(back: true);
                        break;
                    case ProviderBrowserCommand.Forward:
                        NavigateProviderHistory(back: false);
                        break;
                    case ProviderBrowserCommand.Reload:
                        RefreshActiveProvider();
                        break;
                    case ProviderBrowserCommand.Close:
                        ShowStockroomTab();
                        break;
                }
                return;
            }
            if (root.TryGetProperty("schema", out var viewportSchema)
                && viewportSchema.ValueKind == JsonValueKind.String
                && viewportSchema.GetString() == "stockroom.host.provider-viewport")
            {
                HandoffCodec.RequireExactObject(
                    root,
                    "provider viewport request",
                    "schema",
                    "component_id",
                    "visible",
                    "x",
                    "y",
                    "width",
                    "height");
                if (!root.TryGetProperty("visible", out var visible)
                    || visible.ValueKind is not (JsonValueKind.True or JsonValueKind.False))
                {
                    return;
                }
                var request = new ProviderViewportRequest(
                    HandoffCodec.GetRequiredString(root, "component_id"),
                    visible.GetBoolean(),
                    RequiredFiniteDouble(root, "x"),
                    RequiredFiniteDouble(root, "y"),
                    RequiredFiniteDouble(root, "width"),
                    RequiredFiniteDouble(root, "height"));
                _providerViewportRequest = request;
                if (!request.Visible || !TryApplyProviderViewport())
                {
                    _providerSurface.Visibility = Visibility.Collapsed;
                    _webView.Visibility = Visibility.Visible;
                }
                else if (_providerSurface.Visibility == Visibility.Visible)
                {
                    _webView.Visibility = Visibility.Visible;
                }
                return;
            }
            HandoffCodec.RequireExactObject(
                root,
                "renderer picker request",
                "schema",
                "id",
                "purpose");
            var schema = HandoffCodec.GetRequiredString(root, "schema");
            if (schema is not (
                    "stockroom.host.folder-request" or
                    "stockroom.host.file-request"))
            {
                return;
            }
            fileRequest = schema == "stockroom.host.file-request";
            id = HandoffCodec.GetRequiredString(root, "id");
            purpose = HandoffCodec.GetRequiredString(root, "purpose");
            if (!Guid.TryParseExact(id, "D", out _)
                || (fileRequest
                    ? purpose != "cad-recovery"
                    : purpose is not ("project" or "stm-cubemx")))
            {
                return;
            }
        }
        catch (Exception exception)
            when (exception is JsonException or WindowHostException)
        {
            return;
        }

        var paths = Array.Empty<string>();
        var error = "";
        try
        {
            if (fileRequest)
            {
                var dialog = new OpenFileDialog
                {
                    Multiselect = true,
                    Title = "Choose Downloaded CAD Files",
                    Filter = "CAD files|*.zip;*.kicad_sym;*.kicad_mod;*.step;*.stp;*.SchLib;*.PcbLib|All files|*.*",
                };
                if (dialog.ShowDialog(_window) == true)
                {
                    paths = dialog.FileNames
                        .Select(Path.GetFullPath)
                        .ToArray();
                }
            }
            else
            {
                var dialog = new OpenFolderDialog
                {
                    Multiselect = false,
                    Title = purpose == "project"
                        ? "Choose A Project Folder"
                        : "Choose The STM32CubeMX Folder",
                };
                if (dialog.ShowDialog(_window) == true
                    && !string.IsNullOrWhiteSpace(dialog.FolderName))
                {
                    paths = [Path.GetFullPath(dialog.FolderName)];
                }
            }
        }
        catch (Exception exception)
            when (exception is IOException
                or UnauthorizedAccessException
                or ArgumentException
                or InvalidOperationException)
        {
            error = "Stockroom could not open the Windows picker.";
        }

        core.PostWebMessageAsJson(
            JsonSerializer.Serialize(
                new Dictionary<string, object?>
                {
                    ["schema"] = fileRequest
                        ? "stockroom.host.file-result"
                        : "stockroom.host.folder-result",
                    ["id"] = id,
                    ["paths"] = paths,
                    ["error"] = error,
                }));
    }

    private static double RequiredFiniteDouble(JsonElement root, string name)
    {
        if (!root.TryGetProperty(name, out var value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetDouble(out var result)
            || !double.IsFinite(result))
        {
            throw new WindowHostException($"{name} is invalid");
        }
        return result;
    }

    private void OnNavigationStarting(
        object? sender,
        CoreWebView2NavigationStartingEventArgs eventArguments)
    {
        if (!OriginPolicy.IsAllowedNavigation(
                eventArguments.Uri,
                _bootstrap.BaseUri))
        {
            eventArguments.Cancel = true;
            SignalFatal(
                new WindowHostException(
                    "top-level navigation left the Stockroom origin"));
        }
    }

    private void OnFrameNavigationStarting(
        object? sender,
        CoreWebView2NavigationStartingEventArgs eventArguments)
    {
        if (!OriginPolicy.IsAllowedNavigation(
                eventArguments.Uri,
                _bootstrap.BaseUri))
        {
            eventArguments.Cancel = true;
        }
    }

    private static void OnNewWindowRequested(
        object? sender,
        CoreWebView2NewWindowRequestedEventArgs eventArguments)
    {
        eventArguments.Handled = true;
    }

    private static void OnDownloadStarting(
        object? sender,
        CoreWebView2DownloadStartingEventArgs eventArguments)
    {
        eventArguments.Cancel = true;
        eventArguments.Handled = true;
    }

    private static void OnPermissionRequested(
        object? sender,
        CoreWebView2PermissionRequestedEventArgs eventArguments)
    {
        eventArguments.State = CoreWebView2PermissionState.Deny;
        eventArguments.SavesInProfile = false;
    }

    private static void OnBasicAuthenticationRequested(
        object? sender,
        CoreWebView2BasicAuthenticationRequestedEventArgs eventArguments)
    {
        eventArguments.Cancel = true;
    }

    private void OnProcessFailed(
        object? sender,
        CoreWebView2ProcessFailedEventArgs eventArguments)
    {
        SignalFatal(
            new WindowHostException(
                "WebView2 process failed"));
    }

    private void OnBrowserProcessExited(
        object? sender,
        CoreWebView2BrowserProcessExitedEventArgs eventArguments)
    {
        if (!_shuttingDown)
        {
            SignalFatal(
                new WindowHostException(
                    "WebView2 browser process exited"));
        }
    }

    private void OnNavigationCompleted(
        object? sender,
        CoreWebView2NavigationCompletedEventArgs eventArguments)
    {
        if (!eventArguments.IsSuccess
            || !OriginPolicy.IsAllowedNavigation(
                _webView.Source?.AbsoluteUri,
                _bootstrap.BaseUri))
        {
            _navigationCompletion.TrySetException(
                new WindowHostException(
                    "Stockroom navigation failed"));
            return;
        }

        _navigationCompletion.TrySetResult(true);
    }

    private void OnWindowClosing(
        object? sender,
        CancelEventArgs eventArguments)
    {
        if (_shuttingDown)
        {
            return;
        }

        eventArguments.Cancel = true;
        if (WindowClosePolicy.ShouldRequestClose(
                _initialized,
                _hidden,
                _shuttingDown))
        {
            _closeRequested = true;
        }
    }

    private void SignalFatal(Exception exception)
    {
        if (_shuttingDown || _fatalException is not null)
        {
            return;
        }

        _fatalException = exception;
        _navigationCompletion.TrySetException(exception);
        _fatalFailure();
    }

    private void ThrowIfNotReady()
    {
        ThrowIfFatal();
        if (!_initialized
            || _readiness is null
            || !_readiness.ApiHealthy
            || !_readiness.EventStreamHealthy)
        {
            throw new WindowHostException(
                "native window is not ready");
        }
    }

    private void ThrowIfFatal()
    {
        if (_fatalException is not null)
        {
            throw new WindowHostException(
                "native window is unhealthy",
                _fatalException);
        }
    }

    private void InvokeOnDispatcher(Action operation)
    {
        _window.Dispatcher.Invoke(operation);
    }

    private T InvokeOnDispatcher<T>(Func<T> operation)
    {
        return _window.Dispatcher.Invoke(operation);
    }

    private T InvokeOnDispatcher<T>(Func<Task<T>> operation)
    {
        return _window.Dispatcher
            .InvokeAsync(operation)
            .Task
            .Unwrap()
            .GetAwaiter()
            .GetResult();
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _shuttingDown = true;
        if (_environment is not null)
        {
            _environment.BrowserProcessExited -=
                OnBrowserProcessExited;
        }

        ResetProviderBrowser();
        _webView.Dispose();
    }
}

internal static class ProviderNavigationPolicy
{
    internal static bool IsAllowedTopLevel(string? value)
    {
        if (!Uri.TryCreate(value, UriKind.Absolute, out var uri)
            || !string.IsNullOrEmpty(uri.UserInfo))
        {
            return false;
        }
        if (uri.Scheme == "about"
            && string.Equals(uri.AbsolutePath, "blank", StringComparison.Ordinal))
        {
            return true;
        }
        return uri.Scheme == Uri.UriSchemeHttps
            && !string.IsNullOrWhiteSpace(uri.IdnHost);
    }

    /// <summary>
    /// Whether a page is a real destination the open provider view can simply go to.
    /// </summary>
    /// <remarks>
    /// <c>about:blank</c> passes <see cref="IsAllowedTopLevel"/> because a script legitimately
    /// opens one and writes into it, but navigating the page a person is working on to a blank
    /// document is not honouring their click - it is losing it.
    /// </remarks>
    internal static bool IsNavigableInPlace(string? value) =>
        Uri.TryCreate(value, UriKind.Absolute, out var uri)
        && string.IsNullOrEmpty(uri.UserInfo)
        && uri.Scheme == Uri.UriSchemeHttps
        && !string.IsNullOrWhiteSpace(uri.IdnHost);
}

internal enum ProviderNewWindowAction
{
    /// <summary>Consumed and dropped. Never passed on to the operating system.</summary>
    Refuse,

    /// <summary>A real popup over the same page, which is what an OAuth window needs to be.</summary>
    Popup,

    /// <summary>The open provider view goes there itself, under the same lease.</summary>
    NavigateInPlace,
}

/// <summary>
/// What happens when a provider page asks for a new window.
///
/// The one invariant: never the operating system's browser. A link out of a provider page must
/// stay inside Stockroom, because a page opened in Chrome is a page whose downloads no longer
/// belong to a lease and no longer reach the journal that proves which component a file is for.
/// So every outcome here is inside this window, and the last resort is refusal rather than
/// handing the string to whatever program claims the scheme.
///
/// A popup is preferred while one can be built: real opener semantics are what carries a provider
/// sign-in through. When one cannot be built, the click is still honoured - the open provider view
/// navigates there itself - instead of being swallowed, which is how a person ends up clicking a
/// link repeatedly and watching nothing happen.
/// </summary>
internal static class ProviderNewWindowPolicy
{
    internal static ProviderNewWindowAction Resolve(
        string? uri,
        bool hasActiveLease,
        bool canCreatePopup)
    {
        if (!hasActiveLease
            || !ProviderNavigationPolicy.IsAllowedTopLevel(uri))
        {
            return ProviderNewWindowAction.Refuse;
        }
        if (canCreatePopup)
        {
            return ProviderNewWindowAction.Popup;
        }
        return ProviderNavigationPolicy.IsNavigableInPlace(uri)
            ? ProviderNewWindowAction.NavigateInPlace
            : ProviderNewWindowAction.Refuse;
    }
}

internal enum ProviderHistoryStep
{
    None,
    Back,
    Forward,
}

/// <summary>
/// Alt+Left and Alt+Right, the two keys a person already has in their hands for a browser.
/// </summary>
/// <remarks>
/// WPF reports a modified arrow key as <see cref="Key.System"/> and carries the real key in
/// <c>SystemKey</c>, so both are read. Alt alone qualifies: Ctrl+Alt+Left and Shift+Alt+Left mean
/// other things on Windows and must not be claimed here.
/// </remarks>
internal static class ProviderHistoryShortcut
{
    internal static ProviderHistoryStep Resolve(
        Key key,
        Key systemKey,
        ModifierKeys modifiers)
    {
        if (modifiers != ModifierKeys.Alt)
        {
            return ProviderHistoryStep.None;
        }
        var effective = key == Key.System ? systemKey : key;
        return effective switch
        {
            Key.Left => ProviderHistoryStep.Back,
            Key.Right => ProviderHistoryStep.Forward,
            _ => ProviderHistoryStep.None,
        };
    }
}

internal static class WindowClosePolicy
{
    internal static bool ShouldRequestClose(
        bool initialized,
        bool hidden,
        bool shuttingDown) =>
        initialized && !hidden && !shuttingDown;
}

internal static class SnapshotSanitizer
{
    private static readonly string[] SensitiveNameFragments =
    [
        "token",
        "secret",
        "password",
        "credential",
        "api_key",
        "apikey",
    ];

    internal static void RequireNonSecret(
        JsonElement value,
        SensitiveCredential apiCredential,
        SensitiveCredential handoffCredential)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                foreach (var property in value.EnumerateObject())
                {
                    var normalized = property.Name.ToLowerInvariant();
                    if (SensitiveNameFragments.Any(
                            normalized.Contains))
                    {
                        throw new WindowHostException(
                            "renderer export contains a sensitive field");
                    }

                    RequireNonSecret(
                        property.Value,
                        apiCredential,
                        handoffCredential);
                }

                break;
            case JsonValueKind.Array:
                foreach (var item in value.EnumerateArray())
                {
                    RequireNonSecret(
                        item,
                        apiCredential,
                        handoffCredential);
                }

                break;
            case JsonValueKind.String:
            {
                var bytes = Encoding.UTF8.GetBytes(
                    value.GetString() ?? string.Empty);
                try
                {
                    if (apiCredential.OccursIn(bytes)
                        || handoffCredential.OccursIn(bytes))
                    {
                        throw new WindowHostException(
                            "renderer export contains a credential");
                    }
                }
                finally
                {
                    CryptographicOperations.ZeroMemory(bytes);
                }

                break;
            }
        }
    }
}
