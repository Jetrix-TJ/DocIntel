"""U-Pak was one of the 5 personas that shipped with no `bill_to_name` selector
at all (STATUS-SUMMARY.md §4.1), so `bill_to_mismatch` could never fire
regardless of who a document was billed to. This file is the selector that
closed its share of that finding; all five - `comcast`, `windstream`, `edco`,
`upak`, `veritiv` - carry one as of this branch, so the count is now zero.

**The selector is `scope: "block"` plus an anchored party-name shape, and both
halves are load-bearing.** It shipped as `pattern: "text_block"` and the
whole-branch review, replaying all 12 real second samples, found it wrong on 3
of them. The two failures the fix has to survive are BOTH real, and they pull in
opposite directions:

1. **The block bleeds vertically.** `near-anchor` reaches 40pt below `Bill To`,
   and on `_AP Invoice 4421470` an `ATTN: SEAN LEES` line (top=161.18) sits
   between the label and the party (top=169.18); on `_AP Invoice 4489932` it is
   `JPITONIAK@NSRECYCLE.COM` (top=165.18) above the party at top=173.18.
   `text_block` joined them, producing `ATTN: SEAN LEES, NORTHSTAR RECYCLING`.
   That also silently cost those records their `bill_to_address`, because
   `ops.infer.resolve_bill_to_alias` derives it via `_block_under` keyed on the
   exact printed party string and no block sits under a two-line blob.

2. **A per-line pattern bleeds horizontally.** `Bill` is at x0=90, so
   `near-anchor` runs to x=390 - and U-Pak's SERVICE LOCATION column starts at
   x0=355.07, with its rows interleaved between the bill-to rows, often one row
   ABOVE the party. Measured across the same 12 samples, porting Windstream's
   shape idiom with the default `scope: "line"` returned the service location on
   6 of them (`ROYAL CANIN`, `BLUE ZONE`, `MARS CANADA`, `RED ZONE`, `ARL LAB`,
   `ASPIRE BAKERY`) - wrong-PARTY reads on correctly-addressed bills, worse than
   the defect being fixed.

`scope: "block"` answers (2): it is the path that applies `regions.column_cut`,
which was previously reachable only by `pattern: "text_block"`. The anchored
`^...$` shape answers (1): `re` matches it against the WHOLE string unless
`re.MULTILINE` is set and `patterns.compile_restricted` never sets it, so a
block carrying anything besides the name cannot match at all. A miss is not a
loss - it falls through to `resolve_bill_to_alias`'s roster rung, which restores
both the name and the address.

Measured outcome on the real corpus, all 12 second samples plus the gold PDF:
10 clean captures, 3 clean misses, **zero wrong values**, `bill_to_address`
present on all 12, and no `bill_to_mismatch` on any correctly-addressed
document. Every fixture below is built from those documents' own
`pdfplumber.extract_words` boxes.
"""

from __future__ import annotations

from docintel.core.models import JobContext, PageMeta, PageText, Word
from docintel.grammar.executor import Executor
from docintel.grammar.schema import parse_persona
from docintel.packs.registry import load_packs

WIDTH = 612.0
HEIGHT = 792.0

# Real page-1 rows, verbatim from the named PDFs. `(top, [(text, x0, x1), ...])`.
Row = tuple[float, list[tuple[str, float, float]]]

# Every U-Pak document prints this row: the `Bill To:` label and, 238pt to its
# right, the `Location:` label heading the service-location column. Both are
# inside `near-anchor`'s 300pt reach from `Bill` (x0=90 -> x1=390).
LABEL_ROW: Row = (
    135.68,
    [("Bill", 90.00, 102.42), ("To:", 104.64, 117.06), ("Location:", 355.07, 391.03)],
)

# `_AP Invoice 4444058 U-Pak 4476.34000.pdf` - the healthy shape. The service
# location's own first row (top=165.18) sits ABOVE the party's row (top=173.18),
# and its first words are inside x1=390.
HEALTHY_ROWS: list[Row] = [
    LABEL_ROW,
    (165.18, [("BLUE", 355.07, 375.95), ("ZONE", 378.17, 400.37),
              ("SH", 402.58, 413.69), ("ROYAL", 415.90, 443.00)]),
    (173.18, [("NORTHSTAR", 90.00, 139.74), ("RECYCLING", 141.95, 188.59),
              ("*BIN", 355.07, 371.50), ("CONNECTED", 373.72, 424.35)]),
    # Below `NEAR_ANCHOR_BELOW`'s 40pt floor (135.68 + 40 = 175.68), so outside
    # the region - kept so the fixture is the document rather than a slice of it.
    (181.18, [("94", 90.00, 98.90), ("MAPLE", 101.11, 128.21), ("ST", 130.42, 140.63)]),
]

# `_AP Invoice 4421470 U-Pak 1360.60000.pdf` - an ATTN: line above the party.
ATTN_ROWS: list[Row] = [
    LABEL_ROW,
    (161.18, [("ATTN:", 90.00, 113.08), ("SEAN", 115.30, 137.06),
              ("LEES", 139.27, 159.70)]),
    (169.18, [("NORTHSTAR", 90.00, 139.74), ("RECYCLING", 141.95, 188.59),
              ("MARS", 355.07, 378.17), ("CANADA", 380.38, 413.69)]),
]

# `_AP Invoice 4489932 U-Pak 9220.92000.pdf` - an email line above the party AND
# a service-location row that has no left-column content at all, so nothing
# precedes `ROYAL CANIN` on its row to push it out of a per-line candidate.
EMAIL_ROWS: list[Row] = [
    LABEL_ROW,
    (165.18, [("JPITONIAK@NSRECYCLE.COM", 90.00, 209.14)]),
    (169.18, [("ROYAL", 355.07, 382.17), ("CANIN", 384.38, 409.25),
              ("CANADA-PIVOT", 411.47, 471.41)]),
    (173.18, [("NORTHSTAR", 90.00, 139.74), ("RECYCLING", 141.95, 188.59),
              ("CO", 190.81, 202.80), ("INC", 205.02, 218.78)]),
]


def _upak_bill_to_name_selector() -> dict:
    """The selector as shipped, read out of the loaded pack.

    Re-typing it here would test a copy of the rule rather than the rule.
    """
    for pack in load_packs():
        if pack.name != "northstar":
            continue
        for persona in pack.personas():
            if persona.get("sender_fingerprint") == "northstar|upak":
                for selector in persona["field_selectors"]:
                    if selector.get("field") == "bill_to_name":
                        return selector
    raise AssertionError("northstar|upak persona (or its bill_to_name selector) not found")


def _page(rows: list[Row]) -> PageText:
    words = [
        Word(text=text, x0=x0, y0=top, x1=x1, y1=top + 8.0)
        for top, cells in rows
        for text, x0, x1 in cells
    ]
    return PageText(page_number=1, words=tuple(words), width=WIDTH, height=HEIGHT,
                    source="native")


def _renamed(rows: list[Row], party: str) -> list[Row]:
    """The same geometry with a different party printed on the party's row.

    The party's row is the one that starts at the bill-to column (x0=90) and
    carries more than one word - the same structural fact the document itself
    has, so a fixture cannot drift from it silently. The service-location cells
    on that row are kept exactly where they were.
    """
    out: list[Row] = []
    for top, cells in rows:
        if top != LABEL_ROW[0] and cells[0][1] == 90.00 and len(cells) > 1:
            x = 90.00
            replaced: list[tuple[str, float, float]] = []
            for token in party.split():
                width = 5.53 * len(token)
                replaced.append((token, x, x + width))
                x += width + 2.21
            out.append((top, [*replaced, *[c for c in cells if c[1] > 340.0]]))
        else:
            out.append((top, cells))
    return out


def _ctx(page: PageText) -> JobContext:
    meta = (
        PageMeta(page_number=1, char_count=sum(len(w.text) for w in page.words),
                 image_count=0, annot_count=0, role="primary"),
    )
    return JobContext(document_id="d1", source_path="x.pdf", pages=(page,), page_meta=meta,
                      doc_type="standard_invoice")


def _extract(rows: list[Row]) -> str | None:
    persona = parse_persona(
        {
            "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
            "rule_version": "v1", "status": "draft",
            "field_selectors": [_upak_bill_to_name_selector()],
            "layout_fingerprint": {},
        }
    )
    return Executor(persona).apply(_ctx(_page(rows))).extracted.get("bill_to_name")


# --------------------------------------------------------------------------
# It reads the party where the party is unambiguous
# --------------------------------------------------------------------------


def test_reads_the_printed_bill_to_name() -> None:
    assert _extract(HEALTHY_ROWS) == "NORTHSTAR RECYCLING"


def test_reads_a_different_printed_bill_to_name() -> None:
    """The whole point of the selector: a name that is NOT on the roster must
    still be read, or `bill_to_mismatch` can never fire. Asserted on the healthy
    layout, so this is what a genuinely misdirected U-Pak invoice produces."""
    assert _extract(_renamed(HEALTHY_ROWS, "SOME OTHER COMPANY LLC")) == (
        "SOME OTHER COMPANY LLC"
    )


def test_reads_the_gold_documents_longer_rendering() -> None:
    """`CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf` prints `NORTHSTAR
    RECYCLING COMPANY` with the `LLC` wrapped onto its own line 8pt below, past
    `NEAR_ANCHOR_BELOW`'s 40pt floor. The shape's 30/45-character bounds have to
    be wide enough for what does fit."""
    assert _extract(_renamed(HEALTHY_ROWS, "NORTHSTAR RECYCLING COMPANY")) == (
        "NORTHSTAR RECYCLING COMPANY"
    )


# --------------------------------------------------------------------------
# Horizontal bleed: the service-location column (what `scope: "block"` fixes)
# --------------------------------------------------------------------------


def test_does_not_read_the_service_location_column_beside_the_party() -> None:
    """`Location:`'s column starts at x0=355.07, inside `near-anchor`'s x1=390.
    `regions.column_cut` finds the gutter and drops it - and that cut is reached
    only through `scope: "block"`. Reverting the selector to `scope: "line"`
    fails here."""
    value = _extract(HEALTHY_ROWS)
    assert value == "NORTHSTAR RECYCLING"
    assert "BLUE" not in value
    assert "*BIN" not in value


def test_does_not_read_a_service_location_row_that_sits_above_the_party() -> None:
    """The measured regression that ruled out a plain per-line shape pattern.

    On `_AP Invoice 4489932` the service location's row (top=169.18) carries NO
    left-column words, so `_cells` offers `ROYAL CANIN` as a candidate of its
    own, one row BEFORE the party's row - and it is a perfectly well-formed
    two-token party name, so no shape can reject it. Only the column cut can.

    Asserted as an inequality because this document is one where the selector
    deliberately misses: the point here is that it must not return the WRONG
    party instead. `test_an_email_line_above_the_party_makes_the_selector_miss`
    carries the positive half.
    """
    assert _extract(EMAIL_ROWS) != "ROYAL CANIN"


# --------------------------------------------------------------------------
# Vertical bleed: a block that is more than the name misses, it does not blob
# --------------------------------------------------------------------------


def test_an_attn_line_above_the_party_makes_the_selector_miss() -> None:
    """`_AP Invoice 4421470`. Before the fix this captured `ATTN: SEAN LEES,
    NORTHSTAR RECYCLING` at 0.99 confidence and routed `lane: high`, and the
    two-line blob also cost the record its `bill_to_address` -
    `resolve_bill_to_alias` derives that via `_block_under` keyed on the exact
    printed party string, and nothing sits under a blob.

    A miss is the correct answer here, not a consolation: the roster rung behind
    it returns `NORTHSTAR RECYCLING` and restores the address, which is what the
    real replay of this document now shows.
    """
    assert _extract(ATTN_ROWS) is None


def test_an_email_line_above_the_party_makes_the_selector_miss() -> None:
    """`_AP Invoice 4489932`, the same failure with a different line above the
    name - captured as `JPITONIAK@NSRECYCLE.COM, NORTHSTAR RECYCLING CO INC`
    before the fix. Two documents rather than one, because a fixture built for
    `ATTN:` alone would pass on a pattern that merely excluded a colon."""
    assert _extract(EMAIL_ROWS) is None


def test_the_shape_pattern_is_anchored_at_both_ends() -> None:
    """The property both misses above depend on, asserted directly so that
    loosening the pattern fails here with an explanation rather than only as two
    puzzling case failures. Unanchored, `re.search` would find the party name
    INSIDE the blob and return it - a value that looks right, from a document
    whose block the selector never actually understood."""
    pattern = _upak_bill_to_name_selector()["pattern"]
    assert pattern.startswith("^("), pattern
    assert pattern.endswith(")$"), pattern


def test_the_selector_declares_block_scope() -> None:
    """The other half of the same pair. `scope` defaults to `line`, and dropping
    the key would silently restore the horizontal bleed while leaving every
    vertical-bleed test above still passing."""
    assert _upak_bill_to_name_selector().get("scope") == "block"
