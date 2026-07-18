from stockroom.scrape.fetch.browser import (
    is_challenge_text,
    looks_settled,
    should_block_resource,
)


def test_challenge_text_detected():
    assert is_challenge_text("Verifying you are human. Please wait.") is True
    assert is_challenge_text("Checking your browser before accessing") is True
    assert is_challenge_text("LM317 Adjustable Regulator, 1.5A, TO-220") is False


def test_settle_requires_complete_stable_substantial_and_unchallenged():
    # complete, stable across two polls, >= 400 chars, not challenged -> settled
    assert looks_settled("complete", 500, 500, False) is True
    # still loading
    assert looks_settled("loading", 500, 500, False) is False
    # not yet stable (first poll: last is None)
    assert looks_settled("complete", 500, None, False) is False
    # changed since last poll
    assert looks_settled("complete", 500, 480, False) is False
    # too little text (a challenge shell)
    assert looks_settled("complete", 120, 120, False) is False
    # challenged
    assert looks_settled("complete", 500, 500, True) is False


def test_resource_blocking():
    assert should_block_resource("image", "https://x/logo.png") is True
    assert should_block_resource("font", "https://x/f.woff2") is True
    assert should_block_resource("media", "https://x/v.mp4") is True
    assert should_block_resource("document", "https://x/page") is False
    assert should_block_resource("script", "https://x/app.js") is False
    # a tracker host is blocked even when it is a script
    assert should_block_resource("script", "https://www.googletagmanager.com/gtm.js") is True
