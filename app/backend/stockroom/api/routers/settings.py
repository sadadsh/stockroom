"""Per-machine settings surface (spec section 11). Reads the redacted per-machine
config and writes the fields wired end-to-end: the Mouser API key, the GitHub
token, and the KiCad overrides. The keys are secrets, so GET returns only
presence plus a last-4 hint, never the raw value; the KiCad overrides are plain
paths and are shown raw. Every PATCH applies live on the running context (no
restart) and persists to the config.json."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from stockroom.kicad.common_json import read_env_var


def _hint(key: str) -> str:
    """The last four characters, so the user can confirm which key is stored
    without the surface ever revealing the whole secret. Short keys reveal
    nothing. Tolerates a null field in a hand-edited config.json."""
    key = key or ""
    return key[-4:] if len(key) >= 4 else ""


# The credential fields a dev-creds.json may carry (identifiers + secrets alike). Loading is a
# local-only convenience: the file lives in the OS config dir, NEVER the (public) repo, so no
# secret is ever committed. Only these known fields are read; anything else in the file is ignored.
_DEV_CRED_FIELDS = (
    "mouser_api_key",
    "github_token",
    "digikey_client_id",
    "digikey_client_secret",
    "digikey_username",
    "digikey_password",
    "ul_username",
    "ul_password",
    "snapeda_username",
    "snapeda_password",
    "samacsys_username",
    "samacsys_password",
)


def _load_dev_creds(ctx) -> list[str]:
    """Apply any credentials present in the per-machine dev-creds.json (in the OS config dir, never
    the repo) to the running config and persist. A missing or unreadable file is a no-op. Returns
    the field NAMES that were loaded (never the values), so the UI can confirm what landed."""
    import json

    from stockroom.store.machine_config import config_dir

    path = config_dir() / "dev-creds.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    loaded: list[str] = []
    for field in _DEV_CRED_FIELDS:
        value = data.get(field)
        if value:
            setattr(ctx.config, field, str(value))
            loaded.append(field)
    if loaded:
        ctx.config.save()
    return loaded


def _settings_dto(ctx) -> dict:
    config = ctx.config
    return {
        "mouser_api_key_set": bool(config.mouser_api_key),
        "mouser_api_key_hint": _hint(config.mouser_api_key),
        # The GitHub token is never revealed, only whether one is stored + its last 4 chars, so the
        # user can confirm which token is connected without the surface exposing the secret.
        "github_token_set": bool(config.github_token),
        "github_token_hint": _hint(config.github_token),
        # DigiKey Product Information API v4 OAuth client-credentials. The client_id is a
        # non-secret identifier (echoed so the UI can confirm which client is stored); the
        # client_secret is masked to presence + last 4, exactly like the Mouser key.
        "digikey_client_id": config.digikey_client_id,
        "digikey_client_secret_set": bool(config.digikey_client_secret),
        "digikey_client_secret_hint": _hint(config.digikey_client_secret),
        # DigiKey account web login (the driver's hands-free sign-in), distinct from the API
        # creds above. The username is echoed; the password is masked.
        "digikey_username": config.digikey_username,
        "digikey_password_set": bool(config.digikey_password),
        "digikey_password_hint": _hint(config.digikey_password),
        # Saved logins for the in-DigiKey CAD providers (Ultra Librarian, SnapEDA, SamacSys).
        # Usernames are not secrets (echoed so the UI can prefill them); passwords are masked
        # to presence + last 4, never revealed, exactly like the Mouser key.
        "ul_username": config.ul_username,
        "ul_password_set": bool(config.ul_password),
        "ul_password_hint": _hint(config.ul_password),
        "snapeda_username": config.snapeda_username,
        "snapeda_password_set": bool(config.snapeda_password),
        "snapeda_password_hint": _hint(config.snapeda_password),
        "samacsys_username": config.samacsys_username,
        "samacsys_password_set": bool(config.samacsys_password),
        "samacsys_password_hint": _hint(config.samacsys_password),
        # KiCad wiring state: the overrides (not secrets), the effective locations
        # they resolve to, and whether SR_LIB currently points at the active profile.
        "kicad_config_override": config.kicad_config_override,
        "kicad_cli_override": config.kicad_cli_override,
        # STM32CubeMX MCU XML source path (stm-viewer workstream, Phase 3). A plain
        # filesystem path, not a secret - echoed raw, following the kicad_*_override
        # pattern (NOT the masked-hint pattern used for API keys/passwords above).
        "stm_cubemx_source": config.stm_cubemx_source,
        "kicad_config_dir": ctx.kicad_dir.as_posix(),
        "kicad_cli_path": ctx.cli.binary or "",
        "kicad_cli_available": ctx.cli.available,
        "kicad_wired": (
            read_env_var(ctx.kicad_dir / "kicad_common.json", "SR_LIB")
            == str(ctx.profile.root.resolve())
        ),
        # the last automatic wiring's honest outcome, so a green SR_LIB pointer can
        # never mask a failed category-lib step or a skipped machine
        "kicad_wiring_error": getattr(ctx.last_wiring, "error", "") or "",
        "kicad_wiring_skipped": getattr(ctx.last_wiring, "skipped", "") or "",
    }


def settings_router(require_token) -> APIRouter:
    r = APIRouter(prefix="/api/settings", dependencies=[Depends(require_token)])

    @r.get("")
    def get_settings(request: Request) -> dict:
        ctx = request.app.state.ctx
        return _settings_dto(ctx)

    @r.post("/load-dev-creds")
    def load_dev_creds(request: Request) -> dict:
        # The hidden "secret combo" target: pull any API keys / logins from the per-machine
        # dev-creds.json (OS config dir, never the repo) into the config so live validation is not
        # blocked on retyping them. Absent file -> empty loaded list, DTO unchanged.
        from stockroom.store.machine_config import config_dir

        ctx = request.app.state.ctx
        loaded = _load_dev_creds(ctx)
        # the exact path searched, so an empty result can say WHERE to put the file
        # (the owner hit a bare "not found" on a fresh laptop, 2026-07-24)
        return {"loaded": loaded, "config_path": (config_dir() / "dev-creds.json").as_posix(),
                **_settings_dto(ctx)}

    @r.patch("")
    def update_settings(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        # only touch a field the caller actually sent, so an empty PATCH is a
        # no-op and an unknown field is ignored rather than corrupting the config
        if "mouser_api_key" in body:
            ctx.config.mouser_api_key = str(body["mouser_api_key"] or "")
            ctx.config.save()
        # Saved credentials (no live-apply side effect beyond ctx.config being updated, so the
        # next enrich / cad-source build picks them up): write only the fields sent, then
        # persist once (not once per field). Covers the DigiKey API creds, the DigiKey account
        # login, and the in-DigiKey providers Ultra Librarian, SnapEDA, and SamacSys.
        _vendor_dirty = False
        for _vendor_field in (
            "digikey_client_id",
            "digikey_client_secret",
            "digikey_username",
            "digikey_password",
            "ul_username",
            "ul_password",
            "snapeda_username",
            "snapeda_password",
            "samacsys_username",
            "samacsys_password",
        ):
            if _vendor_field in body:
                setattr(ctx.config, _vendor_field, str(body[_vendor_field] or ""))
                _vendor_dirty = True
        if _vendor_dirty:
            ctx.config.save()
        if "github_token" in body:
            ctx.config.github_token = str(body["github_token"] or "").strip()
            ctx.config.save()
            # Apply the credential to the library repo LIVE so push/pull authenticate immediately,
            # not only after the next boot. Non-fatal: a non-git library never fails the save.
            try:
                from stockroom.vcs import github_auth

                github_auth.configure(ctx.repo, ctx.config.github_token)
            except Exception:  # noqa: BLE001 - applying the credential is best-effort
                pass
        if "kicad_cli_override" in body or "kicad_config_override" in body:
            # strip whitespace AND the quotes Windows "Copy as path" wraps around
            # a path, which would otherwise break wiring and CLI discovery
            if "kicad_cli_override" in body:
                ctx.config.kicad_cli_override = str(body["kicad_cli_override"] or "").strip().strip('"')
            if "kicad_config_override" in body:
                ctx.config.kicad_config_override = str(body["kicad_config_override"] or "").strip().strip('"')
            ctx.config.save()
            # Rebuild the cli/ops/config-dir LIVE and rewire KiCad at the active
            # library, so the change takes effect without a restart.
            ctx.apply_kicad_settings()
        if "stm_cubemx_source" in body:
            # No live-apply side effect: changing the source path does not rebuild the
            # STM index - the user separately POSTs /api/stm/build.
            ctx.config.stm_cubemx_source = str(body["stm_cubemx_source"] or "").strip().strip('"')
            ctx.config.save()
        return _settings_dto(ctx)

    return r
