using System.Security.Cryptography;
using OriginalCircuit.Altium;
using OriginalCircuit.Altium.Models.Pcb;
using OriginalCircuit.Altium.Models.Sch;
using OriginalCircuit.Altium.Rendering;
using OriginalCircuit.Altium.Rendering.Svg;
using OriginalCircuit.Eda.Primitives;
using OriginalCircuit.Eda.Rendering;

namespace Stockroom.CadConverter;

public static class ProjectDocumentRenderer
{
    public static async Task<ProjectRenderResult> RenderAsync(
        ProjectRenderRequest request,
        CancellationToken cancellationToken = default)
    {
        if (request.Schema != ProjectRenderRequest.CurrentSchema)
        {
            throw new CadConverterException("unsupported project render request schema");
        }
        if (request.Width is < 64 or > 8192 || request.Height is < 64 or > 8192)
        {
            throw new CadConverterException("project render dimensions must be between 64 and 8192");
        }

        var root = Path.GetFullPath(request.ProjectRoot);
        if (!Directory.Exists(root))
        {
            throw new CadConverterException("project root does not exist");
        }
        var output = Path.GetFullPath(request.OutputDirectory);
        if (SamePath(root, output) || Inside(root, output))
        {
            throw new CadConverterException("project render output must remain outside the project root");
        }
        if (request.Documents.Count == 0)
        {
            throw new CadConverterException("project render requires at least one document");
        }

        var sources = request.Documents.Select(relative => ResolveSource(root, relative)).ToArray();
        var before = sources.ToDictionary(item => item.FullPath, item => Sha256(item.FullPath));
        Directory.CreateDirectory(output);
        var options = new RenderOptions
        {
            Width = request.Width,
            Height = request.Height,
            BackgroundColor = EdaColor.Transparent,
        };
        var renderer = new SvgRenderer();
        var artifacts = new List<ProjectRenderArtifact>();

        foreach (var source in sources)
        {
            cancellationToken.ThrowIfCancellationRequested();
            if (source.Kind == "schematic")
            {
                await using var opened = await AltiumLibrary.OpenSchDocAsync(source.FullPath, cancellationToken).ConfigureAwait(false);
                var document = opened as SchDocument
                    ?? throw new CadConverterException($"unsupported schematic document: {source.RelativePath}");
                artifacts.Add(await RenderAsync(
                    renderer,
                    document,
                    source,
                    "sheet",
                    output,
                    options,
                    PcbRenderSettings.Top,
                    before[source.FullPath],
                    cancellationToken).ConfigureAwait(false));
            }
            else
            {
                await using var opened = await AltiumLibrary.OpenPcbDocAsync(source.FullPath, cancellationToken).ConfigureAwait(false);
                var document = opened as PcbDocument
                    ?? throw new CadConverterException($"unsupported PCB document: {source.RelativePath}");
                artifacts.Add(await RenderAsync(
                    renderer,
                    document,
                    source,
                    "top",
                    output,
                    options,
                    PcbRenderSettings.Top,
                    before[source.FullPath],
                    cancellationToken).ConfigureAwait(false));
                artifacts.Add(await RenderAsync(
                    renderer,
                    document,
                    source,
                    "bottom",
                    output,
                    options,
                    PcbRenderSettings.Bottom,
                    before[source.FullPath],
                    cancellationToken).ConfigureAwait(false));
            }
            if (Sha256(source.FullPath) != before[source.FullPath])
            {
                throw new CadConverterException($"project source changed while rendering: {source.RelativePath}");
            }
        }

        return new ProjectRenderResult
        {
            Schema = ProjectRenderResult.CurrentSchema,
            Status = "ok",
            Detail = $"Rendered {sources.Length} Altium project document(s).",
            Artifacts = artifacts,
        };
    }

    private static async Task<ProjectRenderArtifact> RenderAsync(
        SvgRenderer renderer,
        object document,
        SourceDocument source,
        string view,
        string output,
        RenderOptions options,
        PcbRenderSettings settings,
        string sourceSha256,
        CancellationToken cancellationToken)
    {
        var identity = Convert.ToHexString(SHA256.HashData(System.Text.Encoding.UTF8.GetBytes(source.RelativePath))).ToLowerInvariant()[..12];
        var path = Path.Combine(output, $"{Path.GetFileNameWithoutExtension(source.RelativePath)}-{identity}-{view}.svg");
        if (document is SchDocument schematic)
        {
            await renderer.RenderAsync(schematic, path, options, cancellationToken).ConfigureAwait(false);
        }
        else if (document is PcbDocument board)
        {
            await renderer.RenderAsync(board, path, options, settings, cancellationToken).ConfigureAwait(false);
        }
        else
        {
            throw new CadConverterException("unsupported project document type");
        }
        var info = new FileInfo(path);
        return new ProjectRenderArtifact
        {
            SourcePath = source.RelativePath.Replace('\\', '/'),
            Kind = source.Kind,
            View = view,
            Path = info.FullName,
            MediaType = "image/svg+xml",
            Width = options.Width,
            Height = options.Height,
            SizeBytes = info.Length,
            Sha256 = Sha256(info.FullName),
            SourceSha256 = sourceSha256,
        };
    }

    private static SourceDocument ResolveSource(string root, string value)
    {
        if (string.IsNullOrWhiteSpace(value) || Path.IsPathRooted(value))
        {
            throw new CadConverterException("project documents must be relative to the project root");
        }
        var fullPath = Path.GetFullPath(Path.Combine(root, value));
        if (!Inside(root, fullPath))
        {
            throw new CadConverterException("project document escaped the project root");
        }
        if (!File.Exists(fullPath))
        {
            throw new CadConverterException($"project document does not exist: {value}");
        }
        var suffix = Path.GetExtension(fullPath);
        var kind = suffix.Equals(".SchDoc", StringComparison.OrdinalIgnoreCase)
            ? "schematic"
            : suffix.Equals(".PcbDoc", StringComparison.OrdinalIgnoreCase)
                ? "pcb"
                : throw new CadConverterException($"unsupported project document: {value}");
        return new SourceDocument(fullPath, Path.GetRelativePath(root, fullPath), kind);
    }

    private static bool Inside(string root, string candidate)
    {
        var prefix = root.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar)
            + Path.DirectorySeparatorChar;
        return candidate.StartsWith(prefix, StringComparison.OrdinalIgnoreCase);
    }

    private static bool SamePath(string first, string second) =>
        string.Equals(
            first.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            second.TrimEnd(Path.DirectorySeparatorChar, Path.AltDirectorySeparatorChar),
            StringComparison.OrdinalIgnoreCase);

    private static string Sha256(string path)
    {
        using var stream = File.OpenRead(path);
        return Convert.ToHexString(SHA256.HashData(stream)).ToLowerInvariant();
    }

    private sealed record SourceDocument(string FullPath, string RelativePath, string Kind);
}
