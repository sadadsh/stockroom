"""The DigiKey models id the PERSON's own navigation revealed, and the deep link it buys.

DigiKey's product page is the one surface that gathers Ultra Librarian, SnapMagic and TraceParts
in one place, which is why the owner works from it. Stockroom, though, opened a keyword SEARCH for
every part, so every capture repeated the same search, the same navigation and the same tab click
that the person had already performed for that exact part.

DigiKey publishes a per-part models page with a provider tab,
``https://www.digikey.com/en/models/<id>?tab=<provider>``. The id is opaque and no sanctioned
lookup for it exists, so it can only be learned - and it already is, incidentally, every time a
person finishes a user-driven capture: ``UserCaptureResult.final_url`` is the URL of the page they
chose to be on. Reading a URL Stockroom was handed is not scraping and reveals nothing about the
page; this module never reads page content, and it never operates a DigiKey control.

**This module resolves URLs and remembers one opaque id per part. Nothing else.** The deep link is
strictly an optimisation for a part the person has already visited, so a first run behaves exactly
as it did before this file existed.

Two rules keep a learned id from ever becoming a liability:

* **Fail closed on the way in.** Only ``https://www.digikey.com/en/models/<digits>`` teaches
  anything. A look-alike host, an embedded credential, a traversal segment or an encoded ``?``
  teaches nothing and is never written.
* **Rebuild, never paste.** A stored id is re-validated and re-interpolated into the canonical
  shape at every use, so a tampered store file cannot move the person off DigiKey's own origin.

The id is bound to manufacturer AND MPN. Two manufacturers ship the same MPN string, and a models
page belongs to one of them; keying on the MPN alone would deep-link one manufacturer's part to
another's models page, which is the mistake the exact-identity gate exists to prevent everywhere
else in capture.
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import urlsplit

from stockroom.capture.identity import provider_url_allowed
from stockroom.enrich.cache import _retry_transient

# DigiKey's ids are positive integers with no leading zero, and the path carries the id and
# nothing else. Anchored, applied to the RAW (still percent-encoded) path, so `%2e%2e%2f` and
# `%3Ftab%3D` fail here rather than being decoded into something that passes.
_MODELS_PATH = re.compile(r"/en/models/([1-9][0-9]{0,11})\Z")
_MODELS_ID = re.compile(r"[1-9][0-9]{0,11}\Z")
# A provider tab is a lowercase library name. Deliberately narrow: every accepted value is a
# constant declared on a route, so anything needing escaping is a bug, not input to encode.
_MODELS_TAB = re.compile(r"[a-z][a-z0-9-]{0,31}\Z")

_MODELS_BASE = "https://www.digikey.com/en/models/"


def digikey_models_id(url: str) -> str:
    """The models id in a DigiKey models URL, or ``""`` for anything else.

    Fails closed on every axis at once: origin (via the shared provider-origin check, which also
    rejects credentials in the authority and any scheme but HTTPS), port, and an exact path shape
    matched before any decoding.
    """

    if not isinstance(url, str) or not url:
        return ""
    if not provider_url_allowed("digikey", url):
        return ""
    try:
        parsed = urlsplit(url)
    except ValueError:  # noqa: PERF203 - a malformed authority establishes no identity
        return ""
    if parsed.port is not None:
        return ""
    match = _MODELS_PATH.fullmatch(parsed.path)
    return match.group(1) if match else ""


def digikey_models_url(models_id: str, *, tab: str = "") -> str:
    """The canonical models URL for one id, optionally on one provider tab.

    Raises rather than degrading: every caller holds either a validated id or nothing, so a value
    that fails here is a defect to surface, never a URL to sanitize and navigate to anyway.
    """

    if not isinstance(models_id, str) or not _MODELS_ID.fullmatch(models_id):
        raise ValueError("a DigiKey models id must be its published positive integer form")
    if tab and (not isinstance(tab, str) or not _MODELS_TAB.fullmatch(tab)):
        raise ValueError("a DigiKey models tab must be a measured lowercase provider name")
    return f"{_MODELS_BASE}{models_id}?tab={tab}" if tab else f"{_MODELS_BASE}{models_id}"


def _identity_key(value: str) -> str:
    """Fold presentation, not identity: case and surrounding whitespace only."""

    if not isinstance(value, str):
        return ""
    return unicodedata.normalize("NFKC", value).strip().casefold()


class DigiKeyModelsIds:
    """A per-machine record of which DigiKey models page each part turned out to live on.

    Derived, re-learnable navigation state, so it lives beside the other machine-local capture
    state rather than in the Git-backed record: a models id is DigiKey's private catalogue
    numbering, it can change under us, and stamping it on a committed record would put vendor
    routing churn into the library's history for no gain.

    Advisory throughout. Every filesystem failure degrades to "nothing learned", which costs one
    keyword search - exactly today's behaviour - and never raises into a capture run.
    """

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._parts: dict[str, dict[str, dict]] = {}
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return  # missing, unreadable or corrupt -> nothing learned, never raises
        if not isinstance(raw, dict) or not isinstance(raw.get("parts"), dict):
            return
        for manufacturer, by_mpn in raw["parts"].items():
            if not isinstance(manufacturer, str) or not isinstance(by_mpn, dict):
                continue
            entries = {
                mpn: entry
                for mpn, entry in by_mpn.items()
                if isinstance(mpn, str) and isinstance(entry, dict)
            }
            if entries:
                self._parts[manufacturer] = entries

    def get(self, *, manufacturer: str, mpn: str) -> str:
        """The learned models id for one exact part, or ``""``.

        Re-validated on the way OUT as well as in. The file is machine-local and editable, and a
        value that reaches a URL must be provably an id no matter how it got onto disk.
        """

        manufacturer_key = _identity_key(manufacturer)
        mpn_key = _identity_key(mpn)
        if not manufacturer_key or not mpn_key:
            return ""
        entry = self._parts.get(manufacturer_key, {}).get(mpn_key)
        if not isinstance(entry, dict):
            return ""
        models_id = entry.get("models_id")
        if not isinstance(models_id, str) or not _MODELS_ID.fullmatch(models_id):
            return ""
        return models_id

    def learn(self, *, manufacturer: str, mpn: str, final_url: str) -> str:
        """Remember the id if ``final_url`` is a DigiKey models page; return what was kept.

        The id and nothing else. A final URL can carry a session token or a tracking parameter,
        and page content is not ours to retain at all.
        """

        manufacturer_key = _identity_key(manufacturer)
        mpn_key = _identity_key(mpn)
        models_id = digikey_models_id(final_url)
        if not manufacturer_key or not mpn_key or not models_id:
            return ""
        if self.get(manufacturer=manufacturer, mpn=mpn) == models_id:
            return models_id
        self._parts.setdefault(manufacturer_key, {})[mpn_key] = {"models_id": models_id}
        self._save()
        return models_id

    def _save(self) -> None:
        # A unique temp file plus a retried os.replace, the same shape `RescanState` uses: two
        # capture runs can be learning at once, and on Windows a peer holding the destination open
        # raises a transient sharing violation. Every filesystem step is inside the one degrading
        # try, so a persistent failure leaves the prior file intact and simply learns nothing.
        body = json.dumps({"parts": self._parts}, indent=2, sort_keys=True)
        tmp: Path | None = None
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(
                dir=str(self._path.parent), prefix=self._path.name + ".", suffix=".tmp"
            )
            tmp = Path(tmp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(body)
            _retry_transient(lambda: os.replace(tmp, str(self._path)))
        except OSError:
            if tmp is not None:
                try:
                    tmp.unlink()
                except OSError:
                    pass  # best-effort cleanup; a peer or the OS may already have removed it


def default_digikey_models_ids() -> DigiKeyModelsIds:
    """The machine-local store, beside the browser profiles and the provider-start ledger."""

    from stockroom.capture.runner import capture_state_root

    return DigiKeyModelsIds(capture_state_root() / "DigiKey Models" / "Models.json")


__all__ = [
    "DigiKeyModelsIds",
    "default_digikey_models_ids",
    "digikey_models_id",
    "digikey_models_url",
]
