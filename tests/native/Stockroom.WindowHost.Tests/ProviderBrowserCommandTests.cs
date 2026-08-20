namespace Stockroom.WindowHost.Tests;

public sealed class ProviderBrowserCommandTests
{
    [Theory]
    [InlineData("back", "Back")]
    [InlineData("forward", "Forward")]
    [InlineData("reload", "Reload")]
    [InlineData("close", "Close")]
    [InlineData("navigate", "Navigate")]
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
    [InlineData("Navigate")]
    public void RejectsCommandsOutsideTheClosedGrammar(string value)
    {
        Assert.False(ProviderBrowserCommandCodec.TryParse(value, out _));
    }

    [Fact]
    public void CommandOutcomeAcknowledgesTheActionRatherThanOnlyTheMessageReceipt()
    {
        var calls = new List<(ProviderBrowserCommand Command, string? Url)>();
        var accepted = ProviderBrowserCommandExecutor.Execute(
            ProviderBrowserCommand.Navigate,
            "https://www.mouser.com/c/?q=LM358",
            (command, url) =>
            {
                calls.Add((command, url));
                return true;
            });
        var refused = ProviderBrowserCommandExecutor.Execute(
            ProviderBrowserCommand.Back,
            null,
            (_, _) => false);

        Assert.True(accepted.Accepted);
        Assert.Equal(string.Empty, accepted.Error);
        Assert.Equal(
            [(ProviderBrowserCommand.Navigate, "https://www.mouser.com/c/?q=LM358")],
            calls);
        Assert.False(refused.Accepted);
        Assert.Equal("The provider browser refused Back.", refused.Error);
    }

    [Fact]
    public void CommandOutcomeReturnsABoundedFailureWhenNativeExecutionThrows()
    {
        var outcome = ProviderBrowserCommandExecutor.Execute(
            ProviderBrowserCommand.Reload,
            null,
            (_, _) => throw new InvalidOperationException("native detail must stay private"));

        Assert.False(outcome.Accepted);
        Assert.Equal("The provider browser could not execute Reload.", outcome.Error);
    }

    [Fact]
    public void CloseStillMatchesItsExactSessionAfterReactPublishesTheHiddenViewport()
    {
        var current = new ProviderBrowserSurfaceIdentity(
            "part-1",
            "mouser",
            "manual:mouser",
            "session-1");
        Assert.True(
            ProviderBrowserCommandContext.Matches(
                ProviderBrowserCommand.Close,
                current,
                current,
                viewportVisible: false));
        Assert.False(
            ProviderBrowserCommandContext.Matches(
                ProviderBrowserCommand.Navigate,
                current,
                current,
                viewportVisible: false));
    }

    [Fact]
    public void CommandsFromAnOldProviderRouteOrSessionAreRejected()
    {
        var current = new ProviderBrowserSurfaceIdentity(
            "part-1",
            "lcsc",
            "manual:lcsc",
            "session-2");

        Assert.False(ProviderBrowserCommandContext.Matches(
            ProviderBrowserCommand.Reload,
            current with { ProviderId = "mouser", RouteId = "manual:mouser" },
            current,
            viewportVisible: true));
        Assert.False(ProviderBrowserCommandContext.Matches(
            ProviderBrowserCommand.Reload,
            current with { SessionId = "session-1" },
            current,
            viewportVisible: true));
        Assert.True(ProviderBrowserCommandContext.Matches(
            ProviderBrowserCommand.Reload,
            current,
            current,
            viewportVisible: true));
    }

    [Fact]
    public void ViewportProviderOrAuthorRouteMustMatchTheNativeLease()
    {
        var context = new ProviderLeaseContext(
            @"C:\Provider",
            "part-1",
            "Texas Instruments",
            "LM358DR",
            "mouser");

        Assert.True(new ProviderBrowserSurfaceIdentity(
            "part-1", "mouser", "manual:mouser", "session-1").MatchesLease(context));
        Assert.False(new ProviderBrowserSurfaceIdentity(
            "part-1", "lcsc", "manual:lcsc", "session-2").MatchesLease(context));
    }

    [Fact]
    public void StaleCloseCannotHideAReplacementProviderLease()
    {
        var oldIdentity = new ProviderBrowserSurfaceIdentity(
            "part-1", "mouser", "manual:mouser", "session-1");
        var replacement = new ProviderLeaseContext(
            @"C:\Provider",
            "part-1",
            "Texas Instruments",
            "LM358DR",
            "lcsc");

        Assert.False(ProviderBrowserCommandContext.MatchesLease(
            ProviderBrowserCommand.Close,
            oldIdentity,
            replacement));
        Assert.True(ProviderBrowserCommandContext.MatchesLease(
            ProviderBrowserCommand.Close,
            oldIdentity,
            activeLease: null));
    }
}
