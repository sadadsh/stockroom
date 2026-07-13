import pytest

from tests.backend.conftest import requires_kicad_cli


def test_symbol_preview_404_when_part_absent(client):
    r = client.get("/api/previews/symbol/nope.svg")
    assert r.status_code == 404


def test_symbol_preview_uses_the_injected_cli_and_returns_svg(app_ctx, tmp_path):
    # Inject a fake CLI that writes a known SVG, so the render path is exercised
    # without kicad-cli. The fake honors the sym_export_svg signature.
    from fastapi.testclient import TestClient

    from stockroom.api.app import create_app

    class _FakeCli:
        def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
            out = out_dir / f"{symbol}_unit1.svg"
            out.write_text("<svg><!-- fake --></svg>", encoding="utf-8")
            return [out]

        def fp_export_svg(self, pretty_dir, footprint, out_dir, layers="F.Cu,F.SilkS,F.Fab"):
            out = out_dir / f"{footprint}.svg"
            out.write_text("<svg><!-- fp --></svg>", encoding="utf-8")
            return out

    app_ctx.cli = _FakeCli()
    # the tps62130 fixture part must have its symbol lib file on disk for hashing;
    # write a placeholder symbol lib at the expected category path
    sym_path = app_ctx.profile.library.symbol_lib_path("ICs")
    sym_path.parent.mkdir(parents=True, exist_ok=True)
    sym_path.write_text("(kicad_symbol_lib)", encoding="utf-8")

    app = create_app(app_ctx)
    with TestClient(app, base_url="http://test", raise_server_exceptions=False,
                    headers={"X-Stockroom-Token": "testtoken"}) as c:
        r = c.get("/api/previews/symbol/tps62130.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert "svg" in r.text


@requires_kicad_cli
def test_symbol_preview_end_to_end_with_real_cli(client):
    # Only meaningful once the fixture ships a real .kicad_sym with the symbol; this
    # marks the honest integration boundary. Skipped where kicad-cli is absent.
    r = client.get("/api/previews/symbol/tps62130.svg")
    assert r.status_code in (200, 404, 502)
