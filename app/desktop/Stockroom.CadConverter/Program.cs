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
        CadConverterResult result;
        var exitCode = 0;
        try
        {
            await using var input = File.OpenRead(requestPath);
            var request = await JsonSerializer.DeserializeAsync(
                input,
                CadConverterJsonContext.Default.CadConverterRequest,
                cancellationToken).ConfigureAwait(false);
            if (request is null)
            {
                throw new CadConverterException("request JSON is empty");
            }
            result = await CadLibraryConverter.ConvertAsync(request, cancellationToken).ConfigureAwait(false);
        }
        catch (Exception exception) when (exception is not OperationCanceledException)
        {
            exitCode = 1;
            result = new CadConverterResult
            {
                Schema = CadConverterResult.CurrentSchema,
                Status = "error",
                Detail = exception.Message,
            };
        }

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
        return exitCode;
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
