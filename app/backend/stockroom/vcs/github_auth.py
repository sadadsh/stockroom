"""Authenticate a repo's git operations to GitHub with a personal access token, so the in-repo
library can push a part add + pull collaborators' changes without an interactive credential prompt.

The token is injected as a per-repo `http.https://github.com/.extraheader` (an HTTP Authorization
header git sends on every request to github.com over https), NOT baked into the remote URL: so it
never appears in `git remote -v`, and it lives only in the repo's LOCAL .git/config (git's internal
dir, never a tracked / committed file). The token itself is stored per-machine in config.json (in
the OS config dir, never the repo) and re-applied on boot, since a recovery re-clone resets
.git/config. Basic auth with the token as the password is how GitHub authenticates a git https
operation; the username is a conventional placeholder.

No em dashes anywhere (standing owner rule).
"""

from __future__ import annotations

import base64

# Match ONLY github.com https requests from this repo, so the token never leaks to another host.
_GITHUB_HTTPS = "https://github.com/"
EXTRAHEADER_KEY = f"http.{_GITHUB_HTTPS}.extraheader"


def auth_header(token: str) -> str:
    """The Authorization header value that basic-authenticates a GitHub git https request with
    `token` as the password (username is a conventional placeholder GitHub ignores)."""
    creds = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"AUTHORIZATION: basic {creds}"


def configure(repo, token: str) -> None:
    """Apply `token` (or clear it when blank) as this repo's GitHub credential. Idempotent: a
    re-apply overwrites the single header; a blank token removes it. Any git error (no repo) is
    surfaced by the caller's own error handling; a missing key on unset is not an error."""
    token = (token or "").strip()
    if token:
        repo.set_config(EXTRAHEADER_KEY, auth_header(token))
    else:
        repo.unset_config(EXTRAHEADER_KEY)
