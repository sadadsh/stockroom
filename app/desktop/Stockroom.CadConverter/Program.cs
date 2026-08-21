using System.Text.Json;

namespace Stockroom.CadConverter;

public static class CadConverterApplication
{
    public static async Task<int> Main(string[] arguments)
    {
        if (!TryParseArguments(arguments, out var requestPath, out var resultPath))
        {
            return 2;
        }
        return await ConvertFileAsync(requestPath, resultPath).ConfigureAwait(false);
    }

    public static async Task<int> ConvertFileAsync(
        string requestPath,
        string resultPath,
        CancellationToken cancellationToken = default)
    {
        var projectRequest = false;
        try
        {
            var json = await File.ReadAllTextAsync(requestPath, cancellationToken).ConfigureAwait(false);
            using var envelope = JsonDocument.Parse(json);
            projectRequest = envelope.RootElement.TryGetProperty("schema", out var schema)
                && schema.GetString() == ProjectRenderRequest.CurrentSchema;
            if (projectRequest)
            {
                var request = JsonSerializer.Deserialize(
                    json,
                    CadConverterJsonContext.Default.ProjectRenderRequest)
                    ?? throw new CadConverterException("request JSON is empty");
                var result = await ProjectDocumentRenderer.RenderAsync(request, cancellationToken).ConfigureAwait(false);
                await WriteResultAsync(resultPath, result, cancellationToken).ConfigureAwait(false);
                return 0;
            }

            var libraryRequest = JsonSerializer.Deserialize(
                json,
                CadConverterJsonContext.Default.CadConverterRequest)
                ?? throw new CadConverterException("request JSON is empty");
            var libraryResult = await CadLibraryConverter.ConvertAsync(libraryRequest, cancellationToken).ConfigureAwait(false);
            await WriteResultAsync(resultPath, libraryResult, cancellationToken).ConfigureAwait(false);
            return 0;
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            if (projectRequest)
            {
                await WriteResultAsync(
                    resultPath,
                    new ProjectRenderResult
                    {
                        Schema = ProjectRenderResult.CurrentSchema,
                        Status = "error",
                        Detail = exception.Message,
                    },
                    cancellationToken).ConfigureAwait(false);
            }
            else
            {
                await WriteResultAsync(
                    resultPath,
                    new CadConverterResult
                    {
                        Schema = CadConverterResult.CurrentSchema,
                        Status = "error",
                        Detail = exception.Message,
                    },
                    cancellationToken).ConfigureAwait(false);
            }
            return 1;
        }
    }

    private static async Task WriteResultAsync(
        string resultPath,
        CadConverterResult result,
        CancellationToken cancellationToken)
    {
        var resultDirectory = Path.GetDirectoryName(Path.GetFullPath(resultPath));
        if (!string.IsNullOrEmpty(resultDirectory))
        {
            Directory.CreateDirectory(resultDirectory);
        }
        await using var output = new FileStream(resultPath, FileMode.Create, FileAccess.Write, FileShare.None, 4096, true);
        await JsonSerializer.SerializeAsync(
            output,
            result,
            CadConverterJsonContext.Default.CadConverterResult,
            cancellationToken).ConfigureAwait(false);
        await output.WriteAsync("\n"u8.ToArray(), cancellationToken).ConfigureAwait(false);
    }

    private static async Task WriteResultAsync(
        string resultPath,
        ProjectRenderResult result,
        CancellationToken cancellationToken)
    {
        var resultDirectory = Path.GetDirectoryName(Path.GetFullPath(resultPath));
        if (!string.IsNullOrEmpty(resultDirectory))
        {
            Directory.CreateDirectory(resultDirectory);
        }
        await using var output = new FileStream(resultPath, FileMode.Create, FileAccess.Write, FileShare.None, 4096, true);
        await JsonSerializer.SerializeAsync(
            output,
            result,
            CadConverterJsonContext.Default.ProjectRenderResult,
            cancellationToken).ConfigureAwait(false);
        await output.WriteAsync("\n"u8.ToArray(), cancellationToken).ConfigureAwait(false);
    }

    private static bool TryParseArguments(
        IReadOnlyList<string> arguments,
        out string requestPath,
        out string resultPath)
    {
        requestPath = string.Empty;
        resultPath = string.Empty;
        for (var index = 0; index < arguments.Count; index += 2)
        {
            if (index + 1 >= arguments.Count)
            {
                return false;
            }
            switch (arguments[index])
            {
                case "--request":
                    requestPath = arguments[index + 1];
                    break;
                case "--result":
                    resultPath = arguments[index + 1];
                    break;
                default:
                    return false;
            }
        }
        return arguments.Count == 4
            && !string.IsNullOrWhiteSpace(requestPath)
            && !string.IsNullOrWhiteSpace(resultPath);
    }
}
