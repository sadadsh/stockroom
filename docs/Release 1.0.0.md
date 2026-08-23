# Stockroom 1.0.0

Stockroom 1.0 makes the installed Windows application, trusted component intake, CAD asset
management, and in-app Design Studio one coherent product line.

## Installed Windows Product

- The supported production shape is a signed x64 MSIX with a native WPF/WebView2 host and an
  immutable packaged worker. Source Python, `uv`, and a mutable application checkout are not
  production startup fallbacks.
- Each successful main push retains its unique GitHub build number as the fourth Windows version
  component and publishes one normal immutable GitHub Release: `1.0.0.<build number>`. Manual
  workflow dispatch verifies without publishing, and version tags do not create another line.
- Updates remain signed TUF release generations. They preserve machine-owned configuration,
  Design Studio drafts, and applied designs outside immutable release directories.

## Component And CAD Workflows

- Multi-part intake keeps exact identity, provenance, duplicate recovery, and per-row outcomes
  visible without launching CAD acquisition automatically.
- Manage Models keeps provider browsing person-driven and binds downloads, proposals, and applied
  CAD evidence to the exact component and selected EDA requirements.
- Assets separates CAD Ready source material from Catalog Current, Pending, and Building. Catalog
  Build is one explicit confirmed action for the selected Primary EDA, with concise results and
  retained per-part history.

## Design Studio

- Authored and generated global identities make Stockroom-owned elements selectable without
  collapsing repeated occurrences onto the wrong target.
- Preview recovery, root-surface protection, transform-safe rotation, bounded z-order, gesture
  undo, and persisted draft/applied separation protect both the application and personal work.
- Remove From Arrangement takes an element out of layout without deleting it; Layers and Undo can
  restore the exact occurrence. Direct authored text remains selectable and editable.
- The 3D asset viewer rejects buried or sideways SMD placement, stands rectangular bodies upright,
  and aligns them to their real footprint pads while leaving valid source placement unchanged.

## Release Boundary

The 1.0 metadata does not itself publish or install a release. Production publication still
requires the legitimate Authenticode certificate, exact publisher and HTTPS feed configuration,
authorized TUF online-role keys, a green canonical CI/reproducibility run on the integrated source,
and installed Windows/WebView2 acceptance. Stockroom does not create, trust, or publish a
self-signed production substitute.
