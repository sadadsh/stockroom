using System.Text;

namespace Stockroom.WindowHost.Tests;

public sealed class MachineWindowConfigTests : IDisposable
{
    private readonly string _temporaryRoot = Path.Combine(
        Path.GetTempPath(),
        "Stockroom.WindowHost.Tests",
        Guid.NewGuid().ToString("N"));

    [Fact]
    public void LoadsOnlyWindowAndThemeFromTheNonsecretConfig()
    {
        Directory.CreateDirectory(_temporaryRoot);
        File.WriteAllText(
            Path.Combine(_temporaryRoot, "config.json"),
            """
            {
              "window": {
                "schema": "stockroom.window-geometry",
                "version": 1,
                "units": "physical-pixels",
                "normal_bounds": {
                  "left": 100,
                  "top": 120,
                  "right": 1300,
                  "bottom": 920
                },
                "show_state": "maximized",
                "monitor": {
                  "device_name": "\\\\.\\DISPLAY1",
                  "work_area": {
                    "left": 0,
                    "top": 0,
                    "right": 1920,
                    "bottom": 1040
                  },
                  "dpi": 96
                }
              },
              "ui": {
                "theme": "light",
                "density": "compact"
              },
              "digikey_username": "not-read-by-window-host",
              "ul_private_evaluation_automation": true
            }
            """,
            new UTF8Encoding(false));

        var config = MachineWindowConfig.Load(
            new Dictionary<string, string?>
            {
                ["STOCKROOM_CONFIG_DIR"] = _temporaryRoot,
            });

        Assert.Equal(Path.GetFullPath(_temporaryRoot), config.ConfigRoot);
        Assert.Equal("light", config.Theme);
        Assert.NotNull(config.Geometry);
        Assert.Equal(
            PersistedWindowShowState.Maximized,
            config.Geometry.ShowState);
        Assert.Equal(1200, config.Geometry.NormalBounds.Width);
        Assert.Equal(@"\\.\DISPLAY1", config.Geometry.Monitor.DeviceName);
        var profile = config.ProfileDirectory(
            "window-2ed594a5e46d4fc0aecb17ca94aab32f");
        Assert.StartsWith(
            Path.Combine(_temporaryRoot, "Host State"),
            profile,
            StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public void MissingConfigUsesAnEmptyGeometryAndDarkTheme()
    {
        var config = MachineWindowConfig.Load(
            new Dictionary<string, string?>
            {
                ["STOCKROOM_CONFIG_DIR"] = _temporaryRoot,
            });

        Assert.Null(config.Geometry);
        Assert.Equal("dark", config.Theme);
    }

    [Theory]
    [InlineData("""{"window":{"schema":"stockroom.window-geometry"}}""")]
    [InlineData("""{"window":[],"ui":{"theme":"dark"}}""")]
    [InlineData("""{"window":{},"ui":{"theme":"system"}}""")]
    [InlineData("""{"window":{},"window":{},"ui":{"theme":"dark"}}""")]
    public void MalformedContinuityFailsBeforeWindowCreation(string content)
    {
        Directory.CreateDirectory(_temporaryRoot);
        File.WriteAllText(
            Path.Combine(_temporaryRoot, "config.json"),
            content,
            new UTF8Encoding(false));

        Assert.Throws<WindowHostException>(
            () => MachineWindowConfig.Load(
                new Dictionary<string, string?>
                {
                    ["STOCKROOM_CONFIG_DIR"] = _temporaryRoot,
                }));
    }

    public void Dispose()
    {
        if (Directory.Exists(_temporaryRoot))
        {
            Directory.Delete(_temporaryRoot, recursive: true);
        }
    }
}
