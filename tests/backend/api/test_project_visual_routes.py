"""Format-neutral native board geometry and artifact routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from tests.backend.api.test_projects import (
    _make_altium_api_project,
    _make_project,
    _register,
)


def test_board_geometry_delegates_both_edas_to_one_adapter_contract(
    client, tmp_path, monkeypatch
):
    kicad_root = _make_project(tmp_path / "ext" / "board")
    (kicad_root / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    altium_root = _make_altium_api_project(tmp_path / "ext" / "amp")
    (altium_root / "Amp.PcbDoc").write_bytes(b"native-altium-board")
    kicad = _register(client, kicad_root)
    altium = _register(client, altium_root)
    calls = []

    class Adapter:
        def __init__(self, key):
            self.key = key

        def board_geometry(self, project):
            calls.append((self.key, project.id))
            return {
                "schema_version": 1,
                "adapter": self.key,
                "status": "ready",
                "boards": project.board_paths,
                "placements": [
                    {
                        "reference": "R1",
                        "board": project.board_paths[0],
                        "x_mm": 10.25,
                        "y_mm": 18.5,
                        "rotation_deg": 90.0,
                        "side": "top",
                        "footprint": "R_0402_1005Metric",
                    }
                ],
            }

    monkeypatch.setattr(
        "stockroom.api.routers.projects.get_adapter",
        lambda key: Adapter(key),
    )

    kicad_geometry = client.get(
        f"/api/projects/{kicad['id']}/board-geometry"
    )
    altium_geometry = client.get(
        f"/api/projects/{altium['id']}/board-geometry"
    )
    assert kicad_geometry.status_code == altium_geometry.status_code == 200
    assert set(kicad_geometry.json()["placements"][0]) == set(
        altium_geometry.json()["placements"][0]
    )
    assert calls == [("kicad", kicad["id"]), ("altium", altium["id"])]


def test_native_visuals_use_one_contract_and_serve_both_edas(
    client, tmp_path, monkeypatch
):
    kicad_root = _make_project(tmp_path / "ext" / "board")
    (kicad_root / "board.kicad_pcb").write_text("(kicad_pcb)\n", encoding="utf-8")
    altium_root = _make_altium_api_project(tmp_path / "ext" / "amp")
    (altium_root / "Amp.PcbDoc").write_bytes(b"native-altium-board")
    kicad = _register(client, kicad_root)
    altium = _register(client, altium_root)
    calls = []

    class Adapter:
        def __init__(self, key):
            self.key = key

        def render(self, project):
            calls.append((self.key, project.id))
            if self.key == "kicad":
                (Path(project.root) / "board.kicad_prl").write_text(
                    "generated preference",
                    encoding="utf-8",
                )
            payload = f"<svg data-adapter='{self.key}'/>".encode()
            artifact_id = f"{self.key}-top"
            return SimpleNamespace(
                evidence={
                    "schema_version": 1,
                    "adapter": self.key,
                    "status": "ready",
                    "runtime": {"name": self.key, "version": "test"},
                    "documents": [
                        {
                            "kind": "pcb",
                            "path": project.board_paths[0],
                            "status": "ready",
                            "detail": "Native board views",
                            "artifacts": [
                                {
                                    "id": artifact_id,
                                    "kind": "pcb",
                                    "path": project.board_paths[0],
                                    "view": "top",
                                    "label": "Top copper + mask + silkscreen",
                                    "page": 1,
                                    "media_type": "image/svg+xml",
                                    "width": 100,
                                    "height": 60,
                                    "bytes": len(payload),
                                    "sha256": "digest",
                                }
                            ],
                        }
                    ],
                    "summary": {"documents": 1, "artifacts": 1, "blocked": 0},
                    "detail": "Native PCB views are ready",
                    "digest": f"{self.key}-digest",
                },
                artifacts={
                    artifact_id: SimpleNamespace(
                        content=payload,
                        media_type="image/svg+xml",
                    )
                },
            )

    monkeypatch.setattr(
        "stockroom.api.routers.projects.get_adapter",
        lambda key: Adapter(key),
    )

    for record in (kicad, altium):
        metadata = client.get(f"/api/projects/{record['id']}/visuals")
        assert metadata.status_code == 200, metadata.text
        artifact = metadata.json()["documents"][0]["artifacts"][0]
        image = client.get(
            f"/api/projects/{record['id']}/visuals/{artifact['id']}"
        )
        assert image.status_code == 200, image.text
        assert image.headers["content-type"].startswith("image/svg+xml")
        assert f"data-adapter='{record['eda']}'".encode() in image.content

    assert calls == [("kicad", kicad["id"]), ("altium", altium["id"])]
    assert not (kicad_root / "board.kicad_prl").exists()

    refreshed = client.get(
        f"/api/projects/{kicad['id']}/visuals",
        params={"refresh": "true"},
    )
    assert refreshed.status_code == 200
    assert calls[-1] == ("kicad", kicad["id"])
    assert len(calls) == 3
    assert not (kicad_root / "board.kicad_prl").exists()


def test_native_visuals_reject_unknown_artifacts(client, tmp_path, monkeypatch):
    record = _register(client, _make_project(tmp_path / "ext" / "board"))

    class Adapter:
        def render(self, _project):
            return SimpleNamespace(
                evidence={"status": "ready", "documents": []},
                artifacts={},
            )

    monkeypatch.setattr(
        "stockroom.api.routers.projects.get_adapter",
        lambda _key: Adapter(),
    )

    response = client.get(f"/api/projects/{record['id']}/visuals/nope")
    assert response.status_code == 404
