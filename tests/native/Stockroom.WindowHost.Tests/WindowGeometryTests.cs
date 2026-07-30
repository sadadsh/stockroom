namespace Stockroom.WindowHost.Tests;

public sealed class WindowGeometryTests
{
    [Fact]
    public void RestoresPhysicalBoundsWithDpiScalingAndFullClamp()
    {
        var saved = new PersistedWindowGeometry(
            new PhysicalRectangle(100, 100, 1100, 800),
            PersistedWindowShowState.Maximized,
            new PersistedMonitorGeometry(
                @"\\.\DISPLAY1",
                new PhysicalRectangle(0, 0, 1920, 1080),
                96));
        var target = new CurrentMonitorGeometry(
            new IntPtr(1),
            @"\\.\DISPLAY1",
            new PhysicalRectangle(0, 0, 2560, 1440),
            144);

        var resolved = WindowGeometryResolver.Resolve(
            saved,
            [target]);

        Assert.Equal(
            new PhysicalRectangle(150, 150, 1650, 1200),
            resolved.Bounds);
        Assert.Equal(
            PersistedWindowShowState.Maximized,
            resolved.ShowState);
    }

    [Fact]
    public void MissingMonitorUsesNearestAndKeepsWholeWindowOnScreen()
    {
        var saved = new PersistedWindowGeometry(
            new PhysicalRectangle(5000, 200, 7000, 1600),
            PersistedWindowShowState.Normal,
            new PersistedMonitorGeometry(
                @"\\.\MISSING",
                new PhysicalRectangle(4000, 0, 8000, 2200),
                96));
        var left = new CurrentMonitorGeometry(
            new IntPtr(1),
            @"\\.\LEFT",
            new PhysicalRectangle(-1920, 0, 0, 1040),
            96);
        var right = new CurrentMonitorGeometry(
            new IntPtr(2),
            @"\\.\RIGHT",
            new PhysicalRectangle(0, 0, 1920, 1040),
            96);

        var resolved = WindowGeometryResolver.Resolve(
            saved,
            [left, right]);

        Assert.True(resolved.Bounds.Left >= right.WorkArea.Left);
        Assert.True(resolved.Bounds.Top >= right.WorkArea.Top);
        Assert.True(resolved.Bounds.Right <= right.WorkArea.Right);
        Assert.True(resolved.Bounds.Bottom <= right.WorkArea.Bottom);
        Assert.True(resolved.Bounds.Width >= 960);
        Assert.True(resolved.Bounds.Height >= 640);
    }
}
