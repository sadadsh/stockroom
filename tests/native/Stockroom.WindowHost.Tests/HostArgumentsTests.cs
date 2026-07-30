namespace Stockroom.WindowHost.Tests;

public sealed class HostArgumentsTests
{
    private const string PipeName =
        "Stockroom.WindowHandoff.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    [Fact]
    public void ParsesOnlyTheExactNonSecretChildContract()
    {
        var parsed = HostArguments.Parse(
        [
            "--window-host",
            "--handoff-pipe",
            PipeName,
            "--parent-pid",
            "1234",
        ]);

        Assert.Equal(PipeName, parsed.PipeName);
        Assert.Equal(1234u, parsed.ParentProcessId);
        Assert.DoesNotContain(
            "token",
            parsed.ToString(),
            StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData("--api-token")]
    [InlineData("--handoff-token")]
    [InlineData("--base-url")]
    [InlineData("--profile")]
    public void RejectsAnySecretOrAuthorityExpansionInArgv(
        string forbiddenFlag)
    {
        var arguments = new[]
        {
            "--window-host",
            "--handoff-pipe",
            PipeName,
            "--parent-pid",
            "1234",
            forbiddenFlag,
            "value",
        };

        var exception = Assert.Throws<WindowHostException>(
            () => HostArguments.Parse(arguments));

        Assert.Equal(
            "window-host arguments are invalid",
            exception.Message);
        Assert.DoesNotContain("value", exception.ToString());
    }

    [Theory]
    [InlineData("Stockroom.WindowHandoff.AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")]
    [InlineData("Stockroom.WindowHandoff.short")]
    [InlineData(@"\\.\pipe\Stockroom.WindowHandoff.aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa")]
    public void RejectsNoncanonicalPipeNames(string pipeName)
    {
        Assert.Throws<WindowHostException>(
            () => HostArguments.Parse(
            [
                "--window-host",
                "--handoff-pipe",
                pipeName,
                "--parent-pid",
                "1234",
            ]));
    }
}
