using Stockroom.WindowHost;

namespace Stockroom.WindowHost.Tests;

public sealed class ProviderViewportLayoutTests
{
    [Fact]
    public void AcceptsCurrentComponentBoundsInsideStockroomContent()
    {
        var request = new ProviderViewportRequest(
            "part-1", true, 280, 76, 900, 620);

        Assert.True(
            ProviderViewportLayout.TryResolve(
                request,
                "part-1",
                1280,
                760,
                out var layout));
        Assert.Equal(new ProviderViewportLayout(280, 76, 900, 620), layout);
    }

    [Theory]
    [InlineData("part-2", 280, 76, 900, 620)]
    [InlineData("part-1", -1, 76, 900, 620)]
    [InlineData("part-1", 280, 76, 1200, 620)]
    [InlineData("part-1", 280, 76, 200, 120)]
    public void RejectsStaleOutsideOrUnusableBounds(
        string componentId,
        double x,
        double y,
        double width,
        double height)
    {
        var request = new ProviderViewportRequest(
            componentId, true, x, y, width, height);

        Assert.False(
            ProviderViewportLayout.TryResolve(
                request,
                "part-1",
                1280,
                760,
                out _));
    }
}
