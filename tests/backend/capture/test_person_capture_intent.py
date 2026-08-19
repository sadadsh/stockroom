"""The person's OWN Finish and Skip controls, and the channel that carries them into a live run.

WHY THIS EXISTS
De-automation removed the provider HUD, so the Finish / Try Another / Close buttons that used to be
drawn over the provider page are gone. What replaced them was nothing: a person-driven route ended
only on Stockroom's global Cancel, roughly 25 seconds of quiet after at least one file had landed,
or the 600 second timeout. DigiKey fans out to FIVE author routes, so a part where nothing
downloads held the owner for five timeouts in a row.

WHAT IS ASSERTED
That the signal is a statement of the PERSON'S intent held for a running capture and refused
otherwise; that finishing a route is answered ONCE (a latched finish would end all five DigiKey
routes on one click); that skipping travels on the same predicate the runner already stops on; and
that both are named in the capture trace so a run's story says who ended it.
"""

from __future__ import annotations

import logging

import pytest

from stockroom.capture.intent import (
    FINISH_ROUTE,
    SKIP_PART,
    PersonCaptureIntent,
    PersonCaptureIntentError,
    active_person_capture,
    person_capture_intent,
    queue_person_capture_files,
    running_person_captures,
    signal_person_capture,
)
from stockroom.capture.trace import LOGGER_NAME, reset_for_tests


@pytest.fixture(autouse=True)
def _isolated_trace(tmp_path, monkeypatch):
    monkeypatch.setenv("STOCKROOM_CAPTURE_LOG", str(tmp_path / "capture.log"))
    reset_for_tests()
    yield
    reset_for_tests()


# --- 1. the signal only exists while a capture does --------------------------------------------


def test_a_signal_for_a_part_with_no_running_capture_is_refused_not_remembered():
    with pytest.raises(PersonCaptureIntentError):
        signal_person_capture("lm317", FINISH_ROUTE, route_token="route-not-running")

    # And nothing was stored, so the NEXT run for that part starts unsignalled.
    intent = PersonCaptureIntent()
    with person_capture_intent("lm317", intent):
        assert intent.take_route_finish() is False
        assert intent.part_skipped() is False


def test_a_running_capture_is_published_under_its_part_for_exactly_its_run():
    intent = PersonCaptureIntent()

    assert running_person_captures() == ()
    with person_capture_intent("lm317", intent):
        assert running_person_captures() == ("lm317",)
        assert intent.part_id == "lm317"
    assert running_person_captures() == ()


def test_the_active_provider_route_is_visible_only_for_its_exact_running_capture():
    intent = PersonCaptureIntent()

    assert active_person_capture("item-1", part_id="lm317") is None
    with person_capture_intent("lm317", intent, capture_id="item-1"):
        assert active_person_capture("item-1", part_id="lm317") is None
        route_token = intent.set_active_route(
            "digikey",
            "https://www.digikey.com/en/products/detail/example",
            "digikey-snapmagic",
        )
        assert active_person_capture("item-1", part_id="lm317") == {
            "vendor": "digikey",
            "detail_url": "https://www.digikey.com/en/products/detail/example",
            "evidence_provider_key": "digikey-snapmagic",
            "route_token": route_token,
            "download_progress": None,
            "browser_state": None,
        }
        intent.set_download_progress({
            "active": 1,
            "completed": 0,
            "bytes_received": 50,
            "total_bytes": 100,
            "files": [{
                "name": "LM317.zip",
                "state": "in_progress",
                "bytes_received": 50,
                "total_bytes": 100,
            }],
        })
        intent.set_browser_state({
            "url": "https://www.digikey.com/en/products/detail/example/redirected",
            "loading": False,
            "navigation_error": "",
            "can_go_back": True,
            "can_go_forward": False,
        })
        active = active_person_capture("item-1", part_id="lm317")
        assert active is not None
        assert active["browser_state"] == {
            "url": "https://www.digikey.com/en/products/detail/example/redirected",
            "loading": False,
            "navigation_error": "",
            "can_go_back": True,
            "can_go_forward": False,
        }
        assert active["download_progress"] == {
            "active": 1,
            "completed": 0,
            "bytes_received": 50,
            "total_bytes": 100,
            "files": [{
                "name": "LM317.zip",
                "state": "in_progress",
                "bytes_received": 50,
                "total_bytes": 100,
            }],
        }
        intent.clear_active_route(
            "digikey",
            "https://www.digikey.com/en/products/detail/example",
            "digikey-snapmagic",
            route_token,
        )
        assert active_person_capture("item-1", part_id="lm317") is None
    assert active_person_capture("item-1", part_id="lm317") is None


def test_selected_files_wake_only_the_exact_capture_generation_and_author_route(tmp_path):
    selected = tmp_path / "LM317.step"
    selected.write_bytes(b"model")
    intent = PersonCaptureIntent()
    url = "https://www.digikey.com/en/products/detail/example"

    with person_capture_intent("lm317", intent, capture_id="item-current"):
        route_token = intent.set_active_route("digikey", url, "digikey-snapmagic")
        with pytest.raises(PersonCaptureIntentError):
            queue_person_capture_files(
                "item-stale",
                part_id="lm317",
                vendor="digikey",
                detail_url=url,
                route_token=route_token,
                paths=(selected,),
            )
        with pytest.raises(PersonCaptureIntentError):
            queue_person_capture_files(
                "item-current",
                part_id="lm317",
                vendor="digikey",
                detail_url=url,
                route_token="stale-route-token",
                paths=(selected,),
            )
        intent.finish_route(route_token)
        queue_person_capture_files(
            "item-current",
            part_id="lm317",
            vendor="digikey",
            detail_url=url,
            route_token=route_token,
            paths=(selected,),
        )
        assert intent.take_route_finish() is True
        assert intent.take_selected_files(
            "digikey", url, "digikey-ultralibrarian", route_token
        ) == ()
        assert intent.take_selected_files(
            "digikey", url, "digikey-snapmagic", route_token
        ) == (selected,)
        assert intent.take_route_finish() is False
        with pytest.raises(PersonCaptureIntentError):
            queue_person_capture_files(
                "item-current",
                part_id="lm317",
                vendor="digikey",
                detail_url=url,
                route_token=route_token,
                paths=(selected,),
            )


def test_an_empty_route_drain_closes_intake_before_cleanup(tmp_path):
    selected = tmp_path / "late.step"
    selected.write_bytes(b"late")
    intent = PersonCaptureIntent()
    url = "https://www.digikey.com/en/products/detail/example"

    with person_capture_intent("lm317", intent, capture_id="item-current"):
        route_token = intent.set_active_route(
            "digikey", url, "digikey-ultralibrarian"
        )
        assert intent.take_selected_files(
            "digikey", url, "digikey-ultralibrarian", route_token
        ) == ()
        with pytest.raises(PersonCaptureIntentError):
            queue_person_capture_files(
                "item-current",
                part_id="lm317",
                vendor="digikey",
                detail_url=url,
                route_token=route_token,
                paths=(selected,),
            )


def test_a_library_wide_run_publishes_nothing_a_person_could_signal():
    intent = PersonCaptureIntent()

    with person_capture_intent(None, intent):
        assert running_person_captures() == ()


def test_one_part_cannot_own_two_captures_at_once():
    with person_capture_intent("lm317", PersonCaptureIntent()):
        with pytest.raises(PersonCaptureIntentError):
            with person_capture_intent("lm317", PersonCaptureIntent()):
                pytest.fail("a second capture claimed the same part")


def test_an_unknown_action_or_a_blank_part_is_a_caller_error():
    with person_capture_intent("lm317", PersonCaptureIntent()):
        with pytest.raises(ValueError):
            signal_person_capture("lm317", "finish-everything")
        with pytest.raises(ValueError):
            signal_person_capture("  ", FINISH_ROUTE)


# --- 2. finishing a route is answered once, for the route in front of the person ----------------


def test_finishing_a_route_is_consumed_by_the_one_route_that_is_open():
    intent = PersonCaptureIntent()
    with person_capture_intent("lm317", intent):
        route_token = intent.set_active_route(
            "digikey", "https://provider.example/part", "digikey-ultralibrarian"
        )
        signal_person_capture("lm317", FINISH_ROUTE, route_token=route_token)

        # The route that is open when the person says it takes the answer...
        assert intent.take_route_finish() is True
        # ...and the next of DigiKey's five author routes does NOT, because one click means one
        # route. A latched finish would close every remaining route with nobody asking.
        assert intent.take_route_finish() is False


def test_finishing_never_stops_the_part_so_files_already_adopted_keep_landing():
    intent = PersonCaptureIntent()
    with person_capture_intent("lm317", intent):
        route_token = intent.set_active_route(
            "digikey", "https://provider.example/part", "digikey-ultralibrarian"
        )
        signal_person_capture("lm317", FINISH_ROUTE, route_token=route_token)

        # Finish means "no more is coming", never "throw away what landed": the run's own stop
        # predicate is untouched, so the route drains and attaches what it already has.
        assert intent.part_skipped() is False


# --- 3. skipping is the whole part's verdict, and it latches ------------------------------------


def test_skipping_the_part_latches_for_the_rest_of_the_run():
    intent = PersonCaptureIntent()
    with person_capture_intent("lm317", intent):
        signal_person_capture("lm317", SKIP_PART)

        assert intent.part_skipped() is True
        assert intent.part_skipped() is True


# --- 4. the trace names the person, so a run's story says who ended it --------------------------


def test_the_trace_records_a_person_driven_finish_a_skip_and_a_refusal(caplog):
    intent = PersonCaptureIntent()
    with caplog.at_level(logging.DEBUG, logger=LOGGER_NAME):
        with person_capture_intent("lm317", intent):
            route_token = intent.set_active_route(
                "digikey", "https://provider.example/part", "digikey-ultralibrarian"
            )
            signal_person_capture("lm317", FINISH_ROUTE, route_token=route_token)
            intent.take_route_finish()
            signal_person_capture("lm317", SKIP_PART)
        with pytest.raises(PersonCaptureIntentError):
            signal_person_capture("lm317", SKIP_PART)

    lines = [record.getMessage() for record in caplog.records]
    assert any(line.startswith("capture.person.finish part=lm317") for line in lines)
    assert any(line.startswith("capture.person.finish.applied part=lm317") for line in lines)
    assert any(line.startswith("capture.person.skip part=lm317") for line in lines)
    assert any(line.startswith("capture.person.refused part=lm317") for line in lines)
