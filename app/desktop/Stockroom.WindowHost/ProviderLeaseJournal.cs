using System.IO;
using System.Net.Http.Headers;

namespace Stockroom.WindowHost;

internal static class ProviderDownloadName
{
    internal static string Resolve(
        string contentDisposition,
        string uri,
        string resultFilePath)
    {
        if (ContentDispositionHeaderValue.TryParse(
                contentDisposition,
                out var disposition))
        {
            var declared = disposition.FileNameStar ?? disposition.FileName;
            var name = SafeFileName(declared?.Trim().Trim('"'));
            if (name.Length > 0)
            {
                return name;
            }
        }
        if (Uri.TryCreate(uri, UriKind.Absolute, out var parsed))
        {
            var name = SafeFileName(Uri.UnescapeDataString(parsed.AbsolutePath));
            if (name.Length > 0 && Path.HasExtension(name))
            {
                return name;
            }
        }
        return SafeFileName(resultFilePath) is { Length: > 0 } fallback
            ? fallback
            : "cad-download";
    }

    private static string SafeFileName(string? value)
    {
        if (string.IsNullOrWhiteSpace(value))
        {
            return string.Empty;
        }
        try
        {
            return Path.GetFileName(value);
        }
        catch (ArgumentException)
        {
            return string.Empty;
        }
    }
}

internal sealed record ProviderLeaseIdentity(
    string LeaseId,
    long Generation);

internal sealed record ProviderDownloadEvent(
    long Sequence,
    string LeaseId,
    long Generation,
    string OperationId,
    string Phase,
    string State,
    string Uri,
    string SuggestedFileName,
    string ResultFilePath,
    string MimeType,
    string InterruptReason,
    long TotalBytes,
    long BytesReceived);

/// <summary>
/// Owns the generation fence and the bounded native download event journal for
/// the one embedded provider surface. Visibility is deliberately not part of
/// lease ownership: Return To Stockroom hides the surface without ending work.
/// </summary>
internal sealed class ProviderLeaseJournal
{
    private const int MaximumRetainedEvents = 4096;

    private readonly object _sync = new();
    private readonly List<ProviderDownloadEvent> _events = [];
    private ProviderLeaseIdentity? _active;
    private long _generation;
    private long _eventSequence;

    internal ProviderLeaseIdentity Begin(string leaseId)
    {
        RequireLeaseId(leaseId);
        lock (_sync)
        {
            if (_active is not null)
            {
                throw new WindowHostException("provider browser already has an active lease");
            }
            _active = new ProviderLeaseIdentity(
                leaseId,
                checked(++_generation));
            return _active;
        }
    }

    internal ProviderLeaseIdentity RequireActive()
    {
        lock (_sync)
        {
            return _active
                ?? throw new WindowHostException(
                    "provider browser requires an active lease");
        }
    }

    internal ProviderLeaseIdentity RequireActive(ProviderLeaseIdentity requested)
    {
        ArgumentNullException.ThrowIfNull(requested);
        lock (_sync)
        {
            if (_active != requested)
            {
                throw new WindowHostException("provider browser lease is stale");
            }
            return requested;
        }
    }

    internal bool TryGetActive(out ProviderLeaseIdentity? lease)
    {
        lock (_sync)
        {
            lease = _active;
            return lease is not null;
        }
    }

    internal bool Release(ProviderLeaseIdentity requested)
    {
        ArgumentNullException.ThrowIfNull(requested);
        lock (_sync)
        {
            if (_active != requested)
            {
                return false;
            }
            _active = null;
            return true;
        }
    }

    internal ProviderDownloadEvent Record(
        ProviderLeaseIdentity lease,
        string operationId,
        string phase,
        string state,
        string uri,
        string suggestedFileName,
        string resultFilePath,
        string mimeType,
        string interruptReason,
        long totalBytes,
        long bytesReceived)
    {
        ArgumentNullException.ThrowIfNull(lease);
        lock (_sync)
        {
            var value = new ProviderDownloadEvent(
                checked(++_eventSequence),
                lease.LeaseId,
                lease.Generation,
                operationId,
                phase,
                state,
                uri,
                suggestedFileName,
                resultFilePath,
                mimeType,
                interruptReason,
                totalBytes,
                bytesReceived);
            _events.Add(value);
            if (_events.Count > MaximumRetainedEvents)
            {
                _events.RemoveRange(0, _events.Count - MaximumRetainedEvents);
            }
            return value;
        }
    }

    internal IReadOnlyList<ProviderDownloadEvent> After(
        ProviderLeaseIdentity lease,
        long sequence)
    {
        ArgumentNullException.ThrowIfNull(lease);
        if (sequence < 0)
        {
            throw new WindowHostException("provider download cursor is invalid");
        }
        lock (_sync)
        {
            return _events
                .Where(item =>
                    item.LeaseId == lease.LeaseId
                    && item.Generation == lease.Generation
                    && item.Sequence > sequence)
                .ToArray();
        }
    }

    private static void RequireLeaseId(string leaseId)
    {
        if (string.IsNullOrWhiteSpace(leaseId)
            || leaseId.Length > 128
            || leaseId != leaseId.Trim()
            || leaseId.Any(char.IsControl))
        {
            throw new WindowHostException("provider lease id is invalid");
        }
    }
}
