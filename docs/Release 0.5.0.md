# Stockroom 0.5.0

Stockroom 0.5.0 is a verified unsigned Windows fixture with a writable Stockroom
application and showcase library. It is not connected to a production update
feed and therefore does not follow pushed `main`. Install a later signed
production build once its real HTTPS release feed is available.

## What Changed

- Added the full Projects workspace and shared KiCad/Altium inspection grammar.
- Added writable component intake, sourcing, completion, and library workflows.
- Added automatic provider discovery with retained DigiKey, Ultra Librarian,
  SamacSys, and SnapMagic sessions.
- Made `Open Provider` the explicit login/security-check handoff when a provider
  needs user input; the provider profile is reused on later parts.
- Preserved the current UI session across ordinary fixture restarts. Production
  release convergence is intentionally unavailable in this unsigned fixture;
  it requires a signed artifact and real HTTPS release feed.
- Hid native helper consoles while preserving the underlying KiCad and Altium
  operations.
- Added the new Stockroom application icon.

## Windows Artifact

- File: `Stockroom.exe`
- Size: `193176475` bytes
- SHA-256:
  `3a0987d263a63d4d967b239d0588f944b8fee0c2e65edabdbe3809af42049ca3`

The executable is an unsigned, self-contained development fixture. Windows may
show a SmartScreen warning. It runs the bundled application revision and does
not fetch or activate newer application revisions.
