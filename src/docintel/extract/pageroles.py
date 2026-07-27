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

The rule is decided **per page, from that page's own signals alone** — read
straight off all ten gold labels (`docs/corpus/gold/*.json` ->
`classification.page_roles`) and matching `docs/corpus-analysis.md` F10: a
page is `primary` if it carries both a document-identity anchor (an
"Invoice Number" / "Account Number" style label) and a totals-block label
(`PLEASE PAY`, `TOTAL AMOUNT DUE`, ...) — even when, as on U-PAK's
non-final pages, the totals cell itself is blank (F9), the label alone is
enough. There is deliberately no "page 1 is special" rule and no "collapse
to primary if every page matches" rule: each page is judged independently,
and it is exactly this that lets U-PAK's identical five-page template come
out *all* `primary` (every page independently carries both signals) without
being told it is a special case, while Lumen's and Windstream's and
Comcast's and Centracom's continuation pages — which carry the anchor
(routine running-header text) but never the totals label — come out
`supporting` on their own, without a page-index rule doing the work.

Both label checks only look at short visual lines (table headers and
label/value cells), never at prose: a long sentence that happens to use the
phrase "amount due" — e.g. Lumen page 2's FAQ, "...the recovery of the
amount due to the Federal Universal Service Fund..." — must not count as a
totals block, and a sentence like EDCO's "...have the last 6 digits of your
account number ready..." must not count as an identity anchor. Table header
rows can legitimately bundle several short cells onto one visual line
(U-PAK's aging header, "AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay"), so
the totals-line cutoff is generous enough for that; the anchor cutoff is
tighter, because every genuine anchor label in the corpus is short (at most
8 words) and a looser cutoff only ever adds false positives from prose.

**Every document must produce at least one `primary` page** — field capture
has nowhere to read from otherwise — but two documents in the corpus
(`_AP Invoice 6060DTSS` and `_AP Invoice 32930 Complete Beverage
Destruction`) have no page that independently carries both signals: DTSS's
one page has a totals label ("Balance Due") but no machine-findable anchor
label at all, and Complete Beverage's invoice page has an anchor-free totals
line ("Total Due" in a header row) while its three BOL pages have neither.
For exactly this case, `assign` falls back in two tiers, in order, and logs
which one fired (`logging.getLogger(__name__)`, not a print, so a caller can
decide whether that is worth surfacing):

1. The first page carrying a totals-block label on its own — that is where
   the payable lives, even without a confirmed identity anchor next to it.
2. If literally no page carries either signal, page 1, as an unconditional
   last resort — logged loudly, because at that point the choice really is
   arbitrary and a human should know it happened.

A page that is not `primary` is `supporting` unless it carries no words at
all (`len(page.words) == 0`) — a genuinely blank page is not "known" to be
part of the document's supporting content, it is just an absence of
information, and is reported `"unknown"` rather than a guess in either
direction. No document in the corpus has a blank page, so this branch is
covered only by a synthetic test (`tests/extract/test_pageroles.py`).

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

import logging
import re
from dataclasses import replace

from docintel.core.models import PageMeta, PageText

logger = logging.getLogger(__name__)

# A label naming the document's own identity ("Invoice Number", "Account
# No.", "Acct #", "Billing Account Number") as opposed to a reference number
# scoped to a single line item. Every genuine instance of this in the corpus
# is a short label/value cell, at most 8 words; anything longer is prose
# that happens to contain the phrase (see EDCO in the module docstring).
_ANCHOR_RE = re.compile(
    r"\b(INVOICE\s*(NUMBER|NO\.?|#)|ACCOUNT\s*(NUMBER|NO\.?|#)|ACCT\.?\s*#|"
    r"BILLING ACCOUNT NUMBER)\b"
)
_MAX_ANCHOR_LINE_WORDS = 8

# A label for the document's own payable total, as opposed to a line-item or
# per-section subtotal ("Subtotal Monthly Charges") that merely contains the
# word "total", or a recap/aging-table restatement of the same figure on a
# continuation page (Lumen page 3's "Total Current Charges" / "Amount Due"
# recap, Windstream page 3's "Windstream Current Charges" section header).
# Deliberately narrower than a first draft of this module, which matched
# bare "AMOUNT DUE" and "CURRENT CHARGES" and, as a result, misclassified
# both of those continuation pages as `primary`.
_TOTALS_RE = re.compile(
    r"\b(TOTAL AMOUNT DUE|PLEASE PAY|BALANCE DUE|TOTAL DUE|GRAND TOTAL|TOTAL AMT)\b"
)
_MAX_TOTALS_LINE_WORDS = 12


def _page_signals(page: PageText) -> tuple[bool, bool]:
    """(has_anchor, has_totals_label), read from short visual lines only."""
    has_anchor = False
    has_totals = False
    for line in page.lines():
        n_words = len(line)
        text: str | None = None
        if not has_anchor and n_words <= _MAX_ANCHOR_LINE_WORDS:
            text = " ".join(w.text for w in line).upper()
            if _ANCHOR_RE.search(text):
                has_anchor = True
        if not has_totals and n_words <= _MAX_TOTALS_LINE_WORDS:
            text = text or " ".join(w.text for w in line).upper()
            if _TOTALS_RE.search(text):
                has_totals = True
        if has_anchor and has_totals:
            break
    return has_anchor, has_totals


def assign(pages: tuple[PageText, ...], meta: tuple[PageMeta, ...]) -> tuple[PageMeta, ...]:
    """Classify every page as `primary`, `supporting`, or `unknown`.

    `primary`: the page's own signals qualify it (see module docstring for
    the anchor+totals rule and its two-tier fallback, which only engages
    when no page qualifies on its own).
    `unknown`: not primary, and carries no words at all.
    `supporting`: not primary, and carries at least one word.

    Never mutates `pages` or `meta` — always returns a new tuple built from
    new `PageMeta` instances (see the module docstring for why that is
    load-bearing).
    """
    if not pages:
        return meta
    if len(pages) != len(meta):
        raise ValueError(f"pages/meta length mismatch: {len(pages)} vs {len(meta)}")

    signals = [_page_signals(p) for p in pages]
    primary_idx = {
        i for i, (has_anchor, has_totals) in enumerate(signals) if has_anchor and has_totals
    }

    if not primary_idx:
        totals_only = [i for i, (_, has_totals) in enumerate(signals) if has_totals]
        if totals_only:
            primary_idx = {totals_only[0]}
            logger.warning(
                "pageroles: no page carried both an identity anchor and a totals "
                "label; falling back to page %d, the first page carrying a totals "
                "label on its own",
                totals_only[0] + 1,
            )
        else:
            primary_idx = {0}
            logger.warning(
                "pageroles: no page carried an identity anchor, a totals label, "
                "or both; falling back to page 1 as a last resort so the "
                "document still has a primary page"
            )

    roles = []
    for i, page in enumerate(pages):
        if i in primary_idx:
            roles.append("primary")
        elif not page.words:
            roles.append("unknown")
        else:
            roles.append("supporting")

    return tuple(replace(m, role=r) for m, r in zip(meta, roles))
