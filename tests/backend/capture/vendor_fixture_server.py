"""A local stand-in for a CAD vendor, so the whole capture chain is testable with no network,
no vendor account, and no Windows.

It serves the REAL captured vendor markup (`tests/backend/host/fixtures/*.html`) and answers the
form's own POST with a REAL zip, sent as an attachment. So a test drives a real browser through
the real page structure and a real download actually lands on disk.

WHAT IS VERBATIM AND WHAT IS A STAND-IN - stated, because a fixture that quietly differs from the
thing it imitates is worse than no fixture:
  * VERBATIM: the vendor's markup - every id, class, label and form action, exactly as captured
    from the live signed-in page.
  * STAND-IN: the vendor's own JavaScript, which we did not capture and may not redistribute. On
    the real page that JS enables `#submit-export` once a format is chosen and posts the form.
    `_HARNESS_JS` below does only that, and is injected by THIS SERVER, never by the app. It is
    labelled in the served HTML so nobody mistakes it for vendor behaviour.
So the test proves OUR half end to end (drive -> select -> submit -> download -> classify) and
deliberately does not claim to prove the vendor's JS.
"""

from __future__ import annotations

import http.server
import io
import socketserver
import threading
import zipfile
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

FIXTURES = Path(__file__).resolve().parents[1] / "host" / "fixtures"
READABLE_STEP = Path(__file__).parent / "fixtures" / "readable_geometry.step"
ALTIUM_FIXTURES = Path(__file__).resolve().parents[1] / "altium" / "fixtures"

# Stands in for the vendor's own submit script (see the module docstring). Enables the disabled
# submit link once any export is selected, and posts the form when it is clicked.
_HARNESS_JS = """
<script data-stockroom-harness="stands in for the vendor's own submit JS; NOT vendor markup">
(function(){
  var form = document.getElementById('export-submission-form');
  var submit = document.getElementById('submit-export');
  if(!form || !submit) return;
  function sync(){
    var any = document.querySelectorAll('input[name=exports]:checked').length > 0;
    submit.classList.toggle('disabled', !any);
  }
  document.addEventListener('change', sync);
  sync();
  submit.addEventListener('click', function(e){
    e.preventDefault();
    if(submit.classList.contains('disabled')) return;
    form.submit();
  });
})();
</script>
"""


# A MINIMAL BUT VALID KiCad 6 symbol library. The first version of this fixture wrote the string
# "(kicad_symbol_lib)" and the real ingest pipeline rejected it with "no symbol found inside ...",
# which is correct behaviour and meant the end-to-end test could never attach anything. A fixture
# has to be valid enough for the REAL parser, or it tests the parser's error path by accident.
_SYMBOL_LIB = """(kicad_symbol_lib (version 20211014) (generator stockroom_test)
  (symbol "TPD6E05U06RVZR" (in_bom yes) (on_board yes)
    (property "Reference" "U" (id 0) (at 0 0 0))
    (property "Value" "TPD6E05U06RVZR" (id 1) (at 0 0 0))
    (property "Manufacturer" "Texas Instruments" (id 2) (at 0 0 0))
    (symbol "TPD6E05U06RVZR_0_1"
      (rectangle (start -5.08 5.08) (end 5.08 -5.08)
        (stroke (width 0.254) (type default)) (fill (type none)))
    )
    (symbol "TPD6E05U06RVZR_1_1"
      (pin input line (at -7.62 0 0) (length 2.54)
        (name "IO1" (effects (font (size 1.27 1.27))))
        (number "1" (effects (font (size 1.27 1.27)))))
    )
  )
)
"""

_FOOTPRINT = """(footprint "RVZ0014A" (version 20211014) (generator stockroom_test) (layer "F.Cu")
  (attr smd)
  (fp_text reference "REF**" (at 0 0) (layer "F.SilkS") (effects (font (size 1 1) (thickness 0.15))))
  (pad "1" smd rect (at -1 0) (size 0.5 0.3) (layers "F.Cu" "F.Paste" "F.Mask"))
)
"""

_NATIVE_SYMBOL_LIB = """(kicad_symbol_lib
  (version 20240101)
  (generator stockroom-test)
  (symbol "S1M"
    (property "Reference" "D" (at 0 0 0))
    (property "Value" "S1M" (at 0 0 0))
    (property "Footprint" "Test:D_SMA" (at 0 0 0))
    (property "Manufacturer" "ON Semiconductor" (at 0 0 0))
    (property "Manufacturer Part Number" "S1M" (at 0 0 0))
    (symbol "S1M_0_1"
      (pin passive line (at -5 0 0) (length 2.54)
        (name "K" (effects (font (size 1 1))))
        (number "1" (effects (font (size 1 1)))))
      (pin passive line (at 5 0 180) (length 2.54)
        (name "A" (effects (font (size 1 1))))
        (number "2" (effects (font (size 1 1))))))))
"""

_NATIVE_FOOTPRINT = """(footprint "D_SMA"
  (version 20240108)
  (generator stockroom-test)
  (layer "F.Cu")
  (pad "1" smd rect (at -2.14 0) (size 2.33 1.56) (layers "F.Cu"))
  (pad "2" smd rect (at 2.14 0) (size 2.33 1.56) (layers "F.Cu"))
  (model "D_SMA.step"
    (offset (xyz 0 0 0))
    (scale (xyz 1 1 1))
    (rotate (xyz 0 0 0))))
"""

# A P-CAD ASCII library shaped like the real one: ACCEL_ASCII header, one symbolDef (the schematic
# symbol) and one patternDef (the PCB footprint), so ONE file satisfies BOTH Altium requirements.
# This is what the captured legacy Ultra Librarian PCAD row delivers.
_LIA = """ACCEL_ASCII "TEST.LIA"
(asciiHeader (asciiVersion 3 0))
(library (libraryName "TPD6E05U06RVZR")
  (symbolDef "TPD6E05U06RVZR" (pin (pinNum 1)))
  (patternDef "RVZ0014A" (pad (padNum 1)))
  (compDef "TPD6E05U06RVZR")
)
"""


def _kicad_altium_zip() -> bytes:
    """A bundle shaped like the captured legacy PCAD export plus KiCad and STEP."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("TPD6E05U06RVZR.kicad_sym", _SYMBOL_LIB)
        zf.writestr("footprints.pretty/RVZ0014A.kicad_mod", _FOOTPRINT)
        zf.writestr("RVZ0014A.stp", READABLE_STEP.read_bytes())
        # What Ultra Librarian's legacy PCAD v15 choice delivers: one P-CAD ASCII library carrying
        # both sides. Current native Altium export is tested separately as .SchLib/.PcbLib.
        zf.writestr("AltiumV15/2026-07-27_20-52-11.lia", _LIA)
        zf.writestr("AltiumV15/ImportGuide.html", "<html></html>")
    return buffer.getvalue()


def _kicad_only_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("TPD6E05U06RVZR.kicad_sym", _SYMBOL_LIB)
        zf.writestr("footprints.pretty/RVZ0014A.kicad_mod", _FOOTPRINT)
        zf.writestr("RVZ0014A.stp", READABLE_STEP.read_bytes())
    return buffer.getvalue()


def _native_kicad_zip() -> bytes:
    """The KiCad sibling for the same S1M definition carried by the Altium fixtures."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("S1M.kicad_sym", _NATIVE_SYMBOL_LIB)
        zf.writestr("footprints.pretty/D_SMA.kicad_mod", _NATIVE_FOOTPRINT)
        zf.writestr("D_SMA.step", READABLE_STEP.read_bytes())
    return buffer.getvalue()


def _native_altium_zip() -> bytes:
    """A native UL sibling archive with real readable Altium libraries."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr(
            "Altium Designer (Native)/S1M.LibPkg",
            b"native package descriptor",
        )
        zf.writestr(
            "Altium Designer (Native)/S1M.SchLib",
            (ALTIUM_FIXTURES / "sample.SchLib").read_bytes(),
        )
        zf.writestr(
            "Altium Designer (Native)/S1M.PcbLib",
            (ALTIUM_FIXTURES / "sample.PcbLib").read_bytes(),
        )
    return buffer.getvalue()


_NATIVE_DOWNLOADS = {
    # The native UL page delivers sibling downloads in one export action. The KiCad archive must
    # itself contain the exact symbol, footprint, and STEP candidate because production inspects
    # each sibling atomically before binding the complete sibling set into one evidence manifest.
    "/downloads/native-kicad.zip": ("native-kicad.zip", _native_kicad_zip()),
    "/downloads/native-altium.zip": ("native-altium.zip", _native_altium_zip()),
    "/downloads/native-step.step": (
        "native-step.step",
        READABLE_STEP.read_bytes(),
    ),
}


class _Handler(http.server.BaseHTTPRequestHandler):
    # set by serve_fixture_vendor
    fixture_name = "ul-export-panel.html"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's interface
        if self.path in _NATIVE_DOWNLOADS:
            filename, body = _NATIVE_DOWNLOADS[self.path]
            self._send(body, "application/octet-stream", attachment=filename)
            return
        html = (FIXTURES / self.fixture_name).read_text(encoding="utf-8")
        body = (html + _HARNESS_JS).encode("utf-8")
        self._send(body, "text/html; charset=utf-8")

    def do_POST(self):  # noqa: N802
        """The vendor's export endpoint. Answers with whichever formats were actually requested,
        so a test can tell 'both formats were selected' from 'only one was'."""
        length = int(self.headers.get("Content-Length") or 0)
        payload = self.rfile.read(length).decode("utf-8", "replace") if length else ""
        # `2` is #AltiumPCADV15's value on the real panel - the PCAD row, the one that yields a
        # .lia. `0` is the script row, which ships no libraries and must NOT count as Altium.
        wants_altium = "AltiumPCAD" in payload or "exports=2" in payload
        blob = _kicad_altium_zip() if wants_altium else _kicad_only_zip()
        self._send(blob, "application/octet-stream", attachment="TPD6E05U06RVZR.zip")

    def _send(self, body: bytes, ctype: str, attachment: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the test output readable
        pass


class _Server(socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve_fixture_vendor(fixture_name: str = "ul-export-panel.html"):
    """Start the stand-in vendor on an ephemeral port. Returns (base_url, shutdown)."""
    handler = type("_Bound", (_Handler,), {"fixture_name": fixture_name})
    server = _Server(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    def shutdown() -> None:
        server.shutdown()
        server.server_close()

    return f"http://127.0.0.1:{server.server_address[1]}", shutdown


def route_fixture_vendor(
    page,
    fixture_url: str,
    *,
    manufacturer: str = "Texas Instruments",
    mpn: str = "TPD6E05U06RVZR",
) -> str:
    """Serve a local fixture at an official-looking UL URL without touching the live service."""

    def proxy(route) -> None:
        browser_request = route.request
        parsed = urlsplit(browser_request.url)
        target = f"{fixture_url}{parsed.path}"
        if parsed.query:
            target += f"?{parsed.query}"
        payload = browser_request.post_data_buffer
        request = Request(
            target,
            data=payload,
            method=browser_request.method,
        )
        with urlopen(request, timeout=5) as response:  # noqa: S310 - loopback test fixture only
            body = response.read()
            headers = dict(response.headers.items())
            if response.headers.get_content_type() == "text/html":
                html = body.decode("utf-8")
                html = html.replace('"/downloads/', f'"{fixture_url}/downloads/')
                html = html.replace('action="/Export/', f'action="{fixture_url}/Export/')
                body = html.encode("utf-8")
                headers.pop("Content-Length", None)
            route.fulfill(
                status=response.status,
                headers=headers,
                body=body,
            )

    page.route("https://app.ultralibrarian.com/**", proxy)
    return (
        "https://app.ultralibrarian.com/details/fixture/"
        f"{quote(manufacturer, safe='')}/{quote(mpn, safe='')}?open=exports"
    )
