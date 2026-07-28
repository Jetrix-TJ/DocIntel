"""GUARDRAIL 8: no hand-authored answer may score against gold.

`replay-gold` is this project's objective function. A cassette entry authored from a
gold file feeds the gold answer in as the model's answer and then scores it against
the gold answer - the run goes green and measures nothing. The failure mode is not
that it is wrong, it is that it is *indistinguishable from working*.

The implementation plan proposed exactly this as a bootstrap before an API key
existed. It stays available: author the entry, change this test, and write down why.
That is the same rule the gold files live under, for the same reason.
"""

from __future__ import annotations

import json
import os

from docintel.cli import DEFAULT_CASSETTE

VALID_PROVENANCE = ("recorded", "authored")


def _entries() -> dict[str, dict]:
    if not os.path.isfile(DEFAULT_CASSETTE):
        return {}
    with open(DEFAULT_CASSETTE, encoding="utf-8") as fh:
        return json.load(fh)


def test_the_default_cassette_exists_so_the_default_vision_mode_has_a_target():
    assert os.path.isfile(DEFAULT_CASSETTE), (
        f"{DEFAULT_CASSETTE} is the default for --vision cassette; an absent file "
        "replays as a loud miss, which is correct but undiscoverable"
    )


def test_no_entry_in_the_default_cassette_was_hand_authored():
    authored = [
        key for key, entry in _entries().items()
        if entry.get("provenance") != "recorded"
    ]
    assert authored == [], (
        f"cassette entries {authored} are not marked 'recorded'. An authored entry "
        "replayed into replay-gold scores the gold answer against itself. See "
        "tests/fixtures/cassettes/README.md before changing this test."
    )


def test_every_entry_declares_a_known_provenance():
    """An entry with no provenance is the dangerous case: it reads as recorded to a
    human skimming the file and is unverifiable."""
    for key, entry in _entries().items():
        assert entry.get("provenance") in VALID_PROVENANCE, (
            f"cassette entry {key!r} has provenance {entry.get('provenance')!r}"
        )
