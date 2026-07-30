using System.Buffers.Binary;
using System.Text;
using System.Text.Json;

namespace Stockroom.WindowHost.Tests;

public sealed class HandoffProtocolTests
{
    private const string HandoffId =
        "2ed594a5-e46d-4fc0-aecb-17ca94aab32f";
    private const string ApiCredential =
        "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA";
    private const string HandoffCredential =
        "BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBQ";
    private const long Now = 1_800_000_000_000;

    [Fact]
    public void DecodesTheExactPythonCanonicalBootstrapAndProof()
    {
        var body = PythonCanonicalBootstrap();
        var message = HandoffCodec.Decode(body, Now);
        using var bootstrap = BootstrapParser.Parse(message);

        Assert.Equal(HandoffId, bootstrap.HandoffId);
        Assert.Equal("release-v2", bootstrap.ReleaseId);
        Assert.Equal(
            "http://127.0.0.1:43210/",
            bootstrap.BaseUri.AbsoluteUri);
        Assert.Equal(
            "window-2ed594a5e46d4fc0aecb17ca94aab32f",
            bootstrap.ProfileId);
        Assert.Equal(
            "f33b8f59bf565ab02d36f3d7087a30002fe8ca6a81431911bfd94c681879e1ba",
            bootstrap.CreateProof(111, 222));
        Assert.Equal(nameof(HandoffBootstrap), bootstrap.ToString());
        Assert.DoesNotContain(ApiCredential, bootstrap.ToString());
        Assert.DoesNotContain(
            HandoffCredential,
            bootstrap.ToString());
    }

    [Fact]
    public void EncoderMatchesPythonCanonicalSortedJson()
    {
        var payload = new Dictionary<string, object?>
        {
            ["release_id"] = "release-v2",
            ["flags"] = new object?[] { true, 7, null },
        };

        var encoded = HandoffCodec.Encode(
            HandoffId,
            1,
            Now + 5_000,
            "bootstrap",
            payload,
            Now);

        Assert.Equal(
            """{"deadline_unix_ms":1800000005000,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f","name":"bootstrap","payload":{"flags":[true,7,null],"release_id":"release-v2"},"schema":"stockroom.window-handoff","sequence":1,"version":1}""",
            Encoding.ASCII.GetString(encoded));
    }

    [Theory]
    [InlineData("""{"schema":"stockroom.window-handoff","schema":"stockroom.window-handoff","version":1,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f","sequence":1,"deadline_unix_ms":1800000005000,"name":"health","payload":{}}""")]
    [InlineData("""{"schema":"other","version":1,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f","sequence":1,"deadline_unix_ms":1800000005000,"name":"health","payload":{}}""")]
    [InlineData("""{"schema":"stockroom.window-handoff","version":1,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f","sequence":true,"deadline_unix_ms":1800000005000,"name":"health","payload":{}}""")]
    [InlineData("""{"schema":"stockroom.window-handoff","version":1,"handoff_id":"2ed594a5-e46d-4fc0-aecb-17ca94aab32f","sequence":1,"deadline_unix_ms":1800000005000,"name":"Show","payload":{}}""")]
    public void RejectsWeakOrAmbiguousJson(string document)
    {
        Assert.Throws<WindowHostException>(
            () => HandoffCodec.Decode(
                Encoding.UTF8.GetBytes(document),
                Now));
    }

    [Fact]
    public void RejectsExpiredAndOverlongDeadlines()
    {
        Assert.Throws<WindowHostException>(
            () => HandoffCodec.Decode(
                RawMessage(Now - 1),
                Now));
        Assert.Throws<WindowHostException>(
            () => HandoffCodec.Decode(
                RawMessage(
                    Now
                    + HandoffCodec
                        .MaximumDeadlineHorizonMilliseconds
                    + 1),
                Now));
    }

    internal static byte[] PythonCanonicalBootstrap()
    {
        var document =
            $$"""{"deadline_unix_ms":1800000030000,"handoff_id":"{{HandoffId}}","name":"bootstrap","payload":{"api_credential":"{{ApiCredential}}","base_url":"http://127.0.0.1:43210/","handoff_credential":"{{HandoffCredential}}","release_id":"release-v2"},"schema":"stockroom.window-handoff","sequence":1,"version":1}""";
        return Encoding.ASCII.GetBytes(document);
    }

    internal static byte[] BuildMessage(
        long sequence,
        string name,
        long deadline,
        IReadOnlyDictionary<string, object?> payload)
    {
        var body = HandoffCodec.Encode(
            HandoffId,
            sequence,
            deadline,
            name,
            payload,
            Now);
        var framed = new byte[body.Length + 4];
        BinaryPrimitives.WriteUInt32LittleEndian(
            framed,
            checked((uint)body.Length));
        body.CopyTo(framed, 4);
        return framed;
    }

    internal static HandoffBootstrap ParseBootstrap()
    {
        var message = HandoffCodec.Decode(
            PythonCanonicalBootstrap(),
            Now);
        return BootstrapParser.Parse(message);
    }

    private static byte[] RawMessage(long deadline)
    {
        var document =
            $$"""{"deadline_unix_ms":{{deadline}},"handoff_id":"{{HandoffId}}","name":"health","payload":{},"schema":"stockroom.window-handoff","sequence":1,"version":1}""";
        return Encoding.ASCII.GetBytes(document);
    }
}
