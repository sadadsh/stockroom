"""PassiveFastPathSource + its wiring as registry source #0 in the pipeline.

The passive fast path is offline and deterministic, so a passive MPN enriches
fully with NO network (the owner's no-API headline). These tests prove the source
fills identity + specs + the resolved KiCad stock asset paths, that it contributes
nothing for a non-passive MPN (never walling off the walk), and that the pipeline
returns real passive data even when every network source is dead.
"""

from __future__ import annotations

import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.pipeline import EnrichmentPipeline, PassiveFastPathSource
from stockroom.enrich.registry import DEFAULT_WANT


def test_source_fills_identity_specs_and_asset_paths_for_a_passive():
    r = PassiveFastPathSource().enrich("667-ERJ-P03F1101V", "Resistors", set(DEFAULT_WANT))
    # distributor prefix stripped -> the clean manufacturer MPN
    assert r.mpn.value == "ERJ-P03F1101V"
    assert r.manufacturer.value == "Panasonic"
    assert r.package.value == "0603"
    assert r.description is not None and "Resistor" in r.description.value
    specs = {k: v.value for k, v in r.specs.items()}
    assert specs["Resistance"] == "1.1 kOhm"
    assert specs["Tolerance"] == "1%"
    assert specs["Power"] == "0.2 W"
    # exact KiCad stock asset paths carried as facts (owner: every part carries them)
    assert specs["Symbol"] == "Device:R"
    assert specs["Footprint"] == "Resistor_SMD:R_0603_1608Metric"
    assert specs["3D Model"] == "Resistor_SMD.3dshapes/R_0603_1608Metric.wrl"


def test_source_contributes_nothing_for_a_non_passive_mpn():
    r = PassiveFastPathSource().enrich("STM32F103C8T6", "ICs", set(DEFAULT_WANT))
    assert r.mpn is None and r.package is None and r.manufacturer is None
    assert not r.specs


class _DeadFetcher:
    """Every network fetch fails, simulating a fully offline box."""

    def rendered_html(self, url, timeout=20.0):
        raise EnrichError("offline")


def test_pipeline_enriches_a_passive_fully_offline(tmp_path):
    # No network at all: the scrape source is dead. A passive must still come back
    # with its value, tolerance, package and stock assets from the offline fast path.
    pipe = EnrichmentPipeline(tmp_path, fetcher=_DeadFetcher())
    result = pipe.enrich("ERJ-P03F1101V", "Resistors")
    assert result.package.value == "0603"
    assert result.package.source == "passive"
    specs = {k: v.value for k, v in result.specs.items()}
    assert specs["Resistance"] == "1.1 kOhm"
    assert specs["Footprint"] == "Resistor_SMD:R_0603_1608Metric"


def test_passive_is_the_first_source_so_it_wins_the_shared_fields(tmp_path):
    pipe = EnrichmentPipeline(tmp_path, fetcher=_DeadFetcher())
    assert pipe.registry.sources[0].name == "passive"
