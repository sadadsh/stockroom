"""Strict physical-pixel window geometry for the Windows desktop host.

The update handoff needs a small native contract that can be carried between
host generations without depending on pywebview's logical-coordinate model.
This module owns that contract and the Win32 translation at its boundary:

* persisted coordinates are physical screen pixels;
* the normal (restored) bounds and the prior show state are kept separately;
* monitor identity, work area, and DPI are recorded with the bounds;
* restoration resolves against the monitors that exist *now*, scales for a
  DPI change, and clamps the whole window into a current work area; and
* malformed or unavailable geometry fails before the HWND is changed.

The public functions accept a small protocol so the behavior is fully testable
without opening a window.  ``_Win32GeometryApi`` is instantiated lazily only
when a caller uses the real Windows boundary.
"""

from __future__ import annotations

import ctypes
import os
from collections.abc import Mapping, Sequence
from ctypes import wintypes
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast

GEOMETRY_SCHEMA = "stockroom.window-geometry"
GEOMETRY_VERSION = 1
PHYSICAL_PIXEL_UNITS = "physical-pixels"

DEFAULT_MINIMUM_WIDTH = 960
DEFAULT_MINIMUM_HEIGHT = 640

_MAX_ABSOLUTE_COORDINATE = 2_000_000
_MAX_DIMENSION = 100_000
_MIN_DPI = 48
_MAX_DPI = 768
_MAX_DEVICE_NAME_LENGTH = 128

_MONITOR_DEFAULTTONEAREST = 0x00000002
_SW_HIDE = 0
_SW_SHOWNORMAL = 1
_SW_SHOWMINIMIZED = 2
_SW_SHOWMAXIMIZED = 3
_SW_MINIMIZE = 6
_SW_SHOWMINNOACTIVE = 7
_SW_FORCEMINIMIZE = 11


class WindowGeometryError(ValueError):
    """Persisted or caller-supplied geometry violates the bounded schema."""


class WindowGeometryUnavailable(RuntimeError):
    """Native geometry could not be captured or applied safely."""


class WindowShowState(StrEnum):
    """The user-visible state to restore after the bounds are prepared."""

    NORMAL = "normal"
    MAXIMIZED = "maximized"
    MINIMIZED = "minimized"


def _strict_int(value: object, *, label: str) -> int:
    if type(value) is not int:
        raise WindowGeometryError(f"{label} must be an integer")
    return value


def _strict_mapping(
    value: object,
    *,
    label: str,
    keys: frozenset[str],
) -> Mapping[str, object]:
    if type(value) is not dict:
        raise WindowGeometryError(f"{label} must be an object")
    mapping = cast(dict[object, object], value)
    if any(type(key) is not str for key in mapping):
        raise WindowGeometryError(f"{label} keys must be strings")
    actual = frozenset(cast(str, key) for key in mapping)
    if actual != keys:
        missing = sorted(keys - actual)
        unknown = sorted(actual - keys)
        detail: list[str] = []
        if missing:
            detail.append(f"missing {missing}")
        if unknown:
            detail.append(f"unknown {unknown}")
        raise WindowGeometryError(f"{label} has invalid fields: {', '.join(detail)}")
    return cast(Mapping[str, object], mapping)


@dataclass(frozen=True, slots=True)
class PhysicalRect:
    """One non-empty rectangle in physical virtual-screen coordinates."""

    left: int
    top: int
    right: int
    bottom: int

    def __post_init__(self) -> None:
        for label, value in (
            ("left", self.left),
            ("top", self.top),
            ("right", self.right),
            ("bottom", self.bottom),
        ):
            if type(value) is not int:
                raise WindowGeometryError(f"{label} must be an integer")
            if abs(value) > _MAX_ABSOLUTE_COORDINATE:
                raise WindowGeometryError(f"{label} is outside the supported virtual screen")
        if self.right <= self.left or self.bottom <= self.top:
            raise WindowGeometryError("physical rectangle must have positive width and height")
        if self.width > _MAX_DIMENSION or self.height > _MAX_DIMENSION:
            raise WindowGeometryError("physical rectangle exceeds the supported dimensions")

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    def to_config(self) -> dict[str, int]:
        return {
            "left": self.left,
            "top": self.top,
            "right": self.right,
            "bottom": self.bottom,
        }

    @classmethod
    def from_config(cls, value: object, *, label: str = "rectangle") -> PhysicalRect:
        mapping = _strict_mapping(
            value,
            label=label,
            keys=frozenset({"left", "top", "right", "bottom"}),
        )
        return cls(
            left=_strict_int(mapping["left"], label=f"{label}.left"),
            top=_strict_int(mapping["top"], label=f"{label}.top"),
            right=_strict_int(mapping["right"], label=f"{label}.right"),
            bottom=_strict_int(mapping["bottom"], label=f"{label}.bottom"),
        )


def _validate_device_name(value: object, *, label: str) -> str:
    if type(value) is not str:
        raise WindowGeometryError(f"{label} must be a string")
    device_name = value
    if (
        not device_name
        or device_name != device_name.strip()
        or len(device_name) > _MAX_DEVICE_NAME_LENGTH
        or "\x00" in device_name
    ):
        raise WindowGeometryError(f"{label} is invalid")
    return device_name


def _validate_dpi(value: object, *, label: str) -> int:
    dpi = _strict_int(value, label=label)
    if not _MIN_DPI <= dpi <= _MAX_DPI:
        raise WindowGeometryError(f"{label} is outside the supported range")
    return dpi


@dataclass(frozen=True, slots=True)
class MonitorGeometry:
    """Current or persisted geometry for one Windows display monitor."""

    device_name: str
    work_area: PhysicalRect
    dpi: int

    def __post_init__(self) -> None:
        _validate_device_name(self.device_name, label="monitor.device_name")
        if type(self.work_area) is not PhysicalRect:
            raise WindowGeometryError("monitor.work_area must be a PhysicalRect")
        _validate_dpi(self.dpi, label="monitor.dpi")

    def to_config(self) -> dict[str, object]:
        return {
            "device_name": self.device_name,
            "work_area": self.work_area.to_config(),
            "dpi": self.dpi,
        }

    @classmethod
    def from_config(cls, value: object) -> MonitorGeometry:
        mapping = _strict_mapping(
            value,
            label="monitor",
            keys=frozenset({"device_name", "work_area", "dpi"}),
        )
        return cls(
            device_name=_validate_device_name(
                mapping["device_name"],
                label="monitor.device_name",
            ),
            work_area=PhysicalRect.from_config(
                mapping["work_area"],
                label="monitor.work_area",
            ),
            dpi=_validate_dpi(mapping["dpi"], label="monitor.dpi"),
        )


@dataclass(frozen=True, slots=True)
class WindowGeometry:
    """Versioned durable geometry for one Stockroom top-level window."""

    normal_bounds: PhysicalRect
    show_state: WindowShowState
    monitor: MonitorGeometry

    def __post_init__(self) -> None:
        if type(self.normal_bounds) is not PhysicalRect:
            raise WindowGeometryError("normal_bounds must be a PhysicalRect")
        if type(self.show_state) is not WindowShowState:
            raise WindowGeometryError("show_state must be a WindowShowState")
        if type(self.monitor) is not MonitorGeometry:
            raise WindowGeometryError("monitor must be a MonitorGeometry")

    def to_config(self) -> dict[str, object]:
        return {
            "schema": GEOMETRY_SCHEMA,
            "version": GEOMETRY_VERSION,
            "units": PHYSICAL_PIXEL_UNITS,
            "normal_bounds": self.normal_bounds.to_config(),
            "show_state": self.show_state.value,
            "monitor": self.monitor.to_config(),
        }

    @classmethod
    def from_config(cls, value: object) -> WindowGeometry:
        mapping = _strict_mapping(
            value,
            label="window geometry",
            keys=frozenset(
                {
                    "schema",
                    "version",
                    "units",
                    "normal_bounds",
                    "show_state",
                    "monitor",
                }
            ),
        )
        if mapping["schema"] != GEOMETRY_SCHEMA:
            raise WindowGeometryError("window geometry schema is unsupported")
        if type(mapping["version"]) is not int or mapping["version"] != GEOMETRY_VERSION:
            raise WindowGeometryError("window geometry version is unsupported")
        if mapping["units"] != PHYSICAL_PIXEL_UNITS:
            raise WindowGeometryError("window geometry units must be physical pixels")
        if type(mapping["show_state"]) is not str:
            raise WindowGeometryError("show_state must be a string")
        try:
            show_state = WindowShowState(mapping["show_state"])
        except ValueError as exc:
            raise WindowGeometryError("show_state is unsupported") from exc
        return cls(
            normal_bounds=PhysicalRect.from_config(
                mapping["normal_bounds"],
                label="normal_bounds",
            ),
            show_state=show_state,
            monitor=MonitorGeometry.from_config(mapping["monitor"]),
        )


@dataclass(frozen=True, slots=True)
class GeometryResolution:
    """The safe current-monitor placement chosen for persisted geometry."""

    geometry: WindowGeometry
    monitor_recovered: bool
    bounds_clamped: bool
    dpi_scaled: bool


class WindowGeometryApi(Protocol):
    """Narrow native surface used by capture and application."""

    def is_window(self, hwnd: int) -> bool: ...

    def get_window_placement(self, hwnd: int) -> tuple[PhysicalRect, WindowShowState]: ...

    def get_window_dpi(self, hwnd: int) -> int: ...

    def monitor_for_window(self, hwnd: int) -> MonitorGeometry: ...

    def monitors(self) -> Sequence[MonitorGeometry]: ...

    def set_window_bounds(self, hwnd: int, bounds: PhysicalRect) -> None: ...

    def show_window(self, hwnd: int, show_state: WindowShowState) -> None: ...


def window_geometry_from_machine_config(config: object) -> WindowGeometry | None:
    """Decode ``MachineConfig.window`` with exact-key validation.

    ``{}`` is the only empty-state representation because that is the existing
    ``MachineConfig`` default.  Any other malformed value is an error rather
    than a partially trusted placement.
    """

    raw = getattr(config, "window", None)
    if raw == {}:
        return None
    return WindowGeometry.from_config(raw)


def set_machine_config_window_geometry(config: object, geometry: WindowGeometry) -> None:
    """Replace the in-memory ``MachineConfig.window`` payload atomically."""

    if type(geometry) is not WindowGeometry:
        raise WindowGeometryError("geometry must be a WindowGeometry")
    if not hasattr(config, "window"):
        raise WindowGeometryError("configuration has no window field")
    setattr(config, "window", geometry.to_config())


def _distance_squared(rectangle: PhysicalRect, work_area: PhysicalRect) -> int:
    horizontal = max(work_area.left - rectangle.right, rectangle.left - work_area.right, 0)
    vertical = max(work_area.top - rectangle.bottom, rectangle.top - work_area.bottom, 0)
    return horizontal * horizontal + vertical * vertical


def _choose_monitor(
    geometry: WindowGeometry,
    monitors: Sequence[MonitorGeometry],
) -> tuple[MonitorGeometry, bool]:
    if not monitors:
        raise WindowGeometryUnavailable("Windows reported no usable display monitors")
    seen: set[str] = set()
    for monitor in monitors:
        if type(monitor) is not MonitorGeometry:
            raise WindowGeometryError("current monitors must contain MonitorGeometry values")
        normalized_name = monitor.device_name.casefold()
        if normalized_name in seen:
            raise WindowGeometryError("current monitor device names must be unique")
        seen.add(normalized_name)
    device_name = geometry.monitor.device_name.casefold()
    for monitor in monitors:
        if monitor.device_name.casefold() == device_name:
            return monitor, False
    nearest = min(
        monitors,
        key=lambda item: (
            _distance_squared(geometry.normal_bounds, item.work_area),
            item.device_name.casefold(),
        ),
    )
    return nearest, True


def _validate_minimum_size(minimum_size: tuple[int, int]) -> tuple[int, int]:
    if (
        type(minimum_size) is not tuple
        or len(minimum_size) != 2
        or type(minimum_size[0]) is not int
        or type(minimum_size[1]) is not int
        or minimum_size[0] <= 0
        or minimum_size[1] <= 0
        or minimum_size[0] > _MAX_DIMENSION
        or minimum_size[1] > _MAX_DIMENSION
    ):
        raise WindowGeometryError("minimum_size must contain two supported positive integers")
    return minimum_size


def _scale_physical(value: int, *, source_dpi: int, target_dpi: int) -> int:
    return round(value * target_dpi / source_dpi)


def resolve_window_geometry(
    geometry: WindowGeometry,
    monitors: Sequence[MonitorGeometry],
    *,
    minimum_size: tuple[int, int] = (
        DEFAULT_MINIMUM_WIDTH,
        DEFAULT_MINIMUM_HEIGHT,
    ),
) -> GeometryResolution:
    """Map saved geometry into one current monitor and fully clamp it.

    Relative work-area placement and logical size are preserved across a DPI
    change.  If the recorded monitor disappeared, the nearest current work
    area is selected deterministically.  A window can therefore never be
    restored wholly or partly off-screen because a display was unplugged.
    """

    if type(geometry) is not WindowGeometry:
        raise WindowGeometryError("geometry must be a WindowGeometry")
    minimum_width, minimum_height = _validate_minimum_size(minimum_size)
    target, monitor_recovered = _choose_monitor(geometry, monitors)
    source = geometry.monitor
    dpi_scaled = source.dpi != target.dpi

    desired_width = _scale_physical(
        geometry.normal_bounds.width,
        source_dpi=source.dpi,
        target_dpi=target.dpi,
    )
    desired_height = _scale_physical(
        geometry.normal_bounds.height,
        source_dpi=source.dpi,
        target_dpi=target.dpi,
    )
    minimum_width = min(minimum_width, target.work_area.width)
    minimum_height = min(minimum_height, target.work_area.height)
    width = min(max(desired_width, minimum_width), target.work_area.width)
    height = min(max(desired_height, minimum_height), target.work_area.height)

    source_offset_x = geometry.normal_bounds.left - source.work_area.left
    source_offset_y = geometry.normal_bounds.top - source.work_area.top
    desired_left = target.work_area.left + _scale_physical(
        source_offset_x,
        source_dpi=source.dpi,
        target_dpi=target.dpi,
    )
    desired_top = target.work_area.top + _scale_physical(
        source_offset_y,
        source_dpi=source.dpi,
        target_dpi=target.dpi,
    )
    left = min(
        max(desired_left, target.work_area.left),
        target.work_area.right - width,
    )
    top = min(
        max(desired_top, target.work_area.top),
        target.work_area.bottom - height,
    )
    bounds = PhysicalRect(left, top, left + width, top + height)
    resolved = WindowGeometry(
        normal_bounds=bounds,
        show_state=geometry.show_state,
        monitor=target,
    )
    return GeometryResolution(
        geometry=resolved,
        monitor_recovered=monitor_recovered,
        bounds_clamped=width != desired_width
        or height != desired_height
        or left != desired_left
        or top != desired_top,
        dpi_scaled=dpi_scaled,
    )


def capture_window_geometry(
    hwnd: int,
    *,
    api: WindowGeometryApi | None = None,
) -> WindowGeometry:
    """Capture one valid HWND as strict physical-pixel geometry."""

    if type(hwnd) is not int or hwnd <= 0:
        raise WindowGeometryUnavailable("window handle must be a positive integer")
    native = api or _Win32GeometryApi()
    if not native.is_window(hwnd):
        raise WindowGeometryUnavailable("window handle is not valid")
    bounds, show_state = native.get_window_placement(hwnd)
    dpi = _validate_dpi(native.get_window_dpi(hwnd), label="window dpi")
    monitor = native.monitor_for_window(hwnd)
    return WindowGeometry(
        normal_bounds=bounds,
        show_state=show_state,
        monitor=MonitorGeometry(
            device_name=monitor.device_name,
            work_area=monitor.work_area,
            dpi=dpi,
        ),
    )


def apply_window_geometry(
    hwnd: int,
    geometry: WindowGeometry,
    *,
    api: WindowGeometryApi | None = None,
    show: bool = False,
    minimum_size: tuple[int, int] = (
        DEFAULT_MINIMUM_WIDTH,
        DEFAULT_MINIMUM_HEIGHT,
    ),
) -> GeometryResolution:
    """Prepare safe bounds and optionally restore the recorded show state.

    ``show=False`` is the handoff-safe default: the candidate remains hidden
    while its physical bounds are installed.  The returned resolved geometry
    carries the show state for the later visibility commit.  ``show=True``
    performs both operations in order.
    """

    if type(hwnd) is not int or hwnd <= 0:
        raise WindowGeometryUnavailable("window handle must be a positive integer")
    if type(show) is not bool:
        raise WindowGeometryError("show must be a boolean")
    native = api or _Win32GeometryApi()
    if not native.is_window(hwnd):
        raise WindowGeometryUnavailable("window handle is not valid")
    resolution = resolve_window_geometry(
        geometry,
        native.monitors(),
        minimum_size=minimum_size,
    )
    native.set_window_bounds(hwnd, resolution.geometry.normal_bounds)
    if show:
        native.show_window(hwnd, resolution.geometry.show_state)
    return resolution


class _WINDOWPLACEMENT(ctypes.Structure):
    _fields_ = [
        ("length", wintypes.UINT),
        ("flags", wintypes.UINT),
        ("showCmd", wintypes.UINT),
        ("ptMinPosition", wintypes.POINT),
        ("ptMaxPosition", wintypes.POINT),
        ("rcNormalPosition", wintypes.RECT),
    ]


class _MONITORINFOEXW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
        ("szDevice", wintypes.WCHAR * 32),
    ]


@dataclass(frozen=True, slots=True)
class _NativeMonitor:
    handle: int
    geometry: MonitorGeometry
    monitor_area: PhysicalRect


def _rect_from_win32(rectangle: wintypes.RECT) -> PhysicalRect:
    return PhysicalRect(
        int(rectangle.left),
        int(rectangle.top),
        int(rectangle.right),
        int(rectangle.bottom),
    )


def _set_signature(function: object, argtypes: list[object], restype: object) -> None:
    """Set ctypes metadata while allowing ordinary Python test doubles."""

    try:
        setattr(function, "argtypes", argtypes)
        setattr(function, "restype", restype)
    except (AttributeError, TypeError):
        pass


def _win32_failure(message: str) -> WindowGeometryUnavailable:
    return WindowGeometryUnavailable(f"{message} (Win32 error {ctypes.get_last_error()})")


class _Win32GeometryApi:
    """Minimal ctypes adapter; no Win32 library is loaded on other platforms."""

    def __init__(self) -> None:
        if os.name != "nt":
            raise WindowGeometryUnavailable("window geometry requires Windows")
        self._user32 = ctypes.WinDLL("user32", use_last_error=True)  # type: ignore[attr-defined]
        try:
            self._shcore = ctypes.WinDLL("shcore", use_last_error=True)  # type: ignore[attr-defined]
        except OSError:
            self._shcore = None

        callback_factory = getattr(ctypes, "WINFUNCTYPE", ctypes.CFUNCTYPE)
        self._monitor_callback_type = callback_factory(
            wintypes.BOOL,
            wintypes.HANDLE,
            wintypes.HDC,
            ctypes.POINTER(wintypes.RECT),
            wintypes.LPARAM,
        )
        _set_signature(self._user32.IsWindow, [wintypes.HWND], wintypes.BOOL)
        _set_signature(
            self._user32.GetWindowPlacement,
            [wintypes.HWND, ctypes.POINTER(_WINDOWPLACEMENT)],
            wintypes.BOOL,
        )
        _set_signature(self._user32.GetDpiForWindow, [wintypes.HWND], wintypes.UINT)
        _set_signature(
            self._user32.MonitorFromWindow,
            [wintypes.HWND, wintypes.DWORD],
            wintypes.HANDLE,
        )
        _set_signature(
            self._user32.MonitorFromRect,
            [ctypes.POINTER(wintypes.RECT), wintypes.DWORD],
            wintypes.HANDLE,
        )
        _set_signature(
            self._user32.GetMonitorInfoW,
            [wintypes.HANDLE, ctypes.POINTER(_MONITORINFOEXW)],
            wintypes.BOOL,
        )
        _set_signature(
            self._user32.EnumDisplayMonitors,
            [
                wintypes.HDC,
                ctypes.POINTER(wintypes.RECT),
                self._monitor_callback_type,
                wintypes.LPARAM,
            ],
            wintypes.BOOL,
        )
        _set_signature(
            self._user32.SetWindowPlacement,
            [wintypes.HWND, ctypes.POINTER(_WINDOWPLACEMENT)],
            wintypes.BOOL,
        )
        _set_signature(
            self._user32.ShowWindow,
            [wintypes.HWND, ctypes.c_int],
            wintypes.BOOL,
        )
        if self._shcore is not None:
            _set_signature(
                self._shcore.GetDpiForMonitor,
                [
                    wintypes.HANDLE,
                    ctypes.c_int,
                    ctypes.POINTER(wintypes.UINT),
                    ctypes.POINTER(wintypes.UINT),
                ],
                ctypes.c_long,
            )

    def is_window(self, hwnd: int) -> bool:
        return bool(self._user32.IsWindow(hwnd))

    def _dpi_for_monitor(self, handle: int) -> int:
        if self._shcore is None:
            return 96
        dpi_x = wintypes.UINT(0)
        dpi_y = wintypes.UINT(0)
        result = int(
            self._shcore.GetDpiForMonitor(
                handle,
                0,
                ctypes.byref(dpi_x),
                ctypes.byref(dpi_y),
            )
        )
        if result != 0 or dpi_x.value != dpi_y.value:
            return 96
        try:
            return _validate_dpi(int(dpi_x.value), label="monitor dpi")
        except WindowGeometryError:
            return 96

    def _monitor(self, handle: int) -> _NativeMonitor:
        if not handle:
            raise WindowGeometryUnavailable("Windows did not resolve a display monitor")
        information = _MONITORINFOEXW()
        information.cbSize = ctypes.sizeof(information)
        if not self._user32.GetMonitorInfoW(handle, ctypes.byref(information)):
            raise _win32_failure("monitor geometry could not be read")
        return _NativeMonitor(
            handle=int(handle),
            geometry=MonitorGeometry(
                device_name=str(information.szDevice),
                work_area=_rect_from_win32(information.rcWork),
                dpi=self._dpi_for_monitor(int(handle)),
            ),
            monitor_area=_rect_from_win32(information.rcMonitor),
        )

    def _monitor_for_window(self, hwnd: int) -> _NativeMonitor:
        handle = self._user32.MonitorFromWindow(hwnd, _MONITOR_DEFAULTTONEAREST)
        return self._monitor(int(handle or 0))

    def _monitor_for_rect(self, bounds: PhysicalRect) -> _NativeMonitor:
        rectangle = wintypes.RECT(
            bounds.left,
            bounds.top,
            bounds.right,
            bounds.bottom,
        )
        handle = self._user32.MonitorFromRect(
            ctypes.byref(rectangle),
            _MONITOR_DEFAULTTONEAREST,
        )
        return self._monitor(int(handle or 0))

    def get_window_placement(self, hwnd: int) -> tuple[PhysicalRect, WindowShowState]:
        placement = _WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(placement)
        if not self._user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise _win32_failure("window placement could not be read")
        monitor = self._monitor_for_window(hwnd)
        raw = _rect_from_win32(placement.rcNormalPosition)
        # WINDOWPLACEMENT uses work-area coordinates for ordinary top-level
        # windows.  Translate that native restore rectangle into physical
        # virtual-screen coordinates before it enters the durable schema.
        offset_x = monitor.geometry.work_area.left - monitor.monitor_area.left
        offset_y = monitor.geometry.work_area.top - monitor.monitor_area.top
        physical = PhysicalRect(
            raw.left + offset_x,
            raw.top + offset_y,
            raw.right + offset_x,
            raw.bottom + offset_y,
        )
        return physical, _show_state_from_command(int(placement.showCmd))

    def get_window_dpi(self, hwnd: int) -> int:
        dpi = int(self._user32.GetDpiForWindow(hwnd))
        if dpi == 0:
            raise _win32_failure("window DPI could not be read")
        return dpi

    def monitor_for_window(self, hwnd: int) -> MonitorGeometry:
        return self._monitor_for_window(hwnd).geometry

    def monitors(self) -> tuple[MonitorGeometry, ...]:
        found: list[MonitorGeometry] = []
        failure: list[BaseException] = []

        def collect(handle, device_context, rectangle, data) -> bool:
            del device_context, rectangle, data
            try:
                found.append(self._monitor(int(handle)).geometry)
            except BaseException as exc:
                failure.append(exc)
                return False
            else:
                return True

        callback = self._monitor_callback_type(collect)
        enumerated = bool(self._user32.EnumDisplayMonitors(None, None, callback, 0))
        if failure:
            raise failure[0]
        if not enumerated:
            raise _win32_failure("display monitors could not be enumerated")
        if not found:
            raise WindowGeometryUnavailable("Windows reported no usable display monitors")
        return tuple(found)

    def set_window_bounds(self, hwnd: int, bounds: PhysicalRect) -> None:
        monitor = self._monitor_for_rect(bounds)
        offset_x = monitor.geometry.work_area.left - monitor.monitor_area.left
        offset_y = monitor.geometry.work_area.top - monitor.monitor_area.top
        placement = _WINDOWPLACEMENT()
        placement.length = ctypes.sizeof(placement)
        if not self._user32.GetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise _win32_failure("window placement could not be read before applying bounds")
        placement.rcNormalPosition = wintypes.RECT(
            bounds.left - offset_x,
            bounds.top - offset_y,
            bounds.right - offset_x,
            bounds.bottom - offset_y,
        )
        # Keep the current native show command.  This installs restore bounds
        # without making a hidden handoff candidate visible.
        if not self._user32.SetWindowPlacement(hwnd, ctypes.byref(placement)):
            raise _win32_failure("window bounds could not be applied")

    def show_window(self, hwnd: int, show_state: WindowShowState) -> None:
        command = {
            WindowShowState.NORMAL: _SW_SHOWNORMAL,
            WindowShowState.MAXIMIZED: _SW_SHOWMAXIMIZED,
            WindowShowState.MINIMIZED: _SW_SHOWMINIMIZED,
        }[show_state]
        # ShowWindow's return value is the *prior* visibility state, not success.
        self._user32.ShowWindow(hwnd, command)


def _show_state_from_command(command: int) -> WindowShowState:
    if command == _SW_SHOWMAXIMIZED:
        return WindowShowState.MAXIMIZED
    if command in {
        _SW_SHOWMINIMIZED,
        _SW_MINIMIZE,
        _SW_SHOWMINNOACTIVE,
        _SW_FORCEMINIMIZE,
    }:
        return WindowShowState.MINIMIZED
    # Hidden, restored, default, and non-activating normal forms all retain a
    # normal restore state in the durable contract.
    return WindowShowState.NORMAL


__all__ = [
    "DEFAULT_MINIMUM_HEIGHT",
    "DEFAULT_MINIMUM_WIDTH",
    "GEOMETRY_SCHEMA",
    "GEOMETRY_VERSION",
    "GeometryResolution",
    "MonitorGeometry",
    "PHYSICAL_PIXEL_UNITS",
    "PhysicalRect",
    "WindowGeometry",
    "WindowGeometryApi",
    "WindowGeometryError",
    "WindowGeometryUnavailable",
    "WindowShowState",
    "apply_window_geometry",
    "capture_window_geometry",
    "resolve_window_geometry",
    "set_machine_config_window_geometry",
    "window_geometry_from_machine_config",
]
