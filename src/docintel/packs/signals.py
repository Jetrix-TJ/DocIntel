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

from docintel.core import pagination
from docintel.core.models import JobContext, PageText, Word
from docintel.core.senders import normalize_name

# Where a pattern may be looked for. Named rather than boolean flags because a
# declarative rung has to say which one it means, and "primary" vs "all" is a
# real semantic difference (grammar section 7): a supporting Bill of Lading may
# carry facts that are not statements about the invoice it is stapled to.
SCOPES: frozenset[str] = frozenset({"primary", "all", "page1"})


def line_text(line: list[Word]) -> str:
    """A visual line's words joined with single spaces."""
    return " ".join(w.text for w in line)


def scope_text(ctx: JobContext, scope: str) -> str:
    """The text a signal with this scope may read."""
    if scope == "primary":
        return "\n".join(p.text for p in primary_pages(ctx))
    if scope == "page1":
        return next((p.text for p in ctx.pages if p.page_number == 1), "")
    if scope == "all":
        return "\n".join(p.text for p in ctx.pages)
    raise ValueError(f"unknown scope {scope!r}; expected one of {sorted(SCOPES)}")


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


# --------------------------------------------------------------------------
# The remaining primitives, lifted out of the two packs' ladders.
#
# Each already existed as working pack code with its evidence attached; the
# evidence moved with it. A rung in a declarative ladder names one of these
# rather than restating its mechanics, which is what stops "declarative" from
# becoming a second, unreviewed way to write the same regex twice.
# --------------------------------------------------------------------------


def pattern_in_scope(ctx: JobContext, pattern: re.Pattern[str], *, scope: str) -> bool:
    """Whether `pattern` appears anywhere in `scope`'s text.

    The blunt one, and the right choice only when a match ANYWHERE is genuinely
    the finding - a scanline, a sub-account marker, a promotional insert's own
    wording. When the question is really "is this a title" or "is this a label
    with a value", use `title_near_top` or `label_with_corroborating_value`
    instead: both exist because a bare search over joined text is what produced
    the credit-memo and $0.00-tax false positives.
    """
    return bool(pattern.search(scope_text(ctx, scope)))


def text_near_top(ctx: JobContext, pattern: re.Pattern[str], *, max_line_index: int) -> bool:
    """Whether `pattern` appears in the first few lines of page 1.

    `title_near_top` without the length constraint, for the case where the thing
    being matched is not a title: Northstar's own letterhead is a company name
    and address block whose lines are legitimately long. Every corpus document
    names Northstar somewhere - it is the bill-to on all six - so a whole-page
    search would call every one of them own paperwork. Position alone is what
    separates a letterhead from a bill-to block.
    """
    if not ctx.pages:
        return False
    return any(
        pattern.search(line_text(line))
        for line in ctx.pages[0].lines()[:max_line_index]
    )


def all_matches_negative(ctx: JobContext, pattern: re.Pattern[str], *, scope: str) -> bool:
    """Whether `pattern` matches at least once and EVERY match is negative.

    `pattern` must expose the sign as its first group. This is the
    "negative-priced commodity column" that separates a contra invoice from an
    ordinary invoice carrying a rebate line: U-PAK prints `-40.500` and Complete
    Beverage `-0.65`, both negative unit prices, and neither document is a
    contra. What makes Federal Recycling's `-40.00/ST` different is that every
    per-unit RATE on the page is negative.

    Requires at least one match on purpose: "no rates at all" is not "all rates
    negative", and a vacuous truth here would classify every invoice without a
    rate column as a contra.
    """
    matches = pattern.findall(scope_text(ctx, scope))
    if not matches:
        return False
    return all((m[0] if isinstance(m, tuple) else m) == "-" for m in matches)


def role_shape(
    ctx: JobContext,
    *,
    primary_exactly: int | None = None,
    supporting_at_least: int | None = None,
) -> bool:
    """Whether the page roles Stage 2 assigned match this shape.

    One primary page plus at least one supporting page is an invoice with
    something stapled behind it. U-PAK's five-page repeating template comes out
    all-primary and does not match, which is the point.
    """
    primary = sum(1 for m in ctx.page_meta if m.role == "primary")
    supporting = sum(1 for m in ctx.page_meta if m.role != "primary")
    if primary_exactly is not None and primary != primary_exactly:
        return False
    if supporting_at_least is not None and supporting < supporting_at_least:
        return False
    return True


def shared_pagination_footer(ctx: JobContext) -> bool:
    """Whether every page carries a matching `N OF M` footer with M == page count.

    A real attachment - a Bill of Lading stapled behind an invoice - has no
    reason to share the invoice's own pagination sequence. A genuine multi-page
    invoice whose totals overflowed onto a later page does. Reading the printed
    footer is what tells apart two documents with the identical role shape.
    """
    return pagination.shared_footer_pages(ctx.pages) is not None


def money_table_present(ctx: JobContext, *, min_money_tokens: int = 3) -> bool:
    """A crude but honest table test: a line carrying several money tokens.

    Used as a NEGATIVE condition - a document titled "statement of account"
    that also prints a charges table is a bill, whatever its header says.
    """
    money = re.compile(r"[\d,]+\.\d{2}")
    for page in ctx.pages:
        for line in page.lines():
            if sum(1 for w in line if money.fullmatch(w.text)) >= min_money_tokens:
                return True
    return False


def text_source_is(ctx: JobContext, *, value: str) -> bool:
    """Whether the words came from the PDF text layer or from OCR.

    Not a fact about the invoice's content, which is why it is a tag and never a
    doc type: it says how much to trust every other signal on the page.
    """
    return ctx.text_source == value


_ODD_CHARS = re.compile(r"[^\w\s.,/$#&()'-]")


def _noise_ratio(text_tokens: list[str]) -> float:
    """Share of tokens that do not look like printed words.

    Three cheap signals, because OCR of handwriting fails in three ways: it
    produces fragments (`eo`, `eS`), it drops vowels (`Traotor`, `Looeition`),
    and it invents punctuation. None is reliable alone; the ratio is.
    """
    if not text_tokens:
        return 0.0

    def odd(token: str) -> bool:
        if len(token) <= 2:
            return True
        if token.isalpha() and not re.search(r"[aeiouAEIOU]", token):
            return True
        return bool(_ODD_CHARS.search(token))

    return sum(odd(t) for t in text_tokens) / len(text_tokens)


def noise_ratio_above(
    ctx: JobContext, *, threshold: float, role: str = "supporting", ocr_only: bool = True
) -> bool:
    """Whether any page in `role` reads as handwriting rather than print.

    Measured on the corpus: Complete Beverage's handwritten Bill of Lading pages
    score 0.51 and 0.46, its printed invoice and certificate pages 0.22 and 0.28,
    and Federal Recycling's printed page 0.17. A threshold of 0.40 sits in the
    gap with room on both sides.

    Restricted to supporting pages by default, which removes the whole
    false-positive risk: Federal Recycling carries a handwritten margin note that
    OCR transcribes, but it is a single-page document with no supporting page,
    and its gold label is correctly not tagged.
    """
    if ocr_only and ctx.text_source != "ocr":
        return False
    def wanted_role(assigned: str) -> bool:
        # "supporting" means "not primary", which also catches `unknown` - a
        # blank page carries no words, so it cannot raise the ratio anyway.
        return assigned != "primary" if role == "supporting" else assigned == role

    wanted = {m.page_number for m in ctx.page_meta if wanted_role(m.role)}
    return any(
        _noise_ratio([w.text for w in page.words]) >= threshold
        for page in ctx.pages
        if page.page_number in wanted
    )


def distinct_printed_aliases_at_least(ctx: JobContext, *, count: int, scope: str = "primary") -> bool:
    """Whether the pack's alias table matches at least `count` printed names.

    Drives `multi_brand_sender`, which is what makes the alias collapse visible
    on the record rather than a silent normalization nobody can audit: Lumen
    prints three names for one carrier.

    Reads `ctx.pack.vendor_aliases`, so the primitive is generic and the TABLE
    stays the pack's own data.

    **Known defect, deliberately preserved here.** This counts matched alias
    PHRASES, so a short alias that is a substring of a longer matched one counts
    twice - `comcast` inside `comcast business` tags Comcast `multi_brand_sender`
    against its gold label. The fix is a parked task
    (`2026-08-07-classification-correctness-v2.md`, Task 3) and is deliberately
    NOT applied here: this module's migration is a representation change proven
    by a byte-identical `replay-gold`, and folding a behaviour fix into it would
    destroy that proof. Fixing it afterwards is now a one-line change in one
    place instead of a pack-local edit.
    """
    pack = ctx.pack
    aliases: dict[str, str] = getattr(pack, "vendor_aliases", {}) or {}
    haystack = normalize_name(scope_text(ctx, scope))
    return len({phrase for phrase in aliases if phrase in haystack}) >= count
