using System.IO;

namespace Stockroom.WindowHost.Tests;

/// <summary>
/// The shell bridge is the one part of this host that can start a program or point Windows at a
/// path, so every test here is a refusal. The behaviour being locked is not "reveal works"; it is
/// that a path the backend did not resolve inside its own root never reaches the shell.
/// </summary>
public sealed class ShellPathPolicyTests : IDisposable
{
    private readonly string _root;

    public ShellPathPolicyTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(),
            "stockroom-shell-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(_root, "component-1"));
        File.WriteAllText(Path.Combine(_root, "component-1", "symbol.kicad_sym"), "()");
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // A temp directory the test machine still holds open is not a test failure.
        }
    }

    [Fact]
    public void AcceptsADirectoryTheRootReallyContains()
    {
        var target = Path.Combine(_root, "component-1");

        Assert.Equal(
            target,
            ShellPathPolicy.RequireContained(_root, target, ShellTargetKind.Directory));
    }

    [Fact]
    public void AcceptsAFileTheRootReallyContains()
    {
        var target = Path.Combine(_root, "component-1", "symbol.kicad_sym");

        Assert.Equal(
            target,
            ShellPathPolicy.RequireContained(_root, target, ShellTargetKind.File));
    }

    [Fact]
    public void RefusesAPathThatEscapesTheRootThroughRelativeSegments()
    {
        // The exact shape the bridge exists to refuse: a path that is syntactically "inside" the
        // library root and resolves to the machine's system directory.
        var escape = Path.Combine(_root, "..", "..", "Windows", "System32");

        var failure = Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, escape, ShellTargetKind.Directory));

        Assert.Contains("canonical", failure.Message, StringComparison.Ordinal);
    }

    [Fact]
    public void RefusesAnAlreadyCanonicalPathOutsideTheRoot()
    {
        // Canonical, fully qualified, really present, and still not the caller's to reveal.
        var outside = Path.GetFullPath(
            Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows)));

        var failure = Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, outside, ShellTargetKind.Directory));

        Assert.Equal("shell path escapes its root", failure.Message);
    }

    [Fact]
    public void RefusesASiblingRootThatMerelySharesAPrefix()
    {
        // "C:\Library Extra" is not inside "C:\Library". A prefix comparison says it is.
        var sibling = _root + " Extra";
        Directory.CreateDirectory(sibling);
        try
        {
            var failure = Assert.Throws<WindowHostException>(
                () => ShellPathPolicy.RequireContained(
                    _root,
                    sibling,
                    ShellTargetKind.Directory));

            Assert.Equal("shell path escapes its root", failure.Message);
        }
        finally
        {
            Directory.Delete(sibling, recursive: true);
        }
    }

    [Theory]
    // Relative: nothing anchors it, so what it means depends on the host's working directory.
    [InlineData(@"component-1")]
    // UNC: a share is not a local path and can be anything on any machine.
    [InlineData(@"\\server\share\component-1")]
    // The Win32 device namespace bypasses normalisation entirely.
    [InlineData(@"\\?\C:\component-1")]
    [InlineData(@"\\.\PhysicalDrive0")]
    // Wildcards and quotes have no business in a resolved path.
    [InlineData(@"C:\components\*")]
    [InlineData("C:\\components\\\"quoted\"")]
    // A NUL byte truncates the string for anything below the managed layer.
    [InlineData("C:\\components\\a\0b")]
    public void RefusesEveryPathShapeThatIsNotAResolvedLocalTarget(string path)
    {
        Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, path, ShellTargetKind.Directory));
    }

    [Fact]
    public void RefusesADirectoryThatIsNotThere()
    {
        var missing = Path.Combine(_root, "component-9");

        var failure = Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, missing, ShellTargetKind.Directory));

        Assert.Equal("shell path is not an existing directory", failure.Message);
    }

    [Fact]
    public void RefusesAFileWhenADirectoryWasAskedForAndTheReverse()
    {
        var directory = Path.Combine(_root, "component-1");
        var file = Path.Combine(directory, "symbol.kicad_sym");

        Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, directory, ShellTargetKind.File));
        Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(_root, file, ShellTargetKind.Directory));
    }

    [Fact]
    public void RefusesARootThatIsNotThere()
    {
        var absentRoot = Path.Combine(_root, "no-such-library");

        var failure = Assert.Throws<WindowHostException>(
            () => ShellPathPolicy.RequireContained(
                absentRoot,
                Path.Combine(absentRoot, "component-1"),
                ShellTargetKind.Directory));

        Assert.Equal("shell root is not an existing directory", failure.Message);
    }
}

/// <summary>
/// "Open In..." must offer what this machine has and nothing else: a menu item that cannot work
/// is a dead click path, and the whole point of the item is to answer what can open the part.
/// </summary>
public sealed class EdaApplicationCatalogTests
{
    [Fact]
    public void OffersOnlyApplicationsWhoseExecutableIsReallyOnDisk()
    {
        var resolved = EdaApplicationCatalog.Resolve(
            [
                new EdaInstallationCandidate("kicad", "KiCad 9.0", "9.0.1", @"C:\KiCad\bin\kicad.exe"),
                new EdaInstallationCandidate(
                    "altium-designer",
                    "Altium Designer 25",
                    "25.0",
                    @"C:\Altium\X2.EXE"),
            ],
            path => string.Equals(path, @"C:\KiCad\bin\kicad.exe", StringComparison.Ordinal));

        Assert.Equal(["kicad"], resolved.Select(static item => item.Id));
    }

    [Fact]
    public void RefusesToNameAnApplicationOutsideTheKnownSet()
    {
        var resolved = EdaApplicationCatalog.Resolve(
            [new EdaInstallationCandidate("notepad", "Notepad", "1.0", @"C:\Windows\notepad.exe")],
            static _ => true);

        Assert.Empty(resolved);
    }

    [Fact]
    public void KeepsTheNewestBuildWhenOneMachineCarriesSeveral()
    {
        var resolved = EdaApplicationCatalog.Resolve(
            [
                new EdaInstallationCandidate("kicad", "KiCad 8.0", "8.0.6", @"C:\KiCad8\bin\kicad.exe"),
                new EdaInstallationCandidate("kicad", "KiCad 9.0", "9.0.1", @"C:\KiCad9\bin\kicad.exe"),
            ],
            static _ => true);

        var only = Assert.Single(resolved);
        Assert.Equal("KiCad 9.0", only.Name);
        Assert.Equal(@"C:\KiCad9\bin\kicad.exe", only.ExecutablePath);
    }
}

/// <summary>
/// The surface that actually starts things. The process launch is injected so the refusals can be
/// proved without a test opening Explorer or an EDA application on the machine running them.
/// </summary>
public sealed class WindowsShellSurfaceTests : IDisposable
{
    private readonly string _root;
    private readonly List<string> _started = [];
    private readonly WindowsShellSurface _surface;

    public WindowsShellSurfaceTests()
    {
        _root = Path.Combine(
            Path.GetTempPath(),
            "stockroom-shell-surface-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(Path.Combine(_root, "component-1"));
        File.WriteAllText(Path.Combine(_root, "component-1", "symbol.kicad_sym"), "()");
        _surface = new WindowsShellSurface(
            probe: () =>
            [
                new EdaInstallationCandidate("kicad", "KiCad 9.0", "9.0.1", @"C:\KiCad\bin\kicad.exe"),
            ],
            executableExists: static _ => true,
            start: (fileName, arguments) =>
                _started.Add(fileName + "|" + string.Join("|", arguments)));
    }

    public void Dispose()
    {
        try
        {
            Directory.Delete(_root, recursive: true);
        }
        catch (IOException)
        {
            // See ShellPathPolicyTests.Dispose.
        }
    }

    [Fact]
    public void RevealsTheComponentDirectoryInTheFileBrowser()
    {
        var target = Path.Combine(_root, "component-1");

        _surface.RevealDirectory(_root, target);

        var started = Assert.Single(_started);
        Assert.EndsWith("explorer.exe|" + target, started, StringComparison.Ordinal);
    }

    [Fact]
    public void RefusesToRevealAPathOutsideTheRootTheBackendResolved()
    {
        Assert.Throws<WindowHostException>(
            () => _surface.RevealDirectory(
                _root,
                Environment.GetFolderPath(Environment.SpecialFolder.Windows)));

        Assert.Empty(_started);
    }

    [Fact]
    public void OpensAComponentFileInADetectedApplication()
    {
        var target = Path.Combine(_root, "component-1", "symbol.kicad_sym");

        _surface.OpenFileWith("kicad", _root, target);

        Assert.Equal([@"C:\KiCad\bin\kicad.exe|" + target], _started);
    }

    [Fact]
    public void RefusesAnApplicationThisMachineDoesNotHave()
    {
        var target = Path.Combine(_root, "component-1", "symbol.kicad_sym");

        var failure = Assert.Throws<WindowHostException>(
            () => _surface.OpenFileWith("altium-designer", _root, target));

        Assert.Equal(
            "the requested EDA application is not installed on this machine",
            failure.Message);
        Assert.Empty(_started);
    }

    [Fact]
    public void RefusesAnApplicationIdItDoesNotRecognise()
    {
        var target = Path.Combine(_root, "component-1", "symbol.kicad_sym");

        var failure = Assert.Throws<WindowHostException>(
            () => _surface.OpenFileWith(@"C:\Windows\System32\cmd.exe", _root, target));

        Assert.Equal("application id is not a known EDA application", failure.Message);
        Assert.Empty(_started);
    }

    [Fact]
    public void RefusesToOpenAFileOutsideTheRootTheBackendResolved()
    {
        Assert.Throws<WindowHostException>(
            () => _surface.OpenFileWith(
                "kicad",
                _root,
                Path.Combine(
                    Environment.GetFolderPath(Environment.SpecialFolder.Windows),
                    "System32",
                    "cmd.exe")));

        Assert.Empty(_started);
    }
}
