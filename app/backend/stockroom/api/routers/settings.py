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


def _settings_dto(ctx) -> dict:
    config = ctx.config
    return {
        "mouser_api_key_set": bool(config.mouser_api_key),
        "mouser_api_key_hint": _hint(config.mouser_api_key),
        # The GitHub token is never revealed, only whether one is stored + its last 4 chars, so the
        # user can confirm which token is connected without the surface exposing the secret.
        "github_token_set": bool(config.github_token),
        "github_token_hint": _hint(config.github_token),
        # Saved vendor logins for the guided capture window. Usernames are not secrets
        # (echoed so the UI can prefill them); passwords are masked to presence + last 4,
        # never revealed, exactly like the Mouser key.
        "ul_username": config.ul_username,
        "ul_password_set": bool(config.ul_password),
        "ul_password_hint": _hint(config.ul_password),
        "snapeda_username": config.snapeda_username,
        "snapeda_password_set": bool(config.snapeda_password),
        "snapeda_password_hint": _hint(config.snapeda_password),
        # KiCad wiring state: the overrides (not secrets), the effective locations
        # they resolve to, and whether SR_LIB currently points at the active profile.
        "kicad_config_override": config.kicad_config_override,
        "kicad_cli_override": config.kicad_cli_override,
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

    @r.patch("")
    def update_settings(request: Request, body: dict) -> dict:
        ctx = request.app.state.ctx
        # only touch a field the caller actually sent, so an empty PATCH is a
        # no-op and an unknown field is ignored rather than corrupting the config
        if "mouser_api_key" in body:
            ctx.config.mouser_api_key = str(body["mouser_api_key"] or "")
            ctx.config.save()
        # Saved vendor logins (no live-apply side effect): write only the fields sent,
        # then persist once (not once per field).
        _vendor_dirty = False
        for _vendor_field in ("ul_username", "ul_password", "snapeda_username", "snapeda_password"):
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
        return _settings_dto(ctx)

    return r
