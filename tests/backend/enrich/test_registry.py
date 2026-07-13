import pytest

from stockroom.enrich.errors import EnrichError
from stockroom.enrich.registry import SourceRegistry
from stockroom.enrich.schema import EnrichmentResult, Sourced


class _FakeSource:
    def __init__(self, name, fields, raises=False):
        self.name = name
        self._fields = fields  # {field: value}
        self._raises = raises
        self.was_called_with = None

    def enrich(self, mpn, category, remaining):
        self.was_called_with = set(remaining)
        if self._raises:
            raise EnrichError(f"{self.name} down")
        r = EnrichmentResult(category=category)
        for f, v in self._fields.items():
            setattr(r, f, Sourced(v, self.name, "high"))
        return r


def test_first_source_wins_and_second_fills_only_the_rest():
    s1 = _FakeSource("lcsc", {"mpn": "M1", "manufacturer": "MAN1"})
    s2 = _FakeSource("scrape", {"manufacturer": "MAN2", "description": "D2"})
    reg = SourceRegistry([s1, s2])
    r = reg.enrich("M1", "ICs")
    assert r.mpn.value == "M1" and r.mpn.source == "lcsc"
    # manufacturer already filled by lcsc; scrape must not overwrite it
    assert r.manufacturer.value == "MAN1"
    # description was still missing after lcsc, so scrape filled it
    assert r.description.value == "D2"
    # scrape was only asked for what lcsc left missing
    assert "manufacturer" not in s2.was_called_with


def test_a_source_that_raises_is_skipped_and_the_walk_continues():
    dead = _FakeSource("scrape", {}, raises=True)
    alive = _FakeSource("mouser", {"mpn": "M1"})
    reg = SourceRegistry([dead, alive])
    r = reg.enrich("M1", "ICs")
    assert r.mpn.value == "M1" and r.mpn.source == "mouser"  # dead source never blocked


def test_walk_stops_early_once_nothing_remains():
    s1 = _FakeSource("lcsc", {"mpn": "M1", "manufacturer": "M", "description": "d",
                              "datasheet_url": "u", "stock": 1, "package": "QFN"})
    s2 = _FakeSource("scrape", {"mpn": "SHOULD-NOT-RUN"})
    reg = SourceRegistry([s1, s2])
    reg.enrich("M1", "ICs", want={"mpn", "manufacturer", "description",
                                  "datasheet_url", "stock", "package"})
    assert s2.was_called_with is None  # s1 satisfied everything; s2 never called
