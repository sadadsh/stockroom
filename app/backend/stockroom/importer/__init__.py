"""The importer: pull each source's RAW payload into `sourced/`, then re-derive.

It writes evidence and calls the derive engine; it never contains a second derivation. See
`engine.py` for the outcome model (a rate-limited part is DEFERRED, never FAILED) and
`sources.py` for why the credentialed fetch registry is separate from the credential-free
parse registry in `stockroom.derive.payloads`.
"""
