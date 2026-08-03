# Stockroom 0.6.0

Stockroom 0.6.0 turns CAD completion into one primary workflow: choose **Get CAD Files**, let one provider complete the component, and use **Add Files** only when a provider requires a person to finish a download. The application accepts the selected file set as a whole, keeps useful CAD artifacts, ignores unrelated files, converts supported Ultra Librarian P-CAD source to native Altium libraries without launching Altium, and publishes one verified KiCad/Altium component.

## User-Facing Changes

- The normal acquisition path uses one provider at a time and stops after that provider supplies a complete Symbol, Footprint, and shared 3D Model set for KiCad and Altium.
- Provider pages stay inside the managed Stockroom window. Partial provider sessions remain available instead of closing before the component is complete.
- **Add Files** accepts up to 100 selected files or archives in one operation. Stockroom extracts useful files, merges split CAD packages, ignores unrelated siblings, and runs the same validation, conversion, publication, Git, and UI-refresh path as automatic downloads.
- Component inspection again shows separate 3D Model, Symbol, and Footprint viewers. The 3D viewer defaults to realistic source color, retains its view/layer controls, and separates the PCB, pads, and model to prevent visible z-fighting.
- Footprint previews use a lighter stroke and more surrounding context.
- The Category editor uses the canonical category catalog even when a category is not yet populated; **Fuses** is included.
- Capture results and completion state come from a fresh canonical library readback. A provider download event alone cannot claim completion.

## Release Acceptance

- Managed Window Host: 65 passed.
- Native CAD converter: 5 passed.
- Provider runner/planning/guided end-to-end cohort: 106 passed, 1 environment skip.
- Capture/API/ingest release-critical cohort: 1,566 passed, 3 environment skips after correcting one stale test-double signature.
- Frontend: 1,400 passed across the full suite after correcting one stale copy expectation.
- Serialized Windows/budget cohort: 50 passed; six coordinator cases were rerun after the existing source host released its mutex.
- Ruff, Windows-targeted Python type checking, TypeScript, token parity, actionlint, production frontend build, generated distribution synchronization, and source/test/document Git diff checks pass. The generated Three.js chunk retains upstream shader whitespace and is treated as generated output.
- Real Windows WebView2 inspection passed in dark and light themes against the canonical seven-component library. The final source bundle visibly exposes **Get CAD Files**, separate representation viewers, realistic 3D rendering, and KiCad/Altium readiness without launching either EDA.

The release does not claim the still-open ten-component fresh-network matrix or SnapMagic phone-verification boundary. Those remain tracked provider qualifications, not hidden release claims.
