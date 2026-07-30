using System.Buffers.Binary;
using System.Text.Json;

namespace Stockroom.WindowHost.Tests;

public sealed class WindowHostSessionTests
{
    private const long Now = 1_800_000_000_000;

    [Fact]
    public void RunsTheExactHiddenFirstCommandAndExportContract()
    {
        var incoming = Concatenate(
            Frame(HandoffProtocolTests.PythonCanonicalBootstrap()),
            HandoffProtocolTests.BuildMessage(
                2,
                "prepare-hidden",
                Now + 30_000,
                new Dictionary<string, object?>()),
            HandoffProtocolTests.BuildMessage(
                3,
                "health",
                Now + 30_000,
                new Dictionary<string, object?>()),
            HandoffProtocolTests.BuildMessage(
                4,
                "export",
                Now + 30_000,
                new Dictionary<string, object?>()),
            HandoffProtocolTests.BuildMessage(
                5,
                "show",
                Now + 30_000,
                new Dictionary<string, object?>()),
            HandoffProtocolTests.BuildMessage(
                6,
                "focus",
                Now + 30_000,
                new Dictionary<string, object?>()),
            HandoffProtocolTests.BuildMessage(
                7,
                "shutdown",
                Now + 30_000,
                new Dictionary<string, object?>()));
        using var stream = new ScriptedDuplexStream(incoming);
        using var channel = new HandoffChannel(stream, () => Now);
        var bootstrapMessage = channel.Receive("bootstrap");
        using var bootstrap = BootstrapParser.Parse(
            bootstrapMessage);
        var controller = new FakeController();
        var session = new WindowHostSession(
            channel,
            bootstrap,
            controller,
            111,
            222);

        session.Run();

        Assert.Equal(
            [
                "prepare-hidden",
                "health",
                "export",
                "show",
                "focus",
                "shutdown",
            ],
            controller.Operations);
        var responses = DecodeFrames(stream.Written);
        Assert.Equal(
            [
                "hello-hidden",
                "prepared-hidden",
                "health",
                "exported",
                "shown",
                "focused",
                "stopping",
            ],
            responses.Select(static item => item.Name));
        Assert.Equal(
            Enumerable.Range(1, 7).Select(static item => (long)item),
            responses.Select(static item => item.Sequence));

        var hello = responses[0].Payload.GetProperty("result");
        Assert.True(hello.GetProperty("hidden").GetBoolean());
        Assert.Equal("edgechromium", hello.GetProperty("renderer").GetString());
        Assert.Equal(
            "f33b8f59bf565ab02d36f3d7087a30002fe8ca6a81431911bfd94c681879e1ba",
            hello.GetProperty("proof").GetString());
        var health = responses[2].Payload.GetProperty("result");
        Assert.Equal(
            new[]
            {
                "close_requested",
                "current_url",
                "hidden",
                "hwnd",
                "renderer",
                "visible",
            },
            health.EnumerateObject()
                .Select(static item => item.Name)
                .Order(StringComparer.Ordinal));
        Assert.False(
            health.GetProperty("close_requested").GetBoolean());
        var snapshot = responses[3]
            .Payload
            .GetProperty("result")
            .GetProperty("snapshot");
        Assert.Equal(
            new[]
            {
                "api_healthy",
                "event_stream_healthy",
                "geometry",
                "theme",
                "ui_export",
            },
            snapshot.EnumerateObject()
                .Select(static item => item.Name)
                .Order(StringComparer.Ordinal));
        Assert.True(snapshot.GetProperty("api_healthy").GetBoolean());
        Assert.True(
            snapshot.GetProperty("event_stream_healthy").GetBoolean());
        Assert.Equal(
            "stockroom.window-geometry",
            snapshot
                .GetProperty("geometry")
                .GetProperty("schema")
                .GetString());
        Assert.True(controller.ShutdownCalled);
    }

    [Fact]
    public void RejectsVisibilityCommitBeforeHiddenPreparation()
    {
        var incoming = Concatenate(
            Frame(HandoffProtocolTests.PythonCanonicalBootstrap()),
            HandoffProtocolTests.BuildMessage(
                2,
                "show",
                Now + 30_000,
                new Dictionary<string, object?>()));
        using var stream = new ScriptedDuplexStream(incoming);
        using var channel = new HandoffChannel(stream, () => Now);
        using var bootstrap = BootstrapParser.Parse(
            channel.Receive("bootstrap"));
        var session = new WindowHostSession(
            channel,
            bootstrap,
            new FakeController(),
            111,
            222);

        Assert.Throws<WindowHostException>(() => session.Run());

        var responses = DecodeFrames(stream.Written);
        Assert.Equal(
            ["hello-hidden", "command-error"],
            responses.Select(static item => item.Name));
        Assert.Equal(
            "candidate-command-failed",
            responses[1]
                .Payload
                .GetProperty("result")
                .GetProperty("code")
                .GetString());
    }

    [Fact]
    public void FailsClosedWhenACommandCompletesAfterItsDeadline()
    {
        var incoming = Concatenate(
            Frame(HandoffProtocolTests.PythonCanonicalBootstrap()),
            HandoffProtocolTests.BuildMessage(
                2,
                "prepare-hidden",
                Now + 30_000,
                new Dictionary<string, object?>()));
        using var stream = new ScriptedDuplexStream(incoming);
        using var channel = new HandoffChannel(stream, () => Now);
        using var bootstrap = BootstrapParser.Parse(
            channel.Receive("bootstrap"));
        var controller = new FakeController();
        var session = new WindowHostSession(
            channel,
            bootstrap,
            controller,
            111,
            222,
            () => Now + 30_001);

        Assert.Throws<WindowHostException>(() => session.Run());

        Assert.Equal(["prepare-hidden"], controller.Operations);
        var responses = DecodeFrames(stream.Written);
        Assert.Equal(
            ["hello-hidden", "command-error"],
            responses.Select(static item => item.Name));
    }

    private static byte[] Frame(byte[] body)
    {
        var framed = new byte[body.Length + 4];
        BinaryPrimitives.WriteUInt32LittleEndian(
            framed,
            checked((uint)body.Length));
        body.CopyTo(framed, 4);
        return framed;
    }

    private static byte[] Concatenate(params byte[][] values)
    {
        var result = new byte[values.Sum(static item => item.Length)];
        var offset = 0;
        foreach (var value in values)
        {
            value.CopyTo(result, offset);
            offset += value.Length;
        }

        return result;
    }

    private static IReadOnlyList<HandoffMessage> DecodeFrames(byte[] data)
    {
        var messages = new List<HandoffMessage>();
        var offset = 0;
        while (offset < data.Length)
        {
            var length = checked((int)BinaryPrimitives.ReadUInt32LittleEndian(
                data.AsSpan(offset, 4)));
            offset += 4;
            messages.Add(
                HandoffCodec.Decode(
                    data.AsMemory(offset, length),
                    Now));
            offset += length;
        }

        Assert.Equal(data.Length, offset);
        return messages;
    }

    private sealed class FakeController : IWindowHostController
    {
        public long WindowHandle => 4500;

        public string ProfileId =>
            "window-2ed594a5e46d4fc0aecb17ca94aab32f";

        internal List<string> Operations { get; } = [];

        internal bool ShutdownCalled { get; private set; }

        public void PrepareHidden(long deadlineUnixMilliseconds)
        {
            Assert.Equal(Now + 30_000, deadlineUnixMilliseconds);
            Operations.Add("prepare-hidden");
        }

        public void Show() => Operations.Add("show");

        public void Focus() => Operations.Add("focus");

        public IReadOnlyDictionary<string, object?> Health()
        {
            Operations.Add("health");
            return new Dictionary<string, object?>
            {
                ["hwnd"] = 4500L,
                ["current_url"] = "http://127.0.0.1:43210/components",
                ["hidden"] = true,
                ["visible"] = false,
                ["renderer"] = "edgechromium",
                ["close_requested"] = false,
            };
        }

        public IReadOnlyDictionary<string, object?> ExportSession()
        {
            Operations.Add("export");
            return new Dictionary<string, object?>
            {
                ["ui_export"] = new Dictionary<string, object?>
                {
                    ["route"] = "components",
                },
                ["theme"] = "dark",
                ["api_healthy"] = true,
                ["event_stream_healthy"] = true,
                ["geometry"] = new Dictionary<string, object?>
                {
                    ["schema"] = "stockroom.window-geometry",
                    ["version"] = 1,
                    ["units"] = "physical-pixels",
                    ["normal_bounds"] =
                        new Dictionary<string, object?>
                        {
                            ["left"] = 0,
                            ["top"] = 0,
                            ["right"] = 1280,
                            ["bottom"] = 800,
                        },
                    ["show_state"] = "normal",
                    ["monitor"] =
                        new Dictionary<string, object?>
                        {
                            ["device_name"] = @"\\.\DISPLAY1",
                            ["work_area"] =
                                new Dictionary<string, object?>
                                {
                                    ["left"] = 0,
                                    ["top"] = 0,
                                    ["right"] = 1920,
                                    ["bottom"] = 1040,
                                },
                            ["dpi"] = 96,
                        },
                },
            };
        }

        public void Shutdown()
        {
            Operations.Add("shutdown");
            ShutdownCalled = true;
        }
    }

    private sealed class ScriptedDuplexStream : Stream
    {
        private readonly MemoryStream _incoming;
        private readonly MemoryStream _outgoing = new();

        internal ScriptedDuplexStream(byte[] incoming)
        {
            _incoming = new MemoryStream(
                incoming,
                writable: false);
        }

        internal byte[] Written => _outgoing.ToArray();

        public override bool CanRead => true;

        public override bool CanSeek => false;

        public override bool CanWrite => true;

        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override void Flush()
        {
        }

        public override int Read(
            byte[] buffer,
            int offset,
            int count) =>
            _incoming.Read(buffer, offset, count);

        public override int Read(Span<byte> buffer) =>
            _incoming.Read(buffer);

        public override long Seek(
            long offset,
            SeekOrigin origin) =>
            throw new NotSupportedException();

        public override void SetLength(long value) =>
            throw new NotSupportedException();

        public override void Write(
            byte[] buffer,
            int offset,
            int count) =>
            _outgoing.Write(buffer, offset, count);

        public override void Write(ReadOnlySpan<byte> buffer) =>
            _outgoing.Write(buffer);

        protected override void Dispose(bool disposing)
        {
            if (disposing)
            {
                _incoming.Dispose();
                _outgoing.Dispose();
            }

            base.Dispose(disposing);
        }
    }
}
