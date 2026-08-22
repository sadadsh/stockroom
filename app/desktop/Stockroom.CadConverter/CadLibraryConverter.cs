using System.Security.Cryptography;
using System.Runtime.CompilerServices;
using System.Text;
using OriginalCircuit.Altium.Models.Pcb;
using OriginalCircuit.Altium.Models.Sch;
using OriginalCircuit.Altium.Serialization.Readers;
using OriginalCircuit.Altium.Serialization.Writers;
using OriginalCircuit.Eda.Enums;
using OriginalCircuit.Eda.Primitives;
using AltiumPadShape = OriginalCircuit.Altium.Models.Pcb.PadShape;
using AltiumPadHoleType = OriginalCircuit.Altium.Models.Pcb.PadHoleType;
using AltiumPinElectricalType = OriginalCircuit.Altium.Models.Sch.PinElectricalType;

namespace Stockroom.CadConverter;

public static class CadLibraryConverter
{
    private const string PcbLibraryTemplateResource = "Stockroom.CadConverter.AltiumPcbLibTemplate";
    private const int StandardComponentColor = 128;
    private const int StandardComponentAreaColor = 11599871;
    private const int StandardParameterColor = 8388608;

    private static readonly UTF8Encoding StrictUtf8 = new(
        encoderShouldEmitUTF8Identifier: false,
        throwOnInvalidBytes: true);

    public static async Task<CadConverterResult> ConvertAsync(
        CadConverterRequest request,
        CancellationToken cancellationToken = default)
    {
        ConversionValidation.RequireValid(request);
        var output = Path.GetFullPath(request.OutputDirectory);
        var createdOutput = !Directory.Exists(output);
        Directory.CreateDirectory(output);
        var schlibPath = Path.Combine(output, $"{request.OutputStem}.SchLib");
        var pcblibPath = Path.Combine(output, $"{request.OutputStem}.PcbLib");

        try
        {
            var schlib = BuildSymbolLibrary(request);
            var (pcblib, models) = BuildFootprintLibrary(request);
            await new SchLibWriter().WriteAsync(
                schlib,
                schlibPath,
                overwrite: false,
                cancellationToken).ConfigureAwait(false);
            await new PcbLibWriter().WriteAsync(
                pcblib,
                pcblibPath,
                overwrite: false,
                cancellationToken).ConfigureAwait(false);

            return new CadConverterResult
            {
                Schema = CadConverterResult.CurrentSchema,
                Status = "ok",
                Detail = "Native Altium libraries were written without an Altium runtime.",
                Schlib = await ArtifactAsync(schlibPath, cancellationToken).ConfigureAwait(false),
                Pcblib = await ArtifactAsync(pcblibPath, cancellationToken).ConfigureAwait(false),
                SymbolEntries = [request.Symbol.Name],
                FootprintEntries = request.Footprints.Select(item => item.Name).ToArray(),
                EmbeddedModels = models,
            };
        }
        catch
        {
            DeleteIfPresent(schlibPath);
            DeleteIfPresent(pcblibPath);
            if (createdOutput && Directory.Exists(output) && !Directory.EnumerateFileSystemEntries(output).Any())
            {
                Directory.Delete(output);
            }
            throw;
        }
    }

    private static SchLibrary BuildSymbolLibrary(CadConverterRequest request)
    {
        var definition = request.Symbol;
        var component = new SchComponent
        {
            Name = definition.Name,
            LibReference = definition.Name,
            Description = definition.Description,
            DesignatorPrefix = definition.DesignatorPrefix,
            PartCount = definition.PartCount,
            AllPinCount = definition.Pins.Count,
            Color = StandardComponentColor,
            AreaColor = StandardComponentAreaColor,
            PinColor = StandardComponentColor,
        };

        foreach (var pin in definition.Pins)
        {
            component.AddPin(new SchPin
            {
                Designator = pin.Designator,
                Name = pin.Name,
                Location = Point(pin.Xmm, pin.Ymm),
                Length = Mm(pin.LengthMm),
                Orientation = PinOrientation(pin.Orientation),
                ElectricalType = ElectricalType(pin.ElectricalType),
                ShowName = pin.ShowName,
                ShowDesignator = pin.ShowDesignator,
                Color = StandardComponentColor,
                AreaColor = StandardComponentAreaColor,
                OwnerPartId = pin.OwnerPartId,
            });
        }
        foreach (var line in definition.Lines)
        {
            component.AddLine(new SchLine
            {
                Start = Point(line.X1mm, line.Y1mm),
                End = Point(line.X2mm, line.Y2mm),
                Width = Mm(line.WidthMm),
                Color = line.Color,
                OwnerPartId = line.OwnerPartId,
            });
        }
        foreach (var rectangle in definition.Rectangles)
        {
            component.AddRectangle(new SchRectangle
            {
                Corner1 = Point(rectangle.X1mm, rectangle.Y1mm),
                Corner2 = Point(rectangle.X2mm, rectangle.Y2mm),
                LineWidth = Mm(rectangle.WidthMm),
                IsFilled = rectangle.Filled,
                Color = rectangle.Color,
                FillColor = rectangle.FillColor,
                OwnerPartId = rectangle.OwnerPartId,
            });
        }
        foreach (var polyline in definition.Polylines)
        {
            var builder = SchPolyline.Create()
                .LineWidth(polyline.LineWidth)
                .Color(polyline.Color);
            foreach (var point in polyline.Points)
            {
                builder.AddVertex(Mm(point.Xmm), Mm(point.Ymm));
            }
            var builtPolyline = builder.Build();
            builtPolyline.OwnerPartId = polyline.OwnerPartId;
            component.AddPolyline(builtPolyline);
        }
        foreach (var arc in definition.Arcs)
        {
            component.AddArc(new SchArc
            {
                Center = Point(arc.Xmm, arc.Ymm),
                Radius = Mm(arc.RadiusMm),
                StartAngle = arc.StartAngle,
                EndAngle = arc.EndAngle,
                LineWidth = arc.LineWidth,
                Color = arc.Color,
                OwnerPartId = arc.OwnerPartId,
            });
        }
        foreach (var ellipse in definition.Ellipses)
        {
            component.AddEllipse(new SchEllipse
            {
                Center = Point(ellipse.Xmm, ellipse.Ymm),
                RadiusX = Mm(ellipse.RadiusXmm),
                RadiusY = Mm(ellipse.RadiusYmm),
                LineWidth = ellipse.LineWidth,
                IsFilled = ellipse.Filled,
                Color = ellipse.Color,
                FillColor = ellipse.FillColor,
                OwnerPartId = ellipse.OwnerPartId,
            });
        }
        foreach (var label in definition.Labels)
        {
            component.AddLabel(new SchLabel
            {
                Text = label.Text,
                Location = Point(label.Xmm, label.Ymm),
                Rotation = label.Orientation * 90d,
                Color = label.Color,
                OwnerPartId = label.OwnerPartId,
            });
        }

        var parameters = new Dictionary<string, SymbolParameterDefinition>(StringComparer.OrdinalIgnoreCase);
        foreach (var parameter in definition.Parameters)
        {
            parameters.Add(parameter.Name, parameter);
        }
        // Use Altium's conventional human-facing parameter names. Stockroom's native
        // readback intentionally accepts these stable names instead of depending on a
        // provider-specific underscore spelling.
        parameters["Manufacturer"] = IdentityParameter("Manufacturer", request.Manufacturer);
        parameters["Manufacturer Part Number"] = IdentityParameter("Manufacturer Part Number", request.Mpn);
        foreach (var parameter in parameters.Values)
        {
            component.AddParameter(new SchParameter
            {
                Name = parameter.Name,
                Value = parameter.Value,
                Location = Point(parameter.Xmm, parameter.Ymm),
                IsVisible = parameter.Visible,
                HideName = true,
                Color = StandardParameterColor,
            });
        }

        var implementation = new SchImplementation
        {
            Description = $"Stockroom footprint {request.DefaultFootprint}",
            ModelName = request.DefaultFootprint,
            ModelType = "PCBLIB",
            IsCurrent = true,
            DataFileKinds = { "PCBLib" },
        };
        foreach (var mapping in request.PadPinMap)
        {
            var definer = new SchMapDefiner
            {
                DesignatorInterface = mapping.Pin,
                DesignatorImplementations = { mapping.Pad },
                IsTrivial = string.Equals(mapping.Pin, mapping.Pad, StringComparison.Ordinal),
            };
            AddMapDefiner(implementation, definer);
        }
        AddImplementation(component, implementation);

        var library = new SchLibrary();
        library.Add(component);
        return library;
    }

    private static (PcbLibrary Library, IReadOnlyList<ModelResult> Models) BuildFootprintLibrary(
        CadConverterRequest request)
    {
        var library = CreateFootprintLibrary(request);
        var models = new Dictionary<string, (PcbModel Model, ModelResult Result)>(StringComparer.OrdinalIgnoreCase);

        foreach (var definition in request.Footprints)
        {
            var component = new PcbComponent
            {
                Name = definition.Name,
                Description = definition.Description,
                FootprintDescription = definition.Description,
            };
            foreach (var pad in definition.Pads)
            {
                var size = Point(pad.SizeXmm, pad.SizeYmm);
                var shape = PadShape(pad.Shape);
                component.AddPad(new PcbPad
                {
                    Designator = pad.Designator,
                    Location = Point(pad.Xmm, pad.Ymm),
                    SizeTop = size,
                    SizeMiddle = size,
                    SizeBottom = size,
                    HoleSize = Mm(pad.HoleSizeMm),
                    Rotation = pad.Rotation,
                    Layer = pad.Layer,
                    ShapeTop = shape,
                    ShapeMiddle = shape,
                    ShapeBottom = shape,
                    HoleType = HoleType(pad.HoleType),
                    IsPlated = pad.Plated,
                    Mode = pad.Layer == 74 ? 1 : 0,
                });
            }
            foreach (var line in definition.Lines)
            {
                component.AddTrack(new PcbTrack
                {
                    Start = Point(line.X1mm, line.Y1mm),
                    End = Point(line.X2mm, line.Y2mm),
                    Width = Mm(line.WidthMm),
                    Layer = line.Layer,
                });
            }
            foreach (var arc in definition.Arcs)
            {
                component.AddArc(new PcbArc
                {
                    Center = Point(arc.Xmm, arc.Ymm),
                    Radius = Mm(arc.RadiusMm),
                    StartAngle = arc.StartAngle,
                    EndAngle = arc.EndAngle,
                    Width = Mm(arc.WidthMm),
                    Layer = arc.Layer,
                });
            }
            foreach (var text in definition.Texts)
            {
                component.AddText(new PcbText
                {
                    Text = text.Text,
                    Location = Point(text.Xmm, text.Ymm),
                    Height = Mm(text.HeightMm),
                    StrokeWidth = Mm(text.StrokeWidthMm),
                    Layer = text.Layer,
                    Rotation = text.Rotation,
                    IsMirrored = text.Mirrored,
                });
            }
            foreach (var fill in definition.Fills)
            {
                component.AddFill(new PcbFill
                {
                    Corner1 = Point(fill.X1mm, fill.Y1mm),
                    Corner2 = Point(fill.X2mm, fill.Y2mm),
                    Layer = fill.Layer,
                    Rotation = fill.Rotation,
                });
            }
            if (definition.Model is not null)
            {
                var model = AddOrRequireSameModel(models, definition.Model);
                component.AddComponentBody(BuildComponentBody(definition.Model, model));
            }
            library.Add(component);
        }

        foreach (var value in models.Values)
        {
            library.Models.Add(value.Model);
        }
        return (library, models.Values.Select(value => value.Result).ToArray());
    }

    private static PcbLibrary CreateFootprintLibrary(CadConverterRequest request)
    {
        using var template = typeof(CadLibraryConverter).Assembly.GetManifestResourceStream(PcbLibraryTemplateResource)
            ?? throw new CadConverterException("the embedded Altium PCB library template is missing");
        var library = new PcbLibReader().Read(template);

        foreach (var component in library.Components.ToArray())
        {
            library.Remove(component.Name);
        }
        library.Models.Clear();
        library.ComponentParamsToc.Clear();
        library.UniqueId = StableLibraryId(request);
        ReplaceOrderedLibraryParameter(
            library,
            "FILENAME",
            $"{request.OutputStem}.PcbLib");
        return library;
    }

    private static string StableLibraryId(CadConverterRequest request)
    {
        var identity = Encoding.UTF8.GetBytes(
            $"{request.Manufacturer}\0{request.Mpn}\0{request.OutputStem}");
        var digest = SHA256.HashData(identity);
        return string.Create(8, digest, static (characters, bytes) =>
        {
            for (var index = 0; index < characters.Length; index++)
            {
                characters[index] = (char)('A' + (bytes[index] % 26));
            }
        });
    }

    private static void ReplaceOrderedLibraryParameter(
        PcbLibrary library,
        string name,
        string value)
    {
        if (library.LibraryParametersOrdered is not { Count: > 0 } parameters)
        {
            throw new CadConverterException("the embedded Altium PCB library template has no native metadata");
        }
        var replaced = false;
        for (var index = 0; index < parameters.Count; index++)
        {
            if (!string.Equals(parameters[index].Key, name, StringComparison.OrdinalIgnoreCase))
            {
                continue;
            }
            parameters[index] = KeyValuePair.Create(parameters[index].Key, value);
            replaced = true;
        }
        if (!replaced)
        {
            throw new CadConverterException($"the embedded Altium PCB library template has no {name} metadata");
        }
    }

    private static PcbModel AddOrRequireSameModel(
        IDictionary<string, (PcbModel Model, ModelResult Result)> models,
        StepModelDefinition definition)
    {
        var stepBytes = ReadBoundedStep(definition.Path);
        var digest = Convert.ToHexStringLower(SHA256.HashData(stepBytes));
        if (models.TryGetValue(definition.Id, out var existing))
        {
            if (!string.Equals(existing.Result.Sha256, digest, StringComparison.Ordinal)
                || !string.Equals(existing.Result.Name, definition.Name, StringComparison.Ordinal))
            {
                throw new CadConverterException($"model id {definition.Id} identifies different STEP content");
            }
            return existing.Model;
        }

        var model = new PcbModel
        {
            Id = definition.Id,
            Name = definition.Name,
            IsEmbedded = true,
            StepData = DecodeStep(stepBytes, definition.Name),
            RotationX = definition.RotationX,
            RotationY = definition.RotationY,
            RotationZ = definition.RotationZ,
            Dz = Mm(definition.OffsetZmm).ToRaw(),
        };
        model.RecomputeChecksum();
        models.Add(definition.Id, (
            model,
            new ModelResult
            {
                Id = definition.Id,
                Name = definition.Name,
                Sha256 = digest,
            }));
        return model;
    }

    private static byte[] ReadBoundedStep(string path)
    {
        using var source = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 81920, FileOptions.SequentialScan);
        using var buffer = new MemoryStream((int)Math.Min(source.Length, ConversionValidation.MaximumStepBytes));
        var chunk = new byte[81920];
        while (true)
        {
            var count = source.Read(chunk, 0, chunk.Length);
            if (count == 0)
            {
                return buffer.ToArray();
            }
            if (buffer.Length + count > ConversionValidation.MaximumStepBytes)
            {
                throw new CadConverterException($"{Path.GetFileName(path)} exceeds the 128 MiB embedded STEP limit");
            }
            buffer.Write(chunk, 0, count);
        }
    }

    private static string DecodeStep(byte[] bytes, string name)
    {
        try
        {
            return StrictUtf8.GetString(bytes);
        }
        catch (DecoderFallbackException error)
        {
            throw new CadConverterException($"{name} must be valid UTF-8 so its embedded STEP bytes remain unchanged: {error.Message}");
        }
    }

    private static PcbComponentBody BuildComponentBody(StepModelDefinition definition, PcbModel model)
    {
        var builder = PcbComponentBody.Create()
            .OnLayer("MECHANICAL1")
            .WithName(definition.Name)
            .Kind(0)
            .ShapeBased(false)
            .ModelId(model.Id)
            .At2D(Mm(definition.Xmm), Mm(definition.Ymm))
            .Rotation2D(definition.Rotation2D)
            .Rotation3D(definition.RotationX, definition.RotationY, definition.RotationZ)
            .OffsetZ(Mm(definition.OffsetZmm))
            .OverallHeight(Mm(definition.OverallHeightMm));
        foreach (var point in definition.BodyOutline)
        {
            builder.AddPoint(Mm(point.Xmm), Mm(point.Ymm));
        }
        var body = builder.Build();
        body.Layer = 57;
        body.ModelName = model.Name;
        body.ModelEmbed = true;
        body.ModelType = 1;
        body.ModelChecksum = unchecked((uint)model.Checksum);
        body.ModelSource = model.ModelSource;
        return body;
    }

    private static SymbolParameterDefinition IdentityParameter(string name, string value) => new()
    {
        Name = name,
        Value = value,
        Visible = false,
    };

    private static Coord Mm(double value) => Coord.FromMm(value);
    private static CoordPoint Point(double x, double y) => new(Mm(x), Mm(y));

    private static PinOrientation PinOrientation(string value) => value.ToLowerInvariant() switch
    {
        "right" => OriginalCircuit.Eda.Enums.PinOrientation.Right,
        "up" => OriginalCircuit.Eda.Enums.PinOrientation.Up,
        "left" => OriginalCircuit.Eda.Enums.PinOrientation.Left,
        "down" => OriginalCircuit.Eda.Enums.PinOrientation.Down,
        _ => throw new CadConverterException($"unsupported pin orientation: {value}"),
    };

    private static AltiumPinElectricalType ElectricalType(string value) => value.ToLowerInvariant() switch
    {
        "input" => AltiumPinElectricalType.Input,
        "inputoutput" => AltiumPinElectricalType.InputOutput,
        "output" => AltiumPinElectricalType.Output,
        "opencollector" => AltiumPinElectricalType.OpenCollector,
        "passive" => AltiumPinElectricalType.Passive,
        "hiz" => AltiumPinElectricalType.HiZ,
        "openemitter" => AltiumPinElectricalType.OpenEmitter,
        "power" => AltiumPinElectricalType.Power,
        _ => throw new CadConverterException($"unsupported pin electrical type: {value}"),
    };

    private static AltiumPadShape PadShape(string value) => value.ToLowerInvariant() switch
    {
        "round" => AltiumPadShape.Round,
        "rectangular" => AltiumPadShape.Rectangular,
        "octagonal" => AltiumPadShape.Octagonal,
        "roundedrectangle" => AltiumPadShape.RoundedRectangle,
        _ => throw new CadConverterException($"unsupported pad shape: {value}"),
    };

    private static AltiumPadHoleType HoleType(string value) => value.ToLowerInvariant() switch
    {
        "round" => AltiumPadHoleType.Round,
        "square" => AltiumPadHoleType.Square,
        "slot" => AltiumPadHoleType.Slot,
        _ => throw new CadConverterException($"unsupported pad hole type: {value}"),
    };

    private static async Task<ArtifactResult> ArtifactAsync(string path, CancellationToken cancellationToken)
    {
        await using var stream = new FileStream(path, FileMode.Open, FileAccess.Read, FileShare.Read, 81920, true);
        var digest = await SHA256.HashDataAsync(stream, cancellationToken).ConfigureAwait(false);
        return new ArtifactResult
        {
            Path = path,
            SizeBytes = stream.Length,
            Sha256 = Convert.ToHexStringLower(digest),
        };
    }

    private static void DeleteIfPresent(string path)
    {
        if (File.Exists(path))
        {
            File.Delete(path);
        }
    }

    // AltiumSharp v2 can faithfully read/write implementation records but exposes its
    // two collection mutators as internal. The dependency is source-pinned, so use a
    // compile-time, fail-fast accessor instead of reflection or binary patching.
    [UnsafeAccessor(UnsafeAccessorKind.Method, Name = "AddImplementation")]
    private static extern void AddImplementation(SchComponent component, SchImplementation implementation);

    [UnsafeAccessor(UnsafeAccessorKind.Method, Name = "AddMapDefiner")]
    private static extern void AddMapDefiner(SchImplementation implementation, SchMapDefiner definer);
}
