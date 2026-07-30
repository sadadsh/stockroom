namespace Stockroom.WindowHost.Tests;

public sealed class OriginPolicyTests
{
    private static readonly Uri BaseUri =
        new("http://127.0.0.1:43210/");

    [Theory]
    [InlineData("http://127.0.0.1:43210/")]
    [InlineData("http://127.0.0.1:43210/components#selected")]
    [InlineData("http://127.0.0.1:43210/assets/app.js")]
    public void AllowsOnlySameOriginNavigation(string value)
    {
        Assert.True(
            OriginPolicy.IsAllowedNavigation(value, BaseUri));
    }

    [Theory]
    [InlineData("https://127.0.0.1:43210/")]
    [InlineData("http://localhost:43210/")]
    [InlineData("http://127.0.0.1:43211/")]
    [InlineData("file:///C:/Windows/System32/config/SAM")]
    [InlineData("data:text/html,unsafe")]
    [InlineData("javascript:alert(1)")]
    public void DeniesExternalFileAndActiveContentNavigation(string value)
    {
        Assert.False(
            OriginPolicy.IsAllowedNavigation(value, BaseUri));
    }

    [Theory]
    [InlineData("http://127.0.0.1:43210/api/system/identity", true)]
    [InlineData("http://127.0.0.1:43210/api/jobs/1/events", true)]
    [InlineData("http://127.0.0.1:43210/apiculture", false)]
    [InlineData("http://127.0.0.1:43211/api/system/identity", false)]
    public void AuthHeaderScopeIsTheExactApiPathAndOrigin(
        string value,
        bool expected)
    {
        Assert.Equal(
            expected,
            OriginPolicy.IsApiRequest(value, BaseUri));
    }
}
