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

FIXTURES = Path(__file__).resolve().parents[1] / "host" / "fixtures"

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
    (symbol "TPD6E05U06RVZR_0_1"
      (rectangle (start -5.08 5.08) (end 5.08 -5.08)
        (stroke (width 0.254) (type default)) (fill (type none)))
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

# A real STEP header, so a classifier or reader that sniffs content sees a plausible model.
_STEP = "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"

# A P-CAD ASCII library shaped like the real one: ACCEL_ASCII header, one symbolDef (the schematic
# symbol) and one patternDef (the PCB footprint), so ONE file satisfies BOTH Altium requirements.
# This is what Ultra Librarian's PCAD row actually delivers - see UltraLibrarianAdapter.
_LIA = """ACCEL_ASCII "TEST.LIA"
(asciiHeader (asciiVersion 3 0))
(library (libraryName "TPD6E05U06RVZR")
  (symbolDef "TPD6E05U06RVZR" (pin (pinNum 1)))
  (patternDef "RVZ0014A" (pad (padNum 1)))
  (compDef "TPD6E05U06RVZR")
)
"""


def _kicad_altium_zip() -> bytes:
    """A bundle shaped like a real two-format export: KiCad symbol + footprint + STEP, and the
    Altium pair. Classified by `capture.classify.classify_asset` exactly as a vendor's would be."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("TPD6E05U06RVZR.kicad_sym", _SYMBOL_LIB)
        zf.writestr("footprints.pretty/RVZ0014A.kicad_mod", _FOOTPRINT)
        zf.writestr("RVZ0014A.stp", _STEP)
        # What Ultra Librarian ACTUALLY delivers for Altium: a P-CAD ASCII library nested under
        # AltiumV15/, carrying the symbol AND the footprint in one file. NOT .SchLib/.PcbLib - the
        # fixture claimed those for a while, and no vendor this app drives produces them that way,
        # so the fixture was testing a shape that does not exist.
        zf.writestr("AltiumV15/2026-07-27_20-52-11.lia", _LIA)
        zf.writestr("AltiumV15/ImportGuide.html", "<html></html>")
    return buffer.getvalue()


def _kicad_only_zip() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        zf.writestr("TPD6E05U06RVZR.kicad_sym", _SYMBOL_LIB)
        zf.writestr("footprints.pretty/RVZ0014A.kicad_mod", _FOOTPRINT)
        zf.writestr("RVZ0014A.stp", _STEP)
    return buffer.getvalue()


class _Handler(http.server.BaseHTTPRequestHandler):
    # set by serve_fixture_vendor
    fixture_name = "ul-export-panel.html"

    def do_GET(self):  # noqa: N802 - BaseHTTPRequestHandler's interface
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
