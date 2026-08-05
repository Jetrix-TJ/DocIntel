"""Finding 2 regression (and Finding A on top of it): Edco's
`vendor_account_number` selector must not be keyed to one prefix, and the
prefix must not be a hardcoded calendar year either.

The shipped pattern used to be `(25-3A [0-9]{6})`, copied straight off the
single gold sample (`25-3A 077087`). Reading the actual printed text of the
four newer real Edco invoices named in the task brief (via `fitz`/PyMuPDF
against the PDFs directly, not the filenames - the account number is not in
the filename at all) turned up:

    13307OCT25   -> 25-1A 013307
    15570AUG25   -> 25-1R 015570
    15570SEPT25  -> 25-1R 015570
    159507OCT25  -> 25-1A 159507

A wider spot-check across every sample in `all-docs/second-samples/edco/`
(28 files) turned up `25-1A`, `25-3A`, `25-5A`, `25-1R`, `25-3R`, `25-5R` -
i.e. every sample shares a literal `25-` prefix, then one digit, then one
letter, then a space, then six digits.

Finding A (this pass): `25-` is not a vendor constant, it is the calendar
year 2025 - confirmed invariant across all 28 samples, which span
March-October 2025. It is now 2026, so a literal `25-` is a live break, not a
hypothetical one. The digit-then-letter route/service code after it was
already a character class and is unchanged; only the year needed widening.

**Why the pattern also gained a `744-2700 ` prefix.** A bare `([0-9]{2}-
[0-9][A-Z] [0-9]{6})` has no literal alphanumeric text outside its character
classes, which trips V6 (`validator._is_bare_digit_pattern`): on `region:
any-page` a pattern with nothing to anchor it could match a phone number or a
zip+4 instead. Two region-based workarounds were tried and rejected on real
evidence first:

  * `near-anchor` (anchor `FOR BILLING INQUIRIES OR SERVICE,`) cuts off
    300pt right of the anchor's first word - short of where the account
    number actually prints on the same page (`CALL (760) 744-2700 25-3A
    077087 ...`, well past that cutoff). Verified via `docintel.cli process
    --json`: every one of the 28 second samples came back `None`.
  * `remittance-block` is a fixed bottom-of-page band (`REMITTANCE_FRACTION`)
    that does not reach as high up the page as this line sits. Same result:
    every sample came back `None`.

Both were real regressions, not near-misses - confirmed empirically, not
reasoned about in the abstract. `region: any-page` stays, and instead the
selector's OWN invariant boilerplate - Edco's support phone number, `744-
2700`, confirmed printed immediately before the account number on the same
line across all 29 real documents (28 second samples + the original) via
`load_document` - supplies the literal context V6 wants, without
reintroducing a hardcoded YEAR the way keeping `25-` would have. The phone
number is a company constant, unconnected to the account's own year prefix,
so anchoring the pattern on it does not reintroduce Finding A's bug.

There is no gold label for the new samples (see the task brief), so this test
is the synthetic fixture that stands in for corpus coverage: it drives the
REAL selector out of the shipped persona through the REAL executor, against a
minimal page carrying the real anchor phrase AND the real `744-2700` context
the pattern now requires, and checks several distinct prefixes in the same
test - so a "fix" that just added `25-1A` (or `25-1R`) as a second/third
alternative next to `25-3A` cannot pass this by accident the way it could
pass a corpus-only check.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0

ANCHOR_PHRASE = "FOR BILLING INQUIRIES OR SERVICE,"


def _edco_vendor_account_number_selector() -> dict:
    """The actual `vendor_account_number` selector out of the shipped persona.

    Read from the loaded pack rather than re-typed here - re-typing it would
    test a copy of the rule, not the rule itself, and could quietly drift from
    what ships.
    """
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|edco":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "vendor_account_number":
                        return selector
    raise AssertionError("northstar|edco persona (or its vendor_account_number selector) not found")


def _account_page(account_number: str) -> PageText:
    """A minimal page carrying the real anchor line and, on a SEPARATE line,
    the real `CALL (760) 744-2700 <account> ...` row the pattern now keys
    off of - the way every real invoice prints it (the anchor sits near the
    bottom of the real page, close to but not on the same row as the
    `744-2700` line; `any-page` does not care about their relative position,
    only that both pieces of text are present somewhere on the document)."""
    prefix, digits = account_number.split(" ")
    anchor_words = [
        Word(text=w, x0=10.0 + i * 60.0, y0=500.0, x1=65.0 + i * 60.0, y1=510.0)
        for i, w in enumerate(["FOR", "BILLING", "INQUIRIES", "OR", "SERVICE,"])
    ]
    call_row = [
        Word(text=w, x0=10.0 + i * 70.0, y0=20.0, x1=65.0 + i * 70.0, y1=30.0)
        for i, w in enumerate(["CALL", "(760)", "744-2700"])
    ]
    account_words = [
        Word(text=prefix, x0=220.0, y0=20.0, x1=220.0 + 8.0 * len(prefix), y1=30.0),
        Word(text=digits, x0=270.0, y0=20.0, x1=270.0 + 8.0 * len(digits), y1=30.0),
    ]
    return PageText(
        page_number=1, words=tuple(call_row + account_words + anchor_words), width=WIDTH, height=HEIGHT,
        source="native",
    )


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


def _extract_vendor_account_number(account_number: str) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_edco_vendor_account_number_selector()],
            "layout_fingerprint": {},
        }
    )
    ctx = Executor(persona).apply(_ctx(_account_page(account_number)))
    return ctx.extracted.get("vendor_account_number")


def test_matches_a_25_1a_prefixed_account_number() -> None:
    """The bug: real invoices `13307OCT25`, `159507OCT25` (and others) print
    this prefix and the old `25-3A`-only pattern returned `missing_required`
    on every one of them."""
    assert _extract_vendor_account_number("25-1A 013307") == "25-1A 013307"


def test_matches_a_25_1r_prefixed_account_number() -> None:
    """Real invoices `15570AUG25` and `15570SEPT25` print this prefix - a
    different letter as well as a different digit, so a fix that only widened
    the digit (e.g. `25-[0-9]A`) would still miss these two."""
    assert _extract_vendor_account_number("25-1R 015570") == "25-1R 015570"


def test_still_matches_the_original_25_3a_prefixed_account_number() -> None:
    """No regression on the one gold document (`25-3A 077087`) that already
    passed this field."""
    assert _extract_vendor_account_number("25-3A 077087") == "25-3A 077087"


def test_matches_other_prefixes_observed_in_the_wider_sample_pool() -> None:
    """`25-5A` and `25-3R` were also observed across the 28-file sample pool
    (not just the 4 named in the task brief) - confirming the fix generalizes
    rather than fitting only the samples it was written against."""
    assert _extract_vendor_account_number("25-5A 709223") == "25-5A 709223"
    assert _extract_vendor_account_number("25-3R 819387") == "25-3R 819387"


def test_does_not_match_a_shape_with_two_letters_or_two_digits() -> None:
    """A prefix-class pattern widened past one digit and one letter (e.g.
    dropped digit/letter counts, or swapped the class order) would be the
    first place a too-loose fix showed up."""
    assert _extract_vendor_account_number("25-AB 013307") is None
    assert _extract_vendor_account_number("25-11 013307") is None


def test_matches_a_26_year_prefixed_account_number() -> None:
    """Finding A: `25-` was hardcoded as if it were a vendor constant, but it
    is the calendar year (2025). It is now 2026 - a real invoice printed this
    year would carry a `26-` prefix, and the old literal-`25-` pattern would
    drop the field entirely on every one of them."""
    assert _extract_vendor_account_number("26-1A 013307") == "26-1A 013307"


def test_still_rejects_a_year_with_a_letter_or_a_missing_dash() -> None:
    """The year became a digit class (`[0-9]{2}`), not an open-ended
    wildcard - a fix that over-widened it (e.g. `.{2}` or dropped the dash)
    would be the first place that showed up."""
    assert _extract_vendor_account_number("2A-1A 013307") is None
    assert _extract_vendor_account_number("251A 013307") is None
