"""`cli._build_vision`: the mode -> adapter dispatch.

This was never directly tested before - only exercised indirectly through
whichever mode a given CLI test happened to pass. That left the one line
that decides which live model backs `--vision live`/`--vision record`
uncovered: a typo or a bad merge here would silently swap backends with no
test catching it. These tests pin the exact adapter class and wiring for
every mode, offline - `live`/`record` never make a network call or need a
key, since `GeminiVision()` only touches credentials lazily, inside
`_resolve_client`, the first time `.extract()` is actually invoked.
"""

from __future__ import annotations

from docintel.adapters.vision.cassette import CassetteVision
from docintel.adapters.vision.fake import FakeVision
from docintel.adapters.vision.gemini_adapter import MODEL, GeminiVision
from docintel.cli import DEFAULT_CASSETTE, VISION_MODES, _build_vision


def test_every_advertised_mode_is_handled():
    """`argparse`'s `choices=VISION_MODES` is the only gate stopping a typo
    from reaching `_build_vision` as a live mode string - this pins the set
    those choices actually promise."""
    assert VISION_MODES == ("cassette", "fake", "live", "record")


def test_fake_mode_returns_a_fake_vision():
    adapter = _build_vision("fake", DEFAULT_CASSETTE)
    assert isinstance(adapter, FakeVision)


def test_cassette_mode_replays_with_no_inner_fallback():
    """`inner=None` is load-bearing: a replay must never be able to fall
    through to a live call, which is exactly how a "deterministic" run would
    quietly start billing and stop being reproducible."""
    adapter = _build_vision("cassette", "some/cassette.json")
    assert isinstance(adapter, CassetteVision)
    assert adapter.inner is None
    assert adapter.mode == "replay"
    assert adapter.path == "some/cassette.json"


def test_live_mode_returns_a_bare_gemini_vision_not_wrapped_in_a_cassette():
    adapter = _build_vision("live", DEFAULT_CASSETTE)
    assert isinstance(adapter, GeminiVision)


def test_record_mode_wraps_a_gemini_vision_and_tags_it_with_the_model():
    adapter = _build_vision("record", "some/cassette.json")
    assert isinstance(adapter, CassetteVision)
    assert isinstance(adapter.inner, GeminiVision)
    assert adapter.mode == "record"
    assert adapter.model == MODEL
    assert adapter.path == "some/cassette.json"


def test_live_and_record_never_touch_credentials_until_extract_is_called():
    """Constructing the adapter must not require GEMINI_API_KEY/GOOGLE_API_KEY
    to be set, and must not import the google-genai SDK's client - only
    `.extract()` resolves a real client, lazily."""
    live = _build_vision("live", DEFAULT_CASSETTE)
    assert live._client is None  # not resolved yet
    record = _build_vision("record", DEFAULT_CASSETTE)
    assert record.inner._client is None


def test_cassette_mode_warns_clearly_when_the_default_cassette_is_not_packaged(capsys):
    """A fresh pip install user running `docintel process any.pdf --json` gets
    --vision cassette by default, pointing at a path that won't exist post-install.
    The cassette loads gracefully on missing file, so this would silently produce
    vision misses on every field with no signal why. Print an actionable warning
    instead of proceeding mute."""
    vision = _build_vision("cassette", "/definitely/does/not/exist/corpus.json")
    captured = capsys.readouterr()
    assert "no cassette found" in captured.err.lower()
    # still returns a working (if empty) CassetteVision - never raises, never silently proceeds mute
    assert vision is not None
