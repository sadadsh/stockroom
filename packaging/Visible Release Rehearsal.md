# Visible Release Rehearsal

`packaging.visible_release_rehearsal` is the bounded Windows acceptance harness
for a visible V1 → V2 → fresh V1 native-window sequence plus a separately
recorded precommit rollback fault.

It requires:

- the exact unpacked V1 `Stockroom.exe`;
- complete, locally verified V1 and V2 release-set directories and their
  manifest SHA-256 values;
- exactly one canonical `WindowHost/Stockroom.WindowHost.exe` member in each
  release;
- four distinct task-owned roots for Config, Local App Data, Roaming App Data,
  and evidence;
- an initialized library named by the isolated config and physically contained
  by the isolated Config, Local App Data, or Roaming App Data root;
- an available Stockroom coordinator mutex; and
- a trusted exact-HWND Windows Graphics Capture port.

No registered or installed exact-HWND Windows Graphics Capture helper currently
exists in the workspace. The Python entry point therefore fails closed before
starting the coordinator, backend workers, or native windows. A future trusted
helper must implement `WindowCapturePort.capture`, verify that the supplied HWND
belongs to the supplied process ID, and write one PNG to the supplied new
destination. `PrintWindow`, WebView2 remote debugging, CDP, and a source
pywebview window are not accepted substitutes.

The harness refuses roots that equal the current live environment roots, never
starts an EDA application, records any new `X2.EXE` as a failure, and owns every
release worker and native window child through the production boundaries.

The terminal receipt is valid only when `passed` is `true`. It binds:

- the SHA-256 of the unpacked V1 executable, both manifest backends, and both
  exact packaged native WindowHost executables;
- one stable source broker PID and loopback origin;
- three distinct native child PID, HWND, and profile identities for V1, V2,
  and fresh V1;
- each child's release identity, renderer health, visible state, sanitized UI
  export, Settings route, theme, geometry, and API/event-stream readiness;
- `/api/system/identity` and `/api/update/check` at every phase;
- exact-HWND PNG evidence before, during, and after;
- native child process-image, `WM_GETICON`, file-icon, and taskbar
  AppUserModelID inspection; and
- zero release-worker or newly launched Altium processes after cleanup.

## Rollback Semantics

The precommit fault proof keeps the original V1 native child alive, shows the
V2 candidate, then uses `HostReleaseBoundary.rollback` to restore that exact V1
child and stop V2. It is recorded separately as
`precommit_rollback_fault`.

That proof is not a committed downgrade. After a successful window commit,
`ManagedWindowHandoff` retires the old child and clears the reversible
adoption. A production V2 → cached V1 downgrade must therefore be a second
activation authorized by V2's rollback declaration: launch a fresh V1 backend
and WindowHost, health-check them, move the durable pointer, commit the new
window, then retire V2. The production rollback activator owns that pointer
workflow; this harness must not simulate it by committing a window without the
durable release pointer.
