# Stockroom 0.5.0

Stockroom 0.5.0 is the first continuously delivered Windows build. The
downloaded executable is a stable launcher for the writable Stockroom
application, not a read-only demo shell. It includes the showcase library and
keeps the managed application checkout aligned with the pushed `main` branch.

## What Changed

- Added the full Projects workspace and shared KiCad/Altium inspection grammar.
- Added writable component intake, sourcing, completion, and library workflows.
- Added automatic provider discovery with retained DigiKey, Ultra Librarian,
  SamacSys, and SnapMagic sessions.
- Made `Open Provider` the explicit login/security-check handoff when a provider
  needs user input; the provider profile is reused on later parts.
- Added automatic Git convergence. Pushed revisions are downloaded, the current
  UI session is persisted, and Stockroom relaunches itself on the updated
  checkout without asking the user to download another executable.
- The updater verifies that the native Stockroom window belongs to its process
  and waits for Windows to confirm closure before it reports a successful
  restart handoff. A bounded restart watchdog returns control to the stable
  launcher if WebView2 does not close gracefully.
- Hid native helper consoles while preserving the underlying KiCad and Altium
  operations.
- Added the new Stockroom application icon.

## Windows Artifact

- File: `Stockroom.exe`
- Size: `193176475` bytes
- SHA-256:
  `3a0987d263a63d4d967b239d0588f944b8fee0c2e65edabdbe3809af42049ca3`

The executable is an unsigned development build. Windows may show a SmartScreen
warning. The first launch requires internet access to prepare the managed
runtime and fetch the current application revision.
