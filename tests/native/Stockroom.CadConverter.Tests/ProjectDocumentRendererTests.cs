using System.Security.Cryptography;
using System.Text.Json;

namespace Stockroom.CadConverter.Tests;

public sealed class ProjectDocumentRendererTests
{
    [Fact]
    public async Task RendersRealSchematicAndBoardWithoutChangingSources()
    {
        using var scope = new ProjectScope();
        var before = scope.SourceHashes();

        var result = await ProjectDocumentRenderer.RenderAsync(scope.Request());

        Assert.Equal("ok", result.Status);
        Assert.Equal(3, result.Artifacts.Count);
        Assert.Equal(["sheet", "top", "bottom"], result.Artifacts.Select(item => item.View));
        Assert.Equal(before, scope.SourceHashes());
        Assert.All(result.Artifacts, artifact =>
        {
            var path = Path.GetFullPath(artifact.Path);
            Assert.StartsWith(Path.GetFullPath(scope.Output) + Path.DirectorySeparatorChar, path);
            Assert.Equal("image/svg+xml", artifact.MediaType);
            Assert.Equal(1600, artifact.Width);
            Assert.Equal(1000, artifact.Height);
            Assert.Equal(new FileInfo(path).Length, artifact.SizeBytes);
            Assert.Equal(Hash(path), artifact.Sha256);
            Assert.Contains("<svg", File.ReadAllText(path), StringComparison.OrdinalIgnoreCase);
        });
    }

    [Fact]
    public async Task JsonBoundaryDispatchesProjectRenderSchema()
    {
        using var scope = new ProjectScope();
        var requestPath = Path.Combine(scope.Root, "Request.json");
        var resultPath = Path.Combine(scope.Root, "Result.json");
        await File.WriteAllTextAsync(
            requestPath,
            JsonSerializer.Serialize(scope.Request(), CadConverterJsonContext.Default.ProjectRenderRequest));

        var exitCode = await CadConverterApplication.ConvertFileAsync(requestPath, resultPath);

        Assert.Equal(0, exitCode);
        var result = JsonSerializer.Deserialize(
            await File.ReadAllTextAsync(resultPath),
            CadConverterJsonContext.Default.ProjectRenderResult);
        Assert.NotNull(result);
        Assert.Equal(ProjectRenderResult.CurrentSchema, result.Schema);
        Assert.Equal("ok", result.Status);
        Assert.Equal(3, result.Artifacts.Count);
    }

    [Fact]
    public async Task RejectsDocumentOutsideProjectRootBeforeWritingOutput()
    {
        using var scope = new ProjectScope();
        var outside = Path.Combine(scope.Root, "Outside.SchDoc");
        File.Copy(scope.Schematic, outside);
        var request = scope.Request() with { Documents = ["..\\Outside.SchDoc"] };

        var error = await Assert.ThrowsAsync<CadConverterException>(
            () => ProjectDocumentRenderer.RenderAsync(request));

        Assert.Contains("project root", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(Directory.Exists(scope.Output));
    }

    private static string Hash(string path) =>
        Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(path))).ToLowerInvariant();

    private sealed class ProjectScope : IDisposable
    {
        internal ProjectScope()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Stockroom-ProjectRender-{Guid.NewGuid():N}");
            Project = Path.Combine(Root, "Project");
            Output = Path.Combine(Root, "Output");
            Directory.CreateDirectory(Project);
            Schematic = CopyFixture("USB Power.SchDoc");
            Board = CopyFixture("USB Power Adapter.PcbDoc");
        }

        internal string Root { get; }
        internal string Project { get; }
        internal string Output { get; }
        internal string Schematic { get; }
        internal string Board { get; }

        internal ProjectRenderRequest Request() => new()
        {
            Schema = ProjectRenderRequest.CurrentSchema,
            ProjectRoot = Project,
            OutputDirectory = Output,
            Documents = [Path.GetFileName(Schematic), Path.GetFileName(Board)],
            Width = 1600,
            Height = 1000,
        };

        internal string[] SourceHashes() => [Hash(Schematic), Hash(Board)];

        private string CopyFixture(string name)
        {
            var destination = Path.Combine(Project, name);
            File.Copy(Path.Combine(AppContext.BaseDirectory, "Fixtures", name), destination);
            return destination;
        }

        public void Dispose() => Directory.Delete(Root, recursive: true);
    }
}
