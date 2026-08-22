using System.Globalization;
using System.Text.RegularExpressions;

namespace Stockroom.CadConverter;

internal static partial class ConversionValidation
{
    private const double CoordinateLimitMm = 1_000_000;
    internal const long MaximumStepBytes = 128L * 1024 * 1024;

    internal static void RequireValid(CadConverterRequest request)
    {
        ArgumentNullException.ThrowIfNull(request);
        Require(request.Schema == CadConverterRequest.CurrentSchema, "unsupported request schema");
        RequireText(request.OutputDirectory, "outputDirectory", 1024);
        RequireText(request.OutputStem, "outputStem", 100);
        Require(OutputStemRegex().IsMatch(request.OutputStem) && !request.OutputStem.Contains("..", StringComparison.Ordinal),
            "outputStem must be a bounded filename-safe identifier");
        RequireText(request.Manufacturer, "manufacturer", 255);
        RequireText(request.Mpn, "mpn", 255);
        RequireText(request.DefaultFootprint, "defaultFootprint", 255);

        var output = Path.GetFullPath(request.OutputDirectory);
        Require(!File.Exists(output), "outputDirectory cannot be a file");
        Require(!Directory.Exists(output) || !Directory.EnumerateFileSystemEntries(output).Any(),
            "outputDirectory must be new or empty");

        ValidateSymbol(request.Symbol);
        Require(request.Footprints.Count > 0, "at least one footprint is required");
        RequireUnique(request.Footprints.Select(item => item.Name), "footprint names");
        Require(request.Footprints.Any(item => string.Equals(item.Name, request.DefaultFootprint, StringComparison.OrdinalIgnoreCase)),
            "defaultFootprint must name one supplied footprint");
        Require(request.PadPinMap.Count > 0, "padPinMap cannot be empty");
        RequireUnique(request.PadPinMap.Select(item => item.Pad), "padPinMap pads");
        RequireUnique(request.PadPinMap.Select(item => item.Pin), "padPinMap pins");
        var symbolPins = request.Symbol.Pins.Select(item => item.Designator).ToHashSet(StringComparer.OrdinalIgnoreCase);
        var defaultPads = request.Footprints
            .Single(item => string.Equals(item.Name, request.DefaultFootprint, StringComparison.OrdinalIgnoreCase))
            .Pads.Select(item => item.Designator).ToHashSet(StringComparer.OrdinalIgnoreCase);
        Require(request.PadPinMap.Select(item => item.Pin).ToHashSet(StringComparer.OrdinalIgnoreCase).SetEquals(symbolPins),
            "padPinMap must close over every symbol pin");
        var mappedPads = request.PadPinMap.Select(item => item.Pad).ToHashSet(StringComparer.OrdinalIgnoreCase);
        Require(mappedPads.IsSubsetOf(defaultPads),
            "padPinMap refers to a pad absent from the default footprint");
        foreach (var footprint in request.Footprints)
        {
            ValidateFootprint(footprint);
        }
    }

    private static void ValidateSymbol(SymbolDefinition symbol)
    {
        RequireText(symbol.Name, "symbol.name", 255);
        RequireText(symbol.Description, "symbol.description", 1024);
        RequireText(symbol.DesignatorPrefix, "symbol.designatorPrefix", 32);
        Require(symbol.PartCount is >= 1 and <= 255, "symbol partCount must be 1 through 255");
        Require(symbol.Pins.Count > 0, "symbol requires at least one pin");
        RequireUnique(symbol.Pins.Select(item => item.Designator), "symbol pin designators");
        foreach (var pin in symbol.Pins)
        {
            RequireOwnerPart(pin.OwnerPartId, symbol.PartCount, "symbol pin");
            RequireText(pin.Designator, "symbol pin designator", 64);
            RequireText(pin.Name, "symbol pin name", 255, allowEmpty: true);
            RequireCoordinate(pin.Xmm, "symbol pin x");
            RequireCoordinate(pin.Ymm, "symbol pin y");
            RequirePositive(pin.LengthMm, "symbol pin length");
            Require(Orientations.Contains(pin.Orientation), $"unsupported pin orientation: {pin.Orientation}");
            Require(ElectricalTypes.Contains(pin.ElectricalType), $"unsupported pin electrical type: {pin.ElectricalType}");
        }

        foreach (var line in symbol.Lines)
        {
            RequireOwnerPart(line.OwnerPartId, symbol.PartCount, "symbol line");
            RequireCoordinates(line.X1mm, line.Y1mm, line.X2mm, line.Y2mm, "symbol line");
            RequireNonNegative(line.WidthMm, "symbol line width");
        }
        foreach (var rectangle in symbol.Rectangles)
        {
            RequireOwnerPart(rectangle.OwnerPartId, symbol.PartCount, "symbol rectangle");
            RequireCoordinates(rectangle.X1mm, rectangle.Y1mm, rectangle.X2mm, rectangle.Y2mm, "symbol rectangle");
            RequirePositive(rectangle.WidthMm, "symbol rectangle width");
        }
        foreach (var polyline in symbol.Polylines)
        {
            RequireOwnerPart(polyline.OwnerPartId, symbol.PartCount, "symbol polyline");
            Require(polyline.Points.Count >= 2, "symbol polyline requires at least two points");
            Require(polyline.LineWidth is >= 0 and <= 2, "symbol polyline lineWidth must be 0, 1, or 2");
            ValidatePoints(polyline.Points, "symbol polyline");
        }
        foreach (var arc in symbol.Arcs)
        {
            RequireOwnerPart(arc.OwnerPartId, symbol.PartCount, "symbol arc");
            RequireCoordinate(arc.Xmm, "symbol arc x");
            RequireCoordinate(arc.Ymm, "symbol arc y");
            RequirePositive(arc.RadiusMm, "symbol arc radius");
            RequireAngle(arc.StartAngle, "symbol arc start angle");
            RequireAngle(arc.EndAngle, "symbol arc end angle");
            Require(arc.LineWidth is >= 0 and <= 2, "symbol arc lineWidth must be 0, 1, or 2");
        }
        foreach (var ellipse in symbol.Ellipses)
        {
            RequireOwnerPart(ellipse.OwnerPartId, symbol.PartCount, "symbol ellipse");
            RequireCoordinate(ellipse.Xmm, "symbol ellipse x");
            RequireCoordinate(ellipse.Ymm, "symbol ellipse y");
            RequirePositive(ellipse.RadiusXmm, "symbol ellipse x radius");
            RequirePositive(ellipse.RadiusYmm, "symbol ellipse y radius");
            Require(ellipse.LineWidth is >= 0 and <= 2, "symbol ellipse lineWidth must be 0, 1, or 2");
        }
        foreach (var label in symbol.Labels)
        {
            RequireOwnerPart(label.OwnerPartId, symbol.PartCount, "symbol label");
            RequireText(label.Text, "symbol label", 1024, allowEmpty: true);
            RequireCoordinate(label.Xmm, "symbol label x");
            RequireCoordinate(label.Ymm, "symbol label y");
            Require(label.Orientation is >= 0 and <= 3, "symbol label orientation must be 0 through 3");
        }
        RequireUnique(symbol.Parameters.Select(item => item.Name), "symbol parameter names");
        foreach (var parameter in symbol.Parameters)
        {
            RequireText(parameter.Name, "symbol parameter name", 255);
            RequireText(parameter.Value, "symbol parameter value", 4096, allowEmpty: true);
            RequireCoordinate(parameter.Xmm, "symbol parameter x");
            RequireCoordinate(parameter.Ymm, "symbol parameter y");
        }
    }

    private static void ValidateFootprint(FootprintDefinition footprint)
    {
        RequireText(footprint.Name, "footprint.name", 255);
        RequireText(footprint.Description, "footprint.description", 1024);
        Require(footprint.Pads.Count > 0, $"footprint {footprint.Name} requires at least one pad");
        foreach (var pad in footprint.Pads)
        {
            RequireText(pad.Designator, "pad designator", 64);
            RequireCoordinate(pad.Xmm, "pad x");
            RequireCoordinate(pad.Ymm, "pad y");
            RequirePositive(pad.SizeXmm, "pad x size");
            RequirePositive(pad.SizeYmm, "pad y size");
            RequireNonNegative(pad.HoleSizeMm, "pad hole size");
            RequireAngle(pad.Rotation, "pad rotation");
            RequireLayer(pad.Layer);
            Require(PadShapes.Contains(pad.Shape), $"unsupported pad shape: {pad.Shape}");
            Require(HoleTypes.Contains(pad.HoleType), $"unsupported pad hole type: {pad.HoleType}");
        }
        foreach (var line in footprint.Lines)
        {
            RequireCoordinates(line.X1mm, line.Y1mm, line.X2mm, line.Y2mm, "footprint line");
            RequirePositive(line.WidthMm, "footprint line width");
            RequireLayer(line.Layer);
        }
        foreach (var arc in footprint.Arcs)
        {
            RequireCoordinate(arc.Xmm, "footprint arc x");
            RequireCoordinate(arc.Ymm, "footprint arc y");
            RequirePositive(arc.RadiusMm, "footprint arc radius");
            RequirePositive(arc.WidthMm, "footprint arc width");
            RequireAngle(arc.StartAngle, "footprint arc start angle");
            RequireAngle(arc.EndAngle, "footprint arc end angle");
            RequireLayer(arc.Layer);
        }
        foreach (var text in footprint.Texts)
        {
            RequireText(text.Text, "footprint text", 1024, allowEmpty: true);
            RequireCoordinate(text.Xmm, "footprint text x");
            RequireCoordinate(text.Ymm, "footprint text y");
            RequirePositive(text.HeightMm, "footprint text height");
            RequirePositive(text.StrokeWidthMm, "footprint text stroke width");
            RequireAngle(text.Rotation, "footprint text rotation");
            RequireLayer(text.Layer);
        }
        foreach (var fill in footprint.Fills)
        {
            RequireCoordinates(fill.X1mm, fill.Y1mm, fill.X2mm, fill.Y2mm, "footprint fill");
            RequireAngle(fill.Rotation, "footprint fill rotation");
            RequireLayer(fill.Layer);
        }
        RequireUnique(footprint.Parameters.Keys, $"{footprint.Name} parameter names");
        foreach (var pair in footprint.Parameters)
        {
            RequireText(pair.Key, "footprint parameter name", 255);
            RequireText(pair.Value, "footprint parameter value", 4096, allowEmpty: true);
        }
        if (footprint.Model is not null)
        {
            ValidateModel(footprint.Model);
        }
    }

    private static void RequireOwnerPart(int ownerPartId, int partCount, string label) =>
        Require(ownerPartId >= 1 && ownerPartId <= partCount, $"{label} ownerPartId must name an existing part");

    private static void ValidateModel(StepModelDefinition model)
    {
        RequireText(model.Path, "model.path", 1024);
        Require(File.Exists(model.Path), $"STEP model does not exist: {model.Path}");
        var modelLength = new FileInfo(model.Path).Length;
        Require(modelLength > 0, $"{Path.GetFileName(model.Path)} is empty");
        Require(modelLength <= MaximumStepBytes,
            $"{Path.GetFileName(model.Path)} exceeds the 128 MiB embedded STEP limit");
        RequireText(model.Id, "model.id", 255);
        Require(
            Guid.TryParseExact(model.Id, "B", out _),
            "model.id must be a brace-delimited GUID accepted by Altium");
        RequireText(model.Name, "model.name", 255);
        Require(Path.GetFileName(model.Name) == model.Name, "model.name must be a filename, not a path");
        Require(model.BodyOutline.Count >= 3, "model body outline requires at least three points");
        ValidatePoints(model.BodyOutline, "model body outline");
        RequireCoordinate(model.Xmm, "model x");
        RequireCoordinate(model.Ymm, "model y");
        RequireCoordinate(model.OffsetZmm, "model z offset");
        RequireAngle(model.Rotation2D, "model 2D rotation");
        RequireAngle(model.RotationX, "model x rotation");
        RequireAngle(model.RotationY, "model y rotation");
        RequireAngle(model.RotationZ, "model z rotation");
        RequireNonNegative(model.OverallHeightMm, "model overall height");
        Span<byte> prefix = stackalloc byte[256];
        using var stream = new FileStream(model.Path, FileMode.Open, FileAccess.Read, FileShare.Read, prefix.Length, FileOptions.SequentialScan);
        var prefixLength = stream.Read(prefix);
        Require(System.Text.Encoding.ASCII.GetString(prefix[..prefixLength]).Contains("ISO-10303-21", StringComparison.Ordinal),
            $"{model.Name} is not an ISO-10303-21 STEP file");
    }

    private static void ValidatePoints(IEnumerable<PointDefinition> points, string label)
    {
        foreach (var point in points)
        {
            RequireCoordinate(point.Xmm, $"{label} x");
            RequireCoordinate(point.Ymm, $"{label} y");
        }
    }

    private static void RequireCoordinates(double x1, double y1, double x2, double y2, string label)
    {
        RequireCoordinate(x1, $"{label} x1");
        RequireCoordinate(y1, $"{label} y1");
        RequireCoordinate(x2, $"{label} x2");
        RequireCoordinate(y2, $"{label} y2");
    }

    private static void RequireText(string? value, string label, int maximumLength, bool allowEmpty = false)
    {
        Require(value is not null, $"{label} is required");
        Require(allowEmpty || value!.Length > 0, $"{label} cannot be empty");
        Require(value!.Length <= maximumLength, $"{label} exceeds {maximumLength.ToString(CultureInfo.InvariantCulture)} characters");
        Require(value == value.Trim(), $"{label} cannot have surrounding whitespace");
        Require(!value.Any(char.IsControl), $"{label} cannot contain control characters");
    }

    private static void RequireUnique(IEnumerable<string> values, string label)
    {
        var seen = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        Require(values.All(seen.Add), $"{label} must be unique ignoring case");
    }

    private static void RequireLayer(int layer) =>
        Require(layer is >= 1 and <= 74, "Altium layer must be in the supported 1 through 74 range");

    private static void RequireAngle(double value, string label)
    {
        RequireFinite(value, label);
        Require(Math.Abs(value) <= 360_000, $"{label} exceeds the bounded rotation range");
    }

    private static void RequireCoordinate(double value, string label)
    {
        RequireFinite(value, label);
        Require(Math.Abs(value) <= CoordinateLimitMm, $"{label} exceeds the coordinate limit");
    }

    private static void RequirePositive(double value, string label)
    {
        RequireFinite(value, label);
        Require(value > 0 && value <= CoordinateLimitMm, $"{label} must be positive and bounded");
    }

    private static void RequireNonNegative(double value, string label)
    {
        RequireFinite(value, label);
        Require(value >= 0 && value <= CoordinateLimitMm, $"{label} must be non-negative and bounded");
    }

    private static void RequireFinite(double value, string label) =>
        Require(double.IsFinite(value), $"{label} must be finite");

    private static void Require(bool condition, string message)
    {
        if (!condition)
        {
            throw new CadConverterException(message);
        }
    }

    private static readonly HashSet<string> Orientations =
        new(["right", "up", "left", "down"], StringComparer.OrdinalIgnoreCase);
    private static readonly HashSet<string> ElectricalTypes =
        new(["input", "inputOutput", "output", "openCollector", "passive", "hiZ", "openEmitter", "power"], StringComparer.OrdinalIgnoreCase);
    private static readonly HashSet<string> PadShapes =
        new(["round", "rectangular", "octagonal", "roundedRectangle"], StringComparer.OrdinalIgnoreCase);
    private static readonly HashSet<string> HoleTypes =
        new(["round", "square", "slot"], StringComparer.OrdinalIgnoreCase);

    [GeneratedRegex("^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$", RegexOptions.CultureInvariant)]
    private static partial Regex OutputStemRegex();
}

public sealed class CadConverterException(string message) : Exception(message);
