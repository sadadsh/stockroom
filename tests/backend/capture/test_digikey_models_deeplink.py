"""Land the person ON the DigiKey provider tab they already reached once by hand.

DigiKey's product page is the one surface that gathers Ultra Librarian, SnapMagic and TraceParts
together, which is why the owner works from it. Stockroom, however, opened a keyword SEARCH every
single time, so every part cost the same search, the same navigation and the same tab click - work
the person had already done for that exact part on a previous visit.

DigiKey publishes a per-part models page with a provider tab
(`https://www.digikey.com/en/models/<id>?tab=<provider>`). The id is opaque and there is no
sanctioned way to look it up, but the person's own navigation reveals it: `UserCaptureResult`
already carries the `final_url` of the page they ended on. Reading that URL is reading something
Stockroom was handed; it is not scraping, and nothing here operates a DigiKey control.

So this is a two-run optimisation. The first capture for a part behaves EXACTLY as before. It
learns the id as a side effect, and every later capture skips straight to the tab.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from stockroom.capture import guided
from stockroom.capture.browser import UserCaptureResult
from stockroom.capture.digikey_models import (
    DigiKeyModelsIds,
    digikey_models_id,
    digikey_models_url,
)
from stockroom.capture.vendors import (
    _DIGIKEY_CADENAS_ROUTE,
    _DIGIKEY_MANUFACTURER_ROUTE,
    _DIGIKEY_SNAPMAGIC_ROUTE,
    _DIGIKEY_TRACEPARTS_ROUTE,
    _DIGIKEY_ULTRALIBRARIAN_ROUTE,
    DigiKeySnapMagicRouteAdapter,
    DigiKeyTracePartsRouteAdapter,
    DigiKeyUltraLibrarianAdapter,
)

_MANUFACTURER = "Texas Instruments"
_MPN = "TPS2121RUXR"
_SEARCH_URL = "https://www.digikey.com/en/products/result?keywords=TPS2121RUXR"


def _store(tmp_path: Path) -> DigiKeyModelsIds:
    return DigiKeyModelsIds(tmp_path / "DigiKey Models.json")


# --- reading the id off the person's own navigation -----------------------------------------


def test_a_models_final_url_teaches_the_id():
    assert digikey_models_id("https://www.digikey.com/en/models/6695662") == "6695662"
    # The person's own tab choice rides along in the query and changes nothing about the id.
    assert (
        digikey_models_id("https://www.digikey.com/en/models/6695662?tab=snapmagic")
        == "6695662"
    )


@pytest.mark.parametrize(
    "final_url",
    [
        # Where a first-run capture actually starts and often ends: nothing to learn here.
        _SEARCH_URL,
        "https://www.digikey.com/en/products/detail/texas-instruments/TPS2121RUXR/16584161",
        "https://www.snapeda.com/parts/TPS2121RUXR/Texas%20Instruments/view-part/",
        "",
        # A LOOK-ALIKE host. `digikey.com.evil.test` ends with nothing the naive check would
        # notice, and `evil.test/www.digikey.com/en/models/1` puts the whole brand in the path.
        "https://www.digikey.com.evil.test/en/models/6695662",
        "https://evil.test/www.digikey.com/en/models/6695662",
        "https://digikey.com.evil.test/en/models/6695662?tab=snapmagic",
        # Not HTTPS, and credentials smuggled into the authority.
        "http://www.digikey.com/en/models/6695662",
        "https://user:password@www.digikey.com/en/models/6695662",
        "https://www.digikey.com:8443/en/models/6695662",
        # Not a models id.
        "https://www.digikey.com/en/models/",
        "https://www.digikey.com/en/models/abc",
        "https://www.digikey.com/en/models/6695662abc",
        "https://www.digikey.com/en/models/-1",
        "https://www.digikey.com/en/models/6695662.json",
        "https://www.digikey.com/en/models/0123456",
        "https://www.digikey.com/en/models/999999999999999999999",
        # Path traversal, raw and percent-encoded, plus an extra segment.
        "https://www.digikey.com/en/models/../../en/products/result",
        "https://www.digikey.com/en/models/6695662/../../evil",
        "https://www.digikey.com/en/models/%2e%2e%2f%2e%2e%2fevil",
        "https://www.digikey.com/en/models/6695662/downloads",
        # Query and fragment smuggled into the id itself.
        "https://www.digikey.com/en/models/6695662%3Ftab%3Devil",
        "https://www.digikey.com/en/models/6695662%23evil",
        "https://www.digikey.com/en/models/6695662%2f..%2fevil",
        # No origin at all.
        "/en/models/6695662",
        "//www.digikey.com/en/models/6695662",
        "javascript:alert(1)",
        "not a url",
    ],
)
def test_a_url_that_is_not_a_digikey_models_page_teaches_nothing(final_url):
    assert digikey_models_id(final_url) == ""


def test_a_hostile_final_url_is_never_persisted(tmp_path):
    path = tmp_path / "DigiKey Models.json"
    store = DigiKeyModelsIds(path)
    for final_url in (
        "https://www.digikey.com.evil.test/en/models/6695662",
        "https://www.digikey.com/en/models/6695662/../../evil",
        "https://www.digikey.com/en/models/%2e%2e%2fevil",
        _SEARCH_URL,
    ):
        assert store.learn(manufacturer=_MANUFACTURER, mpn=_MPN, final_url=final_url) == ""
    assert store.get(manufacturer=_MANUFACTURER, mpn=_MPN) == ""
    # Nothing hostile may reach the disk, not even as a rejected record.
    assert not path.exists()


# --- the store ------------------------------------------------------------------------------


def test_the_id_is_learned_once_and_survives_a_restart(tmp_path):
    path = tmp_path / "DigiKey Models.json"
    learner = DigiKeyModelsIds(path)
    assert (
        learner.learn(
            manufacturer=_MANUFACTURER,
            mpn=_MPN,
            final_url="https://www.digikey.com/en/models/6695662?tab=snapmagic",
        )
        == "6695662"
    )
    # A later run is a different process, so the fact has to be on disk, not in memory.
    assert DigiKeyModelsIds(path).get(manufacturer=_MANUFACTURER, mpn=_MPN) == "6695662"


def test_the_id_is_bound_to_the_exact_part_not_to_the_mpn_alone(tmp_path):
    """Two manufacturers ship the same MPN string. A models page belongs to ONE of them.

    Keying on the MPN alone would deep-link one manufacturer's part to another's models page -
    the same class of mistake the exact-identity gate exists to stop everywhere else.
    """
    store = _store(tmp_path)
    store.learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/6695662",
    )
    assert store.get(manufacturer="Onsemi", mpn=_MPN) == ""
    assert store.get(manufacturer=_MANUFACTURER, mpn="TPS2121RUXT") == ""
    # Case and surrounding whitespace are presentation, not identity.
    assert store.get(manufacturer=" texas instruments ", mpn=" tps2121ruxr ") == "6695662"


def test_a_part_with_no_identity_is_never_stored(tmp_path):
    store = _store(tmp_path)
    models_url = "https://www.digikey.com/en/models/6695662"
    assert store.learn(manufacturer="", mpn=_MPN, final_url=models_url) == ""
    assert store.learn(manufacturer=_MANUFACTURER, mpn="", final_url=models_url) == ""
    assert store.get(manufacturer="", mpn="") == ""


def test_a_corrupt_or_hostile_store_file_is_a_miss_not_a_crash(tmp_path):
    path = tmp_path / "DigiKey Models.json"
    for body in (
        "not json at all",
        "[]",
        '{"parts": 7}',
        # A tampered file must not be able to inject a foreign id into a deep link.
        '{"parts": {"texas instruments": {"tps2121ruxr": {"models_id": "../evil"}}}}',
        '{"parts": {"texas instruments": {"tps2121ruxr": {"models_id": 6695662}}}}',
    ):
        path.write_text(body, encoding="utf-8")
        assert DigiKeyModelsIds(path).get(manufacturer=_MANUFACTURER, mpn=_MPN) == ""


def test_a_relearned_id_replaces_the_stale_one(tmp_path):
    store = _store(tmp_path)
    store.learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/1111111",
    )
    store.learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/6695662",
    )
    assert store.get(manufacturer=_MANUFACTURER, mpn=_MPN) == "6695662"


def test_the_store_records_the_id_and_nothing_about_the_page(tmp_path):
    """Only the id. Page CONTENT is not ours to keep, and a URL can carry a session token."""

    path = tmp_path / "DigiKey Models.json"
    DigiKeyModelsIds(path).learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/6695662?tab=snapmagic&token=secret",
    )
    body = path.read_text(encoding="utf-8")
    assert "secret" not in body
    assert "token" not in body
    entry = json.loads(body)["parts"]["texas instruments"]["tps2121ruxr"]
    assert set(entry) == {"models_id"}


# --- the tab, as route data ------------------------------------------------------------------


def test_the_evidenced_routes_carry_their_measured_tab():
    """Owner-confirmed `?tab=snapmagic`, corroborated by DigiKey's own indexed models URLs:

    * https://www.digikey.com/en/models/303553?tab=snapmagic
    * https://www.digikey.com/en/models/3906419?tab=ultralibrarian
    """

    assert _DIGIKEY_SNAPMAGIC_ROUTE.models_tab == "snapmagic"
    assert _DIGIKEY_ULTRALIBRARIAN_ROUTE.models_tab == "ultralibrarian"


@pytest.mark.parametrize(
    "route",
    [_DIGIKEY_TRACEPARTS_ROUTE, _DIGIKEY_MANUFACTURER_ROUTE, _DIGIKEY_CADENAS_ROUTE],
)
def test_an_unevidenced_route_gets_no_tab_even_though_its_key_would_spell_one(route):
    """The tab is DATA, not `evidence_provider_key.removeprefix("digikey-")`.

    Deriving it would silently invent `?tab=traceparts`, `?tab=manufacturer` and `?tab=cadenas`,
    none of which anyone has seen DigiKey serve. A wrong tab is worse than no tab: it sends the
    person to a surface that may not exist for the part, having promised it would not.
    """

    assert route.evidence_provider_key.startswith("digikey-")
    assert route.evidence_provider_key.removeprefix("digikey-")
    assert route.models_tab == ""


# --- building the link ------------------------------------------------------------------------


def test_the_deep_link_is_the_exact_published_shape():
    assert (
        digikey_models_url("6695662", tab="snapmagic")
        == "https://www.digikey.com/en/models/6695662?tab=snapmagic"
    )
    assert digikey_models_url("6695662") == "https://www.digikey.com/en/models/6695662"


@pytest.mark.parametrize(
    "models_id",
    ["", "abc", "../evil", "6695662/../evil", "6695662?tab=evil", "6695662#x", "0123", " 6695662"],
)
def test_a_models_id_that_is_not_a_models_id_is_never_interpolated(models_id):
    with pytest.raises(ValueError):
        digikey_models_url(models_id, tab="snapmagic")


@pytest.mark.parametrize(
    "tab",
    ["snap magic", "snapmagic&next=evil", "snapmagic#x", "../evil", "SNAPMAGIC", "x" * 64],
)
def test_a_tab_that_is_not_a_measured_tab_is_never_interpolated(tab):
    with pytest.raises(ValueError):
        digikey_models_url("6695662", tab=tab)


# --- the guided seam ---------------------------------------------------------------------------


class _Record:
    id = "tps2121ruxr-0001"
    mpn = _MPN
    manufacturer = _MANUFACTURER

    def capturable(self, tool_key: str) -> set[str]:
        return {"symbol", "footprint"} if tool_key == "kicad" else set()

    def assets_for(self, tool_key: str) -> dict:
        return {}


class _RecordingBrowser:
    """Records the URL the person is actually sent to, and answers with a final_url."""

    def __init__(self, final_url: str = ""):
        self.captured: list = []
        self.opened: list[str] = []
        self.options: list[dict] = []
        self._final_url = final_url

    def capture_user_downloads(self, url, broker, **kwargs):
        self.opened.append(url)
        self.options.append(kwargs)
        return UserCaptureResult(status="finished", files=(), final_url=self._final_url or url)


def _source(tmp_path: Path, store: DigiKeyModelsIds | None):
    return guided.GuidedCaptureSource(
        lambda *a, **k: None,
        vendor="digikey",
        download_root=tmp_path / "downloads",
        models_ids=store,
    )


def _run_route(source, browser, adapter):
    session = guided._Session(browser=browser, ctx_manager=None)
    return source._supply_user_driven_route(
        _Record(),
        session,
        adapter,
        _MANUFACTURER,
        _MPN,
        _SEARCH_URL,
        ["kicad"],
    )


def test_the_first_run_is_exactly_todays_search_and_learns_the_id(tmp_path):
    """THE FIRST-RUN CONTRACT. With nothing learned, the person's journey is unchanged."""

    store = _store(tmp_path)
    browser = _RecordingBrowser(
        final_url="https://www.digikey.com/en/models/6695662?tab=snapmagic"
    )
    source = _source(tmp_path, store)

    _run_route(source, browser, DigiKeySnapMagicRouteAdapter(DigiKeyUltraLibrarianAdapter()))

    assert browser.opened == [_SEARCH_URL]
    hud = browser.options[0]["hud"]
    assert hud.automated_step == "Listening for provider downloads."
    assert hud.human_action == (
        "Start this part's download with every required format shown here."
    )
    assert store.get(manufacturer=_MANUFACTURER, mpn=_MPN) == "6695662"


def test_a_learned_id_lands_the_person_on_this_routes_own_tab(tmp_path):
    """THE SECOND-RUN CONTRACT. The id was observed for THIS exact manufacturer and MPN.

    Provenance, not URL text, is what makes this safe to navigate on: it is stored under the
    part's manufacturer AND MPN, so a hit is bound to the requested part rather than merely
    spelling it. Identity for attachment still runs through the unchanged detail-URL gates.
    """

    store = _store(tmp_path)
    store.learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/6695662",
    )
    browser = _RecordingBrowser()
    source = _source(tmp_path, store)

    _run_route(
        source,
        browser,
        DigiKeySnapMagicRouteAdapter(DigiKeyUltraLibrarianAdapter()),
    )

    assert browser.opened == ["https://www.digikey.com/en/models/6695662?tab=snapmagic"]


def test_a_route_with_no_evidenced_tab_still_uses_todays_url(tmp_path):
    store = _store(tmp_path)
    store.learn(
        manufacturer=_MANUFACTURER,
        mpn=_MPN,
        final_url="https://www.digikey.com/en/models/6695662",
    )
    browser = _RecordingBrowser()
    source = _source(tmp_path, store)

    _run_route(source, browser, DigiKeyTracePartsRouteAdapter(DigiKeyUltraLibrarianAdapter()))

    assert browser.opened == [_SEARCH_URL]


def test_a_capture_with_no_models_store_behaves_exactly_as_before(tmp_path):
    browser = _RecordingBrowser(
        final_url="https://www.digikey.com/en/models/6695662?tab=snapmagic"
    )
    source = _source(tmp_path, None)

    _run_route(source, browser, DigiKeySnapMagicRouteAdapter(DigiKeyUltraLibrarianAdapter()))

    assert browser.opened == [_SEARCH_URL]


def test_a_search_final_url_teaches_the_guided_seam_nothing(tmp_path):
    store = _store(tmp_path)
    browser = _RecordingBrowser(final_url=_SEARCH_URL)
    source = _source(tmp_path, store)

    _run_route(source, browser, DigiKeySnapMagicRouteAdapter(DigiKeyUltraLibrarianAdapter()))

    assert store.get(manufacturer=_MANUFACTURER, mpn=_MPN) == ""


def test_a_stored_id_never_moves_the_person_off_digikeys_own_origin(tmp_path):
    """The deep link is rebuilt from the id and re-checked, never pasted from storage."""

    path = tmp_path / "DigiKey Models.json"
    path.write_text(
        json.dumps(
            {
                "parts": {
                    "texas instruments": {
                        "tps2121ruxr": {"models_id": "6695662@evil.test"}
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    browser = _RecordingBrowser()
    source = _source(tmp_path, DigiKeyModelsIds(path))

    _run_route(source, browser, DigiKeySnapMagicRouteAdapter(DigiKeyUltraLibrarianAdapter()))

    assert browser.opened == [_SEARCH_URL]
