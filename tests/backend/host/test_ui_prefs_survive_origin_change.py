"""UI preferences must survive the page ORIGIN changing between launches.

MEASURED on real Windows (2026-07-25), driving the real app through two controlled restarts:

    rail:  origin :65149  collapsed "1"  rail 52px  ->  restart  ->  origin :60359  collapsed "0"  rail 190px
    theme: origin :60359  theme "light"              ->  restart  ->  origin :55588  theme "dark"

The host binds an EPHEMERAL PORT, so `http://127.0.0.1:<port>` is a DIFFERENT ORIGIN on every
launch, and localStorage is origin-scoped. Every preference therefore starts empty and the app
rewrites its defaults. The owner's theme choice has been silently reverting on every single launch
for as long as the host has used an ephemeral port.

No existing test could catch this: they all run against ONE origin, where localStorage works
perfectly. So these tests assert the two properties that actually matter -

  1. the preference is stored somewhere ORIGIN-INDEPENDENT (the machine config), and
  2. the host hands it to the page SYNCHRONOUSLY at boot, before the SPA's first paint, so the
     restored theme cannot flash the wrong one first.
"""

from __future__ import annotations

import json
import re

from stockroom.host.window import inject_script
from stockroom.store.machine_config import MachineConfig


def test_ui_preferences_survive_a_save_and_reload(tmp_path):
    """Origin-independent storage: the preference must come back from DISK, which is the whole
    point - a new page origin cannot take it away. A dict, so a new preference needs no migration."""
    cfg = MachineConfig()
    assert hasattr(cfg, "ui"), "MachineConfig has no `ui` field, so a preference has nowhere to live that outlasts the origin"
    assert cfg.ui == {}, "ui should default empty; a default here would override a real choice"

    path = tmp_path / "config.json"
    cfg.ui = {"theme": "light", "rail_collapsed": True}
    cfg.save(path)

    # A DIFFERENT process/origin loading the same machine config - the real-world restart.
    reloaded = MachineConfig.load(path)
    assert reloaded.ui == {"theme": "light", "rail_collapsed": True}, (
        "ui preferences did not survive a save/reload, so a restart still loses them"
    )


def test_boot_script_injects_ui_preferences_synchronously():
    """The page must receive the preferences in the SAME injected script that already carries the
    API base and token - i.e. before the SPA runs. Fetching them later paints the default first."""
    script = inject_script("http://127.0.0.1:1234/", "tok", ui={"theme": "light"})

    assert "__STOCKROOM_UI__" in script, (
        "the boot script does not hand the page its UI preferences, so the SPA can only learn them "
        "asynchronously and will paint the wrong theme first"
    )
    match = re.search(r"window\.__STOCKROOM_UI__\s*=\s*(\{.*?\});", script, re.S)
    assert match, "the UI preferences are not assigned as a JSON object literal"
    assert json.loads(match.group(1)) == {"theme": "light"}

    # JSON-encoded, like the token beside it: a value with a quote or backslash must not be able to
    # break out of the script it is embedded in.
    hostile = inject_script("http://127.0.0.1:1234/", "tok", ui={"theme": 'l"ight</script>'})
    assert "</script>" not in hostile.replace("<\\/script>", ""), "UI prefs are not safely encoded"


def test_boot_script_still_works_with_no_preferences_saved():
    """A fresh install has no stored preferences; the page must still boot with a valid object."""
    script = inject_script("http://127.0.0.1:1234/", "tok")
    match = re.search(r"window\.__STOCKROOM_UI__\s*=\s*(\{.*?\});", script, re.S)
    assert match, "the boot script must always define __STOCKROOM_UI__, even when empty"
    assert json.loads(match.group(1)) == {}
