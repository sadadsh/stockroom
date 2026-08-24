using System.IO;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal sealed record MachineWindowConfig(
    string ConfigRoot,
    PersistedWindowGeometry? Geometry,
    string Theme,
    string ColorScheme)
{
    private const int MaximumConfigBytes = 4 * 1024 * 1024;

    internal static MachineWindowConfig Load(
        IReadOnlyDictionary<string, string?>? environment = null)
    {
        environment ??= Environment.GetEnvironmentVariables()
            .Cast<System.Collections.DictionaryEntry>()
            .ToDictionary(
                static item => (string)item.Key,
                static item => item.Value?.ToString(),
                StringComparer.OrdinalIgnoreCase);
        var configRoot = ResolveConfigRoot(environment);
        var configPath = Path.Combine(configRoot, "config.json");
        if (!File.Exists(configPath))
        {
            return new MachineWindowConfig(
                configRoot,
                null,
                "dark",
                "neutral");
        }

        var file = new FileInfo(configPath);
        if (file.Length is < 0 or > MaximumConfigBytes)
        {
            throw new WindowHostException(
                "machine config exceeds the supported size");
        }

        JsonDocument document;
        try
        {
            document = JsonDocument.Parse(
                File.ReadAllBytes(configPath),
                new JsonDocumentOptions
                {
                    AllowTrailingCommas = false,
                    CommentHandling = JsonCommentHandling.Disallow,
                    MaxDepth = 16,
                });
        }
        catch (Exception exception)
            when (exception is IOException
                or UnauthorizedAccessException
                or JsonException)
        {
            throw new WindowHostException(
                "machine config could not be read safely",
                exception);
        }

        using (document)
        {
            var root = document.RootElement;
            RequireObject(root, "machine config");
            RejectDuplicateProperties(root, "machine config");
            PersistedWindowGeometry? geometry = null;
            if (root.TryGetProperty("window", out var rawWindow))
            {
                geometry = PersistedWindowGeometry.Parse(rawWindow);
            }

            var theme = "dark";
            var colorScheme = "neutral";
            if (root.TryGetProperty("ui", out var rawUi))
            {
                RequireObject(rawUi, "ui");
                RejectDuplicateProperties(rawUi, "ui");
                if (rawUi.TryGetProperty("theme", out var rawTheme))
                {
                    if (rawTheme.ValueKind != JsonValueKind.String)
                    {
                        throw new WindowHostException(
                            "machine config ui.theme is invalid");
                    }

                    var value = rawTheme.GetString();
                    if (value is not ("dark" or "light"))
                    {
                        throw new WindowHostException(
                            "machine config ui.theme is invalid");
                    }

                    theme = value;
                }
                if (rawUi.TryGetProperty("color_scheme", out var rawColorScheme))
                {
                    if (rawColorScheme.ValueKind != JsonValueKind.String)
                    {
                        throw new WindowHostException(
                            "machine config ui.color_scheme is invalid");
                    }

                    var value = rawColorScheme.GetString();
                    if (value is not ("neutral" or "blue" or "green" or "violet"))
                    {
                        throw new WindowHostException(
                            "machine config ui.color_scheme is invalid");
                    }

                    colorScheme = value;
                }
            }

            return new MachineWindowConfig(
                configRoot,
                geometry,
                theme,
                colorScheme);
        }
    }

    internal string ProfileDirectory(string profileId)
    {
        if (!profileId.StartsWith("window-", StringComparison.Ordinal)
            || profileId.Length != 39)
        {
            throw new WindowHostException("profile ID is invalid");
        }

        var root = Path.GetFullPath(
            Path.Combine(
                ConfigRoot,
                "Host State",
                "WebView Profiles"));
        var directory = Path.GetFullPath(
            Path.Combine(root, profileId));
        if (!string.Equals(
                Path.GetDirectoryName(directory),
                root,
                StringComparison.OrdinalIgnoreCase))
        {
            throw new WindowHostException(
                "window profile escaped its machine-local root");
        }

        Directory.CreateDirectory(directory);
        return directory;
    }

    internal string ProviderProfileDirectory()
    {
        var directory = Path.GetFullPath(
            Path.Combine(
                ConfigRoot,
                "Host State",
                "Provider Browser"));
        Directory.CreateDirectory(directory);
        return directory;
    }

    private static string ResolveConfigRoot(
        IReadOnlyDictionary<string, string?> environment)
    {
        if (environment.TryGetValue(
                "STOCKROOM_CONFIG_DIR",
                out var overrideValue)
            && !string.IsNullOrWhiteSpace(overrideValue))
        {
            if (!Path.IsPathFullyQualified(overrideValue)
                || overrideValue.IndexOf('\0') >= 0)
            {
                throw new WindowHostException(
                    "STOCKROOM_CONFIG_DIR must be an absolute path");
            }

            return Path.GetFullPath(overrideValue);
        }

        if (!environment.TryGetValue("APPDATA", out var appData)
            || string.IsNullOrWhiteSpace(appData)
            || !Path.IsPathFullyQualified(appData))
        {
            throw new WindowHostException(
                "the machine config root is unavailable");
        }

        return Path.GetFullPath(Path.Combine(appData, "Stockroom"));
    }

    internal static void RequireObject(JsonElement value, string label)
    {
        if (value.ValueKind != JsonValueKind.Object)
        {
            throw new WindowHostException($"{label} must be an object");
        }
    }

    internal static void RejectDuplicateProperties(
        JsonElement value,
        string label)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        foreach (var property in value.EnumerateObject())
        {
            if (!names.Add(property.Name))
            {
                throw new WindowHostException(
                    $"{label} contains duplicate fields");
            }
        }
    }

    internal static void RequireExactProperties(
        JsonElement value,
        string label,
        params string[] properties)
    {
        RequireObject(value, label);
        RejectDuplicateProperties(value, label);
        var expected = new HashSet<string>(
            properties,
            StringComparer.Ordinal);
        var actual = value.EnumerateObject()
            .Select(static item => item.Name)
            .ToHashSet(StringComparer.Ordinal);
        if (!actual.SetEquals(expected))
        {
            throw new WindowHostException(
                $"{label} has invalid fields");
        }
    }
}
