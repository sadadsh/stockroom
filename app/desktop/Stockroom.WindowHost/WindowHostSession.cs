using System.Text.Json;

namespace Stockroom.WindowHost;

internal interface IWindowHostController
{
    long WindowHandle { get; }

    string ProfileId { get; }

    void PrepareHidden(long deadlineUnixMilliseconds);

    void Show();

    void Focus();

    IReadOnlyDictionary<string, object?> Health();

    IReadOnlyDictionary<string, object?> ExportSession();

    IReadOnlyDictionary<string, object?> BeginProviderLease(
        string leaseId,
        ProviderLeaseContext context);

    bool ReleaseProviderLease(string leaseId, long generation);

    IReadOnlyList<ProviderDownloadEvent> ProviderDownloadEvents(
        string leaseId,
        long generation,
        long afterSequence);

    void ShowProviderBrowser(string leaseId, long generation);

    void HideProviderBrowser(string leaseId, long generation);

    string ProviderCurrentUrl(string leaseId, long generation);

    void NavigateProviderBrowser(string leaseId, long generation, string url);

    void RefreshProviderBrowser(string leaseId, long generation);

    IReadOnlyDictionary<string, object?> ProviderState(string leaseId, long generation);

    IReadOnlyDictionary<string, object?> ProviderDocumentState(
        string leaseId,
        long generation,
        IReadOnlyList<string> readySelectors,
        IReadOnlyList<string> readyTexts);

    void Shutdown();
}

internal sealed class WebViewWindowController : IWindowHostController
{
    private readonly WebViewWindowHost _host;

    internal WebViewWindowController(
        WebViewWindowHost host,
        string profileId)
    {
        _host = host ?? throw new ArgumentNullException(nameof(host));
        ProfileId = profileId;
    }

    public long WindowHandle => _host.WindowHandle.ToInt64();

    public string ProfileId { get; }

    public void PrepareHidden(long deadlineUnixMilliseconds) =>
        _host.PrepareHidden(deadlineUnixMilliseconds);

    public void Show() => _host.Show();

    public void Focus() => _host.Focus();

    public IReadOnlyDictionary<string, object?> Health() =>
        _host.Health();

    public IReadOnlyDictionary<string, object?> ExportSession() =>
        _host.ExportSession();

    public IReadOnlyDictionary<string, object?> BeginProviderLease(
        string leaseId,
        ProviderLeaseContext context) =>
        _host.BeginProviderLease(leaseId, context);

    public bool ReleaseProviderLease(string leaseId, long generation) =>
        _host.ReleaseProviderLease(leaseId, generation);

    public IReadOnlyList<ProviderDownloadEvent> ProviderDownloadEvents(
        string leaseId,
        long generation,
        long afterSequence) =>
        _host.ProviderDownloadEvents(leaseId, generation, afterSequence);

    public void ShowProviderBrowser(string leaseId, long generation) =>
        _host.ShowProviderBrowser(leaseId, generation);

    public void HideProviderBrowser(string leaseId, long generation) =>
        _host.HideProviderBrowser(leaseId, generation);

    public string ProviderCurrentUrl(string leaseId, long generation) =>
        _host.ProviderCurrentUrl(leaseId, generation);

    public void NavigateProviderBrowser(string leaseId, long generation, string url) =>
        _host.NavigateProviderBrowser(leaseId, generation, url);

    public void RefreshProviderBrowser(string leaseId, long generation) =>
        _host.RefreshProviderBrowser(leaseId, generation);

    public IReadOnlyDictionary<string, object?> ProviderState(
        string leaseId,
        long generation) =>
        _host.ProviderState(leaseId, generation);

    public IReadOnlyDictionary<string, object?> ProviderDocumentState(
        string leaseId,
        long generation,
        IReadOnlyList<string> readySelectors,
        IReadOnlyList<string> readyTexts) =>
        _host.ProviderDocumentState(leaseId, generation, readySelectors, readyTexts);

    public void Shutdown() => _host.Shutdown();
}

internal sealed class WindowHostSession
{
    private static readonly string[] Commands =
    [
        "prepare-hidden",
        "show",
        "focus",
        "health",
        "export",
        "provider-lease-begin",
        "provider-lease-release",
        "provider-download-events",
        "provider-show",
        "provider-hide",
        "provider-current-url",
        "provider-navigate",
        "provider-refresh",
        "provider-state",
        "provider-document-state",
        "shutdown",
    ];

    private readonly HandoffChannel _channel;
    private readonly HandoffBootstrap _bootstrap;
    private readonly IWindowHostController _controller;
    private readonly uint _parentProcessId;
    private readonly uint _childProcessId;
    private readonly Func<long> _clock;
    private bool _prepared;
    private bool _visible;

    internal WindowHostSession(
        HandoffChannel channel,
        HandoffBootstrap bootstrap,
        IWindowHostController controller,
        uint parentProcessId,
        uint childProcessId,
        Func<long>? clock = null)
    {
        _channel = channel
            ?? throw new ArgumentNullException(nameof(channel));
        _bootstrap = bootstrap
            ?? throw new ArgumentNullException(nameof(bootstrap));
        _controller = controller
            ?? throw new ArgumentNullException(nameof(controller));
        _parentProcessId = parentProcessId;
        _childProcessId = childProcessId;
        _clock = clock
            ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    internal void Run()
    {
        if (_controller.WindowHandle <= 0
            || _parentProcessId == 0
            || _childProcessId == 0)
        {
            throw new WindowHostException(
                "window-host identity is invalid");
        }

        var helloSequence = _channel.Send(
            "hello-hidden",
            new Dictionary<string, object?>
            {
                ["request_sequence"] = 1,
                ["result"] = new Dictionary<string, object?>
                {
                    ["release_id"] = _bootstrap.ReleaseId,
                    ["process_id"] = _childProcessId,
                    ["parent_process_id"] = _parentProcessId,
                    ["window_handle"] = _controller.WindowHandle,
                    ["profile_id"] = _controller.ProfileId,
                    ["renderer"] = "edgechromium",
                    ["hidden"] = true,
                    ["proof"] = _bootstrap.CreateProof(
                        _parentProcessId,
                        _childProcessId),
                },
            },
            _bootstrap.ApiCredential,
            _bootstrap.HandoffCredential);
        if (helloSequence != 1)
        {
            throw new WindowHostException(
                "window-host hello sequence is invalid");
        }

        while (true)
        {
            var request = _channel.Receive(Commands);
            if (request.Payload.ValueKind != JsonValueKind.Object)
            {
                throw new WindowHostException(
                    $"{request.Name} payload has invalid fields");
            }

            try
            {
                var response = ExecuteCommand(request);
                if (_clock() > request.DeadlineUnixMilliseconds)
                {
                    throw new WindowHostException(
                        $"window-host command '{request.Name}' exceeded its deadline");
                }

                _channel.Send(
                    response.Name,
                    ResponsePayload(
                        request.Sequence,
                        response.Result),
                    _bootstrap.ApiCredential,
                    _bootstrap.HandoffCredential);
                if (request.Name == "shutdown")
                {
                    _controller.Shutdown();
                    return;
                }
            }
            catch (Exception exception)
            {
                try
                {
                    _channel.Send(
                        "command-error",
                        ResponsePayload(
                            request.Sequence,
                            new Dictionary<string, object?>
                            {
                                ["command"] = request.Name,
                                ["code"] =
                                    "candidate-command-failed",
                            }),
                        _bootstrap.ApiCredential,
                        _bootstrap.HandoffCredential);
                }
                catch
                {
                    // The exact child will be reaped by the stable supervisor.
                }

                throw new WindowHostException(
                    $"window-host command '{request.Name}' failed",
                    exception);
            }
        }
    }

    private (string Name, IReadOnlyDictionary<string, object?> Result)
        ExecuteCommand(HandoffMessage request)
    {
        if (request.Name is not "provider-navigate"
            and not "provider-document-state"
            and not "provider-lease-begin"
            and not "provider-lease-release"
            and not "provider-download-events"
            and not "provider-show"
            and not "provider-hide"
            and not "provider-current-url"
            and not "provider-refresh"
            and not "provider-state"
            && request.Payload.EnumerateObject().Any())
        {
            throw new WindowHostException(
                $"{request.Name} payload has invalid fields");
        }
        return request.Name switch
        {
            "prepare-hidden" => PrepareHidden(request),
            "show" => Show(),
            "focus" => Focus(),
            "health" => (
                "health",
                _controller.Health()),
            "export" => Export(),
            "provider-lease-begin" => ProviderLeaseBegin(request),
            "provider-lease-release" => ProviderLeaseRelease(request),
            "provider-download-events" => ProviderDownloadEvents(request),
            "provider-show" => ProviderShow(request),
            "provider-hide" => ProviderHide(request),
            "provider-current-url" => ProviderCurrentUrl(request),
            "provider-navigate" => ProviderNavigate(request),
            "provider-refresh" => ProviderRefresh(request),
            "provider-state" => ProviderState(request),
            "provider-document-state" => ProviderDocumentState(request),
            "shutdown" => (
                "stopping",
                new Dictionary<string, object?>
                {
                    ["stopping"] = true,
                }),
            _ => throw new WindowHostException(
                "window-host command is unsupported"),
        };
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        PrepareHidden(HandoffMessage request)
    {
        _controller.PrepareHidden(
            request.DeadlineUnixMilliseconds);
        _prepared = true;
        _visible = false;
        return (
            "prepared-hidden",
            new Dictionary<string, object?>
            {
                ["hidden"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        Show()
    {
        if (!_prepared)
        {
            throw new WindowHostException(
                "show requires a prepared hidden window");
        }

        _controller.Show();
        _visible = true;
        return (
            "shown",
            new Dictionary<string, object?>
            {
                ["visible"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        Focus()
    {
        if (!_visible)
        {
            throw new WindowHostException(
                "focus requires a visible window");
        }

        _controller.Focus();
        return (
            "focused",
            new Dictionary<string, object?>
            {
                ["focused"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        Export()
    {
        if (!_prepared)
        {
            throw new WindowHostException(
                "export requires a prepared window");
        }

        return (
            "exported",
            new Dictionary<string, object?>
            {
                ["snapshot"] = _controller.ExportSession(),
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderLeaseBegin(HandoffMessage request)
    {
        HandoffCodec.RequireExactObject(
            request.Payload,
            "provider lease begin",
            "lease_id",
            "staging_root",
            "component_id",
            "manufacturer",
            "mpn",
            "provider_id");
        var leaseId = HandoffCodec.GetRequiredString(request.Payload, "lease_id");
        var context = new ProviderLeaseContext(
            HandoffCodec.GetRequiredString(request.Payload, "staging_root"),
            HandoffCodec.GetRequiredString(request.Payload, "component_id"),
            HandoffCodec.GetRequiredString(request.Payload, "manufacturer"),
            HandoffCodec.GetRequiredString(request.Payload, "mpn"),
            HandoffCodec.GetRequiredString(request.Payload, "provider_id"));
        return (
            "provider-lease-begun",
            _controller.BeginProviderLease(leaseId, context));
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderLeaseRelease(HandoffMessage request)
    {
        var lease = ParseProviderLease(request.Payload, "provider lease release");
        return (
            "provider-lease-released",
            new Dictionary<string, object?>
            {
                ["lease_id"] = lease.LeaseId,
                ["generation"] = lease.Generation,
                ["released"] = _controller.ReleaseProviderLease(
                    lease.LeaseId,
                    lease.Generation),
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderDownloadEvents(HandoffMessage request)
    {
        HandoffCodec.RequireExactObject(
            request.Payload,
            "provider download events",
            "lease_id",
            "generation",
            "after_sequence");
        var lease = ParseProviderLease(request.Payload, "provider download events", exact: false);
        var afterSequence = RequiredInt64(request.Payload, "after_sequence");
        var events = _controller.ProviderDownloadEvents(
            lease.LeaseId,
            lease.Generation,
            afterSequence);
        return (
            "provider-download-events",
            new Dictionary<string, object?>
            {
                ["lease_id"] = lease.LeaseId,
                ["generation"] = lease.Generation,
                ["events"] = events.Select(SerializeProviderDownloadEvent).ToArray(),
            });
    }

    private static ProviderLeaseIdentity ParseProviderLease(
        JsonElement payload,
        string label,
        bool exact = true)
    {
        if (exact)
        {
            HandoffCodec.RequireExactObject(payload, label, "lease_id", "generation");
        }
        var leaseId = HandoffCodec.GetRequiredString(payload, "lease_id");
        var generation = RequiredInt64(payload, "generation");
        if (generation <= 0)
        {
            throw new WindowHostException("provider lease generation is invalid");
        }
        return new ProviderLeaseIdentity(leaseId, generation);
    }

    private static long RequiredInt64(JsonElement payload, string name)
    {
        if (!payload.TryGetProperty(name, out var value)
            || value.ValueKind != JsonValueKind.Number
            || !value.TryGetInt64(out var result))
        {
            throw new WindowHostException($"{name} is invalid");
        }
        return result;
    }

    private static IReadOnlyDictionary<string, object?> SerializeProviderDownloadEvent(
        ProviderDownloadEvent item) =>
        new Dictionary<string, object?>
        {
            ["sequence"] = item.Sequence,
            ["lease_id"] = item.LeaseId,
            ["generation"] = item.Generation,
            ["component_id"] = item.ComponentId,
            ["manufacturer"] = item.Manufacturer,
            ["mpn"] = item.Mpn,
            ["provider_id"] = item.ProviderId,
            ["operation_id"] = item.OperationId,
            ["phase"] = item.Phase,
            ["state"] = item.State,
            ["uri"] = item.Uri,
            ["suggested_file_name"] = item.SuggestedFileName,
            ["result_file_path"] = item.ResultFilePath,
            ["mime_type"] = item.MimeType,
            ["interrupt_reason"] = item.InterruptReason,
            ["total_bytes"] = item.TotalBytes,
            ["bytes_received"] = item.BytesReceived,
        };

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderShow(HandoffMessage request)
    {
        if (!_visible)
        {
            throw new WindowHostException(
                "provider browser requires a visible Stockroom window");
        }
        var lease = ParseProviderLease(request.Payload, "provider show");
        _controller.ShowProviderBrowser(lease.LeaseId, lease.Generation);
        return (
            "provider-shown",
            new Dictionary<string, object?>
            {
                ["visible"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderHide(HandoffMessage request)
    {
        var lease = ParseProviderLease(request.Payload, "provider hide");
        _controller.HideProviderBrowser(lease.LeaseId, lease.Generation);
        return (
            "provider-hidden",
            new Dictionary<string, object?>
            {
                ["visible"] = false,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderCurrentUrl(HandoffMessage request)
    {
        var lease = ParseProviderLease(request.Payload, "provider current URL");
        return (
            "provider-current-url",
            new Dictionary<string, object?>
            {
                ["url"] = _controller.ProviderCurrentUrl(
                    lease.LeaseId,
                    lease.Generation),
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderNavigate(HandoffMessage request)
    {
        HandoffCodec.RequireExactObject(
            request.Payload,
            "provider navigate",
            "lease_id",
            "generation",
            "url");
        var lease = ParseProviderLease(request.Payload, "provider navigate", exact: false);
        var url = HandoffCodec.GetRequiredString(request.Payload, "url");
        _controller.NavigateProviderBrowser(lease.LeaseId, lease.Generation, url);
        return (
            "provider-navigated",
            new Dictionary<string, object?>
            {
                ["navigated"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderRefresh(HandoffMessage request)
    {
        var lease = ParseProviderLease(request.Payload, "provider refresh");
        _controller.RefreshProviderBrowser(lease.LeaseId, lease.Generation);
        return (
            "provider-refreshed",
            new Dictionary<string, object?>
            {
                ["refreshed"] = true,
            });
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderState(HandoffMessage request)
    {
        var lease = ParseProviderLease(request.Payload, "provider state");
        return (
            "provider-state",
            _controller.ProviderState(lease.LeaseId, lease.Generation));
    }

    private (
        string Name,
        IReadOnlyDictionary<string, object?> Result)
        ProviderDocumentState(HandoffMessage request)
    {
        HandoffCodec.RequireExactObject(
            request.Payload,
            "provider document state",
            "lease_id",
            "generation",
            "ready_selectors",
            "ready_texts");
        var lease = ParseProviderLease(
            request.Payload,
            "provider document state",
            exact: false);
        var selectors = RequiredStringArray(request.Payload, "ready_selectors");
        var texts = RequiredStringArray(request.Payload, "ready_texts");
        return (
            "provider-document-state",
            _controller.ProviderDocumentState(
                lease.LeaseId,
                lease.Generation,
                selectors,
                texts));
    }

    private static IReadOnlyList<string> RequiredStringArray(
        JsonElement payload,
        string name)
    {
        if (!payload.TryGetProperty(name, out var value)
            || value.ValueKind != JsonValueKind.Array)
        {
            throw new WindowHostException($"{name} is invalid");
        }
        var result = new List<string>();
        foreach (var item in value.EnumerateArray())
        {
            if (item.ValueKind != JsonValueKind.String)
            {
                throw new WindowHostException($"{name} is invalid");
            }
            var text = item.GetString() ?? string.Empty;
            if (text.Length > 512 || text.Any(char.IsControl))
            {
                throw new WindowHostException($"{name} is invalid");
            }
            result.Add(text);
        }
        if (result.Count > 64)
        {
            throw new WindowHostException($"{name} is invalid");
        }
        return result;
    }

    private static IReadOnlyDictionary<string, object?> ResponsePayload(
        long requestSequence,
        IReadOnlyDictionary<string, object?> result) =>
        new Dictionary<string, object?>
        {
            ["request_sequence"] = requestSequence,
            ["result"] = result,
        };
}
