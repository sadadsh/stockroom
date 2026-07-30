using System.Globalization;
using System.Text.RegularExpressions;

namespace Stockroom.WindowHost;

internal sealed record HostArguments(string PipeName, uint ParentProcessId)
{
    private static readonly Regex PipeNamePattern = new(
        @"\AStockroom\.WindowHandoff\.[0-9a-f]{32}\z",
        RegexOptions.CultureInvariant | RegexOptions.NonBacktracking);

    internal static HostArguments Parse(IReadOnlyList<string> arguments)
    {
        if (arguments.Count != 5
            || arguments[0] != "--window-host"
            || arguments[1] != "--handoff-pipe"
            || arguments[3] != "--parent-pid"
            || !PipeNamePattern.IsMatch(arguments[2])
            || !uint.TryParse(
                arguments[4],
                NumberStyles.None,
                CultureInfo.InvariantCulture,
                out var parentProcessId)
            || parentProcessId == 0)
        {
            throw new WindowHostException("window-host arguments are invalid");
        }

        return new HostArguments(arguments[2], parentProcessId);
    }
}
