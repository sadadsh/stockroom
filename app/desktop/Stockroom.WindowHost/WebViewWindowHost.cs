using System.ComponentModel;
using System.Globalization;
using System.IO;
using System.Net;
using System.Net.Http;
using System.Net.Sockets;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Controls;
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
    private const int ProviderProbeTimeoutSeconds = 10;
    private const int MaximumProviderProbeBytes = 256 * 1024;

    private readonly HandoffBootstrap _bootstrap;
    private readonly MachineWindowConfig _machineConfig;
    private readonly Action _fatalFailure;
    private readonly Window _window;
    private readonly WebView2 _webView;
    private readonly Grid _root;
    private readonly Grid _providerSurface;
    private readonly Grid _providerContent;
    private readonly HashSet<WebView2> _providerPopups = [];
    private readonly TaskCompletionSource<bool> _navigationCompletion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly string _probeNonce;

    private CoreWebView2Environment? _environment;
    private CoreWebView2Environment? _providerEnvironment;
    private WebView2? _providerWebView;
    private int _providerCdpPort;
    private readonly string _providerProbeNonce;
    private IntPtr _windowHandle;
    private ResolvedWindowGeometry? _resolvedGeometry;
    private RendererReadiness? _readiness;
    private Exception? _fatalException;
    private bool _initialized;
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
        _providerProbeNonce = Convert.ToHexStringLower(
            RandomNumberGenerator.GetBytes(16));
        _webView = new WebView2
        {
            AllowDrop = false,
            CreationProperties = new CoreWebView2CreationProperties(),
        };
        _root = new Grid();
        _root.Children.Add(_webView);
        _providerSurface = BuildProviderSurface(
            HideProviderBrowser,
            out _providerContent);
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

    internal int ProviderCdpPort()
    {
        return InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                await EnsureProviderBrowserReadyAsync()
                    .ConfigureAwait(true);
                if (_providerCdpPort is < 1 or > 65535)
                {
                    throw new WindowHostException(
                        "provider browser endpoint is unavailable");
                }

                return _providerCdpPort;
            });
    }

    internal void ShowProviderBrowser()
    {
        InvokeOnDispatcher(
            async () =>
            {
                ThrowIfNotReady();
                await EnsureProviderBrowserReadyAsync()
                    .ConfigureAwait(true);
                _webView.Visibility = Visibility.Collapsed;
                _providerSurface.Visibility = Visibility.Visible;
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
                _providerSurface.Visibility = Visibility.Collapsed;
                _webView.Visibility = Visibility.Visible;
                _webView.Focus();
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
        if (_providerWebView?.CoreWebView2 is not null
            && _providerCdpPort is > 0 and <= 65535)
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
                return;
            }
            catch (Exception exception)
            {
                lastFailure = exception;
                ResetProviderBrowser();
            }
        }

        throw new WindowHostException(
            "embedded provider browser could not prove its local automation endpoint",
            lastFailure
                ?? new InvalidOperationException(
                    "provider browser initialization did not report a failure"));
    }

    private async Task InitializeProviderBrowserAttemptAsync()
    {
        _providerCdpPort = ReserveLoopbackPort();
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
            // this browser. A fresh port per host avoids stale or foreign CDP ownership while the
            // stable user-data folder preserves provider sign-in state between launches.
            ExclusiveUserDataFolderAccess = true,
            AdditionalBrowserArguments = string.Create(
                CultureInfo.InvariantCulture,
                $"--remote-debugging-port={_providerCdpPort}"),
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
        var markerUrl = $"about:blank#stockroom-provider-{_providerProbeNonce}";
        await NavigateProviderAsync(providerWebView, markerUrl)
            .ConfigureAwait(true);
        await VerifyProviderCdpEndpointAsync(
                _providerCdpPort,
                markerUrl)
            .ConfigureAwait(true);
        _providerSurface.Visibility = Visibility.Collapsed;
    }

    private static int ReserveLoopbackPort()
    {
        var listener = new TcpListener(IPAddress.Loopback, 0);
        try
        {
            listener.Start();
            return ((IPEndPoint)listener.LocalEndpoint).Port;
        }
        finally
        {
            listener.Stop();
        }
    }

    private static Grid BuildProviderSurface(
        Action hideProviderBrowser,
        out Grid providerContent)
    {
        var surface = new Grid
        {
            Background = new SolidColorBrush(Color.FromArgb(224, 9, 12, 18)),
            Visibility = Visibility.Collapsed,
        };
        var panel = new Grid
        {
            Margin = new Thickness(24),
            Background = new SolidColorBrush(Color.FromRgb(17, 21, 29)),
        };
        panel.RowDefinitions.Add(
            new RowDefinition { Height = new GridLength(44) });
        panel.RowDefinitions.Add(
            new RowDefinition { Height = new GridLength(1, GridUnitType.Star) });
        var header = new Grid();
        header.ColumnDefinitions.Add(
            new ColumnDefinition { Width = new GridLength(1, GridUnitType.Star) });
        header.ColumnDefinitions.Add(
            new ColumnDefinition { Width = GridLength.Auto });
        var title = new TextBlock
        {
            Text = "STOCKROOM  /  PROVIDER BROWSER",
            Foreground = new SolidColorBrush(Color.FromRgb(205, 214, 225)),
            FontFamily = new FontFamily("Segoe UI Semibold"),
            FontSize = 12,
            VerticalAlignment = VerticalAlignment.Center,
            Margin = new Thickness(16, 0, 0, 0),
        };
        var close = new Button
        {
            Content = "Return To Stockroom",
            Foreground = new SolidColorBrush(Color.FromRgb(205, 214, 225)),
            Background = new SolidColorBrush(Color.FromRgb(27, 33, 44)),
            BorderBrush = new SolidColorBrush(Color.FromRgb(55, 65, 81)),
            FontFamily = new FontFamily("Segoe UI Semibold"),
            FontSize = 11,
            Padding = new Thickness(10, 4, 10, 4),
            Margin = new Thickness(0, 7, 10, 7),
            VerticalAlignment = VerticalAlignment.Center,
        };
        close.Click += (_, _) => hideProviderBrowser();
        Grid.SetColumn(title, 0);
        Grid.SetColumn(close, 1);
        header.Children.Add(title);
        header.Children.Add(close);
        Grid.SetRow(header, 0);
        panel.Children.Add(header);
        providerContent = new Grid();
        Grid.SetRow(providerContent, 1);
        panel.Children.Add(providerContent);
        surface.Children.Add(panel);
        return surface;
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
        core.NewWindowRequested += OnProviderNewWindowRequested;
        core.PermissionRequested += OnProviderPermissionRequested;
        core.BasicAuthenticationRequested +=
            OnBasicAuthenticationRequested;
        core.ProcessFailed += OnProviderProcessFailed;
    }

    private static void OnProviderNavigationStarting(
        object? sender,
        CoreWebView2NavigationStartingEventArgs eventArguments)
    {
        if (!ProviderNavigationPolicy.IsAllowedTopLevel(eventArguments.Uri))
        {
            eventArguments.Cancel = true;
        }
    }

    private async void OnProviderNewWindowRequested(
        object? sender,
        CoreWebView2NewWindowRequestedEventArgs eventArguments)
    {
        eventArguments.Handled = true;
        if (!ProviderNavigationPolicy.IsAllowedTopLevel(eventArguments.Uri)
            || _providerEnvironment is not CoreWebView2Environment environment)
        {
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
            _providerPopups.Add(popup);
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
        }
        finally
        {
            deferral.Complete();
        }
    }

    private void OnProviderPopupCloseRequested(object? sender, object eventArguments)
    {
        _ = eventArguments;
        var popup = _providerPopups.FirstOrDefault(
            candidate => ReferenceEquals(
                candidate.CoreWebView2,
                sender));
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

    private static void OnProviderPermissionRequested(
        object? sender,
        CoreWebView2PermissionRequestedEventArgs eventArguments)
    {
        eventArguments.State = CoreWebView2PermissionState.Deny;
        eventArguments.SavesInProfile = false;
    }

    private async Task NavigateProviderAsync(
        WebView2 providerWebView,
        string markerUrl)
    {
        var completion = new TaskCompletionSource<bool>(
            TaskCreationOptions.RunContinuationsAsynchronously);
        void Completed(
            object? sender,
            CoreWebView2NavigationCompletedEventArgs eventArguments)
        {
            if (eventArguments.IsSuccess)
            {
                completion.TrySetResult(true);
            }
            else
            {
                completion.TrySetException(
                    new WindowHostException(
                        "provider browser marker navigation failed"));
            }
        }

        providerWebView.CoreWebView2.NavigationCompleted += Completed;
        try
        {
            providerWebView.Source = new Uri(markerUrl, UriKind.Absolute);
            await completion.Task.WaitAsync(
                    TimeSpan.FromSeconds(ProviderProbeTimeoutSeconds))
                .ConfigureAwait(true);
        }
        finally
        {
            providerWebView.CoreWebView2.NavigationCompleted -= Completed;
        }
    }

    private static async Task VerifyProviderCdpEndpointAsync(
        int port,
        string markerUrl)
    {
        using var handler = new SocketsHttpHandler
        {
            UseProxy = false,
        };
        using var client = new HttpClient(handler)
        {
            Timeout = TimeSpan.FromMilliseconds(500),
        };
        var deadline = DateTimeOffset.UtcNow
            + TimeSpan.FromSeconds(ProviderProbeTimeoutSeconds);
        Exception? lastFailure = null;
        while (DateTimeOffset.UtcNow < deadline)
        {
            try
            {
                var version = await ReadProviderProbeAsync(
                        client,
                        $"http://127.0.0.1:{port}/json/version")
                    .ConfigureAwait(true);
                ProviderCdpProof.RequireVersion(version, port);
                var targets = await ReadProviderProbeAsync(
                        client,
                        $"http://127.0.0.1:{port}/json/list")
                    .ConfigureAwait(true);
                ProviderCdpProof.RequireOwnedTarget(targets, markerUrl);
                return;
            }
            catch (Exception exception)
                when (exception is HttpRequestException
                    or TaskCanceledException
                    or JsonException
                    or WindowHostException)
            {
                lastFailure = exception;
                await Task.Delay(50).ConfigureAwait(true);
            }
        }

        throw new WindowHostException(
            "provider browser CDP endpoint did not prove ownership",
            lastFailure
                ?? new InvalidOperationException(
                    "provider browser CDP probe did not report a failure"));
    }

    private static async Task<byte[]> ReadProviderProbeAsync(
        HttpClient client,
        string url)
    {
        using var response = await client.GetAsync(
                url,
                HttpCompletionOption.ResponseHeadersRead)
            .ConfigureAwait(true);
        response.EnsureSuccessStatusCode();
        var length = response.Content.Headers.ContentLength;
        if (length is > MaximumProviderProbeBytes)
        {
            throw new WindowHostException(
                "provider browser CDP response is too large");
        }
        var bytes = await response.Content.ReadAsByteArrayAsync()
            .ConfigureAwait(true);
        if (bytes.Length is 0 or > MaximumProviderProbeBytes)
        {
            throw new WindowHostException(
                "provider browser CDP response is invalid");
        }
        return bytes;
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
            || _providerPopups.Any(
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
        _providerSurface.Visibility = Visibility.Collapsed;
        _webView.Visibility = Visibility.Visible;
        foreach (var popup in _providerPopups.ToArray())
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
        _providerCdpPort = 0;
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
}

internal static class ProviderCdpProof
{
    internal static void RequireVersion(ReadOnlySpan<byte> document, int expectedPort)
    {
        using var parsed = JsonDocument.Parse(document.ToArray());
        var root = parsed.RootElement;
        if (root.ValueKind != JsonValueKind.Object
            || !root.TryGetProperty("Browser", out var browser)
            || browser.ValueKind != JsonValueKind.String
            || string.IsNullOrWhiteSpace(browser.GetString())
            || !root.TryGetProperty(
                "webSocketDebuggerUrl",
                out var rawWebSocket)
            || rawWebSocket.ValueKind != JsonValueKind.String
            || !Uri.TryCreate(
                rawWebSocket.GetString(),
                UriKind.Absolute,
                out var webSocket)
            || webSocket.Scheme != "ws"
            || !IsLoopbackHost(webSocket.Host)
            || webSocket.Port != expectedPort)
        {
            throw new WindowHostException(
                "provider browser CDP version proof is invalid");
        }
    }

    private static bool IsLoopbackHost(string host)
    {
        return string.Equals(
                host,
                "localhost",
                StringComparison.OrdinalIgnoreCase)
            || (IPAddress.TryParse(host, out var address)
                && IPAddress.IsLoopback(address));
    }

    internal static void RequireOwnedTarget(
        ReadOnlySpan<byte> document,
        string expectedUrl)
    {
        using var parsed = JsonDocument.Parse(document.ToArray());
        var root = parsed.RootElement;
        if (root.ValueKind != JsonValueKind.Array
            || !root.EnumerateArray().Any(
                item => item.ValueKind == JsonValueKind.Object
                    && item.TryGetProperty("type", out var type)
                    && type.ValueKind == JsonValueKind.String
                    && type.GetString() == "page"
                    && item.TryGetProperty("url", out var url)
                    && url.ValueKind == JsonValueKind.String
                    && url.GetString() == expectedUrl))
        {
            throw new WindowHostException(
                "provider browser CDP target ownership proof is invalid");
        }
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
