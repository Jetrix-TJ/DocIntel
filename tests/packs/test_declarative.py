"""A malformed classification spec must fail at LOAD, never at classify time.

This is the whole safety argument for making the ladder data. A hand-written
`if` chain fails loudly when you break it - Python raises. A data-driven one can
fail *silently*: a misspelled signal name, an unknown scope, a typo'd parameter
would each evaluate to "condition did not hold", and the rung would simply never
fire. A document type that silently never gets recognised is exactly the class of
failure this project refuses to ship (`s3_classify.py`: an unclaimed document is
flagged, never dropped).

So every one of those is a `LadderError` raised while the pack is being loaded,
before any document has been seen.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs import declarative
from docintel.packs.declarative import LadderError, compile_classification

REPO = pathlib.Path(__file__).resolve().parents[2]


def _ladder(when: dict) -> dict:
    return {"ladder": {"default": "standard_invoice",
                       "rungs": [{"name": "r", "doc_type": "d", "when": when}]}}


# --------------------------------------------------------------------------
# Authoring errors, each caught at load
# --------------------------------------------------------------------------


def test_an_unknown_signal_is_rejected() -> None:
    with pytest.raises(LadderError, match="unknown signal"):
        compile_classification(_ladder({"signal": "definitely_not_a_signal"}))


def test_an_unknown_scope_is_rejected() -> None:
    with pytest.raises(LadderError, match="unknown scope"):
        compile_classification(
            _ladder({"signal": "pattern_in_scope",
                     "params": {"pattern": "x", "scope": "everywhere"}})
        )


def test_a_misspelled_parameter_is_rejected() -> None:
    """The one a plain schema check would miss. `max_wordz` is a perfectly valid
    JSON key; only calling the signal reveals it is not a parameter."""
    with pytest.raises(LadderError, match="rejected its parameters"):
        compile_classification(
            _ladder({"signal": "title_near_top",
                     "params": {"pattern": "x", "max_wordz": 7, "max_line_index": 10}})
        )


def test_a_bad_regex_is_rejected() -> None:
    with pytest.raises(LadderError, match="bad regex"):
        compile_classification(
            _ladder({"signal": "pattern_in_scope", "params": {"pattern": "(unclosed", "scope": "all"}})
        )


def test_an_unknown_value_predicate_is_rejected() -> None:
    with pytest.raises(LadderError, match="unknown value predicate"):
        compile_classification(
            _ladder({"signal": "label_with_corroborating_value",
                     "params": {"label": "tax", "next_line": "vibes"}})
        )


def test_an_empty_combinator_is_rejected() -> None:
    """An empty `all_of` is vacuously TRUE, so its rung would fire on every
    document; an empty `any_of` is vacuously false and would fire on none.
    Both are far likelier to be an authoring slip than an intent."""
    with pytest.raises(LadderError, match="must not be empty"):
        compile_classification(_ladder({"all_of": []}))
    with pytest.raises(LadderError, match="must not be empty"):
        compile_classification(_ladder({"any_of": []}))


def test_a_condition_with_two_operators_is_rejected() -> None:
    with pytest.raises(LadderError, match="exactly one of"):
        compile_classification(
            _ladder({"signal": "shared_pagination_footer", "not": {"signal": "shared_pagination_footer"}})
        )


def test_a_duplicate_rung_name_is_rejected() -> None:
    """`signal_that_fired` is what an auditor reads to learn WHY a document was
    classified. Two rungs sharing a name makes that answer ambiguous."""
    spec = {"ladder": {"default": "x", "rungs": [
        {"name": "same", "doc_type": "a", "when": {"signal": "shared_pagination_footer"}},
        {"name": "same", "doc_type": "b", "when": {"signal": "shared_pagination_footer"}},
    ]}}
    with pytest.raises(LadderError, match="duplicate rung name"):
        compile_classification(spec)


def test_a_rung_named_default_is_rejected() -> None:
    spec = {"ladder": {"default": "x", "rungs": [
        {"name": "default", "doc_type": "a", "when": {"signal": "shared_pagination_footer"}},
    ]}}
    with pytest.raises(LadderError, match="reserved"):
        compile_classification(spec)


def test_an_empty_ladder_is_rejected() -> None:
    with pytest.raises(LadderError, match="non-empty"):
        compile_classification({"ladder": {"default": "x", "rungs": []}})


def test_a_duplicate_tag_is_rejected() -> None:
    spec = _ladder({"signal": "shared_pagination_footer"})
    spec["tags"] = [
        {"tag": "dup", "when": {"signal": "shared_pagination_footer"}},
        {"tag": "dup", "when": {"signal": "shared_pagination_footer"}},
    ]
    with pytest.raises(LadderError, match="duplicate tag"):
        compile_classification(spec)


# --------------------------------------------------------------------------
# Semantics
# --------------------------------------------------------------------------


def _ctx(text: str, role: str = "primary"):
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (
        PageText(page_number=1, words=tuple(words), width=612.0, height=792.0, source="native"),
    )
    ctx.page_meta = (PageMeta(1, 100, 0, 0, role),)
    return ctx


def test_the_first_matching_rung_wins_and_the_ladder_stops() -> None:
    """Spec Stage 3's rule, now explicit in data rather than implicit in the
    order of `if` statements."""
    spec = {"ladder": {"default": "fallback", "rungs": [
        {"name": "first", "doc_type": "won",
         "when": {"signal": "pattern_in_scope", "params": {"pattern": "invoice", "scope": "all"}}},
        {"name": "second", "doc_type": "lost",
         "when": {"signal": "pattern_in_scope", "params": {"pattern": "invoice", "scope": "all"}}},
    ]}}
    ladder, _ = compile_classification(spec)
    assert ladder.doc_type_for(_ctx("INVOICE 100.00")) == ("won", "first")


def test_the_default_fires_when_no_rung_does() -> None:
    ladder, _ = compile_classification(_ladder(
        {"signal": "pattern_in_scope", "params": {"pattern": "zzz", "scope": "all"}}
    ))
    assert ladder.doc_type_for(_ctx("INVOICE")) == ("standard_invoice", "default")


def test_not_negates() -> None:
    ladder, _ = compile_classification(_ladder(
        {"not": {"signal": "pattern_in_scope", "params": {"pattern": "zzz", "scope": "all"}}}
    ))
    assert ladder.doc_type_for(_ctx("INVOICE"))[0] == "d"


def test_all_of_requires_every_child() -> None:
    ladder, _ = compile_classification(_ladder({"all_of": [
        {"signal": "pattern_in_scope", "params": {"pattern": "invoice", "scope": "all"}},
        {"signal": "pattern_in_scope", "params": {"pattern": "zzz", "scope": "all"}},
    ]}))
    assert ladder.doc_type_for(_ctx("INVOICE"))[1] == "default"


def test_tags_do_not_stop_at_the_first_match() -> None:
    """Unlike rungs. Tags are layered on and never change the type."""
    spec = _ladder({"signal": "pattern_in_scope", "params": {"pattern": "zzz", "scope": "all"}})
    spec["tags"] = [
        {"tag": "a", "when": {"signal": "pattern_in_scope", "params": {"pattern": "invoice", "scope": "all"}}},
        {"tag": "b", "when": {"signal": "pattern_in_scope", "params": {"pattern": "100", "scope": "all"}}},
    ]
    _, tags = compile_classification(spec)
    assert tags.tags_for(_ctx("INVOICE 100.00")) == ["a", "b"]


# --------------------------------------------------------------------------
# The shipped specs
# --------------------------------------------------------------------------


SHIPPED = [
    "src/docintel/packs/northstar/classification.json",
    "src/docintel/packs/digitaldirection/classification.json",
]


@pytest.mark.parametrize("path", SHIPPED)
def test_every_shipped_spec_compiles(path: str) -> None:
    """The declarative equivalent of GUARDRAIL 5 (`test_personas_validate.py`):
    a persona the grammar rejects is a silent lookup MISS, and a classification
    spec that will not compile is a pack that cannot classify at all."""
    full = REPO / path
    assert full.exists(), full
    compile_classification(json.loads(full.read_text()))


@pytest.mark.parametrize("path", SHIPPED)
def test_every_rung_and_tag_carries_a_reason(path: str) -> None:
    """House style, made mechanical. Every constant in this codebase cites the
    real document it was measured against; a rung expressed as data must not be
    able to drop that. `_why` explains why the rule is right; `_defect` records
    a known, parked wrongness. One or the other is required - a rung with
    neither is a rule nobody has justified.

    Exempt: rungs whose condition is a bare pattern match on an unambiguous
    marker, where the tag name IS the explanation (`has_scanline`).
    """
    spec = json.loads((REPO / path).read_text())
    SELF_EVIDENT = {"has_scanline", "mixed_sign", "sub_accounts", "ocr_only", "early_pay_discount"}
    unexplained = [
        rung["name"]
        for rung in spec["ladder"]["rungs"]
        if not (rung.get("_why") or rung.get("_defect"))
    ] + [
        tag["tag"]
        for tag in spec.get("tags", [])
        if not (tag.get("_why") or tag.get("_defect")) and tag["tag"] not in SELF_EVIDENT
    ]
    assert unexplained == [], f"no _why/_defect on: {unexplained}"


def test_the_signal_registry_is_closed() -> None:
    """A pack composes what the registry offers. Adding a primitive is a code
    change with a test and a named real document behind it - the same bar the
    grammar's BASE_ADJUST_OPS sets. This pins the current vocabulary so that
    growing it is a deliberate, reviewed act rather than a side effect.
    """
    assert set(declarative.SIGNALS) == {
        "pattern_in_scope",
        "short_label_line",
        "title_near_top",
        "text_near_top",
        "label_with_corroborating_value",
        "all_matches_negative",
        "role_shape",
        "shared_pagination_footer",
        "money_table_present",
        "text_source_is",
        "noise_ratio_above",
        "distinct_printed_aliases_at_least",
    }
