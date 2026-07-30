from __future__ import annotations

import copy
import ctypes
from dataclasses import dataclass, field
from types import SimpleNamespace

import pytest

from stockroom.credentials import MemoryCredentialStore
from stockroom.host import window_geometry as geometry_module
from stockroom.host.window_geometry import (
    GeometryResolution,
    MonitorGeometry,
    PhysicalRect,
    WindowGeometry,
    WindowGeometryError,
    WindowGeometryUnavailable,
    WindowShowState,
    apply_window_geometry,
    capture_window_geometry,
    resolve_window_geometry,
    set_machine_config_window_geometry,
    window_geometry_from_machine_config,
)
from stockroom.store.machine_config import MachineConfig


def _monitor(
    *,
    name: str = r"\\.\DISPLAY1",
    work_area: PhysicalRect = PhysicalRect(0, 0, 1920, 1040),
    dpi: int = 96,
) -> MonitorGeometry:
    return MonitorGeometry(device_name=name, work_area=work_area, dpi=dpi)


def _geometry(
    *,
    bounds: PhysicalRect = PhysicalRect(100, 80, 1100, 780),
    state: WindowShowState = WindowShowState.NORMAL,
    monitor: MonitorGeometry | None = None,
) -> WindowGeometry:
    return WindowGeometry(
        normal_bounds=bounds,
        show_state=state,
        monitor=monitor or _monitor(),
    )


@dataclass
class _FakeApi:
    placement: tuple[PhysicalRect, WindowShowState] = (
        PhysicalRect(100, 80, 1100, 780),
        WindowShowState.NORMAL,
    )
    dpi: int = 96
    monitor: MonitorGeometry = field(default_factory=_monitor)
    current_monitors: tuple[MonitorGeometry, ...] = field(default_factory=lambda: (_monitor(),))
    valid: bool = True
    operations: list[tuple[str, object]] = field(default_factory=list)

    def is_window(self, hwnd: int) -> bool:
        self.operations.append(("is_window", hwnd))
        return self.valid

    def get_window_placement(self, hwnd: int) -> tuple[PhysicalRect, WindowShowState]:
        self.operations.append(("get_window_placement", hwnd))
        return self.placement

    def get_window_dpi(self, hwnd: int) -> int:
        self.operations.append(("get_window_dpi", hwnd))
        return self.dpi

    def monitor_for_window(self, hwnd: int) -> MonitorGeometry:
        self.operations.append(("monitor_for_window", hwnd))
        return self.monitor

    def monitors(self) -> tuple[MonitorGeometry, ...]:
        self.operations.append(("monitors", None))
        return self.current_monitors

    def set_window_bounds(self, hwnd: int, bounds: PhysicalRect) -> None:
        self.operations.append(("set_window_bounds", (hwnd, bounds)))

    def show_window(self, hwnd: int, show_state: WindowShowState) -> None:
        self.operations.append(("show_window", (hwnd, show_state)))


def test_geometry_round_trips_through_the_exact_versioned_schema() -> None:
    expected = _geometry(state=WindowShowState.MAXIMIZED)

    encoded = expected.to_config()

    assert encoded == {
        "schema": "stockroom.window-geometry",
        "version": 1,
        "units": "physical-pixels",
        "normal_bounds": {
            "left": 100,
            "top": 80,
            "right": 1100,
            "bottom": 780,
        },
        "show_state": "maximized",
        "monitor": {
            "device_name": r"\\.\DISPLAY1",
            "work_area": {
                "left": 0,
                "top": 0,
                "right": 1920,
                "bottom": 1040,
            },
            "dpi": 96,
        },
    }
    assert WindowGeometry.from_config(encoded) == expected


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update({"future": True}), "invalid fields"),
        (lambda value: value.pop("normal_bounds"), "invalid fields"),
        (lambda value: value.update({"version": True}), "version is unsupported"),
        (lambda value: value.update({"units": "logical"}), "physical pixels"),
        (lambda value: value.update({"show_state": "hidden"}), "unsupported"),
        (
            lambda value: value["normal_bounds"].update({"left": True}),
            "normal_bounds.left must be an integer",
        ),
        (
            lambda value: value["monitor"].update({"dpi": 0}),
            "outside the supported range",
        ),
        (
            lambda value: value["monitor"].update({"device_name": " "}),
            "monitor.device_name is invalid",
        ),
    ],
)
def test_persisted_geometry_rejects_unknown_missing_or_weakly_typed_values(
    mutation,
    message: str,
) -> None:
    encoded = copy.deepcopy(_geometry().to_config())
    mutation(encoded)

    with pytest.raises(WindowGeometryError, match=message):
        WindowGeometry.from_config(encoded)


def test_machine_config_window_payload_round_trips_without_a_schema_widening(tmp_path) -> None:
    path = tmp_path / "config.json"
    credentials = MemoryCredentialStore("window-geometry")
    config = MachineConfig.load(path, credential_store=credentials)
    expected = _geometry(state=WindowShowState.MINIMIZED)

    set_machine_config_window_geometry(config, expected)
    config.save(path, credential_store=credentials)
    reloaded = MachineConfig.load(path, credential_store=credentials)

    assert window_geometry_from_machine_config(reloaded) == expected
    assert window_geometry_from_machine_config(MachineConfig()) is None


def test_machine_config_decode_fails_closed_on_malformed_persisted_geometry() -> None:
    config = MachineConfig(window={"schema": "not-stockroom"})

    with pytest.raises(WindowGeometryError, match="invalid fields"):
        window_geometry_from_machine_config(config)


def test_capture_records_physical_normal_bounds_show_state_monitor_and_window_dpi() -> None:
    monitor = _monitor(dpi=96)
    api = _FakeApi(
        placement=(
            PhysicalRect(-1700, 120, -700, 820),
            WindowShowState.MAXIMIZED,
        ),
        dpi=144,
        monitor=monitor,
    )

    captured = capture_window_geometry(4321, api=api)

    assert captured == WindowGeometry(
        normal_bounds=PhysicalRect(-1700, 120, -700, 820),
        show_state=WindowShowState.MAXIMIZED,
        monitor=MonitorGeometry(
            device_name=monitor.device_name,
            work_area=monitor.work_area,
            dpi=144,
        ),
    )
    assert api.operations == [
        ("is_window", 4321),
        ("get_window_placement", 4321),
        ("get_window_dpi", 4321),
        ("monitor_for_window", 4321),
    ]


def test_capture_rejects_an_invalid_handle_before_reading_native_state() -> None:
    api = _FakeApi(valid=False)

    with pytest.raises(WindowGeometryUnavailable, match="not valid"):
        capture_window_geometry(4321, api=api)

    assert api.operations == [("is_window", 4321)]


def test_capture_rejects_an_untrusted_native_dpi() -> None:
    api = _FakeApi(dpi=0)

    with pytest.raises(WindowGeometryError, match="outside the supported range"):
        capture_window_geometry(4321, api=api)

    assert api.operations == [
        ("is_window", 4321),
        ("get_window_placement", 4321),
        ("get_window_dpi", 4321),
    ]


def test_same_monitor_geometry_is_preserved_when_it_is_already_safe() -> None:
    expected = _geometry()

    resolved = resolve_window_geometry(expected, (expected.monitor,))

    assert resolved == GeometryResolution(
        geometry=expected,
        monitor_recovered=False,
        bounds_clamped=False,
        dpi_scaled=False,
    )


def test_resolution_scales_bounds_and_work_area_offset_for_current_monitor_dpi() -> None:
    saved_monitor = _monitor(
        work_area=PhysicalRect(0, 0, 1920, 1080),
        dpi=96,
    )
    current_monitor = _monitor(
        work_area=PhysicalRect(0, 0, 2560, 1440),
        dpi=144,
    )
    saved = _geometry(
        bounds=PhysicalRect(100, 50, 900, 650),
        monitor=saved_monitor,
    )

    resolved = resolve_window_geometry(
        saved,
        (current_monitor,),
        minimum_size=(100, 100),
    )

    assert resolved.geometry == WindowGeometry(
        normal_bounds=PhysicalRect(150, 75, 1350, 975),
        show_state=WindowShowState.NORMAL,
        monitor=current_monitor,
    )
    assert resolved.dpi_scaled
    assert not resolved.bounds_clamped
    assert not resolved.monitor_recovered


def test_missing_monitor_recovers_to_nearest_current_work_area() -> None:
    removed = _monitor(
        name=r"\\.\DISPLAY2",
        work_area=PhysicalRect(-1920, 0, 0, 1080),
    )
    current = _monitor(work_area=PhysicalRect(0, 0, 1920, 1040))
    saved = _geometry(
        bounds=PhysicalRect(-1800, 100, -800, 800),
        monitor=removed,
    )

    resolved = resolve_window_geometry(saved, (current,))

    assert resolved.geometry.normal_bounds == PhysicalRect(120, 100, 1120, 800)
    assert resolved.geometry.monitor == current
    assert resolved.monitor_recovered
    assert not resolved.bounds_clamped


def test_oversized_or_offscreen_bounds_are_fully_clamped_into_the_work_area() -> None:
    monitor = _monitor()
    saved = _geometry(
        bounds=PhysicalRect(-100, -100, 3000, 2000),
        monitor=monitor,
    )

    resolved = resolve_window_geometry(saved, (monitor,))

    assert resolved.geometry.normal_bounds == monitor.work_area
    assert resolved.bounds_clamped


def test_no_current_monitor_fails_before_any_window_mutation() -> None:
    api = _FakeApi(current_monitors=())

    with pytest.raises(WindowGeometryUnavailable, match="no usable display"):
        apply_window_geometry(4321, _geometry(), api=api)

    assert api.operations == [
        ("is_window", 4321),
        ("monitors", None),
    ]


def test_duplicate_current_monitor_identity_fails_before_any_window_mutation() -> None:
    monitor = _monitor()
    api = _FakeApi(current_monitors=(monitor, monitor))

    with pytest.raises(WindowGeometryError, match="device names must be unique"):
        apply_window_geometry(4321, _geometry(), api=api)

    assert api.operations == [
        ("is_window", 4321),
        ("monitors", None),
    ]


@pytest.mark.parametrize("show", [False, True])
def test_apply_installs_hidden_bounds_before_optionally_restoring_show_state(show: bool) -> None:
    api = _FakeApi()
    saved = _geometry(state=WindowShowState.MAXIMIZED)

    resolution = apply_window_geometry(4321, saved, api=api, show=show)

    assert resolution.geometry == saved
    expected = [
        ("is_window", 4321),
        ("monitors", None),
        ("set_window_bounds", (4321, saved.normal_bounds)),
    ]
    if show:
        expected.append(("show_window", (4321, WindowShowState.MAXIMIZED)))
    assert api.operations == expected


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        (geometry_module._SW_HIDE, WindowShowState.NORMAL),
        (geometry_module._SW_SHOWNORMAL, WindowShowState.NORMAL),
        (geometry_module._SW_SHOWMAXIMIZED, WindowShowState.MAXIMIZED),
        (geometry_module._SW_SHOWMINIMIZED, WindowShowState.MINIMIZED),
        (geometry_module._SW_MINIMIZE, WindowShowState.MINIMIZED),
        (geometry_module._SW_SHOWMINNOACTIVE, WindowShowState.MINIMIZED),
        (geometry_module._SW_FORCEMINIMIZE, WindowShowState.MINIMIZED),
    ],
)
def test_native_show_commands_have_one_durable_state(
    command: int,
    expected: WindowShowState,
) -> None:
    assert geometry_module._show_state_from_command(command) is expected


class _FakeUser32:
    def __init__(self) -> None:
        self.applied: geometry_module._WINDOWPLACEMENT | None = None
        self.shown: list[tuple[int, int]] = []

    def IsWindow(self, hwnd: int) -> bool:
        return hwnd == 4321

    def GetWindowPlacement(self, hwnd: int, pointer) -> bool:
        assert hwnd == 4321
        placement = pointer._obj
        placement.showCmd = geometry_module._SW_HIDE
        placement.rcNormalPosition = geometry_module.wintypes.RECT(60, 70, 1060, 770)
        return True

    def GetDpiForWindow(self, hwnd: int) -> int:
        assert hwnd == 4321
        return 144

    def MonitorFromWindow(self, hwnd: int, fallback: int) -> int:
        assert hwnd == 4321
        assert fallback == geometry_module._MONITOR_DEFAULTTONEAREST
        return 99

    def MonitorFromRect(self, rectangle, fallback: int) -> int:
        assert fallback == geometry_module._MONITOR_DEFAULTTONEAREST
        bounds = rectangle._obj
        assert (bounds.left, bounds.top, bounds.right, bounds.bottom) == (
            100,
            100,
            1100,
            800,
        )
        return 99

    def GetMonitorInfoW(self, handle: int, pointer) -> bool:
        assert handle == 99
        information = pointer._obj
        information.rcMonitor = geometry_module.wintypes.RECT(0, 0, 1920, 1080)
        information.rcWork = geometry_module.wintypes.RECT(40, 30, 1920, 1040)
        information.szDevice = r"\\.\DISPLAY1"
        return True

    def SetWindowPlacement(self, hwnd: int, pointer) -> bool:
        assert hwnd == 4321
        placement = pointer._obj
        copied = geometry_module._WINDOWPLACEMENT()
        ctypes.memmove(
            ctypes.byref(copied),
            ctypes.byref(placement),
            ctypes.sizeof(copied),
        )
        self.applied = copied
        return True

    def ShowWindow(self, hwnd: int, command: int) -> bool:
        self.shown.append((hwnd, command))
        return False


class _FakeShcore:
    def GetDpiForMonitor(self, handle: int, kind: int, dpi_x, dpi_y) -> int:
        assert handle == 99
        assert kind == 0
        dpi_x._obj.value = 144
        dpi_y._obj.value = 144
        return 0


def _native_api(user32: _FakeUser32) -> geometry_module._Win32GeometryApi:
    api = object.__new__(geometry_module._Win32GeometryApi)
    api._user32 = user32
    api._shcore = _FakeShcore()
    return api


def test_win32_adapter_translates_workspace_placement_to_physical_screen_pixels() -> None:
    user32 = _FakeUser32()
    api = _native_api(user32)

    bounds, show_state = api.get_window_placement(4321)

    assert bounds == PhysicalRect(100, 100, 1100, 800)
    assert show_state is WindowShowState.NORMAL


def test_win32_adapter_applies_screen_bounds_as_workspace_placement_without_showing() -> None:
    user32 = _FakeUser32()
    api = _native_api(user32)

    api.set_window_bounds(4321, PhysicalRect(100, 100, 1100, 800))

    assert user32.applied is not None
    applied = user32.applied.rcNormalPosition
    assert (applied.left, applied.top, applied.right, applied.bottom) == (
        60,
        70,
        1060,
        770,
    )
    assert user32.applied.showCmd == geometry_module._SW_HIDE
    assert user32.shown == []


def test_native_show_uses_the_requested_state_without_treating_return_as_success() -> None:
    user32 = _FakeUser32()
    api = _native_api(user32)

    api.show_window(4321, WindowShowState.MINIMIZED)

    assert user32.shown == [(4321, geometry_module._SW_SHOWMINIMIZED)]
