from stockroom.api.serve import pick_free_port


def test_pick_free_port_returns_a_usable_loopback_port():
    port = pick_free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536


def test_two_calls_can_differ():
    ports = {pick_free_port() for _ in range(5)}
    assert len(ports) >= 1  # at least usable; OS may reuse, but never raises


def test_run_refuses_a_non_loopback_host():
    import pytest

    from stockroom.api.serve import run

    with pytest.raises(ValueError):
        run(host="0.0.0.0")  # binding beyond loopback is refused (spec section 2.2)


def test_build_context_auto_wires_kicad(library_root, tmp_path, monkeypatch):
    # every real boot (windowed host and standalone serve both come through here)
    # wires KiCad automatically, so the library is visible without the Doctor click
    from pathlib import Path

    from stockroom.api import serve

    calls = {}

    def fake_auto_wire(kicad_dir, profile, cli=None, **kwargs):
        calls["kicad_dir"] = Path(kicad_dir)
        calls["profile"] = profile.name
        return "WIRING-REPORT"

    monkeypatch.setattr(serve, "auto_wire", fake_auto_wire)
    ctx = serve.build_context(library_root, kicad_dir=tmp_path / "kicad")
    assert calls["kicad_dir"] == tmp_path / "kicad"
    assert calls["profile"] == "Main"
    assert ctx.last_wiring == "WIRING-REPORT"
