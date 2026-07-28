"""Fail-closed provider navigation and selection behavior."""

from __future__ import annotations

from stockroom.capture.vendors import (
    SnapMagicAdapter,
    UltraLibrarianAdapter,
    _challenge_issue,
    _clear_export_selections,
    _exact_result_href,
    _export_selectors,
    _href_demonstrates_mpn,
    _requested_mpn,
    _snapmagic_account_issue,
)


class _ResultNode:
    def __init__(self, href: str, text: str = "") -> None:
        self.href = href
        self.text = text

    def get_attribute(self, name: str):
        return self.href if name == "href" else None

    def inner_text(self):
        return self.text


class _Results:
    def __init__(self, *nodes: _ResultNode) -> None:
        self.nodes = list(nodes)

    def count(self):
        return len(self.nodes)

    def nth(self, index: int):
        return self.nodes[index]


def test_requested_mpn_is_recovered_without_losing_identity_punctuation():
    assert (
        _requested_mpn(
            "https://app.ultralibrarian.com/search?queryText=MCP4728-E%2FUN",
            ("queryText",),
        )
        == "MCP4728-E/UN"
    )
    assert (
        _requested_mpn("https://www.snapeda.com/search/?q=MAX6817EUT%2BT", ("q",)) == "MAX6817EUT+T"
    )


def test_result_navigation_requires_a_whole_exact_mpn_component():
    assert _href_demonstrates_mpn("/parts/analog-devices/MAX6817EUT%2BT/view-part/", "MAX6817EUT+T")
    assert not _href_demonstrates_mpn("/parts/analog-devices/ABC-1/view-part/", "ABC")
    assert not _href_demonstrates_mpn("/details/id/vendor/MCP4728-E/UN", "MCP4728-E/UN")


def test_exact_result_selection_rejects_near_and_ambiguous_matches():
    href, error = _exact_result_href(
        _Results(
            _ResultNode("/parts/acme/ABC-1/view-part/", "ABC-1"),
            _ResultNode("/parts/acme/ABC/view-part/", "ABC"),
        ),
        "ABC",
    )
    assert href == "/parts/acme/ABC/view-part/"
    assert error == ""

    href, error = _exact_result_href(
        _Results(
            _ResultNode("/parts/acme/ABC/view-part/", "ABC"),
            _ResultNode("/parts/other/ABC/view-part/", "ABC"),
        ),
        "ABC",
    )
    assert href == ""
    assert "multiple exact links" in error

    href, error = _exact_result_href(
        _Results(_ResultNode("/parts/acme/ABC-1/view-part/", "ABC-1")), "ABC"
    )
    assert href == ""
    assert "no exact result" in error


class _Checkbox:
    def __init__(self, box_id: str, checked: bool) -> None:
        self.box_id = box_id
        self.checked = checked

    @property
    def first(self):
        return self

    def count(self):
        return 1

    def nth(self, index: int):
        assert index == 0
        return self

    def get_attribute(self, name: str):
        return self.box_id if name == "id" else None

    def is_checked(self):
        return self.checked

    def uncheck(self, **_kwargs):
        self.checked = False


class _CheckboxCollection:
    def __init__(self, nodes: list[_Checkbox]) -> None:
        self.nodes = list(nodes)

    def count(self):
        return len(self.nodes)

    def nth(self, index: int):
        return self.nodes[index]


class _ExportPage:
    def __init__(self, *boxes: _Checkbox) -> None:
        self.boxes = {box.box_id: box for box in boxes}

    def locator(self, selector: str):
        if selector == "input[name=exports]:checked":
            return _CheckboxCollection([box for box in self.boxes.values() if box.checked])
        prefix = 'input[name="exports"][id="'
        if selector.startswith(prefix) and selector.endswith('"]'):
            box_id = selector[len(prefix) : -2].replace('\\"', '"').replace("\\\\", "\\")
            if box_id in self.boxes:
                return self.boxes[box_id]
        return _CheckboxCollection([])

    def evaluate(self, *_args):
        raise AssertionError("native uncheck should have verified")


def test_ultra_clears_persisted_obsolete_export_versions_before_selecting():
    old_kicad = _Checkbox("KiCAD", True)
    old_altium = _Checkbox("AltiumPCADv14", True)
    wanted = _Checkbox("KiCADv6", False)
    page = _ExportPage(old_kicad, old_altium, wanted)

    assert _clear_export_selections(page) is True
    assert old_kicad.checked is False
    assert old_altium.checked is False
    assert wanted.checked is False


def test_ultra_declares_current_live_model_id_and_retains_measured_legacy_fixture_alias():
    adapter = UltraLibrarianAdapter()
    assert adapter.capability.version_pins["model"] == "ThreeDModel"
    assert _export_selectors("model", "ThreeDModel") == (
        "#ThreeDModel",
        "#MfrThreeDModel",
    )


class _PageText:
    url = "https://www.snapeda.com/parts/ABC/view-part/"

    def __init__(self, body: str = "", title: str = "", frames: tuple[str, ...] = ()) -> None:
        self.body = body
        self.page_title = title
        self.frames = frames

    def title(self):
        return self.page_title

    def inner_text(self, selector: str):
        assert selector == "body"
        return self.body

    def locator(self, selector: str):
        assert selector == "iframe"
        return _Frames(self.frames)


class _Frame:
    def __init__(self, src: str) -> None:
        self.src = src

    def get_attribute(self, name: str):
        return self.src if name == "src" else None


class _Frames:
    def __init__(self, sources: tuple[str, ...]) -> None:
        self.sources = sources

    def count(self):
        return len(self.sources)

    def nth(self, index: int):
        return _Frame(self.sources[index])


def test_challenge_and_unverified_account_states_are_reported_distinctly():
    issue = _challenge_issue(
        _PageText(frames=("https://challenges.cloudflare.com/cf-chl-widget",)), "SnapMagic"
    )
    assert "confirm you are human" in issue
    assert "provider-specific browser profile" in issue

    issue = _snapmagic_account_issue(_PageText("Verify your email to download CAD files"))
    assert "email to be verified" in issue
    assert _snapmagic_account_issue(_PageText("Email status: Unverified")) == ""
    assert _snapmagic_account_issue(_PageText("Download verified CAD models")) == ""


def test_snapmagic_pins_formats_explicitly_when_account_preference_is_none():
    pins = SnapMagicAdapter.capability.version_pins
    assert pins == {
        "kicad": "kicad_modv6",
        "altium": "altium_native",
        "model": "step_model",
    }


class _FormatButton:
    @property
    def first(self):
        return self

    def count(self):
        return 1

    def get_attribute(self, name: str):
        if name == "href":
            return "/account/signup/?next=/parts/ABC/view-part/"
        return None

    def click(self):
        raise AssertionError("a signup redirect must never be clicked as though it were a download")


class _SignedOutFormatPage:
    url = "https://www.snapeda.com/parts/acme/ABC/view-part/"

    def locator(self, selector: str):
        if selector == "[data-format]" or selector == '[data-format="altium_native"]':
            return _FormatButton()
        return _CheckboxCollection([])


def test_snapmagic_signup_redirect_is_not_reported_as_a_submitted_download():
    report = SnapMagicAdapter().drive(_SignedOutFormatPage(), ["altium"])
    assert report.submitted is False
    assert report.selected == []
    assert report.missed == ["altium"]
    assert "signed-in, verified account" in report.message


def test_snapmagic_done_page_without_saved_bytes_is_a_provider_wide_download_gate():
    issue = SnapMagicAdapter().download_gate(_PageText("Done! You just downloaded S1M"))
    assert "browser received no file" in issue
    assert "multiple-file permission" in issue
