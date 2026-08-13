namespace Stockroom.WindowHost;

internal enum ProviderBrowserCommand
{
    Back,
    Forward,
    Reload,
    Close,
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
            _ => default,
        };
        return value is "back" or "forward" or "reload" or "close";
    }
}
