using System.Runtime.InteropServices;
using System.Text.Json;

namespace Stockroom.WindowHost;

internal enum PersistedWindowShowState
{
    Normal,
    Maximized,
    Minimized,
}

internal readonly record struct PhysicalRectangle(
    int Left,
    int Top,
    int Right,
    int Bottom)
{
    internal int Width => Right - Left;

    internal int Height => Bottom - Top;

    internal static PhysicalRectangle Parse(
        JsonElement value,
        string label)
    {
        MachineWindowConfig.RequireExactProperties(
            value,
            label,
            "left",
            "top",
            "right",
            "bottom");
        var result = new PhysicalRectangle(
            RequiredInteger(value, "left", label),
            RequiredInteger(value, "top", label),
            RequiredInteger(value, "right", label),
            RequiredInteger(value, "bottom", label));
        result.Validate(label);
        return result;
    }

    internal void Validate(string label)
    {
        if (Math.Abs((long)Left) > 2_000_000
            || Math.Abs((long)Top) > 2_000_000
            || Math.Abs((long)Right) > 2_000_000
            || Math.Abs((long)Bottom) > 2_000_000
            || Right <= Left
            || Bottom <= Top
            || Width > 100_000
            || Height > 100_000)
        {
            throw new WindowHostException(
                $"{label} is outside the supported physical screen range");
        }
    }

    private static int RequiredInteger(
        JsonElement value,
        string property,
        string label)
    {
        if (!value.GetProperty(property).TryGetInt32(out var result))
        {
            throw new WindowHostException(
                $"{label}.{property} must be an integer");
        }

        return result;
    }
}

internal sealed record PersistedMonitorGeometry(
    string DeviceName,
    PhysicalRectangle WorkArea,
    int Dpi)
{
    internal static PersistedMonitorGeometry Parse(JsonElement value)
    {
        MachineWindowConfig.RequireExactProperties(
            value,
            "monitor",
            "device_name",
            "work_area",
            "dpi");
        var nameElement = value.GetProperty("device_name");
        if (nameElement.ValueKind != JsonValueKind.String)
        {
            throw new WindowHostException(
                "monitor.device_name must be a string");
        }

        var deviceName = nameElement.GetString();
        if (string.IsNullOrWhiteSpace(deviceName)
            || deviceName != deviceName.Trim()
            || deviceName.Length > 128
            || deviceName.IndexOf('\0') >= 0)
        {
            throw new WindowHostException(
                "monitor.device_name is invalid");
        }

        if (!value.GetProperty("dpi").TryGetInt32(out var dpi)
            || dpi is < 48 or > 768)
        {
            throw new WindowHostException(
                "monitor.dpi is outside the supported range");
        }

        return new PersistedMonitorGeometry(
            deviceName,
            PhysicalRectangle.Parse(
                value.GetProperty("work_area"),
                "monitor.work_area"),
            dpi);
    }
}

internal sealed record PersistedWindowGeometry(
    PhysicalRectangle NormalBounds,
    PersistedWindowShowState ShowState,
    PersistedMonitorGeometry Monitor)
{
    internal static PersistedWindowGeometry? Parse(JsonElement value)
    {
        MachineWindowConfig.RequireObject(value, "window geometry");
        MachineWindowConfig.RejectDuplicateProperties(
            value,
            "window geometry");
        if (!value.EnumerateObject().Any())
        {
            return null;
        }

        MachineWindowConfig.RequireExactProperties(
            value,
            "window geometry",
            "schema",
            "version",
            "units",
            "normal_bounds",
            "show_state",
            "monitor");
        if (value.GetProperty("schema").GetString()
                != "stockroom.window-geometry"
            || !value.GetProperty("version").TryGetInt32(out var version)
            || version != 1
            || value.GetProperty("units").GetString()
                != "physical-pixels")
        {
            throw new WindowHostException(
                "window geometry schema is unsupported");
        }

        var showState = value.GetProperty("show_state").GetString() switch
        {
            "normal" => PersistedWindowShowState.Normal,
            "maximized" => PersistedWindowShowState.Maximized,
            "minimized" => PersistedWindowShowState.Minimized,
            _ => throw new WindowHostException(
                "window geometry show_state is unsupported"),
        };
        return new PersistedWindowGeometry(
            PhysicalRectangle.Parse(
                value.GetProperty("normal_bounds"),
                "normal_bounds"),
            showState,
            PersistedMonitorGeometry.Parse(
                value.GetProperty("monitor")));
    }
}

internal sealed record CurrentMonitorGeometry(
    IntPtr Handle,
    string DeviceName,
    PhysicalRectangle WorkArea,
    int Dpi);

internal sealed record ResolvedWindowGeometry(
    PhysicalRectangle Bounds,
    PersistedWindowShowState ShowState);

internal static class WindowGeometryResolver
{
    internal static ResolvedWindowGeometry Resolve(
        PersistedWindowGeometry saved,
        IReadOnlyList<CurrentMonitorGeometry> monitors)
    {
        ArgumentNullException.ThrowIfNull(saved);
        if (monitors.Count == 0)
        {
            throw new WindowHostException(
                "Windows reported no usable display monitors");
        }

        var target = monitors.FirstOrDefault(
            item => string.Equals(
                item.DeviceName,
                saved.Monitor.DeviceName,
                StringComparison.OrdinalIgnoreCase))
            ?? monitors
                .OrderBy(
                    item => DistanceSquared(
                        saved.NormalBounds,
                        item.WorkArea))
                .ThenBy(
                    static item => item.DeviceName,
                    StringComparer.OrdinalIgnoreCase)
                .First();
        var width = Math.Min(
            Math.Max(
                Scale(
                    saved.NormalBounds.Width,
                    saved.Monitor.Dpi,
                    target.Dpi),
                Math.Min(960, target.WorkArea.Width)),
            target.WorkArea.Width);
        var height = Math.Min(
            Math.Max(
                Scale(
                    saved.NormalBounds.Height,
                    saved.Monitor.Dpi,
                    target.Dpi),
                Math.Min(640, target.WorkArea.Height)),
            target.WorkArea.Height);
        var offsetX = Scale(
            saved.NormalBounds.Left - saved.Monitor.WorkArea.Left,
            saved.Monitor.Dpi,
            target.Dpi);
        var offsetY = Scale(
            saved.NormalBounds.Top - saved.Monitor.WorkArea.Top,
            saved.Monitor.Dpi,
            target.Dpi);
        var left = Math.Clamp(
            target.WorkArea.Left + offsetX,
            target.WorkArea.Left,
            target.WorkArea.Right - width);
        var top = Math.Clamp(
            target.WorkArea.Top + offsetY,
            target.WorkArea.Top,
            target.WorkArea.Bottom - height);
        return new ResolvedWindowGeometry(
            new PhysicalRectangle(
                left,
                top,
                left + width,
                top + height),
            saved.ShowState);
    }

    private static int Scale(
        int value,
        int sourceDpi,
        int targetDpi) =>
        checked((int)Math.Round(
            value * (double)targetDpi / sourceDpi,
            MidpointRounding.ToEven));

    private static long DistanceSquared(
        PhysicalRectangle source,
        PhysicalRectangle target)
    {
        static long AxisDistance(int start, int end, int otherStart, int otherEnd)
        {
            if (end < otherStart)
            {
                return otherStart - end;
            }

            if (otherEnd < start)
            {
                return start - otherEnd;
            }

            return 0;
        }

        var x = AxisDistance(
            source.Left,
            source.Right,
            target.Left,
            target.Right);
        var y = AxisDistance(
            source.Top,
            source.Bottom,
            target.Top,
            target.Bottom);
        return x * x + y * y;
    }
}

internal static class WindowsWindowGeometry
{
    private const uint MonitorDefaultToNearest = 0x00000002;
    private const uint SetWindowPositionNoActivate = 0x0010;
    private const uint SetWindowPositionNoZOrder = 0x0004;
    private const int MonitorDpiTypeEffective = 0;

    internal static ResolvedWindowGeometry? ApplyHidden(
        IntPtr windowHandle,
        PersistedWindowGeometry? saved)
    {
        if (windowHandle == IntPtr.Zero)
        {
            throw new WindowHostException("window handle is invalid");
        }

        if (saved is null)
        {
            return null;
        }

        var resolution = WindowGeometryResolver.Resolve(
            saved,
            EnumerateMonitors());
        var bounds = resolution.Bounds;
        if (!NativeMethods.SetWindowPos(
                windowHandle,
                IntPtr.Zero,
                bounds.Left,
                bounds.Top,
                bounds.Width,
                bounds.Height,
                SetWindowPositionNoActivate
                    | SetWindowPositionNoZOrder))
        {
            throw new WindowHostException(
                "persisted window geometry could not be applied");
        }

        return resolution;
    }

    internal static void Show(
        IntPtr windowHandle,
        ResolvedWindowGeometry? resolution)
    {
        var command = resolution?.ShowState switch
        {
            PersistedWindowShowState.Maximized => 3,
            PersistedWindowShowState.Minimized => 2,
            _ => 1,
        };
        _ = NativeMethods.ShowWindow(windowHandle, command);
    }

    internal static void Focus(IntPtr windowHandle)
    {
        _ = NativeMethods.ShowWindow(windowHandle, 9);
        _ = NativeMethods.SetForegroundWindow(windowHandle);
    }

    internal static IReadOnlyDictionary<string, object?> Capture(
        IntPtr windowHandle)
    {
        if (windowHandle == IntPtr.Zero)
        {
            throw new WindowHostException("window handle is invalid");
        }

        var placement = new NativeMethods.WindowPlacement
        {
            Length = Marshal.SizeOf<NativeMethods.WindowPlacement>(),
        };
        if (!NativeMethods.GetWindowPlacement(
                windowHandle,
                ref placement))
        {
            throw new WindowHostException(
                "window placement could not be captured");
        }

        var monitorHandle = NativeMethods.MonitorFromWindow(
            windowHandle,
            MonitorDefaultToNearest);
        var information = new NativeMethods.MonitorInformation
        {
            Size = Marshal.SizeOf<NativeMethods.MonitorInformation>(),
        };
        if (monitorHandle == IntPtr.Zero
            || !NativeMethods.GetMonitorInfo(
                monitorHandle,
                ref information))
        {
            throw new WindowHostException(
                "window monitor could not be captured");
        }

        var dpi = NativeMethods.GetDpiForWindow(windowHandle);
        if (dpi is < 48 or > 768)
        {
            throw new WindowHostException(
                "window DPI could not be captured");
        }

        var offsetX = information.WorkArea.Left
            - information.MonitorArea.Left;
        var offsetY = information.WorkArea.Top
            - information.MonitorArea.Top;
        var bounds = new PhysicalRectangle(
            placement.NormalPosition.Left + offsetX,
            placement.NormalPosition.Top + offsetY,
            placement.NormalPosition.Right + offsetX,
            placement.NormalPosition.Bottom + offsetY);
        bounds.Validate("captured normal_bounds");
        var showState = placement.ShowCommand switch
        {
            3 => "maximized",
            2 or 6 or 7 or 11 => "minimized",
            _ => "normal",
        };
        return new Dictionary<string, object?>
        {
            ["schema"] = "stockroom.window-geometry",
            ["version"] = 1,
            ["units"] = "physical-pixels",
            ["normal_bounds"] = new Dictionary<string, object?>
            {
                ["left"] = bounds.Left,
                ["top"] = bounds.Top,
                ["right"] = bounds.Right,
                ["bottom"] = bounds.Bottom,
            },
            ["show_state"] = showState,
            ["monitor"] = new Dictionary<string, object?>
            {
                ["device_name"] = information.GetDeviceName(),
                ["work_area"] = new Dictionary<string, object?>
                {
                    ["left"] = information.WorkArea.Left,
                    ["top"] = information.WorkArea.Top,
                    ["right"] = information.WorkArea.Right,
                    ["bottom"] = information.WorkArea.Bottom,
                },
                ["dpi"] = checked((int)dpi),
            },
        };
    }

    private static IReadOnlyList<CurrentMonitorGeometry> EnumerateMonitors()
    {
        var monitors = new List<CurrentMonitorGeometry>();
        NativeMethods.MonitorEnumProcedure callback = (
            handle,
            _,
            _,
            _) =>
        {
            var information = new NativeMethods.MonitorInformation
            {
                Size = Marshal.SizeOf<NativeMethods.MonitorInformation>(),
            };
            if (!NativeMethods.GetMonitorInfo(handle, ref information))
            {
                return false;
            }

            var dpiX = 96u;
            var dpiY = 96u;
            if (NativeMethods.GetDpiForMonitor(
                    handle,
                    MonitorDpiTypeEffective,
                    out var measuredX,
                    out var measuredY) == 0
                && measuredX == measuredY
                && measuredX is >= 48 and <= 768)
            {
                dpiX = measuredX;
                dpiY = measuredY;
            }

            monitors.Add(
                new CurrentMonitorGeometry(
                    handle,
                    information.GetDeviceName(),
                    new PhysicalRectangle(
                        information.WorkArea.Left,
                        information.WorkArea.Top,
                        information.WorkArea.Right,
                        information.WorkArea.Bottom),
                    checked((int)Math.Min(dpiX, dpiY))));
            return true;
        };
        if (!NativeMethods.EnumDisplayMonitors(
                IntPtr.Zero,
                IntPtr.Zero,
                callback,
                IntPtr.Zero))
        {
            throw new WindowHostException(
                "display monitors could not be enumerated");
        }

        return monitors;
    }
}

internal static partial class NativeMethods
{
    [StructLayout(LayoutKind.Sequential)]
    internal struct NativeRectangle
    {
        internal int Left;
        internal int Top;
        internal int Right;
        internal int Bottom;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct NativePoint
    {
        internal int X;
        internal int Y;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal struct WindowPlacement
    {
        internal int Length;
        internal int Flags;
        internal int ShowCommand;
        internal NativePoint MinimumPosition;
        internal NativePoint MaximumPosition;
        internal NativeRectangle NormalPosition;
    }

    [StructLayout(LayoutKind.Sequential)]
    internal unsafe struct MonitorInformation
    {
        internal int Size;
        internal NativeRectangle MonitorArea;
        internal NativeRectangle WorkArea;
        internal uint Flags;
        internal fixed char DeviceName[32];

        internal string GetDeviceName()
        {
            fixed (char* value = DeviceName)
            {
                return new string(value).TrimEnd('\0');
            }
        }
    }

    internal delegate bool MonitorEnumProcedure(
        IntPtr monitor,
        IntPtr deviceContext,
        IntPtr rectangle,
        IntPtr data);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool SetProcessDpiAwarenessContext(
        IntPtr dpiContext);

    [LibraryImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool SetWindowPos(
        IntPtr windowHandle,
        IntPtr insertAfter,
        int x,
        int y,
        int width,
        int height,
        uint flags);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool ShowWindow(
        IntPtr windowHandle,
        int command);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool SetForegroundWindow(
        IntPtr windowHandle);

    [LibraryImport("user32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetWindowPlacement(
        IntPtr windowHandle,
        ref WindowPlacement placement);

    [LibraryImport("user32.dll")]
    internal static partial uint GetDpiForWindow(
        IntPtr windowHandle);

    [LibraryImport("user32.dll")]
    internal static partial IntPtr MonitorFromWindow(
        IntPtr windowHandle,
        uint flags);

    [LibraryImport("user32.dll")]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool EnumDisplayMonitors(
        IntPtr deviceContext,
        IntPtr clipRectangle,
        MonitorEnumProcedure callback,
        IntPtr data);

    [LibraryImport(
        "user32.dll",
        EntryPoint = "GetMonitorInfoW",
        StringMarshalling = StringMarshalling.Utf16)]
    [return: MarshalAs(UnmanagedType.Bool)]
    internal static partial bool GetMonitorInfo(
        IntPtr monitor,
        ref MonitorInformation information);

    [LibraryImport("shcore.dll")]
    internal static partial int GetDpiForMonitor(
        IntPtr monitor,
        int dpiType,
        out uint dpiX,
        out uint dpiY);
}
