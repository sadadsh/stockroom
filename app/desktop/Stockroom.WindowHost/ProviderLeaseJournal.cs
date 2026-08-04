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

/// <summary>
/// What one lease is for: the Stockroom-owned staging root its downloads must land in, and the
/// component identity every event it produces is stamped with. Deliberately separate from
/// <see cref="ProviderLeaseIdentity"/> so the generation fence keeps comparing exactly two values.
/// </summary>
internal sealed record ProviderLeaseContext(
    string StagingRoot,
    string ComponentId,
    string Manufacturer,
    string Mpn,
    string ProviderId)
{
    internal static ProviderLeaseContext Empty { get; } =
        new(string.Empty, string.Empty, string.Empty, string.Empty, string.Empty);
}

internal sealed record ProviderDownloadEvent(
    long Sequence,
    string LeaseId,
    long Generation,
    string ComponentId,
    string Manufacturer,
    string Mpn,
    string ProviderId,
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
    internal const int MaximumRetainedEvents = 4096;

    private const int MaximumStagingRootLength = 240;
    private const int MaximumIdentityLength = 256;

    private static readonly HashSet<string> AllowedPhases =
        new(StringComparer.Ordinal) { "started", "progress", "terminal" };

    private readonly object _sync = new();
    private readonly List<ProviderDownloadEvent> _events = [];
    private ProviderLeaseIdentity? _active;
    private ProviderLeaseContext _activeContext = ProviderLeaseContext.Empty;
    private long _generation;
    private long _eventSequence;

    internal ProviderLeaseIdentity Begin(string leaseId) =>
        Begin(leaseId, ProviderLeaseContext.Empty);

    internal ProviderLeaseIdentity Begin(
        string leaseId,
        ProviderLeaseContext context)
    {
        ArgumentNullException.ThrowIfNull(context);
        RequireLeaseId(leaseId);
        RequireContext(context);
        lock (_sync)
        {
            if (_active is not null)
            {
                throw new WindowHostException("provider browser already has an active lease");
            }
            _active = new ProviderLeaseIdentity(
                leaseId,
                checked(++_generation));
            _activeContext = context;
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

    /// <summary>
    /// Read the active lease and what it is for under one lock, so a release cannot land between
    /// the two reads and pair a live identity with a stale destination.
    /// </summary>
    internal bool TryGetActive(
        out ProviderLeaseIdentity? lease,
        out ProviderLeaseContext context)
    {
        lock (_sync)
        {
            lease = _active;
            context = _activeContext;
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
            _activeContext = ProviderLeaseContext.Empty;
            return true;
        }
    }

    internal ProviderDownloadEvent Record(
        ProviderLeaseIdentity lease,
        ProviderLeaseContext context,
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
        ArgumentNullException.ThrowIfNull(context);
        RequirePhase(phase);
        lock (_sync)
        {
            var value = new ProviderDownloadEvent(
                checked(++_eventSequence),
                lease.LeaseId,
                lease.Generation,
                context.ComponentId,
                context.Manufacturer,
                context.Mpn,
                context.ProviderId,
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

    private static void RequireContext(ProviderLeaseContext context)
    {
        // An unknown staging root is allowed here and refused at download time. A malformed one
        // is refused now, because a lease that carries garbage would otherwise look serviceable.
        if (context.StagingRoot.Length > 0
            && (context.StagingRoot.Length > MaximumStagingRootLength
                || context.StagingRoot != context.StagingRoot.Trim()
                || context.StagingRoot.Any(char.IsControl)
                || !Path.IsPathFullyQualified(context.StagingRoot)))
        {
            throw new WindowHostException("provider lease staging root is invalid");
        }
        foreach (var value in new[]
        {
            context.ComponentId,
            context.Manufacturer,
            context.Mpn,
            context.ProviderId,
        })
        {
            if (value.Length > MaximumIdentityLength || value.Any(char.IsControl))
            {
                throw new WindowHostException("provider lease component identity is invalid");
            }
        }
    }

    private static void RequirePhase(string phase)
    {
        if (!AllowedPhases.Contains(phase))
        {
            throw new WindowHostException("provider download phase is invalid");
        }
    }
}
