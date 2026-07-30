using System.ComponentModel;
using System.Globalization;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Windows;
using System.Windows.Interop;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.Wpf;

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

    private readonly HandoffBootstrap _bootstrap;
    private readonly MachineWindowConfig _machineConfig;
    private readonly Action _fatalFailure;
    private readonly Window _window;
    private readonly WebView2 _webView;
    private readonly TaskCompletionSource<bool> _navigationCompletion =
        new(TaskCreationOptions.RunContinuationsAsynchronously);
    private readonly string _probeNonce;

    private CoreWebView2Environment? _environment;
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
        _webView = new WebView2
        {
            AllowDrop = false,
            CreationProperties = new CoreWebView2CreationProperties(),
        };
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
            Content = _webView,
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
        settings.IsWebMessageEnabled = false;
        settings.IsZoomControlEnabled = false;

        core.AddWebResourceRequestedFilter(
            new Uri(_bootstrap.BaseUri, "api/*").AbsoluteUri,
            CoreWebView2WebResourceContext.All);
        core.WebResourceRequested += OnWebResourceRequested;
        core.NavigationStarting += OnNavigationStarting;
        core.FrameNavigationStarting += OnFrameNavigationStarting;
        core.NewWindowRequested += OnNewWindowRequested;
        core.DownloadStarting += OnDownloadStarting;
        core.PermissionRequested += OnPermissionRequested;
        core.BasicAuthenticationRequested +=
            OnBasicAuthenticationRequested;
        core.ProcessFailed += OnProcessFailed;
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

        _webView.Dispose();
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
