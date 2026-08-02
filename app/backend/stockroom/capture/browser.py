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

import hashlib
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

from stockroom.capture.download_broker import (
    DownloadBroker,
    DownloadBrokerError,
    DownloadReceipt,
)
from stockroom.capture.trace import file_note, trace, trace_debug, trace_warning, url_note


class CaptureBrowserError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


UserCaptureStatus = Literal["completed", "try_another", "cancelled", "timed_out"]
ProviderHudAction = Literal["finish", "try_another", "cancel"]
_PROVIDER_HUD_ACTIONS = frozenset({"finish", "try_another", "cancel"})


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
_CLOAK_BROWSER_VERSION = "146.0.7680.177.5"
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

_PROVIDER_HUD_BOOTSTRAP = r"""
async (payload) => {
  if (!payload || globalThis !== globalThis.top || globalThis[payload.namespace]) {
    return;
  }

  // This payload is registered once and replayed on every provider navigation, so the count it
  // carries is only ever the one that was true at bind time. Read the live one back from Stockroom
  // the way the security handoff does, and keep the snapshot when that read cannot be served.
  let downloadCount = payload.downloadCount;
  // Fail SAFE, not open: an unreadable state leaves the hold on, so a remount during a security
  // handoff never draws an outline before Stockroom's next push arrives.
  let securityHold = true;
  try {
    const state = await globalThis[payload.stateBinding](payload.stateToken);
    if (state && Number.isInteger(state.downloadCount)) downloadCount = state.downloadCount;
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
        inset: 12px 12px auto auto;
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

    document.documentElement.append(host);

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
        place(globalThis.innerWidth - host.offsetWidth - 12, 12);
        return;
      }
      const offset = offsets[event.key];
      if (!offset) return;
      event.preventDefault();
      place(host.offsetLeft + offset[0], host.offsetTop + offset[1]);
    });

    let pendingAction = null;
    let currentDownloadCount = 0;
    const pendingSteps = {
      finish: "Finishing capture after downloaded files settle.",
      try_another: "Closing this route and preparing the next provider.",
      cancel: "Closing the assisted capture.",
    };

    // ---- Tier 1: the live checklist, built only from Stockroom-owned data --------------------
    const renderChecklist = () => {
      const labels = payload.requiredFileLabels;
      const total = labels.length;
      const landed = Math.min(currentDownloadCount, total);
      steps.forEach((step, index) => {
        const done = index < landed;
        const next = !done && index === landed;
        step.item.className = done ? "step done" : next ? "step next" : "step";
        step.mark.textContent = done ? "✓" : next ? "▸" : "○";
        step.state.textContent = done ? "Captured" : next ? "Next" : "Waiting";
      });
      if (total > 0 && landed >= total) {
        outstanding.className = "outstanding done";
        outstanding.textContent =
          `All ${total} required ${total === 1 ? "format has" : "formats have"} landed. ` +
          "Nothing is outstanding; Stockroom resumes automatically.";
        return;
      }
      outstanding.className = "outstanding";
      const remaining = labels.slice(landed).join(", ");
      outstanding.textContent =
        landed === 0
          ? `Nothing captured yet. Still outstanding: ${remaining}.`
          : `${landed} of ${total} captured. Still outstanding: ${remaining}. One provider ` +
            "archive can carry several formats, so Stockroom checks the delivered files and " +
            "resumes on its own.";
    };

    // ---- Tier 2: position-only outlines over the real controls -------------------------------
    // These two helpers are the WHOLE of this script's provider-DOM surface: where an element is,
    // and whether it is worth drawing over. No page text, markup, attribute value, form value, or
    // credential is read, kept, or reported anywhere - a rect is not content.
    const drawableRect = (node) => {
      if (node === host || node === overlayHost) return null;
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
      if (total > 0 && currentDownloadCount >= total) {
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
      if (typeof next.securityHold === "boolean") securityHold = next.securityHold;
      render();
    };
    updateState({ downloadCount, securityHold });

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
({ namespace, downloadCount, securityHold }) => {
  const hud = globalThis[namespace];
  if (hud && typeof hud.updateState === "function") {
    hud.updateState({ downloadCount, securityHold });
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

  const host = document.createElement("aside");
  host.setAttribute("aria-label", "Stockroom security handoff");
  host.setAttribute("popover", "manual");
  host.style.cssText = [
    "position:fixed",
    "inset:12px 12px auto auto",
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
    .content {
      display: grid;
      gap: 8px;
      padding: 8px;
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
  header.append(title, mode);

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
      dismiss() { host.remove(); },
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

    def update_download_count(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("download count must be a non-negative integer")
        with self._lock:
            self._download_count = count

    @property
    def download_count(self) -> int:
        with self._lock:
            return self._download_count

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
                "automatedStep": self.spec.automated_step,
                "humanAction": self.spec.human_action,
                "sessionPersistent": self.persistent_session,
                "downloadCount": self._download_count,
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


class PlaywrightCaptureBrowser:
    """A real, visible browser the person can work in, whose downloads we observe.

    Not headless by default: this is a GUIDED capture, so the human signs in, clears a Cloudflare
    check, and watches what happens. Headless exists for the tests.

    ENGINE IS A PARAMETER, NEVER A SECOND CLASS. Production uses Stockroom's version-pinned
    Playwright Chromium so the browser version is part of the tested application contract rather
    than whichever branded browser happens to be installed. ``windows`` remains an explicit
    Chrome-then-Chromium compatibility policy. ``camoufox`` is the Firefox stealth mode and
    ``cloak`` is the Chromium stealth mode, each selected only for a measured provider need. A
    vendor that resists is therefore a MODE on this class, never a second capture-browser class
    beside it - that is the one-tool-per-job rule, and
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
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.engine = engine
        self._playwright_runtime = playwright_runtime
        self._cdp_endpoint = cdp_endpoint
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
        # Playwright's synchronous API may re-enter the download callback while ``save_as`` for
        # the previous file pumps protocol events.  A provider action that emits a symbol,
        # footprint, and model together therefore nests callbacks on the same thread.  A plain
        # Lock deadlocks on the second file; the RLock serializes filename allocation without
        # blocking that legitimate re-entry.
        self._download_lock = threading.RLock()

    @property
    def captured(self) -> list[CapturedFile]:
        return list(self._captured)

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
        # A persistent Playwright context normally starts with one about:blank page. Opening a
        # second page here left that inert first window visible beside the task-bound one, which
        # made Stockroom appear to launch duplicate browsers even though only one could capture.
        # Claim that untouched page for the first task; later tasks still receive fresh pages.
        with self._download_lock:
            bound_pages = {id(wired) for wired, _bound in self._page_brokers}
        pages = list(getattr(context, "pages", ()) or ())
        page = next(
            (
                candidate
                for candidate in pages
                if id(candidate) not in bound_pages
                and not _page_is_closed(candidate)
                and _page_url(candidate, "about:blank") in {"", "about:blank"}
            ),
            None,
        )
        # Claiming a pre-existing page avoids a stray blank window, but that page is the one
        # `session()` yields and keeps for the whole session. Only a page this task actually
        # opened may be closed with it; closing a claimed one ends the session's own surface.
        task_opened_page = page is None
        if page is None:
            page = context.new_page()
        self._wire_downloads(page)
        with self._download_lock:
            self._page_brokers.append((page, broker))
        try:
            if hud_state is not None:
                self._bind_provider_hud(page, hud_state)
            yield page
        finally:
            # Provider download actions can open child tabs/windows. They inherit the broker
            # binding through their opener, so they are part of this task and must close with it.
            # Leaving them behind produces stale windows whose controls no longer attach files.
            owned_pages = [page]
            for candidate in list(getattr(context, "pages", ()) or ()):
                if candidate is page:
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
            owned_ids = {id(owned) for owned in owned_pages}
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
            state_token = secrets.token_hex(24)
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

            payload = {
                "namespace": namespace,
                "stateBinding": state_binding,
                "stateToken": state_token,
            }
            bootstrap = (
                f"({_HANDOFF_HUD_BOOTSTRAP})("
                f"{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"
                ");"
            )
            try:
                page.expose_binding(state_binding, provide_state)
                page.add_init_script(bootstrap)
                page.evaluate(_HANDOFF_HUD_BOOTSTRAP, payload)
            except Exception as exc:  # noqa: BLE001 - a hidden handoff is not a safe handoff
                state["active"] = False
                raise CaptureBrowserError(
                    "could not show the Stockroom security handoff before pausing automation"
                ) from exc

            deadline = time.monotonic() + timeout
            last_issue = current_issue
            while time.monotonic() < deadline:
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
    ) -> UserCaptureResult:
        """Open one provider page and observe downloads while the person controls it.

        This is deliberately a small browser lifecycle, not a provider driver. Production code
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
        ``auto_finish_idle_seconds`` bounds that wait so a provider that packs every required
        format into one archive still completes without a click. Closing the page also completes
        the session. Try Another Provider, cancellation, and timeout return every file already
        intercepted; staging never depends on a second click.
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
        auto_finish_idle = _bounded_seconds(
            auto_finish_idle_seconds,
            "auto_finish_idle_seconds",
            maximum=600.0,
            allow_zero=True,
        )
        # The HUD names exactly the formats this route must come home with, so it is also the
        # only completeness signal available here. Without a HUD there is nothing to be complete
        # against and the first quiet period stands.
        expected_files = len(hud.required_file_labels) if hud is not None else 0

        deadline = time.monotonic() + timeout
        status: UserCaptureStatus = "timed_out"
        final_url = url
        error_mark = len(self.download_errors)
        hud_state = (
            _ProviderHudState(hud, self.persistent_digikey_session) if hud is not None else None
        )
        if hud_state is not None:
            hud_state.update_download_count(len(broker.receipts))

        with (
            _exclusive_user_capture_window(),
            self.task_page(
                broker,
                hud_state=hud_state,
            ) as page,
        ):
            if should_cancel is not None and should_cancel():
                status = "cancelled"
            else:
                navigation_terminal = False
                try:
                    page.goto(
                        url,
                        # Provider pages can commit the requested URL and then keep loading
                        # challenge scripts or subresources indefinitely.  Waiting for
                        # DOMContentLoaded prevented Stockroom from observing Finish Route (and
                        # manually selected files) until the full capture timeout elapsed.
                        wait_until="commit",
                        # Initial navigation is advisory: the task-bound picker and HUD remain
                        # useful even when a provider challenge never commits a document. Keep
                        # the overall route timeout for the polling loop, not this blocking call.
                        timeout=max(1, int(min(timeout, 10.0) * 1000)),
                    )
                except Exception as exc:  # noqa: BLE001 - recovery remains available off-page
                    final_url = _page_url(page, url)
                    hud_action = hud_state.action if hud_state is not None else None
                    if should_cancel is not None and should_cancel():
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
                final_url = _page_url(page, final_url)
                if not navigation_terminal:
                    receipt_count = len(broker.receipts)
                    if hud_state is not None:
                        self._update_provider_hud(hud_state, receipt_count)
                    quiet_since = time.monotonic()
                    finish_requested = False
                    while True:
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
                            status = "completed"
                            break

                        now = time.monotonic()
                        current_count = len(broker.receipts)
                        if current_count != receipt_count:
                            receipt_count = current_count
                            quiet_since = now
                        if hud_state is not None:
                            # This cheap Stockroom-namespace update also restores the current count
                            # after an in-page navigation remounts the init-script HUD.
                            self._update_provider_hud(hud_state, current_count)

                        if should_cancel is not None and should_cancel():
                            status = "cancelled"
                            break
                        hud_action = hud_state.action if hud_state is not None else None
                        if hud_action == "cancel":
                            status = "cancelled"
                            break
                        if hud_action == "try_another":
                            status = "try_another"
                            break
                        if _page_is_closed(page):
                            status = "completed"
                            break
                        if should_finish is not None and should_finish():
                            finish_requested = True
                        if hud_action == "finish":
                            finish_requested = True
                        if finish_requested and (current_count == 0 or now - quiet_since >= settle):
                            status = "completed"
                            break
                        if (
                            current_count > 0
                            and now - quiet_since >= auto_finish
                            and current_count >= expected_files
                        ):
                            status = "completed"
                            break
                        # A provider that ships every required format in one archive produces
                        # fewer receipts than labels and would otherwise wait for a click the
                        # HUD's own copy promises is unnecessary. Finish on a longer idle gap.
                        if current_count > 0 and now - quiet_since >= auto_finish_idle:
                            status = "completed"
                            break
                        if now >= deadline:
                            status = "timed_out"
                            break

                        remaining = deadline - now
                        wait_ms = max(1, int(min(poll_interval, remaining) * 1000))
                        try:
                            page.wait_for_timeout(wait_ms)
                        except Exception:
                            if _page_is_closed(page):
                                status = "completed"
                                break
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
            # A verified CDP endpoint is the already-open Stockroom WebView2 surface. It owns the
            # visible provider session regardless of the adapter's standalone fallback engine;
            # choosing Camoufox/Cloak first would open a second external browser and leave the
            # embedded one disconnected from download capture.
            if self._cdp_endpoint is None and self.engine == "camoufox":
                self.launched_browser = "Camoufox"
                with self._camoufox_session() as page:
                    yield page
                return
            if self._cdp_endpoint is None and self.engine == "cloak":
                self.launched_browser = f"CloakBrowser Chromium {_CLOAK_BROWSER_VERSION}"
                with self._cloak_session() as page:
                    yield page
                return

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
            context.on("page", self._wire_downloads)
            page = context.pages[0] if context.pages else context.new_page()
            self._wire_downloads(page)
            yield page
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
                    raise CaptureBrowserError(
                        "the embedded provider browser exposed no context"
                    )
                self.launched_browser = "Stockroom Embedded WebView2"
                context = contexts[0]
                _disable_webrtc(context)
                return context, browser
            except Exception as exc:
                detail = (
                    str(exc).strip().splitlines()[0]
                    if str(exc).strip()
                    else type(exc).__name__
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

    @contextmanager
    def _camoufox_session(self):
        """The stealth engine, for vendors that put a bot wall in front of their downloads.

        MEASURED 2026-07-27:
          * SnapEDA serves plain headless Chromium a Cloudflare Turnstile interstitial (title
            "Just a moment...", sole input `cf-turnstile-response`). Camoufox walks straight
            through it headless - real results, no wall, no human.
          * It handles Ultra Librarian identically (sign-in and search both fine), so there is no
            page that needs Chromium instead, and no reason for a second launcher to exist.
          * It is roughly 15x slower to launch, which is the whole reason it is opted into rather
            than defaulted to. The guided source opens ONE session per run, so that launch cost is
            paid once for a 90-part sitting, not once per part.

        uBLOCK IS DISABLED, and that is load-bearing rather than tidiness: Camoufox ships uBlock
        Origin, which BLOCKS the anti-bot challenge scripts themselves - leaving a challenge that
        can never complete, on a page that then never loads. The scrape render tier learned this
        the expensive way; the lesson is carried here rather than re-learned.
        """
        try:
            from camoufox import DefaultAddons
            from camoufox.sync_api import Camoufox
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise CaptureBrowserError(
                "camoufox is not installed; it is a declared dependency, run `uv sync` and "
                "`uv run python -m camoufox fetch`"
            ) from exc

        options = {
            "headless": self.headless,
            "os": "windows",
            "humanize": True,
            "timeout": _BROWSER_LAUNCH_TIMEOUT_MS,
            # Capture does not need geolocation. Camoufox's automatic GeoIP mode makes a separate
            # request to a public IP service before the browser can even launch, turning an
            # unrelated third-party outage or firewall rule into a CAD-provider outage.
            "geoip": False,
            "exclude_addons": [DefaultAddons.UBO],
        }
        if self.profile_dir is not None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            options["persistent_context"] = True
            options["user_data_dir"] = str(self.profile_dir)

        try:
            handle = Camoufox(**options)
        except Exception as exc:  # noqa: BLE001 - a missing browser build is a real, nameable case
            raise CaptureBrowserError(
                f"could not launch camoufox: {exc}. If its browser build is missing, run "
                "`uv run python -m camoufox fetch`."
            ) from exc

        with handle as opened:
            # Persistent mode yields a CONTEXT, ephemeral mode yields a BROWSER. Normalising here
            # keeps every caller identical whichever it got.
            if hasattr(opened, "new_page") and not hasattr(opened, "new_context"):
                context = opened
            else:
                context = getattr(opened, "new_context")(accept_downloads=True)
            try:
                _disable_webrtc(context)
                with self._download_lock:
                    self._context = context
                context.on("page", self._wire_downloads)
                page = context.pages[0] if context.pages else context.new_page()
                self._wire_downloads(page)
                yield page
            finally:
                try:
                    context.close()
                except Exception:  # noqa: BLE001 - teardown is best effort
                    pass
                with self._download_lock:
                    self._context = None
                    self._page_brokers.clear()
                    self._page_huds.clear()
                    self._wired_pages.clear()

    @contextmanager
    def _cloak_session(self):
        """Launch the pinned free stealth-Chromium build through the one browser owner.

        CloakBrowser remains the Chromium fallback for a provider surface that requires Chromium.
        DigiKey no longer uses it: a current live check showed Camoufox rendering DigiKey's exact
        product and CAD-model pages, while DigiKey's Cloudflare login challenge repeatedly
        rejected the visible CloakBrowser session after a person completed the checkbox.
        CloakBrowser supplies a source-patched Chromium binary and the same synchronous Playwright
        objects this class already owns. Its public v146 build is pinned deliberately: it requires
        no account or API key, is downloaded independently on each installation, and its wrapper
        verifies the published signature/checksum.
        """

        try:
            from cloakbrowser import launch, launch_persistent_context
        except ImportError as exc:  # pragma: no cover - dependency is declared
            raise CaptureBrowserError(
                "cloakbrowser is not installed; it is a declared dependency, run `uv sync`"
            ) from exc

        fingerprint_source = (
            str(self.profile_dir.resolve()).casefold()
            if self.profile_dir is not None
            else f"stockroom:{self.provider_key or 'ephemeral'}"
        )
        fingerprint = (
            int.from_bytes(
                hashlib.sha256(fingerprint_source.encode("utf-8")).digest()[:4],
                "big",
            )
            % 90_000
            + 10_000
        )
        fingerprint_args = [f"--fingerprint={fingerprint}"]
        context = None
        browser = None
        try:
            if self.profile_dir is not None:
                self.profile_dir.mkdir(parents=True, exist_ok=True)
                context = launch_persistent_context(
                    str(self.profile_dir),
                    headless=self.headless,
                    browser_version=_CLOAK_BROWSER_VERSION,
                    humanize=True,
                    args=fingerprint_args,
                    accept_downloads=True,
                )
            else:
                browser = launch(
                    headless=self.headless,
                    browser_version=_CLOAK_BROWSER_VERSION,
                    humanize=True,
                    args=fingerprint_args,
                )
                context = browser.new_context(accept_downloads=True)
            _disable_webrtc(context)
            with self._download_lock:
                self._context = context
            context.on("page", self._wire_downloads)
            page = context.pages[0] if context.pages else context.new_page()
            self._wire_downloads(page)
            yield page
        except Exception as exc:
            if isinstance(exc, CaptureBrowserError):
                raise
            raise CaptureBrowserError(
                f"could not launch pinned CloakBrowser Chromium: {exc}"
            ) from exc
        finally:
            for closable in (context, browser):
                if closable is not None:
                    try:
                        closable.close()
                    except Exception:  # noqa: BLE001 - teardown is best effort
                        pass
            with self._download_lock:
                self._context = None
                self._page_brokers.clear()
                self._page_huds.clear()
                self._wired_pages.clear()

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
            return state.request_action(action, token)

        def provide_state(_source, token) -> dict[str, object]:
            return state.read_state(token)

        init_script = (
            f"({_PROVIDER_HUD_BOOTSTRAP})("
            f"{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"
            ");"
        )
        try:
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

    @contextmanager
    def _provider_hud_security_hold(self, page):
        """Suppress this task's control outlines while the person owns a provider gate.

        Reuses the one detection Stockroom already has: whatever decided to call
        ``wait_for_user_clearance`` decides this too. A page with no bound provider HUD simply has
        nothing to suppress, and the hold is always released, including on cancellation and
        timeout, so a cleared gate restores the guidance without a second detector.
        """

        state = self._hud_for_page(page)
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

    def _update_provider_hud(self, state: _ProviderHudState, download_count: int) -> None:
        """Push Stockroom's receipt count and outline hold into every page showing this HUD."""

        state.update_download_count(download_count)
        with self._download_lock:
            pages = [page for page, bound in self._page_huds if bound is state]
        payload = {
            "namespace": state.namespace,
            "downloadCount": download_count,
            "securityHold": state.security_hold,
        }
        for page in pages:
            try:
                page.evaluate(_PROVIDER_HUD_UPDATE, payload)
            except Exception:  # noqa: BLE001 - navigation can replace an execution context
                # The registered init script remounts the HUD; the capture loop retries this
                # Stockroom-namespace update on its next bounded poll.
                pass

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

        current = page
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
        current = page
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
