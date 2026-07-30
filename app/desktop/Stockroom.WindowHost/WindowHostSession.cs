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
            if (request.Payload.ValueKind != JsonValueKind.Object
                || request.Payload.EnumerateObject().Any())
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
        return request.Name switch
        {
            "prepare-hidden" => PrepareHidden(request),
            "show" => Show(),
            "focus" => Focus(),
            "health" => (
                "health",
                _controller.Health()),
            "export" => Export(),
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

    private static IReadOnlyDictionary<string, object?> ResponsePayload(
        long requestSequence,
        IReadOnlyDictionary<string, object?> result) =>
        new Dictionary<string, object?>
        {
            ["request_sequence"] = requestSequence,
            ["result"] = result,
        };
}
