"""Which page is the invoice itself, and which pages are just along for the
ride? Finding F10: one PDF in the corpus (`_AP Invoice 32930 Complete
Beverage Destruction`) is an invoice glued to three pages of a scanned,
handwritten Bill of Lading. Field values must never be read off a supporting
page — a selector free to roam the whole document will eventually grab a BOL
scrawl instead of the printed total — but reference-pattern matching must
still run across every page, because the BOL pages are exactly where match
keys such as a seal or BOL number get corroborated. `assign` gives every
page a role so a later stage can restrict field capture to `primary` pages
while leaving reference matching untouched.

The rule, read straight off all ten gold labels
(`docs/corpus/gold/*.json` -> `classification.page_roles`), is the one
`docs/corpus-analysis.md` F10 describes: a page is `primary` if it carries
both a document-identity anchor (an "Invoice Number" / "Account Number"
style label) and a totals-block label (`PLEASE PAY`, `TOTAL AMOUNT DUE`,
...) — even when, as on U-PAK's non-final pages, the totals cell itself is
blank (F9). Nine of the ten documents in the corpus put both signals on page
1 only, so the default is "page 1 primary, the rest supporting". The tenth
(`CANADIAN WITHOUT NOTES U-PAK`) prints the identical template — the same
anchor, the same totals label — on every one of its five pages, with the
totals cell only resolving to a number on the last; when EVERY page
independently carries both signals, every page is `primary`.

Both label checks only look at short visual lines (table headers and
label/value cells), never at prose: a long sentence that happens to use the
phrase "amount due" — e.g. Lumen page 2's FAQ, "...the recovery of the
amount due to the Federal Universal Service Fund..." — must not count as a
totals block. Table header rows can legitimately bundle several short cells
onto one visual line (U-PAK's aging header, "AGE CURRENT 30 DAYS 60 DAYS 90
DAYS Please Pay"), so the line-length cutoff is generous enough for that but
not for a multi-clause sentence.

`meta` is memoized upstream (`normalize.load_document`'s in-process cache
returns the same tuple object to every caller), and `PageMeta` is frozen, so
an in-place mutation would raise immediately — but a successful
copy-and-replace of individual fields, done carelessly, could still hand
back a tuple built from the *cached* objects and leak new roles into the
memo's stored return value, corrupting every other caller's view of the
same document. `assign` therefore always builds and returns a brand new
tuple of brand new `PageMeta` instances; it must never write to, or return
unmodified members of, the tuple it was given.
"""

from __future__ import annotations

import re
from dataclasses import replace

from docintel.core.models import PageMeta, PageText

# A label naming the document's own identity ("Invoice Number", "Account
# No.", "Acct #", "Billing Account Number") as opposed to a reference number
# scoped to a single line item.
_ANCHOR_RE = re.compile(
    r"\b(INVOICE\s*(NUMBER|NO\.?|#)|ACCOUNT\s*(NUMBER|NO\.?|#)|ACCT\.?\s*#|"
    r"BILLING ACCOUNT NUMBER)\b"
)

# A label for the document's own payable total, as opposed to a line-item or
# per-section subtotal ("Subtotal Monthly Charges") that merely contains the
# word "total".
_TOTALS_RE = re.compile(
    r"\b(TOTAL AMOUNT DUE|AMOUNT DUE|PLEASE PAY|BALANCE DUE|TOTAL DUE|"
    r"GRAND TOTAL|TOTAL AMT|CURRENT CHARGES)\b"
)

# Visual lines longer than this are prose, not a label/value cell or a
# table header row, and are never inspected for either signal.
_MAX_LABEL_LINE_WORDS = 12


def _page_signals(page: PageText) -> tuple[bool, bool]:
    """(has_anchor, has_totals_label), read from short visual lines only."""
    has_anchor = False
    has_totals = False
    for line in page.lines():
        if len(line) > _MAX_LABEL_LINE_WORDS:
            continue
        text = " ".join(w.text for w in line).upper()
        if not has_anchor and _ANCHOR_RE.search(text):
            has_anchor = True
        if not has_totals and _TOTALS_RE.search(text):
            has_totals = True
        if has_anchor and has_totals:
            break
    return has_anchor, has_totals


def assign(pages: tuple[PageText, ...], meta: tuple[PageMeta, ...]) -> tuple[PageMeta, ...]:
    """Classify every page as `primary` or `supporting`.

    Page 1 is always `primary` — every gold label in the corpus has at least
    one primary page, and it is always the first. Every other page is
    `primary` too, but only if EVERY page in the document independently
    carries both the anchor and the totals-block label (the U-PAK
    repeating-template case); otherwise every page after the first is
    `supporting`.

    Never mutates `pages` or `meta` — always returns a new tuple built from
    new `PageMeta` instances (see the module docstring for why that is
    load-bearing).
    """
    if not pages:
        return meta
    if len(pages) != len(meta):
        raise ValueError(f"pages/meta length mismatch: {len(pages)} vs {len(meta)}")

    signals = (_page_signals(p) for p in pages)
    every_page_primary = all(has_anchor and has_totals for has_anchor, has_totals in signals)

    return tuple(
        replace(m, role="primary" if (i == 0 or every_page_primary) else "supporting")
        for i, m in enumerate(meta)
    )
