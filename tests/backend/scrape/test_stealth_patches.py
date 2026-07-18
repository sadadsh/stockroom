from stockroom.scrape.stealth.patches import (
    STEALTH_INIT_SCRIPT,
    real_user_agent,
    stealth_context_options,
    stealth_launch_args,
)


def test_real_user_agent_de_headlesses():
    ua = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
          "HeadlessChrome/149.0.7827.55 Safari/537.36")
    fixed = real_user_agent(ua)
    assert "Headless" not in fixed
    assert "Chrome/149.0.7827.55" in fixed


def test_launch_args_disable_automation():
    args = stealth_launch_args()
    assert "--disable-blink-features=AutomationControlled" in args
    assert "--no-sandbox" in args


def test_init_script_patches_the_detection_surface():
    s = STEALTH_INIT_SCRIPT
    assert "navigator" in s and "webdriver" in s
    assert "plugins" in s
    assert "getParameter" in s  # WebGL vendor/renderer spoof


def test_context_options_carry_a_user_agent():
    opts = stealth_context_options("Mozilla/5.0 Chrome/149")
    assert opts["user_agent"] == "Mozilla/5.0 Chrome/149"
    assert opts["locale"] == "en-US"
    assert "viewport" in opts
