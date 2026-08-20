namespace Stockroom.WindowHost;

internal enum ProviderBrowserCommand
{
    Back,
    Forward,
    Reload,
    Close,
    Navigate,
}

internal static class ProviderBrowserCommandCodec
{
    internal static bool TryParse(string value, out ProviderBrowserCommand command)
    {
        command = value switch
        {
            "back" => ProviderBrowserCommand.Back,
            "forward" => ProviderBrowserCommand.Forward,
            "reload" => ProviderBrowserCommand.Reload,
            "close" => ProviderBrowserCommand.Close,
            "navigate" => ProviderBrowserCommand.Navigate,
            _ => default,
        };
        return value is "back" or "forward" or "reload" or "close" or "navigate";
    }
}

internal sealed record ProviderBrowserCommandOutcome(bool Accepted, string Error);

internal sealed record ProviderBrowserSurfaceIdentity(
    string ComponentId,
    string ProviderId,
    string RouteId,
    string SessionId)
{
    internal bool IsValid =>
        new[] { ComponentId, ProviderId, RouteId, SessionId }
            .All(value =>
                !string.IsNullOrWhiteSpace(value)
                && value.Length <= 256
                && value == value.Trim()
                && !value.Any(char.IsControl));

    internal bool MatchesLease(ProviderLeaseContext context) =>
        IsValid
        && string.Equals(ComponentId, context.ComponentId, StringComparison.Ordinal)
        && (
            string.Equals(ProviderId, context.ProviderId, StringComparison.Ordinal)
            || string.Equals(RouteId, context.ProviderId, StringComparison.Ordinal)
            || string.Equals(
                RouteId,
                $"manual:{context.ProviderId}",
                StringComparison.Ordinal)
        );
}

internal static class ProviderBrowserCommandContext
{
    internal static bool Matches(
        ProviderBrowserCommand command,
        ProviderBrowserSurfaceIdentity requested,
        ProviderBrowserSurfaceIdentity? viewport,
        bool viewportVisible)
    {
        if (!requested.IsValid || viewport is null || requested != viewport)
        {
            return false;
        }
        return viewportVisible || command == ProviderBrowserCommand.Close;
    }

    internal static bool MatchesLease(
        ProviderBrowserCommand command,
        ProviderBrowserSurfaceIdentity requested,
        ProviderLeaseContext? activeLease)
    {
        return activeLease is null
            ? command == ProviderBrowserCommand.Close
            : requested.MatchesLease(activeLease);
    }
}

internal static class ProviderBrowserCommandExecutor
{
    internal static ProviderBrowserCommandOutcome Execute(
        ProviderBrowserCommand command,
        string? url,
        Func<ProviderBrowserCommand, string?, bool> action)
    {
        ArgumentNullException.ThrowIfNull(action);
        try
        {
            return action(command, url)
                ? new ProviderBrowserCommandOutcome(true, string.Empty)
                : new ProviderBrowserCommandOutcome(
                    false,
                    $"The provider browser refused {command}.");
        }
        catch (Exception exception)
            when (exception is not (OutOfMemoryException or StackOverflowException))
        {
            return new ProviderBrowserCommandOutcome(
                false,
                $"The provider browser could not execute {command}.");
        }
    }
}
