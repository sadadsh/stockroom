"""The provider browser: one deterministic way to open a page and save its download.

The retired implementation drove provider pages through the pywebview app host, private
WebView2 download hooks, injected vendor JavaScript, and a global Downloads-folder watcher.
That path was Windows-only, difficult to verify end to end, and could not bind a downloaded
file reliably to the task that requested it.

Playwright has a public download API (``expect_download`` / ``save_as``), real waiting
primitives, and portable test support. Provider logic therefore lives here as ordinary
Python behind the API-owned capture workflow. The Stockroom app shell remains
pywebview/WebView2 on Windows; it no longer owns provider acquisition.

A NOTE ON THE PERSISTENT PROFILE, which is not a free choice
Vendor logins must survive between parts, which means a persistent user-data dir. Playwright and
Chromium permit only one owner of a user-data dir at a time. Production therefore gives every
provider its own profile and holds an explicit inter-process profile lock for the whole browser
session. Two workers can drive different providers, but two workers can never corrupt the same
provider's cookies or browser state.
"""

from __future__ import annotations

import json
import os
import re
import secrets
import shutil
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from stockroom.capture.classify import classify_asset
from stockroom.capture.download_broker import (
    DownloadBroker,
    DownloadBrokerError,
    DownloadReceipt,
)
from stockroom.capture.requirements import Requirement
from stockroom.capture.trace import file_note, trace, trace_debug, trace_warning, url_note


class CaptureBrowserError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


class ProviderPageTerminalError(CaptureBrowserError):
    """The provider rendered a known terminal page instead of its CAD controls."""


UserCaptureStatus = Literal["completed", "try_another", "cancelled", "timed_out"]
ProviderHudAction = Literal["finish", "try_another", "cancel"]
_PROVIDER_HUD_ACTIONS = frozenset({"finish", "try_another", "cancel"})
_PROVIDER_FORMAT_REQUIREMENTS = {
    "kicad": frozenset({Requirement.KICAD_SYMBOL, Requirement.KICAD_FOOTPRINT}),
    "kicad_symbol": frozenset({Requirement.KICAD_SYMBOL}),
    "kicad_footprint": frozenset({Requirement.KICAD_FOOTPRINT}),
    "model": frozenset({Requirement.KICAD_MODEL}),
    "altium": frozenset({Requirement.ALTIUM_SYMBOL, Requirement.ALTIUM_FOOTPRINT}),
    "altium_symbol": frozenset({Requirement.ALTIUM_SYMBOL}),
    "altium_footprint": frozenset({Requirement.ALTIUM_FOOTPRINT}),
}
_DEFAULT_PROVIDER_FORMATS = (
    "kicad_symbol",
    "kicad_footprint",
    "model",
    "altium_symbol",
    "altium_footprint",
)


@dataclass(frozen=True, slots=True)
class ProviderControlHint:
    """WHERE one provider control sits, so Stockroom can outline it. Position, never content.

    A hint is Stockroom-owned data, declared next to the adapter that measured it:

      * ``label`` is Stockroom's own short caption drawn beside the outline. It is never read
        from the page, so an outline can never repeat provider copy back to the person.
      * ``selectors`` are measured CSS selectors, most current first. The HUD tries them in order
        and uses the first that matches EXACTLY ONE visible element; anything else draws nothing.
        A tuple exists only for a measured backwards-compatible alias (Ultra Librarian's
        ``#MfrThreeDModel``), never to widen a guess.
      * ``source`` names where the selector was measured in this repo, so a reviewer can check the
        claim. It is deliberately NOT sent into the page.
    """

    label: str
    selectors: tuple[str, ...]
    source: str

    def __post_init__(self) -> None:
        for value, field_name in ((self.label, "label"), (self.source, "source")):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"control hint {field_name} must be exact non-empty text")
        selectors = self.selectors
        if (
            type(selectors) is not tuple
            or not selectors
            or any(
                type(selector) is not str or not selector or selector != selector.strip()
                for selector in selectors
            )
        ):
            raise ValueError("control hint selectors must be a non-empty tuple of exact selectors")


@dataclass(frozen=True, slots=True)
class ProviderHudSpec:
    """Exact Stockroom-owned text shown over one person-controlled provider page."""

    provider_label: str
    author_route: str
    manufacturer: str
    mpn: str
    required_file_labels: tuple[str, ...]
    # Stable machine keys corresponding one-for-one with ``required_file_labels``. The browser
    # counts download receipts, but completion is determined from the contents of those receipts:
    # one provider archive can carry every format, while several unrelated downloads can carry
    # none. Keeping both answers prevents the HUD from pretending ZIP count is CAD completeness.
    required_formats: tuple[str, ...] = ()
    automated_step: str = "Listening for provider downloads."
    human_action: str = "Start this part's download with every required format shown here."
    # Leading context for the checklist: the provider's own `capability.instruction`. Left empty
    # here, it is resolved from the vendor registry by exact provider label.
    provider_instruction: str = ""
    # Where this provider's controls were measured to sit. Empty here, it is resolved the same way.
    control_hints: tuple[ProviderControlHint, ...] = ()

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_label, "provider_label"),
            (self.author_route, "author_route"),
            (self.manufacturer, "manufacturer"),
            (self.mpn, "mpn"),
            (self.automated_step, "automated_step"),
            (self.human_action, "human_action"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{label} must be exact non-empty text")
        labels = self.required_file_labels
        if (
            type(labels) is not tuple
            or not labels
            or any(
                type(label) is not str or not label or label != label.strip() for label in labels
            )
        ):
            raise ValueError("required_file_labels must be a non-empty tuple of exact labels")
        formats = self.required_formats or _DEFAULT_PROVIDER_FORMATS[: len(labels)]
        if (
            type(formats) is not tuple
            or len(formats) != len(labels)
            or len(set(formats)) != len(formats)
            or any(value not in _PROVIDER_FORMAT_REQUIREMENTS for value in formats)
        ):
            raise ValueError(
                "required_formats must uniquely identify every required_file_labels entry"
            )
        object.__setattr__(self, "required_formats", formats)
        instruction = self.provider_instruction
        if type(instruction) is not str or instruction != instruction.strip():
            raise ValueError("provider_instruction must be exact text")
        hints = self.control_hints
        if type(hints) is not tuple or any(type(hint) is not ProviderControlHint for hint in hints):
            raise ValueError("control_hints must be a tuple of ProviderControlHint")


@dataclass(frozen=True)
class CapturedFile:
    """One file the vendor actually delivered, already on disk at `path`.

    `suggested_name` is the vendor's own filename, kept because it is evidence (and because the
    classifier's zip-by-content path exists precisely for downloads that arrive without one).
    """

    path: Path
    suggested_name: str
    url: str


@dataclass(frozen=True, slots=True)
class UserCaptureResult:
    """Files Stockroom intercepted while the person controlled the provider page."""

    status: UserCaptureStatus
    files: tuple[DownloadReceipt, ...]
    final_url: str


def _completed_provider_formats(
    receipts: tuple[DownloadReceipt, ...],
    required_formats: tuple[str, ...],
) -> tuple[str, ...]:
    """Return CAD format groups actually present in the task-bound downloaded bytes.

    Receipt count is intentionally not used as a proxy. Providers variously deliver one archive
    containing every asset, two complementary archives, or a download that contains no CAD at
    all. The existing content classifier safely inspects loose files and nested vendor ZIPs, so
    the HUD and its auto-finish decision can speak the same format truth as downstream ingest.
    """

    requirements: set[Requirement] = set()
    for receipt in receipts:
        requirements.update(classify_asset(Path(receipt.path)).requirements)
    return tuple(
        format_key
        for format_key in required_formats
        if _PROVIDER_FORMAT_REQUIREMENTS[format_key] <= requirements
    )


@dataclass(frozen=True)
class _BrowserCandidate:
    label: str
    browser_type: str
    channel: str | None = None


_PROVIDER_KEY = re.compile(r"[a-z0-9]+(?:[-_][a-z0-9]+)*", re.ASCII)
_WINDOWS_INVALID_FILENAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_WINDOWS_RESERVED_NAMES = {
    "aux",
    "clock$",
    "con",
    "nul",
    "prn",
    *(f"com{number}" for number in range(1, 10)),
    *(f"lpt{number}" for number in range(1, 10)),
}
_PROCESS_LOCK_GUARD = threading.Lock()
_PROCESS_LOCKS: set[str] = set()
_USER_CAPTURE_WINDOW_LOCK = threading.Lock()
_CHROMIUM_PREFERENCES = Path("Default") / "Preferences"
_BROWSER_LAUNCH_TIMEOUT_MS = 20_000
_DISABLE_WEBRTC_INIT_SCRIPT = """
(() => {
  for (const key of ["RTCPeerConnection", "webkitRTCPeerConnection"]) {
    try {
      Object.defineProperty(globalThis, key, {
        value: undefined,
        writable: false,
        configurable: false,
      });
    } catch {}
  }
})();
"""


@contextmanager
def exclusive_user_capture_window():
    """At most ONE person-driven capture window in this process, whatever transport opened it.

    Public because the de-automated transport in ``capture/handoff.py`` must hold the SAME lock,
    not one of its own. Two concurrent person-driven captures watching one Downloads directory is
    precisely how the retired implementation attributed a file to the wrong task; one person can
    only work one provider page at a time, so serializing them removes the ambiguity at the source
    rather than trying to resolve it afterwards.
    """

    if not _USER_CAPTURE_WINDOW_LOCK.acquire(blocking=False):
        raise CaptureBrowserError(
            "another assisted capture window is already active; Stockroom will retry this "
            "task after that window finishes"
        )
    try:
        yield
    finally:
        _USER_CAPTURE_WINDOW_LOCK.release()


_exclusive_user_capture_window = exclusive_user_capture_window


# Stockroom-owned structural markers for a bot-detection or authentication control. They mirror
# `vendors._CHALLENGE_MARKERS` (the same measured Turnstile/reCAPTCHA/hCaptcha surfaces) and the
# Camoufox note below recording SnapEDA's sole `cf-turnstile-response` input. The HUD checks them
# for PRESENCE AND VISIBILITY ONLY, and only ever to STOP drawing: no value, text, or attribute of
# a matched element is read, and nothing about the match is reported back to Python. A page that
# shows one of these belongs entirely to the person and to the existing security handoff.
_HUD_SECURITY_CONTROL_MARKERS = (
    'iframe[src*="challenges.cloudflare.com"]',
    'iframe[src*="google.com/recaptcha"]',
    'iframe[src*="recaptcha.net"]',
    'iframe[src*="hcaptcha.com"]',
    ".cf-turnstile",
    "#cf-turnstile-response",
    ".g-recaptcha",
    "#g-recaptcha",
    ".h-captcha",
    "input[type=password]",
)


_EMBEDDED_PROVIDER_NAVIGATION_BOOTSTRAP = r"""
() => {
  if (globalThis !== globalThis.top) return;
  const marker = Symbol.for("stockroom.provider-contained-navigation.v1");
  if (globalThis[marker]) return;
  globalThis[marker] = true;

  // pywebview hands target=_blank links to the Windows default browser before Playwright can
  // observe a popup. Contain only the exact HTTPS/HTTP link the person clicked. Downloads keep
  // their native path, modified clicks keep their normal browser meaning, and unsafe or
  // credential-bearing targets are left for the native host's fail-closed policy.
  globalThis.addEventListener("click", (event) => {
    if (
      event.defaultPrevented || event.button !== 0 || event.ctrlKey || event.metaKey ||
      event.shiftKey || event.altKey
    ) return;
    const anchor = event.composedPath().find(
      (node) => node instanceof HTMLAnchorElement,
    );
    if (!anchor || anchor.target.toLowerCase() !== "_blank" || anchor.hasAttribute("download")) {
      return;
    }
    let destination;
    try {
      destination = new URL(anchor.href, globalThis.location.href);
    } catch {
      return;
    }
    if (
      !["http:", "https:"].includes(destination.protocol) ||
      destination.username || destination.password
    ) return;
    event.preventDefault();
    event.stopImmediatePropagation();
    globalThis.location.assign(destination.href);
  }, true);
}
"""


_PROVIDER_HUD_BOOTSTRAP = r"""
async (payload) => {
  if (!payload || globalThis !== globalThis.top || globalThis[payload.namespace]) {
    return;
  }

  // This payload is registered once and replayed on every provider navigation, so the count it
  // carries is only ever the one that was true at bind time. Read the live one back from Stockroom
  // the way the security handoff does, and keep the snapshot when that read cannot be served.
  let downloadCount = payload.downloadCount;
  let completedFormats = Array.isArray(payload.completedFormats) ? payload.completedFormats : [];
  // Fail SAFE, not open: an unreadable state leaves the hold on, so a remount during a security
  // handoff never draws an outline before Stockroom's next push arrives.
  let securityHold = true;
  try {
    const state = await globalThis[payload.stateBinding](payload.stateToken);
    if (state && Number.isInteger(state.downloadCount)) downloadCount = state.downloadCount;
    if (state && Array.isArray(state.completedFormats)) completedFormats = state.completedFormats;
    if (state && typeof state.securityHold === "boolean") securityHold = state.securityHold;
  } catch {}

  const mount = () => {
    if (!document.documentElement || globalThis[payload.namespace]) {
      return;
    }

    const make = (tag, className = "", text = "") => {
      const node = document.createElement(tag);
      if (className) node.className = className;
      if (text) node.textContent = text;
      return node;
    };

    const host = document.createElement("aside");
    host.setAttribute("popover", "manual");
    host.setAttribute("aria-label", "Stockroom capture assistant");
    const shadow = host.attachShadow({ mode: "closed" });

    const style = document.createElement("style");
    style.textContent = `
      :host {
        all: initial;
        position: fixed;
        inset: 56px 12px auto auto;
        z-index: 2147483647;
        display: block;
        width: min(368px, calc(100vw - 24px));
        margin: 0;
        padding: 0;
        border: 0;
        color-scheme: light dark;
        --sr-canvas: #e9eaee;
        --sr-surface: #ffffff;
        --sr-raise: #f4f4f5;
        --sr-field: rgb(17 18 20 / 5%);
        --sr-band: #e2e4e9;
        --sr-line: rgb(17 18 20 / 10%);
        --sr-line-strong: rgb(17 18 20 / 18%);
        --sr-t1: #17181b;
        --sr-t2: rgb(23 24 27 / 68%);
        --sr-t3: rgb(23 24 27 / 48%);
        --sr-accent: #1b1b1e;
        --sr-accent-on: #f5f5f5;
        --sr-ok: #2f9e63;
        --sr-ok-soft: #e3f3ea;
        --sr-warn: #a9761b;
        --sr-warn-soft: #f7edd7;
        --sr-err: #cf4a40;
        --sr-err-soft: #f8e4e2;
        --sr-shadow: inset 0 1px 0 rgb(255 255 255 / 90%),
          0 2px 8px rgb(17 18 20 / 10%), 0 24px 56px rgb(17 18 20 / 20%);
        --sr-scrollbar: rgb(0 0 0 / 20%);
        font: 12px/1.45 "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont,
          sans-serif;
        letter-spacing: -.004em;
      }
      *, *::before, *::after {
        box-sizing: border-box;
      }
      .panel {
        overflow: hidden;
        color: var(--sr-t1);
        background: var(--sr-surface);
        border: 1px solid var(--sr-line-strong);
        border-radius: 3px;
        box-shadow: var(--sr-shadow);
      }
      .header {
        display: grid;
        grid-template-columns: 28px minmax(0, 1fr) auto 28px;
        align-items: center;
        gap: 6px;
        min-height: 38px;
        padding: 4px 5px;
        background: var(--sr-band);
        border-bottom: 1px solid var(--sr-line);
        cursor: grab;
        user-select: none;
        touch-action: none;
      }
      .header.dragging {
        cursor: grabbing;
      }
      .move,
      .collapse {
        width: 28px;
        height: 28px;
        padding: 0;
        color: var(--sr-t2);
        background: transparent;
        border: 1px solid transparent;
        border-radius: 2px;
        font: inherit;
      }
      .move {
        cursor: grab;
        font-family: Consolas, "Cascadia Mono", ui-monospace, monospace;
        font-size: 14px;
        letter-spacing: -3px;
      }
      .collapse {
        cursor: pointer;
        font-family: Consolas, "Cascadia Mono", ui-monospace, monospace;
        font-size: 15px;
      }
      .title {
        min-width: 0;
        font-size: 12px;
        font-weight: 650;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .mode {
        padding: 2px 5px;
        color: var(--sr-t2);
        background: var(--sr-field);
        border: 1px solid var(--sr-line);
        border-radius: 2px;
        font: 700 9px/1.3 Consolas, "Cascadia Mono", ui-monospace, monospace;
        letter-spacing: .06em;
      }
      .content {
        display: grid;
        gap: 8px;
        max-height: min(76vh, 620px);
        padding: 8px;
        overflow: auto;
        scrollbar-color: var(--sr-scrollbar) transparent;
      }
      .identity {
        display: grid;
        grid-template-columns: max-content minmax(0, 1fr);
        gap: 3px 9px;
        margin: 0;
        padding: 7px 8px;
        background: var(--sr-field);
        border: 1px solid var(--sr-line);
        border-radius: 2px;
      }
      dt {
        color: var(--sr-t3);
        font-size: 10px;
        font-weight: 600;
      }
      dd {
        min-width: 0;
        margin: 0;
        color: var(--sr-t1);
        font: 600 11px/1.45 Consolas, "Cascadia Mono", ui-monospace, monospace;
        overflow-wrap: anywhere;
        user-select: text;
      }
      .section-label {
        margin: 0 0 4px;
        color: var(--sr-t3);
        font-size: 10px;
        font-weight: 650;
      }
      .instruction {
        margin: 0 0 6px;
        padding: 6px 7px;
        color: var(--sr-t2);
        background: var(--sr-field);
        border: 1px solid var(--sr-line);
        border-radius: 2px;
        font-size: 11px;
        overflow-wrap: anywhere;
      }
      .checklist {
        display: grid;
        gap: 3px;
        margin: 0;
        padding: 0;
        list-style: none;
        counter-reset: sr-step;
      }
      .step {
        display: grid;
        grid-template-columns: 14px minmax(0, 1fr) max-content;
        align-items: baseline;
        gap: 6px;
        padding: 4px 6px;
        background: var(--sr-field);
        border: 1px solid var(--sr-line);
        border-radius: 2px;
      }
      .step.next {
        border-color: var(--sr-warn);
        border-left-width: 3px;
      }
      .step.done {
        border-color: var(--sr-ok);
        border-left-width: 3px;
      }
      .step-mark {
        color: var(--sr-t3);
        font: 700 11px/1.4 Consolas, "Cascadia Mono", ui-monospace, monospace;
        text-align: center;
      }
      .step.done .step-mark {
        color: var(--sr-ok);
      }
      .step.next .step-mark {
        color: var(--sr-warn);
      }
      .step-text {
        min-width: 0;
        color: var(--sr-t1);
        font: 10px/1.4 Consolas, "Cascadia Mono", ui-monospace, monospace;
        overflow-wrap: anywhere;
      }
      .step-state {
        color: var(--sr-t3);
        font-size: 9px;
        font-weight: 650;
        letter-spacing: .04em;
        text-transform: uppercase;
      }
      .step.done .step-state {
        color: var(--sr-ok);
      }
      .step.next .step-state {
        color: var(--sr-warn);
      }
      .outstanding {
        margin: 5px 0 0;
        color: var(--sr-t2);
        font-size: 10px;
        overflow-wrap: anywhere;
      }
      .outstanding.done {
        color: var(--sr-ok);
        font-weight: 650;
      }
      .hint-state {
        margin: 4px 0 0;
        color: var(--sr-t3);
        font-size: 10px;
        overflow-wrap: anywhere;
      }
      .state-card {
        display: grid;
        grid-template-columns: 12px minmax(0, 1fr);
        gap: 7px;
        margin: 0;
        padding: 7px 8px;
        background: var(--sr-field);
        border: 1px solid var(--sr-line);
        border-radius: 2px;
      }
      .state-mark {
        width: 7px;
        height: 7px;
        margin-top: 5px;
        background: var(--sr-ok);
        border-radius: 50%;
        box-shadow: 0 0 0 3px var(--sr-ok-soft);
      }
      .state-copy {
        min-width: 0;
      }
      .state-value {
        margin: 0;
        color: var(--sr-t1);
        font-weight: 650;
        overflow-wrap: anywhere;
      }
      .session {
        display: grid;
        grid-template-columns: 12px minmax(0, 1fr);
        gap: 7px;
        margin: 0;
        padding: 7px 8px;
        color: var(--sr-t1);
        background: var(--sr-ok-soft);
        border: 1px solid var(--sr-ok);
        border-left-width: 3px;
        border-radius: 2px;
      }
      .session-mark {
        color: var(--sr-ok);
        font: 700 12px/1.4 Consolas, "Cascadia Mono", ui-monospace, monospace;
      }
      .session-title {
        margin: 0;
        font-weight: 650;
      }
      .session-note {
        margin: 3px 0 0;
        color: var(--sr-t2);
        font-size: 10px;
        overflow-wrap: anywhere;
      }
      .gate {
        margin: 0;
        padding: 7px 8px;
        color: var(--sr-t1);
        background: var(--sr-warn-soft);
        border: 1px solid var(--sr-warn);
        border-left-width: 3px;
        border-radius: 2px;
      }
      .gate .section-label {
        color: var(--sr-warn);
      }
      .gate-files {
        margin-top: 6px;
      }
      .gate-files .section-label {
        margin-bottom: 3px;
        color: var(--sr-t2);
      }
      .gate-action {
        margin: 0;
        font-weight: 650;
        overflow-wrap: anywhere;
      }
      .boundary {
        margin: 5px 0 0;
        color: var(--sr-t2);
        font-size: 10px;
        overflow-wrap: anywhere;
      }
      .actions {
        position: sticky;
        bottom: -8px;
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 4px;
        margin: 0 -8px -8px;
        padding: 6px 8px 8px;
        background: var(--sr-surface);
        border-top: 1px solid var(--sr-line);
      }
      .action {
        min-height: 30px;
        padding: 5px 7px;
        color: var(--sr-t1);
        background: var(--sr-raise);
        border: 1px solid var(--sr-line-strong);
        border-radius: 2px;
        cursor: pointer;
        font: 650 11px/1.2 "Segoe UI", system-ui, sans-serif;
      }
      .finish {
        grid-column: 1 / -1;
        color: var(--sr-accent-on);
        background: var(--sr-accent);
        border-color: var(--sr-accent);
      }
      .another {
        color: var(--sr-t1);
      }
      .cancel {
        color: var(--sr-err);
        background: var(--sr-err-soft);
        border-color: var(--sr-err);
      }
      button:hover:not(:disabled) {
        border-color: var(--sr-t2);
      }
      button:focus-visible {
        outline: 2px solid var(--sr-accent);
        outline-offset: 2px;
      }
      button:disabled {
        cursor: not-allowed;
        opacity: .48;
      }
      .sr-only {
        position: absolute;
        width: 1px;
        height: 1px;
        padding: 0;
        margin: -1px;
        overflow: hidden;
        clip: rect(0, 0, 0, 0);
        white-space: nowrap;
        border: 0;
      }
      @media (prefers-color-scheme: dark) {
        :host {
          --sr-canvas: #242427;
          --sr-surface: #33333a;
          --sr-raise: rgb(255 255 255 / 7%);
          --sr-field: rgb(0 0 0 / 28%);
          --sr-band: #2b2b30;
          --sr-line: rgb(255 255 255 / 8%);
          --sr-line-strong: rgb(255 255 255 / 15%);
          --sr-t1: #f4f4f4;
          --sr-t2: rgb(244 244 244 / 68%);
          --sr-t3: rgb(244 244 244 / 44%);
          --sr-accent: #f4f4f5;
          --sr-accent-on: #141414;
          --sr-ok: #5fd39a;
          --sr-ok-soft: #253f35;
          --sr-warn: #e0b354;
          --sr-warn-soft: #403722;
          --sr-err: #e8756c;
          --sr-err-soft: #402726;
          --sr-shadow: inset 0 1px 0 rgb(255 255 255 / 10%),
            0 2px 8px rgb(0 0 0 / 40%), 0 28px 64px rgb(0 0 0 / 62%);
          --sr-scrollbar: rgb(255 255 255 / 16%);
        }
      }
      @media (prefers-reduced-motion: reduce) {
        *, *::before, *::after {
          scroll-behavior: auto !important;
          animation-duration: .001ms !important;
          animation-iteration-count: 1 !important;
          transition-duration: .001ms !important;
        }
      }
      @media (forced-colors: active) {
        .panel,
        .identity,
        .instruction,
        .step,
        .state-card,
        .session,
        .gate,
        .action {
          border: 1px solid ButtonText;
        }
        .state-mark {
          background: Highlight;
          box-shadow: none;
        }
      }
    `;

    // The provider is a temporary second Stockroom tab, not a free-form browser. The native
    // WebView stays the same; this narrow chrome makes that ownership visible and deliberately
    // exposes no address bar or arbitrary navigation surface.
    const browserHost = document.createElement("aside");
    browserHost.setAttribute("popover", "manual");
    browserHost.setAttribute("aria-label", "Stockroom provider tabs");
    browserHost.style.cssText = [
      "position:fixed", "inset:0 0 auto 0", "z-index:2147483647", "display:block",
      "width:100%", "height:44px", "max-width:none", "margin:0", "padding:0",
      "border:0", "background:transparent", "color-scheme:light dark",
    ].join(";");
    const browserShadow = browserHost.attachShadow({ mode: "closed" });
    const browserStyle = document.createElement("style");
    browserStyle.textContent = `
      :host { all: initial; font: 12px/1.3 "Segoe UI", system-ui, sans-serif; }
      *, *::before, *::after { box-sizing: border-box; }
      .browser-bar {
        display: grid; grid-template-columns: auto auto minmax(0, 1fr) auto;
        align-items: end; gap: 4px; width: 100%; height: 44px; padding: 6px 8px 0;
        color: #17181b; background: #e2e4e9; border-bottom: 1px solid rgb(17 18 20 / 18%);
        box-shadow: 0 2px 8px rgb(17 18 20 / 12%);
      }
      .nav-button, .tab {
        height: 32px; padding: 0 10px; color: inherit; background: rgb(255 255 255 / 45%);
        border: 1px solid rgb(17 18 20 / 14%); border-bottom: 0; border-radius: 3px 3px 0 0;
        cursor: pointer; font: 600 11px/1 "Segoe UI", system-ui, sans-serif;
      }
      .nav-button { width: 32px; padding: 0; border-bottom: 1px solid rgb(17 18 20 / 14%); }
      .tabs { display: flex; align-items: end; min-width: 0; height: 38px; gap: 3px; }
      .tab { min-width: 116px; max-width: 260px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .tab.active { height: 38px; background: #fff; border-color: rgb(17 18 20 / 22%); cursor: default; }
      .task-note { align-self: center; padding: 0 8px 6px; color: rgb(23 24 27 / 62%); font-size: 10px; white-space: nowrap; }
      button:hover:not(:disabled) { background: #fff; }
      button:focus-visible { outline: 2px solid #17181b; outline-offset: 1px; }
      @media (prefers-color-scheme: dark) {
        .browser-bar { color: #f4f4f4; background: #2b2b30; border-color: rgb(255 255 255 / 15%); box-shadow: 0 2px 8px rgb(0 0 0 / 45%); }
        .nav-button, .tab { background: rgb(255 255 255 / 7%); border-color: rgb(255 255 255 / 12%); }
        .tab.active, button:hover:not(:disabled) { background: #33333a; }
        .task-note { color: rgb(244 244 244 / 62%); }
        button:focus-visible { outline-color: #f4f4f5; }
      }
      @media (max-width: 720px) { .task-note { display: none; } .tab { min-width: 92px; } }
    `;
    const browserBar = make("nav", "browser-bar");
    browserBar.setAttribute("aria-label", "Provider navigation");
    const back = make("button", "nav-button", "←");
    back.type = "button";
    back.setAttribute("aria-label", "Back");
    const forward = make("button", "nav-button", "→");
    forward.type = "button";
    forward.setAttribute("aria-label", "Forward");
    const tabs = make("div", "tabs");
    tabs.setAttribute("role", "tablist");
    const stockroomTab = make("button", "tab", "Stockroom");
    stockroomTab.type = "button";
    stockroomTab.setAttribute("role", "tab");
    stockroomTab.setAttribute("aria-selected", "false");
    stockroomTab.setAttribute("aria-label", "Return to Stockroom");
    const providerTab = make("button", "tab active", payload.providerLabel);
    providerTab.type = "button";
    providerTab.disabled = true;
    providerTab.setAttribute("role", "tab");
    providerTab.setAttribute("aria-selected", "true");
    tabs.append(stockroomTab, providerTab);
    const taskNote = make(
      "span", "task-note", `Capturing ${payload.mpn} · downloads stay with this part`,
    );
    browserBar.append(back, forward, tabs, taskNote);
    browserShadow.append(browserStyle, browserBar);

    const panel = make("section", "panel");
    panel.setAttribute("role", "region");
    panel.setAttribute("aria-labelledby", `${payload.namespace}-title`);

    const header = make("header", "header");
    const move = make("button", "move", "⠿");
    move.type = "button";
    move.setAttribute("aria-label", "Move Stockroom panel; use arrow keys");
    const title = make("div", "title", "Stockroom Capture");
    title.id = `${payload.namespace}-title`;
    const captureCount = make("span", "mode", "0 FILES");
    captureCount.setAttribute("aria-label", "Downloads captured: 0");
    const collapse = make("button", "collapse", "−");
    collapse.type = "button";
    collapse.setAttribute("aria-expanded", "true");
    collapse.setAttribute("aria-controls", `${payload.namespace}-content`);
    collapse.setAttribute("aria-label", "Collapse Stockroom panel");
    header.append(move, title, captureCount, collapse);

    const content = make("div", "content");
    content.id = `${payload.namespace}-content`;

    const identity = make("dl", "identity");
    for (const [label, value] of [
      ["Provider", payload.providerLabel],
      ["Author Route", payload.authorRoute],
      ["Manufacturer", payload.manufacturer],
      ["MPN", payload.mpn],
    ]) {
      identity.append(make("dt", "", label), make("dd", "", value));
    }

    let sessionMemory = null;
    if (payload.sessionPersistent === true) {
      sessionMemory = make("section", "session");
      sessionMemory.setAttribute("aria-label", "DigiKey session memory");
      const sessionMark = make("span", "session-mark", "✓");
      sessionMark.setAttribute("aria-hidden", "true");
      const sessionCopy = make("div");
      sessionCopy.append(
        make("p", "session-title", "Session Memory On"),
        make(
          "p",
          "session-note",
          "Provider-only browser profile keeps this session on this PC. This assisted " +
            "window never reads or stores passwords from the page. DigiKey sign-in or " +
            "consent returns only after session expiry or a new gate.",
        ),
      );
      sessionMemory.append(sessionMark, sessionCopy);
    }

    const automation = make("section", "state-card");
    automation.setAttribute("aria-labelledby", `${payload.namespace}-automation-label`);
    const stateMark = make("span", "state-mark");
    stateMark.setAttribute("aria-hidden", "true");
    const stateCopy = make("div", "state-copy");
    const automationLabel = make("h2", "section-label", "Automated Step");
    automationLabel.id = `${payload.namespace}-automation-label`;
    const automationValue = make("p", "state-value", payload.automatedStep);
    stateCopy.append(automationLabel, automationValue);
    automation.append(stateMark, stateCopy);

    const gate = make("section", "gate");
    gate.setAttribute("aria-labelledby", `${payload.namespace}-human-label`);
    const humanLabel = make("h2", "section-label", "Human Action");
    humanLabel.id = `${payload.namespace}-human-label`;
    const humanAction = make("p", "gate-action", payload.humanAction);
    const boundary = make(
      "p",
      "boundary",
      "Provider security gates stay yours. This assisted window never reads or submits " +
        "credentials, CAPTCHA, 2FA, or passkeys.",
    );

    // The guided checklist. Every step is one exact required file label, in order, and the ONLY
    // thing that advances it is Stockroom's own receipt count. No provider state is consulted.
    const filesSection = make("div", "gate-files");
    filesSection.append(make("h3", "section-label", "Required Files"));
    if (payload.providerInstruction) {
      filesSection.append(make("p", "instruction", payload.providerInstruction));
    }
    const checklist = make("ol", "checklist");
    checklist.setAttribute("aria-label", "Required file checklist");
    const steps = payload.requiredFileLabels.map((label) => {
      const item = make("li", "step");
      const mark = make("span", "step-mark", "○");
      mark.setAttribute("aria-hidden", "true");
      const text = make("span", "step-text", label);
      const state = make("span", "step-state", "Waiting");
      item.append(mark, text, state);
      checklist.append(item);
      return { item, mark, state };
    });
    const outstanding = make("p", "outstanding", "");
    const hintState = make("p", "hint-state", "");
    filesSection.append(checklist, outstanding, hintState);
    gate.append(humanLabel, humanAction, filesSection, boundary);

    const live = make("p", "sr-only", "No files captured yet.");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");

    const actionStatus = make("p", "sr-only", "");
    actionStatus.setAttribute("role", "status");
    actionStatus.setAttribute("aria-live", "polite");

    const actions = make("div", "actions");
    const finish = make("button", "action finish", "Resume Now");
    const another = make("button", "action another", "Use Another Provider");
    const cancel = make("button", "action cancel", "Close Capture");
    for (const button of [finish, another, cancel]) button.type = "button";
    actions.append(finish, another, cancel);
    const contentNodes = [identity];
    if (sessionMemory) contentNodes.push(sessionMemory);
    contentNodes.push(
      automation,
      gate,
      live,
      actionStatus,
      actions,
    );
    content.append(...contentNodes);
    panel.append(header, content);
    shadow.append(style, panel);

    // Stockroom's own outline surface: a SECOND closed-shadow, top-layer element. Boxes are drawn
    // here and never injected into provider DOM, and every one is pointer-events:none so the
    // person's click always reaches the real control underneath. It is shown before the panel so
    // the panel stays above it in the top layer.
    const overlayHost = document.createElement("aside");
    overlayHost.setAttribute("popover", "manual");
    overlayHost.setAttribute("aria-hidden", "true");
    overlayHost.style.cssText = [
      "position:fixed",
      "inset:0",
      "z-index:2147483646",
      "display:block",
      "width:100%",
      "height:100%",
      "max-width:none",
      "max-height:none",
      "margin:0",
      "padding:0",
      "border:0",
      "overflow:visible",
      "background:transparent",
      "pointer-events:none",
      "color-scheme:light dark",
    ].join(";");
    const overlayShadow = overlayHost.attachShadow({ mode: "closed" });
    const overlayStyle = document.createElement("style");
    overlayStyle.textContent = `
      :host {
        all: initial;
        pointer-events: none;
      }
      .overlay {
        position: fixed;
        inset: 0;
        pointer-events: none;
      }
      .outline {
        position: fixed;
        pointer-events: none;
        border: 2px dashed rgb(27 27 30 / 55%);
        border-radius: 3px;
        box-shadow: 0 0 0 2px rgb(255 255 255 / 70%);
      }
      .outline.next {
        border-style: solid;
        border-color: #1b1b1e;
        box-shadow: 0 0 0 2px rgb(255 255 255 / 88%), 0 0 0 5px rgb(27 27 30 / 30%);
      }
      .outline:not(.next) .outline-tag {
        color: #17181b;
        background: rgb(255 255 255 / 92%);
        border: 1px solid rgb(27 27 30 / 45%);
      }
      .outline-tag {
        position: absolute;
        left: -2px;
        bottom: calc(100% + 4px);
        max-width: 280px;
        padding: 2px 6px;
        color: #f5f5f5;
        background: #1b1b1e;
        border-radius: 2px;
        font: 650 10px/1.4 "Segoe UI", system-ui, -apple-system, sans-serif;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
      }
      @media (prefers-color-scheme: dark) {
        .outline {
          border-color: rgb(244 244 245 / 55%);
          box-shadow: 0 0 0 2px rgb(0 0 0 / 65%);
        }
        .outline.next {
          border-color: #f4f4f5;
          box-shadow: 0 0 0 2px rgb(0 0 0 / 78%), 0 0 0 5px rgb(244 244 245 / 26%);
        }
        .outline-tag {
          color: #141414;
          background: #f4f4f5;
        }
        .outline:not(.next) .outline-tag {
          color: #f4f4f4;
          background: rgb(20 20 20 / 92%);
          border: 1px solid rgb(244 244 245 / 45%);
        }
      }
      @media (forced-colors: active) {
        .outline {
          border: 2px dashed ButtonText;
        }
        .outline.next {
          border: 2px solid Highlight;
        }
        .outline-tag {
          color: HighlightText;
          background: Highlight;
        }
      }
    `;
    const overlay = make("div", "overlay");
    overlayShadow.append(overlayStyle, overlay);
    document.documentElement.append(overlayHost);
    if (typeof overlayHost.showPopover === "function") {
      try {
        overlayHost.showPopover();
      } catch {
        overlayHost.removeAttribute("popover");
      }
    } else {
      overlayHost.removeAttribute("popover");
    }

    document.documentElement.append(browserHost, host);

    let browserChromeInTopLayer = false;
    if (typeof browserHost.showPopover === "function") {
      try {
        browserHost.showPopover();
        browserChromeInTopLayer = true;
      } catch {}
    }
    if (!browserChromeInTopLayer) browserHost.removeAttribute("popover");
    Object.defineProperty(globalThis, "__stockroom_provider_browser_chrome", {
      value: true,
      configurable: false,
      enumerable: false,
      writable: false,
    });

    let shownInTopLayer = false;
    if (typeof host.showPopover === "function") {
      try {
        host.showPopover();
        shownInTopLayer = true;
      } catch {}
    }
    if (!shownInTopLayer) host.removeAttribute("popover");

    let collapsed = false;
    collapse.addEventListener("click", () => {
      collapsed = !collapsed;
      content.hidden = collapsed;
      collapse.textContent = collapsed ? "+" : "−";
      collapse.setAttribute("aria-expanded", String(!collapsed));
      collapse.setAttribute(
        "aria-label",
        collapsed ? "Expand Stockroom panel" : "Collapse Stockroom panel",
      );
    });

    const place = (left, top) => {
      const maxLeft = Math.max(0, globalThis.innerWidth - host.offsetWidth);
      const maxTop = Math.max(0, globalThis.innerHeight - host.offsetHeight);
      host.style.inset = "auto";
      host.style.left = `${Math.max(0, Math.min(left, maxLeft))}px`;
      host.style.top = `${Math.max(0, Math.min(top, maxTop))}px`;
    };

    let drag = null;
    header.addEventListener("pointerdown", (event) => {
      if (event.target === collapse || event.button !== 0) return;
      drag = {
        pointer: event.pointerId,
        x: event.clientX,
        y: event.clientY,
        left: host.offsetLeft,
        top: host.offsetTop,
      };
      header.classList.add("dragging");
      header.setPointerCapture(event.pointerId);
    });
    header.addEventListener("pointermove", (event) => {
      if (!drag || drag.pointer !== event.pointerId) return;
      place(drag.left + event.clientX - drag.x, drag.top + event.clientY - drag.y);
    });
    const endDrag = (event) => {
      if (!drag || drag.pointer !== event.pointerId) return;
      drag = null;
      header.classList.remove("dragging");
    };
    header.addEventListener("pointerup", endDrag);
    header.addEventListener("pointercancel", endDrag);
    move.addEventListener("keydown", (event) => {
      const delta = event.shiftKey ? 40 : 10;
      const offsets = {
        ArrowLeft: [-delta, 0],
        ArrowRight: [delta, 0],
        ArrowUp: [0, -delta],
        ArrowDown: [0, delta],
      };
      if (event.key === "Home") {
        event.preventDefault();
        place(globalThis.innerWidth - host.offsetWidth - 12, 56);
        return;
      }
      const offset = offsets[event.key];
      if (!offset) return;
      event.preventDefault();
      place(host.offsetLeft + offset[0], host.offsetTop + offset[1]);
    });

    let pendingAction = null;
    let currentDownloadCount = 0;
    let unavailableFormats = Array.isArray(payload.unavailableFormats)
      ? payload.unavailableFormats
      : [];
    const pendingSteps = {
      finish: "Finishing capture after downloaded files settle.",
      try_another: "Closing this route and preparing the next provider.",
      cancel: "Closing the assisted capture.",
    };

    // ---- Tier 1: the live checklist, built only from Stockroom-owned data --------------------
    const renderChecklist = () => {
      const labels = payload.requiredFileLabels;
      const total = labels.length;
      const completed = new Set(completedFormats);
      const unavailable = new Set(unavailableFormats);
      steps.forEach((step, index) => {
        const format = payload.requiredFormats[index];
        const done = completed.has(format);
        const notOffered = unavailable.has(format);
        step.item.className = done ? "step done" : "step";
        step.mark.textContent = done ? "✓" : notOffered ? "–" : "○";
        step.state.textContent = done
          ? "Verified in download"
          : notOffered
            ? "Not offered"
            : "Required";
      });
      const availableFormats = payload.requiredFormats.filter((format) => !unavailable.has(format));
      const availableComplete = availableFormats.every((format) => completed.has(format));
      if (total > 0 && availableComplete && completed.size > 0) {
        outstanding.className = "outstanding done";
        outstanding.textContent =
          unavailable.size > 0
            ? "Every format this provider offers has been received. Stockroom will preserve it " +
              "and continue with another provider for anything still missing."
            : `All ${total} required ${total === 1 ? "format is" : "formats are"} present in the ` +
              "downloaded package. Stockroom resumes automatically.";
        return;
      }
      outstanding.className = "outstanding";
      const remaining = labels.filter(
        (_label, index) =>
          !completed.has(payload.requiredFormats[index]) &&
          !unavailable.has(payload.requiredFormats[index]),
      ).join(", ");
      outstanding.textContent =
        currentDownloadCount === 0
          ? `No download received yet. Required: ${remaining}.`
          : `${currentDownloadCount} ${currentDownloadCount === 1 ? "package" : "packages"} ` +
            `safely received. Still missing from ${currentDownloadCount === 1 ? "its" : "their"} ` +
            `contents: ${remaining}. Download another ` +
            "package if this provider offers it, or let Stockroom try the next provider.";
    };

    // ---- Tier 2: position-only outlines over the real controls -------------------------------
    // These two helpers are the WHOLE of this script's provider-DOM surface: where an element is,
    // and whether it is worth drawing over. No page text, markup, attribute value, form value, or
    // credential is read, kept, or reported anywhere - a rect is not content.
    const drawableRect = (node) => {
      if (node === host || node === overlayHost || node === browserHost) return null;
      const rect = node.getBoundingClientRect();
      if (rect.width < 6 || rect.height < 6) return null;
      if (rect.bottom <= 0 || rect.right <= 0) return null;
      if (rect.top >= globalThis.innerHeight || rect.left >= globalThis.innerWidth) return null;
      const style = getComputedStyle(node);
      if (style.visibility === "hidden" || style.display === "none") return null;
      if (Number(style.opacity) === 0) return null;
      return rect;
    };

    const uniqueVisibleRect = (selector) => {
      let nodes;
      try {
        nodes = document.querySelectorAll(selector);
      } catch {
        return null;
      }
      let found = null;
      for (const node of nodes) {
        const rect = drawableRect(node);
        if (!rect) continue;
        // Degrade, never guess. A second visible match makes the hint ambiguous, and a box on the
        // wrong control is worse than no box at all.
        if (found) return null;
        found = rect;
      }
      return found;
    };

    const anyVisible = (selector) => {
      let nodes;
      try {
        nodes = document.querySelectorAll(selector);
      } catch {
        return false;
      }
      for (const node of nodes) {
        if (drawableRect(node)) return true;
      }
      return false;
    };

    const clearOutlines = () => {
      while (overlay.firstChild) overlay.firstChild.remove();
    };

    const syncOverlay = () => {
      const total = payload.requiredFileLabels.length;
      if (securityHold) {
        clearOutlines();
        hintState.textContent =
          "Stockroom is waiting on a provider security check. It outlines nothing until you " +
          "clear it.";
        return;
      }
      if (!payload.controlHints.length) {
        clearOutlines();
        hintState.textContent =
          "Stockroom has no measured control outline for this provider; follow the checklist " +
          "above.";
        return;
      }
      if (pendingAction !== null) {
        clearOutlines();
        hintState.textContent = "";
        return;
      }
      if (total > 0 && completedFormats.length >= total) {
        clearOutlines();
        hintState.textContent = "Every required file has landed; nothing is left to outline.";
        return;
      }
      // A challenge, CAPTCHA, or sign-in belongs entirely to the person and to Stockroom's
      // existing handoff. Presence and visibility are the only things checked, and the only
      // thing they can do is STOP drawing.
      if (payload.securityControlMarkers.some(anyVisible)) {
        clearOutlines();
        hintState.textContent =
          "This page is showing a security check. Stockroom outlines nothing until you clear it.";
        return;
      }
      clearOutlines();
      const drawn = [];
      for (const hint of payload.controlHints) {
        let rect = null;
        for (const selector of hint.selectors) {
          rect = uniqueVisibleRect(selector);
          if (rect) break;
        }
        if (!rect) continue;
        drawn.push(hint.label);
        // The first hint that resolves is the one to work next; the rest are the route ahead of
        // it. Which of them is already SATISFIED cannot be known without reading the control's
        // own state, and that is exactly the page content this surface may not touch - so the
        // ordering is stated honestly rather than guessed at.
        const box = make("div", drawn.length === 1 ? "outline next" : "outline");
        box.style.left = `${Math.round(rect.left)}px`;
        box.style.top = `${Math.round(rect.top)}px`;
        box.style.width = `${Math.round(rect.width)}px`;
        box.style.height = `${Math.round(rect.height)}px`;
        box.append(make("span", "outline-tag", `${drawn.length}. ${hint.label}`));
        overlay.append(box);
      }
      hintState.textContent = drawn.length
        ? `Outlined on this page: ${drawn.join(", ")}.`
        : "No provider control could be outlined here; follow the checklist above.";
    };

    const render = () => {
      const value = currentDownloadCount;
      const noun = value === 1 ? "file" : "files";
      captureCount.textContent = `${value} ${noun.toUpperCase()}`;
      captureCount.setAttribute("aria-label", `Downloads captured: ${value}`);
      live.textContent =
        value === 0 ? "No files captured yet." : `${value} ${noun} captured in this task.`;
      // Stockroom can stay busy for the rest of the session on a request it has already accepted,
      // so everything the capture count implies has to keep tracking reality while it works.
      finish.disabled = value === 0 || (pendingAction !== null && pendingAction !== "finish");
      finish.title =
        value === 0
          ? "Available after Stockroom captures at least one file"
          : "Finish this route after its downloads settle";
      // Only a control that would conflict with the accepted request is withdrawn. Repeating the
      // pending request itself is idempotent, and the guard in requestAction is what stops a
      // second submission, so no button state has to be frozen to keep one click one request.
      another.disabled = pendingAction !== null && pendingAction !== "try_another";
      cancel.disabled = pendingAction !== null && pendingAction !== "cancel";
      automationValue.textContent =
        pendingAction !== null
          ? pendingSteps[pendingAction]
          : value === 0
            ? payload.automatedStep
            : `${value} ${noun} captured. Stockroom will resume automatically after downloads settle.`;
      renderChecklist();
      syncOverlay();
    };

    const requestAction = async (action, spokenLabel) => {
      if (pendingAction !== null) {
        if (pendingAction === action) actionStatus.textContent = `${spokenLabel} requested.`;
        return;
      }
      pendingAction = action;
      render();
      actionStatus.textContent = `${spokenLabel} requested.`;
      try {
        const accepted = await globalThis[payload.actionBinding](action, payload.actionToken);
        if (accepted) return;
      } catch {}
      pendingAction = null;
      render();
      actionStatus.textContent = "Stockroom could not accept that action. Try again.";
    };
    const requestTransientAction = async (action, spokenLabel) => {
      // Returning to the app changes only native visibility. It must not occupy the route's
      // terminal action slot or disable Finish/Try Another/Cancel when the provider is shown
      // again.
      actionStatus.textContent = `${spokenLabel} requested.`;
      try {
        const accepted = await globalThis[payload.actionBinding](action, payload.actionToken);
        if (accepted) return;
      } catch {}
      actionStatus.textContent = "Stockroom could not accept that action. Try again.";
    };
    back.addEventListener("click", () => globalThis.history.back());
    forward.addEventListener("click", () => globalThis.history.forward());
    stockroomTab.addEventListener("click", () =>
      requestTransientAction("hide", "Return to Stockroom"),
    );
    for (const [button, action] of [
      [finish, "finish"],
      [another, "try_another"],
      [cancel, "cancel"],
    ]) {
      // The spoken confirmation is read from the control's own label, so the two cannot drift.
      button.addEventListener("click", () => requestAction(action, button.textContent));
    }

    const updateState = (next) => {
      if (!next) return;
      if (Number.isInteger(next.downloadCount) && next.downloadCount >= 0) {
        currentDownloadCount = next.downloadCount;
      }
      if (Array.isArray(next.completedFormats)) completedFormats = next.completedFormats;
      if (Array.isArray(next.unavailableFormats)) unavailableFormats = next.unavailableFormats;
      if (typeof next.securityHold === "boolean") securityHold = next.securityHold;
      render();
    };
    updateState({ downloadCount, completedFormats, securityHold });

    // Provider layouts move under the person constantly. The animation frame keeps a visible tab
    // exact; the bounded interval covers a backgrounded tab, where animation frames do not fire
    // and a stale box would otherwise sit over the wrong place.
    let overlayFrame = 0;
    const scheduleOverlay = () => {
      if (overlayFrame) return;
      overlayFrame = requestAnimationFrame(() => {
        overlayFrame = 0;
        syncOverlay();
      });
    };
    globalThis.addEventListener("scroll", scheduleOverlay, { passive: true, capture: true });
    globalThis.addEventListener("resize", scheduleOverlay, { passive: true });
    setInterval(scheduleOverlay, 500);

    Object.defineProperty(globalThis, payload.namespace, {
      value: Object.freeze({ updateState }),
      configurable: false,
      enumerable: false,
      writable: false,
    });
  };

  if (document.documentElement) {
    mount();
  } else {
    document.addEventListener("DOMContentLoaded", mount, { once: true });
  }
}
"""
_PROVIDER_HUD_UPDATE = r"""
({ namespace, downloadCount, completedFormats, securityHold }) => {
  const hud = globalThis[namespace];
  if (hud && typeof hud.updateState === "function") {
    hud.updateState({ downloadCount, completedFormats, securityHold });
  }
}
"""
_HANDOFF_HUD_BOOTSTRAP = r"""
async (payload) => {
  if (!payload || globalThis !== globalThis.top || globalThis[payload.namespace]) return;
  let state;
  try {
    state = await globalThis[payload.stateBinding](payload.stateToken);
  } catch {
    return;
  }
  if (!state || !state.active || !document.documentElement) return;

  const make = (tag, className = "", text = "") => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  };

  // Automated capture can reach a security gate before the ordinary provider HUD is mounted.
  // Supply the same constrained Stockroom/provider tabs in that state, but never mount a second
  // copy when the task HUD already owns the chrome.
  let browserHost = null;
  if (!globalThis.__stockroom_provider_browser_chrome) {
    browserHost = document.createElement("aside");
    browserHost.setAttribute("popover", "manual");
    browserHost.setAttribute("aria-label", "Stockroom provider tabs");
    browserHost.style.cssText = [
      "position:fixed", "inset:0 0 auto 0", "z-index:2147483647", "display:block",
      "width:100%", "height:44px", "max-width:none", "margin:0", "padding:0",
      "border:0", "background:transparent", "color-scheme:light dark",
    ].join(";");
    const browserShadow = browserHost.attachShadow({ mode: "closed" });
    const browserStyle = document.createElement("style");
    browserStyle.textContent = `
      :host { all: initial; font: 12px/1.3 "Segoe UI", system-ui, sans-serif; }
      *, *::before, *::after { box-sizing: border-box; }
      .browser-bar { display:grid; grid-template-columns:auto auto minmax(0,1fr) auto;
        align-items:end; gap:4px; width:100%; height:44px; padding:6px 8px 0;
        color:#17181b; background:#e2e4e9; border-bottom:1px solid rgb(17 18 20 / 18%);
        box-shadow:0 2px 8px rgb(17 18 20 / 12%); }
      .nav-button,.tab { height:32px; padding:0 10px; color:inherit;
        background:rgb(255 255 255 / 45%); border:1px solid rgb(17 18 20 / 14%);
        border-bottom:0; border-radius:3px 3px 0 0; cursor:pointer;
        font:600 11px/1 "Segoe UI",system-ui,sans-serif; }
      .nav-button { width:32px; padding:0; border-bottom:1px solid rgb(17 18 20 / 14%); }
      .tabs { display:flex; align-items:end; min-width:0; height:38px; gap:3px; }
      .tab { min-width:116px; max-width:260px; overflow:hidden; text-overflow:ellipsis;
        white-space:nowrap; }
      .tab.active { height:38px; background:#fff; border-color:rgb(17 18 20 / 22%);
        cursor:default; }
      .task-note { align-self:center; padding:0 8px 6px; color:rgb(23 24 27 / 62%);
        font-size:10px; white-space:nowrap; }
      button:hover:not(:disabled) { background:#fff; }
      button:focus-visible { outline:2px solid #17181b; outline-offset:1px; }
      @media (prefers-color-scheme:dark) {
        .browser-bar { color:#f4f4f4; background:#2b2b30; border-color:rgb(255 255 255 / 15%);
          box-shadow:0 2px 8px rgb(0 0 0 / 45%); }
        .nav-button,.tab { background:rgb(255 255 255 / 7%);
          border-color:rgb(255 255 255 / 12%); }
        .tab.active,button:hover:not(:disabled) { background:#33333a; }
        .task-note { color:rgb(244 244 244 / 62%); }
        button:focus-visible { outline-color:#f4f4f5; }
      }
      @media (max-width:720px) { .task-note { display:none; } .tab { min-width:92px; } }
    `;
    const browserBar = make("nav", "browser-bar");
    browserBar.setAttribute("aria-label", "Provider navigation");
    const back = make("button", "nav-button", "←");
    back.type = "button";
    back.setAttribute("aria-label", "Back");
    const forward = make("button", "nav-button", "→");
    forward.type = "button";
    forward.setAttribute("aria-label", "Forward");
    const tabs = make("div", "tabs");
    tabs.setAttribute("role", "tablist");
    const stockroomTab = make("button", "tab", "Stockroom");
    stockroomTab.type = "button";
    stockroomTab.setAttribute("role", "tab");
    stockroomTab.setAttribute("aria-selected", "false");
    stockroomTab.setAttribute("aria-label", "Return to Stockroom");
    const providerTab = make("button", "tab active", state.providerLabel);
    providerTab.type = "button";
    providerTab.disabled = true;
    providerTab.setAttribute("role", "tab");
    providerTab.setAttribute("aria-selected", "true");
    tabs.append(stockroomTab, providerTab);
    const taskNote = make("span", "task-note", `Capturing ${state.mpn} · security check paused`);
    browserBar.append(back, forward, tabs, taskNote);
    browserShadow.append(browserStyle, browserBar);
    back.addEventListener("click", () => globalThis.history.back());
    forward.addEventListener("click", () => globalThis.history.forward());
    stockroomTab.addEventListener("click", async () => {
      stockroomTab.disabled = true;
      stockroomTab.textContent = "Returning…";
      try {
        const accepted = await globalThis[payload.actionBinding]("hide", payload.actionToken);
        if (accepted) return;
      } catch {}
      stockroomTab.disabled = false;
      stockroomTab.textContent = "Stockroom";
    });
    document.documentElement.append(browserHost);
    if (typeof browserHost.showPopover === "function") {
      try { browserHost.showPopover(); } catch { browserHost.removeAttribute("popover"); }
    } else {
      browserHost.removeAttribute("popover");
    }
  }

  const host = document.createElement("aside");
  host.setAttribute("aria-label", "Stockroom security handoff");
  host.setAttribute("popover", "manual");
  host.style.cssText = [
    "position:fixed",
    "inset:56px 12px auto auto",
    "z-index:2147483647",
    "display:block",
    "width:min(368px,calc(100vw - 24px))",
    "color-scheme:light dark",
  ].join(";");
  const shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    :host {
      all: initial;
      --sr-surface: #ffffff;
      --sr-field: rgb(17 18 20 / 5%);
      --sr-band: #e2e4e9;
      --sr-line: rgb(17 18 20 / 10%);
      --sr-line-strong: rgb(17 18 20 / 18%);
      --sr-t1: #17181b;
      --sr-t2: rgb(23 24 27 / 68%);
      --sr-t3: rgb(23 24 27 / 48%);
      --sr-ok: #2f9e63;
      --sr-ok-soft: #e3f3ea;
      --sr-warn: #a9761b;
      --sr-warn-soft: #f7edd7;
      --sr-shadow: inset 0 1px 0 rgb(255 255 255 / 90%),
        0 2px 8px rgb(17 18 20 / 10%), 0 24px 56px rgb(17 18 20 / 20%);
      font: 12px/1.45 "Segoe UI", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
      letter-spacing: -.004em;
    }
    *, *::before, *::after { box-sizing: border-box; }
    .panel {
      overflow: hidden;
      color: var(--sr-t1);
      background: var(--sr-surface);
      border: 1px solid var(--sr-warn);
      border-radius: 3px;
      box-shadow: var(--sr-shadow);
    }
    .header {
      display: flex;
      min-height: 38px;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      padding: 5px 8px;
      background: var(--sr-band);
      border-bottom: 1px solid var(--sr-line);
    }
    h1 {
      min-width: 0;
      margin: 0;
      overflow: hidden;
      font-size: 12px;
      font-weight: 650;
      text-overflow: ellipsis;
      white-space: nowrap;
    }
    .mode {
      flex: none;
      padding: 2px 5px;
      color: var(--sr-warn);
      background: var(--sr-warn-soft);
      border: 1px solid var(--sr-warn);
      border-radius: 2px;
      font: 700 9px/1.3 Consolas, "Cascadia Mono", ui-monospace, monospace;
      letter-spacing: .06em;
    }
    .header-actions {
      display: flex;
      flex: none;
      align-items: center;
      gap: 5px;
    }
    .toggle {
      min-width: 48px;
      min-height: 26px;
      padding: 3px 7px;
      color: var(--sr-t1);
      background: var(--sr-surface);
      border: 1px solid var(--sr-line-strong);
      border-radius: 2px;
      font: 600 10px/1.2 "Segoe UI", system-ui, sans-serif;
      cursor: pointer;
    }
    .toggle:hover { border-color: var(--sr-warn); }
    .toggle:focus-visible {
      outline: 2px solid var(--sr-warn);
      outline-offset: 1px;
    }
    .content {
      display: grid;
      gap: 8px;
      padding: 8px;
    }
    .content[hidden] { display: none; }
    .identity {
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 3px 9px;
      margin: 0;
      padding: 7px 8px;
      background: var(--sr-field);
      border: 1px solid var(--sr-line);
      border-radius: 2px;
    }
    dt {
      color: var(--sr-t3);
      font-size: 10px;
      font-weight: 600;
    }
    dd {
      min-width: 0;
      margin: 0;
      color: var(--sr-t1);
      font: 600 11px/1.45 Consolas, "Cascadia Mono", ui-monospace, monospace;
      overflow-wrap: anywhere;
      user-select: text;
    }
    .section-label {
      margin: 0 0 4px;
      color: var(--sr-t3);
      font-size: 10px;
      font-weight: 650;
    }
    .automation,
    .gate {
      margin: 0;
      padding: 7px 8px;
      border-radius: 2px;
    }
    .automation {
      background: var(--sr-field);
      border: 1px solid var(--sr-line);
    }
    .gate {
      background: var(--sr-warn-soft);
      border: 1px solid var(--sr-warn);
      border-left-width: 3px;
    }
    .gate .section-label { color: var(--sr-warn); }
    .session {
      display: grid;
      grid-template-columns: 12px minmax(0, 1fr);
      gap: 7px;
      margin: 0;
      padding: 7px 8px;
      background: var(--sr-ok-soft);
      border: 1px solid var(--sr-ok);
      border-left-width: 3px;
      border-radius: 2px;
    }
    .session-mark {
      color: var(--sr-ok);
      font: 700 12px/1.4 Consolas, "Cascadia Mono", ui-monospace, monospace;
    }
    .session-title {
      margin: 0;
      font-weight: 650;
    }
    .session-note {
      margin: 3px 0 0;
      color: var(--sr-t2);
      font-size: 10px;
      overflow-wrap: anywhere;
    }
    .status,
    .action {
      margin: 0;
      font-weight: 650;
      overflow-wrap: anywhere;
    }
    .safe {
      margin: 5px 0 0;
      color: var(--sr-t2);
      font-size: 10px;
      overflow-wrap: anywhere;
    }
    .resume {
      display: flex;
      align-items: center;
      gap: 7px;
      margin: 0;
      padding: 6px 8px;
      color: var(--sr-t2);
      background: var(--sr-field);
      border: 1px solid var(--sr-line);
      border-radius: 2px;
    }
    .resume::before {
      width: 7px;
      height: 7px;
      flex: none;
      background: var(--sr-warn);
      border-radius: 50%;
      box-shadow: 0 0 0 3px var(--sr-warn-soft);
      content: "";
    }
    @media (prefers-color-scheme: dark) {
      :host {
        --sr-surface: #33333a;
        --sr-field: rgb(0 0 0 / 28%);
        --sr-band: #2b2b30;
        --sr-line: rgb(255 255 255 / 8%);
        --sr-line-strong: rgb(255 255 255 / 15%);
        --sr-t1: #f4f4f4;
        --sr-t2: rgb(244 244 244 / 68%);
        --sr-t3: rgb(244 244 244 / 44%);
        --sr-ok: #5fd39a;
        --sr-ok-soft: #253f35;
        --sr-warn: #e0b354;
        --sr-warn-soft: #403722;
        --sr-shadow: inset 0 1px 0 rgb(255 255 255 / 10%),
          0 2px 8px rgb(0 0 0 / 40%), 0 28px 64px rgb(0 0 0 / 62%);
      }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after {
        animation-duration: .001ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: .001ms !important;
      }
    }
    @media (forced-colors: active) {
      .panel, .identity, .automation, .session, .gate, .resume {
        border: 1px solid ButtonText;
      }
      .resume::before { background: Highlight; box-shadow: none; }
    }
  `;
  const panel = make("section", "panel");
  panel.setAttribute("role", "alert");
  const header = make("header", "header");
  const title = make("h1", "", "Stockroom Capture");
  const mode = make("span", "mode", "PAUSED");
  const headerActions = make("div", "header-actions");
  const toggle = make("button", "toggle", "Details");
  toggle.type = "button";
  toggle.setAttribute("aria-label", "Show Stockroom capture guidance");
  headerActions.append(mode, toggle);
  header.append(title, headerActions);

  const content = make("div", "content");
  const identity = make("dl", "identity");
  for (const [label, value] of [
    ["Provider", state.providerLabel],
    ["Author Route", state.authorRoute],
    ["Manufacturer", state.manufacturer],
    ["MPN", state.mpn],
  ]) {
    identity.append(make("dt", "", label), make("dd", "", value));
  }

  let sessionMemory = null;
  if (state.sessionPersistent === true) {
    sessionMemory = make("section", "session");
    sessionMemory.setAttribute("aria-label", "DigiKey session memory");
    const sessionMark = make("span", "session-mark", "✓");
    sessionMark.setAttribute("aria-hidden", "true");
    const sessionCopy = make("div");
    sessionCopy.append(
      make("p", "session-title", "Session Memory On"),
      make(
        "p",
        "session-note",
        "Provider-only browser profile keeps this session on this PC. This assisted " +
          "window never reads or stores passwords from the page. DigiKey sign-in or " +
          "consent returns only after session expiry or a new gate.",
      ),
    );
    sessionMemory.append(sessionMark, sessionCopy);
  }

  const automation = make("section", "automation");
  automation.append(
    make("h2", "section-label", "Automated Step"),
    make("p", "status", "Paused at the provider security gate."),
  );
  const gate = make("section", "gate");
  const message = make("p", "action", state.message);
  message.setAttribute("aria-live", "polite");
  const safe = make(
    "p",
    "safe",
    "Complete the visible provider gate yourself. This assisted window never reads or " +
      "submits credentials, CAPTCHA, 2FA, or passkeys.",
  );
  gate.append(make("h2", "section-label", "Human Action"), message, safe);
  const resume = make(
    "p",
    "resume",
    "Waiting to resume automatically when the provider gate clears.",
  );
  const contentNodes = [identity];
  if (sessionMemory) contentNodes.push(sessionMemory);
  contentNodes.push(automation, gate, resume);
  content.append(...contentNodes);
  panel.append(header, content);
  const setCollapsed = (collapsed) => {
    content.hidden = collapsed;
    toggle.textContent = collapsed ? "Details" : "Hide";
    toggle.setAttribute("aria-expanded", collapsed ? "false" : "true");
    toggle.setAttribute(
      "aria-label",
      collapsed
        ? "Show Stockroom capture guidance"
        : "Hide Stockroom capture guidance",
    );
  };
  toggle.addEventListener("click", () => setCollapsed(!content.hidden));
  // Security challenges are commonly centered in narrow embedded panes. Keep the
  // handoff visible without covering the control the person must operate.
  setCollapsed(true);
  shadow.append(style, panel);
  document.documentElement.append(host);
  let shownInTopLayer = false;
  if (typeof host.showPopover === "function") {
    try {
      host.showPopover();
      shownInTopLayer = true;
    } catch {}
  }
  if (!shownInTopLayer) host.removeAttribute("popover");

  Object.defineProperty(globalThis, payload.namespace, {
    value: Object.freeze({
      update(next) {
        if (typeof next === "string" && next) message.textContent = next;
      },
      dismiss() { host.remove(); if (browserHost) browserHost.remove(); },
    }),
    configurable: false,
    enumerable: false,
    writable: false,
  });
}
"""
_HANDOFF_HUD_UPDATE = r"""
({ namespace, message }) => {
  const hud = globalThis[namespace];
  if (hud && typeof hud.update === "function") hud.update(message);
}
"""
_HANDOFF_HUD_DISMISS = r"""
(namespace) => {
  const hud = globalThis[namespace];
  if (hud && typeof hud.dismiss === "function") hud.dismiss();
}
"""


@dataclass(slots=True)
class _ProviderHudState:
    spec: ProviderHudSpec
    persistent_session: bool = False
    namespace: str = field(
        default_factory=lambda: f"__stockroom_capture_hud_{secrets.token_hex(12)}"
    )
    action_binding: str = field(
        default_factory=lambda: f"__stockroom_capture_action_{secrets.token_hex(12)}"
    )
    action_token: str = field(default_factory=lambda: secrets.token_hex(24))
    state_binding: str = field(
        default_factory=lambda: f"__stockroom_capture_state_{secrets.token_hex(12)}"
    )
    state_token: str = field(default_factory=lambda: secrets.token_hex(24))
    _action: ProviderHudAction | None = None
    _download_count: int = 0
    _completed_formats: tuple[str, ...] = ()
    _unavailable_formats: tuple[str, ...] = ()
    # True while Stockroom's own `user_clearance_issue` detection says this page belongs to the
    # person. The HUD draws no control outline at all while it is set.
    _security_hold: bool = False
    _lock: threading.RLock = field(default_factory=threading.RLock)

    @property
    def action(self) -> ProviderHudAction | None:
        with self._lock:
            return self._action

    def request_action(self, action: object, token: object) -> bool:
        if (
            type(action) is not str
            or action not in _PROVIDER_HUD_ACTIONS
            or type(token) is not str
            or not secrets.compare_digest(token, self.action_token)
        ):
            return False
        with self._lock:
            if self._action is not None:
                # One state is shared across every page bound to this task, and the HUD remounts
                # with a fresh pending flag on each provider navigation, so the person can click
                # the same control again before Python has acted on the first request. Reporting
                # failure for an action already accepted is what surfaced "Stockroom could not
                # accept that action". A genuinely conflicting action is still refused.
                return self._action == action
            self._action = cast(ProviderHudAction, action)
            return True

    def authorizes_visibility_action(self, action: object, token: object) -> bool:
        """Authorize a reversible browser-tab switch without ending the capture route."""

        return (
            action == "hide"
            and type(token) is str
            and secrets.compare_digest(token, self.action_token)
        )

    def update_download_count(
        self,
        count: int,
        completed_formats: tuple[str, ...] | None = None,
        unavailable_formats: tuple[str, ...] | None = None,
    ) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("download count must be a non-negative integer")
        if completed_formats is not None and (
            type(completed_formats) is not tuple
            or any(value not in self.spec.required_formats for value in completed_formats)
        ):
            raise ValueError("completed formats must be required provider format keys")
        if unavailable_formats is not None and (
            type(unavailable_formats) is not tuple
            or any(value not in self.spec.required_formats for value in unavailable_formats)
        ):
            raise ValueError("unavailable formats must be required provider format keys")
        with self._lock:
            self._download_count = count
            if completed_formats is not None:
                self._completed_formats = tuple(
                    key for key in self.spec.required_formats if key in completed_formats
                )
            if unavailable_formats is not None:
                self._unavailable_formats = tuple(
                    key for key in self.spec.required_formats if key in unavailable_formats
                )

    @property
    def download_count(self) -> int:
        with self._lock:
            return self._download_count

    @property
    def completed_formats(self) -> tuple[str, ...]:
        with self._lock:
            return self._completed_formats

    @property
    def unavailable_formats(self) -> tuple[str, ...]:
        with self._lock:
            return self._unavailable_formats

    @property
    def security_hold(self) -> bool:
        with self._lock:
            return self._security_hold

    def set_security_hold(self, held: object) -> None:
        """Suppress or restore every control outline from Stockroom's own security detection."""

        if type(held) is not bool:
            raise ValueError("security hold must be a bool")
        with self._lock:
            self._security_hold = held

    def read_state(self, token: object) -> dict[str, object]:
        """Serve the live receipt count and outline hold to a HUD that has just mounted.

        The bootstrap payload is registered once and replayed on every provider navigation, so a
        remounted panel would otherwise report the count as it stood at bind time. Nothing here
        reads the provider page: this is Stockroom's own count and Stockroom's own security
        verdict, both behind Stockroom's own secret.
        """

        if type(token) is not str or not secrets.compare_digest(token, self.state_token):
            return {}
        with self._lock:
            return {
                "downloadCount": self._download_count,
                "completedFormats": list(self._completed_formats),
                "unavailableFormats": list(self._unavailable_formats),
                "securityHold": self._security_hold,
            }

    def payload(self) -> dict[str, object]:
        instruction, hints = _provider_guidance(self.spec)
        with self._lock:
            return {
                "namespace": self.namespace,
                "actionBinding": self.action_binding,
                "actionToken": self.action_token,
                "stateBinding": self.state_binding,
                "stateToken": self.state_token,
                "providerLabel": self.spec.provider_label,
                "authorRoute": self.spec.author_route,
                "manufacturer": self.spec.manufacturer,
                "mpn": self.spec.mpn,
                "requiredFileLabels": list(self.spec.required_file_labels),
                "requiredFormats": list(self.spec.required_formats),
                "automatedStep": self.spec.automated_step,
                "humanAction": self.spec.human_action,
                "sessionPersistent": self.persistent_session,
                "downloadCount": self._download_count,
                "completedFormats": list(self._completed_formats),
                "unavailableFormats": list(self._unavailable_formats),
                "securityHold": self._security_hold,
                "providerInstruction": instruction,
                # Only what the surface needs to DRAW. The measured provenance of each selector
                # stays in Python, where reviewers read it; the page never receives it.
                "controlHints": [
                    {"label": hint.label, "selectors": list(hint.selectors)} for hint in hints
                ],
                "securityControlMarkers": list(_HUD_SECURITY_CONTROL_MARKERS),
            }


def _provider_guidance(
    spec: ProviderHudSpec,
) -> tuple[str, tuple[ProviderControlHint, ...]]:
    """The provider's own instruction and measured control hints for one HUD spec.

    An explicit spec always wins. Otherwise the vendor registry is consulted by the EXACT provider
    label, which is the adapter's own ``capability.label`` and unique across the registry. That
    fallback is what lets the guidance reach a HUD whose caller builds the spec from task identity
    alone. The import is deferred so this module keeps no import-time dependency on the vendor
    registry, and an unavailable registry simply means Tier 1 text with no outlines.
    """

    if spec.provider_instruction and spec.control_hints:
        return spec.provider_instruction, spec.control_hints
    instruction = spec.provider_instruction
    hints = spec.control_hints
    try:
        from stockroom.capture.vendors import provider_hud_guidance

        registry_instruction, registry_hints = provider_hud_guidance(spec.provider_label)
    except Exception:  # noqa: BLE001 - guidance is an enhancement, never a capture blocker
        return instruction, hints
    return (
        instruction or registry_instruction,
        hints or registry_hints,
    )


def _disable_webrtc(context) -> None:
    """Prevent capture pages from opening inbound WebRTC UDP listeners.

    Playwright controls Chromium over a pipe, so its automation transport does not need an
    inbound firewall exception. Provider and fingerprinting scripts can still instantiate
    ``RTCPeerConnection``, though, which makes Chromium's Network Service bind wildcard UDP
    endpoints and can trigger Windows Defender Firewall. CAD capture does not use WebRTC.

    A context init script applies before page scripts in every subsequently created document and
    child frame. Fail closed: continuing without this boundary can surface the firewall prompt.
    """

    try:
        context.add_init_script(_DISABLE_WEBRTC_INIT_SCRIPT)
    except Exception as exc:  # noqa: BLE001 - browser implementations expose different errors
        raise CaptureBrowserError("could not disable WebRTC in the capture browser") from exc


def _normalise_provider_key(provider_key: str) -> str:
    key = (provider_key or "").strip().casefold()
    if _PROVIDER_KEY.fullmatch(key) is None:
        raise CaptureBrowserError(f"invalid capture provider key {provider_key!r}")
    return key


def provider_profile_dir(profile_root: Path, provider_key: str) -> Path:
    """Return the provider's isolated persistent profile below ``profile_root``."""

    return Path(profile_root) / _normalise_provider_key(provider_key)


def _allow_automatic_downloads(profile_dir: Path) -> None:
    """Allow a provider page to deliver every file in one export.

    SnapMagic and similar CAD providers fan one explicit "download" action out into
    several browser downloads (symbol, footprint, model, metadata). Chromium otherwise
    pauses after the first file behind an "allow multiple downloads" prompt while the
    page itself reports success. This profile is isolated to one capture provider, and
    every resulting file still has to pass Stockroom's content and identity verification.
    """

    preferences_path = Path(profile_dir) / _CHROMIUM_PREFERENCES
    preferences_path.parent.mkdir(parents=True, exist_ok=True)
    preferences: dict = {}
    if preferences_path.is_file():
        try:
            loaded = json.loads(preferences_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise CaptureBrowserError(
                f"could not safely update capture browser preferences at {preferences_path}"
            ) from exc
        if not isinstance(loaded, dict):
            raise CaptureBrowserError(
                f"capture browser preferences are not an object at {preferences_path}"
            )
        preferences = loaded

    profile = preferences.setdefault("profile", {})
    if not isinstance(profile, dict):
        raise CaptureBrowserError(
            f"capture browser profile preferences are malformed at {preferences_path}"
        )
    defaults = profile.setdefault("default_content_setting_values", {})
    if not isinstance(defaults, dict):
        raise CaptureBrowserError(
            f"capture browser content settings are malformed at {preferences_path}"
        )
    defaults["automatic_downloads"] = 1

    temporary_path = preferences_path.with_suffix(".stockroom.tmp")
    try:
        temporary_path.write_text(
            json.dumps(preferences, ensure_ascii=False, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(temporary_path, preferences_path)
    except OSError as exc:
        temporary_path.unlink(missing_ok=True)
        raise CaptureBrowserError(
            f"could not enable provider multi-file downloads at {preferences_path}"
        ) from exc


@dataclass(slots=True)
class _NativeSurfaceDownload:
    """One host-observed download that remains visible while CDP is detached."""

    operation_id: str
    generation: int
    broker: DownloadBroker | None
    suggested_name: str
    source_url: str
    result_path: Path
    state: str = "in_progress"
    captured: bool = False


class ProviderProfileLock:
    """Fail-fast process and OS lock protecting one provider's browser profile.

    Chromium already refuses many duplicate profile launches, but relying on its incidental error
    makes contention browser-version dependent and can leave partially updated profile state.
    This guard establishes ownership before Playwright touches the directory.
    """

    def __init__(self, profile_dir: Path, provider_key: str):
        self.profile_dir = Path(profile_dir)
        self.provider_key = _normalise_provider_key(provider_key)
        self.path = (
            self.profile_dir.parent / ".locks" / f"{self.provider_key}.stockroom-browser.lock"
        )
        self._handle = None
        self._process_key = os.path.normcase(str(self.path.resolve(strict=False)))
        self._held = False

    def acquire(self) -> None:
        with _PROCESS_LOCK_GUARD:
            if self._process_key in _PROCESS_LOCKS:
                self._raise_busy()
            _PROCESS_LOCKS.add(self._process_key)

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:  # pragma: no cover - Windows is authoritative; keeps unit tests portable
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except (OSError, BlockingIOError):
                handle.close()
                self._raise_busy()
            self._handle = handle
            self._held = True
        except BaseException:
            with _PROCESS_LOCK_GUARD:
                _PROCESS_LOCKS.discard(self._process_key)
            raise

    def _raise_busy(self) -> None:
        raise CaptureBrowserError(
            f"{self.provider_key} capture is already using its browser profile; "
            "wait for that capture worker to finish"
        )

    def release(self) -> None:
        if not self._held:
            return
        handle = self._handle
        try:
            if handle is not None:
                try:
                    handle.seek(0)
                    if os.name == "nt":
                        import msvcrt

                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                    else:  # pragma: no cover - Windows authoritative; tests stay portable
                        import fcntl

                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                finally:
                    handle.close()
        finally:
            self._handle = None
            self._held = False
            with _PROCESS_LOCK_GUARD:
                _PROCESS_LOCKS.discard(self._process_key)

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.release()


class SharedPlaywrightRuntime:
    """One lazy synchronous Playwright owner shared by every provider in a capture run.

    Playwright's synchronous API cannot nest two runtime context managers on one thread. A
    provider fallback chain legitimately keeps several browser contexts alive so each provider
    can preserve its signed-in session across parts; those contexts therefore share this one
    engine runtime and retain separate browser/profile ownership.
    """

    def __init__(self) -> None:
        self._manager = None
        self._playwright = None
        self._thread_id: int | None = None
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def get(self):
        thread_id = threading.get_ident()
        if self._playwright is not None:
            if self._thread_id != thread_id:
                raise CaptureBrowserError(
                    "the guided-capture browser runtime cannot move between worker threads"
                )
            return self._playwright
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise CaptureBrowserError(
                "playwright is not installed; it is a declared dependency, run `uv sync`"
            ) from exc
        manager = sync_playwright()
        self._playwright = manager.__enter__()
        self._manager = manager
        self._thread_id = thread_id
        self._generation += 1
        return self._playwright

    def close(self) -> None:
        manager = self._manager
        if manager is None:
            return
        if self._thread_id != threading.get_ident():
            raise CaptureBrowserError(
                "the guided-capture browser runtime must close on its owning worker thread"
            )
        self._manager = None
        self._playwright = None
        self._thread_id = None
        manager.__exit__(None, None, None)


class _ReconnectablePage:
    """Stable page identity across a deliberate CDP detach/reconnect.

    Provider adapters keep the same small Playwright-shaped object while Stockroom removes the
    automation transport for a visible security check.  Once the native WebView reports the gate
    gone, the handle is rebound to the same live WebView page and ordinary provider work resumes.
    """

    def __init__(self, page) -> None:
        self._page = page

    @property
    def raw_page(self):
        return self._page

    def replace(self, page) -> None:
        self._page = page

    def __getattr__(self, name):
        return getattr(self._page, name)


def _raw_page(page):
    return page.raw_page if isinstance(page, _ReconnectablePage) else page


def _native_surface_page(pages, native_surface):
    """Return the CDP page that belongs to the native Stockroom window.

    A provider can leave a popup target beside the real pywebview target. CDP does not promise
    context page ordering, so taking ``pages[0]`` can bind the next task's broker/HUD to a stale
    popup while the person is looking at the native Stockroom window. The native shell already
    exposes its exact current URL without provider content; use that stable identity and retain
    the old first-page fallback only when a lightweight/test surface cannot report it.
    """

    current_url = getattr(native_surface, "current_url", None)
    if not callable(current_url):
        return None
    try:
        expected = str(current_url() or "")
    except Exception:  # noqa: BLE001 - unreadable native state keeps the legacy fallback
        return None
    if not expected:
        return None
    return next(
        (candidate for candidate in pages if _page_url(candidate, "") == expected),
        None,
    )


class PlaywrightCaptureBrowser:
    """A real, visible browser the person can work in, whose downloads we observe.

    Not headless by default: this is a GUIDED capture, so the human signs in, clears a Cloudflare
    check, and watches what happens. Headless exists for the tests.

    ENGINE IS A PARAMETER, NEVER A SECOND CLASS. Production attaches to Stockroom's own embedded
    provider surface; the standalone fallback uses Stockroom's version-pinned Playwright Chromium
    so the browser version is part of the tested application contract rather than whichever
    branded browser happens to be installed. ``windows`` remains an explicit Chrome-then-Chromium
    compatibility policy. Stealth engines are gone with the automation they served: this window
    exists so a PERSON can work a provider page, and a person needs no evasion. There is one
    capture-browser class - that is the one-tool-per-job rule, and
    tests/backend/capture/test_one_tool_per_job.py enforces it by listing the modules allowed to
    launch a browser at all.

    The constructor and production call site deliberately share the ``chromium`` default. Tests
    drive the same bundled browser policy the product ships.
    """

    # Stockroom launched this window and is responsible for closing it. The de-automated transport
    # in ``capture/handoff.py`` declares the opposite, and that difference is the whole contract:
    # a window Stockroom owns is an automated session, and a person-driven route must not have one.
    owns_window = True

    def __init__(
        self,
        *,
        download_dir: Path,
        profile_dir: Path | None = None,
        headless: bool = False,
        engine: str = "chromium",
        provider_key: str | None = None,
        playwright_runtime: SharedPlaywrightRuntime | None = None,
        cdp_endpoint: str | None = None,
        native_surface: object | None = None,
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.engine = engine
        self._playwright_runtime = playwright_runtime
        self._cdp_endpoint = cdp_endpoint
        self._native_surface = native_surface
        self._runtime_generation = 0
        self._browser = None
        self.provider_key = (
            _normalise_provider_key(provider_key)
            if provider_key is not None
            else _normalise_provider_key(self.profile_dir.name)
            if self.profile_dir is not None
            else None
        )
        self.launched_browser: str | None = None
        self._captured: list[CapturedFile] = []
        self._download_errors: list[CaptureBrowserError] = []
        self._wired_pages: list[object] = []
        self._page_brokers: list[tuple[object, DownloadBroker]] = []
        self._page_huds: list[tuple[Any, _ProviderHudState]] = []
        self._context = None
        self._embedded_download_generation = 0
        self._embedded_active_generation = 0
        self._embedded_finalized_generations: set[int] = set()
        self._native_download_cursor = 0
        self._native_surface_downloads: dict[str, _NativeSurfaceDownload] = {}
        # Playwright's synchronous API may re-enter the download callback while ``save_as`` for
        # the previous file pumps protocol events.  A provider action that emits a symbol,
        # footprint, and model together therefore nests callbacks on the same thread.  A plain
        # Lock deadlocks on the second file; the RLock serializes filename allocation without
        # blocking that legitimate re-entry.
        self._download_lock = threading.RLock()

    @property
    def captured(self) -> list[CapturedFile]:
        self._drain_native_downloads()
        return list(self._captured)

    @property
    def _has_native_download_ledger(self) -> bool:
        """True when Stockroom's host reports this window's downloads itself."""

        return callable(getattr(self._native_surface, "download_events", None))

    @property
    def download_errors(self) -> tuple[CaptureBrowserError, ...]:
        with self._download_lock:
            return tuple(self._download_errors)

    @property
    def persistent_digikey_session(self) -> bool:
        """Whether this browser owns DigiKey's provider-isolated persistent profile."""

        return self.provider_key == "digikey" and self.profile_dir is not None

    @contextmanager
    def task_page(
        self,
        broker: DownloadBroker,
        *,
        hud_state: _ProviderHudState | None = None,
    ):
        """Open one page whose downloads can belong to exactly one workflow task.

        A provider context persists for the run so cookies and sign-in survive, but pages do not
        cross task boundaries. A slow export from part A can therefore never arrive after a
        mutable global binding has moved to part B: A's page stays permanently mapped to A and is
        closed before B gets a new page. Popups inherit the mapping through their opener.
        """
        if type(broker) is not DownloadBroker:
            raise TypeError("broker must be a DownloadBroker")
        if hud_state is not None and type(hud_state) is not _ProviderHudState:
            raise TypeError("hud_state must be Stockroom-owned provider HUD state")
        with self._download_lock:
            context = self._context
        if context is None:
            raise CaptureBrowserError("the capture browser session is not open")
        with self._download_lock:
            self._embedded_download_generation += 1
            embedded_generation = self._embedded_download_generation
            self._embedded_active_generation = embedded_generation
        # A persistent Playwright context normally starts with one about:blank page. Opening a
        # second page here left that inert first window visible beside the task-bound one, which
        # made Stockroom appear to launch duplicate browsers even though only one could capture.
        # Claim that untouched page for the first task; later tasks still receive fresh pages.
        with self._download_lock:
            bound_pages = {id(wired) for wired, _bound in self._page_brokers}
        pages = list(getattr(context, "pages", ()) or ())
        reusable_pages = [
            candidate
            for candidate in pages
            if id(candidate) not in bound_pages and not _page_is_closed(candidate)
        ]
        page = next(
            (
                candidate
                for candidate in reusable_pages
                if _page_url(candidate, "about:blank") in {"", "about:blank"}
            ),
            None,
        )
        # A CDP session is the WebView that already renders Stockroom. It will not be blank, and
        # opening a new Playwright page creates a second native WebView window beside the app.
        # Claim the existing page instead: the surface lease restores the Stockroom SPA after the
        # provider task ends, while this task keeps download listeners bound to that exact page.
        if page is None and self._cdp_endpoint is not None and reusable_pages:
            page = _native_surface_page(reusable_pages, self._native_surface) or reusable_pages[0]
        # Claiming a pre-existing page avoids a stray blank window, but that page is the one
        # `session()` yields and keeps for the whole session. Only a page this task actually
        # opened may be closed with it; closing a claimed one ends the session's own surface.
        task_opened_page = page is None
        if page is None:
            page = context.new_page()
        original_page = page
        page_handle = _ReconnectablePage(page) if self._cdp_endpoint is not None else page
        self._wire_downloads(page)
        with self._download_lock:
            self._page_brokers.append((page, broker))
        try:
            if hud_state is not None:
                self._bind_provider_hud(page, hud_state)
            yield page_handle
        finally:
            page = _raw_page(page_handle)
            with self._download_lock:
                context = self._context or context
            # Provider download actions can open child tabs/windows. They inherit the broker
            # binding through their opener, so they are part of this task and must close with it.
            # Leaving them behind produces stale windows whose controls no longer attach files.
            owned_pages = [page]
            for candidate in list(getattr(context, "pages", ()) or ()):
                if candidate is page:
                    continue
                if self._cdp_endpoint is not None:
                    # The embedded provider context is exclusive to this task while ``task_page``
                    # is active. Chromium deliberately removes the opener from ``noopener``
                    # download tabs, so an opener walk can never reclaim those native popup
                    # WebViews. Close every non-primary target in this exclusive context at the
                    # task boundary; the managed host receives WindowCloseRequested and removes
                    # the matching lease-owned popup without ending the reusable provider root.
                    owned_pages.append(candidate)
                    continue
                current = candidate
                seen: set[int] = set()
                while current is not None and id(current) not in seen:
                    seen.add(id(current))
                    opener = getattr(current, "opener", None)
                    try:
                        current = opener() if callable(opener) else None
                    except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                        current = None
                    if current is page:
                        owned_pages.append(candidate)
                        break
            closable_pages = [
                owned for owned in owned_pages if owned is not page or task_opened_page
            ]
            for owned in reversed(closable_pages):
                try:
                    owned.close()
                except Exception:  # noqa: BLE001 - teardown is best effort
                    pass
            owned_ids = {id(owned) for owned in owned_pages} | {id(original_page)}
            with self._download_lock:
                self._page_brokers = [
                    (wired, bound)
                    for wired, bound in self._page_brokers
                    if id(wired) not in owned_ids
                ]
                self._page_huds = (
                    [
                        (wired, bound)
                        for wired, bound in self._page_huds
                        if bound is not hud_state and id(wired) not in owned_ids
                    ]
                    if hud_state is not None
                    else [
                        (wired, bound)
                        for wired, bound in self._page_huds
                        if id(wired) not in owned_ids
                    ]
                )
                self._wired_pages = [
                    wired for wired in self._wired_pages if id(wired) not in owned_ids
                ]
                if self._embedded_active_generation == embedded_generation:
                    self._embedded_active_generation = 0

    def ensure_connected(self, page) -> None:
        """Reconnect a CDP page after another provider temporarily detached the shared runtime."""

        if self._cdp_endpoint is None or self._playwright_runtime is None:
            return
        if (
            self._context is not None
            and self._runtime_generation == self._playwright_runtime.generation
        ):
            return
        self._reconnect_cdp_page(page)

    def navigate_provider(
        self,
        page,
        url: str,
        *,
        wait_until: str = "domcontentloaded",
        detached: bool = False,
        ready_selectors: tuple[str, ...] = (),
        ready_texts: tuple[str, ...] = (),
        timeout_s: float = 120.0,
    ) -> None:
        """Navigate a provider page, optionally with CDP fully detached.

        Some security providers treat an attached CDP client as the bot signal even when the
        visible WebView, profile, and person are otherwise trusted.  For those reviewed routes the
        native Stockroom WebView performs only the top-level navigation while Playwright is
        disconnected.  Stockroom polls booleans for document readiness, provider readiness, and a
        visible security gate; it reconnects only after the real provider page is ready.
        """

        _validate_capture_url(url)
        raw = _raw_page(page)
        native_navigate = getattr(self._native_surface, "navigate", None)
        native_state = getattr(self._native_surface, "document_state", None)
        show = getattr(self._native_surface, "show", None)
        if (
            not detached
            or self._cdp_endpoint is None
            or self._playwright_runtime is None
            or not callable(native_navigate)
            or not callable(native_state)
        ):
            raw.goto(url, wait_until=wait_until)
            return

        timeout = _bounded_seconds(timeout_s, "timeout_s", maximum=600.0)
        broker = self._broker_for_page(raw)
        hud_state = self._hud_for_page(raw)
        if callable(show):
            show()
        trace(
            "capture.navigation.detached",
            provider=self.provider_key or "",
            url=url_note(url),
            ready_selectors=len(ready_selectors),
            ready_texts=len(ready_texts),
            timeout_s=timeout,
        )
        self._playwright_runtime.close()
        with self._download_lock:
            self._context = None
            self._browser = None
        native_navigate(url)

        deadline = time.monotonic() + timeout
        ready_polls = 0
        ready = False
        challenge_seen = False
        provider_error = False
        while time.monotonic() < deadline:
            try:
                state = native_state(
                    ready_selectors=tuple(ready_selectors),
                    ready_texts=tuple(ready_texts),
                )
            except Exception:  # noqa: BLE001 - a navigating document is temporarily unreadable
                state = {
                    "ready": False,
                    "challenge": True,
                    "provider_ready": False,
                }
            challenge = bool(state.get("challenge"))
            if bool(state.get("provider_error")):
                provider_error = True
                trace(
                    "capture.navigation.provider-error",
                    provider=self.provider_key or "",
                    url=url_note(url),
                )
                break
            if challenge and not challenge_seen:
                challenge_seen = True
                trace(
                    "capture.navigation.security",
                    provider=self.provider_key or "",
                    url=url_note(url),
                    visible=True,
                )
            if bool(state.get("ready")) and bool(state.get("provider_ready")) and not challenge:
                ready_polls += 1
                if ready_polls >= 3:
                    ready = True
                    break
            else:
                ready_polls = 0
            time.sleep(0.25)

        reconnect_error: Exception | None = None
        try:
            self._reconnect_cdp_page(page, broker=broker, hud_state=hud_state)
        except Exception as exc:  # noqa: BLE001 - report the readiness failure first when present
            reconnect_error = exc
        trace(
            "capture.navigation.reconnected",
            provider=self.provider_key or "",
            url=url_note(url),
            ready=ready,
            challenge_seen=challenge_seen,
            reconnected=reconnect_error is None,
        )
        if provider_error:
            raise ProviderPageTerminalError(
                "the embedded provider reported a terminal page error before its CAD controls loaded"
            )
        if not ready:
            raise CaptureBrowserError(
                "the embedded provider page did not become ready before the bounded wait ended"
            )
        if reconnect_error is not None:
            raise CaptureBrowserError(
                "the embedded provider page became ready but automation could not reconnect"
            ) from reconnect_error

    def _reconnect_cdp_page(self, page, *, broker=None, hud_state=None):
        if self._playwright_runtime is None or self._cdp_endpoint is None:
            raise CaptureBrowserError("the embedded provider page cannot be reconnected")
        pw = self._playwright_runtime.get()
        context, browser = self._launch_playwright(pw)
        pages = [candidate for candidate in context.pages if not _page_is_closed(candidate)]
        candidates = [
            candidate
            for candidate in pages
            if not _page_url(candidate, "").casefold().startswith("edge://")
        ]
        if candidates:
            replacement = _native_surface_page(candidates, self._native_surface) or candidates[0]
        elif pages:
            replacement = pages[0]
        else:
            replacement = context.new_page()
        with self._download_lock:
            self._context = context
            self._browser = browser
            self._runtime_generation = self._playwright_runtime.generation
            self._wired_pages.clear()
            self._page_brokers.clear()
            self._page_huds.clear()
        context.on("page", self._wire_downloads)
        self._wire_downloads(replacement)
        if broker is not None:
            with self._download_lock:
                self._page_brokers.append((replacement, broker))
        if hud_state is not None:
            try:
                self._bind_provider_hud(replacement, hud_state)
            except CaptureBrowserError:
                # The pre-detach bootstrap can remain in the live document. A duplicate binding
                # is cosmetic; task ownership and intercepted bytes are restored above.
                pass
        if isinstance(page, _ReconnectablePage):
            page.replace(replacement)
        return replacement

    def _detach_until_security_clears(
        self,
        page,
        *,
        should_cancel: Callable[[], bool] | None,
        timeout: float,
        poll: float,
    ) -> bool:
        """Leave a visible WebView security page running with no Playwright connection."""

        native_state = getattr(self._native_surface, "security_state", None)
        show = getattr(self._native_surface, "show", None)
        if (
            self._cdp_endpoint is None
            or self._playwright_runtime is None
            or not callable(native_state)
        ):
            return False
        raw = _raw_page(page)
        broker = self._broker_for_page(raw)
        hud_state = self._hud_for_page(raw)
        if callable(show):
            show()
        # Stopping the Playwright manager closes only its protocol transport. The WebView2 process,
        # profile, visible page, and human input remain owned by Stockroom's native host.
        self._playwright_runtime.close()
        with self._download_lock:
            self._context = None
            self._browser = None
        deadline = time.monotonic() + timeout
        clear_polls = 0
        cleared = False
        account_verification = False
        while time.monotonic() < deadline:
            if should_cancel is not None and should_cancel():
                break
            try:
                state = native_state()
            except Exception:  # noqa: BLE001 - navigation stays blocked until readable
                state = {"ready": False, "challenge": True}
            if bool(state.get("account_verification")):
                # A transient security challenge can become a durable account restriction only
                # after a provider download click. Do not spend the remaining capture timeout on
                # a gate that requires the account owner to enter a phone number and one-time code.
                account_verification = True
                trace(
                    "capture.security.account-verification",
                    provider=self.provider_key or "",
                )
                break
            if bool(state.get("ready")) and not bool(state.get("challenge")):
                clear_polls += 1
                if clear_polls >= 3:
                    cleared = True
                    break
            else:
                clear_polls = 0
            time.sleep(poll)
        if not account_verification:
            try:
                self._reconnect_cdp_page(page, broker=broker, hud_state=hud_state)
            except Exception:
                if cleared:
                    raise
        return cleared

    def wait_for_user_clearance(
        self,
        page,
        *,
        provider_label: str,
        manufacturer: str,
        mpn: str,
        message: str,
        issue_detector: Callable[[], str],
        author_route: str | None = None,
        should_cancel: Callable[[], bool] | None = None,
        cancel_workflow: Callable[[], None] | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.25,
    ) -> bool:
        """Show a Stockroom HUD while the person clears authentication or a security control.

        The detector observes only whether a gate remains. This method never locates, fills, clicks,
        or submits any provider element. The HUD is registered for future documents before it is
        mounted on the current one, so an SSO or 2FA navigation retains the handoff. Once cleared,
        the binding returns inactive and later automation navigations cannot remount stale guidance.
        For as long as the gate stands, this task's provider HUD also draws no control outline.
        """

        for value, label in (
            (provider_label, "provider_label"),
            (manufacturer, "manufacturer"),
            (mpn, "mpn"),
            (message, "message"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{label} must be exact non-empty text")
        if author_route is None:
            author_route = provider_label
        if (
            type(author_route) is not str
            or not author_route
            or author_route != author_route.strip()
        ):
            raise ValueError("author_route must be exact non-empty text")
        if not callable(issue_detector):
            raise TypeError("issue_detector must be callable")
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("should_cancel must be callable")
        if cancel_workflow is not None and not callable(cancel_workflow):
            raise TypeError("cancel_workflow must be callable")
        timeout = _bounded_seconds(timeout_s, "timeout_s", maximum=3600.0)
        poll = _bounded_seconds(poll_interval_s, "poll_interval_s", maximum=1.0)

        try:
            current_issue = issue_detector() or ""
            readable = True
        except Exception:  # noqa: BLE001 - unreadable gate stays blocked and visible
            current_issue = message
            readable = False
        trace(
            "capture.clearance.wait",
            provider=provider_label,
            author_route=author_route,
            gate_present=bool(current_issue),
            detector_readable=readable,
            timeout_s=timeout,
            why=current_issue,
        )
        if not current_issue:
            return True

        # A page that needs a person is not a page Stockroom points at. While this gate
        # stands, the provider HUD bound to this task draws no control outline at all, so
        # `user_clearance_issue` stays the single detector behind that decision.
        with self._provider_hud_security_hold(page):
            namespace = f"__stockroom_security_handoff_{secrets.token_hex(12)}"
            state_binding = f"__stockroom_security_state_{secrets.token_hex(12)}"
            action_binding = f"__stockroom_security_action_{secrets.token_hex(12)}"
            state_token = secrets.token_hex(24)
            action_token = secrets.token_hex(24)
            cancel_requested = False
            state: dict[str, object] = {
                "active": True,
                "providerLabel": provider_label,
                "authorRoute": author_route,
                "manufacturer": manufacturer,
                "mpn": mpn,
                "message": current_issue,
                "sessionPersistent": self.persistent_digikey_session,
            }

            def provide_state(_source, token) -> dict[str, object]:
                if type(token) is not str or not secrets.compare_digest(token, state_token):
                    return {"active": False}
                return dict(state)

            def receive_action(_source, action, token) -> bool:
                nonlocal cancel_requested
                if (
                    action not in {"hide", "cancel"}
                    or type(token) is not str
                    or not secrets.compare_digest(token, action_token)
                ):
                    return False
                if action == "hide":
                    self._defer_native_surface_hide()
                    return True
                cancel_requested = True
                if cancel_workflow is not None:
                    cancel_workflow()
                return True

            payload = {
                "namespace": namespace,
                "stateBinding": state_binding,
                "stateToken": state_token,
                "actionBinding": action_binding,
                "actionToken": action_token,
            }
            bootstrap = (
                f"({_HANDOFF_HUD_BOOTSTRAP})("
                f"{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"
                ");"
            )
            try:
                page.expose_binding(state_binding, provide_state)
                page.expose_binding(action_binding, receive_action)
                page.add_init_script(bootstrap)
                page.evaluate(_HANDOFF_HUD_BOOTSTRAP, payload)
            except Exception as exc:  # noqa: BLE001 - a hidden handoff is not a safe handoff
                state["active"] = False
                raise CaptureBrowserError(
                    "could not show the Stockroom security handoff before pausing automation"
                ) from exc

            if (
                self._cdp_endpoint is not None
                and self._playwright_runtime is not None
                and callable(getattr(self._native_surface, "security_state", None))
            ):
                cleared = self._detach_until_security_clears(
                    page,
                    should_cancel=should_cancel,
                    timeout=timeout,
                    poll=poll,
                )
                state["active"] = False
                try:
                    page.evaluate(_HANDOFF_HUD_DISMISS, namespace)
                except Exception:  # noqa: BLE001 - a provider navigation may remove the HUD
                    pass
                trace(
                    "capture.clearance.result",
                    provider=provider_label,
                    cleared=cleared,
                    ended="native-gate-gone" if cleared else "native-gate-not-cleared",
                )
                return cleared

            deadline = time.monotonic() + timeout
            last_issue = current_issue
            while time.monotonic() < deadline:
                provider_hud = self._hud_for_page(page)
                if provider_hud is not None and provider_hud.action == "cancel":
                    cancel_requested = True
                    if cancel_workflow is not None:
                        cancel_workflow()
                if cancel_requested:
                    state["active"] = False
                    try:
                        page.evaluate(_HANDOFF_HUD_DISMISS, namespace)
                    except Exception:  # noqa: BLE001 - the return request is authoritative
                        pass
                    trace(
                        "capture.clearance.result",
                        provider=provider_label,
                        cleared=False,
                        ended="returned-to-stockroom",
                    )
                    return False
                if should_cancel is not None and should_cancel():
                    state["active"] = False
                    try:
                        page.evaluate(_HANDOFF_HUD_DISMISS, namespace)
                    except Exception:  # noqa: BLE001 - cancellation is already authoritative
                        pass
                    trace(
                        "capture.clearance.result",
                        provider=provider_label,
                        cleared=False,
                        ended="cancelled",
                    )
                    return False
                if _page_is_closed(page):
                    state["active"] = False
                    trace(
                        "capture.clearance.result",
                        provider=provider_label,
                        cleared=False,
                        ended="page-closed",
                    )
                    return False
                try:
                    issue = issue_detector() or ""
                except Exception:  # noqa: BLE001 - navigation can temporarily make the page unreadable
                    issue = last_issue
                if not issue:
                    state["active"] = False
                    try:
                        page.evaluate(_HANDOFF_HUD_DISMISS, namespace)
                    except Exception:  # noqa: BLE001 - navigation may already have removed the document
                        pass
                    trace(
                        "capture.clearance.result",
                        provider=provider_label,
                        cleared=True,
                        ended="gate-gone",
                    )
                    return True
                if issue != last_issue:
                    last_issue = issue
                    trace_debug(
                        "capture.clearance.changed",
                        provider=provider_label,
                        why=issue,
                    )
                    state["message"] = issue
                    try:
                        page.evaluate(
                            _HANDOFF_HUD_UPDATE,
                            {"namespace": namespace, "message": issue},
                        )
                    except Exception:  # noqa: BLE001 - the init script remounts after navigation
                        pass
                page.wait_for_timeout(max(1, int(poll * 1000)))

            state["active"] = False
            try:
                page.evaluate(_HANDOFF_HUD_DISMISS, namespace)
            except Exception:  # noqa: BLE001 - timeout is already the authoritative outcome
                pass
            trace(
                "capture.clearance.result",
                provider=provider_label,
                cleared=False,
                ended="timed-out",
                timeout_s=timeout,
                why=last_issue,
            )
            return False

    def capture_user_downloads(
        self,
        url: str,
        broker: DownloadBroker,
        *,
        hud: ProviderHudSpec | None = None,
        should_finish: Callable[[], bool] | None = None,
        should_cancel: Callable[[], bool] | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.1,
        settle_seconds: float = 0.75,
        auto_finish_seconds: float = 2.0,
        auto_finish_idle_seconds: float = 25.0,
        retryable_render_issue: Callable[[object], str] | None = None,
        max_render_reloads: int = 0,
        render_reload_delay_seconds: float = 5.0,
    ) -> UserCaptureResult:
        """Open one provider page and observe downloads while the person controls it.

        This is deliberately a small browser lifecycle, not a generic provider driver. Production code
        wires the task-bound download handler and optional Stockroom HUD *before* navigation, opens
        exactly ``url``, pumps Playwright, and observes only explicit HUD/caller actions, page
        closure, or timeout. The HUD is a closed-shadow, top-layer Stockroom surface whose exact
        identity, required-file labels, and guidance text come only from Stockroom's own data.

        THE PROVIDER-DOM CONTRACT, narrowed deliberately by the owner rather than dropped
        The HUD may ask the provider document exactly ONE class of question: WHERE a control it
        already knows about is - an element's bounding box and whether it is visible - so it can
        draw a Stockroom-owned outline over it. That is the entire allowance. Neither Python nor
        that surface reads, collects, stores, transmits, or returns page text, markup, attribute
        values, form values, credentials, prices, or any other page CONTENT; a rect is not content,
        and that distinction is the whole basis for this being acceptable. Nothing here clicks,
        focuses, scrolls, fills, selects a result or format, accepts terms, or otherwise operates
        any provider control - the person performs every interaction. Selectors come only from
        measured per-provider hints, a hint that does not match exactly one visible element draws
        nothing at all, and a page showing a challenge, CAPTCHA, or sign-in draws nothing at all
        and defers to the existing person-handoff.

        ``should_finish`` remains a caller-owned completion signal beside the HUD's Finish button.
        Capture finishes automatically once every file ``hud`` declares required has landed and a
        bounded quiet period passes; the quiet period resets for every companion file. A capture
        still missing a required format keeps waiting for the person, because finishing on the
        first file truncates multi-asset providers and the partial set is then rejected downstream.
        A provider that packs every required format into one archive completes after the normal
        quiet period because completion is classified from that archive's contents. An incomplete
        first package never completes merely because it has been idle; that would cut off a later
        complementary KiCad or Altium package. Closing the page also completes the session. Try
        Another Provider, cancellation, and timeout return every file already intercepted;
        staging never depends on a second click.
        """

        if type(broker) is not DownloadBroker:
            raise TypeError("broker must be a DownloadBroker")
        if hud is not None:
            if type(hud) is not ProviderHudSpec:
                raise TypeError("hud must be a ProviderHudSpec")
            if (
                hud.manufacturer != broker.task.manufacturer_key
                or hud.mpn != broker.task.mpn_canonical
            ):
                raise CaptureBrowserError(
                    "provider HUD identity must exactly match its bound download task"
                )
        _validate_capture_url(url)
        for callback, label in (
            (should_finish, "should_finish"),
            (should_cancel, "should_cancel"),
            (retryable_render_issue, "retryable_render_issue"),
        ):
            if callback is not None and not callable(callback):
                raise TypeError(f"{label} must be callable")
        timeout = _bounded_seconds(timeout_s, "timeout_s", maximum=3600.0)
        poll_interval = _bounded_seconds(
            poll_interval_s,
            "poll_interval_s",
            maximum=1.0,
        )
        settle = _bounded_seconds(
            settle_seconds,
            "settle_seconds",
            maximum=30.0,
            allow_zero=True,
        )
        trace(
            "capture.user-window.open",
            provider=self.provider_key,
            url=url_note(url),
            task=broker.task.task_id,
            required=list(hud.required_file_labels) if hud is not None else [],
            timeout_s=timeout,
        )
        auto_finish = _bounded_seconds(
            auto_finish_seconds,
            "auto_finish_seconds",
            maximum=30.0,
            allow_zero=True,
        )
        _bounded_seconds(
            auto_finish_idle_seconds,
            "auto_finish_idle_seconds",
            maximum=600.0,
            allow_zero=True,
        )
        if type(max_render_reloads) is not int or not 0 <= max_render_reloads <= 2:
            raise ValueError("max_render_reloads must be between zero and two")
        render_reload_delay = _bounded_seconds(
            render_reload_delay_seconds,
            "render_reload_delay_seconds",
            maximum=30.0,
            allow_zero=True,
        )
        # The HUD carries the stable format keys corresponding to its human labels. Completion is
        # classified from the downloaded bytes, never inferred from archive count.
        required_formats = hud.required_formats if hud is not None else ()

        deadline = time.monotonic() + timeout
        status: UserCaptureStatus = "timed_out"
        final_url = url
        error_mark = len(self.download_errors)
        hud_state = (
            _ProviderHudState(hud, self.persistent_digikey_session) if hud is not None else None
        )
        if hud_state is not None:
            receipts = broker.receipts
            hud_state.update_download_count(
                len(receipts),
                _completed_provider_formats(receipts, required_formats),
            )

        embedded_detached_navigation = (
            self._cdp_endpoint is not None
            and self._playwright_runtime is not None
            and callable(getattr(self._native_surface, "navigate", None))
            and callable(getattr(self._native_surface, "document_state", None))
        )

        with (
            _exclusive_user_capture_window(),
            self.task_page(
                broker,
                # Do not register Stockroom's document bootstrap in the destination before a
                # native security gate has run. The broker is still armed first; the HUD is bound
                # immediately after the detached navigation returns and then survives ordinary
                # provider navigations exactly as before.
                hud_state=None if embedded_detached_navigation else hud_state,
            ) as page,
        ):
            show_native_surface = getattr(self._native_surface, "show", None)
            if callable(show_native_surface):
                # A person may return to Stockroom while this provider finalizes. Reusing the
                # browser session must still show the next task-bound route after its broker is
                # armed; visibility is route state, not session-construction state.
                show_native_surface()

            def downloads_are_terminal(_now: float | None = None) -> bool:
                """Seal native intake only when every observed byte stream is idle."""

                return self._finalize_native_downloads_if_idle()

            def drain_navigation_terminal_downloads() -> None:
                """Hold a terminal navigation until its native download edge is quiescent."""

                quiet_period = max(settle, 0.25)
                observed_receipts = len(broker.receipts)
                quiet_until = time.monotonic() + quiet_period
                while True:
                    native_pending, _ = self._drain_native_downloads()
                    now = time.monotonic()
                    current_receipts = len(broker.receipts)
                    if current_receipts != observed_receipts:
                        observed_receipts = current_receipts
                        quiet_until = now + quiet_period
                    if (
                        native_pending == 0
                        and now >= quiet_until
                        and downloads_are_terminal(now)
                    ):
                        return
                    wait_seconds = min(
                        poll_interval,
                        max(0.001, quiet_until - now)
                        if native_pending == 0
                        else poll_interval,
                    )
                    if _page_is_closed(page):
                        time.sleep(wait_seconds)
                    else:
                        page.wait_for_timeout(max(1, int(wait_seconds * 1000)))

            if should_cancel is not None and should_cancel():
                status = "cancelled"
            else:
                navigation_terminal = False
                navigation_terminal_can_download = True
                try:
                    if embedded_detached_navigation:
                        # A person-driven provider route still needs CDP briefly so its exact
                        # task broker and download listener can be armed. Keeping CDP attached
                        # during the first cross-origin navigation can keep DigiKey's Cloudflare
                        # verification on an automation-observable path even after a real person
                        # completes it. Use the same native detached-navigation seam
                        # as the reviewed provider adapters, then reconnect only after the gate
                        # is visibly gone. The broker/HUD are rebound to the same native page by
                        # ``navigate_provider`` before this method resumes.
                        self.navigate_provider(
                            page,
                            url,
                            wait_until="commit",
                            detached=True,
                            timeout_s=timeout,
                        )
                    else:
                        page.goto(
                            url,
                            # Provider pages can commit the requested URL and then keep loading
                            # challenge scripts or subresources indefinitely.  Waiting for
                            # DOMContentLoaded prevented Stockroom from observing Finish Route
                            # (and manually selected files) until the full capture timeout elapsed.
                            wait_until="commit",
                            # Initial navigation is advisory: the task-bound picker and HUD remain
                            # useful even when a provider challenge never commits a document. Keep
                            # the overall route timeout for the polling loop, not this blocking call.
                            timeout=max(1, int(min(timeout, 10.0) * 1000)),
                        )
                except Exception as exc:  # noqa: BLE001 - recovery remains available off-page
                    final_url = _page_url(page, url)
                    hud_action = hud_state.action if hud_state is not None else None
                    if isinstance(exc, ProviderPageTerminalError):
                        # A known provider error document cannot become useful by continuing to
                        # poll it. Advance to the next independent author route immediately; the
                        # manual picker remains available from Stockroom outside this dead page.
                        status = "try_another"
                        navigation_terminal = True
                        navigation_terminal_can_download = False
                    elif should_cancel is not None and should_cancel():
                        status = "cancelled"
                        navigation_terminal = True
                    elif hud_action == "cancel":
                        status = "cancelled"
                        navigation_terminal = True
                    elif hud_action == "try_another":
                        status = "try_another"
                        navigation_terminal = True
                    elif should_finish is not None and should_finish():
                        # The application may already have task-bound files queued for this
                        # route.  Navigation failure must not strand that explicit handoff.
                        status = "completed"
                        navigation_terminal = True
                    elif hud_action == "finish":
                        status = "completed"
                        navigation_terminal = True
                    elif broker.receipts:
                        # Navigation can be aborted by the provider as the download response
                        # replaces or closes the document. Completed task-bound receipts are
                        # authoritative and must still advance to ingestion.
                        status = "completed"
                        navigation_terminal = True
                    elif _page_is_closed(page):
                        status = "completed"
                        navigation_terminal = True
                    elif time.monotonic() >= deadline:
                        status = "timed_out"
                        navigation_terminal = True
                    else:
                        # Network errors, challenge loops, and pages that never commit must not
                        # disable Stockroom's own picker. Continue polling the task-bound intent;
                        # the person can provide already-downloaded files, cancel, or try another
                        # author route without waiting for the provider page lifecycle.
                        trace_warning(
                            "capture.user-window.navigation-pending",
                            provider=self.provider_key,
                            url=url_note(final_url),
                            why=str(exc),
                        )
                finally:
                    if embedded_detached_navigation and hud_state is not None:
                        self._bind_provider_hud(_raw_page(page), hud_state)
                final_url = _page_url(page, final_url)
                if navigation_terminal and navigation_terminal_can_download:
                    drain_navigation_terminal_downloads()
                if not navigation_terminal:
                    receipt_count = len(broker.receipts)
                    completed_formats = _completed_provider_formats(
                        broker.receipts,
                        required_formats,
                    )
                    if hud_state is not None:
                        self._update_provider_hud(
                            hud_state,
                            receipt_count,
                            completed_formats,
                        )
                    quiet_since = time.monotonic()
                    finish_requested = False
                    render_reloads = 0
                    next_render_check = quiet_since + render_reload_delay
                    requested_status: UserCaptureStatus | None = None
                    requested_at: float | None = None
                    while True:
                        native_pending, _ = self._drain_native_downloads()
                        errors = self.download_errors
                        if len(errors) > error_mark:
                            # A failing companion does not invalidate files already staged.
                            # Raising here discarded them along with the result object, so a
                            # partially successful capture reported nothing at all. Surface the
                            # failure only when there is genuinely nothing to hand back; the
                            # error stays readable on the browser for diagnostics, and
                            # downstream verification judges whether the set is complete.
                            if not broker.receipts:
                                raise errors[error_mark]
                            if downloads_are_terminal():
                                status = "completed"
                                break
                            continue

                        now = time.monotonic()
                        current_count = len(broker.receipts)
                        if current_count != receipt_count:
                            receipt_count = current_count
                            completed_formats = _completed_provider_formats(
                                broker.receipts,
                                required_formats,
                            )
                            quiet_since = now
                        if hud_state is not None:
                            # This cheap Stockroom-namespace update also restores the current count
                            # after an in-page navigation remounts the init-script HUD.
                            self._update_provider_hud(
                                hud_state,
                                current_count,
                                completed_formats,
                            )

                        if should_cancel is not None and should_cancel():
                            requested_status = "cancelled"
                        hud_action = hud_state.action if hud_state is not None else None
                        if hud_action == "cancel":
                            requested_status = "cancelled"
                        elif hud_action == "try_another":
                            requested_status = "try_another"
                        if requested_status is not None:
                            requested_at = requested_at or now
                            # The host can accept a download just before its event reaches this
                            # ledger. Give that event one bounded settle window before sealing a
                            # zero-receipt route.
                            if (
                                self._has_native_download_ledger
                                and current_count == 0
                                and now - requested_at < max(settle, 0.25)
                            ):
                                wait_seconds = min(
                                    poll_interval,
                                    max(settle, 0.25) - (now - requested_at),
                                )
                                if _page_is_closed(page):
                                    time.sleep(wait_seconds)
                                else:
                                    page.wait_for_timeout(max(1, int(wait_seconds * 1000)))
                                continue
                            if native_pending == 0 and downloads_are_terminal(now):
                                status = requested_status
                                break
                            if now - requested_at >= 30.0:
                                # The native operation can become READY after this iteration's
                                # initial snapshot. Drain once more at the exact cutoff so lease
                                # teardown cannot delete a ZIP that finished before we returned.
                                if downloads_are_terminal(now):
                                    status = requested_status
                                    break
                                # A route is not terminal while WebView2 still owns bytes. Keep
                                # the durable item draining instead of returning a receipt snapshot
                                # that cannot include this operation.
                                if _page_is_closed(page):
                                    time.sleep(poll_interval)
                                else:
                                    page.wait_for_timeout(max(1, int(poll_interval * 1000)))
                                continue
                            remaining = min(deadline - now, 30.0 - (now - requested_at))
                            if remaining <= 0:
                                if downloads_are_terminal(now):
                                    status = requested_status
                                    break
                                if _page_is_closed(page):
                                    time.sleep(poll_interval)
                                else:
                                    page.wait_for_timeout(max(1, int(poll_interval * 1000)))
                                continue
                            wait_seconds = min(poll_interval, remaining)
                            if _page_is_closed(page):
                                time.sleep(wait_seconds)
                            else:
                                page.wait_for_timeout(max(1, int(wait_seconds * 1000)))
                            continue
                        native_security_state = getattr(
                            self._native_surface,
                            "security_state",
                            None,
                        )
                        if (
                            self._cdp_endpoint is not None
                            and self._playwright_runtime is not None
                            and callable(native_security_state)
                        ):
                            try:
                                security_state = native_security_state()
                            except Exception:  # noqa: BLE001 - unreadable is not a gate verdict
                                security_state = {}
                            if bool(security_state.get("challenge")):
                                # DigiKey can present another Turnstile step after a person clicks
                                # Sign In. Continuing to poll it with CDP attached makes a valid
                                # completion restart. Drop the transport for the whole visible
                                # gate, preserve the native page/profile, then restore this exact
                                # task's download binding after it clears.
                                trace(
                                    "capture.user-window.security-detach",
                                    provider=self.provider_key or "",
                                    url=url_note(_page_url(page, final_url)),
                                )
                                if bool(security_state.get("account_verification")):
                                    # A provider-owned account restriction is not a transient
                                    # CAPTCHA. Waiting the entire ten-minute person-capture window
                                    # cannot clear it without the account owner entering a phone
                                    # number and one-time code. Leave that native page visible,
                                    # detach automation immediately, and let the guided layer turn
                                    # its exact final URL into a resumable blocked verdict.
                                    native_current_url = getattr(
                                        self._native_surface,
                                        "current_url",
                                        None,
                                    )
                                    if callable(native_current_url):
                                        try:
                                            final_url = native_current_url() or final_url
                                        except Exception:  # noqa: BLE001 - stale URL is advisory
                                            final_url = _page_url(page, final_url)
                                    self._playwright_runtime.close()
                                    with self._download_lock:
                                        self._context = None
                                        self._browser = None
                                    trace(
                                        "capture.user-window.account-verification",
                                        provider=self.provider_key or "",
                                        url=url_note(final_url),
                                    )
                                    requested_status = "timed_out"
                                    requested_at = requested_at or now
                                    if downloads_are_terminal(now):
                                        status = "timed_out"
                                        break
                                    time.sleep(min(poll_interval, max(0.001, deadline - now)))
                                    continue
                                cleared = self._detach_until_security_clears(
                                    page,
                                    should_cancel=should_cancel,
                                    timeout=max(0.001, deadline - now),
                                    poll=poll_interval,
                                )
                                native_current_url = getattr(
                                    self._native_surface,
                                    "current_url",
                                    None,
                                )
                                if callable(native_current_url):
                                    try:
                                        final_url = native_current_url() or final_url
                                    except Exception:  # noqa: BLE001 - stale URL is advisory
                                        final_url = _page_url(page, final_url)
                                else:
                                    final_url = _page_url(page, final_url)
                                if not cleared:
                                    status = (
                                        "cancelled"
                                        if should_cancel is not None and should_cancel()
                                        else "timed_out"
                                    )
                                    requested_status = status
                                    requested_at = requested_at or now
                                    if downloads_are_terminal(now):
                                        break
                                    continue
                                continue
                        if _page_is_closed(page) and downloads_are_terminal(now):
                            status = "completed"
                            break
                        if should_finish is not None and should_finish():
                            finish_requested = True
                        if hud_action == "finish":
                            finish_requested = True
                        if (
                            retryable_render_issue is not None
                            and current_count == 0
                            and render_reloads < max_render_reloads
                            and now >= next_render_check
                        ):
                            try:
                                render_issue = str(retryable_render_issue(page) or "")
                            except Exception:  # noqa: BLE001 - unreadable state cannot trigger reload
                                render_issue = ""
                            if render_issue:
                                render_reloads += 1
                                trace(
                                    "capture.user-window.render-reload",
                                    provider=self.provider_key,
                                    attempt=render_reloads,
                                    of=max_render_reloads,
                                    why=render_issue,
                                )
                                try:
                                    page.reload(
                                        wait_until="commit",
                                        timeout=max(1, int(min(timeout, 10.0) * 1000)),
                                    )
                                except Exception as exc:  # noqa: BLE001 - polling/picker stay usable
                                    trace_warning(
                                        "capture.user-window.render-reload-pending",
                                        provider=self.provider_key,
                                        attempt=render_reloads,
                                        why=str(exc),
                                    )
                                final_url = _page_url(page, final_url)
                                next_render_check = time.monotonic() + render_reload_delay
                                continue
                            next_render_check = now + render_reload_delay
                        if (
                            finish_requested
                            and native_pending == 0
                            and (current_count == 0 or now - quiet_since >= settle)
                            and downloads_are_terminal(now)
                        ):
                            status = "completed"
                            break
                        if (
                            current_count > 0
                            and native_pending == 0
                            and now - quiet_since >= auto_finish
                            and set(required_formats) <= set(completed_formats)
                            and downloads_are_terminal(now)
                        ):
                            status = "completed"
                            break
                        if now >= deadline:
                            # Timeout is a terminal capture boundary, not permission to discard a
                            # native download that completed since the poll at the top of the loop.
                            if downloads_are_terminal(now):
                                status = "timed_out"
                                break
                            if _page_is_closed(page):
                                time.sleep(poll_interval)
                            else:
                                page.wait_for_timeout(max(1, int(poll_interval * 1000)))
                            continue

                        remaining = deadline - now
                        wait_ms = max(1, int(min(poll_interval, remaining) * 1000))
                        try:
                            page.wait_for_timeout(wait_ms)
                        except Exception:
                            if _page_is_closed(page):
                                if downloads_are_terminal():
                                    status = "completed"
                                    break
                                time.sleep(wait_ms / 1000.0)
                                continue
                            raise
                        final_url = _page_url(page, final_url)

        return UserCaptureResult(
            status=status,
            files=broker.receipts,
            final_url=final_url,
        )

    @contextmanager
    def session(self):
        """Open a browser, yield a page, and always tear it down.

        Yields the Playwright `Page`. Downloads that land during the session are saved into
        `download_dir` and recorded on `self.captured` - saved EAGERLY, because Playwright deletes
        a context's downloads when the context closes, so a file only "arrived" once it is copied
        out of the temp area.
        """
        lock = (
            ProviderProfileLock(self.profile_dir, self.provider_key)
            if self.profile_dir is not None and self.provider_key is not None
            else None
        )
        if lock is not None:
            lock.acquire()
        try:
            if self._playwright_runtime is not None:
                with self._playwright_session(self._playwright_runtime.get()) as page:
                    yield page
                return

            try:
                from playwright.sync_api import sync_playwright
            except ImportError as exc:  # pragma: no cover - dependency is declared
                raise CaptureBrowserError(
                    "playwright is not installed; it is a declared dependency, run `uv sync`"
                ) from exc
            with sync_playwright() as pw, self._playwright_session(pw) as page:
                yield page
        finally:
            if lock is not None:
                lock.release()

    @contextmanager
    def _playwright_session(self, pw):
        context = None
        browser = None
        try:
            context, browser = self._launch_playwright(pw)
            with self._download_lock:
                self._context = context
                self._browser = browser
                self._runtime_generation = (
                    self._playwright_runtime.generation
                    if self._playwright_runtime is not None
                    else 0
                )
            context.on("page", self._wire_downloads)
            page = context.pages[0] if context.pages else context.new_page()
            self._wire_downloads(page)
            yield _ReconnectablePage(page) if self._cdp_endpoint is not None else page
        finally:
            closables = () if self._cdp_endpoint is not None else (context, browser)
            for closable in closables:
                if closable is not None:
                    try:
                        closable.close()
                    except Exception:  # noqa: BLE001 - teardown is best effort
                        pass
            with self._download_lock:
                self._context = None
                self._browser = None
                self._page_brokers.clear()
                self._page_huds.clear()
                self._wired_pages.clear()

    def _launch_playwright(self, pw):
        """Launch the requested browser policy and return ``(context, browser)``.

        ``windows`` is a deterministic policy, not an alias for bundled Chromium: prefer the
        preferred browser already managed on this machine (Chrome), then Stockroom's pinned
        Playwright Chromium. A failed candidate is fully discarded before the next one is
        attempted.
        """

        if self._cdp_endpoint is not None:
            try:
                browser = pw.chromium.connect_over_cdp(
                    self._cdp_endpoint,
                    timeout=_BROWSER_LAUNCH_TIMEOUT_MS,
                )
                contexts = list(browser.contexts)
                if not contexts:
                    raise CaptureBrowserError("the embedded provider browser exposed no context")
                self.launched_browser = "Stockroom Embedded WebView2"
                context = contexts[0]
                # This is the person's already-running native WebView, not a browser process
                # Stockroom launched for automation. Rewriting RTCPeerConnection across its
                # future documents changes the browser fingerprint before a Cloudflare gate and
                # can invalidate an otherwise legitimate human verification. Standalone capture
                # contexts retain the firewall-safe WebRTC guard below; the embedded browser must
                # keep its native web-platform surface intact.
                return context, browser
            except Exception as exc:
                detail = (
                    str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                )
                raise CaptureBrowserError(
                    f"could not attach to Stockroom's embedded provider browser: {detail}"
                ) from exc

        candidates = _browser_candidates(self.engine)
        failures: list[str] = []
        for candidate in candidates:
            engine = getattr(pw, candidate.browser_type, None)
            if engine is None:
                failures.append(f"{candidate.label}: browser type unavailable")
                continue
            options = {
                "headless": self.headless,
                "accept_downloads": True,
                "timeout": _BROWSER_LAUNCH_TIMEOUT_MS,
            }
            if candidate.channel is not None:
                options["channel"] = candidate.channel
            context = None
            browser = None
            try:
                if self.profile_dir is not None:
                    self.profile_dir.mkdir(parents=True, exist_ok=True)
                    _allow_automatic_downloads(self.profile_dir)
                    context = engine.launch_persistent_context(
                        str(self.profile_dir),
                        **options,
                    )
                else:
                    launch_options = dict(options)
                    launch_options.pop("accept_downloads")
                    browser = engine.launch(**launch_options)
                    context = browser.new_context(accept_downloads=True)
                _disable_webrtc(context)
                self.launched_browser = candidate.label
                return context, browser
            except Exception as exc:  # noqa: BLE001 - each candidate is an independent fallback
                for closable in (context, browser):
                    if closable is not None:
                        try:
                            closable.close()
                        except Exception:  # noqa: BLE001 - failed-launch teardown is best effort
                            pass
                detail = (
                    str(exc).strip().splitlines()[0] if str(exc).strip() else type(exc).__name__
                )
                failures.append(f"{candidate.label}: {detail}")

        hint = (
            "Install Google Chrome or run `uv run python -m playwright install chromium`."
            if self.engine == "windows"
            else "Run `uv run python -m playwright install chromium` if the bundled browser "
            "is missing."
        )
        raise CaptureBrowserError(f"could not launch {self.engine}: {'; '.join(failures)}. {hint}")

    def _bind_provider_hud(self, page, state: _ProviderHudState) -> None:
        """Install one Stockroom-owned HUD that never reads provider-controlled page content.

        The surface it mounts may ask the document where a measured control sits, so it can draw
        an outline over it, and nothing else. See ``capture_user_downloads`` for the full contract.
        """

        with self._download_lock:
            if any(wired is page for wired, _bound in self._page_huds):
                return

        payload = state.payload()

        def receive_action(_source, action, token) -> bool:
            visibility_only = state.authorizes_visibility_action(action, token)
            accepted = visibility_only or state.request_action(action, token)
            if accepted:
                # A page binding is completing on WebView2's renderer/UI command path. Sending a
                # synchronous native hide command here can deadlock that path: the page waits for
                # this binding to return while the host waits for the page command to finish. Let
                # the binding acknowledge first, then switch the native surface on a worker.
                self._defer_native_surface_hide()
            return accepted

        def provide_state(_source, token) -> dict[str, object]:
            return state.read_state(token)

        init_script = (
            f"({_PROVIDER_HUD_BOOTSTRAP})("
            f"{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"
            ");"
        )
        try:
            if self._cdp_endpoint is not None:
                # The managed host owns CoreWebView2.NewWindowRequested directly. The source
                # pywebview host does not expose that event, so a target=_blank provider link
                # otherwise escapes into Vivaldi/Chrome before a Playwright popup exists. Install
                # this only after detached security navigation has cleared, alongside the HUD.
                page.add_init_script(_EMBEDDED_PROVIDER_NAVIGATION_BOOTSTRAP)
                page.evaluate(_EMBEDDED_PROVIDER_NAVIGATION_BOOTSTRAP)
            page.expose_binding(state.action_binding, receive_action)
            # Bound before the init script that reads it, so a HUD that remounts on the very first
            # provider navigation already has a live count to ask for.
            page.expose_binding(state.state_binding, provide_state)
            # Registration precedes the first provider navigation and runs again for every
            # subsequent document. Evaluating the same idempotent bootstrap mounts it in the
            # existing about:blank document too.
            page.add_init_script(init_script)
            with self._download_lock:
                self._page_huds.append((page, state))
            page.evaluate(_PROVIDER_HUD_BOOTSTRAP, payload)
        except Exception as exc:  # noqa: BLE001 - Playwright implementations vary
            with self._download_lock:
                self._page_huds = [
                    (wired, bound) for wired, bound in self._page_huds if wired is not page
                ]
            raise CaptureBrowserError(
                "could not install the Stockroom capture panel before provider navigation"
            ) from exc

    def _defer_native_surface_hide(self) -> None:
        """Return from a page binding before asking WebView2 to switch native surfaces."""

        hide_native_surface = getattr(self._native_surface, "hide", None)
        if not callable(hide_native_surface):
            return

        def hide() -> None:
            try:
                hide_native_surface()
            except Exception as exc:  # noqa: BLE001 - the native button remains a safe fallback
                trace_warning(
                    "capture.provider-surface.hide-failed",
                    provider=self.provider_key or "",
                    why=str(exc),
                )

        threading.Thread(
            target=hide,
            name="stockroom-provider-surface-hide",
            daemon=True,
        ).start()

    def retain_provider_surface(self) -> bool:
        """Keep the native provider document when this capture ends incomplete."""

        retain = getattr(self._native_surface, "retain", None)
        if not callable(retain):
            return False
        retain()
        return True

    @contextmanager
    def _provider_hud_security_hold(self, page):
        """Suppress this task's control outlines while the person owns a provider gate.

        Reuses the one detection Stockroom already has: whatever decided to call
        ``wait_for_user_clearance`` decides this too. A page with no bound provider HUD simply has
        nothing to suppress, and the hold is always released, including on cancellation and
        timeout, so a cleared gate restores the guidance without a second detector.
        """

        state = self._hud_for_page(_raw_page(page))
        if state is None:
            yield
            return
        state.set_security_hold(True)
        self._update_provider_hud(state, state.download_count)
        try:
            yield
        finally:
            state.set_security_hold(False)
            self._update_provider_hud(state, state.download_count)

    def _update_provider_hud(
        self,
        state: _ProviderHudState,
        download_count: int,
        completed_formats: tuple[str, ...] | None = None,
        *,
        unavailable_formats: tuple[str, ...] | None = None,
    ) -> None:
        """Push Stockroom's receipt count and outline hold into every page showing this HUD."""

        state.update_download_count(download_count, completed_formats, unavailable_formats)
        with self._download_lock:
            pages = [page for page, bound in self._page_huds if bound is state]
        payload = {
            "namespace": state.namespace,
            "downloadCount": download_count,
            "completedFormats": list(state.completed_formats),
            "unavailableFormats": list(state.unavailable_formats),
            "securityHold": state.security_hold,
        }
        for page in pages:
            try:
                page.evaluate(_PROVIDER_HUD_UPDATE, payload)
            except Exception:  # noqa: BLE001 - navigation can replace an execution context
                # The registered init script remounts the HUD; the capture loop retries this
                # Stockroom-namespace update on its next bounded poll.
                pass

    def _drain_native_downloads(
        self,
        *,
        finalize_if_idle: bool = False,
    ) -> tuple[int, bool]:
        """Move host-observed WebView2 files through the exact task broker."""

        self._poll_native_surface_downloads()
        pending = self._drain_native_surface_downloads()
        finalized = pending == 0
        if finalize_if_idle and finalized:
            with self._download_lock:
                generation = self._embedded_active_generation
                if generation > 0:
                    self._embedded_finalized_generations.add(generation)
        return pending, finalized

    def _poll_native_surface_downloads(self) -> None:
        """Reconcile host download events that survive CDP/security detachment."""

        read_events = getattr(self._native_surface, "download_events", None)
        if not callable(read_events):
            return
        try:
            events = tuple(read_events(after_sequence=self._native_download_cursor))
        except Exception as exc:  # noqa: BLE001 - a broken native ledger is a capture failure
            with self._download_lock:
                self._download_errors.append(
                    CaptureBrowserError(
                        "the embedded provider download ledger could not be read "
                        f"({type(exc).__name__})"
                    )
                )
            return
        for event in events:
            sequence = getattr(event, "sequence", None)
            operation_id = str(getattr(event, "operation_id", "") or "")
            phase = str(getattr(event, "phase", "") or "")
            state = str(getattr(event, "state", "") or "")
            if type(sequence) is not int or sequence <= self._native_download_cursor:
                continue
            self._native_download_cursor = sequence
            if not operation_id or phase not in {"started", "terminal"}:
                continue
            result_path = Path(str(getattr(event, "result_file_path", "") or ""))
            suggested_name = _safe_filename(
                str(getattr(event, "suggested_file_name", "") or "cad-download")
            )
            source_url = str(getattr(event, "uri", "") or "")
            with self._download_lock:
                generation = self._embedded_active_generation
                if generation in self._embedded_finalized_generations:
                    generation = 0
                brokers = {id(broker): broker for _page, broker in self._page_brokers}
                broker = next(iter(brokers.values())) if generation > 0 and len(brokers) == 1 else None
                download = self._native_surface_downloads.get(operation_id)
                if download is None:
                    download = _NativeSurfaceDownload(
                        operation_id=operation_id,
                        generation=generation,
                        broker=broker,
                        suggested_name=suggested_name,
                        source_url=source_url,
                        result_path=result_path,
                    )
                    self._native_surface_downloads[operation_id] = download
                if result_path != Path(""):
                    download.result_path = result_path
                if source_url:
                    download.source_url = source_url
                if suggested_name != "cad-download":
                    download.suggested_name = suggested_name
                download.state = state
                if broker is None and download.broker is None:
                    self._download_errors.append(
                        CaptureBrowserError(
                            "the native download began without one exact Stockroom task binding"
                        )
                    )

    def _drain_native_surface_downloads(self) -> int:
        """Adopt terminal host paths when browser-domain events were unavailable."""

        with self._download_lock:
            generation = self._embedded_active_generation
            active = [
                item
                for item in self._native_surface_downloads.values()
                if item.generation == generation and not item.captured
            ]
        pending = sum(item.state in {"in_progress", "unknown"} for item in active)
        for download in active:
            if download.state == "interrupted":
                download.captured = True
                continue
            if download.state != "completed":
                continue
            source = download.result_path
            if not source.is_file() or source.is_symlink() or source.stat().st_size <= 0:
                pending += 1
                continue

            if download.broker is None:
                download.captured = True
                source.unlink(missing_ok=True)
                continue
            try:
                receipt = download.broker.capture_local_file(
                    source,
                    source_url=download.source_url,
                    transport="webview2-native",
                    suggested_filename=download.suggested_name,
                )
                with self._download_lock:
                    download.captured = True
                    if all(captured.path != receipt.path for captured in self._captured):
                        self._captured.append(
                            CapturedFile(
                                path=receipt.path,
                                suggested_name=(
                                    download.suggested_name
                                    if download.suggested_name != "cad-download"
                                    else receipt.suggested_name
                                ),
                                url=receipt.source_url,
                            )
                        )
                trace(
                    "capture.download.saved",
                    provider=self.provider_key or "",
                    via="webview2-native",
                    saved=file_note(receipt.path),
                    path=receipt.path,
                )
            finally:
                source.unlink(missing_ok=True)
        with self._download_lock:
            self._native_surface_downloads = {
                operation_id: item
                for operation_id, item in self._native_surface_downloads.items()
                if not item.captured
            }
        return pending

    def _finalize_native_downloads_if_idle(self) -> bool:
        """Atomically drain and close the native intake only when no byte stream is in flight."""

        pending, finalized = self._drain_native_downloads(finalize_if_idle=True)
        return pending == 0 and finalized

    def _wire_downloads(self, page) -> None:
        with self._download_lock:
            if any(wired is page for wired in self._wired_pages):
                return
            # Keep the object, not id(page): a long-lived browser can collect a closed page and
            # later reuse its numeric id for a new popup. Remembering only the id would silently
            # leave that new page without a download handler.
            self._wired_pages.append(page)

        def record_download(download) -> None:
            try:
                self._on_download(download, page=page)
            except CaptureBrowserError as exc:
                # Event callbacks are a separate control-flow path. Raising here is not observed
                # by the capture wait and used to turn an immediate save failure into a dishonest
                # 120-second "no file arrived" timeout. Keep it for the owning attempt to read.
                with self._download_lock:
                    self._download_errors.append(exc)

        page.on("download", record_download)
        inherited_hud = self._hud_for_page(page)
        if inherited_hud is not None:
            # Context-created popups inherit task ownership through their opener. Binding the same
            # state gives those user-driven pages the same exact identity, actions, and live count.
            self._bind_provider_hud(page, inherited_hud)

    def _broker_for_page(self, page) -> DownloadBroker | None:
        return self._broker_for_page_with_route(page)[0]

    def _broker_for_page_with_route(self, page) -> tuple[DownloadBroker | None, str]:
        """The owning task, AND which of the three paths found it.

        Which path resolved a download's task is exactly the question "the vendor download did
        not produce a file" could never answer: a direct binding, an opener walk, and the
        single-task fallback all end in the same receipt, but only one of them means the provider
        behaved as measured. The route name is diagnostics only - the returned broker is
        unchanged.
        """

        current = _raw_page(page)
        depth = 0
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            with self._download_lock:
                broker = next(
                    (bound for wired, bound in self._page_brokers if wired is current),
                    None,
                )
            if broker is not None:
                return broker, ("direct-binding" if depth == 0 else f"opener-walk({depth})")
            opener = getattr(current, "opener", None)
            try:
                current = opener() if callable(opener) else None
            except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                current = None
            depth += 1
        # Provider download controls routinely open rel="noopener" windows, and Chromium reports
        # no opener for those. The walk above can never reach the task page from one, so the file
        # fell through to the legacy directory, left broker.receipts empty, and surfaced as "the
        # vendor download did not produce a file" while the HUD count stayed at zero. One assisted
        # capture window is exclusive, so a single bound task is unambiguously that file's owner.
        with self._download_lock:
            if len(self._page_brokers) == 1:
                return self._page_brokers[0][1], "single-task-fallback"
        return None, "unbound"

    def _hud_for_page(self, page) -> _ProviderHudState | None:
        current = _raw_page(page)
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            with self._download_lock:
                state = next(
                    (bound for wired, bound in self._page_huds if wired is current),
                    None,
                )
            if state is not None:
                return state
            opener = getattr(current, "opener", None)
            try:
                current = opener() if callable(opener) else None
            except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                current = None
        return None

    def _on_download(self, download, *, page=None) -> None:
        """Save every download the moment it lands, and record where it went.

        Saved eagerly and unconditionally: Playwright removes a context's downloads on close, and
        a capture that reported a file it can no longer read is the exact "said downloaded before
        the file landed" failure the owner called out.
        """
        name = download.suggested_filename or "cad-download"
        broker, route = (
            self._broker_for_page_with_route(page) if page is not None else (None, "no-page")
        )
        trace(
            "capture.download.event",
            provider=self.provider_key,
            file=name,
            broker=broker is not None,
            via=route,
        )
        if self._has_native_download_ledger:
            # Stockroom's host owns this window's downloads and reports them through its own
            # ledger, which stays readable while the protocol connection is detached for a
            # security gate. Draining both would stage the same bytes twice.
            trace(
                "capture.download.deferred",
                provider=self.provider_key,
                file=name,
                via="webview2-native",
            )
            return
        if broker is not None:
            try:
                receipt = broker.capture_playwright(download)
            except DownloadBrokerError as exc:
                trace_warning(
                    "capture.download.refused",
                    provider=self.provider_key,
                    file=name,
                    via=route,
                    why=str(exc),
                )
                raise CaptureBrowserError(str(exc)) from exc
            with self._download_lock:
                if all(captured.path != receipt.path for captured in self._captured):
                    self._captured.append(
                        CapturedFile(
                            path=receipt.path,
                            suggested_name=receipt.suggested_name,
                            url=receipt.source_url,
                        )
                    )
            trace(
                "capture.download.saved",
                provider=self.provider_key,
                via=route,
                saved=file_note(receipt.path),
                path=receipt.path,
            )
            return

        with self._download_lock:
            dest = _unique(self.download_dir, _safe_filename(name))
            try:
                download.save_as(str(dest))
                if not dest.is_file() or dest.stat().st_size <= 0:
                    raise OSError("saved file is missing or empty")
            except Exception as exc:  # noqa: BLE001 - failed download is an honest capture error
                dest.unlink(missing_ok=True)
                failure = getattr(download, "failure", None)
                reason = failure() if callable(failure) else exc
                trace_warning(
                    "capture.download.failed",
                    provider=self.provider_key,
                    file=name,
                    via=route,
                    why=str(reason),
                )
                raise CaptureBrowserError(
                    f"the vendor download did not complete ({reason}); nothing was saved for "
                    f"{name!r}"
                ) from exc
            self._captured.append(
                CapturedFile(path=dest, suggested_name=name, url=download.url or "")
            )
            trace(
                "capture.download.saved",
                provider=self.provider_key,
                via=route,
                saved=file_note(dest),
                path=dest,
                task_bound=False,
            )


def _browser_candidates(engine: str) -> tuple[_BrowserCandidate, ...]:
    if engine == "windows":
        return (
            _BrowserCandidate("Google Chrome", "chromium", "chrome"),
            _BrowserCandidate("Playwright Chromium", "chromium"),
        )
    if engine in {"chrome", "edge", "msedge"}:
        channel = "chrome" if engine == "chrome" else "msedge"
        label = "Google Chrome" if channel == "chrome" else "Microsoft Edge"
        return (_BrowserCandidate(label, "chromium", channel),)
    if engine in {"chromium", "firefox", "webkit"}:
        return (_BrowserCandidate(f"Playwright {engine.title()}", engine),)
    raise CaptureBrowserError(f"unknown browser engine {engine!r}")


def _safe_filename(name: str) -> str:
    """Make a vendor filename portable to Windows without changing its evidence label."""

    leaf = Path(name).name
    safe = _WINDOWS_INVALID_FILENAME.sub("_", leaf).strip(" .")
    if not safe:
        return "cad-download"
    stem = Path(safe).stem[:160].rstrip(" .") or "cad-download"
    suffix = Path(safe).suffix[:20]
    if stem.casefold() in _WINDOWS_RESERVED_NAMES:
        stem = f"_{stem}"
    return f"{stem}{suffix}"


def _validate_capture_url(url: str) -> None:
    if type(url) is not str or not url or url != url.strip():
        raise CaptureBrowserError("capture URL must be non-empty canonical text")
    parsed = urlsplit(url)
    if parsed.scheme.casefold() not in {"http", "https"} or not parsed.netloc:
        raise CaptureBrowserError("capture URL must be an absolute HTTP or HTTPS provider URL")


def _bounded_seconds(
    value: float,
    label: str,
    *,
    maximum: float,
    allow_zero: bool = False,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        valid = False
        seconds = 0.0
    else:
        seconds = float(value)
        valid = 0 <= seconds <= maximum if allow_zero else 0 < seconds <= maximum
    if not valid:
        lower = "zero" if allow_zero else "greater than zero"
        raise ValueError(f"{label} must be {lower} and at most {maximum:g}")
    return seconds


def _page_is_closed(page) -> bool:
    is_closed = getattr(page, "is_closed", None)
    if not callable(is_closed):
        return False
    try:
        return bool(is_closed())
    except Exception:  # noqa: BLE001 - a torn-down page is closed for lifecycle purposes
        return True


def _page_url(page, fallback: str) -> str:
    try:
        current = getattr(page, "url", "")
    except Exception:  # noqa: BLE001 - page closure must not erase the last known provider URL
        return fallback
    return current if isinstance(current, str) and current else fallback


def _unique(directory: Path, name: str) -> Path:
    """A collision-free path inside `directory`.

    Vendors name every export the same (`<MPN>.zip`), so a second format's download would
    otherwise overwrite the first while it is still being read - a failure already observed live
    on 2026-07-23 with the WebView2 path, and worth carrying over rather than re-learning.
    """
    stem = Path(name).stem or "cad-download"
    suffix = Path(name).suffix
    dest = directory / f"{stem}{suffix}"
    counter = 2
    while dest.exists():
        dest = directory / f"{stem}-{counter}{suffix}"
        counter += 1
    return dest


def chromium_unavailable_reason() -> str | None:
    """None when a browser really can launch, else the REAL reason it cannot.

    Returns the reason rather than a bool because the first version of this returned False for
    every cause and its callers all printed "chromium is not installed". That was FALSE: the
    actual failure was `ENOENT ... mkdtemp '/dev/shm/srtest/...'` - a TMPDIR that did not exist -
    and the invented explanation sent the diagnosis in the wrong direction entirely. A check that
    reports a cause it did not establish is worse than one that reports nothing.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        return f"playwright is not importable ({exc})"
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            browser.close()
        return None
    except Exception as exc:  # noqa: BLE001 - report whatever actually went wrong
        detail = str(exc).strip().splitlines()[0][:200] if str(exc).strip() else type(exc).__name__
        return f"chromium could not launch: {detail}"


def chromium_available() -> bool:
    """Convenience wrapper. Prefer `chromium_unavailable_reason()` where a message is shown."""
    return chromium_unavailable_reason() is None


def default_profile_dir(app_data: Path) -> Path:
    """Where vendor logins persist, per machine.

    PER-MACHINE ON PURPOSE, and it is the allowed kind: it holds credentials/session cookies only,
    never anything that changes what the library renders, so it cannot break device parity the way
    a per-machine enrich cache does.
    """
    return Path(app_data) / "capture-profile"


def clear_profile(profile_dir: Path) -> bool:
    """Delete the persisted vendor sessions. True when something was removed."""
    profile_dir = Path(profile_dir)
    if not profile_dir.exists():
        return False
    shutil.rmtree(profile_dir, ignore_errors=True)
    return not profile_dir.exists()
