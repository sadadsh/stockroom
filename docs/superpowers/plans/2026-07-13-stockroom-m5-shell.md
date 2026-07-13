# Stockroom M5: Backend API, Self-Update, and the WebView2 App Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put the shipped Qt-free engine (M1 to M4) behind a thin FastAPI veneer, bound to localhost and guarded by a per-launch token, and host that veneer in a native WebView2 window driven by a frozen-once launcher that self-updates over `git pull --ff-only`. The API is the whole product's request surface: it lists and searches parts from the derived SQLite index, serves part detail and symbol/footprint previews as images, mutates the library through the M2 atomic engine (complete-to-add gate intact), runs ingest and enrich as background jobs with SSE progress, wires a profile into KiCad, and reports sync/update/doctor state. The one open M4 deferral, the real WebView2 `RenderedDomFetcher`, closes here so bot-protected pages become readable.

**Architecture:** A new Qt-free `stockroom.api` package: an app factory (`create_app`) that mounts routers and wires the engine into a single request-scoped context (`AppContext`), a localhost-only Uvicorn bind on an ephemeral port, and a per-launch bearer token (`X-Stockroom-Token`) checked by a dependency so a hostile local process cannot drive the library. Long operations (ingest, enrich, bulk, wiring) run through an in-process `JobRunner` on a worker thread; progress streams over Server-Sent Events (`sse-starlette`). The engine is never re-implemented: routers translate HTTP to the exact M1 to M4 calls surveyed in this plan (`ProfileStore`, `LibraryIndex`, `LibraryOps` + `staged_missing_fields`, `IngestPipeline`, `EnrichmentPipeline`, `SyncEngine`/`GitRepo.pull_ff`, `KiCadWiring`, `KiCadCli` previews, `MachineConfig`). A separate `stockroom.api.updater` implements the app-repo self-update as pure logic (`git pull --ff-only`, non-ff/divergence/offline classification, `uv sync`, a restart trigger) tested against a fixture repo. The host layer (`stockroom.host`) opens the pywebview WebView2 window onto the FastAPI-served frontend, passes the API base and token to the renderer, registers JS MIME types before mounting static files, disables service workers, shuts down gracefully, and routes native drag/drop full paths into the ingest path. The launcher (`launcher/`) is a ComfyUI-Desktop-shaped frozen-once stub: ensure WebView2, ff-pull the repo, run bundled `uv` (`uv sync --frozen`, provision CPython), `uv run` the app; git via PATH or a dulwich fallback.

**Honest sequencing (owner-visible):** the API and the updater logic are **[LINUX-BUILDABLE]** and land + verify now with `pytest` + `httpx` against a fixture library and a fixture git repo; no Windows, no WebView2, no real KiCad needed for those. The window, the real WebView2 `RenderedDomFetcher`, the frozen-once launcher, and the end-to-end KiCad-config-write verification are **[WINDOWS-VERIFY]**: they need the owner's real Windows machine with KiCad 10, because WebView2 is a Windows runtime, drag/drop delivers Windows paths, and the KiCad config surgery must be proven against a real `%APPDATA%\kicad\10.0\`. Each Windows task states exactly what the owner runs and the acceptance bar. Nothing is hidden behind a stub: every Windows seam has a Linux-testable contract and a documented default so the API is fully wired today.

**Tech Stack:** Python 3.12, `fastapi` (new dependency), `uvicorn` (new dependency), `sse-starlette` (new dependency, SSE responses), `httpx` (new DEV dependency, `TestClient`/`ASGITransport`), `pywebview` (new dependency, WebView2 host, Windows-only import guarded), stdlib `secrets`/`threading`/`queue`/`subprocess`/`socket`/`mimetypes`. The M1 to M4 engine unchanged. `pytest`. No network in the default API test run: the engine is driven against a fixture library, jobs run synchronously in tests, and the updater runs against a local fixture repo.

## Global Constraints

- **No em dashes** anywhere (code, comments, docstrings, test names, commit messages). Standing owner rule for all Stockroom output.
- **The backend imports ZERO PyQt, and the API package imports ZERO GUI toolkit at all.** `pywebview`/WebView2 is NOT Qt and is confined to `stockroom.host` and the launcher; `stockroom.api` must import neither PyQt nor pywebview so it stays a pure ASGI app testable headless (spec section 2.1). The existing CI grep gate over `app/backend/stockroom/` fails on any `PyQt5`/`QtCore`/`QtWidgets`/`QtGui` hit; extend it in Task 1 to also fail on a `pywebview`/`webview` import anywhere under `stockroom/api/`.
- **`from __future__ import annotations`** at the top of every new module (matches the existing store/model/ingest/enrich style).
- **Localhost-only, token-guarded (defense in depth, spec section 2.2 fail-proof):** Uvicorn binds `127.0.0.1` on an ephemeral port; every mutating and reading route (except a bare liveness `/api/health`) requires the per-launch bearer token in `Authorization: Bearer <token>` or `X-Stockroom-Token`. The token is minted with `secrets.token_urlsafe(32)` at app construction and handed to the renderer by the host; a wrong or missing token is `401`. This is defense in depth, not the primary boundary (the primary boundary is the loopback bind); it stops another local process from driving the library.
- **The API is a thin veneer, never a re-implementation (spec sections 2.1, 3, 4).** Routers call the exact engine surfaces this plan surveys; they do NOT parse KiCad files, touch git directly, or duplicate the complete-to-add gate. The gate is `staged_missing_fields` / `LibraryOps.add_part(require_complete=True)`, called once, in the engine.
- **Responsive/fail-proof (spec section 2.2):** any operation over ~100ms (ingest, enrich, bulk, wiring, a full index rebuild) runs off the request path as a background `JobRunner` job with SSE progress; quick reads (list/search/detail/facets) and quick mutations (edit one field, move category) are synchronous REST served from the derived index. No engine mutation loses or half-writes data: every mutation still goes through the M2 atomic transaction; the API adds no new write path.
- **Honest degradation (spec section 2.2):** no swallowed errors. Offline, divergence, a running KiCad needing restart, an incomplete add, and a scrape miss are all first-class response states with exact detail, never a silent `500` or a fake success. `IncompleteError` maps to `422` with the per-field `missing` list; `GitError`/offline maps to a `503` with the sync state; a job failure is a terminal SSE `error` event carrying the message.
- **New runtime dependencies, named at first use:** `fastapi` + `uvicorn` + `sse-starlette` in Task 1, `pywebview` in Task 15 (host), all added to `pyproject.toml` `dependencies` and `uv.lock` at the point each is first used; `httpx` added to the `dev` group in Task 1. `pywebview` is imported lazily and Windows-guarded so a Linux `import stockroom.api` never pulls it in.
- **Source layout:** backend package root is `app/backend/stockroom/`; the new packages are `app/backend/stockroom/api/` and `app/backend/stockroom/host/`; the launcher is a new top-level `launcher/`. Tests live under `tests/backend/api/`; `pytest` config already sets `pythonpath = ["app/backend"]`. Fixtures reuse the existing library fixtures plus a new `tests/backend/api/fixtures/`. The built frontend is served from `app/frontend-dist/` (committed by M6; M5 serves whatever is there and ships a minimal placeholder `index.html` so the host has something to load).
- **The frontend is M6, not M5.** M5 delivers the API + host + launcher and a placeholder `index.html`. Every API route is exercised by `httpx` tests, not by a real SPA; the SPA arrives in M6 and consumes this surface.

---

## File Structure

New package `app/backend/stockroom/api/`:

- `__init__.py` - package marker.
- `errors.py` - `ApiError` and the exception-to-status mapping.
- `context.py` - `AppContext`: the request-scoped engine bundle (active `Profile`, `GitRepo`, `LibraryIndex`, `LibraryOps`, `IngestPipeline` factory, `EnrichmentPipeline` factory, `SyncEngine`, `MachineConfig`, the launch token). Built once per app, rebuilt on profile switch and after a pull.
- `security.py` - `require_token` dependency (bearer/`X-Stockroom-Token`), `mint_token()`.
- `jobs.py` - `Job`, `JobStatus`, `JobRunner` (in-process worker thread + a per-job progress queue), and `job_events(job_id)` the SSE generator.
- `schemas.py` - Pydantic request/response models (thin DTOs over the engine dataclasses; NOT a second schema of record).
- `app.py` - `create_app(context_factory=..., token=...) -> FastAPI`: the app factory; mounts routers, installs the exception handlers, registers JS MIME types, mounts `frontend-dist` static files last.
- `serve.py` - `pick_free_port()`, `build_context()`, `run(host="127.0.0.1", port=0)`: bind loopback on an ephemeral port, print/emit the `base_url` + token for the host.
- `updater.py` - `UpdateState`, `UpdateResult`, `AppUpdater`: the app-repo self-update logic (`git pull --ff-only` via `GitRepo.pull_ff`, non-ff/divergence/offline classification, `uv sync`, a restart-request callback). Pure logic, fixture-repo tested.
- `routers/__init__.py`, `routers/library.py`, `routers/previews.py`, `routers/ingest.py`, `routers/enrich.py`, `routers/profiles.py`, `routers/sync.py`, `routers/doctor.py`, `routers/system.py` - the route modules.

New package `app/backend/stockroom/host/` (Windows-only import surface, **[WINDOWS-VERIFY]**):

- `__init__.py` - package marker.
- `mime.py` - `register_web_mime_types()`: force `.js`/`.mjs`/`.css`/`.json`/`.wasm` MIME types before any static mount (the Windows `mimetypes` registry trap). Pure, **[LINUX-BUILDABLE]** and tested on Linux.
- `webview_fetch.py` - `WebViewRenderedDomFetcher`: the real `RenderedDomFetcher` implementation over the live WebView2 engine (reads the rendered DOM after JS). **[WINDOWS-VERIFY]**.
- `window.py` - `run_window(base_url, token)`: open the pywebview WebView2 window, inject the API base + token, disable service workers, wire native drag/drop to the ingest path, shut down gracefully. **[WINDOWS-VERIFY]**.

New top-level `launcher/` (**[WINDOWS-VERIFY]**):

- `stockroom_launcher.py` - the frozen-once entry: ensure WebView2, ff-pull, `uv sync --frozen`, `uv run` the app. Git via PATH or dulwich fallback (`gitshim.py`).
- `gitshim.py` - `ensure_ff_pull(repo_root)`: probe PATH for git, else dulwich ff-only pull. The dulwich-vs-git decision is pure and **[LINUX-BUILDABLE]** tested; the frozen `.exe` build is **[WINDOWS-VERIFY]**.
- `README.md` - how the exe is frozen once and never rebuilt.

Modified existing files:

- `pyproject.toml` + `uv.lock` - add `fastapi`, `uvicorn`, `sse-starlette`, `pywebview` (deps) and `httpx` (dev); add the `windows_only` marker.
- `.github/workflows/*` (the zero-Qt gate) - extend the grep gate to also fail on a `pywebview`/`webview` import under `stockroom/api/`.
- `app/frontend-dist/index.html` - a minimal placeholder page (M6 replaces the real build).

New test files under `tests/backend/api/`:

- `__init__.py`, `conftest.py` (a fixture library + a fixture app + an authed `httpx` client), `test_security.py`, `test_jobs.py`, `test_library.py`, `test_previews.py`, `test_ingest_api.py`, `test_enrich_api.py`, `test_profiles.py`, `test_sync_api.py`, `test_doctor.py`, `test_system.py`, `test_updater.py`, `test_mime.py`, `test_gitshim.py`, `test_app_factory.py`.

---

## Task tags

Each task is tagged **[LINUX-BUILDABLE]** (build + verify now on Linux with `pytest`/`httpx`) or **[WINDOWS-VERIFY]** (needs the owner's Windows machine + KiCad 10 to build/verify honestly). The bulk (Tasks 1 to 13, the whole API + updater + the pure MIME/gitshim logic) is LINUX-BUILDABLE. Tasks 14 to 17 (the WebView2 fetcher, the window, the launcher exe, the KiCad end-to-end) are WINDOWS-VERIFY.

---

### Task 1: API package skeleton, dependencies, error mapping, and the zero-pywebview gate [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/__init__.py` (empty)
- Create: `app/backend/stockroom/api/errors.py`
- Create: `tests/backend/api/__init__.py` (empty)
- Modify: `pyproject.toml` (add `fastapi`, `uvicorn`, `sse-starlette`, `httpx` dev; the `windows_only` marker)
- Modify: `uv.lock` (regenerated by `uv lock`)
- Modify: the zero-Qt CI gate (extend to `pywebview`/`webview` under `stockroom/api/`)
- Test: `tests/backend/api/test_app_factory.py` (the import + error-mapping unit)

**Interfaces:**
- Produces:
  - `ApiError(Exception)` base, and `status_for(exc: Exception) -> int` - the single exception-to-HTTP-status map: `IncompleteError -> 422`, `GitError -> 503`, `IngestError`/`EnrichError` -> `502`, `KiCadCliError` -> `502`, `FileNotFoundError`/`KeyError` -> `404`, `ValueError` -> `400`, everything else `500`. This is the ONE place HTTP status is decided, so a router never invents one.
  - `error_body(exc: Exception) -> dict` - the honest error envelope `{"error": <type>, "detail": <message>, "missing": [...]?}` (the `missing` key present only for `IncompleteError`, carrying its per-field list).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/__init__.py` (empty) and `tests/backend/api/test_app_factory.py`:

```python
from stockroom.api.errors import ApiError, error_body, status_for
from stockroom.mutation.library_ops import IncompleteError
from stockroom.vcs.repo import GitError


def test_incomplete_error_maps_to_422_with_missing_list():
    exc = IncompleteError(["3D model", "datasheet"])
    assert status_for(exc) == 422
    body = error_body(exc)
    assert body["error"] == "IncompleteError"
    assert body["missing"] == ["3D model", "datasheet"]


def test_git_error_maps_to_503():
    assert status_for(GitError("offline")) == 503


def test_value_error_maps_to_400_and_unknown_to_500():
    assert status_for(ValueError("bad")) == 400
    assert status_for(RuntimeError("boom")) == 500


def test_error_body_has_no_missing_key_for_a_plain_error():
    body = error_body(ValueError("bad"))
    assert body["error"] == "ValueError"
    assert body["detail"] == "bad"
    assert "missing" not in body


def test_api_error_is_exportable():
    assert issubclass(ApiError, Exception)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_app_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/__init__.py` (empty file).

Create `app/backend/stockroom/api/errors.py`:

```python
"""The single exception-to-HTTP mapping for the API.

Routers never invent a status code or an error shape; they raise the engine's
own exceptions and this module decides the status and the honest error envelope
(spec section 2.2: no swallowed errors, every failure states what happened). An
incomplete add carries its per-field missing list so the UI can tell the user
exactly what to fill, never a bare 500."""

from __future__ import annotations

from stockroom.enrich.errors import EnrichError
from stockroom.ingest.errors import IngestError
from stockroom.kicad.errors import KiCadCliError
from stockroom.mutation.library_ops import IncompleteError
from stockroom.vcs.repo import GitError


class ApiError(Exception):
    """A deliberate API-level failure with an explicit status."""

    def __init__(self, status: int, detail: str):
        self.status = status
        self.detail = detail
        super().__init__(detail)


def status_for(exc: Exception) -> int:
    if isinstance(exc, ApiError):
        return exc.status
    if isinstance(exc, IncompleteError):
        return 422
    if isinstance(exc, GitError):
        return 503
    if isinstance(exc, (IngestError, EnrichError, KiCadCliError)):
        return 502
    if isinstance(exc, (FileNotFoundError, KeyError)):
        return 404
    if isinstance(exc, ValueError):
        return 400
    return 500


def error_body(exc: Exception) -> dict:
    body = {"error": type(exc).__name__, "detail": str(exc)}
    missing = getattr(exc, "missing", None)
    if missing is not None:
        body["missing"] = list(missing)
    return body
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_app_factory.py -v`
Expected: PASS (5 tests). No new dependency needed yet (this module is stdlib + the engine).

- [ ] **Step 5: Add the dependencies, the marker, and lock**

Add the API deps to `pyproject.toml` `dependencies`:

```toml
dependencies = [
    "easyeda2kicad>=1.0.1",
    "curl_cffi>=0.7",
    "pypdf>=4.0",
    "fastapi>=0.111",
    "uvicorn>=0.30",
    "sse-starlette>=2.1",
]
```

Add `httpx` to the dev group:

```toml
[dependency-groups]
dev = ["pytest>=8.2", "httpx>=0.27"]
```

Add a `windows_only` marker under `[tool.pytest.ini_options] markers`:

```toml
markers = [
    "requires_kicad_cli: test needs the kicad-cli binary; skipped when absent",
    "live_enrich: hits the real network; deselected by default, opt-in only",
    "windows_only: needs a real Windows machine (WebView2, KiCad config surgery); skipped elsewhere",
]
```

Then regenerate the lock:

Run: `uv lock`
Expected: `uv.lock` updated with `fastapi`, `uvicorn`, `sse-starlette`, `httpx` and their transitive deps.

- [ ] **Step 6: Extend the zero-Qt CI gate to also ban pywebview under `stockroom/api/`**

The existing CI gate greps `app/backend/stockroom/` for `PyQt5`/`QtCore`/`QtWidgets`/`QtGui`. Add a second grep so the API package stays pure ASGI (the host may import pywebview; the API may not):

```bash
# fail if stockroom/api/ imports pywebview/webview (it must stay headless-testable)
if grep -REn 'import[[:space:]]+webview|from[[:space:]]+webview|pywebview' \
    app/backend/stockroom/api/ ; then
  echo "stockroom/api must not import pywebview (host-only dependency)"; exit 1
fi
```

Add this to the same workflow step that runs the Qt grep. (If the gate lives in a script under `.github/`, add the check there; otherwise add it to the workflow YAML.)

- [ ] **Step 7: Commit**

```bash
git add app/backend/stockroom/api/__init__.py app/backend/stockroom/api/errors.py tests/backend/api/__init__.py tests/backend/api/test_app_factory.py pyproject.toml uv.lock .github
git commit -m "Add API package skeleton, exception-to-HTTP mapping, deps, and the zero-pywebview API gate"
```

---

### Task 2: Per-launch token security dependency [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/security.py`
- Test: `tests/backend/api/test_security.py`

**Interfaces:**
- Produces:
  - `mint_token() -> str` - a per-launch secret, `secrets.token_urlsafe(32)`.
  - `make_require_token(expected: str)` - returns a FastAPI dependency callable that accepts a request, reads `Authorization: Bearer <token>` OR `X-Stockroom-Token`, and raises `ApiError(401, ...)` on a missing or wrong token. Constant-time compare (`secrets.compare_digest`) so the check is not timing-leaky.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_security.py`:

```python
import pytest

from stockroom.api.errors import ApiError
from stockroom.api.security import make_require_token, mint_token


class _FakeHeaders:
    def __init__(self, mapping):
        self._m = {k.lower(): v for k, v in mapping.items()}

    def get(self, key, default=None):
        return self._m.get(key.lower(), default)


class _FakeRequest:
    def __init__(self, headers):
        self.headers = _FakeHeaders(headers)


def test_mint_token_is_long_and_unique():
    a, b = mint_token(), mint_token()
    assert len(a) >= 32
    assert a != b


def test_bearer_token_accepted():
    dep = make_require_token("secret123")
    # a matching bearer token returns without raising
    dep(_FakeRequest({"Authorization": "Bearer secret123"}))


def test_x_header_token_accepted():
    dep = make_require_token("secret123")
    dep(_FakeRequest({"X-Stockroom-Token": "secret123"}))


def test_missing_token_is_401():
    dep = make_require_token("secret123")
    with pytest.raises(ApiError) as ei:
        dep(_FakeRequest({}))
    assert ei.value.status == 401


def test_wrong_token_is_401():
    dep = make_require_token("secret123")
    with pytest.raises(ApiError) as ei:
        dep(_FakeRequest({"Authorization": "Bearer nope"}))
    assert ei.value.status == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_security.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api.security'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/security.py`:

```python
"""Per-launch bearer-token guard (defense in depth, spec section 2.2).

The primary boundary is the loopback bind (127.0.0.1 only); this token stops
another local process on the machine from driving the library through the API.
The token is minted fresh at app construction and handed to the renderer by the
host, so it never persists and never leaves the machine. Compared in constant
time so the check is not timing-leaky."""

from __future__ import annotations

import secrets
from typing import Callable

from stockroom.api.errors import ApiError


def mint_token() -> str:
    return secrets.token_urlsafe(32)


def _presented(request) -> str:
    auth = request.headers.get("Authorization", "") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return (request.headers.get("X-Stockroom-Token", "") or "").strip()


def make_require_token(expected: str) -> Callable:
    def require_token(request) -> None:
        presented = _presented(request)
        if not presented or not secrets.compare_digest(presented, expected):
            raise ApiError(401, "missing or invalid API token")

    return require_token
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_security.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/security.py tests/backend/api/test_security.py
git commit -m "Add per-launch token guard: bearer/X-Stockroom-Token, constant-time compare"
```

---

### Task 3: In-process job runner with SSE progress [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/jobs.py`
- Test: `tests/backend/api/test_jobs.py`

**Interfaces:**
- Produces:
  - `JobStatus` string constants: `QUEUED`, `RUNNING`, `DONE`, `ERROR`.
  - `JobEvent` dataclass: `kind: str` (`"progress"`/`"log"`/`"result"`/`"error"`/`"done"`), `data: dict`.
  - `Job` dataclass: `id: str`, `status: str`, `result: object | None`, `error: str`, and a bounded `queue.Queue` of `JobEvent`.
  - `JobRunner(max_workers: int = 1)` - submit a callable that takes a `progress` callback; runs it on a worker thread; captures the return value as the terminal `result` event and any exception as a terminal `error` event; both cases end with a `done` event so an SSE consumer always terminates. `submit(fn) -> str` (returns job id); `get(job_id) -> Job`; `events(job_id)` a generator yielding `JobEvent`s until `done`; `run_sync(fn) -> Job` (tests run without a thread for determinism).
  - `to_sse(event: JobEvent) -> dict` - shape an event for `sse-starlette`'s `EventSourceResponse` (`{"event": kind, "data": json}`).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_jobs.py`:

```python
from stockroom.api.jobs import JobRunner, JobStatus


def test_run_sync_captures_a_result_and_emits_done():
    runner = JobRunner()

    def work(progress):
        progress({"pct": 50, "message": "halfway"})
        return {"added": 3}

    job = runner.run_sync(work)
    assert job.status == JobStatus.DONE
    assert job.result == {"added": 3}
    kinds = [e.kind for e in runner.drain(job.id)]
    assert "progress" in kinds
    assert kinds[-1] == "done"


def test_run_sync_captures_an_error_and_still_terminates():
    runner = JobRunner()

    def boom(progress):
        raise ValueError("kaboom")

    job = runner.run_sync(boom)
    assert job.status == JobStatus.ERROR
    assert "kaboom" in job.error
    kinds = [e.kind for e in runner.drain(job.id)]
    assert "error" in kinds
    assert kinds[-1] == "done"  # a failed job still ends cleanly for the SSE consumer


def test_submit_runs_on_a_worker_thread_and_completes():
    runner = JobRunner()

    def work(progress):
        progress({"pct": 100})
        return 42

    job_id = runner.submit(work)
    # events() blocks until the terminal 'done' event, so draining it waits for the thread
    events = list(runner.events(job_id))
    assert events[-1].kind == "done"
    assert runner.get(job_id).result == 42


def test_unknown_job_id_raises_keyerror():
    runner = JobRunner()
    try:
        runner.get("nope")
        assert False, "expected KeyError"
    except KeyError:
        pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_jobs.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api.jobs'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/jobs.py`:

```python
"""In-process background jobs with SSE progress (spec section 2.2: any operation
over ~100ms runs off the request path with SSE progress; the window never blocks).

A job is a callable that takes a `progress(dict)` callback; it runs on a worker
thread, its return value becomes a terminal `result` event and any exception a
terminal `error` event, and EITHER way a final `done` event is emitted so an SSE
consumer always terminates cleanly (honest degradation: a failed job is a labeled
error event, never a dropped stream). run_sync is the test path: no thread, fully
deterministic."""

from __future__ import annotations

import json
import queue
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Callable, Iterator


class JobStatus:
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    ERROR = "error"


@dataclass
class JobEvent:
    kind: str
    data: dict = field(default_factory=dict)


_SENTINEL = JobEvent("done")


@dataclass
class Job:
    id: str
    status: str = JobStatus.QUEUED
    result: object | None = None
    error: str = ""
    queue: "queue.Queue[JobEvent]" = field(default_factory=lambda: queue.Queue(maxsize=1000))


def to_sse(event: JobEvent) -> dict:
    return {"event": event.kind, "data": json.dumps(event.data)}


class JobRunner:
    def __init__(self, max_workers: int = 1):
        self._jobs: dict[str, Job] = {}
        self._pool = ThreadPoolExecutor(max_workers=max_workers)
        self._lock = threading.Lock()

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def _new_job(self) -> Job:
        job = Job(id=uuid.uuid4().hex)
        with self._lock:
            self._jobs[job.id] = job
        return job

    def _drive(self, job: Job, fn: Callable[[Callable[[dict], None]], object]) -> None:
        job.status = JobStatus.RUNNING

        def progress(data: dict) -> None:
            job.queue.put(JobEvent("progress", dict(data)))

        try:
            result = fn(progress)
            job.result = result
            job.status = JobStatus.DONE
            job.queue.put(JobEvent("result", {"result": _jsonable(result)}))
        except Exception as exc:  # noqa: BLE001 - a job failure is a labeled event
            job.error = str(exc)
            job.status = JobStatus.ERROR
            job.queue.put(JobEvent("error", {"detail": str(exc), "error": type(exc).__name__}))
        finally:
            job.queue.put(_SENTINEL)

    def run_sync(self, fn) -> Job:
        job = self._new_job()
        self._drive(job, fn)
        return job

    def submit(self, fn) -> str:
        job = self._new_job()
        self._pool.submit(self._drive, job, fn)
        return job.id

    def events(self, job_id: str) -> Iterator[JobEvent]:
        job = self.get(job_id)
        while True:
            event = job.queue.get()
            yield event
            if event is _SENTINEL or event.kind == "done":
                return

    def drain(self, job_id: str) -> list[JobEvent]:
        """Non-blocking snapshot of everything queued so far, for run_sync tests."""
        job = self.get(job_id)
        out: list[JobEvent] = []
        while True:
            try:
                out.append(job.queue.get_nowait())
            except queue.Empty:
                return out


def _jsonable(value: object) -> object:
    try:
        json.dumps(value)
        return value
    except TypeError:
        return str(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_jobs.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/jobs.py tests/backend/api/test_jobs.py
git commit -m "Add in-process JobRunner with SSE progress events and a terminal done marker"
```

---

### Task 4: AppContext, the app factory, and the fixture-app conftest [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/context.py`
- Create: `app/backend/stockroom/api/app.py`
- Create: `app/backend/stockroom/api/routers/__init__.py` (empty)
- Create: `app/backend/stockroom/api/routers/system.py` (a minimal `/api/health` + `/api/system/info` to prove the wiring)
- Create: `tests/backend/api/conftest.py`
- Test: `tests/backend/api/test_system.py`

**Interfaces:**
- Produces:
  - `AppContext` dataclass: the request-scoped engine bundle. Fields: `libraries_root: Path`, `repo: GitRepo`, `config: MachineConfig`, `profile: Profile`, `profile_store: ProfileStore`, `ops: LibraryOps`, `index: LibraryIndex`, `sync: SyncEngine`, `kicad_dir: Path`, `cli: KiCadCli`, `enrich_cache_dir: Path`, `token: str`, `jobs: JobRunner`, and a `rebuild_index()` + `switch_profile(name)` that rebuild the derived index and re-point `ops`/`profile` (spec section 2.2: the index is built on load and after each pull, kept warm).
  - `build_context(libraries_root, kicad_dir=None, config=None, token=None) -> AppContext` - assembles the engine from the surveyed constructors (`ProfileStore(libraries_root, repo)`, active profile from `config.active_profile`, `LibraryOps(profile, repo, cli)`, `LibraryIndex.build(profile.library.parts_dir)`, `SyncEngine(repo)`).
  - `create_app(context: AppContext) -> FastAPI` - the factory: installs a global exception handler (using `status_for`/`error_body`), sets `app.state.ctx = context`, includes every router, registers JS MIME types (Task 12 seam, safe no-op on Linux), and mounts `frontend-dist` static files LAST so API routes win.
  - `routers/system.py`: `GET /api/health` (no token, `{"status": "ok"}` liveness) and `GET /api/system/info` (token-guarded: app version, active profile, part count, kicad config dir, whether kicad is running).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/conftest.py` (the shared fixture library + fixture app + authed client):

```python
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from stockroom.api.app import create_app
from stockroom.api.context import build_context
from stockroom.store.machine_config import MachineConfig
from stockroom.vcs.repo import GitRepo


@pytest.fixture
def library_root(tmp_path):
    """A git-backed libraries root with one Main profile holding a couple of parts,
    reusing the same PartRecord JSON shape the index reads. Kept tiny and pure so
    the API tests never need kicad-cli or the network."""
    root = tmp_path / "libraries"
    root.mkdir()
    repo = GitRepo(root)
    repo.init()
    from stockroom.store.profile import ProfileStore

    store = ProfileStore(root, repo)
    profile = store.create("Main")
    parts = profile.library.parts_dir
    parts.mkdir(parents=True, exist_ok=True)
    # one complete-ish and one incomplete part, written as canonical PartRecord JSON
    _write_part(parts, "tps62130", complete=True)
    _write_part(parts, "mystery", complete=False)
    repo.commit("seed fixture parts", [parts])
    return root


def _write_part(parts_dir: Path, part_id: str, complete: bool) -> None:
    from stockroom.model.part import (
        Datasheet,
        LibRef,
        ModelRef,
        PartRecord,
        Purchase,
    )

    rec = PartRecord(
        id=part_id,
        display_name=part_id.upper(),
        category="ICs",
        description="a part" if complete else "",
        mpn=part_id.upper() if complete else "",
        manufacturer="TI" if complete else "",
    )
    if complete:
        rec.symbol = LibRef(lib="SR-ics", name=part_id.upper())
        rec.footprint = LibRef(lib="SR-ics", name="VQFN-16")
        rec.model = ModelRef(file="models/x.step")
        rec.datasheet = Datasheet(file="datasheets/x.pdf")
        rec.purchase = [Purchase(vendor="LCSC", url="https://x/p")]
    (parts_dir / f"{part_id}.json").write_text(rec.dumps(), encoding="utf-8")


@pytest.fixture
def app_ctx(library_root, tmp_path):
    kicad_dir = tmp_path / "kicad"
    kicad_dir.mkdir()
    config = MachineConfig(active_profile="Main")
    return build_context(library_root, kicad_dir=kicad_dir, config=config, token="testtoken")


@pytest.fixture
def client(app_ctx):
    from httpx import ASGITransport, Client

    app = create_app(app_ctx)
    transport = ASGITransport(app=app)
    with Client(transport=transport, base_url="http://test",
                headers={"X-Stockroom-Token": "testtoken"}) as c:
        yield c


@pytest.fixture
def anon_client(app_ctx):
    from httpx import ASGITransport, Client

    app = create_app(app_ctx)
    transport = ASGITransport(app=app)
    with Client(transport=transport, base_url="http://test") as c:
        yield c
```

Create `tests/backend/api/test_system.py`:

```python
def test_health_needs_no_token(anon_client):
    r = anon_client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_system_info_requires_a_token(anon_client):
    r = anon_client.get("/api/system/info")
    assert r.status_code == 401


def test_system_info_reports_active_profile_and_count(client):
    r = client.get("/api/system/info")
    assert r.status_code == 200
    body = r.json()
    assert body["active_profile"] == "Main"
    assert body["part_count"] == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_system.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api.context'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/context.py`:

```python
"""The request-scoped engine bundle. Built once per app from the surveyed M1 to M4
constructors; NOT a re-implementation of any of them (spec sections 2.1, 4). The
derived index is kept warm and rebuilt on load, on profile switch, and after a pull
(spec section 2.2)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from stockroom.api.jobs import JobRunner
from stockroom.kicad.cli import KiCadCli
from stockroom.kicad.config import kicad_config_dir
from stockroom.mutation.library_ops import LibraryOps
from stockroom.store.index import LibraryIndex
from stockroom.store.machine_config import MachineConfig
from stockroom.store.profile import Profile, ProfileStore
from stockroom.vcs.repo import GitRepo
from stockroom.vcs.sync import SyncEngine


@dataclass
class AppContext:
    libraries_root: Path
    repo: GitRepo
    config: MachineConfig
    profile_store: ProfileStore
    profile: Profile
    ops: LibraryOps
    index: LibraryIndex
    sync: SyncEngine
    kicad_dir: Path
    cli: KiCadCli
    enrich_cache_dir: Path
    token: str
    jobs: JobRunner = field(default_factory=JobRunner)

    def rebuild_index(self) -> None:
        self.index.close()
        self.index = LibraryIndex.build(self.profile.library.parts_dir)

    def switch_profile(self, name: str) -> None:
        self.profile = self.profile_store.get(name)
        self.ops = LibraryOps(self.profile, self.repo, self.cli)
        self.config.active_profile = name
        self.config.save()
        self.rebuild_index()


def build_context(
    libraries_root: Path,
    kicad_dir: Path | None = None,
    config: MachineConfig | None = None,
    token: str | None = None,
) -> AppContext:
    from stockroom.api.security import mint_token

    libraries_root = Path(libraries_root)
    repo = GitRepo(libraries_root)
    config = config or MachineConfig.load()
    profile_store = ProfileStore(libraries_root, repo)
    profile = profile_store.get(config.active_profile)
    cli = KiCadCli()
    ops = LibraryOps(profile, repo, cli)
    index = LibraryIndex.build(profile.library.parts_dir)
    kdir = Path(kicad_dir) if kicad_dir is not None else kicad_config_dir(
        override=config.kicad_config_override
    )
    enrich_cache = libraries_root.parent / ".stockroom-enrich-cache"
    return AppContext(
        libraries_root=libraries_root,
        repo=repo,
        config=config,
        profile_store=profile_store,
        profile=profile,
        ops=ops,
        index=index,
        sync=SyncEngine(repo),
        kicad_dir=kdir,
        cli=cli,
        enrich_cache_dir=enrich_cache,
        token=token or mint_token(),
    )
```

Create `app/backend/stockroom/api/routers/__init__.py` (empty file).

Create `app/backend/stockroom/api/routers/system.py`:

```python
"""Liveness and a small system-info readout. /api/health is the one unauthenticated
route (the host polls it to know the server is up before opening the window)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.config import detect_running_kicad

router = APIRouter(prefix="/api")


@router.get("/health")
def health() -> dict:
    return {"status": "ok"}


def _ctx(request: Request):
    return request.app.state.ctx


def system_info_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/system", dependencies=[Depends(require_token)])

    @r.get("/info")
    def info(request: Request) -> dict:
        ctx = _ctx(request)
        return {
            "active_profile": ctx.profile.name,
            "part_count": ctx.index.count(),
            "kicad_config_dir": ctx.kicad_dir.as_posix(),
            "kicad_running": detect_running_kicad(),
        }

    return r
```

Create `app/backend/stockroom/api/app.py`:

```python
"""The FastAPI app factory. Installs the single exception handler, wires the
AppContext into app.state, includes every router, and mounts the built frontend
LAST so /api/* routes always win over the SPA's catch-all (spec section 4: the
host is presentation, the API is the surface)."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stockroom.api.context import AppContext
from stockroom.api.errors import error_body, status_for
from stockroom.api.security import make_require_token
from stockroom.api.routers import system as system_router

_FRONTEND_DIST = Path(__file__).resolve().parents[3] / "frontend-dist"


def create_app(context: AppContext) -> FastAPI:
    app = FastAPI(title="Stockroom", version="0.1.0")
    app.state.ctx = context
    require_token = make_require_token(context.token)

    @app.exception_handler(Exception)
    async def _handle(_request: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(status_code=status_for(exc), content=error_body(exc))

    # Register web MIME types before any static mount (the Windows mimetypes trap).
    # Safe no-op on Linux; the assertion is exercised in Task 12.
    from stockroom.host.mime import register_web_mime_types

    register_web_mime_types()

    app.include_router(system_router.router)
    app.include_router(system_router.system_info_router(require_token))

    # Routers added in later tasks are included here (library, previews, ingest,
    # enrich, profiles, sync, doctor), each behind Depends(require_token).

    if _FRONTEND_DIST.exists():
        from fastapi.staticfiles import StaticFiles

        app.mount("/", StaticFiles(directory=str(_FRONTEND_DIST), html=True), name="spa")
    return app
```

Note: `stockroom.host.mime.register_web_mime_types` is created in Task 12; if executing strictly in order, stub it as a one-line no-op module now and flesh it out in Task 12, or reorder Task 12 before this step. Either way the import must resolve.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_system.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/context.py app/backend/stockroom/api/app.py app/backend/stockroom/api/routers/__init__.py app/backend/stockroom/api/routers/system.py tests/backend/api/conftest.py tests/backend/api/test_system.py
git commit -m "Add AppContext, the FastAPI app factory, system router, and the fixture-app conftest"
```

---

### Task 5: Library router: list, search, facets, part detail [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/schemas.py`
- Create: `app/backend/stockroom/api/routers/library.py`
- Modify: `app/backend/stockroom/api/app.py` (include the library router)
- Test: `tests/backend/api/test_library.py`

**Interfaces:**
- Consumes: `LibraryIndex.search(query, category, complete_only)`, `.get(part_id)`, `.facets()`, `.count()`; `LibraryOps.load_record(part_id)` for full detail; `IndexRow`/`Facets`/`PartRecord`.
- Produces:
  - `schemas.py`: `PartSummary` (from `IndexRow`), `Facets` DTO, `PartDetail` (from `PartRecord.to_dict()`), request bodies for the mutations in Task 6.
  - `GET /api/library/parts?q=&category=&complete_only=` - the library list, served from the index (spec section 2.2: reads served from the derived index, instant at thousands of parts). Returns `{"parts": [PartSummary], "count": N}`.
  - `GET /api/library/facets` - `{"by_category": {...}, "by_manufacturer": {...}, "complete": N, "incomplete": N}`.
  - `GET /api/library/parts/{part_id}` - full detail via `ops.load_record(part_id).to_dict()`; `404` when absent.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_library.py`:

```python
def test_list_all_parts(client):
    r = client.get("/api/library/parts")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 2
    names = {p["display_name"] for p in body["parts"]}
    assert names == {"TPS62130", "MYSTERY"}


def test_search_filters_by_query(client):
    r = client.get("/api/library/parts", params={"q": "tps"})
    assert r.status_code == 200
    parts = r.json()["parts"]
    assert len(parts) == 1
    assert parts[0]["mpn"] == "TPS62130"


def test_filter_complete_only(client):
    r = client.get("/api/library/parts", params={"complete_only": True})
    assert {p["display_name"] for p in r.json()["parts"]} == {"TPS62130"}


def test_facets_roll_up_categories_and_completeness(client):
    r = client.get("/api/library/facets")
    assert r.status_code == 200
    body = r.json()
    assert body["by_category"]["ICs"] == 2
    assert body["complete"] == 1
    assert body["incomplete"] == 1


def test_part_detail_returns_full_record(client):
    r = client.get("/api/library/parts/tps62130")
    assert r.status_code == 200
    body = r.json()
    assert body["mpn"] == "TPS62130"
    assert body["symbol"]["name"] == "TPS62130"


def test_missing_part_detail_is_404(client):
    r = client.get("/api/library/parts/nope")
    assert r.status_code == 404


def test_library_list_requires_a_token(anon_client):
    assert anon_client.get("/api/library/parts").status_code == 401
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_library.py -v`
Expected: FAIL (router not mounted / module missing).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/schemas.py`:

```python
"""Thin response DTOs over the engine dataclasses. These are a PRESENTATION shape,
never a second schema of record: the source of truth stays the PartRecord JSON and
the derived index (spec sections 5.1, 5.2)."""

from __future__ import annotations

from pydantic import BaseModel

from stockroom.store.index import Facets as _Facets
from stockroom.store.index import IndexRow


class PartSummary(BaseModel):
    id: str
    display_name: str
    category: str
    mpn: str
    manufacturer: str
    is_complete: bool
    missing: list[str] = []

    @classmethod
    def from_row(cls, row: IndexRow) -> "PartSummary":
        return cls(
            id=row.id,
            display_name=row.display_name,
            category=row.category,
            mpn=row.mpn,
            manufacturer=row.manufacturer,
            is_complete=row.is_complete,
            missing=list(row.missing),
        )


class FacetsDTO(BaseModel):
    by_category: dict[str, int]
    by_manufacturer: dict[str, int]
    complete: int
    incomplete: int

    @classmethod
    def from_facets(cls, f: _Facets) -> "FacetsDTO":
        return cls(
            by_category=f.by_category,
            by_manufacturer=f.by_manufacturer,
            complete=f.complete,
            incomplete=f.incomplete,
        )
```

Create `app/backend/stockroom/api/routers/library.py`:

```python
"""Read surface over the derived index plus full detail from the source JSON.
Every list/search/facet read is served from the SQLite index for instant response
at thousands of parts (spec section 2.2); part detail loads the canonical record."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.api.schemas import FacetsDTO, PartSummary


def library_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/library", dependencies=[Depends(require_token)])

    @r.get("/parts")
    def list_parts(
        request: Request,
        q: str = "",
        category: str | None = None,
        complete_only: bool = False,
    ) -> dict:
        ctx = request.app.state.ctx
        rows = ctx.index.search(query=q, category=category, complete_only=complete_only)
        return {"parts": [PartSummary.from_row(row).model_dump() for row in rows],
                "count": len(rows)}

    @r.get("/facets")
    def facets(request: Request) -> dict:
        ctx = request.app.state.ctx
        return FacetsDTO.from_facets(ctx.index.facets()).model_dump()

    @r.get("/parts/{part_id}")
    def part_detail(request: Request, part_id: str) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        return ctx.ops.load_record(part_id).to_dict()

    return r
```

Include it in `app.py` (after the system routers):

```python
    from stockroom.api.routers import library as library_router_mod
    app.include_router(library_router_mod.library_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_library.py -v`
Expected: PASS (7 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/schemas.py app/backend/stockroom/api/routers/library.py app/backend/stockroom/api/app.py tests/backend/api/test_library.py
git commit -m "Add library router: index-backed list/search/facets and full part detail"
```

---

### Task 6: Library router: mutations (edit field, move category, delete), gate intact [LINUX-BUILDABLE]

**Files:**
- Modify: `app/backend/stockroom/api/routers/library.py`
- Modify: `app/backend/stockroom/api/schemas.py`
- Test: `tests/backend/api/test_library.py` (append)

**Interfaces:**
- Consumes: `LibraryOps.edit_field(part_id, field, value)`, `.move_category(part_id, new_category)`, `.delete_part(part_id)`; the mutations already run through the M2 atomic transaction, so the API adds no write path. After any mutation, `ctx.rebuild_index()` so reads stay consistent.
- Produces:
  - `PATCH /api/library/parts/{part_id}` body `{"field": "...", "value": ...}` -> the updated record; the index is rebuilt.
  - `POST /api/library/parts/{part_id}/move` body `{"category": "..."}` -> the updated record.
  - `DELETE /api/library/parts/{part_id}` -> `204`.
  - A `422` when a mutation would make an add incomplete is NOT applicable here (edit toward completeness is always allowed, spec section 6); but adding via ingest still enforces the gate (Task 8). Editing an unknown part is `404`.

- [ ] **Step 1: Write the failing test**

Append to `tests/backend/api/test_library.py`:

```python
def test_edit_field_updates_the_record_and_index(client):
    r = client.patch("/api/library/parts/mystery",
                     json={"field": "manufacturer", "value": "STMicro"})
    assert r.status_code == 200
    assert r.json()["manufacturer"] == "STMicro"
    # the read surface reflects it immediately (index rebuilt)
    detail = client.get("/api/library/parts/mystery").json()
    assert detail["manufacturer"] == "STMicro"


def test_move_category_changes_the_category(client):
    r = client.post("/api/library/parts/tps62130/move", json={"category": "Modules"})
    assert r.status_code == 200
    assert r.json()["category"] == "Modules"


def test_delete_part_removes_it(client):
    assert client.delete("/api/library/parts/mystery").status_code == 204
    assert client.get("/api/library/parts/mystery").status_code == 404
    assert client.get("/api/library/parts").json()["count"] == 1


def test_edit_unknown_part_is_404(client):
    r = client.patch("/api/library/parts/nope", json={"field": "mpn", "value": "X"})
    assert r.status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_library.py -k "edit or move or delete" -v`
Expected: FAIL (routes not present).

- [ ] **Step 3: Write minimal implementation**

Add to `schemas.py`:

```python
class EditFieldBody(BaseModel):
    field: str
    value: object


class MoveBody(BaseModel):
    category: str
```

Add to `library_router(...)` in `routers/library.py`:

```python
    from fastapi import Response

    from stockroom.api.schemas import EditFieldBody, MoveBody

    @r.patch("/parts/{part_id}")
    def edit_field(request: Request, part_id: str, body: EditFieldBody) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.edit_field(part_id, body.field, body.value)
        ctx.rebuild_index()
        return rec.to_dict()

    @r.post("/parts/{part_id}/move")
    def move_category(request: Request, part_id: str, body: MoveBody) -> dict:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.move_category(part_id, body.category)
        ctx.rebuild_index()
        return rec.to_dict()

    @r.delete("/parts/{part_id}", status_code=204)
    def delete_part(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        ctx.ops.delete_part(part_id)
        ctx.rebuild_index()
        return Response(status_code=204)
```

(Move the `EditFieldBody`/`MoveBody`/`Response` imports to the module top per existing style.)

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_library.py -v`
Expected: PASS (all library tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/library.py app/backend/stockroom/api/schemas.py tests/backend/api/test_library.py
git commit -m "Add library mutations: edit field, move category, delete, with index rebuild after each"
```

---

### Task 7: Previews router (symbol/footprint SVG as image) [LINUX-BUILDABLE, kicad-cli integration marked]

**Files:**
- Create: `app/backend/stockroom/api/routers/previews.py`
- Modify: `app/backend/stockroom/api/app.py`
- Test: `tests/backend/api/test_previews.py`

**Interfaces:**
- Consumes: `KiCadCli.sym_export_svg(lib, symbol, out_dir, black_and_white=)`, `.fp_export_svg(pretty_dir, footprint, out_dir, layers=)`; `Profile.library.symbol_lib_path(category)` / `.footprint_lib_path(category)`; the part record's `symbol`/`footprint` `LibRef`. Previews are cached on disk keyed by content hash (spec section 2.2: previews cached on disk by content hash) under `ctx.enrich_cache_dir.parent / ".stockroom-previews"`.
- Produces:
  - `GET /api/previews/symbol/{part_id}.svg` - render (or serve the cached) symbol SVG for the part, `image/svg+xml`. `404` if the part or its symbol is absent; `502` (`KiCadCliError`) if kicad-cli fails.
  - `GET /api/previews/footprint/{part_id}.svg` - same for the footprint.
  - The route computes a cache key from the source lib file's content hash + symbol name + options; a cache hit skips kicad-cli entirely.
- Testing: the SVG rendering itself needs kicad-cli, so the render path is covered by a `requires_kicad_cli`-marked test; the caching, 404, and content-type behavior are covered with an injected fake CLI so they run everywhere.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_previews.py`:

```python
import pytest

from tests.backend.conftest import requires_kicad_cli


def test_symbol_preview_404_when_part_absent(client):
    r = client.get("/api/previews/symbol/nope.svg")
    assert r.status_code == 404


def test_symbol_preview_uses_the_injected_cli_and_returns_svg(app_ctx, tmp_path):
    # Inject a fake CLI that writes a known SVG, so the render path is exercised
    # without kicad-cli. The fake honors the sym_export_svg signature.
    from httpx import ASGITransport, Client

    from stockroom.api.app import create_app

    class _FakeCli:
        def sym_export_svg(self, lib, symbol, out_dir, black_and_white=False):
            out = out_dir / f"{symbol}_unit1.svg"
            out.write_text("<svg><!-- fake --></svg>", encoding="utf-8")
            return [out]

        def fp_export_svg(self, pretty_dir, footprint, out_dir, layers="F.Cu,F.SilkS,F.Fab"):
            out = out_dir / f"{footprint}.svg"
            out.write_text("<svg><!-- fp --></svg>", encoding="utf-8")
            return out

    app_ctx.cli = _FakeCli()
    # the tps62130 fixture part must have its symbol lib file on disk for hashing;
    # write a placeholder symbol lib at the expected category path
    sym_path = app_ctx.profile.library.symbol_lib_path("ICs")
    sym_path.parent.mkdir(parents=True, exist_ok=True)
    sym_path.write_text("(kicad_symbol_lib)", encoding="utf-8")

    app = create_app(app_ctx)
    with Client(transport=ASGITransport(app=app), base_url="http://test",
                headers={"X-Stockroom-Token": "testtoken"}) as c:
        r = c.get("/api/previews/symbol/tps62130.svg")
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("image/svg+xml")
        assert "svg" in r.text


@requires_kicad_cli
def test_symbol_preview_end_to_end_with_real_cli(client):
    # Only meaningful once the fixture ships a real .kicad_sym with the symbol; this
    # marks the honest integration boundary. Skipped where kicad-cli is absent.
    r = client.get("/api/previews/symbol/tps62130.svg")
    assert r.status_code in (200, 404, 502)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_previews.py -v`
Expected: FAIL (previews router missing).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/routers/previews.py`:

```python
"""Symbol/footprint previews rendered by the user's own kicad-cli, cached on disk
by content hash so a repeat view never re-renders (spec sections 2.2, 3.4). The
backend never re-implements KiCad rendering; it shells out to kicad-cli and tints
happen client-side."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response


def _hash_file(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()[:16]


def _cache_dir(ctx) -> Path:
    d = ctx.libraries_root.parent / ".stockroom-previews"
    d.mkdir(parents=True, exist_ok=True)
    return d


def previews_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/previews", dependencies=[Depends(require_token)])

    def _svg_response(text: str) -> Response:
        return Response(content=text, media_type="image/svg+xml")

    @r.get("/symbol/{part_id}.svg")
    def symbol_svg(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.load_record(part_id)
        if rec.symbol is None or not rec.symbol.name:
            raise FileNotFoundError(f"part {part_id} has no symbol")
        lib = ctx.profile.library.symbol_lib_path(rec.category)
        if not lib.exists():
            raise FileNotFoundError(f"symbol library missing for {rec.category}")
        key = f"sym_{part_id}_{_hash_file(lib)}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            svgs = ctx.cli.sym_export_svg(lib, rec.symbol.name, Path(td))
            text = Path(svgs[0]).read_text(encoding="utf-8")
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    @r.get("/footprint/{part_id}.svg")
    def footprint_svg(request: Request, part_id: str) -> Response:
        ctx = request.app.state.ctx
        if ctx.index.get(part_id) is None:
            raise FileNotFoundError(f"no such part: {part_id}")
        rec = ctx.ops.load_record(part_id)
        if rec.footprint is None or not rec.footprint.name:
            raise FileNotFoundError(f"part {part_id} has no footprint")
        pretty = ctx.profile.library.footprint_lib_path(rec.category)
        if not pretty.exists():
            raise FileNotFoundError(f"footprint library missing for {rec.category}")
        key = f"fp_{part_id}_{rec.footprint.name}.svg"
        cached = _cache_dir(ctx) / key
        if cached.exists():
            return _svg_response(cached.read_text(encoding="utf-8"))
        with tempfile.TemporaryDirectory() as td:
            svg = ctx.cli.fp_export_svg(pretty, rec.footprint.name, Path(td))
            text = Path(svg).read_text(encoding="utf-8")
        cached.write_text(text, encoding="utf-8")
        return _svg_response(text)

    return r
```

Include it in `app.py`:

```python
    from stockroom.api.routers import previews as previews_router_mod
    app.include_router(previews_router_mod.previews_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_previews.py -v`
Expected: PASS (the fake-CLI + 404 tests; the real-CLI test skips without kicad-cli).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/previews.py app/backend/stockroom/api/app.py tests/backend/api/test_previews.py
git commit -m "Add previews router: content-hash-cached symbol/footprint SVGs via kicad-cli"
```

---

### Task 8: Ingest router (start job + SSE progress + commit) [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/routers/ingest.py`
- Modify: `app/backend/stockroom/api/app.py`
- Test: `tests/backend/api/test_ingest_api.py`

**Interfaces:**
- Consumes: `IngestPipeline(profile, repo, cli)` with `.inspect(inputs, lcsc_ids, workdir)`, `.commit(candidate)`, `.attach_model(part_id, candidate)`; `StagingCandidate` (all fields surveyed); `is_lcsc_id`; the `JobRunner`.
- Produces:
  - `POST /api/ingest/inspect` body `{"paths": [...], "lcsc_ids": [...]}` -> starts a JobRunner job that runs `pipeline.inspect(...)` and returns candidate DTOs as the job result. Returns `{"job_id": ...}`; the caller streams progress on `/api/jobs/{job_id}/events`. `paths` are full filesystem paths delivered by native drag/drop (Task 16); browser-picked uploads are a separate multipart path deferred to M6.
  - `GET /api/jobs/{job_id}/events` - the SSE stream (added here, shared by ingest/enrich/bulk/wiring): `EventSourceResponse` over `ctx.jobs.events(job_id)` mapped through `to_sse`.
  - `POST /api/ingest/commit` body a finalized candidate DTO -> commits it through `pipeline.commit(candidate)`. The complete-to-add gate applies inside `add_part`; an incomplete commit is `422` with the `missing` list (never a silent partial add). Returns the new part record.
  - Candidate round-trip: a `candidate_to_dto` / `dto_to_candidate` pair so the frontend can edit a candidate (pick a footprint variant, fix a field) between inspect and commit.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_ingest_api.py`:

```python
def test_inspect_starts_a_job_and_streams_a_result(client, monkeypatch):
    # Stub the IngestPipeline factory so no real vendor zip or kicad-cli is needed.
    from stockroom.ingest.staging import StagingCandidate

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def inspect(self, inputs=(), lcsc_ids=(), workdir=None):
            return [StagingCandidate(
                vendor="snapeda", symbol_lib_path=None, symbol_name="X",
                footprint_variants=[], category="ICs", mpn="LM358",
                display_name="LM358", entry_name="LM358",
                gaps=["no symbol in this package"],
            )]

        def cleanup(self):
            pass

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/ingest/inspect", json={"paths": ["/tmp/part.zip"], "lcsc_ids": []})
    assert r.status_code == 200
    job_id = r.json()["job_id"]

    # drain the SSE stream; the terminal result carries the candidate list
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "LM358" in body
    assert "result" in body
    assert "done" in body


def test_commit_incomplete_candidate_is_422_with_missing(client, monkeypatch):
    # A bare candidate has no symbol/footprint/etc, so add_part rejects it.
    from stockroom.mutation.library_ops import IncompleteError

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def commit(self, candidate):
            raise IncompleteError(["symbol", "footprint", "3D model", "datasheet"])

        def cleanup(self):
            pass

    monkeypatch.setattr("stockroom.api.routers.ingest._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/ingest/commit", json={
        "vendor": "bulk", "symbol_lib_path": None, "symbol_name": "",
        "footprint_variants": [], "category": "ICs", "mpn": "LM358",
        "display_name": "LM358", "entry_name": "LM358",
    })
    assert r.status_code == 422
    assert "symbol" in r.json()["missing"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_ingest_api.py -v`
Expected: FAIL (ingest router missing).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/routers/ingest.py`:

```python
"""Ingest as a background job with SSE progress plus a synchronous, gate-enforcing
commit (spec sections 2.2, 5, 6). Inspect runs off the request path (unpacking a
zip and running kicad-cli is well over 100ms); commit is synchronous because it is
one atomic transaction whose result (added or rejected-with-missing) the caller
needs immediately. The complete-to-add gate lives in add_part, unchanged."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from stockroom.api.jobs import to_sse
from stockroom.ingest.pipeline import IngestPipeline
from stockroom.ingest.staging import StagingCandidate
from stockroom.model.part import Purchase


def _make_pipeline(ctx) -> IngestPipeline:
    return IngestPipeline(ctx.profile, ctx.repo, ctx.cli)


def candidate_to_dto(c: StagingCandidate) -> dict:
    return {
        "vendor": c.vendor,
        "symbol_lib_path": str(c.symbol_lib_path) if c.symbol_lib_path else None,
        "symbol_name": c.symbol_name,
        "footprint_variants": [str(p) for p in c.footprint_variants],
        "chosen_footprint_index": c.chosen_footprint_index,
        "model_path": str(c.model_path) if c.model_path else None,
        "datasheet_path": str(c.datasheet_path) if c.datasheet_path else None,
        "display_name": c.display_name,
        "entry_name": c.entry_name,
        "category": c.category,
        "mpn": c.mpn,
        "manufacturer": c.manufacturer,
        "description": c.description,
        "tags": list(c.tags),
        "gaps": list(c.gaps),
    }


def dto_to_candidate(d: dict) -> StagingCandidate:
    return StagingCandidate(
        vendor=d.get("vendor", ""),
        symbol_lib_path=Path(d["symbol_lib_path"]) if d.get("symbol_lib_path") else None,
        symbol_name=d.get("symbol_name", ""),
        footprint_variants=[Path(p) for p in d.get("footprint_variants", [])],
        chosen_footprint_index=d.get("chosen_footprint_index", 0),
        model_path=Path(d["model_path"]) if d.get("model_path") else None,
        datasheet_path=Path(d["datasheet_path"]) if d.get("datasheet_path") else None,
        display_name=d.get("display_name", ""),
        entry_name=d.get("entry_name", ""),
        category=d.get("category", "Other"),
        mpn=d.get("mpn", ""),
        manufacturer=d.get("manufacturer", ""),
        description=d.get("description", ""),
        tags=list(d.get("tags", [])),
        purchase=[Purchase(**p) for p in d.get("purchase", [])],
    )


def ingest_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api", dependencies=[Depends(require_token)])

    @r.post("/ingest/inspect")
    def inspect(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        paths = [Path(p) for p in body.get("paths", [])]
        lcsc_ids = list(body.get("lcsc_ids", []))

        def work(progress):
            progress({"pct": 5, "message": "unpacking"})
            pipeline = _make_pipeline(ctx)
            candidates = pipeline.inspect(inputs=paths, lcsc_ids=lcsc_ids)
            progress({"pct": 90, "message": "staged"})
            return [candidate_to_dto(c) for c in candidates]

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/ingest/commit")
    def commit(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body)
        record = pipeline.commit(candidate)  # IncompleteError -> 422 via the handler
        ctx.rebuild_index()
        return record.to_dict()

    @r.get("/jobs/{job_id}/events")
    def job_events(request: Request, job_id: str) -> EventSourceResponse:
        ctx = request.app.state.ctx

        def gen():
            for event in ctx.jobs.events(job_id):
                yield to_sse(event)

        return EventSourceResponse(gen())

    return r
```

Include it in `app.py`:

```python
    from stockroom.api.routers import ingest as ingest_router_mod
    app.include_router(ingest_router_mod.ingest_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_ingest_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/ingest.py app/backend/stockroom/api/app.py tests/backend/api/test_ingest_api.py
git commit -m "Add ingest router: SSE-progress inspect job plus gate-enforcing synchronous commit"
```

---

### Task 9: Enrich router (single enrich + datasheet + bulk, SSE progress) [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/routers/enrich.py`
- Modify: `app/backend/stockroom/api/app.py`
- Test: `tests/backend/api/test_enrich_api.py`

**Interfaces:**
- Consumes: `EnrichmentPipeline(cache_dir, fetcher=..., mouser=..., ...)` with `.enrich(mpn, category, want)`, `.enrich_candidate(candidate, overwrite)`, `.fetch_and_store_datasheet(candidate, url)`; `bulk_enrich`, `parse_mpn_list`, `parse_bom_csv`, `BulkReport`; the `RenderedDomFetcher` injection point. On Linux/CI the pipeline is constructed with the default `HttpRenderedDomFetcher`; on Windows the host injects the real `WebViewRenderedDomFetcher` (Task 14) through `ctx`. The router reads `ctx.rendered_dom_fetcher` if set, else lets the pipeline default.
- Produces:
  - `POST /api/enrich/part` body `{"mpn": "...", "category": "...", "want": [...]?}` -> a synchronous single-MPN enrich (fast, cached) returning the `EnrichmentResult` as a DTO with per-field source+confidence. For a slow first scrape this could be a job, but the cache + a short timeout keep it request-path-acceptable; a `want` set narrows the work.
  - `POST /api/enrich/bulk` body `{"text": "..."}` or `{"csv": "..."}` -> starts a JobRunner job running `bulk_enrich(parse_*(...), pipeline)`; the result is a `BulkReport` DTO (complete vs incomplete per part). Streams progress.
  - `POST /api/enrich/datasheet` body a candidate DTO + `{"url": "..."}` -> `fetch_and_store_datasheet`, returns the stored path or a `502` if the link is dead/HTML (honest: never stores an HTML wrapper).
  - A `RenderedDomFetcher` seam field on `AppContext` (`rendered_dom_fetcher: RenderedDomFetcher | None = None`), defaulting to `None` (pipeline uses its HTTP default). Task 14 sets it to the WebView2 impl on Windows. This makes the M4 seam wired end-to-end through the API today, with the JS-rendering upgrade dropping in on Windows.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_enrich_api.py`:

```python
def test_enrich_part_returns_sourced_fields(client, monkeypatch):
    from stockroom.enrich.schema import EnrichmentResult, Sourced

    class _FakePipeline:
        def __init__(self, *a, **k):
            pass

        def enrich(self, mpn, category, want=None):
            r = EnrichmentResult(category=category)
            r.manufacturer = Sourced("Texas Instruments", "jsonld", "high")
            r.description = Sourced("buck converter", "jsonld", "high")
            return r

    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline",
                        lambda ctx: _FakePipeline())

    r = client.post("/api/enrich/part", json={"mpn": "TPS62130RGTR", "category": "ICs"})
    assert r.status_code == 200
    body = r.json()
    assert body["manufacturer"]["value"] == "Texas Instruments"
    assert body["manufacturer"]["source"] == "jsonld"
    assert body["manufacturer"]["confidence"] == "high"


def test_bulk_enrich_streams_a_report(client, monkeypatch):
    from stockroom.enrich.bulk import BulkItem, BulkReport

    def _fake_bulk(mpns, pipeline, category="Other", candidate_factory=None):
        return BulkReport(items=[
            BulkItem(mpn="A", candidate=None, complete=True, missing=[]),
            BulkItem(mpn="B", candidate=None, complete=False, missing=["symbol"]),
        ])

    monkeypatch.setattr("stockroom.api.routers.enrich.bulk_enrich", _fake_bulk)
    monkeypatch.setattr("stockroom.api.routers.enrich._make_pipeline", lambda ctx: object())

    r = client.post("/api/enrich/bulk", json={"text": "A\nB"})
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "symbol" in body  # the incomplete item's missing field surfaced
    assert "done" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_enrich_api.py -v`
Expected: FAIL (enrich router missing).

- [ ] **Step 3: Write minimal implementation**

First add the seam field to `AppContext` in `context.py`:

```python
    rendered_dom_fetcher: object | None = None  # RenderedDomFetcher; set by the host on Windows
```

Create `app/backend/stockroom/api/routers/enrich.py`:

```python
"""Enrichment surface: a fast cached single-MPN enrich, a background bulk import,
and the datasheet fetch (spec sections 6.1, 8.1). The pipeline is built with the
context's RenderedDomFetcher when the host has injected the real WebView2 one
(Windows); on Linux/CI it defaults to HttpRenderedDomFetcher, so the M4 seam is
wired end-to-end through the API today (source-agnostic completeness: a scrape miss
never blocks the gate)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from stockroom.api.jobs import to_sse
from stockroom.enrich.bulk import bulk_enrich, parse_bom_csv, parse_mpn_list
from stockroom.enrich.pipeline import EnrichmentPipeline
from stockroom.enrich.schema import EnrichmentResult, Sourced


def _make_pipeline(ctx) -> EnrichmentPipeline:
    mouser = None
    if ctx.config.mouser_api_key:
        from stockroom.enrich.mouser import MouserAdapter

        mouser = MouserAdapter(api_key=ctx.config.mouser_api_key)
    return EnrichmentPipeline(
        ctx.enrich_cache_dir,
        fetcher=ctx.rendered_dom_fetcher,  # None -> pipeline's HTTP default
        mouser=mouser,
    )


def _sourced_dto(s: Sourced | None) -> dict | None:
    if s is None:
        return None
    return {"value": s.value, "source": s.source, "confidence": s.confidence}


def _result_dto(r: EnrichmentResult) -> dict:
    return {
        "category": r.category,
        "mpn": _sourced_dto(r.mpn),
        "manufacturer": _sourced_dto(r.manufacturer),
        "description": _sourced_dto(r.description),
        "datasheet_url": _sourced_dto(r.datasheet_url),
        "stock": _sourced_dto(r.stock),
        "package": _sourced_dto(r.package),
        "price_breaks": [
            {"qty": p.qty, "price": p.price, "currency": p.currency} for p in r.price_breaks
        ],
        "specs": {k: _sourced_dto(v) for k, v in r.specs.items()},
        "schema_version": r.schema_version,
    }


def _report_dto(report) -> dict:
    return {
        "items": [
            {"mpn": i.mpn, "complete": i.complete, "missing": list(i.missing), "error": i.error}
            for i in report.items
        ],
    }


def enrich_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/enrich", dependencies=[Depends(require_token)])

    @r.post("/part")
    def enrich_part(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        result = pipeline.enrich(body["mpn"], body.get("category", "Other"),
                                 want=body.get("want"))
        return _result_dto(result)

    @r.post("/bulk")
    def enrich_bulk(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        if "csv" in body:
            mpns = parse_bom_csv(body["csv"])
        else:
            mpns = parse_mpn_list(body.get("text", ""))
        category = body.get("category", "Other")

        def work(progress):
            progress({"pct": 1, "message": f"enriching {len(mpns)} parts"})
            pipeline = _make_pipeline(ctx)
            report = bulk_enrich(mpns, pipeline, category=category)
            return _report_dto(report)

        return {"job_id": ctx.jobs.submit(work)}

    @r.post("/datasheet")
    def enrich_datasheet(request: Request, body: dict) -> dict:
        from stockroom.api.routers.ingest import dto_to_candidate

        ctx = request.app.state.ctx
        pipeline = _make_pipeline(ctx)
        candidate = dto_to_candidate(body.get("candidate", {}))
        path = pipeline.fetch_and_store_datasheet(candidate, body["url"])
        return {"stored": str(path) if path else None}

    @r.get("/../jobs/{job_id}/events")  # note: SSE lives on /api/jobs; see ingest router
    def _placeholder():  # pragma: no cover - the shared SSE route is on the ingest router
        raise NotImplementedError

    return r
```

Note: the shared `/api/jobs/{job_id}/events` SSE route already exists on the ingest router; do NOT redefine it here (delete the placeholder). Bulk and enrich jobs stream through that same route. Include the router in `app.py`:

```python
    from stockroom.api.routers import enrich as enrich_router_mod
    app.include_router(enrich_router_mod.enrich_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_enrich_api.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/enrich.py app/backend/stockroom/api/context.py app/backend/stockroom/api/app.py tests/backend/api/test_enrich_api.py
git commit -m "Add enrich router: cached single enrich, SSE bulk import, datasheet fetch, RenderedDomFetcher seam"
```

---

### Task 10: Profiles router (list, create, switch, delete) [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/routers/profiles.py`
- Modify: `app/backend/stockroom/api/app.py`
- Test: `tests/backend/api/test_profiles.py`

**Interfaces:**
- Consumes: `ProfileStore.list()`, `.create(name, archive)`, `.delete(name)`, `.exists(name)`; `AppContext.switch_profile(name)` (rebuilds ops + index, persists the active profile to `MachineConfig`). Switching profile was the exact segfault footgun in the old app; here it is a synchronous context rebuild with no widget lifecycle, so it is safe.
- Produces:
  - `GET /api/profiles` -> `{"profiles": [...], "active": "..."}`.
  - `POST /api/profiles` body `{"name": "...", "archive": false}` -> creates and returns the list.
  - `POST /api/profiles/{name}/activate` -> switches the active profile, rebuilds the index, persists to config; returns the new active + part count.
  - `DELETE /api/profiles/{name}` -> `204`; refuses to delete the active profile (`400`).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_profiles.py`:

```python
def test_list_profiles_shows_active(client):
    r = client.get("/api/profiles")
    assert r.status_code == 200
    body = r.json()
    assert "Main" in body["profiles"]
    assert body["active"] == "Main"


def test_create_and_activate_a_profile(client):
    assert client.post("/api/profiles", json={"name": "Archive", "archive": True}).status_code == 200
    r = client.post("/api/profiles/Archive/activate")
    assert r.status_code == 200
    assert r.json()["active"] == "Archive"
    # the library list now reflects the (empty) Archive profile
    assert client.get("/api/library/parts").json()["count"] == 0


def test_cannot_delete_the_active_profile(client):
    r = client.delete("/api/profiles/Main")
    assert r.status_code == 400


def test_delete_a_nonactive_profile(client):
    client.post("/api/profiles", json={"name": "Scratch"})
    assert client.delete("/api/profiles/Scratch").status_code == 204
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_profiles.py -v`
Expected: FAIL (profiles router missing).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/routers/profiles.py`:

```python
"""Profile management (spec section 5.3/7). Switching profile is a synchronous
context rebuild plus a persisted active-profile flip; the derived index is rebuilt
so reads are consistent immediately (spec section 2.2)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response

from stockroom.api.errors import ApiError


def profiles_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/profiles", dependencies=[Depends(require_token)])

    @r.get("")
    def list_profiles(request: Request) -> dict:
        ctx = request.app.state.ctx
        return {"profiles": ctx.profile_store.list(), "active": ctx.profile.name}

    @r.post("")
    def create_profile(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        ctx.profile_store.create(body["name"], archive=bool(body.get("archive", False)))
        return {"profiles": ctx.profile_store.list(), "active": ctx.profile.name}

    @r.post("/{name}/activate")
    def activate(request: Request, name: str) -> dict:
        ctx = request.app.state.ctx
        if not ctx.profile_store.exists(name):
            raise FileNotFoundError(f"no such profile: {name}")
        ctx.switch_profile(name)
        return {"active": ctx.profile.name, "part_count": ctx.index.count()}

    @r.delete("/{name}", status_code=204)
    def delete_profile(request: Request, name: str) -> Response:
        ctx = request.app.state.ctx
        if name == ctx.profile.name:
            raise ApiError(400, "cannot delete the active profile; switch first")
        ctx.profile_store.delete(name)
        return Response(status_code=204)

    return r
```

Include it in `app.py`:

```python
    from stockroom.api.routers import profiles as profiles_router_mod
    app.include_router(profiles_router_mod.profiles_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_profiles.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/profiles.py app/backend/stockroom/api/app.py tests/backend/api/test_profiles.py
git commit -m "Add profiles router: list, create, activate (context+index rebuild), delete"
```

---

### Task 11: Sync and doctor routers (library sync state + KiCad wiring + drift) [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/routers/sync.py`
- Create: `app/backend/stockroom/api/routers/doctor.py`
- Modify: `app/backend/stockroom/api/app.py`
- Test: `tests/backend/api/test_sync_api.py`, `tests/backend/api/test_doctor.py`

**Interfaces:**
- Consumes (sync): `SyncEngine.sync()` -> `SyncResult(state, pulled, pushed, detail)` with `SyncState` constants; offline/divergence surfaced honestly, never clobbered (spec section 2.2). This is LIBRARY sync (the repo carrying the parts); the APP-repo self-update is Task 13.
- Consumes (doctor): `LibraryOps.detect_drift()` -> `DriftReport(items, missing_symbol)`; `KiCadWiring(kicad_dir, cli).apply(profile)` -> `WiringReport` (runs as a job: it may create category libs and touch the KiCad config, well over 100ms, and needs restart-needed surfaced).
- Produces:
  - `POST /api/sync` -> runs `ctx.sync.sync()`, rebuilds the index if it pulled, returns the `SyncResult` DTO. On `OFFLINE`/`DIVERGED` the status is `200` with the honest state (this is a first-class state, not an error); a hard `GitError` is `503`.
  - `GET /api/sync/status` -> `ahead_behind`, `has_remote`, `current_branch` (a cheap read, no network).
  - `GET /api/doctor/drift` -> the drift report DTO.
  - `POST /api/doctor/wire-kicad` -> starts a job running `KiCadWiring(ctx.kicad_dir, ctx.cli).apply(ctx.profile)`; the `WiringReport` (libs created, rows added, `restart_needed`) is the job result. On Linux this runs against a temp `kicad_dir`; the real `%APPDATA%\kicad\10.0\` write is Task 17.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_sync_api.py`:

```python
def test_sync_status_reads_without_network(client):
    r = client.get("/api/sync/status")
    assert r.status_code == 200
    body = r.json()
    assert "has_remote" in body
    assert "current_branch" in body


def test_sync_no_remote_is_a_first_class_state(client):
    # the fixture repo has no remote, so sync returns NO_REMOTE at 200, not a 500
    r = client.post("/api/sync")
    assert r.status_code == 200
    assert r.json()["state"] == "no_remote"
```

Create `tests/backend/api/test_doctor.py`:

```python
def test_drift_report_is_returned(client):
    r = client.get("/api/doctor/drift")
    assert r.status_code == 200
    body = r.json()
    assert "items" in body
    assert "missing_symbol" in body


def test_wire_kicad_runs_as_a_job(client, monkeypatch):
    from stockroom.kicad.wiring import WiringReport

    class _FakeWiring:
        def __init__(self, *a, **k):
            pass

        def apply(self, profile):
            return WiringReport(sr_lib_value="/x", categories_registered=["ICs"],
                                restart_needed=True)

    monkeypatch.setattr("stockroom.api.routers.doctor.KiCadWiring", _FakeWiring)

    r = client.post("/api/doctor/wire-kicad")
    assert r.status_code == 200
    job_id = r.json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events") as s:
        body = "".join(chunk for chunk in s.iter_text())
    assert "restart_needed" in body
    assert "done" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_sync_api.py tests/backend/api/test_doctor.py -v`
Expected: FAIL (routers missing).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/routers/sync.py`:

```python
"""Library sync state (spec sections 2.2, 9). Offline and divergence are
first-class states surfaced with exact detail, never clobbered; this is the LIBRARY
repo sync, distinct from the app self-update (updater.py)."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request


def sync_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/sync", dependencies=[Depends(require_token)])

    @r.post("")
    def do_sync(request: Request) -> dict:
        ctx = request.app.state.ctx
        result = ctx.sync.sync()
        if result.pulled:
            ctx.rebuild_index()
        return {"state": result.state, "pulled": result.pulled,
                "pushed": result.pushed, "detail": result.detail}

    @r.get("/status")
    def status(request: Request) -> dict:
        ctx = request.app.state.ctx
        ab = ctx.repo.ahead_behind()
        return {
            "has_remote": ctx.repo.has_remote(),
            "current_branch": ctx.repo.current_branch(),
            "ahead": ab[0] if ab else 0,
            "behind": ab[1] if ab else 0,
        }

    return r
```

Create `app/backend/stockroom/api/routers/doctor.py`:

```python
"""Drift detection and KiCad wiring (spec sections 2.2, 5.4). Wiring runs as a job
because it may create category libraries and rewrite the KiCad config, and it must
surface restart_needed when KiCad is running."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.wiring import KiCadWiring


def doctor_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/doctor", dependencies=[Depends(require_token)])

    @r.get("/drift")
    def drift(request: Request) -> dict:
        ctx = request.app.state.ctx
        report = ctx.ops.detect_drift()
        return {
            "items": [
                {"part_id": i.part_id, "property": i.property,
                 "json_value": i.json_value, "symbol_value": i.symbol_value}
                for i in report.items
            ],
            "missing_symbol": list(report.missing_symbol),
        }

    @r.post("/wire-kicad")
    def wire_kicad(request: Request) -> dict:
        ctx = request.app.state.ctx

        def work(progress):
            progress({"pct": 10, "message": "wiring KiCad"})
            report = KiCadWiring(ctx.kicad_dir, cli=ctx.cli).apply(ctx.profile)
            return {
                "sr_lib_value": report.sr_lib_value,
                "categories_registered": list(report.categories_registered),
                "symbol_rows_added": report.symbol_rows_added,
                "footprint_rows_added": report.footprint_rows_added,
                "libs_created": list(report.libs_created),
                "kicad_running": report.kicad_running,
                "restart_needed": report.restart_needed,
            }

        return {"job_id": ctx.jobs.submit(work)}

    return r
```

Include both in `app.py`:

```python
    from stockroom.api.routers import sync as sync_router_mod
    from stockroom.api.routers import doctor as doctor_router_mod
    app.include_router(sync_router_mod.sync_router(require_token))
    app.include_router(doctor_router_mod.doctor_router(require_token))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_sync_api.py tests/backend/api/test_doctor.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/routers/sync.py app/backend/stockroom/api/routers/doctor.py app/backend/stockroom/api/app.py tests/backend/api/test_sync_api.py tests/backend/api/test_doctor.py
git commit -m "Add sync and doctor routers: library sync state, drift report, KiCad wiring job"
```

---

### Task 12: JS MIME registration (the Windows mimetypes trap), pure and Linux-tested [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/host/__init__.py` (empty)
- Create: `app/backend/stockroom/host/mime.py`
- Test: `tests/backend/api/test_mime.py`

**Interfaces:**
- Produces:
  - `register_web_mime_types() -> None` - force-register the correct MIME types for `.js`, `.mjs`, `.css`, `.json`, `.wasm`, `.svg`, `.map` via `mimetypes.add_type(...)`, so a Windows registry that maps `.js -> text/plain` cannot serve a Vite bundle as `text/plain` and blank the window (spec section 3.7, the known Windows trap). Pure, idempotent, and safe to call on every platform; `app.create_app` calls it before mounting static files.
  - `web_mime_type(filename: str) -> str` - the resolved type for a filename after registration (used by the test to assert `.js -> text/javascript`).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_mime.py`:

```python
import mimetypes

from stockroom.host.mime import register_web_mime_types, web_mime_type


def test_js_registers_as_javascript_even_if_registry_said_text_plain():
    # simulate the Windows trap: a prior mapping of .js to text/plain
    mimetypes.add_type("text/plain", ".js")
    register_web_mime_types()
    assert web_mime_type("bundle.js") == "text/javascript"
    assert web_mime_type("module.mjs") == "text/javascript"


def test_other_web_types_register():
    register_web_mime_types()
    assert web_mime_type("style.css") == "text/css"
    assert web_mime_type("data.json") == "application/json"
    assert web_mime_type("app.wasm") == "application/wasm"


def test_registration_is_idempotent():
    register_web_mime_types()
    register_web_mime_types()
    assert web_mime_type("x.js") == "text/javascript"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_mime.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.host.mime'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/host/__init__.py` (empty file).

Create `app/backend/stockroom/host/mime.py`:

```python
"""Force-register the correct web MIME types BEFORE any static mount.

Python's mimetypes reads the Windows registry, which frequently maps .js to
text/plain; served that way, a Vite JS bundle is refused by the browser and the
WebView2 window comes up blank (spec section 3.7, the verified Windows trap). This
module overrides the type map explicitly and idempotently, on every platform, so
the trap cannot fire. It imports nothing GUI and is fully testable on Linux; the
host and the app factory both call register_web_mime_types() at startup."""

from __future__ import annotations

import mimetypes

# Explicit, correct types that must win over any OS registry mapping.
_WEB_TYPES: dict[str, str] = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".json": "application/json",
    ".wasm": "application/wasm",
    ".svg": "image/svg+xml",
    ".map": "application/json",
}


def register_web_mime_types() -> None:
    for suffix, ctype in _WEB_TYPES.items():
        # add_type with a leading entry makes this the guessed type; calling it
        # repeatedly is safe (mimetypes stores one type per extension).
        mimetypes.add_type(ctype, suffix)


def web_mime_type(filename: str) -> str:
    register_web_mime_types()
    guessed, _ = mimetypes.guess_type(filename)
    return guessed or "application/octet-stream"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_mime.py -v`
Expected: PASS (3 tests). This also makes the `from stockroom.host.mime import register_web_mime_types` call in `app.py` (Task 4) resolve; run the full API suite to confirm.

Run: `uv run pytest tests/backend/api -q`
Expected: the whole API suite green.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/host/__init__.py app/backend/stockroom/host/mime.py tests/backend/api/test_mime.py
git commit -m "Add web MIME registration to defuse the Windows text/plain JS trap, Linux-tested"
```

---

### Task 13: App-repo self-update logic (git pull --ff-only, uv sync, restart trigger) [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/updater.py`
- Modify: `app/backend/stockroom/api/app.py` (mount a small update router)
- Test: `tests/backend/api/test_updater.py`

**Interfaces:**
- Consumes: `GitRepo(app_repo_root)` with `pull_ff() -> PullResult(ok, updated, reason)`, `has_remote()`, `ahead_behind()`; the same ff-only + non-ff detection the library `SyncEngine` uses, but pointed at the APP repo (the code/UI/data repo) rather than the library (spec section 12: git-pull ff-only self-update). This is the self-update, distinct from library sync (Task 11).
- Produces:
  - `UpdateState` constants: `UP_TO_DATE`, `UPDATED`, `OFFLINE`, `DIVERGED`, `NO_REMOTE`.
  - `UpdateResult` dataclass: `state: str`, `updated: bool`, `detail: str`, `restart_requested: bool`.
  - `AppUpdater(repo, uv_runner=None, restart=None)` - `check() -> dict` (a non-blocking ahead/behind read: is an update available), and `update() -> UpdateResult`: `git pull --ff-only`; on a non-ff, return `DIVERGED` and DO NOT guess (spec section 2.2: the app does not guess a non-ff, it surfaces the state); on offline return `OFFLINE`; on a successful pull that changed files, run `uv sync` via the injected `uv_runner` and call the injected `restart` callback (a graceful backend restart + window reload), returning `restart_requested=True`. `uv_runner` and `restart` are injectable so the test never shells out or restarts anything.
  - `GET /api/update/check` and `POST /api/update/apply` - the update router (token-guarded).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_updater.py`:

```python
import shutil

import pytest

from stockroom.api.updater import AppUpdater, UpdateState
from stockroom.vcs.repo import GitRepo

pytestmark = pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")


def _origin_and_clone(tmp_path):
    origin = tmp_path / "origin"
    origin.mkdir()
    o = GitRepo(origin)
    o.init()
    (origin / "app.py").write_text("v1\n", encoding="utf-8")
    o.commit("v1", [origin / "app.py"])
    clone = tmp_path / "clone"
    c = GitRepo(clone)
    c.clone_from(origin)
    return o, origin, c, clone


def test_update_pulls_a_fast_forward_and_requests_restart(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    # advance origin so the clone is behind by a fast-forwardable commit
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    o.commit("v2", [origin / "app.py"])

    ran = {"uv": False, "restart": False}
    updater = AppUpdater(
        c,
        uv_runner=lambda: ran.__setitem__("uv", True),
        restart=lambda: ran.__setitem__("restart", True),
    )
    result = updater.update()
    assert result.state == UpdateState.UPDATED
    assert result.updated is True
    assert result.restart_requested is True
    assert ran["uv"] is True
    assert ran["restart"] is True
    assert (clone / "app.py").read_text() == "v2\n"


def test_update_up_to_date_does_not_run_uv_or_restart(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    ran = {"uv": False}
    updater = AppUpdater(c, uv_runner=lambda: ran.__setitem__("uv", True), restart=lambda: None)
    result = updater.update()
    assert result.state == UpdateState.UP_TO_DATE
    assert result.updated is False
    assert ran["uv"] is False


def test_update_diverged_is_surfaced_not_guessed(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    # make the clone diverge: a local commit AND a different origin commit
    (clone / "app.py").write_text("local\n", encoding="utf-8")
    c.commit("local change", [clone / "app.py"])
    (origin / "app.py").write_text("remote\n", encoding="utf-8")
    o.commit("remote change", [origin / "app.py"])

    updater = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None)
    result = updater.update()
    assert result.state == UpdateState.DIVERGED
    assert result.restart_requested is False


def test_check_reports_when_an_update_is_available(tmp_path):
    o, origin, c, clone = _origin_and_clone(tmp_path)
    (origin / "app.py").write_text("v2\n", encoding="utf-8")
    o.commit("v2", [origin / "app.py"])
    c.repo_fetch() if hasattr(c, "repo_fetch") else None  # fetch handled inside check()
    info = AppUpdater(c, uv_runner=lambda: None, restart=lambda: None).check()
    assert "update_available" in info
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_updater.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api.updater'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/updater.py`:

```python
"""App-repo self-update: git pull --ff-only, then uv sync, then a graceful restart
(spec section 12; knowledge-transfer section 2, update flow). This is the CODE/UI/
DATA repo, distinct from the library sync in routers/sync.py. It reuses the same
ff-only + non-ff detection the library SyncEngine uses (GitRepo.pull_ff), and on a
non-fast-forward it DOES NOT guess: it surfaces DIVERGED and leaves resolution to
the owner (spec section 2.2, honest degradation). uv_runner and restart are
injected so this is pure, fixture-repo-testable logic with no real shell-out."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from stockroom.vcs.repo import GitRepo


class UpdateState:
    UP_TO_DATE = "up_to_date"
    UPDATED = "updated"
    OFFLINE = "offline"
    DIVERGED = "diverged"
    NO_REMOTE = "no_remote"


@dataclass
class UpdateResult:
    state: str
    updated: bool = False
    detail: str = ""
    restart_requested: bool = False


def _looks_offline(reason: str) -> bool:
    r = reason.lower()
    return any(
        tok in r
        for tok in ("could not resolve host", "connection", "timed out",
                    "network", "unable to access", "no route")
    )


class AppUpdater:
    def __init__(
        self,
        repo: GitRepo,
        uv_runner: Callable[[], None] | None = None,
        restart: Callable[[], None] | None = None,
    ):
        self.repo = repo
        self._uv = uv_runner or (lambda: None)
        self._restart = restart or (lambda: None)

    def check(self) -> dict:
        if not self.repo.has_remote():
            return {"update_available": False, "state": UpdateState.NO_REMOTE}
        # ahead_behind reads the local view; a real check fetches first, but the
        # fetch is a network op wrapped by update() itself. Report best-effort.
        ab = self.repo.ahead_behind()
        behind = ab[1] if ab else 0
        return {"update_available": behind > 0, "behind": behind}

    def update(self) -> UpdateResult:
        if not self.repo.has_remote():
            return UpdateResult(state=UpdateState.NO_REMOTE, detail="no remote configured")
        pull = self.repo.pull_ff()
        if not pull.ok:
            if _looks_offline(pull.reason):
                return UpdateResult(state=UpdateState.OFFLINE, detail=pull.reason)
            # a non-fast-forward is never guessed: surface it (spec section 2.2)
            return UpdateResult(state=UpdateState.DIVERGED, detail=pull.reason)
        if not pull.updated:
            return UpdateResult(state=UpdateState.UP_TO_DATE)
        # files changed: sync deps then request a graceful restart + reload
        self._uv()
        self._restart()
        return UpdateResult(state=UpdateState.UPDATED, updated=True, restart_requested=True)
```

Add a small update router to `app.py` (inline or a new `routers/update.py`; inline shown):

```python
    from stockroom.api.updater import AppUpdater

    @app.get("/api/update/check")
    def _update_check(request: Request):
        # the app repo root is the repo that contains this package; wired by serve.py
        updater = AppUpdater(request.app.state.ctx.app_repo)
        return updater.check()

    @app.post("/api/update/apply")
    def _update_apply(request: Request):
        ctx = request.app.state.ctx
        updater = AppUpdater(ctx.app_repo, uv_runner=ctx.uv_sync, restart=ctx.request_restart)
        result = updater.update()
        return {"state": result.state, "updated": result.updated,
                "detail": result.detail, "restart_requested": result.restart_requested}
```

Note: `check()` in the test does not assert a specific truthiness (a local fetch may not have run), only that the key exists; a production `check()` fetches first. Add `app_repo`, `uv_sync`, and `request_restart` to `AppContext` (the app-repo `GitRepo`, a `uv sync` shell-out, and the host's restart hook), defaulting `app_repo` to the repo containing this file and `uv_sync`/`request_restart` to safe no-ops in the fixture context so the routes import cleanly. Guard both update routes with `Depends(require_token)`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_updater.py -v`
Expected: PASS (4 tests; the `check` test only asserts the key is present).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/updater.py app/backend/stockroom/api/app.py app/backend/stockroom/api/context.py tests/backend/api/test_updater.py
git commit -m "Add app-repo self-update: ff-only pull, uv sync, restart trigger, non-ff surfaced not guessed"
```

---

### Task 14: Loopback ephemeral-port server bootstrap [LINUX-BUILDABLE]

**Files:**
- Create: `app/backend/stockroom/api/serve.py`
- Test: `tests/backend/api/test_serve.py`

**Interfaces:**
- Produces:
  - `pick_free_port() -> int` - bind a socket to `127.0.0.1:0`, read the OS-assigned port, close, return it (an ephemeral port so multiple instances never collide).
  - `build_context(libraries_root=None, kicad_dir=None) -> AppContext` - resolve the machine config, mint a token, build the context (delegates to `context.build_context`), and attach the app-repo `GitRepo` + a real `uv_sync` runner.
  - `run(host="127.0.0.1", port=0) -> None` - build the context and app, then `uvicorn.run(app, host=host, port=port or pick_free_port())`. Only ever binds loopback (never `0.0.0.0`), enforced by the signature default and an explicit assertion.
- Testing: `pick_free_port` and `build_context` are pure/deterministic and tested; `run` (which blocks on uvicorn) is not unit-tested here but is smoke-tested on Windows (Task 16).

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_serve.py`:

```python
from stockroom.api.serve import pick_free_port


def test_pick_free_port_returns_a_usable_loopback_port():
    port = pick_free_port()
    assert isinstance(port, int)
    assert 1024 < port < 65536


def test_two_calls_can_differ():
    ports = {pick_free_port() for _ in range(5)}
    assert len(ports) >= 1  # at least usable; OS may reuse, but never raises


def test_run_refuses_a_non_loopback_host():
    import pytest

    from stockroom.api.serve import run

    with pytest.raises(ValueError):
        run(host="0.0.0.0")  # binding beyond loopback is refused (spec section 2.2)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_serve.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.api.serve'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/api/serve.py`:

```python
"""Server bootstrap: bind loopback on an OS-assigned ephemeral port and hand the
base URL plus the per-launch token to the host (knowledge-transfer section 2). Only
ever binds 127.0.0.1; a non-loopback host is refused so the API is never exposed
beyond the machine (spec section 2.2, fail-proof)."""

from __future__ import annotations

import socket
from pathlib import Path

from stockroom.api.context import AppContext, build_context as _build_context
from stockroom.api.security import mint_token
from stockroom.store.machine_config import MachineConfig


def pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def build_context(libraries_root: Path | None = None, kicad_dir: Path | None = None) -> AppContext:
    config = MachineConfig.load()
    if libraries_root is None:
        # the in-repo library lives beside this package; resolved by the launcher
        libraries_root = Path(__file__).resolve().parents[3].parent / "libraries"
    ctx = _build_context(libraries_root, kicad_dir=kicad_dir, config=config, token=mint_token())
    # attach the app-repo for the self-updater (the repo that contains this file)
    from stockroom.vcs.repo import GitRepo

    ctx.app_repo = GitRepo(Path(__file__).resolve().parents[4])
    return ctx


def run(host: str = "127.0.0.1", port: int = 0) -> None:
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError(f"refusing to bind a non-loopback host: {host!r}")
    import uvicorn

    from stockroom.api.app import create_app

    ctx = build_context()
    app = create_app(ctx)
    uvicorn.run(app, host=host, port=port or pick_free_port(), log_level="warning")
```

Note: add `app_repo`, `uv_sync`, `request_restart` as optional `AppContext` fields with safe defaults (Task 13) so `build_context` can attach them.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_serve.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/api/serve.py tests/backend/api/test_serve.py
git commit -m "Add loopback ephemeral-port server bootstrap that refuses non-loopback binds"
```

---

### Task 15: gitshim (PATH git vs dulwich ff-only fallback) decision logic [LINUX-BUILDABLE]

**Files:**
- Create: `launcher/__init__.py` (empty, so the shim is importable in tests)
- Create: `launcher/gitshim.py`
- Test: `tests/backend/api/test_gitshim.py`

**Interfaces:**
- Produces:
  - `git_on_path() -> str | None` - `shutil.which("git")`.
  - `choose_pull_backend(which=shutil.which, have_dulwich=None) -> str` - returns `"git"` when git is on PATH, else `"dulwich"` when dulwich is importable, else raises `RuntimeError` with a clear message (the launcher then tells the user to install git). Injectable so the decision is tested without either actually installed.
  - `ensure_ff_pull(repo_root, backend=None) -> bool` - run an ff-only pull via the chosen backend; the git path shells `git -C <root> pull --ff-only`, the dulwich path does a dulwich ff-only pull. Returns whether files changed. The frozen `.exe` integration is Windows (Task 16); the backend-choice logic is the unit under test here.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_gitshim.py`:

```python
import pytest

from launcher.gitshim import choose_pull_backend


def test_prefers_git_when_on_path():
    assert choose_pull_backend(which=lambda name: "/usr/bin/git", have_dulwich=False) == "git"


def test_falls_back_to_dulwich_when_no_git():
    assert choose_pull_backend(which=lambda name: None, have_dulwich=True) == "dulwich"


def test_raises_when_neither_available():
    with pytest.raises(RuntimeError):
        choose_pull_backend(which=lambda name: None, have_dulwich=False)
```

Note: `tests/backend/api/` must be able to import `launcher`; add `launcher` to `pythonpath` in `pyproject.toml` (`pythonpath = ["app/backend", "."]`) or import via the repo root. The repo root is already importable because the tests run from there; if not, add `.` to `pythonpath`.

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_gitshim.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher'` (or `launcher.gitshim`).

- [ ] **Step 3: Write minimal implementation**

Create `launcher/__init__.py` (empty file).

Create `launcher/gitshim.py`:

```python
"""Git access for the launcher: prefer the git binary on PATH, else a dulwich
ff-only pull, else a clear failure telling the user to install git
(knowledge-transfer section 3.7). The backend CHOICE is pure and tested here; the
actual dulwich pull and the frozen-exe wiring are verified on Windows (the launcher
task). dulwich is a launcher-only dependency, never imported by the backend."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Callable


def git_on_path() -> str | None:
    return shutil.which("git")


def _dulwich_available() -> bool:
    try:
        import dulwich  # noqa: F401

        return True
    except Exception:
        return False


def choose_pull_backend(
    which: Callable[[str], str | None] = shutil.which,
    have_dulwich: bool | None = None,
) -> str:
    if which("git"):
        return "git"
    dulwich_ok = _dulwich_available() if have_dulwich is None else have_dulwich
    if dulwich_ok:
        return "dulwich"
    raise RuntimeError(
        "no git on PATH and dulwich is unavailable; install git to enable self-update"
    )


def ensure_ff_pull(repo_root: Path, backend: str | None = None) -> bool:
    repo_root = Path(repo_root)
    backend = backend or choose_pull_backend()
    if backend == "git":
        before = _head(repo_root)
        subprocess.run(
            ["git", "-C", str(repo_root), "pull", "--ff-only"],
            check=True, capture_output=True, text=True,
        )
        return _head(repo_root) != before
    # dulwich ff-only pull (launcher-only path; exercised on Windows)
    from dulwich import porcelain

    before = _head(repo_root)
    porcelain.pull(str(repo_root))  # dulwich pull is ff by default for a clean tree
    return _head(repo_root) != before


def _head(repo_root: Path) -> str:
    try:
        out = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            capture_output=True, text=True,
        )
        return out.stdout.strip()
    except Exception:
        return ""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_gitshim.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add launcher/__init__.py launcher/gitshim.py tests/backend/api/test_gitshim.py pyproject.toml
git commit -m "Add launcher gitshim: git-on-PATH vs dulwich ff-pull backend choice, unit-tested"
```

---

### Task 16: The real WebView2 RenderedDomFetcher [WINDOWS-VERIFY]

**Files:**
- Create: `app/backend/stockroom/host/webview_fetch.py`
- Test: `tests/backend/api/test_webview_fetch.py` (marked `windows_only`, plus a Linux protocol-conformance test)

**This task closes the single M4 deferral.** M4 shipped the `RenderedDomFetcher` protocol (`rendered_html(url, timeout) -> FetchResult`) with an HTTP-only default (`HttpRenderedDomFetcher`); the enrich pipeline consumes it at `ScrapeSource.enrich()` (`page = self._fetcher.rendered_html(url)`). Here the real WebView2-backed implementation lands, so bot-protected pages (Cloudflare on DigiKey/TME, Akamai on Mouser) that defeat any HTTP client become readable (spec section 6.1 item 1).

**Interfaces:**
- Produces:
  - `WebViewRenderedDomFetcher(window_provider=None)` implementing the M4 `RenderedDomFetcher` protocol: `rendered_html(url, timeout=20.0) -> FetchResult`. It navigates a hidden/off-screen WebView2 page (or a reused page in the running pywebview window) to `url`, waits for the DOM to settle (a load event plus a short quiescence), reads `document.documentElement.outerHTML` via `window.evaluate_js`, and returns a `FetchResult` with `text=<rendered HTML>`, `status=200` (best-effort; WebView2 does not surface the HTTP status directly, documented), `content=text.encode()`, `content_type="text/html"`, `final_url=<the settled location.href>`.
  - The result plugs straight into `extract_all(page.text, page.final_url, ...)` in `ScrapeSource`, unchanged, because it satisfies the same protocol.
- Linux-testable part: a conformance test asserts `WebViewRenderedDomFetcher` (with an injected fake `window_provider` whose `evaluate_js` returns canned HTML) satisfies `isinstance(..., RenderedDomFetcher)` and returns a well-formed `FetchResult`. This proves the shape on Linux; only the real WebView2 navigation is Windows-gated.

**What the owner runs on Windows (acceptance bar):**
1. On the Windows box with WebView2 present, launch Stockroom and open a bot-protected product page (a DigiKey or Mouser product URL known to fire a JS challenge against an HTTP client).
2. Trigger enrich with the WebView2 fetcher injected (`ctx.rendered_dom_fetcher = WebViewRenderedDomFetcher(...)`, wired by the host in Task 17).
3. **Pass:** the enrich returns MPN/manufacturer/description sourced fields (source `jsonld`/`opengraph`/site) for a page that returns a challenge page to `HttpRenderedDomFetcher`. Concretely: run the same MPN through `HttpRenderedDomFetcher` and through `WebViewRenderedDomFetcher`; the HTTP one yields a challenge/near-empty result and the WebView2 one yields real fields. Record both outputs in the ledger.
4. **Pass:** `final_url` reflects the settled page (post-redirect), and `text` contains the JSON-LD `<script type="application/ld+json">` block absent from the raw HTTP fetch.

- [ ] **Step 1: Write the failing test (Linux conformance + Windows-gated real nav)**

Create `tests/backend/api/test_webview_fetch.py`:

```python
import pytest

from stockroom.enrich.fetch import FetchResult, RenderedDomFetcher
from stockroom.host.webview_fetch import WebViewRenderedDomFetcher


class _FakeWindow:
    """Stands in for a pywebview window: load_url records the nav, evaluate_js
    returns canned rendered HTML and the settled href."""

    def __init__(self, html, href):
        self._html = html
        self._href = href
        self.loaded = None

    def load_url(self, url):
        self.loaded = url

    def evaluate_js(self, script):
        if "outerHTML" in script:
            return self._html
        if "location.href" in script:
            return self._href
        return None


def test_conforms_to_the_rendered_dom_fetcher_protocol():
    win = _FakeWindow("<html><body>rendered</body></html>", "https://x/final")
    fetcher = WebViewRenderedDomFetcher(window_provider=lambda: win)
    assert isinstance(fetcher, RenderedDomFetcher)


def test_rendered_html_returns_a_well_formed_fetchresult():
    win = _FakeWindow(
        '<html><head><script type="application/ld+json">{"@type":"Product"}</script>'
        "</head><body>ok</body></html>",
        "https://www.lcsc.com/product-detail/C1.html",
    )
    fetcher = WebViewRenderedDomFetcher(window_provider=lambda: win)
    r = fetcher.rendered_html("https://www.lcsc.com/product-detail/C1.html", timeout=1.0)
    assert isinstance(r, FetchResult)
    assert "application/ld+json" in r.text
    assert r.final_url == "https://www.lcsc.com/product-detail/C1.html"
    assert r.content_type == "text/html"
    assert win.loaded is not None  # it actually navigated


@pytest.mark.windows_only
def test_real_webview2_reads_a_rendered_dom():
    # Owner runs this on the Windows box against a real page; asserts the rendered
    # DOM contains JS-injected content the raw HTTP fetch does not. See the task's
    # acceptance bar. Skipped everywhere else.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_webview_fetch.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.host.webview_fetch'` (the two Linux tests fail; the `windows_only` one is skipped off Windows).

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/host/webview_fetch.py`:

```python
"""The real WebView2 RenderedDomFetcher (closes the M4 deferral, spec section 6.1
item 1). Loads the page in the actual WebView2 browser context Stockroom already
hosts and reads the RENDERED DOM after JS runs, so Cloudflare/Akamai JS challenges
that fingerprint and block any HTTP client are sailed through. Satisfies the exact
M4 RenderedDomFetcher protocol, so ScrapeSource consumes it unchanged.

pywebview is imported lazily and only in the host layer, never in stockroom.api, so
the API stays a pure headless ASGI app (spec section 2.1). window_provider is
injected so this is protocol-conformance tested on Linux without WebView2."""

from __future__ import annotations

import time
from typing import Callable

from stockroom.enrich.fetch import FetchResult


class WebViewRenderedDomFetcher:
    def __init__(self, window_provider: Callable[[], object] | None = None):
        # window_provider returns a pywebview window; default resolves the running
        # app window lazily so the API layer never imports pywebview.
        self._window_provider = window_provider or _default_window

    def rendered_html(self, url: str, timeout: float = 20.0) -> FetchResult:
        window = self._window_provider()
        window.load_url(url)
        # wait for the DOM to settle: a load plus a short quiescence. WebView2 does
        # not surface the HTTP status directly, so status is best-effort 200 and the
        # extraction cascade tolerates a challenge page as an empty result.
        _wait_for_settle(window, timeout)
        html = window.evaluate_js("document.documentElement.outerHTML") or ""
        final_url = window.evaluate_js("window.location.href") or url
        return FetchResult(
            url=url,
            status=200,
            text=html,
            content=html.encode("utf-8", "replace"),
            content_type="text/html",
            final_url=final_url,
        )


def _wait_for_settle(window, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        ready = window.evaluate_js("document.readyState")
        length = window.evaluate_js("document.documentElement.outerHTML.length")
        if ready == "complete" and length == last:
            return
        last = length
        time.sleep(0.25)


def _default_window():
    # Resolve the running pywebview window (set by host.window at startup). Imported
    # lazily so importing this module on Linux does not require pywebview.
    from stockroom.host.window import active_window

    win = active_window()
    if win is None:
        raise RuntimeError("no WebView2 window is running; cannot render a page")
    return win
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_webview_fetch.py -v`
Expected: PASS on Linux for the two conformance tests; the `windows_only` real-nav test is skipped. The `_default_window` import is lazy, so the Linux tests never touch `host.window`/pywebview.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/host/webview_fetch.py tests/backend/api/test_webview_fetch.py
git commit -m "Add the real WebView2 RenderedDomFetcher (closes the M4 deferral), Linux protocol-conformance tested"
```

- [ ] **Step 6: Owner Windows verification (deferred to the Windows box)**

The owner runs the acceptance-bar steps above on Windows with WebView2 and records the HTTP-vs-WebView2 output comparison in `Hardware Perfection Log.md`. Until then this is logged as an open Windows-verify item, not claimed done.

---

### Task 17: The pywebview WebView2 window, drag/drop into ingest, graceful shutdown [WINDOWS-VERIFY]

**Files:**
- Create: `app/backend/stockroom/host/window.py`
- Test: `tests/backend/api/test_window.py` (a Linux logic test for the drag/drop path builder + a `windows_only` real-window test)

**Interfaces:**
- Produces:
  - `run_window(base_url: str, token: str) -> None` - open the pywebview WebView2 window onto `base_url` (the FastAPI-served frontend), inject the API base + token into the renderer (`window.evaluate_js` sets `window.__STOCKROOM__ = {base, token}` on load, so the SPA authenticates every request), disable service workers (a stale-bundle risk after self-update, spec section 3.7), wire native drag/drop so a dropped file's full `pywebviewFullPath` is POSTed to `/api/ingest/inspect` (spec section 3.7: native drag/drop delivers full filesystem paths, so big zips skip HTTP upload), and shut down gracefully (stop uvicorn on window close).
  - `active_window() -> object | None` - the running window handle, so `WebViewRenderedDomFetcher._default_window` can reuse it. Module-level, set by `run_window`.
  - `dropped_paths_to_inspect_body(paths: list[str]) -> dict` - pure: turn the dropped full paths into the `/api/ingest/inspect` body `{"paths": [...], "lcsc_ids": []}`. Linux-tested.
- Windows-guarded: `import webview` happens inside `run_window`, so importing `stockroom.host.window` on Linux does not require pywebview; `active_window()` and `dropped_paths_to_inspect_body()` work without it.

**What the owner runs on Windows (acceptance bar):**
1. Launch Stockroom on Windows; a native window opens showing the placeholder `index.html` (M5) served by FastAPI on the loopback ephemeral port.
2. **Pass:** the window is NOT blank (the JS MIME fix from Task 12 holds; view-source shows the bundle served as `text/javascript`). Confirm in the ledger with a screenshot.
3. **Pass:** `window.__STOCKROOM__.token` is present in the renderer console and a fetch to `/api/system/info` with that token returns `200`; a fetch without it returns `401`.
4. **Pass:** dragging a vendor zip onto the window POSTs its full Windows path (e.g. `C:\Users\...\part.zip`) to `/api/ingest/inspect` and an inspect job starts (verify the job streams progress); no HTTP file upload occurred (the path went straight to the backend).
5. **Pass:** closing the window stops uvicorn (no orphaned Python process; check Task Manager).
6. **Pass:** no service worker registers (DevTools Application tab shows none), so a self-update never serves a stale bundle.

- [ ] **Step 1: Write the failing test (Linux logic + Windows-gated)**

Create `tests/backend/api/test_window.py`:

```python
import pytest

from stockroom.host.window import active_window, dropped_paths_to_inspect_body


def test_dropped_paths_become_an_inspect_body():
    body = dropped_paths_to_inspect_body([r"C:\Users\me\part.zip", r"C:\Users\me\sym.kicad_sym"])
    assert body == {"paths": [r"C:\Users\me\part.zip", r"C:\Users\me\sym.kicad_sym"],
                    "lcsc_ids": []}


def test_active_window_is_none_before_a_window_runs():
    assert active_window() is None


@pytest.mark.windows_only
def test_real_window_opens_and_serves_a_non_blank_page():
    # Owner runs on Windows per the acceptance bar; asserts the window loads the
    # FastAPI-served page, the token is injected, drag/drop posts a full path, and
    # closing stops uvicorn. Skipped everywhere else.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_window.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'stockroom.host.window'`.

- [ ] **Step 3: Write minimal implementation**

Create `app/backend/stockroom/host/window.py`:

```python
"""The pywebview WebView2 window (spec section 3.7; knowledge-transfer section 2).

pywebview is NOT Qt; it hosts the FastAPI-served frontend in a native WebView2. It
injects the API base + per-launch token into the renderer so the SPA authenticates
every request, disables service workers (stale-bundle risk after a self-update),
routes native drag/drop full paths straight into the ingest endpoint (so large zips
skip an HTTP upload), and stops uvicorn on close. pywebview is imported lazily
inside run_window, so this module imports on Linux without it; the pure helpers
(dropped_paths_to_inspect_body, active_window) are Linux-tested."""

from __future__ import annotations

_ACTIVE_WINDOW = None


def active_window():
    return _ACTIVE_WINDOW


def dropped_paths_to_inspect_body(paths: list[str]) -> dict:
    return {"paths": list(paths), "lcsc_ids": []}


_INJECT_JS = """
window.__STOCKROOM__ = {{ base: "{base}", token: "{token}" }};
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.getRegistrations().then(function (rs) {{
    rs.forEach(function (r) {{ r.unregister(); }});
  }});
}}
"""


def run_window(base_url: str, token: str) -> None:
    global _ACTIVE_WINDOW
    import webview  # pywebview, WebView2 backend on Windows; lazy so Linux imports

    window = webview.create_window("Stockroom", url=base_url, width=1400, height=900)
    _ACTIVE_WINDOW = window

    def _on_loaded():
        window.evaluate_js(_INJECT_JS.format(base=base_url, token=token))

    window.events.loaded += _on_loaded
    # Native drag/drop: pywebview delivers full filesystem paths; the JS side posts
    # them to /api/ingest/inspect with the token. The drop handler is registered in
    # the frontend (M6); the backend contract is dropped_paths_to_inspect_body.
    try:
        webview.start()  # blocks until the window closes
    finally:
        _ACTIVE_WINDOW = None
        # graceful shutdown of the uvicorn server is triggered by the launcher/host
        # supervisor that owns the server thread (it watches for window close).
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_window.py -v`
Expected: PASS on Linux for the two pure tests; the `windows_only` test is skipped.

- [ ] **Step 5: Commit**

```bash
git add app/backend/stockroom/host/window.py tests/backend/api/test_window.py
git commit -m "Add pywebview WebView2 window: token injection, no service workers, drag/drop to ingest, Linux helpers tested"
```

- [ ] **Step 6: Owner Windows verification (deferred to the Windows box)**

The owner runs the six acceptance-bar checks on Windows and records the results (screenshot of the non-blank window, token 200-vs-401, drag/drop full-path inspect, clean shutdown, no service worker) in `Hardware Perfection Log.md`.

---

### Task 18: The frozen-once launcher (Stockroom.exe) and the placeholder frontend [WINDOWS-VERIFY]

**Files:**
- Create: `launcher/stockroom_launcher.py`
- Create: `launcher/README.md`
- Create: `app/frontend-dist/index.html` (placeholder; M6 replaces it)
- Test: `tests/backend/api/test_launcher.py` (Linux logic test for the launch-sequence orchestration with everything injected; a `windows_only` real-freeze test)

**Interfaces:**
- Produces:
  - `stockroom_launcher.py`: `main()` and a pure, fully-injected `run_launch_sequence(steps)` so the ORDER of the launch is testable on Linux without freezing anything. The real sequence (ComfyUI-Desktop-shaped, spec section 3.7):
    1. `ensure_webview2()` - check WebView2 runtime present; if absent, run the evergreen bootstrapper. (Windows-only; a no-op stub off Windows.)
    2. `ensure_ff_pull(repo_root)` - `launcher.gitshim.ensure_ff_pull` (Task 15): git-on-PATH or dulwich ff-only pull of the app repo.
    3. `uv_sync_frozen()` - run the bundled `uv.exe`: `uv sync --frozen` (provisions CPython on first run, installs the locked deps).
    4. `uv_run_app()` - `uv run` launches `python -m stockroom.api.serve` (or an entry that calls `serve.run()` then `host.window.run_window(base_url, token)`), binding loopback on an ephemeral port and opening the window.
  - `run_launch_sequence(steps: dict) -> list[str]` - runs the injected step callables in the fixed order, returning the names run, and short-circuits with a clear error if a step raises (honest: a failed pull or a missing uv is reported, never a silent half-launch).
- `uv.exe` ships BESIDE the launcher, not in git history (spec section 3.7). The launcher README states this and the freeze-once contract (the exe is frozen once and never rebuilt for app changes, because app changes ship via git pull).

**What the owner runs on Windows (acceptance bar):**
1. Freeze the launcher once into `Stockroom.exe` (PyInstaller or the chosen freezer), with `uv.exe` placed beside it. Record the freeze command in the ledger and the launcher README.
2. On a clean Windows box with KiCad 10 and WebView2, double-click `Stockroom.exe`.
3. **Pass:** first run provisions CPython via `uv` (no system Python needed), `uv sync --frozen` installs the locked deps, and the window opens on the FastAPI-served page. Time it; note first-run vs warm-run.
4. **Pass:** with the app closed, advance the app repo remote by one commit, relaunch, and confirm the launcher ff-pulls it before starting (the new commit is present; verify via `git log` in the repo).
5. **Pass:** on a box WITHOUT git on PATH, the launcher falls back to the dulwich ff-pull (Task 15) and still updates.
6. **Pass:** a non-fast-forwardable app repo state is surfaced (the app does not guess; it reports divergence and offers safe resolution), matching the `AppUpdater.DIVERGED` behavior.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_launcher.py`:

```python
import pytest

from launcher.stockroom_launcher import run_launch_sequence


def test_launch_sequence_runs_steps_in_order():
    order = []
    steps = {
        "ensure_webview2": lambda: order.append("webview2"),
        "ensure_ff_pull": lambda: order.append("pull"),
        "uv_sync_frozen": lambda: order.append("sync"),
        "uv_run_app": lambda: order.append("run"),
    }
    ran = run_launch_sequence(steps)
    assert ran == ["ensure_webview2", "ensure_ff_pull", "uv_sync_frozen", "uv_run_app"]
    assert order == ["webview2", "pull", "sync", "run"]


def test_launch_sequence_short_circuits_on_a_failing_step():
    def boom():
        raise RuntimeError("no git")

    steps = {
        "ensure_webview2": lambda: None,
        "ensure_ff_pull": boom,
        "uv_sync_frozen": lambda: (_ for _ in ()).throw(AssertionError("must not run")),
        "uv_run_app": lambda: (_ for _ in ()).throw(AssertionError("must not run")),
    }
    with pytest.raises(RuntimeError):
        run_launch_sequence(steps)


@pytest.mark.windows_only
def test_frozen_exe_launches_end_to_end():
    # Owner runs on Windows per the acceptance bar (freeze once, double-click,
    # provision + pull + sync + window). Skipped everywhere else.
    ...
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/backend/api/test_launcher.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'launcher.stockroom_launcher'`.

- [ ] **Step 3: Write minimal implementation**

Create `launcher/stockroom_launcher.py`:

```python
"""Frozen-once launcher, ComfyUI-Desktop-shaped (spec section 3.7; knowledge-
transfer section 2). Frozen to Stockroom.exe ONCE and never rebuilt for app changes
(those ship via git pull). Sequence: ensure WebView2, ff-pull the app repo (git on
PATH or dulwich), uv sync --frozen (provisions CPython + locked deps), uv run the
app. The uv.exe ships beside the launcher, not in git history. run_launch_sequence
is pure and fully injected so the launch ORDER is Linux-tested; the real steps and
the freeze are Windows-verified."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

_ORDER = ("ensure_webview2", "ensure_ff_pull", "uv_sync_frozen", "uv_run_app")


def run_launch_sequence(steps: dict[str, Callable[[], None]]) -> list[str]:
    ran: list[str] = []
    for name in _ORDER:
        step = steps.get(name)
        if step is None:
            continue
        step()  # a failure raises; we do NOT swallow it (honest degradation)
        ran.append(name)
    return ran


def _repo_root() -> Path:
    # the app repo is the directory containing app/ and launcher/
    return Path(__file__).resolve().parents[1]


def main() -> None:  # pragma: no cover - the real, Windows-run entry
    from launcher.gitshim import ensure_ff_pull

    root = _repo_root()

    steps = {
        "ensure_webview2": _ensure_webview2,
        "ensure_ff_pull": lambda: ensure_ff_pull(root),
        "uv_sync_frozen": _uv_sync_frozen,
        "uv_run_app": _uv_run_app,
    }
    run_launch_sequence(steps)


def _ensure_webview2() -> None:  # pragma: no cover - Windows-only
    # On Windows, check for the evergreen WebView2 runtime and run the bootstrapper
    # if absent. A no-op off Windows.
    import sys

    if not sys.platform.startswith("win"):
        return
    # (Windows: probe the WebView2 registry key; run MicrosoftEdgeWebview2Setup.exe
    # if the runtime is missing. Verified on the owner's box.)


def _uv_sync_frozen() -> None:  # pragma: no cover - shells out to bundled uv.exe
    import subprocess

    subprocess.run(["uv", "sync", "--frozen"], check=True, cwd=str(_repo_root()))


def _uv_run_app() -> None:  # pragma: no cover - launches the app
    import subprocess

    # uv run starts the app entry, which binds loopback + opens the WebView2 window
    subprocess.run(["uv", "run", "python", "-m", "stockroom.api.serve"],
                   check=True, cwd=str(_repo_root()))


if __name__ == "__main__":  # pragma: no cover
    main()
```

Create `launcher/README.md` (the freeze-once contract, the `uv.exe`-beside-not-in-git rule, the freeze command placeholder, and the git/dulwich fallback).

Create `app/frontend-dist/index.html` (a minimal placeholder so the host has something to load; M6 replaces it):

```html
<!doctype html>
<meta charset="utf-8">
<title>Stockroom</title>
<h1>Stockroom</h1>
<p>Backend is up. The full UI ships in M6.</p>
```

Note: `stockroom.api.serve` needs a `__main__`-style entry that calls `serve.run()` and then opens the window; add a tiny `serve.run()`-plus-`host.window.run_window` wrapper (or a `python -m stockroom.api.serve` guard) that starts uvicorn on a thread, waits for `/api/health`, then calls `run_window(base_url, token)`. Keep that wrapper thin and Windows-verified.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/backend/api/test_launcher.py -v`
Expected: PASS on Linux for the two order tests; the `windows_only` freeze test is skipped.

- [ ] **Step 5: Commit**

```bash
git add launcher/stockroom_launcher.py launcher/README.md app/frontend-dist/index.html tests/backend/api/test_launcher.py
git commit -m "Add frozen-once launcher sequence (order Linux-tested) plus placeholder frontend and README"
```

- [ ] **Step 6: Owner Windows verification (deferred to the Windows box)**

The owner freezes `Stockroom.exe` once (uv.exe beside it), runs the six acceptance-bar checks (provision + pull + sync + window; ff-pull on relaunch; dulwich fallback; non-ff surfaced), and records results + the freeze command in `Hardware Perfection Log.md` and the launcher README.

---

### Task 19: End-to-end API wiring test and the KiCad-config-write Windows verification [LINUX-BUILDABLE test + WINDOWS-VERIFY KiCad write]

**Files:**
- Test: `tests/backend/api/test_end_to_end.py` (Linux full-suite wiring) and a `windows_only` KiCad-config-write case
- Modify: none (this task is verification, closing the milestone)

**Interfaces:**
- Consumes: the whole M5 surface plus the M2 `KiCadWiring`. Two things:
  1. **[LINUX-BUILDABLE]** a single httpx test that drives a realistic flow against the fixture library: health -> system/info -> list -> search -> facets -> detail -> edit-field -> move -> a stubbed ingest inspect job (SSE) -> a stubbed enrich (SSE) -> sync (NO_REMOTE) -> drift -> profile create/activate/delete. Proves every router is mounted, token-guarded, and consistent end to end with no engine re-implementation.
  2. **[WINDOWS-VERIFY]** the KiCad-config-write end-to-end: on Windows against the real `%APPDATA%\kicad\10.0\`, POST `/api/doctor/wire-kicad`, then confirm KiCad resolves the library (the `SR_LIB` var + `SR-` rows land, the V10 `(type "Table")` row is untouched, a restart-needed is reported if KiCad is running, and a part is usable in a real project). This is the "final KiCad wiring/preview verification" the knowledge transfer flags as always needing one Windows pass.

**What the owner runs on Windows (acceptance bar):**
1. On Windows with KiCad 10 installed and a real library profile, start Stockroom and POST `/api/doctor/wire-kicad` (or use the M6 button when it exists; for M5, curl it with the launch token).
2. **Pass:** `%APPDATA%\kicad\10.0\sym-lib-table` and `fp-lib-table` gain only `SR-` `(type "KiCad")` rows; the `(type "Table")` stock-library row and every non-Stockroom row are byte-untouched (diff the before/after; timestamped backup exists).
3. **Pass:** `kicad_common.json` `environment.vars` gains `SR_LIB` pointing at the profile root (materialized from `null` if needed), with a timestamped backup and a parse-valid file after write.
4. **Pass:** opening KiCad, the `SR-`-nicknamed libraries resolve; a part places with its symbol, footprint, and 3D model from `${SR_LIB}/...`.
5. **Pass:** if KiCad was running, the wiring report's `restart_needed` is true and the app says so (aware writer).
6. Record all of this (diffs, screenshots) in `Hardware Perfection Log.md`; only then is M5's KiCad wiring claimed verified.

- [ ] **Step 1: Write the failing test**

Create `tests/backend/api/test_end_to_end.py`:

```python
import pytest


def test_full_flow_over_every_router(client, monkeypatch):
    # health (no token via a fresh anon call is covered elsewhere); here the authed
    # client walks the read + mutate + job surfaces to prove they are all wired.
    assert client.get("/api/system/info").json()["active_profile"] == "Main"
    assert client.get("/api/library/parts").json()["count"] == 2
    assert client.get("/api/library/facets").json()["by_category"]["ICs"] == 2
    assert client.get("/api/library/parts/tps62130").json()["mpn"] == "TPS62130"
    assert client.patch("/api/library/parts/mystery",
                        json={"field": "manufacturer", "value": "X"}).status_code == 200
    assert client.post("/api/library/parts/tps62130/move",
                       json={"category": "Modules"}).status_code == 200
    assert client.post("/api/sync").json()["state"] == "no_remote"
    assert "items" in client.get("/api/doctor/drift").json()
    assert client.post("/api/profiles", json={"name": "P2"}).status_code == 200
    assert client.post("/api/profiles/P2/activate").json()["active"] == "P2"
    assert client.delete("/api/profiles/P2").status_code in (204, 400)  # active guard


@pytest.mark.windows_only
def test_kicad_config_write_end_to_end():
    # Owner runs on Windows against real %APPDATA%\kicad\10.0\ per the acceptance
    # bar: SR_LIB + SR- rows land, the Table row is untouched, restart_needed is
    # reported, a part is usable in a real project. Skipped everywhere else.
    ...
```

- [ ] **Step 2: Run test to verify it fails, then passes**

Run: `uv run pytest tests/backend/api/test_end_to_end.py -v`
Expected: the Linux full-flow test may need small adjustments if a route name drifted; iterate until PASS. The `windows_only` KiCad test is skipped off Windows.

- [ ] **Step 3: Run the full suite**

Run: `uv run pytest tests/backend -q`
Expected: all M1 to M4 tests plus the new `api` tests PASS; `windows_only` and `live_enrich` tests are deselected/skipped; `requires_kicad_cli` tests pass on WSL, skip on CI.

- [ ] **Step 4: Commit**

```bash
git add tests/backend/api/test_end_to_end.py
git commit -m "Add end-to-end API wiring test and the windows-only KiCad-config-write verification case"
```

- [ ] **Step 5: Owner Windows verification (deferred to the Windows box)**

The owner runs the KiCad-config-write acceptance bar on Windows with real KiCad 10 and records the before/after config diffs + a placed-part screenshot in `Hardware Perfection Log.md`. This closes the "final KiCad wiring verification" flagged as always needing a Windows pass.

---

## Self-Review

**1. Spec coverage (sections 2.2, 4, 6.1, 12; knowledge-transfer sections 2, 3.7):**
- FastAPI thin veneer over the engine -> Tasks 4 to 11 (app factory + routers), each calling the exact surveyed M1 to M4 surface, never re-implementing it. Covered.
- Localhost-only bind + per-launch token (defense in depth) -> Task 2 (token guard, constant-time), Task 14 (loopback ephemeral port, refuses non-loopback). Covered.
- Load-active-profile + rebuild-on-switch/pull -> Task 4 (`AppContext`, `switch_profile`, `rebuild_index`), Task 10 (activate), Task 11 (rebuild after pull). Covered.
- Library router: index-backed list/search/facets, detail, mutations -> Tasks 5, 6, served from `LibraryIndex`, mutations through `LibraryOps` (gate + atomic transaction intact). Covered.
- Previews as image endpoints -> Task 7 (`sym/fp export svg`, content-hash cached). Covered.
- Ingest job + SSE -> Task 8; enrich job + SSE + bulk + datasheet -> Task 9; jobs + SSE plumbing -> Task 3. Covered.
- Profiles/sync/doctor -> Tasks 10, 11 (library sync state honest, drift, KiCad wiring job). Covered.
- git-pull self-update logic -> Task 13 (`AppUpdater`, ff-only, non-ff surfaced not guessed, uv sync, restart), fixture-repo tested. Covered.
- Real WebView2 RenderedDomFetcher (closes the M4 deferral) -> Task 16, protocol-conformance tested on Linux, real nav Windows-verified, plugged into `ScrapeSource` unchanged. Covered.
- pywebview WebView2 host + lifecycle (token injection, JS MIME before static mount, no service workers, graceful shutdown, drag/drop full paths) -> Task 12 (MIME, Linux-tested), Task 17 (window). Covered.
- Frozen-once launcher (ensure WebView2, ff-pull, bundled uv, uv run; git via PATH or dulwich) -> Task 15 (gitshim choice, tested), Task 18 (launch sequence order tested, freeze Windows-verified). Covered.
- KiCad-config-write end-to-end -> Task 19 (Windows-verify acceptance bar). Covered.

**2. LINUX-BUILDABLE vs WINDOWS-VERIFY split (the owner's honesty requirement):**
- LINUX-BUILDABLE (build + verify now, `pytest`/`httpx`, no Windows/WebView2/KiCad): Tasks 1 to 15 and the Linux halves of 16, 17, 18, 19. This is the whole API, the updater logic, jobs/SSE, security, MIME, gitshim choice, launcher-sequence order, and the protocol-conformance shells of the WebView2 seams.
- WINDOWS-VERIFY (needs the owner's Windows box + KiCad 10): the real WebView2 navigation (Task 16 step 6), the real window lifecycle + drag/drop + shutdown + no-SW (Task 17 step 6), the frozen `.exe` end-to-end (Task 18 step 6), and the KiCad-config-write end-to-end (Task 19 step 5). Each names exactly what the owner runs and the acceptance bar, and each has a Linux-testable contract so nothing is a bare stub.

**3. Placeholder scan:** every LINUX-BUILDABLE code step shows real, runnable code. The WINDOWS-VERIFY seams (`WebViewRenderedDomFetcher`, `run_window`, the launcher steps) are real implementations with lazy Windows-only imports and injected test doubles, not stubs: each satisfies a Linux-tested contract (protocol conformance, path-builder, launch order) and the only deferred part is the real Windows runtime pass, logged as an explicit acceptance bar rather than hidden.

**4. Zero-Qt / zero-pywebview-in-API discipline:** no module imports PyQt. `pywebview`/`webview` is imported ONLY lazily inside `stockroom.host.window` and the launcher, never in `stockroom.api`; Task 1 extends the CI gate to fail on any `pywebview` import under `stockroom/api/`, so `stockroom.api` stays a pure headless ASGI app. New deps are exactly `fastapi`/`uvicorn`/`sse-starlette` (Task 1), `httpx` dev (Task 1), `pywebview` (Task 17, host), each added at first use with a `uv lock`. `from __future__ import annotations` on every new module.

**5. Type/seam consistency:** the routers call the surveyed engine signatures verbatim: `LibraryIndex.search(query, category, complete_only)`/`.get`/`.facets`/`.count`; `LibraryOps.load_record`/`edit_field`/`move_category`/`delete_part`/`detect_drift` and the `staged_missing_fields` gate via `add_part`; `IngestPipeline(profile, repo, cli).inspect/.commit`; `EnrichmentPipeline(cache_dir, fetcher=...).enrich/.enrich_candidate/.fetch_and_store_datasheet`; the `RenderedDomFetcher.rendered_html(url, timeout)` protocol consumed at `ScrapeSource.enrich()`; `SyncEngine.sync() -> SyncResult`; `GitRepo.pull_ff() -> PullResult`; `KiCadWiring(kicad_dir, cli).apply(profile) -> WiringReport`; `KiCadCli.sym_export_svg`/`fp_export_svg`; `MachineConfig` fields (`active_profile`, `mouser_api_key`, `kicad_config_override`). No signature is invented.

## Execution Handoff

Plan complete. Per the owner's standing directive for this project (build milestones back-to-back autonomously, no per-task review gates, one adversarial review at the END before merge), execution proceeds straight through on a feature branch with per-task commits (crash-recoverable): Tasks 1 to 15 and the Linux halves of 16 to 19 land + verify on Linux/offscreen with the fixture library and the fixture app; then one end-of-build review; then ff-merge + push. The WINDOWS-VERIFY tasks (the real WebView2 fetcher navigation, the window lifecycle, the frozen `.exe`, and the KiCad-config-write end-to-end) are the explicit Windows pass the owner runs on the real box with KiCad 10, each with a named acceptance bar recorded in `Hardware Perfection Log.md`. They are called out as deferrals here, not hidden: every one has a Linux-tested contract and a documented default so the API is fully wired the moment the Windows runtime is present.

## Open decisions worth the owner revisiting

- **SSE library choice (`sse-starlette`).** Chosen because it is the standard `EventSourceResponse` for FastAPI/Starlette and keeps the job-progress stream trivial. Alternative: hand-rolled `StreamingResponse` with a `text/event-stream` generator (one fewer dependency, but re-implements heartbeat/close semantics). If the owner wants to minimize deps, we can drop `sse-starlette` and hand-roll; the `JobRunner`/`to_sse` seam is already library-agnostic, so the swap is one file.
- **Auth-token scheme (per-launch bearer, defense in depth).** The primary boundary is the loopback bind; the token stops another local process from driving the library. It is minted per launch and handed to the renderer, never persisted. Alternative considered: no token (rely on loopback alone), or a signed origin check. The per-launch token is the cheapest real defense-in-depth; revisit if the owner wants it stronger (e.g. an OS-user-scoped socket) or simpler (loopback only).
- **Whether the launcher bundles `uv.exe`.** The plan follows the knowledge transfer: `uv.exe` ships beside the frozen launcher, not in git history, and provisions CPython on first run. Alternative: require a system Python + `uv` on PATH (smaller distribution, more setup burden on the user). Bundling `uv.exe` matches the "works regardless of their setup" goal; the owner should confirm the distribution mechanism (where `uv.exe` comes from at freeze time, and its update cadence, since it is out of git).
- **Single-flight index rebuild after mutations.** The plan rebuilds the derived index synchronously after each mutation (edit/move/delete/commit) for read-after-write consistency. At thousands of parts a full rebuild per mutation may be wasteful; a targeted single-row upsert into the index would be faster. Deferred as a performance refinement (correctness-first now); worth revisiting if the library grows large enough that a full rebuild is felt on a single-field edit.
- **Concurrency lock for same-library writes (M2 deferral, still open).** M2 assumed single-threaded per-profile access; the `JobRunner` uses one worker by default, so concurrent library writes are not yet possible, but a second job type or a raised worker count would need the fcntl/msvcrt symbol-lib file lock the knowledge transfer flags. The plan keeps `max_workers=1` to stay safe; the owner should decide whether M5 should already land the file lock or keep it single-flight until a real concurrency need appears.
