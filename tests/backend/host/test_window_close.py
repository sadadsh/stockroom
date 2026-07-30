from __future__ import annotations

from stockroom.host import window as window_module


class _Window:
    def __init__(self) -> None:
        self.destroyed = False

    def destroy(self) -> None:
        self.destroyed = True


class _User32:
    def __init__(self, *, accepted: bool) -> None:
        self.accepted = accepted
        self.open = True
        self.messages: list[tuple[int, int, int, int]] = []

    def PostMessageW(self, hwnd: int, message: int, wparam: int, lparam: int) -> bool:
        self.messages.append((hwnd, message, wparam, lparam))
        if self.accepted:
            self.open = False
        return self.accepted

    def IsWindow(self, _hwnd: int) -> bool:
        return self.open


def test_background_close_posts_to_the_verified_native_window(monkeypatch) -> None:
    window = _Window()
    user32 = _User32(accepted=True)
    monkeypatch.setattr(
        window_module,
        "_current_process_window_handle",
        lambda *args, **kwargs: 4242,
    )

    assert window_module.request_window_close(window, user32=user32)
    assert user32.messages == [(4242, window_module._WM_CLOSE, 0, 0)]
    assert window.destroyed is False


def test_close_falls_back_to_destroy_when_native_post_is_rejected(monkeypatch) -> None:
    window = _Window()
    user32 = _User32(accepted=False)
    monkeypatch.setattr(
        window_module,
        "_current_process_window_handle",
        lambda *args, **kwargs: 4242,
    )

    assert window_module.request_window_close(window, user32=user32, timeout=0)
    assert user32.messages == [(4242, window_module._WM_CLOSE, 0, 0)]
    assert window.destroyed is True


def test_close_finds_the_current_process_window_without_module_state(
    monkeypatch,
) -> None:
    user32 = _User32(accepted=True)
    monkeypatch.setattr(window_module, "active_window", lambda: None)
    monkeypatch.setattr(
        window_module,
        "_current_process_named_window_handle",
        lambda *args, **kwargs: 4242,
    )

    assert window_module.request_window_close(user32=user32, process_id=1234)
    assert user32.messages == [(4242, window_module._WM_CLOSE, 0, 0)]


def test_close_fails_when_no_window_can_be_resolved(monkeypatch) -> None:
    monkeypatch.setattr(window_module, "active_window", lambda: None)
    monkeypatch.setattr(
        window_module,
        "_current_process_named_window_handle",
        lambda *args, **kwargs: None,
    )

    assert window_module.request_window_close() is False
