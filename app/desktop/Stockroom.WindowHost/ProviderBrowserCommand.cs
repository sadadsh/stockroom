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
