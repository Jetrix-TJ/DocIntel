"""Finding B regression: U-PAK's `vendor_account_number` selector must not be
a verbatim transcription of one gold value.

The shipped pattern used to be `(1 -[0-9]{5} 1)`, a direct copy of the single
gold value `"1 -24136 1"` (`docs/corpus/gold/northstar-upak-4378107.json`),
including its coincidental leading AND trailing `1`. Real second samples in
`all-docs/second-samples/u_pak/` show the true shape - `1 -23464 8`,
`1 -213121` (no internal space), `1 -23482 0`, `1 -23571 0`, `1 -23427 5`,
`1 -23435 8`, and more - 6 digits after a literal `"1 -"`, with an internal
space before the last digit that appears in some renderings and not others (a
text-layer rendering artifact, not a fixed field boundary). The old pattern
matched exactly one of these (none, actually - the gold value's trailing `1`
is coincidental, not a shape every account number shares).

Fix: swap the hand-rolled regex for the grammar's own named `account_number`
pattern (`docs/architecture/selector-grammar.md` S3.1) on the same
`anchor: "Account No."` / `region: "same-row"` selector, rather than hand-fit
a wider regex. Verified via a live `docintel.cli process --json` run against
all 12 real second samples plus the original gold document - the region
resolves to just the account number cell, never bleeding into the next row
(`Service Dates ...` or `For proper credit please return top portion.`), so
the sanctioned general mechanism is clean here and no fallback regex is
needed.

This test drives the REAL selector out of the shipped persona through the
REAL executor, against a minimal same-row layout, and checks several real
shapes (space-separated, no internal space, and the original gold value) in
the same test - so a "fix" that just widened the trailing literal (e.g.
`(1 -[0-9]{5} ?[0-9])` copied in without actually trying the sanctioned
mechanism first) would still pass this by accident, but a fix that kept the
old fully-hardcoded regex would not.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs
from northstar import PACK as _NORTHSTAR_PACK

WIDTH = 612.0
HEIGHT = 792.0


def _upak_vendor_account_number_selector() -> dict:
    """The actual `vendor_account_number` selector out of the shipped persona.

    Read from the loaded pack rather than re-typed here - re-typing it would
    test a copy of the rule, not the rule itself, and could quietly drift from
    what ships.
    """
    for pack in load_packs() + [_NORTHSTAR_PACK]:
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "vendor_account_number":
                        return selector
    raise AssertionError("northstar|upak persona (or its vendor_account_number selector) not found")


def _account_row(prefix: str, digits: str, suffix: str) -> PageText:
    """A minimal `Account No. <value>` row, split into words the way the real
    text layer renders it - a leading `1`, a dashed digit block, and a
    trailing digit as separate word tokens on the anchor's row."""
    words = [
        Word(text="Account", x0=10.0, y0=20.0, x1=55.0, y1=30.0),
        Word(text="No.", x0=58.0, y0=20.0, x1=78.0, y1=30.0),
        Word(text=prefix, x0=90.0, y0=20.0, x1=95.0, y1=30.0),
        Word(text=digits, x0=98.0, y0=20.0, x1=98.0 + 8.0 * len(digits), y1=30.0),
    ]
    x_after = 98.0 + 8.0 * len(digits) + 3.0
    if suffix:
        words.append(Word(text=suffix, x0=x_after, y0=20.0, x1=x_after + 8.0, y1=30.0))
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(
            page_number=1,
            char_count=sum(len(w.text) for w in page.words),
            image_count=0,
            annot_count=0,
            role="primary",
        ),
    )
    return JobContext(
        document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
        doc_type="standard_invoice",
    )


def _extract_vendor_account_number_raw(prefix: str, digits: str, suffix: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_vendor_account_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_account_row(prefix, digits, suffix)))
    value = ctx.extracted.get("vendor_account_number")
    if value is None:
        return None
    # `account_number` is a named pattern - it produces a structured
    # `AccountNumber(raw=..., normalized=...)`, not a plain string. The
    # PRINTED form (`.raw`) is what `core.contract._serialize` crosses to the
    # record, so that is what this test compares against (F6: raw and
    # normalized are two different facts).
    return value.raw  # type: ignore[no-any-return]


def test_matches_a_split_rendering_with_no_trailing_one() -> None:
    """The bug: real second samples like `1 -23464 8` do not end in `1`, and
    the old `(1 -[0-9]{5} 1)` pattern - a verbatim copy of the gold value's
    coincidental trailing digit - dropped the field on every one of them."""
    assert _extract_vendor_account_number_raw("1", "-23464", "8") == "1 -23464 8"


def test_matches_an_unsplit_rendering_with_no_internal_space() -> None:
    """`1 -213121` (Large UPAK sample) has no space before the last digit -
    a rendering artifact, not a different field boundary. The account-number
    pattern must accept both renderings."""
    assert _extract_vendor_account_number_raw("1", "-213121", "") == "1 -213121"


def test_still_matches_the_original_gold_account_number() -> None:
    """No regression on the one gold document (`1 -24136 1`) that already
    passed this field."""
    assert _extract_vendor_account_number_raw("1", "-24136", "1") == "1 -24136 1"


def test_does_not_bleed_into_the_next_row() -> None:
    """`Service Dates ...` and `For proper credit please return top portion.`
    sit on the rows below `Account No.` on the real invoice - `same-row`
    must not pull either of those into the account number."""
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_vendor_account_number_selector()],
            "layout_fingerprint": {},
        }
    )
    words = [
        Word(text="Account", x0=10.0, y0=20.0, x1=55.0, y1=30.0),
        Word(text="No.", x0=58.0, y0=20.0, x1=78.0, y1=30.0),
        Word(text="1", x0=90.0, y0=20.0, x1=95.0, y1=30.0),
        Word(text="-23464", x0=98.0, y0=20.0, x1=140.0, y1=30.0),
        Word(text="8", x0=143.0, y0=20.0, x1=150.0, y1=30.0),
        # Next row down: must not be swept into `same-row`.
        Word(text="For", x0=10.0, y0=40.0, x1=30.0, y1=50.0),
        Word(text="proper", x0=33.0, y0=40.0, x1=65.0, y1=50.0),
        Word(text="credit", x0=68.0, y0=40.0, x1=95.0, y1=50.0),
    ]
    page = PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT, source="native")
    ctx = Executor(persona).apply(_ctx(page))
    value = ctx.extracted.get("vendor_account_number")
    assert value is not None
    assert "For" not in value.raw
    assert "proper" not in value.raw
    assert value.raw == "1 -23464 8"
