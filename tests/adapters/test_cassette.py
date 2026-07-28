"""CassetteVision: replay is exact, a miss is loud, recording round-trips."""

from __future__ import annotations

import json

import pytest

from docintel.adapters.vision.cassette import CassetteVision
from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText, Word


def _pages(text: str = "TOTAL 1177.70") -> tuple[PageText, ...]:
    words = tuple(
        Word(text=t, x0=float(i * 40), y0=100.0, x1=float(i * 40 + 30), y1=110.0)
        for i, t in enumerate(text.split())
    )
    return (PageText(page_number=1, words=words, width=612.0, height=792.0, source="ocr"),)


def _write(path, entries: dict) -> None:
    path.write_text(json.dumps(entries), encoding="utf-8")


class Exploding:
    def extract(self, pages, field_names, *, source_path=None):
        raise AssertionError("must not be called in replay mode")


class Stub:
    def __init__(self, result: VisionResult) -> None:
        self.result = result
        self.calls = 0

    def extract(self, pages, field_names, *, source_path=None):
        self.calls += 1
        return self.result


# -- replay ----------------------------------------------------------------


def test_replay_returns_the_recorded_result_without_calling_the_inner_adapter(tmp_path):
    path = tmp_path / "c.json"
    v = CassetteVision(inner=Exploding(), path=str(path), mode="replay")
    key = v.key(_pages(), ["total_printed"])
    _write(path, {key: {"fields": {"total_printed": "1177.70"},
                        "confidence": {"total_printed": 0.82},
                        "irregularities": []}})

    result = v.extract(_pages(), ["total_printed"])

    assert result.fields["total_printed"] == "1177.70"
    assert result.confidence["total_printed"] == pytest.approx(0.82)


def test_replay_miss_is_a_loud_failure_not_a_silent_empty_result(tmp_path):
    path = tmp_path / "c.json"
    _write(path, {})
    v = CassetteVision(inner=None, path=str(path), mode="replay")
    with pytest.raises(KeyError, match="no cassette entry"):
        v.extract(_pages(), ["total_printed"])


def test_a_missing_cassette_file_is_a_miss_not_a_crash(tmp_path):
    """The distinction matters: a missing file must produce the same actionable
    KeyError as an empty one, not a FileNotFoundError from deep in the adapter."""
    v = CassetteVision(inner=None, path=str(tmp_path / "absent.json"), mode="replay")
    with pytest.raises(KeyError, match="--vision record"):
        v.extract(_pages(), ["total_printed"])


def test_replay_sanitizes_the_entry_so_a_hand_edited_cassette_cannot_smuggle_a_flag(
    tmp_path,
):
    """A cassette is a JSON file a human edits, which makes it untrusted input in
    exactly the way a model response is. `flattened_annotations` is the sharp case:
    it forces review, so a cassette must not be able to assert it."""
    path = tmp_path / "c.json"
    v = CassetteVision(inner=None, path=str(path), mode="replay")
    key = v.key(_pages(), ["total_printed"])
    _write(path, {key: {
        "fields": {"total_printed": "1177.70", "amount_payable": "9.99", "surprise": "x"},
        "confidence": {"total_printed": 5.0},
        "irregularities": ["flattened_annotations", "handwriting_detected"],
    }})

    result = v.extract(_pages(), ["total_printed"])

    assert set(result.fields) == {"total_printed"}
    assert result.confidence["total_printed"] == pytest.approx(0.99)  # clamped
    assert result.irregularities == ["handwriting_detected"]


def test_a_cassette_that_is_not_an_object_fails_clearly(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("[]", encoding="utf-8")
    v = CassetteVision(inner=None, path=str(path), mode="replay")
    with pytest.raises(ValueError, match="must be a JSON object"):
        v.extract(_pages(), ["total_printed"])


# -- record ----------------------------------------------------------------


def test_record_mode_persists_the_inner_result(tmp_path):
    path = tmp_path / "c.json"
    stub = Stub(VisionResult(fields={"total_printed": "481.20"},
                             confidence={"total_printed": 0.9}))
    v = CassetteVision(inner=stub, path=str(path), mode="record")

    v.extract(_pages(), ["total_printed"])

    saved = json.loads(path.read_text())
    assert any(e["fields"]["total_printed"] == "481.20" for e in saved.values())


def test_a_recorded_entry_replays_identically(tmp_path):
    """The round trip is the point: record then replay must reach the same values
    through the same sanitizing path, or a cassette proves nothing about a live run."""
    path = tmp_path / "c.json"
    stub = Stub(VisionResult(fields={"total_printed": "481.20"},
                             confidence={"total_printed": 0.9}))
    recorded = CassetteVision(inner=stub, path=str(path), mode="record").extract(
        _pages(), ["total_printed"]
    )

    replayed = CassetteVision(inner=None, path=str(path), mode="replay").extract(
        _pages(), ["total_printed"]
    )

    assert replayed == recorded
    assert stub.calls == 1


def test_record_marks_provenance_so_an_authored_entry_is_distinguishable(tmp_path):
    path = tmp_path / "c.json"
    v = CassetteVision(
        inner=Stub(VisionResult(fields={"total_printed": "1.00"})),
        path=str(path),
        mode="record",
        model="claude-opus-5",
    )
    v.extract(_pages(), ["total_printed"])

    entry = next(iter(json.loads(path.read_text()).values()))
    assert entry["provenance"] == "recorded"
    assert entry["model"] == "claude-opus-5"
    assert entry["field_names"] == ["total_printed"]


def test_recording_a_second_call_keeps_the_first(tmp_path):
    path = tmp_path / "c.json"
    first = CassetteVision(
        inner=Stub(VisionResult(fields={"total_printed": "1.00"})),
        path=str(path), mode="record",
    )
    first.extract(_pages("A"), ["total_printed"])
    second = CassetteVision(
        inner=Stub(VisionResult(fields={"total_printed": "2.00"})),
        path=str(path), mode="record",
    )
    second.extract(_pages("B"), ["total_printed"])

    assert len(json.loads(path.read_text())) == 2


def test_record_mode_without_an_inner_extractor_is_rejected_at_construction(tmp_path):
    with pytest.raises(ValueError, match="record mode needs an inner"):
        CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="record")


def test_an_unknown_mode_is_rejected(tmp_path):
    with pytest.raises(ValueError, match="mode must be"):
        CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replayy")


# -- keying ----------------------------------------------------------------


def test_cassette_key_is_stable_for_the_same_pages_and_fields(tmp_path):
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")
    assert v.key(_pages(), ["a", "b"]) == v.key(_pages(), ["a", "b"])
    assert v.key(_pages(), ["a"]) != v.key(_pages(), ["a", "b"])


def test_different_page_text_keys_differently(tmp_path):
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")
    assert v.key(_pages("TOTAL 1.00"), ["a"]) != v.key(_pages("TOTAL 2.00"), ["a"])


def test_the_key_follows_the_source_bytes_not_the_path(tmp_path):
    """The C1a lesson: content-hash keys. A cassette must survive the corpus moving
    and must go stale when the document itself changes."""
    a = tmp_path / "one.pdf"
    b = tmp_path / "two.pdf"
    a.write_bytes(b"%PDF-1.4 same")
    b.write_bytes(b"%PDF-1.4 same")
    changed = tmp_path / "three.pdf"
    changed.write_bytes(b"%PDF-1.4 different")
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")

    assert v.key((), ["a"], str(a)) == v.key((), ["a"], str(b))
    assert v.key((), ["a"], str(a)) != v.key((), ["a"], str(changed))


def test_a_source_backed_key_never_collides_with_a_text_backed_one(tmp_path):
    """Domain separation. Without it, a cassette recorded from a file could be
    replayed for a text-only call about a different document."""
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4")
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")

    assert v.key(_pages(), ["a"], str(pdf)) != v.key(_pages(), ["a"])


def test_an_unreadable_source_path_falls_back_to_the_text_layer(tmp_path):
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")
    assert v.key(_pages(), ["a"], str(tmp_path / "gone.pdf")) == v.key(_pages(), ["a"])
