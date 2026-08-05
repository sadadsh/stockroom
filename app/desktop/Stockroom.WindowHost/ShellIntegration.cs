using System.Diagnostics;
using System.Globalization;
using System.IO;
using Microsoft.Win32;

namespace Stockroom.WindowHost;

/// <summary>
/// One EDA application this machine really has, as the window host proved it.
/// </summary>
/// <remarks>
/// The executable path never leaves this process. Python names an application by its stable id
/// and the host resolves the binary itself, so no command that starts a process ever carries a
/// program path across the handoff channel.
/// </remarks>
internal sealed record EdaApplication(
    string Id,
    string Name,
    string Version,
    string ExecutablePath);

/// <summary>
/// One machine-local installation the probe found, before it has been proved to exist.
/// </summary>
internal readonly record struct EdaInstallationCandidate(
    string Id,
    string Name,
    string Version,
    string ExecutablePath);

/// <summary>
/// The two file-system shapes a shell command may act on.
/// </summary>
internal enum ShellTargetKind
{
    Directory,
    File,
}

/// <summary>
/// What a shell path has to be before this process will hand it to Windows.
/// </summary>
/// <remarks>
/// A command that opens whatever path it is given is a remote-code-execution shape wearing a
/// convenience label, so every rule here is a refusal rather than a repair:
///
///   - fully qualified and already canonical, so no <c>..</c> segment, no short 8.3 alias and no
///     relative fragment can resolve somewhere other than what was inspected;
///   - drive-rooted (<c>X:\</c>) only, which excludes UNC shares (<c>\\server\share</c>) and the
///     Win32 device namespace (<c>\\?\</c>, <c>\\.\</c>) outright;
///   - contained inside a root the CALLER already owns, compared canonically rather than by
///     string prefix, so <c>C:\Library Extra</c> is not inside <c>C:\Library</c>;
///   - really present on disk, and not a reparse point, because a junction inside the root is a
///     redirection out of it that containment alone would never see.
///
/// The root is supplied by the backend, which computes it from the active library. This layer
/// still refuses independently: two checks that can each fail closed are the point.
/// </remarks>
internal static class ShellPathPolicy
{
    private const int MaximumPathLength = 4096;

    /// <summary>
    /// The exact path, once it is a real target of <paramref name="kind"/> inside
    /// <paramref name="root"/>. Throws <see cref="WindowHostException"/> otherwise.
    /// </summary>
    internal static string RequireContained(
        string root,
        string path,
        ShellTargetKind kind)
    {
        var canonicalRoot = RequireCanonicalLocalPath(root, "shell root");
        var canonicalPath = RequireCanonicalLocalPath(path, "shell path");
        if (!Directory.Exists(canonicalRoot))
        {
            throw new WindowHostException("shell root is not an existing directory");
        }

        if (!IsInside(canonicalRoot, canonicalPath))
        {
            throw new WindowHostException("shell path escapes its root");
        }

        RequireNoLinkBetween(canonicalRoot, canonicalPath);
        if (kind == ShellTargetKind.Directory)
        {
            if (!Directory.Exists(canonicalPath))
            {
                throw new WindowHostException("shell path is not an existing directory");
            }
        }
        else if (!File.Exists(canonicalPath))
        {
            throw new WindowHostException("shell path is not an existing file");
        }

        return canonicalPath;
    }

    private static string RequireCanonicalLocalPath(string value, string label)
    {
        if (string.IsNullOrEmpty(value) || value.Length > MaximumPathLength)
        {
            throw new WindowHostException($"{label} is invalid");
        }

        foreach (var character in value)
        {
            if (char.IsControl(character) || character is '"' or '*' or '?' or '<' or '>' or '|')
            {
                throw new WindowHostException($"{label} is invalid");
            }
        }

        if (!Path.IsPathFullyQualified(value))
        {
            throw new WindowHostException($"{label} is not fully qualified");
        }

        var root = Path.GetPathRoot(value);
        if (root is null
            || root.Length != 3
            || !char.IsAsciiLetter(root[0])
            || root[1] != ':'
            || root[2] != Path.DirectorySeparatorChar)
        {
            throw new WindowHostException($"{label} is not a drive-rooted local path");
        }

        string canonical;
        try
        {
            canonical = Path.GetFullPath(value);
        }
        catch (Exception exception)
            when (exception is ArgumentException or NotSupportedException or PathTooLongException)
        {
            throw new WindowHostException($"{label} is invalid", exception);
        }

        if (!string.Equals(canonical, value, StringComparison.Ordinal))
        {
            throw new WindowHostException($"{label} is not already canonical");
        }

        return canonical;
    }

    private static bool IsInside(string root, string path)
    {
        var prefix = root.EndsWith(Path.DirectorySeparatorChar)
            ? root
            : root + Path.DirectorySeparatorChar;
        // Segment-aware on purpose: a plain prefix test would place "C:\Library Extra\a" inside
        // "C:\Library". Windows paths compare case-insensitively, which is what the file system
        // itself will do a moment later.
        return path.Length > prefix.Length
            && path.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    private static void RequireNoLinkBetween(string root, string path)
    {
        var current = path;
        while (!string.IsNullOrEmpty(current)
            && !string.Equals(current, root, StringComparison.OrdinalIgnoreCase))
        {
            var info = Directory.Exists(current)
                ? new DirectoryInfo(current)
                : (FileSystemInfo)new FileInfo(current);
            if (info.Exists && info.LinkTarget is not null)
            {
                throw new WindowHostException("shell path crosses a link out of its root");
            }

            current = Path.GetDirectoryName(current) ?? string.Empty;
        }
    }
}

/// <summary>
/// The EDA applications Stockroom is willing to name, and how each one is proved present.
/// </summary>
/// <remarks>
/// An application appears here only when this machine really has it. An entry that cannot be
/// proved is left out rather than listed and disabled: a menu item that cannot work is a dead
/// click path, and "Open In..." exists precisely to answer "what can actually open this".
/// </remarks>
internal static class EdaApplicationCatalog
{
    /// <summary>The only ids a command may name. Anything else is refused before it is looked up.</summary>
    internal static readonly string[] KnownIds = ["kicad", "altium-designer"];

    /// <summary>
    /// The detected set: candidates whose executable really exists, one row per id, newest build
    /// first when a machine carries several.
    /// </summary>
    internal static IReadOnlyList<EdaApplication> Resolve(
        IEnumerable<EdaInstallationCandidate> candidates,
        Func<string, bool> executableExists)
    {
        ArgumentNullException.ThrowIfNull(candidates);
        ArgumentNullException.ThrowIfNull(executableExists);
        var best = new Dictionary<string, EdaApplication>(StringComparer.Ordinal);
        foreach (var candidate in candidates)
        {
            if (!KnownIds.Contains(candidate.Id, StringComparer.Ordinal))
            {
                continue;
            }

            if (string.IsNullOrEmpty(candidate.Name)
                || string.IsNullOrEmpty(candidate.ExecutablePath)
                || !executableExists(candidate.ExecutablePath))
            {
                continue;
            }

            var resolved = new EdaApplication(
                candidate.Id,
                candidate.Name,
                candidate.Version,
                candidate.ExecutablePath);
            if (!best.TryGetValue(candidate.Id, out var existing)
                || CompareVersions(resolved.Version, existing.Version) > 0)
            {
                best[candidate.Id] = resolved;
            }
        }

        return KnownIds
            .Where(best.ContainsKey)
            .Select(id => best[id])
            .ToArray();
    }

    private static int CompareVersions(string left, string right)
    {
        var parsedLeft = Version.TryParse(left, out var leftVersion);
        var parsedRight = Version.TryParse(right, out var rightVersion);
        if (parsedLeft && parsedRight)
        {
            return leftVersion!.CompareTo(rightVersion);
        }

        if (parsedLeft != parsedRight)
        {
            return parsedLeft ? 1 : -1;
        }

        return string.CompareOrdinal(left, right);
    }
}

/// <summary>
/// The Windows implementation: registry probes for what is installed, and the two shell actions.
/// </summary>
internal sealed class WindowsShellSurface
{
    private const string UninstallKey =
        @"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall";
    private const string AltiumBuildsKey = @"SOFTWARE\Altium\Builds";

    private readonly Func<IReadOnlyList<EdaInstallationCandidate>> _probe;
    private readonly Func<string, bool> _executableExists;
    private readonly Action<string, IReadOnlyList<string>> _start;

    internal WindowsShellSurface(
        Func<IReadOnlyList<EdaInstallationCandidate>>? probe = null,
        Func<string, bool>? executableExists = null,
        Action<string, IReadOnlyList<string>>? start = null)
    {
        _probe = probe ?? ProbeInstalledApplications;
        _executableExists = executableExists ?? File.Exists;
        _start = start ?? StartProcess;
    }

    internal IReadOnlyList<EdaApplication> DetectedEdaApplications() =>
        EdaApplicationCatalog.Resolve(_probe(), _executableExists);

    /// <summary>Open the OS file browser at one directory the backend already resolved.</summary>
    internal void RevealDirectory(string root, string path)
    {
        var target = ShellPathPolicy.RequireContained(root, path, ShellTargetKind.Directory);
        var explorer = Path.Combine(
            Environment.GetFolderPath(Environment.SpecialFolder.Windows),
            "explorer.exe");
        _start(explorer, [target]);
    }

    /// <summary>Open one file in a detected EDA application, named by its stable id.</summary>
    internal void OpenFileWith(string applicationId, string root, string path)
    {
        if (string.IsNullOrEmpty(applicationId)
            || !EdaApplicationCatalog.KnownIds.Contains(applicationId, StringComparer.Ordinal))
        {
            throw new WindowHostException("application id is not a known EDA application");
        }

        var target = ShellPathPolicy.RequireContained(root, path, ShellTargetKind.File);
        var application = DetectedEdaApplications()
            .FirstOrDefault(item => string.Equals(item.Id, applicationId, StringComparison.Ordinal))
            ?? throw new WindowHostException(
                "the requested EDA application is not installed on this machine");
        _start(application.ExecutablePath, [target]);
    }

    private static void StartProcess(string fileName, IReadOnlyList<string> arguments)
    {
        var startInfo = new ProcessStartInfo
        {
            FileName = fileName,
            // Never the shell verb path: `UseShellExecute = true` would let a registered handler
            // decide what "opening" means, and this host must start exactly the binary it proved.
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        foreach (var argument in arguments)
        {
            startInfo.ArgumentList.Add(argument);
        }

        using var started = Process.Start(startInfo);
        if (started is null)
        {
            throw new WindowHostException("the requested application could not be started");
        }
    }

    private static IReadOnlyList<EdaInstallationCandidate> ProbeInstalledApplications()
    {
        var candidates = new List<EdaInstallationCandidate>();
        candidates.AddRange(ProbeKiCad());
        candidates.AddRange(ProbeAltiumDesigner());
        return candidates;
    }

    /// <summary>
    /// KiCad registers one uninstall entry per installed major version, carrying the install
    /// directory. The launcher binary is what a file argument is handed to.
    /// </summary>
    private static IEnumerable<EdaInstallationCandidate> ProbeKiCad()
    {
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            using var machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, view);
            using var uninstall = machine.OpenSubKey(UninstallKey);
            if (uninstall is null)
            {
                continue;
            }

            foreach (var name in uninstall.GetSubKeyNames())
            {
                using var entry = uninstall.OpenSubKey(name);
                var display = entry?.GetValue("DisplayName") as string;
                var location = entry?.GetValue("InstallLocation") as string;
                if (display is null
                    || location is null
                    || !display.StartsWith("KiCad", StringComparison.OrdinalIgnoreCase))
                {
                    continue;
                }

                yield return new EdaInstallationCandidate(
                    "kicad",
                    display,
                    entry?.GetValue("DisplayVersion") as string ?? string.Empty,
                    Path.Combine(location, "bin", "kicad.exe"));
            }
        }
    }

    /// <summary>
    /// Altium Designer records every installed build under its own key, each naming the folder
    /// its executable lives in.
    /// </summary>
    private static IEnumerable<EdaInstallationCandidate> ProbeAltiumDesigner()
    {
        foreach (var view in new[] { RegistryView.Registry64, RegistryView.Registry32 })
        {
            using var machine = RegistryKey.OpenBaseKey(RegistryHive.LocalMachine, view);
            using var builds = machine.OpenSubKey(AltiumBuildsKey);
            if (builds is null)
            {
                continue;
            }

            foreach (var name in builds.GetSubKeyNames())
            {
                using var entry = builds.OpenSubKey(name);
                var location = entry?.GetValue("ProgramsInstallPath") as string;
                if (location is null)
                {
                    continue;
                }

                var version = entry?.GetValue("Version") as string ?? string.Empty;
                yield return new EdaInstallationCandidate(
                    "altium-designer",
                    string.IsNullOrEmpty(version)
                        ? "Altium Designer"
                        : string.Create(
                            CultureInfo.InvariantCulture,
                            $"Altium Designer {version}"),
                    version,
                    Path.Combine(location, "X2.EXE"));
            }
        }
    }
}
