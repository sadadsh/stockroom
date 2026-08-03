using System.Text.Json;
using OriginalCircuit.Altium.Models.Pcb;
using OriginalCircuit.Altium.Models.Sch;
using OriginalCircuit.Altium.Serialization.Readers;

namespace Stockroom.CadConverter.Tests;

public sealed class CadLibraryConverterTests
{
    [Fact]
    public async Task FullRequestWritesReadableNativeLibrariesAndEmbeddedStep()
    {
        using var scope = new TestScope();
        var request = scope.Request();

        var result = await CadLibraryConverter.ConvertAsync(request);

        Assert.Equal("ok", result.Status);
        Assert.NotNull(result.Schlib);
        Assert.NotNull(result.Pcblib);
        Assert.Equal(["ABM13W_SYMBOL"], result.SymbolEntries);
        Assert.Equal(["ABM13W_ABR", "ABM13W_ABR-M"], result.FootprintEntries);
        Assert.Single(result.EmbeddedModels);
        Assert.Equal(64, result.Schlib.Sha256.Length);
        Assert.Equal(64, result.Pcblib.Sha256.Length);

        var schlib = await new SchLibReader().ReadAsync(result.Schlib.Path);
        var symbol = Assert.IsType<SchComponent>(Assert.Single(schlib.Components));
        Assert.Equal("ABM13W_SYMBOL", symbol.Name);
        Assert.Equal(4, symbol.AllPinCount);
        Assert.Equal(4, symbol.Pins.Count);
        Assert.All(symbol.Pins, pin => Assert.Equal(1, ((SchPin)pin).OwnerPartId));
        Assert.False(((SchPin)symbol.Pins[0]).ShowName);
        Assert.True(((SchPin)symbol.Pins[0]).ShowDesignator);
        Assert.Single(symbol.Lines);
        Assert.Equal(1, ((SchLine)symbol.Lines[0]).OwnerPartId);
        Assert.Single(symbol.Rectangles);
        Assert.Single(symbol.Polylines);
        Assert.Single(symbol.Arcs);
        Assert.Single(symbol.Ellipses);
        Assert.Single(symbol.Labels);
        Assert.Contains(symbol.Parameters, item => item.Name == "Manufacturer" && item.Value == "Abracon");
        Assert.Contains(symbol.Parameters, item => item.Name == "Manufacturer Part Number" && item.Value == "ABM13W-32.0000MHZ-5-DH7G-T5");
        var implementation = Assert.Single(symbol.Implementations);
        Assert.Equal("ABM13W_ABR", implementation.ModelName);
        Assert.Equal("PCBLIB", implementation.ModelType);
        Assert.True(implementation.IsCurrent);
        Assert.Equal(4, implementation.MapDefiners.Count);

        var pcblib = await new PcbLibReader().ReadAsync(result.Pcblib.Path);
        Assert.Equal(2, pcblib.Components.Count);
        Assert.NotNull(pcblib.LibraryParametersOrdered);
        Assert.True(pcblib.LibraryParametersOrdered.Count > 100);
        Assert.Contains(
            pcblib.LibraryParametersOrdered,
            item => string.Equals(item.Key, "FILENAME", StringComparison.OrdinalIgnoreCase)
                && item.Value == "ABM13W.PcbLib");
        var footprint = Assert.IsType<PcbComponent>(pcblib["ABM13W_ABR"]);
        Assert.Null(footprint.AdditionalParameters);
        Assert.Equal(4, footprint.Pads.Count);
        Assert.Single(footprint.Tracks);
        Assert.Single(footprint.Arcs);
        Assert.Single(footprint.Texts);
        Assert.Single(footprint.Fills);
        var body = Assert.IsType<PcbComponentBody>(Assert.Single(footprint.ComponentBodies));
        Assert.Equal("ABM13W-32MHz.step", body.ModelName);
        Assert.Matches("^\\{[0-9A-F]{8}(?:-[0-9A-F]{4}){3}-[0-9A-F]{12}\\}$", body.ModelId);
        Assert.Equal("Undefined", body.ModelSource);
        var model = Assert.Single(pcblib.Models);
        Assert.Equal(body.ModelId, model.Id);
        Assert.Equal(unchecked((uint)model.Checksum), body.ModelChecksum);
        Assert.Equal("{AD596804-07F6-7473-8969-A5EA0CFEAE18}", model.Id);
        Assert.Equal(scope.StepText, model.StepData);
        Assert.NotEqual(0, model.Checksum);
    }

    [Fact]
    public async Task JsonBoundaryWritesAResultDocumentAndRejectsUnknownFields()
    {
        using var scope = new TestScope();
        var requestPath = Path.Combine(scope.Root, "Request.json");
        var resultPath = Path.Combine(scope.Root, "Result.json");
        await File.WriteAllTextAsync(
            requestPath,
            JsonSerializer.Serialize(
                scope.Request() with { OutputDirectory = Path.Combine(scope.Root, "Json Output") },
                CadConverterJsonContext.Default.CadConverterRequest));

        var exitCode = await CadConverterApplication.ConvertFileAsync(requestPath, resultPath);

        Assert.Equal(0, exitCode);
        var result = JsonSerializer.Deserialize(
            await File.ReadAllTextAsync(resultPath),
            CadConverterJsonContext.Default.CadConverterResult);
        Assert.NotNull(result);
        Assert.Equal("ok", result.Status);

        var invalidPath = Path.Combine(scope.Root, "Invalid.json");
        var json = await File.ReadAllTextAsync(requestPath);
        await File.WriteAllTextAsync(invalidPath, json.Replace("\"schema\":", "\"unknown\": true, \"schema\":", StringComparison.Ordinal));
        Assert.Equal(1, await CadConverterApplication.ConvertFileAsync(invalidPath, resultPath));
        var failed = JsonSerializer.Deserialize(
            await File.ReadAllTextAsync(resultPath),
            CadConverterJsonContext.Default.CadConverterResult);
        Assert.NotNull(failed);
        Assert.Equal("error", failed.Status);
        Assert.Contains("unknown", failed.Detail, StringComparison.OrdinalIgnoreCase);
    }

    [Fact]
    public async Task InvalidPadIdentityFailsBeforeWritingAnyOutput()
    {
        using var scope = new TestScope();
        var request = scope.Request();
        var duplicate = request.Footprints[0].Pads[0] with { Xmm = 9 };
        request = request with
        {
            Footprints =
            [
                request.Footprints[0] with
                {
                    Pads = [.. request.Footprints[0].Pads, duplicate],
                },
            ],
        };

        var error = await Assert.ThrowsAsync<CadConverterException>(
            () => CadLibraryConverter.ConvertAsync(request));

        Assert.Contains("pad designators", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(Directory.Exists(request.OutputDirectory));
    }

    [Fact]
    public async Task UnmappedPhysicalThermalPadIsPreservedWithoutInventingASymbolPin()
    {
        using var scope = new TestScope();
        var request = scope.Request();
        var thermalVia = new PadDefinition
        {
            Designator = "18",
            Xmm = 0,
            Ymm = 0,
            SizeXmm = 0.5,
            SizeYmm = 0.5,
            HoleSizeMm = 0.25,
            Layer = 74,
            Shape = "round",
            HoleType = "round",
            Plated = true,
        };
        request = request with
        {
            Footprints = request.Footprints
                .Select(item => item with { Pads = [.. item.Pads, thermalVia] })
                .ToArray(),
        };

        var result = await CadLibraryConverter.ConvertAsync(request);

        var schlib = await new SchLibReader().ReadAsync(result.Schlib!.Path);
        var symbol = Assert.IsType<SchComponent>(Assert.Single(schlib.Components));
        Assert.Equal(4, Assert.Single(symbol.Implementations).MapDefiners.Count);
        var pcblib = await new PcbLibReader().ReadAsync(result.Pcblib!.Path);
        var footprint = Assert.IsType<PcbComponent>(pcblib[request.DefaultFootprint]);
        Assert.Equal(5, footprint.Pads.Count);
        Assert.Contains(footprint.Pads, pad => pad.Designator == "18");
    }

    [Fact]
    public async Task InvalidUtf8StepFailsCleanlyWithoutWritingLibraries()
    {
        using var scope = new TestScope();
        await File.WriteAllBytesAsync(
            scope.StepPath,
            [.. "ISO-10303-21;\nDATA;\n"u8.ToArray(), 0xFF, .. "\nENDSEC;\nEND-ISO-10303-21;\n"u8.ToArray()]);
        var request = scope.Request();

        var error = await Assert.ThrowsAsync<CadConverterException>(
            () => CadLibraryConverter.ConvertAsync(request));

        Assert.Contains("valid UTF-8", error.Message, StringComparison.OrdinalIgnoreCase);
        Assert.False(Directory.Exists(request.OutputDirectory));
    }

    private sealed class TestScope : IDisposable
    {
        internal TestScope()
        {
            Root = Path.Combine(Path.GetTempPath(), $"Stockroom-CadConverter-{Guid.NewGuid():N}");
            Directory.CreateDirectory(Root);
            StepPath = Path.Combine(Root, "ABM13W-32MHz.step");
            File.WriteAllText(StepPath, StepText);
        }

        internal string Root { get; }
        internal string StepPath { get; }
        internal string StepText { get; } =
            "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION(('Stockroom test'),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n";

        internal CadConverterRequest Request() => new()
        {
            Schema = CadConverterRequest.CurrentSchema,
            OutputDirectory = Path.Combine(Root, "Output"),
            OutputStem = "ABM13W",
            Manufacturer = "Abracon",
            Mpn = "ABM13W-32.0000MHZ-5-DH7G-T5",
            DefaultFootprint = "ABM13W_ABR",
            PadPinMap =
            [
                new PadPinMapDefinition { Pad = "1", Pin = "1" },
                new PadPinMapDefinition { Pad = "2", Pin = "2" },
                new PadPinMapDefinition { Pad = "3", Pin = "3" },
                new PadPinMapDefinition { Pad = "4", Pin = "4" },
            ],
            Symbol = new SymbolDefinition
            {
                Name = "ABM13W_SYMBOL",
                Description = "32 MHz crystal",
                DesignatorPrefix = "Y",
                Pins =
                [
                    Pin("1", "X1", -5.08, 0, "right") with
                    {
                        ShowName = false,
                        ShowDesignator = true,
                    },
                    Pin("2", "GND", 0, -5.08, "up"),
                    Pin("3", "X2", 5.08, 0, "left"),
                    Pin("4", "GND", 0, 5.08, "down"),
                ],
                Lines = [new SymbolLineDefinition { X1mm = -2, Y1mm = -2, X2mm = 2, Y2mm = -2, WidthMm = 0.2 }],
                Rectangles = [new SymbolRectangleDefinition { X1mm = -2, Y1mm = -2, X2mm = 2, Y2mm = 2, WidthMm = 0.2 }],
                Polylines = [new SymbolPolylineDefinition { Points = [Point(-1, 0), Point(0, 1), Point(1, 0)], LineWidth = 1 }],
                Arcs = [new SymbolArcDefinition { Xmm = 0, Ymm = 0, RadiusMm = 1, StartAngle = 0, EndAngle = 180, LineWidth = 1 }],
                Ellipses = [new SymbolEllipseDefinition { Xmm = 0, Ymm = 0, RadiusXmm = 1, RadiusYmm = 0.5, LineWidth = 1 }],
                Labels = [new SymbolLabelDefinition { Text = "32MHz", Xmm = 0, Ymm = 3 }],
                Parameters = [new SymbolParameterDefinition { Name = "Value", Value = "32MHz", Visible = true }],
            },
            Footprints =
            [
                Footprint("ABM13W_ABR", includeGraphics: true),
                Footprint("ABM13W_ABR-M", includeGraphics: false),
            ],
        };

        private FootprintDefinition Footprint(string name, bool includeGraphics) => new()
        {
            Name = name,
            Description = "3.2 x 2.5 mm crystal",
            Pads =
            [
                Pad("1", -1.1, 0.85),
                Pad("2", 1.1, 0.85),
                Pad("3", 1.1, -0.85),
                Pad("4", -1.1, -0.85),
            ],
            Lines = includeGraphics ? [new FootprintLineDefinition { X1mm = -1.6, Y1mm = -1.25, X2mm = 1.6, Y2mm = -1.25, WidthMm = 0.15, Layer = 21 }] : [],
            Arcs = includeGraphics ? [new FootprintArcDefinition { Xmm = 0, Ymm = 0, RadiusMm = 1.5, StartAngle = 0, EndAngle = 90, WidthMm = 0.15, Layer = 21 }] : [],
            Texts = includeGraphics ? [new FootprintTextDefinition { Text = ".Designator", Xmm = 0, Ymm = 2, HeightMm = 0.8, StrokeWidthMm = 0.12, Layer = 21 }] : [],
            Fills = includeGraphics ? [new FootprintFillDefinition { X1mm = -0.2, Y1mm = -0.2, X2mm = 0.2, Y2mm = 0.2, Layer = 21 }] : [],
            Parameters = new Dictionary<string, string> { ["Package"] = "4-SMD" },
            Model = new StepModelDefinition
            {
                Path = StepPath,
                Id = "{AD596804-07F6-7473-8969-A5EA0CFEAE18}",
                Name = "ABM13W-32MHz.step",
                BodyOutline = [Point(-1.6, -1.25), Point(1.6, -1.25), Point(1.6, 1.25), Point(-1.6, 1.25)],
                OverallHeightMm = 0.8,
            },
        };

        private static SymbolPinDefinition Pin(string designator, string name, double x, double y, string orientation) => new()
        {
            Designator = designator,
            Name = name,
            Xmm = x,
            Ymm = y,
            LengthMm = 2.54,
            Orientation = orientation,
            ElectricalType = "passive",
        };

        private static PadDefinition Pad(string designator, double x, double y) => new()
        {
            Designator = designator,
            Xmm = x,
            Ymm = y,
            SizeXmm = 1.4,
            SizeYmm = 1.1,
            Layer = 1,
            Shape = "rectangular",
        };

        private static PointDefinition Point(double x, double y) => new() { Xmm = x, Ymm = y };

        public void Dispose()
        {
            Directory.Delete(Root, recursive: true);
        }
    }
}
