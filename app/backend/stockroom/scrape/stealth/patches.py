"""Own-code Chromium stealth (spec section 6): launch flags, a de-Headless real
User-Agent, context options, and an init script that patches the standard
headless-detection surfaces. Verified necessary by the S2 feasibility probe: a
default Playwright Chromium reports navigator.webdriver === true and a
"HeadlessChrome" User-Agent, both instant bot tells. Applied at full strength on
every render (no ramp), all our own code, no paid services."""

from __future__ import annotations


def stealth_launch_args() -> list[str]:
    # --disable-blink-features=AutomationControlled removes the navigator.webdriver
    # automation flag at the engine level (belt-and-suspenders with the init script);
    # the no-sandbox / dev-shm flags keep Chromium stable in containers and WSL where
    # the sandbox and /dev/shm are constrained.
    return [
        "--disable-blink-features=AutomationControlled",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
    ]


def real_user_agent(default_ua: str) -> str:
    """De-Headless the engine's own UA rather than invent one: HeadlessChrome/149 ->
    Chrome/149. The version stays honest (the engine IS Chromium 149) and
    navigator.platform stays Linux, so the identity is internally coherent."""
    return default_ua.replace("HeadlessChrome", "Chrome").replace("Headless", "")


def stealth_context_options(user_agent: str) -> dict:
    return {
        "user_agent": user_agent,
        "locale": "en-US",
        "timezone_id": "America/New_York",
        "viewport": {"width": 1280, "height": 800},
        "device_scale_factor": 1,
    }


# Injected via add_init_script BEFORE any page script runs, so a detector reading
# these at load sees a normal browser. Each patch targets a documented tell.
STEALTH_INIT_SCRIPT = r"""
(() => {
  try { Object.defineProperty(navigator, 'webdriver', {get: () => undefined}); } catch (e) {}
  try {
    Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]});
    Object.defineProperty(navigator, 'mimeTypes', {get: () => [1, 2]});
  } catch (e) {}
  try { Object.defineProperty(navigator, 'languages', {get: () => ['en-US', 'en']}); } catch (e) {}
  try { if (!window.chrome) { window.chrome = { runtime: {} }; } } catch (e) {}
  try {
    const orig = window.navigator.permissions && window.navigator.permissions.query;
    if (orig) {
      window.navigator.permissions.query = (p) =>
        p && p.name === 'notifications'
          ? Promise.resolve({ state: Notification.permission })
          : orig(p);
    }
  } catch (e) {}
  try {
    const gp = WebGLRenderingContext.prototype.getParameter;
    WebGLRenderingContext.prototype.getParameter = function (p) {
      if (p === 37445) return 'Intel Inc.';                 // UNMASKED_VENDOR_WEBGL
      if (p === 37446) return 'Intel Iris OpenGL Engine';   // UNMASKED_RENDERER_WEBGL
      return gp.call(this, p);
    };
  } catch (e) {}
})();
"""
