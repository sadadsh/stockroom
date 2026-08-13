namespace Stockroom.WindowHost.Tests;

public sealed class ProviderBrowserCommandTests
{
    [Theory]
    [InlineData("back", "Back")]
    [InlineData("forward", "Forward")]
    [InlineData("reload", "Reload")]
    [InlineData("close", "Close")]
    public void AcceptsEveryModalToolbarCommand(
        string value,
        string expected)
    {
        Assert.True(ProviderBrowserCommandCodec.TryParse(value, out var command));
        Assert.Equal(expected, command.ToString());
    }

    [Theory]
    [InlineData("")]
    [InlineData("Close")]
    [InlineData("navigate")]
    public void RejectsCommandsOutsideTheClosedGrammar(string value)
    {
        Assert.False(ProviderBrowserCommandCodec.TryParse(value, out _));
    }
}
