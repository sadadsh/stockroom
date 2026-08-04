using System.IO;
using System.Text;

namespace Stockroom.WindowHost;

/// <summary>
/// Turns a provider-supplied download name into bytes Stockroom is willing to write, inside a
/// Stockroom-owned staging directory. The person's Downloads folder is never a destination: the
/// only path this produces is a direct child of one operation directory that is itself a direct
/// child of the staging root the lease was begun with.
/// </summary>
internal static class ProviderDownloadStaging
{
    /// <summary>
    /// Windows either rejects these outright or reinterprets them as path or stream syntax. A
    /// provider that sends one is careless or hostile; either way the byte on disk must not
    /// carry it.
    /// </summary>
    private const string ForbiddenFileNameCharacters = "<>:\"/\\|?*";

    /// <summary>
    /// Leaves room for a staging root, one 36-character operation directory and two separators
    /// inside the classic 260-character path limit, without depending on long-path support being
    /// enabled on the machine.
    /// </summary>
    internal const int MaximumFileNameLength = 120;

    private const int MaximumExtensionLength = 16;

    internal const string FallbackFileName = "cad-download";

    private static readonly char[] PathBoundaryCharacters = ['/', '\\', ':'];

    private static readonly HashSet<string> ReservedDeviceNames =
        new(StringComparer.OrdinalIgnoreCase)
        {
            "CON",
            "PRN",
            "AUX",
            "NUL",
            "COM1",
            "COM2",
            "COM3",
            "COM4",
            "COM5",
            "COM6",
            "COM7",
            "COM8",
            "COM9",
            "LPT1",
            "LPT2",
            "LPT3",
            "LPT4",
            "LPT5",
            "LPT6",
            "LPT7",
            "LPT8",
            "LPT9",
        };

    /// <summary>
    /// Reduce a suggested name to one physical file name. The caller keeps the original text for
    /// the journal; this result only ever names bytes on disk.
    /// </summary>
    internal static string SanitizeFileName(string? suggested)
    {
        var candidate = suggested ?? string.Empty;
        var boundary = candidate.LastIndexOfAny(PathBoundaryCharacters);
        if (boundary >= 0)
        {
            candidate = candidate[(boundary + 1)..];
        }

        var builder = new StringBuilder(candidate.Length);
        foreach (var value in candidate)
        {
            builder.Append(
                char.IsControl(value) || ForbiddenFileNameCharacters.Contains(value)
                    ? '_'
                    : value);
        }

        var cleaned = TrimTrailingWindowsPadding(builder.ToString());
        if (cleaned.Length == 0)
        {
            return FallbackFileName;
        }

        if (cleaned.Length > MaximumFileNameLength)
        {
            var extension = Path.GetExtension(cleaned);
            if (extension.Length > MaximumExtensionLength)
            {
                extension = extension[..MaximumExtensionLength];
            }

            var stem = TrimTrailingWindowsPadding(
                cleaned[..(MaximumFileNameLength - extension.Length)]);
            cleaned = stem.Length == 0
                ? FallbackFileName + extension
                : stem + extension;
        }

        var dot = cleaned.IndexOf('.');
        var deviceCandidate = dot >= 0 ? cleaned[..dot] : cleaned;
        if (ReservedDeviceNames.Contains(deviceCandidate))
        {
            // CON.step opens the console, not a file. Prefixing keeps the extension the person
            // recognises while making the name an ordinary one.
            cleaned = "_" + cleaned;
        }

        return cleaned;
    }

    /// <summary>
    /// Resolve the one absolute path a download may write to, or refuse. Refusal is the correct
    /// answer whenever containment cannot be proven; there is no default location to fall back to.
    /// </summary>
    internal static bool TryResolveDestination(
        string? stagingRoot,
        string? operationId,
        string? suggestedFileName,
        out string destination)
    {
        destination = string.Empty;
        if (string.IsNullOrWhiteSpace(stagingRoot)
            || string.IsNullOrWhiteSpace(operationId)
            || stagingRoot.Any(char.IsControl)
            || operationId.Any(char.IsControl)
            || !Path.IsPathFullyQualified(stagingRoot))
        {
            return false;
        }

        try
        {
            var root = Path.TrimEndingDirectorySeparator(Path.GetFullPath(stagingRoot));
            var directory = Path.TrimEndingDirectorySeparator(
                Path.GetFullPath(Path.Combine(root, operationId)));
            var candidate = Path.GetFullPath(
                Path.Combine(directory, SanitizeFileName(suggestedFileName)));
            // Containment is the authority here, not the sanitizer. Whatever the name reduced to,
            // the file must land directly inside one operation directory directly inside the
            // staging root, or the download does not happen at all.
            if (!IsDirectChild(root, directory) || !IsDirectChild(directory, candidate))
            {
                return false;
            }

            destination = candidate;
            return true;
        }
        catch (ArgumentException)
        {
            return false;
        }
        catch (PathTooLongException)
        {
            return false;
        }
        catch (NotSupportedException)
        {
            return false;
        }
        catch (IOException)
        {
            return false;
        }
    }

    private static bool IsDirectChild(string parent, string candidate)
    {
        var directory = Path.GetDirectoryName(candidate);
        return directory is not null
            && Path.TrimEndingDirectorySeparator(directory)
                .Equals(parent, StringComparison.OrdinalIgnoreCase);
    }

    private static string TrimTrailingWindowsPadding(string value)
    {
        var trimmed = value.Trim();
        while (trimmed.Length > 0
            && (trimmed[^1] == '.' || char.IsWhiteSpace(trimmed[^1])))
        {
            trimmed = trimmed[..^1];
        }

        return trimmed;
    }
}

/// <summary>
/// Bounds how many <c>progress</c> entries one download may add to the bounded lease journal.
/// </summary>
internal sealed class ProviderDownloadProgressThrottle
{
    /// <summary>
    /// CoreWebView2DownloadOperation.BytesReceivedChanged fires once per received network buffer,
    /// while ProviderLeaseJournal.MaximumRetainedEvents caps the whole lease. This throttle is the
    /// only thing standing between one long download and the eviction of every other event in that
    /// journal, so all three bounds are deliberately coarse: a progress entry needs a quarter of a
    /// second AND one percent more bytes, and one operation can never publish more than
    /// MaximumProgressEvents entries no matter how long it runs or whether a length was declared.
    /// </summary>
    internal const long MinimumIntervalMilliseconds = 250;

    private const long ProgressPercentStep = 1;

    internal const int MaximumProgressEvents = 128;

    private long _lastUnixMilliseconds;
    private long _lastBytes;
    private int _emitted;

    internal ProviderDownloadProgressThrottle(long startMilliseconds)
    {
        _lastUnixMilliseconds = startMilliseconds;
        _lastBytes = 0;
    }

    internal int Emitted => _emitted;

    internal bool TryAcquire(
        long nowMilliseconds,
        long bytesReceived,
        long totalBytes)
    {
        if (_emitted >= MaximumProgressEvents
            || bytesReceived <= _lastBytes
            || nowMilliseconds - _lastUnixMilliseconds < MinimumIntervalMilliseconds)
        {
            return false;
        }

        // An undeclared total still gets a step, measured against what has already arrived, so a
        // length-free stream reports geometrically rather than per buffer.
        var basis = totalBytes > 0 ? totalBytes : bytesReceived;
        if (bytesReceived - _lastBytes < Math.Max(1, basis * ProgressPercentStep / 100))
        {
            return false;
        }

        _lastUnixMilliseconds = nowMilliseconds;
        _lastBytes = bytesReceived;
        _emitted += 1;
        return true;
    }
}
