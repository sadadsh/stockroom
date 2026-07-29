# Ultra Librarian Machine Access Exception

## Status

`UL-PRIVATE-EVALUATION-2026-07-28` is a narrow exception for the owner's private
evaluation account. It permits ordinary, exact-part CAD retrieval through Stockroom. It
does not permit catalogue scraping, parallel provider sessions, CAPTCHA or MFA
automation, or reuse by another installation without its own authorization.

The feature is off by default. It becomes eligible only when the machine configuration
contains `ul_private_evaluation_automation: true`. Either
`STOCKROOM_DISABLE_PROVIDER_AUTOMATION=1` or
`STOCKROOM_DISABLE_ULTRALIBRARIAN_AUTOMATION=1` immediately disables it.

## Enforced Boundary

- One provider session operates at a time.
- Provider starts are durably spaced at one start per two seconds across jobs and app
  restarts. Cancellation interrupts a pending wait.
- Authorization is checked before and after every pacing wait.
- Resolver results must identify the exact requested MPN and use an official HTTPS
  Ultra Librarian origin before the browser navigates.
- Every result, detail redirect, export panel, selection, and submit is rechecked
  against the exact manufacturer and MPN.
- Credentials remain in Windows Credential Manager. Configuration, logs, evidence, and
  object representations contain no password.
- A provider-specific persistent browser profile preserves the authenticated session.
  Stockroom checks that session before attempting login.
- CAPTCHA, MFA, passkeys, security keys, and identity verification always pause at a
  visible Stockroom handoff. The person clears the provider control; Stockroom resumes
  only after the control disappears, or cancels cleanly.
- Downloads remain bound to the active component task and pass through the existing
  classification, identity evidence, validation, and coherent CAD-variant pipeline.

## Export Contract

Stockroom requests all currently supported artifacts together:

- `KiCad 6 or later`
- `STEP`
- exact visible label `Altium Designer (Native)`

If the native Altium choice is absent, Stockroom still retrieves KiCad and STEP but
reports Altium missing. It never substitutes the legacy Altium script, `.lia`, or P-CAD
exports.

Ultra Librarian's official native-export announcement and help identify the native
Altium package as directly openable `.LibPkg`, `.SchLib`, and `.PcbLib` content with the
STEP model integrated:

- <https://www.ultralibrarian.com/native_export_for_altium_designer/>
- <https://app.ultralibrarian.com/content/help/altium_designer_2.htm>

## Operational Limit

Fixture tests lock the exact visible export label, stale-selection clearing, official
origin checks, human security handoff, and three task-bound downloads. The machine flag
must remain off until a live canary is intentionally run on the authorized account.
Provider markup can change; a missing or ambiguous control fails closed and requires an
adapter review rather than a legacy-format fallback.
