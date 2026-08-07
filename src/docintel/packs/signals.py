"""The closed registry of classification signal primitives.

**This is the classification analogue of the grammar's `BASE_ADJUST_OPS`.**
Extraction was made generic by expressing a vendor's rules as data validated
against a closed op enum; classification stayed hand-written Python per pack,
and that asymmetry is why onboarding a company costs a module and onboarding a
document type costs an `if` branch. A declarative ladder needs a fixed
vocabulary to compile against. This is that vocabulary.

**Closed on purpose.** A pack author composes what is here; adding a primitive
is a code change with a test and a named real document behind it. That is what
keeps "declarative" from becoming arbitrary regex soup authored by whoever
onboarded the last client.

Every primitive below was invented in `northstar/ladder.py` to fix a specific
real-document defect, and every one was then NOT applied to the identical check
in `digitaldirection/ladder.py` — which is how Windstream ships a `past_due`
false positive that Northstar's ladder would reject. The POLICY (which pattern,
which cutoff, which rung order) stays with each pack, because the two businesses
genuinely classify differently. The MECHANICS live here.

Nothing in this module knows what a tag or a `doc_type` is. It answers questions
about ink on a page.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from docintel.core.models import JobContext, PageText, Word


def line_text(line: list[Word]) -> str:
    """A visual line's words joined with single spaces."""
    return " ".join(w.text for w in line)


def primary_pages(ctx: JobContext) -> list[PageText]:
    """The pages a classification signal may read from.

    A supporting page — a Bill of Lading, a certificate, a carrier's FAQ — may
    name a different company, carry a different tax regime or show a different
    total, and none of those are statements about the invoice it is attached to
    (grammar section 7).

    Falls back to every page when no roles are assigned: a classifier that
    classifies nothing is worse than one that occasionally reads a supporting
    page, and Stage 2 always assigns roles before Stage 3 in the real pipeline.

    `registry.primary_text` is built from this function rather than
    reimplementing the same rule. Two copies agreeing today is not a contract.
    """
    primary = {m.page_number for m in ctx.page_meta if m.role == "primary"}
    if not primary:
        return list(ctx.pages)
    return [p for p in ctx.pages if p.page_number in primary]


def short_label_line(
    ctx: JobContext,
    pattern: re.Pattern[str],
    max_words: int,
    *,
    primary_only: bool = True,
) -> bool:
    """Whether `pattern` appears on a SHORT line rather than buried in prose.

    Federal Recycling's terms read "PAST DUE AMOUNTS SUBJECT TO INTEREST FEES IN
    THE AMOUNT OF 18.99% ANNUALLY…" — boilerplate on every invoice that vendor
    sends, correctly untagged in gold. EDCO's is a standalone `PAST DUE` banner.
    Line length separates them, the same discriminator `extract.pageroles` uses
    for the same reason.

    **Length alone is NOT sufficient and callers must not treat it as such.**
    OCR wraps prose onto short lines: page 3 of `Windstream_041069076` carries
    the fragment "any past due Internet balance.", five words, which no
    word-count cutoff can reject. `primary_only` defaults to True because that
    fragment is on a supporting page. A caller that genuinely needs every page
    must say so explicitly and record why — Northstar's `past_due` banner check
    does, because Federal Recycling's terms live on their own page.
    """
    pages = primary_pages(ctx) if primary_only else list(ctx.pages)
    for page in pages:
        for line in page.lines():
            if len(line) > max_words:
                continue
            if pattern.search(line_text(line)):
                return True
    return False


def title_near_top(
    ctx: JobContext,
    pattern: re.Pattern[str],
    *,
    max_words: int,
    max_line_index: int,
) -> bool:
    """Whether a genuine document TITLE matching `pattern` sits near the top of
    page 1.

    Short-line length cannot separate a title from a footnote on its own: real
    OCR of Complete Beverage's "For remaining credited items refer to Credit
    memo 32684." wraps across two SHORT lines, and the second passes a
    word-count check exactly like a real title would. Position is the real
    discriminator — the genuine title on `_AP Invoice 32473` sits at page-1 line
    index 5 of 20; the false-positive footnote on `_AP Invoice 32593` sits at
    index 25-26 of 30.

    **Both constraints are applied deliberately.** Dropping the length check
    would leave a short prose aside near the top of the page able to fool this;
    the corpus has not produced one, but length guards against it for free.

    Literal page 1 only, which is narrower than `primary_pages`: a supporting
    attachment page can never contribute a title match, whatever its role.
    """
    if not ctx.pages:
        return False
    for line in ctx.pages[0].lines()[:max_line_index]:
        if len(line) > max_words:
            continue
        if pattern.search(line_text(line)):
            return True
    return False


def label_with_corroborating_value(
    ctx: JobContext,
    label: re.Pattern[str],
    *,
    same_line: Callable[[str], bool] | None = None,
    next_line: Callable[[str], bool] | None = None,
    primary_only: bool = True,
) -> bool:
    """Whether a `label` match is corroborated by a real value near it.

    **A printed column LABEL is not a fact.** `Total Tax` appears on every
    Veritiv invoice whether or not tax was charged, and an aging header appears
    on every U-PAK invoice whether or not anything is aged — so matching the
    label alone makes the check trivially true on exactly the documents it
    exists to catch.

    The corroboration predicates belong to the caller, because what counts as
    "the value" is layout-specific: Veritiv's tax amount is the second-to-last
    money token on the row, immediately before the trailing grand total, while
    an aging bucket is any token strictly between the first (CURRENT) and the
    last (Please Pay).

    `same_line` is tried first, then `next_line` against the following visual
    line: in every corpus and second-sample document the value row is either the
    same visual line (rare) or the next one.
    """
    pages = primary_pages(ctx) if primary_only else list(ctx.pages)
    for page in pages:
        lines = page.lines()
        for i, line in enumerate(lines):
            text = line_text(line)
            if not label.search(text):
                continue
            if same_line is not None and same_line(text):
                return True
            if next_line is not None and i + 1 < len(lines):
                if next_line(line_text(lines[i + 1])):
                    return True
    return False
