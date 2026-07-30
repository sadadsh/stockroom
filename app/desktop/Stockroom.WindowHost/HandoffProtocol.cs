using System.Buffers.Binary;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.RegularExpressions;

namespace Stockroom.WindowHost;

internal sealed record HandoffMessage(
    string HandoffId,
    long Sequence,
    long DeadlineUnixMilliseconds,
    string Name,
    JsonElement Payload);

internal sealed class HandoffBootstrap : IDisposable
{
    internal HandoffBootstrap(
        string handoffId,
        string releaseId,
        Uri baseUri,
        SensitiveCredential apiCredential,
        SensitiveCredential handoffCredential)
    {
        HandoffId = handoffId;
        ReleaseId = releaseId;
        BaseUri = baseUri;
        ApiCredential = apiCredential;
        HandoffCredential = handoffCredential;
    }

    internal string HandoffId { get; }

    internal string ReleaseId { get; }

    internal Uri BaseUri { get; }

    internal SensitiveCredential ApiCredential { get; }

    internal SensitiveCredential HandoffCredential { get; }

    internal string ProfileId =>
        "window-" + HandoffId.Replace("-", string.Empty, StringComparison.Ordinal);

    internal string CreateProof(uint parentProcessId, uint childProcessId)
    {
        if (parentProcessId == 0 || childProcessId == 0)
        {
            throw new WindowHostException("window-host process identity is invalid");
        }

        var context = Encoding.ASCII.GetBytes(
            string.Create(
                CultureInfo.InvariantCulture,
                $"{HandoffId}\0{ReleaseId}\0{parentProcessId}\0{childProcessId}"));
        try
        {
            return HandoffCredential.HmacHex(context);
        }
        finally
        {
            CryptographicOperations.ZeroMemory(context);
        }
    }

    public void Dispose()
    {
        ApiCredential.Dispose();
        HandoffCredential.Dispose();
    }

    public override string ToString() => nameof(HandoffBootstrap);
}

internal static partial class HandoffCodec
{
    internal const int MaximumFrameBytes = 64 * 1024;
    internal const long MaximumDeadlineHorizonMilliseconds = 5 * 60 * 1000;
    internal const string Schema = "stockroom.window-handoff";
    internal const int Version = 1;

    private const int MaximumJsonDepth = 16;
    private const int MaximumJsonItems = 4096;
    private const int MaximumStringLength = 48 * 1024;

    [GeneratedRegex(@"\A[a-z][a-z0-9-]{0,63}\z", RegexOptions.CultureInvariant)]
    private static partial Regex MessageNamePattern();

    internal static HandoffMessage Decode(
        ReadOnlyMemory<byte> encoded,
        long nowUnixMilliseconds)
    {
        if (encoded.Length is <= 0 or > MaximumFrameBytes)
        {
            throw new WindowHostException("message exceeds the JSON frame limit");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(
                encoded,
                new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = MaximumJsonDepth,
                });
        }
        catch (JsonException exception)
        {
            throw new WindowHostException(
                "message is not strict UTF-8 JSON",
                exception);
        }

        using (document)
        {
            var root = document.RootElement;
            var itemCount = 0;
            ValidateJsonValue(root, 0, ref itemCount);
            RequireExactObject(
                root,
                "message",
                "schema",
                "version",
                "handoff_id",
                "sequence",
                "deadline_unix_ms",
                "name",
                "payload");

            if (GetRequiredString(root, "schema") != Schema)
            {
                throw new WindowHostException("message schema is unsupported");
            }

            var versionElement = root.GetProperty("version");
            if (versionElement.ValueKind != JsonValueKind.Number
                || !versionElement.TryGetInt32(out var version)
                || version != Version)
            {
                throw new WindowHostException("message version is unsupported");
            }

            var handoffId = GetRequiredString(root, "handoff_id");
            ValidateHandoffId(handoffId);
            var sequenceElement = root.GetProperty("sequence");
            if (sequenceElement.ValueKind != JsonValueKind.Number
                || !sequenceElement.TryGetInt64(out var sequence)
                || sequence <= 0)
            {
                throw new WindowHostException(
                    "sequence must be a supported positive integer");
            }

            var deadlineElement = root.GetProperty("deadline_unix_ms");
            if (deadlineElement.ValueKind != JsonValueKind.Number
                || !deadlineElement.TryGetInt64(out var deadline)
                || deadline <= 0)
            {
                throw new WindowHostException(
                    "deadline_unix_ms must be a positive integer");
            }

            ValidateDeadline(deadline, nowUnixMilliseconds);
            var name = GetRequiredString(root, "name");
            if (!MessageNamePattern().IsMatch(name))
            {
                throw new WindowHostException("message name is invalid");
            }

            var payload = root.GetProperty("payload");
            if (payload.ValueKind != JsonValueKind.Object)
            {
                throw new WindowHostException("payload must be an object");
            }

            return new HandoffMessage(
                handoffId,
                sequence,
                deadline,
                name,
                payload.Clone());
        }
    }

    internal static byte[] Encode(
        string handoffId,
        long sequence,
        long deadlineUnixMilliseconds,
        string name,
        IReadOnlyDictionary<string, object?> payload,
        long nowUnixMilliseconds)
    {
        ValidateHandoffId(handoffId);
        if (sequence <= 0)
        {
            throw new WindowHostException(
                "sequence must be a supported positive integer");
        }

        ValidateDeadline(deadlineUnixMilliseconds, nowUnixMilliseconds);
        if (!MessageNamePattern().IsMatch(name))
        {
            throw new WindowHostException("message name is invalid");
        }

        using var buffer = new MemoryStream();
        using (var writer = new Utf8JsonWriter(
                   buffer,
                   new JsonWriterOptions
                   {
                       Encoder = JavaScriptEncoder.Default,
                       Indented = false,
                       SkipValidation = false,
                   }))
        {
            writer.WriteStartObject();
            writer.WriteNumber("deadline_unix_ms", deadlineUnixMilliseconds);
            writer.WriteString("handoff_id", handoffId);
            writer.WriteString("name", name);
            writer.WritePropertyName("payload");
            WriteCanonicalDictionary(writer, payload);
            writer.WriteString("schema", Schema);
            writer.WriteNumber("sequence", sequence);
            writer.WriteNumber("version", Version);
            writer.WriteEndObject();
        }

        var result = buffer.ToArray();
        if (result.Length is <= 0 or > MaximumFrameBytes)
        {
            throw new WindowHostException("message exceeds the JSON frame limit");
        }

        return result;
    }

    internal static void RequireExactObject(
        JsonElement value,
        string label,
        params string[] expectedNames)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            throw new WindowHostException($"{label} must be an object");
        }

        var expected = new HashSet<string>(
            expectedNames,
            StringComparer.Ordinal);
        var actual = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
        {
            if (!actual.Add(property.Name))
            {
                throw new WindowHostException(
                    "message contains duplicate object keys");
            }
        }

        if (!actual.SetEquals(expected))
        {
            throw new WindowHostException($"{label} has invalid fields");
        }
    }

    internal static string GetRequiredString(JsonElement value, string name)
    {
        var property = value.GetProperty(name);
        if (property.ValueKind != JsonValueKind.String)
        {
            throw new WindowHostException($"{name} must be a string");
        }

        return property.GetString()
            ?? throw new WindowHostException($"{name} must be a string");
    }

    private static void ValidateHandoffId(string value)
    {
        if (!Guid.TryParseExact(value, "D", out var parsed)
            || parsed.ToString("D") != value
            || value[14] != '4')
        {
            throw new WindowHostException(
                "handoff_id must be a canonical UUIDv4");
        }
    }

    private static void ValidateDeadline(
        long deadlineUnixMilliseconds,
        long nowUnixMilliseconds)
    {
        if (nowUnixMilliseconds <= 0)
        {
            throw new WindowHostException("current clock value is invalid");
        }

        if (deadlineUnixMilliseconds < nowUnixMilliseconds)
        {
            throw new WindowHostException("message deadline expired");
        }

        if (deadlineUnixMilliseconds
            > nowUnixMilliseconds + MaximumDeadlineHorizonMilliseconds)
        {
            throw new WindowHostException(
                "message deadline exceeds the allowed horizon");
        }
    }

    private static void ValidateJsonValue(
        JsonElement value,
        int depth,
        ref int itemCount)
    {
        if (depth > MaximumJsonDepth)
        {
            throw new WindowHostException(
                "message payload nesting exceeds the limit");
        }

        itemCount++;
        if (itemCount > MaximumJsonItems)
        {
            throw new WindowHostException(
                "message payload contains too many values");
        }

        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
            {
                var names = new HashSet<string>(StringComparer.Ordinal);
                foreach (var property in value.EnumerateObject())
                {
                    if (string.IsNullOrEmpty(property.Name)
                        || property.Name.Length > 128)
                    {
                        throw new WindowHostException(
                            "message payload contains an invalid object key");
                    }

                    if (!names.Add(property.Name))
                    {
                        throw new WindowHostException(
                            "message contains duplicate object keys");
                    }

                    ValidateJsonValue(
                        property.Value,
                        depth + 1,
                        ref itemCount);
                }

                break;
            }
            case JsonValueKind.Array:
                foreach (var item in value.EnumerateArray())
                {
                    ValidateJsonValue(item, depth + 1, ref itemCount);
                }

                break;
            case JsonValueKind.String:
                if ((value.GetString() ?? string.Empty).Length
                    > MaximumStringLength)
                {
                    throw new WindowHostException(
                        "message payload string exceeds the limit");
                }

                break;
            case JsonValueKind.Number:
                if (value.TryGetDouble(out var number)
                    && !double.IsFinite(number))
                {
                    throw new WindowHostException(
                        "message payload contains a non-finite number");
                }

                break;
            case JsonValueKind.True:
            case JsonValueKind.False:
            case JsonValueKind.Null:
                break;
            default:
                throw new WindowHostException(
                    "message payload contains a non-JSON value");
        }
    }

    private static void WriteCanonicalDictionary(
        Utf8JsonWriter writer,
        IReadOnlyDictionary<string, object?> value)
    {
        writer.WriteStartObject();
        foreach (var pair in value.OrderBy(
                     static item => item.Key,
                     StringComparer.Ordinal))
        {
            if (string.IsNullOrEmpty(pair.Key) || pair.Key.Length > 128)
            {
                throw new WindowHostException(
                    "message payload contains an invalid object key");
            }

            writer.WritePropertyName(pair.Key);
            WriteCanonicalValue(writer, pair.Value);
        }

        writer.WriteEndObject();
    }

    private static void WriteCanonicalJsonElement(
        Utf8JsonWriter writer,
        JsonElement value)
    {
        switch (value.ValueKind)
        {
            case JsonValueKind.Object:
                writer.WriteStartObject();
                foreach (var property in value.EnumerateObject().OrderBy(
                             static item => item.Name,
                             StringComparer.Ordinal))
                {
                    writer.WritePropertyName(property.Name);
                    WriteCanonicalJsonElement(writer, property.Value);
                }

                writer.WriteEndObject();
                break;
            case JsonValueKind.Array:
                writer.WriteStartArray();
                foreach (var item in value.EnumerateArray())
                {
                    WriteCanonicalJsonElement(writer, item);
                }

                writer.WriteEndArray();
                break;
            default:
                value.WriteTo(writer);
                break;
        }
    }

    private static void WriteCanonicalValue(
        Utf8JsonWriter writer,
        object? value)
    {
        switch (value)
        {
            case null:
                writer.WriteNullValue();
                break;
            case bool boolean:
                writer.WriteBooleanValue(boolean);
                break;
            case int integer:
                writer.WriteNumberValue(integer);
                break;
            case uint unsignedInteger:
                writer.WriteNumberValue(unsignedInteger);
                break;
            case long longInteger:
                writer.WriteNumberValue(longInteger);
                break;
            case ulong unsignedLongInteger:
                writer.WriteNumberValue(unsignedLongInteger);
                break;
            case double number when double.IsFinite(number):
                writer.WriteNumberValue(number);
                break;
            case string text:
                writer.WriteStringValue(text);
                break;
            case JsonElement element:
                WriteCanonicalJsonElement(writer, element);
                break;
            case IReadOnlyDictionary<string, object?> dictionary:
                WriteCanonicalDictionary(writer, dictionary);
                break;
            case IEnumerable<object?> sequence:
                writer.WriteStartArray();
                foreach (var item in sequence)
                {
                    WriteCanonicalValue(writer, item);
                }

                writer.WriteEndArray();
                break;
            default:
                throw new WindowHostException(
                    "message payload contains a non-JSON value");
        }
    }

}

internal sealed partial class HandoffChannel : IDisposable
{
    private const int ResponseWindowMilliseconds = 10_000;

    private readonly Stream _stream;
    private readonly Func<long> _clock;
    private string? _handoffId;
    private long _nextIncomingSequence = 1;
    private long _nextOutgoingSequence = 1;
    private bool _disposed;

    internal HandoffChannel(Stream stream, Func<long>? clock = null)
    {
        _stream = stream ?? throw new ArgumentNullException(nameof(stream));
        _clock = clock ?? (() => DateTimeOffset.UtcNow.ToUnixTimeMilliseconds());
    }

    internal string HandoffId =>
        _handoffId
        ?? throw new WindowHostException(
            "handoff_id is not bound until the first message");

    internal HandoffMessage Receive(params string[] expectedNames)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        Span<byte> prefix = stackalloc byte[4];
        ReadExactly(prefix);
        var length = BinaryPrimitives.ReadUInt32LittleEndian(prefix);
        if (length is 0 or > HandoffCodec.MaximumFrameBytes)
        {
            throw new WindowHostException(
                "incoming JSON frame length is invalid");
        }

        var body = GC.AllocateUninitializedArray<byte>((int)length);
        try
        {
            ReadExactly(body);
            var message = HandoffCodec.Decode(body, _clock());
            if (_handoffId is null)
            {
                _handoffId = message.HandoffId;
            }
            else if (_handoffId != message.HandoffId)
            {
                throw new WindowHostException(
                    "handoff_id changed inside one channel");
            }

            if (message.Sequence != _nextIncomingSequence)
            {
                throw new WindowHostException(
                    message.Sequence < _nextIncomingSequence
                        ? "message sequence was replayed"
                        : "message sequence has a gap");
            }

            if (!expectedNames.Contains(
                    message.Name,
                    StringComparer.Ordinal))
            {
                throw new WindowHostException(
                    "message name is not valid in the current state");
            }

            _nextIncomingSequence++;
            return message;
        }
        finally
        {
            CryptographicOperations.ZeroMemory(body);
        }
    }

    internal long Send(
        string name,
        IReadOnlyDictionary<string, object?> payload,
        SensitiveCredential apiCredential,
        SensitiveCredential handoffCredential)
    {
        ObjectDisposedException.ThrowIf(_disposed, this);
        var now = _clock();
        var encoded = HandoffCodec.Encode(
            HandoffId,
            _nextOutgoingSequence,
            now + ResponseWindowMilliseconds,
            name,
            payload,
            now);
        try
        {
            if (apiCredential.OccursIn(encoded)
                || handoffCredential.OccursIn(encoded))
            {
                throw new WindowHostException(
                    "window-host response contained a credential");
            }

            Span<byte> prefix = stackalloc byte[4];
            BinaryPrimitives.WriteUInt32LittleEndian(
                prefix,
                checked((uint)encoded.Length));
            _stream.Write(prefix);
            _stream.Write(encoded);
            _stream.Flush();
            return _nextOutgoingSequence++;
        }
        finally
        {
            CryptographicOperations.ZeroMemory(encoded);
        }
    }

    private void ReadExactly(Span<byte> destination)
    {
        var offset = 0;
        while (offset < destination.Length)
        {
            var read = _stream.Read(destination[offset..]);
            if (read <= 0)
            {
                throw new WindowHostException(
                    "window-handoff peer closed the pipe");
            }

            offset += read;
        }
    }

    public void Dispose()
    {
        if (_disposed)
        {
            return;
        }

        _disposed = true;
        _stream.Dispose();
    }
}

internal static partial class BootstrapParser
{
    [GeneratedRegex(
        @"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\z",
        RegexOptions.CultureInvariant)]
    private static partial Regex ReleaseIdPattern();

    [GeneratedRegex(
        @"\Ahttp://127\.0\.0\.1:(?<port>[0-9]{1,5})/?\z",
        RegexOptions.CultureInvariant)]
    private static partial Regex BaseUrlPattern();

    internal static HandoffBootstrap Parse(HandoffMessage message)
    {
        if (message.Name != "bootstrap")
        {
            throw new WindowHostException(
                "the first window-host message must be bootstrap");
        }

        HandoffCodec.RequireExactObject(
            message.Payload,
            "bootstrap payload",
            "release_id",
            "base_url",
            "api_credential",
            "handoff_credential");
        var releaseId = HandoffCodec.GetRequiredString(
            message.Payload,
            "release_id");
        if (!ReleaseIdPattern().IsMatch(releaseId))
        {
            throw new WindowHostException("release_id is invalid");
        }

        var baseUrl = HandoffCodec.GetRequiredString(
            message.Payload,
            "base_url");
        var baseUrlMatch = BaseUrlPattern().Match(baseUrl);
        if (baseUrl.Length > 128
            || !baseUrlMatch.Success
            || !int.TryParse(
                baseUrlMatch.Groups["port"].Value,
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var port)
            || port is <= 0 or > 65535
            || !Uri.TryCreate(baseUrl, UriKind.Absolute, out var baseUri)
            || baseUri.Scheme != Uri.UriSchemeHttp
            || baseUri.Host != "127.0.0.1"
            || !string.IsNullOrEmpty(baseUri.UserInfo)
            || !string.IsNullOrEmpty(baseUri.Query)
            || !string.IsNullOrEmpty(baseUri.Fragment)
            || baseUri.AbsolutePath != "/")
        {
            throw new WindowHostException(
                "base_url must be an exact IPv4 loopback origin");
        }

        var apiCredential = SensitiveCredential.Parse(
            message.Payload.GetProperty("api_credential"),
            "api_credential");
        try
        {
            var handoffCredential = SensitiveCredential.Parse(
                message.Payload.GetProperty("handoff_credential"),
                "handoff_credential");
            if (apiCredential.FixedTimeEquals(handoffCredential))
            {
                handoffCredential.Dispose();
                throw new WindowHostException(
                    "handoff and API credentials must be independent");
            }

            return new HandoffBootstrap(
                message.HandoffId,
                releaseId,
                new Uri(
                    string.Create(
                        CultureInfo.InvariantCulture,
                        $"http://127.0.0.1:{port}/"),
                    UriKind.Absolute),
                apiCredential,
                handoffCredential);
        }
        catch
        {
            apiCredential.Dispose();
            throw;
        }
    }
}
