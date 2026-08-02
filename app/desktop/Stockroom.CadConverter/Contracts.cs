using System.Text.Json.Serialization;

namespace Stockroom.CadConverter;

public sealed record CadConverterRequest
{
    public const string CurrentSchema = "stockroom.cad-converter/request/1";

    public required string Schema { get; init; }
    public required string OutputDirectory { get; init; }
    public required string OutputStem { get; init; }
    public required string Manufacturer { get; init; }
    public required string Mpn { get; init; }
    public required string DefaultFootprint { get; init; }
    public required IReadOnlyList<PadPinMapDefinition> PadPinMap { get; init; }
    public required SymbolDefinition Symbol { get; init; }
    public required IReadOnlyList<FootprintDefinition> Footprints { get; init; }
}

public sealed record PadPinMapDefinition
{
    public required string Pad { get; init; }
    public required string Pin { get; init; }
}

public sealed record SymbolDefinition
{
    public required string Name { get; init; }
    public required string Description { get; init; }
    public required string DesignatorPrefix { get; init; }
    public required IReadOnlyList<SymbolPinDefinition> Pins { get; init; }
    public IReadOnlyList<SymbolLineDefinition> Lines { get; init; } = [];
    public IReadOnlyList<SymbolRectangleDefinition> Rectangles { get; init; } = [];
    public IReadOnlyList<SymbolPolylineDefinition> Polylines { get; init; } = [];
    public IReadOnlyList<SymbolArcDefinition> Arcs { get; init; } = [];
    public IReadOnlyList<SymbolEllipseDefinition> Ellipses { get; init; } = [];
    public IReadOnlyList<SymbolLabelDefinition> Labels { get; init; } = [];
    public IReadOnlyList<SymbolParameterDefinition> Parameters { get; init; } = [];
}

public sealed record SymbolPinDefinition
{
    public required string Designator { get; init; }
    public required string Name { get; init; }
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double LengthMm { get; init; }
    public required string Orientation { get; init; }
    public required string ElectricalType { get; init; }
    public bool ShowName { get; init; } = true;
    public bool ShowDesignator { get; init; } = true;
}

public sealed record SymbolLineDefinition
{
    public required double X1mm { get; init; }
    public required double Y1mm { get; init; }
    public required double X2mm { get; init; }
    public required double Y2mm { get; init; }
    public required double WidthMm { get; init; }
    public int Color { get; init; } = 0xFF0000;
}

public sealed record SymbolRectangleDefinition
{
    public required double X1mm { get; init; }
    public required double Y1mm { get; init; }
    public required double X2mm { get; init; }
    public required double Y2mm { get; init; }
    public required double WidthMm { get; init; }
    public bool Filled { get; init; }
    public int Color { get; init; } = 0xFF0000;
    public int FillColor { get; init; } = 0xFFFFFF;
}

public sealed record SymbolPolylineDefinition
{
    public required IReadOnlyList<PointDefinition> Points { get; init; }
    public int LineWidth { get; init; }
    public int Color { get; init; } = 0xFF0000;
}

public sealed record SymbolArcDefinition
{
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double RadiusMm { get; init; }
    public required double StartAngle { get; init; }
    public required double EndAngle { get; init; }
    public int LineWidth { get; init; }
    public int Color { get; init; } = 0xFF0000;
}

public sealed record SymbolEllipseDefinition
{
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double RadiusXmm { get; init; }
    public required double RadiusYmm { get; init; }
    public int LineWidth { get; init; }
    public bool Filled { get; init; }
    public int Color { get; init; } = 0xFF0000;
    public int FillColor { get; init; } = 0xFFFFFF;
}

public sealed record SymbolLabelDefinition
{
    public required string Text { get; init; }
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public int Orientation { get; init; }
    public int Color { get; init; } = 0x800000;
}

public sealed record SymbolParameterDefinition
{
    public required string Name { get; init; }
    public required string Value { get; init; }
    public double Xmm { get; init; }
    public double Ymm { get; init; }
    public bool Visible { get; init; }
}

public sealed record FootprintDefinition
{
    public required string Name { get; init; }
    public required string Description { get; init; }
    public required IReadOnlyList<PadDefinition> Pads { get; init; }
    public IReadOnlyList<FootprintLineDefinition> Lines { get; init; } = [];
    public IReadOnlyList<FootprintArcDefinition> Arcs { get; init; } = [];
    public IReadOnlyList<FootprintTextDefinition> Texts { get; init; } = [];
    public IReadOnlyList<FootprintFillDefinition> Fills { get; init; } = [];
    public IReadOnlyDictionary<string, string> Parameters { get; init; } =
        new Dictionary<string, string>();
    public StepModelDefinition? Model { get; init; }
}

public sealed record PadDefinition
{
    public required string Designator { get; init; }
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double SizeXmm { get; init; }
    public required double SizeYmm { get; init; }
    public double HoleSizeMm { get; init; }
    public double Rotation { get; init; }
    public int Layer { get; init; } = 1;
    public string Shape { get; init; } = "round";
    public string HoleType { get; init; } = "round";
    public bool Plated { get; init; } = true;
}

public sealed record FootprintLineDefinition
{
    public required double X1mm { get; init; }
    public required double Y1mm { get; init; }
    public required double X2mm { get; init; }
    public required double Y2mm { get; init; }
    public required double WidthMm { get; init; }
    public required int Layer { get; init; }
}

public sealed record FootprintArcDefinition
{
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double RadiusMm { get; init; }
    public required double StartAngle { get; init; }
    public required double EndAngle { get; init; }
    public required double WidthMm { get; init; }
    public required int Layer { get; init; }
}

public sealed record FootprintTextDefinition
{
    public required string Text { get; init; }
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
    public required double HeightMm { get; init; }
    public required double StrokeWidthMm { get; init; }
    public required int Layer { get; init; }
    public double Rotation { get; init; }
    public bool Mirrored { get; init; }
}

public sealed record FootprintFillDefinition
{
    public required double X1mm { get; init; }
    public required double Y1mm { get; init; }
    public required double X2mm { get; init; }
    public required double Y2mm { get; init; }
    public required int Layer { get; init; }
    public double Rotation { get; init; }
}

public sealed record StepModelDefinition
{
    public required string Path { get; init; }
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required IReadOnlyList<PointDefinition> BodyOutline { get; init; }
    public double Xmm { get; init; }
    public double Ymm { get; init; }
    public double OffsetZmm { get; init; }
    public double Rotation2D { get; init; }
    public double RotationX { get; init; }
    public double RotationY { get; init; }
    public double RotationZ { get; init; }
    public double OverallHeightMm { get; init; }
}

public sealed record PointDefinition
{
    public required double Xmm { get; init; }
    public required double Ymm { get; init; }
}

public sealed record CadConverterResult
{
    public const string CurrentSchema = "stockroom.cad-converter/result/1";

    public required string Schema { get; init; }
    public required string Status { get; init; }
    public required string Detail { get; init; }
    public string WriterApi { get; init; } = "OriginalCircuit.Altium/v2";
    public ArtifactResult? Schlib { get; init; }
    public ArtifactResult? Pcblib { get; init; }
    public IReadOnlyList<string> SymbolEntries { get; init; } = [];
    public IReadOnlyList<string> FootprintEntries { get; init; } = [];
    public IReadOnlyList<ModelResult> EmbeddedModels { get; init; } = [];
}

public sealed record ArtifactResult
{
    public required string Path { get; init; }
    public required long SizeBytes { get; init; }
    public required string Sha256 { get; init; }
}

public sealed record ModelResult
{
    public required string Id { get; init; }
    public required string Name { get; init; }
    public required string Sha256 { get; init; }
}

[JsonSourceGenerationOptions(
    PropertyNamingPolicy = JsonKnownNamingPolicy.CamelCase,
    WriteIndented = true,
    UnmappedMemberHandling = JsonUnmappedMemberHandling.Disallow)]
[JsonSerializable(typeof(CadConverterRequest))]
[JsonSerializable(typeof(CadConverterResult))]
public sealed partial class CadConverterJsonContext : JsonSerializerContext;
