"""The capture BROWSER: one deterministic way to open a vendor page and save its download.

Owner, 2026-07-27: *"literally make the best environment for us ... something that works on both
windows and linux so its not hard for u to test it"*.

WHY THIS EXISTS (the problem it removes)
Guided capture used to live entirely inside the pywebview WebView2 window, and that had three
costs, all of them measured rather than supposed:

1. **It is Windows-only, so the whole flow was untestable from Linux.** The frontend's only route
   in is `window.pywebview.api.open_cad_download` (`lib/capture.tsx`), which does not exist off
   Windows, so on Linux the flow silently degrades to "pick the files yourself". That is exactly
   why an agent could verify the URL layer and the selector layer but never the layer the owner
   actually sees.
2. **pywebview exposes NO public download-intercept API** (verified and recorded at
   `host/window.py:201`), so tier 1 monkeypatched pywebview's private WinForms/WebView2 internals
   and tier 2 polled `~/Downloads`. That coupling is logged as risk R3 in the guided-capture spec.
3. **CDP cannot rescue it**: `Browser.setDownloadBehavior` returns invalid-argument (0x80070057)
   in WebView2, so the one API that would have made downloads observable there does not work.

Playwright, which this repo ALREADY bundles for the scrape engine (`pyproject.toml`), has a
public, documented download API (`expect_download` / `save_as`) and gives real waiting primitives
instead of sleeps. So the capture browser is Playwright, and the vendor logic moves OUT of injected
JS in `host/` into ordinary Python that a test can drive anywhere.

WHAT STAYS AS IT WAS
The APP SHELL is still pywebview/WebView2 on Windows: that decision (spec 2026-07-12 section 3) is
about hosting our own frontend, where Python-as-host and native drag/drop paths genuinely win, and
nothing here disturbs it. This module is only about the SECOND window - the vendor page.

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


class CaptureBrowserError(RuntimeError):
    """Something the caller must fix, phrased so the message names the actual blocker."""


UserCaptureStatus = Literal["completed", "try_another", "cancelled", "timed_out"]
ProviderHudAction = Literal["finish", "try_another", "cancel"]
_PROVIDER_HUD_ACTIONS = frozenset({"finish", "try_another", "cancel"})


@dataclass(frozen=True, slots=True)
class ProviderHudSpec:
    """Exact Stockroom-owned text shown over one person-controlled provider page."""

    provider_label: str
    manufacturer: str
    mpn: str
    required_file_labels: tuple[str, ...]

    def __post_init__(self) -> None:
        for value, label in (
            (self.provider_label, "provider_label"),
            (self.manufacturer, "manufacturer"),
            (self.mpn, "mpn"),
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
_PROVIDER_HUD_BOOTSTRAP = r"""
(payload) => {
  if (!payload || globalThis !== globalThis.top || globalThis[payload.namespace]) {
    return;
  }

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
        width: min(360px, calc(100vw - 24px));
        margin: 0;
        padding: 0;
        border: 0;
        color-scheme: dark;
        font: 13px/1.4 Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont,
          "Segoe UI", sans-serif;
      }
      *, *::before, *::after {
        box-sizing: border-box;
      }
      .panel {
        overflow: hidden;
        color: #f8fafc;
        background: #101827;
        border: 1px solid #64748b;
        border-radius: 12px;
        box-shadow: 0 18px 48px rgb(0 0 0 / 42%);
      }
      .header {
        display: grid;
        grid-template-columns: 34px minmax(0, 1fr) auto auto;
        align-items: center;
        gap: 7px;
        min-height: 44px;
        padding: 6px 7px;
        background: #172236;
        border-bottom: 1px solid #334155;
        cursor: grab;
        user-select: none;
        touch-action: none;
      }
      .header.dragging {
        cursor: grabbing;
      }
      .move,
      .collapse {
        width: 32px;
        height: 32px;
        padding: 0;
        color: #e2e8f0;
        background: transparent;
        border: 1px solid transparent;
        border-radius: 7px;
        font: inherit;
      }
      .move {
        cursor: grab;
        font-size: 18px;
        letter-spacing: -4px;
      }
      .collapse {
        cursor: pointer;
        font-size: 17px;
      }
      .title {
        min-width: 0;
        font-size: 13px;
        font-weight: 750;
        letter-spacing: .01em;
        overflow: hidden;
        text-overflow: ellipsis;
        white-space: nowrap;
      }
      .count {
        min-width: 28px;
        padding: 3px 7px;
        color: #dbeafe;
        background: #1e3a5f;
        border: 1px solid #3b82f6;
        border-radius: 999px;
        font-size: 12px;
        font-variant-numeric: tabular-nums;
        text-align: center;
      }
      .content {
        display: grid;
        gap: 10px;
        max-height: min(72vh, 610px);
        padding: 11px;
        overflow: auto;
        scrollbar-color: #64748b transparent;
      }
      .identity {
        display: grid;
        grid-template-columns: max-content minmax(0, 1fr);
        gap: 4px 9px;
        margin: 0;
        padding: 8px;
        background: #0b1220;
        border: 1px solid #334155;
        border-radius: 8px;
      }
      dt {
        color: #94a3b8;
        font-size: 11px;
        font-weight: 700;
        letter-spacing: .045em;
        text-transform: uppercase;
      }
      dd {
        min-width: 0;
        margin: 0;
        color: #f8fafc;
        font-weight: 650;
        overflow-wrap: anywhere;
        user-select: text;
      }
      h2 {
        margin: 0 0 5px;
        color: #cbd5e1;
        font-size: 11px;
        font-weight: 800;
        letter-spacing: .055em;
        text-transform: uppercase;
      }
      .files {
        display: flex;
        flex-wrap: wrap;
        gap: 5px;
        margin: 0;
        padding: 0;
        list-style: none;
      }
      .files li {
        padding: 4px 7px;
        color: #e0f2fe;
        background: #123047;
        border: 1px solid #0ea5e9;
        border-radius: 6px;
        overflow-wrap: anywhere;
      }
      .steps {
        display: grid;
        gap: 5px;
        margin: 0;
        padding-left: 22px;
        color: #dbe4f0;
      }
      .steps li {
        padding-left: 2px;
      }
      .steps li::marker {
        color: #7dd3fc;
        font-weight: 800;
      }
      .live {
        margin: 0;
        padding: 7px 8px;
        color: #bfdbfe;
        background: #172554;
        border-left: 3px solid #60a5fa;
        border-radius: 5px;
        font-weight: 700;
      }
      .actions {
        display: grid;
        grid-template-columns: 1fr 1.35fr 1fr;
        gap: 6px;
      }
      .action {
        min-height: 36px;
        padding: 6px 8px;
        color: #f8fafc;
        background: #263449;
        border: 1px solid #64748b;
        border-radius: 7px;
        cursor: pointer;
        font: 700 12px/1.2 Inter, ui-sans-serif, system-ui, sans-serif;
      }
      .finish {
        color: #052e16;
        background: #86efac;
        border-color: #4ade80;
      }
      .another {
        color: #172554;
        background: #bfdbfe;
        border-color: #60a5fa;
      }
      .cancel {
        color: #fee2e2;
        background: #451a1a;
        border-color: #ef4444;
      }
      button:hover:not(:disabled) {
        filter: brightness(1.08);
      }
      button:focus-visible {
        outline: 3px solid #fbbf24;
        outline-offset: 2px;
      }
      button:disabled {
        cursor: wait;
        filter: grayscale(.5);
        opacity: .68;
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
        .files li,
        .action {
          border: 1px solid ButtonText;
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
    const title = make("div", "title", `Stockroom · ${payload.providerLabel}`);
    title.id = `${payload.namespace}-title`;
    const count = make("span", "count", "0");
    count.setAttribute("aria-label", "Downloads captured: 0");
    const collapse = make("button", "collapse", "−");
    collapse.type = "button";
    collapse.setAttribute("aria-expanded", "true");
    collapse.setAttribute("aria-controls", `${payload.namespace}-content`);
    collapse.setAttribute("aria-label", "Collapse Stockroom panel");
    header.append(move, title, count, collapse);

    const content = make("div", "content");
    content.id = `${payload.namespace}-content`;

    const identity = make("dl", "identity");
    for (const [label, value] of [
      ["Provider", payload.providerLabel],
      ["Manufacturer", payload.manufacturer],
      ["MPN", payload.mpn],
    ]) {
      identity.append(make("dt", "", label), make("dd", "", value));
    }

    const filesSection = make("section");
    filesSection.append(make("h2", "", "Required files"));
    const files = make("ul", "files");
    files.setAttribute("aria-label", "Required file formats");
    for (const label of payload.requiredFileLabels) {
      files.append(make("li", "", label));
    }
    filesSection.append(files);

    const instructions = make("section");
    instructions.append(make("h2", "", "What to do"));
    const steps = make("ol", "steps");
    for (const text of [
      "Sign in if asked—this session is remembered on this PC.",
      "Choose the result matching the exact manufacturer and MPN shown above.",
      "Select every required file format listed here.",
      "Download each file. Stockroom captures it automatically.",
      "Choose Finish, Try Another Provider, or Cancel.",
    ]) {
      steps.append(make("li", "", text));
    }
    instructions.append(steps);

    const live = make("p", "live", "Downloads captured: 0");
    live.setAttribute("role", "status");
    live.setAttribute("aria-live", "polite");
    live.setAttribute("aria-atomic", "true");

    const actionStatus = make("p", "sr-only", "");
    actionStatus.setAttribute("role", "status");
    actionStatus.setAttribute("aria-live", "polite");

    const actions = make("div", "actions");
    const finish = make("button", "action finish", "Finish");
    const another = make("button", "action another", "Try Another Provider");
    const cancel = make("button", "action cancel", "Cancel");
    for (const button of [finish, another, cancel]) button.type = "button";
    actions.append(finish, another, cancel);
    content.append(identity, filesSection, instructions, live, actionStatus, actions);
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

    let actionPending = false;
    const actionButtons = [finish, another, cancel];
    const requestAction = async (action, spokenLabel) => {
      if (actionPending) return;
      actionPending = true;
      for (const button of actionButtons) button.disabled = true;
      actionStatus.textContent = `${spokenLabel} requested.`;
      try {
        const accepted = await globalThis[payload.actionBinding](action, payload.actionToken);
        if (accepted) return;
      } catch {}
      actionPending = false;
      for (const button of actionButtons) button.disabled = false;
      actionStatus.textContent = "Stockroom could not accept that action. Try again.";
    };
    finish.addEventListener("click", () => requestAction("finish", "Finish"));
    another.addEventListener(
      "click",
      () => requestAction("try_another", "Try another provider"),
    );
    cancel.addEventListener("click", () => requestAction("cancel", "Cancel"));

    const updateDownloadCount = (value) => {
      if (!Number.isInteger(value) || value < 0) return;
      const noun = value === 1 ? "file" : "files";
      count.textContent = String(value);
      count.setAttribute("aria-label", `Downloads captured: ${value}`);
      live.textContent = `Downloads captured: ${value} ${noun}`;
    };
    updateDownloadCount(payload.downloadCount);

    Object.defineProperty(globalThis, payload.namespace, {
      value: Object.freeze({ updateDownloadCount }),
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
({ namespace, downloadCount }) => {
  const hud = globalThis[namespace];
  if (hud && typeof hud.updateDownloadCount === "function") {
    hud.updateDownloadCount(downloadCount);
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

  const host = document.createElement("aside");
  host.setAttribute("aria-label", "Stockroom security handoff");
  host.style.cssText = [
    "all:initial",
    "position:fixed",
    "inset:12px 12px auto auto",
    "z-index:2147483647",
    "display:block",
    "width:min(390px,calc(100vw - 24px))",
  ].join(";");
  const shadow = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = `
    * { box-sizing: border-box; }
    section {
      color: #f8fafc; background: #172033; border: 2px solid #f59e0b; border-radius: 12px;
      box-shadow: 0 18px 52px rgb(0 0 0 / 48%); padding: 14px;
      font: 13px/1.45 Inter, ui-sans-serif, system-ui, "Segoe UI", sans-serif;
    }
    h1 { margin: 0 0 7px; color: #fde68a; font-size: 15px; }
    p { margin: 6px 0; overflow-wrap: anywhere; }
    .identity { color: #dbeafe; font-weight: 700; }
    .safe { color: #bfdbfe; border-left: 3px solid #60a5fa; padding-left: 8px; }
    .status { color: #fef3c7; font-weight: 700; }
  `;
  const panel = document.createElement("section");
  panel.setAttribute("role", "alert");
  const title = document.createElement("h1");
  title.textContent = "Stockroom Paused For You";
  const identity = document.createElement("p");
  identity.className = "identity";
  identity.textContent = `${state.providerLabel} · ${state.manufacturer} · ${state.mpn}`;
  const message = document.createElement("p");
  message.className = "status";
  message.textContent = state.message;
  const safe = document.createElement("p");
  safe.className = "safe";
  safe.textContent =
    "Complete the visible sign-in, CAPTCHA, 2FA, or security check yourself. " +
    "Stockroom will not click it and resumes automatically when it is gone.";
  panel.append(title, identity, message, safe);
  shadow.append(style, panel);
  document.documentElement.append(host);

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
    namespace: str = field(
        default_factory=lambda: f"__stockroom_capture_hud_{secrets.token_hex(12)}"
    )
    action_binding: str = field(
        default_factory=lambda: f"__stockroom_capture_action_{secrets.token_hex(12)}"
    )
    action_token: str = field(default_factory=lambda: secrets.token_hex(24))
    _action: ProviderHudAction | None = None
    _download_count: int = 0
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
                return False
            self._action = cast(ProviderHudAction, action)
            return True

    def update_download_count(self, count: int) -> None:
        if type(count) is not int or count < 0:
            raise ValueError("download count must be a non-negative integer")
        with self._lock:
            self._download_count = count

    def payload(self) -> dict[str, object]:
        with self._lock:
            return {
                "namespace": self.namespace,
                "actionBinding": self.action_binding,
                "actionToken": self.action_token,
                "providerLabel": self.spec.provider_label,
                "manufacturer": self.spec.manufacturer,
                "mpn": self.spec.mpn,
                "requiredFileLabels": list(self.spec.required_file_labels),
                "downloadCount": self._download_count,
            }


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

    def __init__(
        self,
        *,
        download_dir: Path,
        profile_dir: Path | None = None,
        headless: bool = False,
        engine: str = "chromium",
        provider_key: str | None = None,
        playwright_runtime: SharedPlaywrightRuntime | None = None,
    ) -> None:
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.profile_dir = Path(profile_dir) if profile_dir else None
        self.headless = headless
        self.engine = engine
        self._playwright_runtime = playwright_runtime
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
        page = context.new_page()
        self._wire_downloads(page)
        with self._download_lock:
            self._page_brokers.append((page, broker))
        try:
            if hud_state is not None:
                self._bind_provider_hud(page, hud_state)
            yield page
        finally:
            try:
                page.close()
            except Exception:  # noqa: BLE001 - teardown is best effort
                pass
            with self._download_lock:
                self._page_brokers = [
                    (wired, bound) for wired, bound in self._page_brokers if wired is not page
                ]
                self._page_huds = (
                    [(wired, bound) for wired, bound in self._page_huds if bound is not hud_state]
                    if hud_state is not None
                    else [(wired, bound) for wired, bound in self._page_huds if wired is not page]
                )
                self._wired_pages = [wired for wired in self._wired_pages if wired is not page]

    def wait_for_user_clearance(
        self,
        page,
        *,
        provider_label: str,
        manufacturer: str,
        mpn: str,
        message: str,
        issue_detector: Callable[[], str],
        should_cancel: Callable[[], bool] | None = None,
        timeout_s: float = 600.0,
        poll_interval_s: float = 0.25,
    ) -> bool:
        """Show a Stockroom HUD while the person clears authentication or a security control.

        The detector observes only whether a gate remains. This method never locates, fills, clicks,
        or submits any provider element. The HUD is registered for future documents before it is
        mounted on the current one, so an SSO or 2FA navigation retains the handoff. Once cleared,
        the binding returns inactive and later automation navigations cannot remount stale guidance.
        """

        for value, label in (
            (provider_label, "provider_label"),
            (manufacturer, "manufacturer"),
            (mpn, "mpn"),
            (message, "message"),
        ):
            if type(value) is not str or not value or value != value.strip():
                raise ValueError(f"{label} must be exact non-empty text")
        if not callable(issue_detector):
            raise TypeError("issue_detector must be callable")
        if should_cancel is not None and not callable(should_cancel):
            raise TypeError("should_cancel must be callable")
        timeout = _bounded_seconds(timeout_s, "timeout_s", maximum=3600.0)
        poll = _bounded_seconds(poll_interval_s, "poll_interval_s", maximum=1.0)

        try:
            current_issue = issue_detector() or ""
        except Exception:  # noqa: BLE001 - unreadable gate stays blocked and visible
            current_issue = message
        if not current_issue:
            return True

        namespace = f"__stockroom_security_handoff_{secrets.token_hex(12)}"
        state_binding = f"__stockroom_security_state_{secrets.token_hex(12)}"
        state_token = secrets.token_hex(24)
        state: dict[str, object] = {
            "active": True,
            "providerLabel": provider_label,
            "manufacturer": manufacturer,
            "mpn": mpn,
            "message": current_issue,
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
                return False
            if _page_is_closed(page):
                state["active"] = False
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
                return True
            if issue != last_issue:
                last_issue = issue
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
    ) -> UserCaptureResult:
        """Open one provider page and observe downloads while the person controls it.

        This is deliberately a small browser lifecycle, not a provider driver. Production code
        wires the task-bound download handler and optional Stockroom HUD *before* navigation, opens
        exactly ``url``, pumps Playwright, and observes only explicit HUD/caller actions, page
        closure, or timeout. The HUD is a closed-shadow, top-layer Stockroom surface whose exact
        identity and required-file labels come only from ``hud``. Neither Python nor that surface
        inspects or searches provider DOM, reads credentials, fills fields, selects a result or
        format, accepts terms, or clicks a provider control.

        ``should_finish`` remains a caller-owned completion signal beside the HUD's Finish button.
        Without either, closing the capture page completes the session. A short quiet period after
        that signal keeps sibling downloads from one user click bound to the same task. Try Another
        Provider, cancellation, and timeout return every file already intercepted, but callers
        decide whether those files may be attached.
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

        deadline = time.monotonic() + timeout
        status: UserCaptureStatus = "timed_out"
        final_url = url
        error_mark = len(self.download_errors)
        hud_state = _ProviderHudState(hud) if hud is not None else None
        if hud_state is not None:
            hud_state.update_download_count(len(broker.receipts))

        with self.task_page(broker, hud_state=hud_state) as page:
            if should_cancel is not None and should_cancel():
                status = "cancelled"
            else:
                try:
                    page.goto(
                        url,
                        wait_until="domcontentloaded",
                        timeout=max(1, int(timeout * 1000)),
                    )
                except Exception:
                    final_url = _page_url(page, url)
                    hud_action = hud_state.action if hud_state is not None else None
                    if should_cancel is not None and should_cancel():
                        status = "cancelled"
                    elif hud_action == "cancel":
                        status = "cancelled"
                    elif hud_action == "try_another":
                        status = "try_another"
                    elif hud_action == "finish":
                        status = "completed"
                    elif _page_is_closed(page):
                        status = "completed"
                    elif time.monotonic() >= deadline:
                        status = "timed_out"
                    else:
                        raise
                else:
                    final_url = _page_url(page, url)
                    receipt_count = len(broker.receipts)
                    if hud_state is not None:
                        self._update_provider_hud(hud_state, receipt_count)
                    quiet_since = time.monotonic()
                    finish_requested = False
                    while True:
                        errors = self.download_errors
                        if len(errors) > error_mark:
                            raise errors[error_mark]

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
            if self.engine == "camoufox":
                self.launched_browser = "Camoufox"
                with self._camoufox_session() as page:
                    yield page
                return
            if self.engine == "cloak":
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

    def _launch_playwright(self, pw):
        """Launch the requested browser policy and return ``(context, browser)``.

        ``windows`` is a deterministic policy, not an alias for bundled Chromium: prefer the
        preferred browser already managed on this machine (Chrome), then Stockroom's pinned
        Playwright Chromium. A failed candidate is fully discarded before the next one is
        attempted.
        """

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

        DigiKey's CAD-provider application currently renders in Chromium but not Camoufox's
        Firefox engine, while stock Playwright Chromium reaches DigiKey's automation
        interstitial. CloakBrowser supplies a source-patched Chromium binary and the same
        synchronous Playwright objects this class already owns. Its public v146 build is pinned
        deliberately: it requires no account or API key, is downloaded independently on each
        installation, and its wrapper verifies the published signature/checksum.
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
        """Install one Stockroom-owned HUD without reading provider-controlled page content."""

        with self._download_lock:
            if any(wired is page for wired, _bound in self._page_huds):
                return

        payload = state.payload()

        def receive_action(_source, action, token) -> bool:
            return state.request_action(action, token)

        init_script = (
            f"({_PROVIDER_HUD_BOOTSTRAP})("
            f"{json.dumps(payload, ensure_ascii=True, separators=(',', ':'))}"
            ");"
        )
        try:
            page.expose_binding(state.action_binding, receive_action)
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

    def _update_provider_hud(self, state: _ProviderHudState, download_count: int) -> None:
        """Push Stockroom's receipt count into every page displaying this task's HUD."""

        state.update_download_count(download_count)
        with self._download_lock:
            pages = [page for page, bound in self._page_huds if bound is state]
        payload = {
            "namespace": state.namespace,
            "downloadCount": download_count,
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
        current = page
        seen: set[int] = set()
        while current is not None and id(current) not in seen:
            seen.add(id(current))
            with self._download_lock:
                broker = next(
                    (bound for wired, bound in self._page_brokers if wired is current),
                    None,
                )
            if broker is not None:
                return broker
            opener = getattr(current, "opener", None)
            try:
                current = opener() if callable(opener) else None
            except Exception:  # noqa: BLE001 - an unreadable opener is simply unbound
                current = None
        return None

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
        broker = self._broker_for_page(page) if page is not None else None
        if broker is not None:
            try:
                receipt = broker.capture_playwright(download)
            except DownloadBrokerError as exc:
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
                raise CaptureBrowserError(
                    f"the vendor download did not complete ({reason}); nothing was saved for "
                    f"{name!r}"
                ) from exc
            self._captured.append(
                CapturedFile(path=dest, suggested_name=name, url=download.url or "")
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
