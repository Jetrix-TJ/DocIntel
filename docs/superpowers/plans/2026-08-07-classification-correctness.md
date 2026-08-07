# Classification Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Stage 3 classification layer's known defects measurable and then fix them, so that no verified-wrong tag or doc_type survives on the corpus and a fix in one pack's ladder cannot silently miss the identical bug in the other's.

**Architecture:** Three moves, in order. (1) Close the *measurement* gap first — the gold `tags` assertion is a superset check, so a false-positive tag is invisible to the scorecard and no later task could prove it was fixed. (2) Extract the four generic signal techniques (primary-page scoping, short-label line, title-near-top, label-with-corroborating-value) out of the two hand-copied ladders into one tested module, then migrate both ladders onto it — this is what makes a fix propagate mechanically instead of by memory. (3) Fix the individual defects on top of that shared vocabulary.

**Tech Stack:** Python 3.12+, pytest, mypy, ruff. No new dependencies. Pure-stdlib `re` and `decimal`.

## Global Constraints

- **Never read the filename.** Three of six Northstar corpus filenames state the answer outright (`s3_classify.py:11`). No task may introduce a filename-derived signal.
- **Every signal fix must be tested against the real PDF that motivated it,** not only a synthetic fixture. Audit precedent: Task 4 of the 2026-08-06 plan passed its synthetic single-line test and was a no-op on the real document, because real OCR wrapped the sentence across two short lines.
- **Printed fields only.** No task may reintroduce an inferred (non-printed) field. `foreign_currency` in Task 7 is computed from a printed Canadian postal code, NOT from a revived `currency` inference.
- **Money is `Decimal`, never `float`** (`dd/ladder.py:231`).
- **Tag additions go through `ctx.add_tag`**, which de-duplicates.
- **No gold label may be changed** by any task in this plan. If a task's evidence contradicts a gold label, it stops and reports rather than editing the label.
- Verification command for every task:
  `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py`
- Baseline at plan start (measured 2026-08-07): **1720 tests pass**, `replay-gold` **1/11 green**, gold tag deltas:

  | document | missing | extra |
  |---|---|---|
  | centracom | `no_invoice_number`, `past_due` | — |
  | comcast | `no_invoice_number` | `multi_brand_sender` ← BUG |
  | lumen | — | — |
  | windstream | `no_invoice_number` | `past_due` ← BUG |
  | complete-beverage | — | — |
  | edco-077087 | — | `page_role_fallback` (legitimate) |
  | edco-819387 | — | — |
  | federal-recycling | — | `page_role_fallback` (legitimate) |
  | upak | `foreign_currency` | — |
  | veritiv | — | — |

## Scope

**In this plan** — the classification/tagging layer and its measurement. Ten tasks, each independently testable.

**Deliberately deferred to separate plans**, because each is its own subsystem and would not produce working software on its own inside this one:

- **Evidence-bearing signals / calibrated confidence.** Signals return `bool` and confidence is four constants (`0.95/0.85/0.80/0.50`). Making signals return match strength + location touches `core/models.py`, `core/confidence.py` and `s7_gate.py`. Own plan.
- **Classification escalation.** Stage 3 has no escalation path: a document matching nothing gets `standard_invoice` at 0.50 and proceeds. The vision (`s5b`) and agent (`s5c`) seams exist but are extraction-only. Own plan.
- **Review-outcome feedback loop.** Rosters (`MANAGED_CLIENTS`, `BILL_TO_MARKERS`) grow only by pull request. Product/infra, not a code change.

---

### Task 1: Gold `forbidden_tags` — make false-positive tags visible

The scorecard compares `tags` with `kind="superset"` (`src/docintel/scorecard.py:618`), and the rationale in the comment above it is correct: the pipeline legitimately contributes diagnostic tags gold does not enumerate (`page_role_fallback` appears as a legitimate extra on two documents). So exact equality is the wrong fix. Instead, gold gains an **optional, affirmative** `classification.forbidden_tags` list: tags a human has verified must NOT appear on this document.

Without this task, Tasks 4, 5 and 6 cannot be proven to have fixed anything — their defects are invisible to the current scorecard.

**Files:**
- Modify: `src/docintel/scorecard.py` (the `tags` assertion block, around line 611-618)
- Modify: `docs/corpus/gold/digitaldirection-comcast-8495444620365242.json`
- Modify: `docs/corpus/gold/digitaldirection-windstream-041069076.json`
- Modify: `docs/corpus/validate_gold.py`
- Test: `tests/test_scorecard_forbidden_tags.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: gold schema key `classification.forbidden_tags: list[str]` (optional). Scorecard emits an assertion named `forbidden_tags` with `kind="disjoint"` when the key is present and non-empty. Later tasks add entries to this key.

- [ ] **Step 1: Write the failing test**

Create `tests/test_scorecard_forbidden_tags.py`:

```python
"""A tag the pipeline emits and gold has affirmatively forbidden must FAIL.

The `tags` assertion is a superset check, deliberately: the pipeline
legitimately contributes diagnostic tags gold does not enumerate
(`page_role_fallback` on two corpus documents). A superset check cannot see
an EXTRA tag, so two verified false positives - Comcast's
`multi_brand_sender` and Windstream's `past_due` - were invisible to the
scorecard. `forbidden_tags` is the affirmative half: a human has checked
this document and this tag is wrong on it.
"""

from __future__ import annotations

from docintel.scorecard import assertions_for_gold


def _gold(**classification):
    return {
        "gold_id": "t",
        "source_file": "x.pdf",
        "classification": classification,
    }


def test_a_forbidden_tag_that_is_absent_passes() -> None:
    gold = _gold(tags=["has_scanline"], forbidden_tags=["past_due"])
    record = {"tags": ["has_scanline"]}
    result = [a for a in assertions_for_gold(gold, record) if a.name == "forbidden_tags"]
    assert len(result) == 1
    assert result[0].passed is True


def test_a_forbidden_tag_that_is_present_fails() -> None:
    gold = _gold(tags=["has_scanline"], forbidden_tags=["past_due"])
    record = {"tags": ["has_scanline", "past_due"]}
    result = [a for a in assertions_for_gold(gold, record) if a.name == "forbidden_tags"]
    assert len(result) == 1
    assert result[0].passed is False


def test_no_assertion_when_the_key_is_absent() -> None:
    """Existing gold files must not gain a new assertion they cannot satisfy."""
    gold = _gold(tags=["has_scanline"])
    record = {"tags": ["has_scanline", "page_role_fallback"]}
    assert [a for a in assertions_for_gold(gold, record) if a.name == "forbidden_tags"] == []
```

Note: the implementer must first read `src/docintel/scorecard.py` to find the real
name of the function that builds assertions for one gold document, and the real
`Assertion` accessor names (`.name`, `.passed`). Adjust the import and attribute
names in this test to match what is actually there; do not rename existing
scorecard functions to fit this test.

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/test_scorecard_forbidden_tags.py -v`
Expected: FAIL — no `forbidden_tags` assertion is produced (all three tests fail, the third by accident of the first two's helper).

- [ ] **Step 3: Implement the assertion in the scorecard**

In `src/docintel/scorecard.py`, immediately after the existing `tags` superset assertion block:

```python
    # The affirmative half of the tags check. `tags` is a SUPERSET assertion
    # (see above) so it structurally cannot see a tag the pipeline emitted and
    # gold did not list - which is how Comcast's `multi_brand_sender` and
    # Windstream's `past_due` false positives survived. `forbidden_tags` is
    # opt-in per document and means "a human checked this document and this
    # tag is wrong on it", NOT "gold's list is exhaustive": the pipeline still
    # legitimately contributes diagnostics like `page_role_fallback`.
    forbidden = cls.get("forbidden_tags", [])
    if forbidden:
        add(
            "forbidden_tags",
            sorted(forbidden),
            lambda r: sorted(set(r.get("tags", [])) & set(forbidden)),
            kind="disjoint",
        )
```

Then add `"disjoint"` handling wherever the scorecard evaluates `kind`. A
`disjoint` assertion passes when the actual value (the intersection computed
above) is empty. Follow the existing `kind` dispatch exactly; do not introduce a
second dispatch mechanism.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python3 -m pytest tests/test_scorecard_forbidden_tags.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Add the two verified forbidden tags to gold**

In `docs/corpus/gold/digitaldirection-comcast-8495444620365242.json`, inside
`classification`:

```json
  "forbidden_tags": ["multi_brand_sender"],
  "forbidden_tags_note": "Verified 2026-08-07: the page prints ONE brand. count_printed_names returns 2 only because the alias 'comcast' is a substring of the alias 'comcast business' and both are counted. Compare Lumen, which prints three genuinely distinct names.",
```

In `docs/corpus/gold/digitaldirection-windstream-041069076.json`, inside
`classification`:

```json
  "forbidden_tags": ["past_due"],
  "forbidden_tags_note": "Verified 2026-08-07: the document's only 'past due' text is the prose fragment 'any past due Internet balance.' on page 3, a SUPPORTING page. No aging table, no past-due banner, and gold's prior_balance_cleared says last month's balance was paid in full.",
```

- [ ] **Step 6: Teach `validate_gold.py` about the new key**

Read `docs/corpus/validate_gold.py` first. Add a check that every string in
`classification.forbidden_tags` is absent from `classification.tags` on the same
document — a gold file that both requires and forbids a tag is self-contradictory
and must fail loudly rather than produce an unsatisfiable pair.

- [ ] **Step 7: Verify the two false positives are now VISIBLE as failures**

Run: `python3 -m docintel.cli replay-gold`
Expected: comcast and windstream each lose one more assertion than the 2026-08-07
baseline (28/32 and 26/30 rather than 28/31 and 26/29). **This is the task
succeeding, not regressing** — the defects were always there and are now counted.
Record the exact new numbers in the commit message.

- [ ] **Step 8: Full verification**

Run: `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py`
Expected: all pass; test count 1720 → 1723.

- [ ] **Step 9: Commit**

```bash
git add src/docintel/scorecard.py tests/test_scorecard_forbidden_tags.py \
        docs/corpus/gold/digitaldirection-comcast-8495444620365242.json \
        docs/corpus/gold/digitaldirection-windstream-041069076.json \
        docs/corpus/validate_gold.py
git commit -m "feat(scorecard): forbidden_tags makes false-positive tags visible

The tags assertion is a superset check, so an extra tag the pipeline emitted
could never fail. Two verified false positives were invisible to it. Adds an
opt-in per-document forbidden_tags list and wires the two verified cases.
Comcast and Windstream each drop one assertion: the defect was always there."
```

---

### Task 2: `packs/signals.py` — the shared signal vocabulary

Both ladders define their own `_short_line_has` with different word limits (Northstar 6, Digital Direction 8) and different page scopes (Northstar's `has_tax` is primary-scoped, Digital Direction's is not). Three defect classes were fixed in `northstar/ladder.py` on 2026-08-06 and none reached `digitaldirection/ladder.py`. This task creates the one module both will call. **No behavior changes in this task** — it is pure extraction plus tests.

**Files:**
- Create: `src/docintel/packs/signals.py`
- Test: `tests/packs/test_signals.py` (create)

**Interfaces:**
- Consumes: `docintel.core.models.JobContext`, `PageText`.
- Produces, for Tasks 3, 4, 5, 6, 7:
  - `primary_pages(ctx: JobContext) -> list[PageText]`
  - `short_label_line(ctx: JobContext, pattern: re.Pattern[str], max_words: int, *, primary_only: bool = True) -> bool`
  - `title_near_top(ctx: JobContext, pattern: re.Pattern[str], *, max_words: int, max_line_index: int) -> bool`
  - `label_with_corroborating_value(ctx: JobContext, label: re.Pattern[str], *, same_line: Callable[[str], bool] | None = None, next_line: Callable[[str], bool] | None = None, primary_only: bool = True) -> bool`
  - `line_text(line) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/packs/test_signals.py`:

```python
"""The four generic classification techniques, tested once.

Each of these was invented in `northstar/ladder.py` to fix a real defect, and
each was then NOT applied to the identical check in
`digitaldirection/ladder.py`. Owning them here is what makes the next fix
propagate to both packs mechanically instead of by someone remembering.
"""

from __future__ import annotations

import re

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs import signals

WORD_W = 40.0


def _page(text: str, number: int = 1) -> PageText:
    """`|`-separated rows become visual lines, matching the convention in
    tests/packs/test_digitaldirection_ladder.py."""
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + WORD_W * i, y0=y, x1=45.0 + WORD_W * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0, source="native"
    )


def _ctx(*pages_and_roles: tuple[str, str]):
    ctx = new_context("d", "/x.pdf")
    pages, meta = [], []
    for n, (text, role) in enumerate(pages_and_roles, start=1):
        pages.append(_page(text, n))
        meta.append(PageMeta(n, 100, 0, 0, role))
    ctx.pages = tuple(pages)
    ctx.page_meta = tuple(meta)
    return ctx


PAST_DUE = re.compile(r"\bPAST\s+DUE\b", re.I)


# -- primary_pages ---------------------------------------------------------


def test_primary_pages_selects_only_primary_roles() -> None:
    ctx = _ctx(("invoice", "primary"), ("bill of lading", "supporting"))
    assert [p.page_number for p in signals.primary_pages(ctx)] == [1]


def test_primary_pages_falls_back_to_every_page_when_no_roles_assigned() -> None:
    """Mirrors registry.primary_text's documented fallback: a classifier that
    classifies nothing is worse than one that reads a supporting page, and
    Stage 2 always assigns roles before Stage 3 in the real pipeline."""
    ctx = _ctx(("invoice", "primary"), ("more", "supporting"))
    ctx.page_meta = ()
    assert [p.page_number for p in signals.primary_pages(ctx)] == [1, 2]


# -- short_label_line ------------------------------------------------------


def test_short_label_line_matches_a_standalone_banner() -> None:
    ctx = _ctx(("PAST DUE", "primary"))
    assert signals.short_label_line(ctx, PAST_DUE, max_words=6) is True


def test_short_label_line_rejects_the_same_phrase_inside_prose() -> None:
    """Federal Recycling's boilerplate terms, on every invoice this vendor
    sends, and correctly not tagged past_due in gold."""
    ctx = _ctx(("PAST DUE AMOUNTS SUBJECT TO INTEREST FEES IN THE AMOUNT OF 18.99%", "primary"),)
    assert signals.short_label_line(ctx, PAST_DUE, max_words=6) is False


def test_short_label_line_ignores_supporting_pages_by_default() -> None:
    """The Windstream defect: a wrapped prose fragment on a SUPPORTING page
    ('any past due Internet balance.') is only 5 words, so word count alone
    cannot reject it. Page scope can."""
    ctx = _ctx(("ordinary bill", "primary"), ("any past due Internet balance.", "supporting"))
    assert signals.short_label_line(ctx, PAST_DUE, max_words=8) is False


def test_short_label_line_can_opt_into_every_page() -> None:
    ctx = _ctx(("ordinary bill", "primary"), ("PAST DUE", "supporting"))
    assert signals.short_label_line(ctx, PAST_DUE, max_words=8, primary_only=False) is True


# -- title_near_top --------------------------------------------------------


CREDIT_MEMO = re.compile(r"\b(credit memo|credit note|adjustment note)\b", re.I)


def test_title_near_top_matches_a_real_title() -> None:
    """The genuine title on `_AP Invoice 32473` sits at page-1 line index 5."""
    body = "|".join(["filler"] * 5 + ["CREDIT MEMO"] + ["filler"] * 14)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is True


def test_title_near_top_rejects_a_wrapped_footnote_deep_in_the_page() -> None:
    """`_AP Invoice 32593`'s footnote wraps onto a SHORT line at index 25-26,
    which passes a word-count check exactly like a real title would. Position
    is the discriminator."""
    body = "|".join(["filler"] * 25 + ["Credit memo 32684."] + ["filler"] * 4)
    ctx = _ctx((body, "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


def test_title_near_top_reads_page_1_only() -> None:
    ctx = _ctx(("filler", "primary"), ("CREDIT MEMO", "primary"))
    assert signals.title_near_top(ctx, CREDIT_MEMO, max_words=7, max_line_index=10) is False


# -- label_with_corroborating_value ---------------------------------------


TAX = re.compile(r"\b(total tax|taxes)\b", re.I)
MONEY = re.compile(r"\d[\d,]*\.\d{2}")


def _second_to_last_nonzero(text: str) -> bool:
    tokens = MONEY.findall(text)
    if not tokens:
        return False
    candidate = tokens[-2] if len(tokens) >= 2 else tokens[-1]
    try:
        return float(candidate.replace(",", "")) != 0.0
    except ValueError:
        return False


def test_label_with_a_nonzero_value_on_the_next_line_corroborates() -> None:
    ctx = _ctx(("Total Tax|0.00 0.00 299.55 4,908.00", "primary"))
    assert signals.label_with_corroborating_value(
        ctx, TAX, next_line=_second_to_last_nonzero
    ) is True


def test_label_with_a_zero_value_does_not_corroborate() -> None:
    """The whole point: the column LABEL is printed on every Veritiv invoice,
    taxed or not. Only the value separates them."""
    ctx = _ctx(("Total Tax|0.00 0.00 0.00 625.00", "primary"))
    assert signals.label_with_corroborating_value(
        ctx, TAX, next_line=_second_to_last_nonzero
    ) is False


def test_label_with_no_value_row_at_all_does_not_corroborate() -> None:
    ctx = _ctx(("Total Tax", "primary"))
    assert signals.label_with_corroborating_value(
        ctx, TAX, next_line=_second_to_last_nonzero
    ) is False
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/packs/test_signals.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.packs.signals'`

- [ ] **Step 3: Implement the module**

Create `src/docintel/packs/signals.py`:

```python
"""The generic techniques a classification signal is built from.

Every function here was invented inside `northstar/ladder.py` to fix a
specific, named, real-document defect - and every one of them was then NOT
applied to the identical check in `digitaldirection/ladder.py`, which is how
Windstream shipped a `past_due` false positive that Northstar's ladder would
have rejected. The POLICY (which pattern, which cutoff, which rung) stays in
each pack, because the two businesses genuinely classify differently. The
MECHANICS live here, tested once, so the next fix reaches both packs without
anyone having to remember that there are two.

Nothing in this module knows what a tag or a doc_type is. It answers
questions about ink on a page.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from docintel.core.models import JobContext, PageText


def line_text(line: object) -> str:
    """A visual line's words joined with single spaces."""
    return " ".join(w.text for w in line)  # type: ignore[attr-defined]


def primary_pages(ctx: JobContext) -> list[PageText]:
    """Pages a field value or a classification signal may be read from.

    A supporting page - a Bill of Lading, a certificate, a carrier's FAQ -
    may name a different company, carry a different tax regime or show a
    different total, and none of those are statements about the invoice it
    is attached to (grammar section 7, `registry.primary_text`).

    Falls back to every page when no roles are assigned, mirroring
    `registry.primary_text` exactly: a classifier that classifies nothing is
    worse than one that occasionally reads a supporting page, and Stage 2
    always assigns roles before Stage 3 in the real pipeline.
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
    """Whether `pattern` appears on a SHORT line, not buried in prose.

    Federal Recycling's terms read "PAST DUE AMOUNTS SUBJECT TO INTEREST FEES
    IN THE AMOUNT OF 18.99% ANNUALLY..." - boilerplate on every invoice this
    vendor sends. EDCO's is a standalone `PAST DUE` banner. Line length is
    the discriminator, the same one `extract.pageroles` uses for the same
    reason.

    Length alone is NOT sufficient and callers must not treat it as such:
    OCR wraps prose onto short lines. Windstream page 3 carries the 5-word
    fragment "any past due Internet balance.", which no word-count cutoff
    can reject. `primary_only` defaults to True because that fragment is on
    a supporting page; a caller that genuinely needs every page must say so
    explicitly and say why.
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
    """Whether a genuine document TITLE matching `pattern` sits near the top
    of page 1.

    Short-line length alone cannot separate a title from a footnote: real OCR
    of Complete Beverage's "For remaining credited items refer to Credit memo
    32684." wraps across two SHORT lines, and the second one passes a
    word-count check exactly like a real title would. Position is the real
    discriminator - the genuine title on `_AP Invoice 32473` sits at page-1
    line index 5 of 20; the false-positive footnote on `_AP Invoice 32593`
    sits at index 25-26 of 30.

    Both constraints are applied, deliberately. Dropping the length check
    would leave a short prose aside near the top of the page able to fool
    this - which the corpus has not produced, but which length guards against
    for free.

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

    A printed column LABEL is not a fact. `Total Tax` appears on every
    Veritiv invoice whether or not tax was charged, and an aging header
    appears on every U-PAK invoice whether or not anything is aged - so
    matching the label alone makes the check trivially true on exactly the
    documents it exists to catch.

    The corroboration predicates are the caller's, because what counts as
    "the value" is layout-specific: Veritiv's tax amount is the
    second-to-last money token on the row (immediately before the trailing
    grand total), while an aging bucket is any token strictly between the
    first (CURRENT) and last (Please Pay).

    `same_line` is tried first, then `next_line` on the following visual
    line: in every corpus and second-sample document the value row is either
    the same visual line (rare) or the next one.
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/packs/test_signals.py -v`
Expected: PASS (14 passed)

- [ ] **Step 5: Full verification — nothing else may change**

Run: `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 -m docintel.cli replay-gold`
Expected: tests 1723 → 1737; `replay-gold` byte-identical to Task 1's output. This
task adds a module and calls nothing, so any change in `replay-gold` means
something is wrong.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/packs/signals.py tests/packs/test_signals.py
git commit -m "feat(packs): shared signal vocabulary for both ladders

Four techniques - primary-page scoping, short-label line, title-near-top,
label-with-corroborating-value - each invented in northstar/ladder.py to fix
a named real-document defect, and each never applied to the identical check
in digitaldirection/ladder.py. Owned and tested once here. No caller yet;
no behavior change."
```

---

### Task 3: Migrate the Northstar ladder onto `signals` — no behavior change

Northstar goes first precisely because it is the pack whose behavior must NOT
change: it already has all four techniques applied correctly, so a byte-identical
`replay-gold` is the proof the shared module is a faithful extraction.

**Files:**
- Modify: `src/docintel/packs/northstar/ladder.py` (delete `_short_line_has` at 95-110, `_credit_memo_title_present` at 113-146, `_primary_pages` at 175-182; rewrite the bodies of `_aging_table_has_balance` at 185-217 and `_short_line_has_nonzero_tax` at 267-293)
- Test: `tests/packs/test_northstar_ladder.py` (must pass unchanged)

**Interfaces:**
- Consumes: every function from Task 2.
- Produces: no new public names. `doc_type_for` and `tags_for` keep their signatures.

- [ ] **Step 1: Confirm the current behavior is pinned before touching it**

Run: `python3 -m pytest tests/packs/test_northstar_ladder.py -q && python3 -m docintel.cli replay-gold --json > /tmp/before-task3.json`
Expected: PASS. Keep `/tmp/before-task3.json` — Step 5 diffs against it.

- [ ] **Step 2: Rewrite the five call sites**

In `src/docintel/packs/northstar/ladder.py`, add the import:

```python
from docintel.packs import signals
```

Replace `_credit_memo_title_present`'s body (keep the existing docstring, which
carries the real-document evidence, and append the note below):

```python
def _credit_memo_title_present(ctx: JobContext) -> bool:
    """<KEEP THE EXISTING DOCSTRING VERBATIM>

    Mechanics now live in `packs.signals.title_near_top`; the constants below
    remain this pack's policy.
    """
    return signals.title_near_top(
        ctx,
        _CREDIT_MEMO,
        max_words=_MAX_CREDIT_MEMO_LINE_WORDS,
        max_line_index=_MAX_CREDIT_MEMO_LINE_INDEX,
    )
```

In `_aging_table_has_balance`, replace the manual page/line walk with — note
`primary_only=False`, which preserves the existing all-pages scope its docstring
already justifies at length:

```python
    everything = "\n".join(p.text for p in ctx.pages)
    if not _AGING_HEADER.search(everything):
        return False
    return signals.label_with_corroborating_value(
        ctx,
        _AGING_HEADER,
        same_line=_aging_buckets_nonzero,
        next_line=_aging_buckets_nonzero,
        primary_only=False,
    )
```

In `_short_line_has_nonzero_tax`, replace the body — `primary_only=True` preserves
the narrowing its docstring justifies:

```python
    return signals.label_with_corroborating_value(
        ctx,
        _TAX_LINE,
        same_line=_same_line_tax_value_nonzero,
        next_line=_tax_value_nonzero,
        primary_only=True,
    )
```

In `tags_for`, replace `_short_line_has(ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS)`
with:

```python
    past_due_banner = signals.short_label_line(
        ctx, _PAST_DUE, _MAX_PAST_DUE_LINE_WORDS, primary_only=False
    )
```

**`primary_only=False` here is deliberate and must not be "tidied" to True.**
`_short_line_has`'s existing docstring records that this check has scanned every
page since before the 2026-08-06 plan, and that decision was reviewed and
accepted; Federal Recycling's terms-and-conditions page is the case it was
reasoned about. Changing the scope here would be a behavior change, which this
task forbids. Task 4 changes Digital Direction's scope, where the evidence points
the other way.

Then delete the now-unused `_short_line_has` and `_primary_pages` functions.

- [ ] **Step 3: Run the pack's own tests**

Run: `python3 -m pytest tests/packs/test_northstar_ladder.py -v`
Expected: PASS, unchanged count. If any test fails, the extraction is not
faithful — fix `signals.py` or the call site, never the test.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest -q && python3 -m mypy && ruff check src tests`
Expected: all pass, 1737 tests.

- [ ] **Step 5: Prove `replay-gold` is byte-identical**

```bash
python3 -m docintel.cli replay-gold --json > /tmp/after-task3.json
diff /tmp/before-task3.json /tmp/after-task3.json && echo "IDENTICAL"
```
Expected: `IDENTICAL`. Any diff is a failed extraction — investigate before
committing.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/packs/northstar/ladder.py
git commit -m "refactor(packs): northstar ladder calls packs.signals

Pure extraction. Page scopes preserved exactly, including the deliberate
all-pages scope on the past_due banner and the aging corroboration, both of
which their own docstrings justify. replay-gold byte-identical."
```

---

### Task 4: Migrate the Digital Direction ladder — fixes the Windstream `past_due` false positive

This is where the shared vocabulary pays. Digital Direction's `_short_line_has`
scans every page, so Windstream's supporting-page prose fragment "any past due
Internet balance." (5 words, page 3, page role `supporting`) tags a bill that
gold marks `prior_balance_cleared`.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/ladder.py` (delete `_short_line_has` at 109-117; rewrite the `past_due` block at 92-95)
- Test: `tests/packs/test_digitaldirection_past_due.py` (create)

**Interfaces:**
- Consumes: `signals.short_label_line` from Task 2; `forbidden_tags` from Task 1.
- Produces: no new public names.

- [ ] **Step 1: Write the failing test**

Create `tests/packs/test_digitaldirection_past_due.py`:

```python
"""Windstream's `past_due` false positive, from the real document.

`Windstream_041069076_07222025_BILL.pdf` page 3 - a SUPPORTING page - prints
the prose fragment "any past due Internet balance." That is 5 words, so the
pack's <=8-word cutoff cannot reject it, and the pack's `_short_line_has`
scanned every page. Gold marks this document `prior_balance_cleared` with no
`past_due`, and its forbidden_tags list now says so affirmatively.

Northstar's identical check was narrowed and corroborated on 2026-08-06.
Digital Direction's was not. This test pins the real document, not a
synthetic line, because the 2026-08-06 audit's own lesson is that a
synthetic fixture passed while the real OCR'd document still failed.
"""

from __future__ import annotations

import os

import pytest

from docintel.core.models import JobContext, new_context
from docintel.extract import normalize, pageroles
from docintel.packs.digitaldirection.ladder import tags_for

REAL_PDF = "docs/Windstream_041069076_07222025_BILL.pdf"


def _ctx_from(path: str) -> JobContext:
    pages, meta, text_source = normalize.load_document(path)
    roles, _ = pageroles.assign(pages, meta)
    ctx = new_context("w", path)
    ctx.pages = pages
    ctx.page_meta = roles
    ctx.text_source = text_source
    return ctx


@pytest.mark.skipif(not os.path.exists(REAL_PDF), reason="corpus PDF not present")
def test_the_real_windstream_bill_is_not_tagged_past_due() -> None:
    assert "past_due" not in tags_for(_ctx_from(REAL_PDF))


@pytest.mark.skipif(not os.path.exists(REAL_PDF), reason="corpus PDF not present")
def test_the_offending_fragment_is_really_on_a_supporting_page() -> None:
    """Pins WHY the fix works. If a future template change moves this line to
    page 1, this test fails and tells the next person the scope fix is no
    longer sufficient on its own."""
    ctx = _ctx_from(REAL_PDF)
    supporting = {m.page_number for m in ctx.page_meta if m.role != "primary"}
    found = [
        p.page_number
        for p in ctx.pages
        if "past due" in p.text.lower()
    ]
    assert found, "the fragment must still be present, or this test proves nothing"
    assert set(found) <= supporting
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `python3 -m pytest tests/packs/test_digitaldirection_past_due.py -v`
Expected: the first test FAILS (`past_due` is currently emitted); the second PASSES.

- [ ] **Step 3: Rewrite the `past_due` block**

In `src/docintel/packs/digitaldirection/ladder.py`, add `from docintel.packs import
signals` and replace lines 92-95 with:

```python
    if signals.short_label_line(
        ctx, _AGING, _MAX_PAST_DUE_LINE_WORDS
    ) or signals.short_label_line(ctx, _AGING_COLUMNS, _MAX_AGING_HEADER_WORDS):
        tags.append("past_due")
```

and replace the bare whole-text regex with a named, line-scoped pattern beside the
others near the top of the file:

```python
# The aging COLUMN HEADER, matched on its own short line rather than across
# the whole document's text. The previous form, `re.search(r"\b30 DAYS\b.*\b60
# DAYS\b", everything)`, ran over every page joined into one string, so `.*`
# could span pages and match a "30 DAYS" on page 1 against a "60 DAYS" on page
# 9. A table header is a line, so it is matched as one. The cutoff is generous
# because a real header row legitimately bundles several short cells onto one
# visual line ("AGE CURRENT 30 DAYS 60 DAYS 90 DAYS Please Pay"), the same
# reasoning `extract.pageroles` uses for its own totals-line cutoff.
_AGING_COLUMNS = re.compile(r"\b30\s*DAYS\b.*\b60\s*DAYS\b", re.I)
_MAX_AGING_HEADER_WORDS = 12
```

Then delete the now-unused `_short_line_has`, and drop the now-unused `everything`
local if nothing else in `tags_for` uses it (`_SCANLINE` does — keep it).

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/packs/test_digitaldirection_past_due.py tests/packs/test_digitaldirection_ladder.py -v`
Expected: PASS. If a pre-existing ladder test now fails, read it before changing
anything: it may be pinning the old all-pages scope, in which case its
justification must be checked against the real document rather than the test
being edited to suit.

- [ ] **Step 5: Confirm the scorecard now sees the fix**

Run: `python3 -m docintel.cli replay-gold`
Expected: windstream's `forbidden_tags` assertion flips to passing — 26/30 → 27/30.
The document still fails overall on unrelated address/reference assertions.

- [ ] **Step 6: Full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py
git add src/docintel/packs/digitaldirection/ladder.py tests/packs/test_digitaldirection_past_due.py
git commit -m "fix(packs): DD past_due no longer fires on supporting-page prose

Windstream page 3 prints 'any past due Internet balance.' - 5 words, so no
word-count cutoff rejects it, and the pack scanned every page. Narrowed to
primary pages via packs.signals, matching the narrowing Northstar's identical
check received on 2026-08-06. Also replaces the whole-document 30/60 DAYS
regex, whose .* could span pages, with a line-scoped header match."
```

---

### Task 5: `count_printed_names` counts brands, not alias phrases — fixes the Comcast false positive

`aliases.count_printed_names` has one caller and zero tests, and drives a
gold-asserted tag. It counts matched alias *phrases*, so a short alias that is a
substring of a longer matched alias is counted twice.

Measured 2026-08-07 on the real documents:

| document | matched phrases | true brands |
|---|---|---|
| Comcast | `comcast`, `comcast business` | **1** (nested) |
| Lumen | `lumen`, `level 3 communications`, `level 3 communications llc`, `centurylink` | **3** (one nested) |
| Windstream | `windstream`, `kinetic business` | 2 |
| Centracom | `centracom` | 1 |

Counting distinct *canonical* values instead would be wrong: Lumen's three names
all canonicalize to `lumen`, and that document genuinely is multi-brand.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/aliases.py:133-145`
- Test: `tests/packs/test_count_printed_names.py` (create)

**Interfaces:**
- Consumes: `forbidden_tags` from Task 1.
- Produces: `count_printed_names(text: str) -> int` keeps its signature.

- [ ] **Step 1: Write the failing test**

Create `tests/packs/test_count_printed_names.py`:

```python
"""Distinct printed BRANDS, not matched alias phrases.

`multi_brand_sender` exists to make the alias collapse auditable: Lumen
prints three names for one carrier and the tag says so on the record. But
the count was over phrases, and `comcast` is a substring of `comcast
business`, so one printed brand counted twice and Comcast was tagged
multi-brand against its gold label.

Counting distinct CANONICALS instead would break the case the tag exists
for: Lumen's `lumen` / `centurylink` / `level 3 communications` all
canonicalize to `lumen`. Nesting is the discriminator.
"""

from __future__ import annotations

import os

import pytest

from docintel.core.models import JobContext, new_context
from docintel.extract import normalize, pageroles
from docintel.packs.digitaldirection import aliases
from docintel.packs.registry import primary_text


def test_a_nested_alias_pair_counts_as_one_brand() -> None:
    assert aliases.count_printed_names("Comcast Business Internet, a Comcast company") == 1


def test_two_disjoint_brands_count_as_two() -> None:
    assert aliases.count_printed_names("KINETIC BUSINESS by WINDSTREAM") == 2


def test_three_disjoint_brands_count_as_three() -> None:
    """Lumen's real page: the LUMEN logo, 'Level 3 Communications, LLC' and
    'a CenturyLink company'. `level 3 communications llc` is nested inside
    nothing here and `level 3 communications` is nested inside IT, so the
    pair contributes one."""
    text = "LUMEN Invoice of Level 3 Communications, LLC, a CenturyLink company"
    assert aliases.count_printed_names(text) == 3


def test_a_single_brand_counts_as_one() -> None:
    assert aliases.count_printed_names("CENTRACOM") == 1


def _brands(path: str) -> int:
    pages, meta, _ = normalize.load_document(path)
    roles, _ = pageroles.assign(pages, meta)
    ctx = new_context("d", path)
    ctx.pages, ctx.page_meta = pages, roles
    return aliases.count_printed_names(primary_text(ctx))


REAL = {
    "docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf": 1,
    "docs/Lumen - 5-QXH7QKM7.pdf": 3,
    "docs/Windstream_041069076_07222025_BILL.pdf": 2,
    "docs/Centracom_0384043574_01012026_BILL.pdf": 1,
}


@pytest.mark.parametrize("path,expected", sorted(REAL.items()))
def test_the_real_documents(path: str, expected: int) -> None:
    if not os.path.exists(path):
        pytest.skip("corpus PDF not present")
    assert _brands(path) == expected
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/packs/test_count_printed_names.py -v`
Expected: the Comcast synthetic case and the real Comcast case FAIL (returning 2
and 2); the Lumen real case FAILS (returning 4).

- [ ] **Step 3: Implement**

Replace the body of `count_printed_names` in
`src/docintel/packs/digitaldirection/aliases.py`:

```python
def count_printed_names(text: str) -> int:
    """How many distinct BRAND NAMES this page prints.

    Drives the `multi_brand_sender` tag, which is what makes the alias
    collapse visible on the record rather than a silent normalization nobody
    can audit. Lumen prints three names, Windstream two.

    A matched alias that is a substring of another matched alias is not a
    second printed name - it is the same ink, matched twice. `comcast` is a
    substring of `comcast business`, and counting phrases tagged Comcast
    `multi_brand_sender` against its gold label.

    Counting distinct CANONICALS instead would be wrong in the other
    direction and would break the case this tag exists for: Lumen's `lumen`,
    `centurylink` and `level 3 communications` all canonicalize to `lumen`,
    and that document genuinely does print three brands.
    """
    normalized = normalize_name(text)
    matched = {phrase for phrase in LITERAL_ALIASES if phrase in normalized}
    outermost = {
        phrase
        for phrase in matched
        if not any(other != phrase and phrase in other for other in matched)
    }
    return len(outermost)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/packs/test_count_printed_names.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Confirm the scorecard sees it**

Run: `python3 -m docintel.cli replay-gold`
Expected: comcast's `forbidden_tags` assertion flips to passing — 28/32 → 29/32.
Lumen's `multi_brand_sender` must still be present (it is in Lumen's gold `tags`,
so a regression here fails Lumen's superset assertion loudly).

- [ ] **Step 6: Full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py
git add src/docintel/packs/digitaldirection/aliases.py tests/packs/test_count_printed_names.py
git commit -m "fix(packs): count_printed_names counts brands, not alias phrases

'comcast' is a substring of 'comcast business', so one printed brand counted
twice and Comcast was tagged multi_brand_sender against gold. Drops nested
matches. Counting canonicals instead would break Lumen, whose three printed
names share one canonical. First tests for this function."
```

---

### Task 6: Digital Direction's `credit_memo` rung must check for a title

`dd/ladder.py:62` returns the signal name `credit_memo_title` from a bare
`_CREDIT_MEMO.search(text)`. Nothing checks that the match is a title. This is
defect #4 of the 2026-08-06 audit, fixed in Northstar and never applied here, and
on this pack a wrong `doc_type` loads the wrong persona — the Centracom failure
mode.

**Scope honesty:** verified 2026-08-07 that **0 of 7** telecom second-samples
(5 Windstream, 2 Lumen) print "credit memo" or "adjustment notice" anywhere, so
this defect is latent, not observed. It is fixed here because the corrected
mechanics are one call away once Task 2 exists, not because it is firing.

**Files:**
- Modify: `src/docintel/packs/digitaldirection/ladder.py:36, 58-70`
- Test: `tests/packs/test_digitaldirection_credit_memo.py` (create)

**Interfaces:**
- Consumes: `signals.title_near_top` from Task 2.
- Produces: no new public names. Module constants `_MAX_CREDIT_MEMO_LINE_WORDS`, `_MAX_CREDIT_MEMO_LINE_INDEX`.

- [ ] **Step 1: Write the failing test**

Create `tests/packs/test_digitaldirection_credit_memo.py`:

```python
"""A telecom bill that MENTIONS a credit memo is still a bill.

Defect #4 of the 2026-08-06 audit, fixed in northstar/ladder.py and never
applied here: the rung returns the signal name `credit_memo_title` from a
bare pattern search that checks nothing about titles. On this pack a wrong
doc_type loads the wrong persona, which is the Centracom failure mode.

Latent, not observed: 0 of 7 telecom second-samples print this wording. The
fixtures below are therefore synthetic BY NECESSITY, and are modelled on the
real Northstar document that produced the defect - Complete Beverage's
footnote 'For remaining credited items refer to Credit memo 32684.', which
real OCR wraps across two SHORT lines deep in the page.
"""

from __future__ import annotations

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.digitaldirection.ladder import doc_type_for


def _page(text: str, number: int = 1) -> PageText:
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0, source="native"
    )


def _ctx(text: str):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page(text),)
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


def test_a_credit_memo_title_at_the_top_still_classifies() -> None:
    body = "|".join(["ACME TELECOM"] + ["CREDIT MEMO"] + ["filler"] * 18)
    assert doc_type_for(_ctx(body)) == ("credit_memo", "credit_memo_title")


def test_a_wrapped_footnote_deep_in_the_page_does_not() -> None:
    body = "|".join(
        ["ACME TELECOM"]
        + ["filler"] * 24
        + ["For remaining credited items refer to", "Credit memo 32684."]
        + ["filler"] * 3
    )
    assert doc_type_for(_ctx(body)) == ("telecom_bill", "default")


def test_a_long_prose_line_mentioning_a_credit_memo_does_not() -> None:
    body = "|".join(
        ["ACME TELECOM"]
        + ["Any adjustment notice issued against this account will be applied to the next cycle"]
        + ["filler"] * 18
    )
    assert doc_type_for(_ctx(body)) == ("telecom_bill", "default")
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/packs/test_digitaldirection_credit_memo.py -v`
Expected: tests 2 and 3 FAIL (both currently return `credit_memo`); test 1 passes.

- [ ] **Step 3: Implement**

In `src/docintel/packs/digitaldirection/ladder.py`, add beside the other constants:

```python
# A genuine credit-memo TITLE, not a mention. Same two constraints and the
# same real-document evidence as `northstar.ladder._credit_memo_title_present`
# (see `packs.signals.title_near_top`): a footnote referring to a credit memo
# wraps onto SHORT lines under real OCR, so line length alone cannot separate
# it from a title - position can. Latent on this pack today (0 of 7 telecom
# second-samples print the wording), fixed because a wrong doc_type here loads
# the wrong persona.
_MAX_CREDIT_MEMO_LINE_WORDS = 7
_MAX_CREDIT_MEMO_LINE_INDEX = 10
```

and replace the rung:

```python
    if signals.title_near_top(
        ctx,
        _CREDIT_MEMO,
        max_words=_MAX_CREDIT_MEMO_LINE_WORDS,
        max_line_index=_MAX_CREDIT_MEMO_LINE_INDEX,
    ):
        return "credit_memo", "credit_memo_title"
```

Note `doc_type_for` currently takes `text = primary_text(ctx)` at the top; the new
rung reads `ctx` directly, so leave `text` in place for the rungs below it.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/packs/test_digitaldirection_credit_memo.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 -m docintel.cli replay-gold
git add src/docintel/packs/digitaldirection/ladder.py tests/packs/test_digitaldirection_credit_memo.py
git commit -m "fix(packs): DD credit_memo rung checks for an actual title

The rung returned the signal name credit_memo_title from a bare pattern
search. Defect #4 of the 2026-08-06 audit, fixed in northstar and never
applied here. Latent (0 of 7 telecom second-samples print the wording) but a
wrong doc_type on this pack loads the wrong persona."
```

---

### Task 7: `foreign_currency` from printed evidence

Gold expects `foreign_currency` on U-PAK (a Canadian invoice) and the tag has no
implementation. It was assumed blocked by the printed-fields-only narrowing, which
dropped the inferred `currency` field. It is not: the evidence is ink on the page.

Measured 2026-08-07 across all 11 gold documents:

| signal | hits | matches gold `foreign_currency`? |
|---|---|---|
| Canadian postal code `A1A 1A1` | **1/11** (U-PAK only) | exactly |
| Canadian tax label (H.S.T./G.S.T./Q.S.T.) | 2/11 (U-PAK **and Lumen**) | no — false-fires |

So the postal code is the signal and the tax label is not. U-PAK prints
`15 TIDEMORE AVENUE, ETOBICOKE, ON M9W 7E9`.

**Files:**
- Modify: `src/docintel/packs/northstar/ladder.py` (`tags_for`)
- Test: `tests/packs/test_northstar_foreign_currency.py` (create)

**Interfaces:**
- Consumes: `signals.primary_pages` from Task 2.
- Produces: tag `foreign_currency` on Northstar documents.

- [ ] **Step 1: Write the failing test**

Create `tests/packs/test_northstar_foreign_currency.py`:

```python
"""`foreign_currency` from a printed Canadian postal code.

Gold expects this tag on U-PAK and nothing implemented it. It was assumed
blocked by the printed-fields-only narrowing, which dropped the INFERRED
`currency` field - but a postal code is ink on the page, so this stays
squarely inside that narrowing.

Measured across all 11 gold documents on 2026-08-07: a Canadian postal code
hits 1/11, exactly the document gold tags. A Canadian tax label hits 2/11 -
it ALSO fires on Lumen, whose FAQ text mentions GST - so the tax label is not
usable as the signal and is deliberately not part of it.
"""

from __future__ import annotations

import os

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.extract import normalize, pageroles
from docintel.packs.northstar.ladder import tags_for


def _page(text: str, number: int = 1) -> PageText:
    words: list[Word] = []
    for row, line in enumerate(text.split("|")):
        y = 100.0 + row * 14.0
        for i, tok in enumerate(line.split()):
            words.append(
                Word(text=tok, x0=10.0 + 40.0 * i, y0=y, x1=45.0 + 40.0 * i, y1=y + 10.0)
            )
    return PageText(
        page_number=number, words=tuple(words), width=612.0, height=792.0, source="native"
    )


def _ctx(text: str):
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page(text),)
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


def test_a_canadian_postal_code_tags_foreign_currency() -> None:
    assert "foreign_currency" in tags_for(_ctx("15 TIDEMORE AVENUE ETOBICOKE ON M9W 7E9"))


def test_a_postal_code_without_the_space_also_tags() -> None:
    assert "foreign_currency" in tags_for(_ctx("15 TIDEMORE AVENUE ETOBICOKE ON M9W7E9"))


def test_a_us_zip_does_not_tag() -> None:
    assert "foreign_currency" not in tags_for(_ctx("PO BOX 188 EAST LONGMEADOW MA 01028"))


def test_a_us_zip_plus_four_does_not_tag() -> None:
    assert "foreign_currency" not in tags_for(_ctx("PO BOX 52015 PHOENIX AZ 85072-2015"))


def test_a_tax_label_alone_does_not_tag() -> None:
    """Lumen's page mentions GST and is NOT a foreign-currency document. The
    tax label is measured at 2/11 on the gold corpus and is deliberately not
    part of this signal."""
    assert "foreign_currency" not in tags_for(_ctx("TOTAL TAX G.S.T. 299.55"))


GOLD = [
    ("docs/_AP Invoice 4378107 U-Pak 14740.85000.pdf", True),
    ("docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 1050.00000.pdf", False),
]


@pytest.mark.parametrize("path,expected", GOLD)
def test_the_real_documents(path: str, expected: bool) -> None:
    if not os.path.exists(path):
        pytest.skip("corpus PDF not present")
    pages, meta, text_source = normalize.load_document(path)
    roles, _ = pageroles.assign(pages, meta)
    ctx = new_context("d", path)
    ctx.pages, ctx.page_meta, ctx.text_source = pages, roles, text_source
    assert ("foreign_currency" in tags_for(ctx)) is expected
```

The implementer must confirm the two real filenames against `ls docs/*.pdf` and
against `docs/corpus/gold/northstar-upak-4378107.json`'s `source_file` before
running; correct them in the test if they differ.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `python3 -m pytest tests/packs/test_northstar_foreign_currency.py -v`
Expected: the two positive cases FAIL (tag never emitted); the negative cases pass
vacuously.

- [ ] **Step 3: Implement**

In `src/docintel/packs/northstar/ladder.py`, beside the other tag patterns:

```python
# A Canadian postal code (`M9W 7E9`), which is ink on the page rather than an
# inference - so this stays inside the printed-fields-only narrowing that
# dropped the `currency` FIELD. The optional space is real: U-PAK prints it,
# but OCR of the same block does not always preserve it.
#
# Measured across all 11 gold documents on 2026-08-07: this pattern hits
# exactly 1, the one gold tags `foreign_currency`. A Canadian tax label
# (H.S.T./G.S.T.) hits 2 - it also fires on Lumen, whose page text mentions
# GST while the bill is in USD - so the tax label is deliberately NOT part of
# this signal.
#
# Read from primary pages only: a stapled Bill of Lading may name a Canadian
# shipper on an invoice that is itself in USD, which is exactly the class of
# error `primary_pages` exists to prevent.
_CANADIAN_POSTAL = re.compile(r"\b[A-Z]\d[A-Z]\s?\d[A-Z]\d\b")
```

and in `tags_for`:

```python
    if _foreign_currency(ctx):
        tags.append("foreign_currency")
```

with:

```python
def _foreign_currency(ctx: JobContext) -> bool:
    """A printed address outside the pack's default-currency country.

    Named `foreign_currency` because that is the gold vocabulary and the
    business consequence - a CAD invoice paid as though it were USD is a real
    loss - but what is actually detected is a printed foreign ADDRESS. That
    distinction is deliberate: the currency itself is not reliably printed on
    U-PAK's invoice, and inferring it is exactly what the printed-fields-only
    narrowing forbids.
    """
    return any(
        _CANADIAN_POSTAL.search(page.text) for page in signals.primary_pages(ctx)
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python3 -m pytest tests/packs/test_northstar_foreign_currency.py -v`
Expected: PASS (7 passed).

- [ ] **Step 5: Check for false positives across the whole corpus**

```bash
python3 -m docintel.cli replay-gold
```
Expected: upak 19/28 → 20/28 (its `tags` superset assertion flips). **No other
document may gain `foreign_currency`** — if one does, the pattern is too loose and
the task stops for reassessment rather than proceeding.

- [ ] **Step 6: Commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py
git add src/docintel/packs/northstar/ladder.py tests/packs/test_northstar_foreign_currency.py
git commit -m "feat(packs): foreign_currency from a printed Canadian postal code

Gold expected this tag on U-PAK and nothing implemented it; it was assumed
blocked by printed-fields-only, which dropped the inferred currency field. A
postal code is ink on the page. Measured 1/11 on gold, exactly the tagged
document; a Canadian tax label measures 2/11 (false-fires on Lumen) and is
deliberately excluded."
```

---

### Task 8: `no_invoice_number` — a Lumen selector and a retag hook

`docs/packs/digital-direction.md:58` specifies this tag for Centracom, Comcast and
Windstream. `grep -rn no_invoice_number src/` returns nothing. It accounts for 3
of the 4 failing gold tag assertions.

It cannot be computed at Stage 3: it is a statement about what extraction found.
The retag pattern already exists for exactly this shape (`retag_prior_balance`,
registered at `beforeConfidenceGate`) and has been used once.

Verified 2026-08-07, and this ordering matters — without the selector the tag would
mean "nobody wrote a selector", which is circular:

| document | prints an invoice-number label? |
|---|---|
| Lumen | **yes** — `Invoice Number 752233001`, a 3-word line on page 1 |
| Centracom | no — 0 matching lines in the document |
| Comcast | no — 0 matching lines |
| Windstream | no — 0 matching lines |

**Files:**
- Modify: `src/docintel/packs/digitaldirection/personas/lumen.json`
- Modify: `src/docintel/packs/digitaldirection/ladder.py` (add `retag_missing_invoice_number`)
- Modify: `src/docintel/packs/digitaldirection/hooks.py` (register it)
- Modify: `src/docintel/packs/digitaldirection/fields.py` (add `invoice_number` to the `telecom_bill` field set if it is not already permitted)
- Test: `tests/packs/test_digitaldirection_no_invoice_number.py` (create)

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `retag_missing_invoice_number(ctx: JobContext) -> JobContext` in `dd/ladder.py`; hook `refineInvoiceNumberTag` registered at `beforeConfidenceGate`.

- [ ] **Step 1: Confirm the field is permitted by the pack's grammar**

Read `src/docintel/packs/digitaldirection/fields.py`. If `invoice_number` is not in
`fields_for("telecom_bill")`, add it there — **not** to `required_fields`, since
three of the four carriers genuinely do not print one. Run
`python3 -m pytest tests/packs/test_personas_validate.py -q` (GUARDRAIL 5) to
confirm the grammar still accepts every shipped persona.

- [ ] **Step 2: Write the failing test**

Create `tests/packs/test_digitaldirection_no_invoice_number.py`:

```python
"""`no_invoice_number` is a statement about what extraction found.

Specified at docs/packs/digital-direction.md:58 for three of the four
carriers and never implemented - 3 of the 4 failing gold tag assertions.

It cannot be computed at Stage 3, which runs before extraction. The retag
socket exists for exactly this shape (`retag_prior_balance`) and had been
used once.

The ordering matters and is verified, not assumed: Lumen really does print
`Invoice Number 752233001` on a 3-word line on page 1, and Centracom,
Comcast and Windstream really do print no invoice-number label at all (0
matching lines each, measured 2026-08-07). Without Lumen's selector this tag
would mean 'nobody wrote a selector', which is circular.
"""

from __future__ import annotations

from docintel.core.models import new_context
from docintel.packs.digitaldirection.ladder import retag_missing_invoice_number


def _ctx(invoice_number=None):
    ctx = new_context("d", "/x.pdf")
    ctx.doc_type = "telecom_bill"
    if invoice_number is not None:
        ctx.extracted.set("invoice_number", invoice_number, 0.95)
    return ctx


def test_tags_when_no_invoice_number_was_extracted() -> None:
    ctx = retag_missing_invoice_number(_ctx())
    assert "no_invoice_number" in ctx.tags


def test_does_not_tag_when_one_was_extracted() -> None:
    ctx = retag_missing_invoice_number(_ctx("752233001"))
    assert "no_invoice_number" not in ctx.tags


def test_an_empty_string_counts_as_missing() -> None:
    """A selector that matched its anchor but captured nothing has not found
    an invoice number, and the record must not claim it did."""
    ctx = retag_missing_invoice_number(_ctx(""))
    assert "no_invoice_number" in ctx.tags


def test_is_idempotent() -> None:
    ctx = retag_missing_invoice_number(retag_missing_invoice_number(_ctx()))
    assert ctx.tags.count("no_invoice_number") == 1
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `python3 -m pytest tests/packs/test_digitaldirection_no_invoice_number.py -v`
Expected: FAIL — `ImportError: cannot import name 'retag_missing_invoice_number'`

- [ ] **Step 4: Implement the retag**

In `src/docintel/packs/digitaldirection/ladder.py`:

```python
def retag_missing_invoice_number(ctx: JobContext) -> JobContext:
    """Tag `no_invoice_number` when extraction found none.

    Most carriers in this pack do not print an invoice number at all - the
    document's identity falls back to account plus billing period - and that
    is a fact a downstream consumer needs, because it is why two months of
    the same account are not duplicates of each other.

    This runs at `beforeConfidenceGate`, not in `tags_for`, because Stage 3
    runs before extraction and therefore cannot know what was found. Same
    reasoning and same socket as `retag_prior_balance`.

    An empty or whitespace-only value counts as missing: a selector that
    matched its anchor and captured nothing has not found an invoice number,
    and the record must not imply otherwise.
    """
    value = ctx.extracted.get("invoice_number")
    if value is None or not str(value).strip():
        ctx.add_tag("no_invoice_number")
    return ctx
```

In `src/docintel/packs/digitaldirection/hooks.py`, add the wrapper beside the
others and register it:

```python
def refine_invoice_number_tag(ctx: JobContext, next_: Next) -> JobContext:
    """`no_invoice_number`, which only extraction can decide (spec section 2)."""
    return next_(ladder.retag_missing_invoice_number(ctx))
```

```python
    registry.register("beforeConfidenceGate", refine_invoice_number_tag, PACK_NAME)
```

Register it **before** `collect_references` in the existing registration block, so
the tag is on the record by the time references are promoted.

- [ ] **Step 5: Run the test to verify it passes**

Run: `python3 -m pytest tests/packs/test_digitaldirection_no_invoice_number.py -v`
Expected: PASS (4 passed).

- [ ] **Step 6: Add the Lumen selector**

Read `src/docintel/packs/digitaldirection/personas/lumen.json` and an existing
persona field entry to copy the exact schema shape — do not invent one. Add an
`invoice_number` field whose selector anchors on the printed label
`Invoice Number` and captures the digits after it. The real line is
`Invoice Number 752233001` on page 1, a 3-word visual line.

**GUARDRAIL 9 applies:** the selector must READ the value, not restate it. A
pattern containing `752233001` will be rejected by
`tests/packs/test_no_hardcoded_values.py`.

- [ ] **Step 7: Verify against gold**

Run: `python3 -m pytest -q && python3 -m docintel.cli replay-gold`
Expected:
- centracom 28/32 → 29/32 (still missing `past_due`, which is Task 10)
- comcast 29/32 → **30/32**
- windstream 27/30 → **28/30**
- lumen must NOT gain `no_invoice_number` — if it does, the selector is not
  matching and the tag is lying. Lumen's `fields.invoice_number` should now also
  be extracted; confirm it reads `752233001`.

- [ ] **Step 8: Commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py
git add src/docintel/packs/digitaldirection/ tests/packs/test_digitaldirection_no_invoice_number.py
git commit -m "feat(packs): no_invoice_number, via a Lumen selector and a retag hook

Specified for three carriers since the pack spec and never implemented - 3 of
the 4 failing gold tag assertions. Computed at beforeConfidenceGate because
Stage 3 runs before extraction, the same shape as retag_prior_balance. Lumen's
selector lands first so the tag means 'extraction looked and found none'
rather than 'nobody wrote a selector'."
```

---

### Task 9: An out-of-domain corpus — measure `claims()` precision

Every one of the 111 second-samples belongs to a vendor that is already in a pack,
so there are zero documents that *should* be rejected. `unclaimed_document: 3 → 0`
measures recall only. Meanwhile the markers were deliberately loosened —
`"ma 01028"` now claims **any** document printing that ZIP code — and the only
negative test in 1720 is one synthetic `ACME WIDGETS / SPRINGFIELD IL` fixture.

**Files:**
- Create: `tests/packs/test_claim_precision.py`
- Create: `tests/packs/fixtures/out_of_domain.py`

**Interfaces:**
- Consumes: `NorthstarPack.claims`, `DigitalDirectionPack.claims`.
- Produces: a fixture list other tasks may extend.

- [ ] **Step 1: Build the fixture set**

Create `tests/packs/fixtures/out_of_domain.py` with at least 12 synthetic
invoice page texts that must be claimed by **no** pack. Cover the specific ways the
loosened markers could over-claim:

```python
"""Documents no pack may claim.

Every one of the 111 second-samples belongs to a vendor already in a pack, so
the corpus contains no negative example at all and `claims()` precision is
unmeasured. The markers were deliberately loosened to catch OCR typos - the
Northstar roster now includes the bare ZIP `ma 01028` - and a loosened marker
trades false negatives for false positives. This is the fixture set that
measures the trade.

These are synthetic because the real risk is a document class the corpus does
not contain. Each names the specific over-claim it probes.
"""

OUT_OF_DOMAIN: dict[str, str] = {
    # The bare ZIP is a Northstar marker. Any OTHER business at that ZIP, or
    # any invoice merely shipping there, must not be claimed.
    "different_company_same_zip": (
        "ACME PACKAGING LLC|INVOICE 40122|"
        "BILL TO: HAMPDEN MILLS INC|22 SHAKER RD EAST LONGMEADOW MA 01028|"
        "TOTAL DUE 4,182.00"
    ),
    "ship_to_only_at_the_marker_zip": (
        "GLOBEX SUPPLY CO|INVOICE 88231|"
        "BILL TO: GLOBEX CORPORATE OFFICE 400 W 5TH ST AUSTIN TX 78701|"
        "SHIP TO: 94 MAPLE ST EAST LONGMEADOW MA 01028|TOTAL DUE 912.44"
    ),
    # A carrier-shaped bill from a carrier this pack does not manage.
    "unmanaged_carrier": (
        "VERIZON BUSINESS|Account Number 992-118-4471|"
        "BILL TO: CLYDE PARTNERS UNLIMITED|TOTAL AMOUNT DUE 1,204.55"
    ),
    # A managed-client NAME appearing as a line item on someone else's invoice.
    "managed_client_named_as_a_line_item": (
        "PRINTWORKS INC|INVOICE 5521|BILL TO: RIVERSIDE HOLDINGS|"
        "1x SIGNAGE FOR CITY OF DUBLIN PROJECT 2,400.00|TOTAL DUE 2,400.00"
    ),
    # Ordinary invoices from businesses in neither pack's domain.
    "plain_office_supply_invoice": (
        "NORTHWIND OFFICE SUPPLY|INVOICE 7781|"
        "BILL TO: PARKER & SONS 88 BROAD ST BOSTON MA 02110|TOTAL DUE 341.20"
    ),
    "plain_freight_invoice": (
        "SUMMIT FREIGHT LINES|PRO NUMBER 5541209|"
        "BILL TO: DELTA FOODS 900 INDUSTRIAL PKWY TOLEDO OH 43615|"
        "AMOUNT DUE 8,220.00"
    ),
}
```

Add at least six more in the same shape. Every entry needs a comment naming the
over-claim it probes. Do **not** include any real vendor name from either pack's
alias table — that would be testing the claim rather than its precision.

- [ ] **Step 2: Write the test**

Create `tests/packs/test_claim_precision.py`:

```python
"""No pack may claim a document outside its domain.

A wrong claim is worse than no claim: an unclaimed document is emitted and
tagged `unclaimed_document` for a human, while a wrongly-claimed one runs a
whole rulebook of another organization's assumptions against it.
"""

from __future__ import annotations

import pytest

from docintel.core.models import PageMeta, PageText, Word, new_context
from docintel.packs.registry import load_packs, resolve_pack
from tests.packs.fixtures.out_of_domain import OUT_OF_DOMAIN


def _ctx(text: str):
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
    ctx.page_meta = (PageMeta(1, 100, 0, 0, "primary"),)
    return ctx


@pytest.mark.parametrize("name,text", sorted(OUT_OF_DOMAIN.items()))
def test_no_pack_claims_an_out_of_domain_document(name: str, text: str) -> None:
    assert resolve_pack(_ctx(text), load_packs()) is None
```

- [ ] **Step 3: Run it and record the truth**

Run: `python3 -m pytest tests/packs/test_claim_precision.py -v`

**Both outcomes are a successful task.** If cases fail, the loosened markers do
over-claim, and that is the finding this task exists to produce.

- [ ] **Step 4: Do NOT fix a failure inside this task**

If any case fails, write the measured result into the module docstring of
`tests/packs/fixtures/out_of_domain.py`, mark the failing cases
`@pytest.mark.xfail(strict=True, reason="...")` with the specific marker that
over-claims named in the reason, and commit. Tightening a marker changes claiming
behavior across the whole corpus and needs its own task with its own gold
verification — folding it in here would mean this task's own measurement could not
be trusted.

- [ ] **Step 5: Full verification and commit**

```bash
python3 -m pytest -q && python3 -m mypy && ruff check src tests
git add tests/packs/fixtures/ tests/packs/test_claim_precision.py
git commit -m "test(packs): out-of-domain corpus measures claims() precision

All 111 second-samples belong to a vendor already in a pack, so precision was
unmeasured while the markers were being loosened - the Northstar roster now
includes a bare ZIP. 12 synthetic out-of-domain documents, each naming the
over-claim it probes."
```

---

### Task 10: Centracom's `past_due` — REQUIRES PRODUCT SIGN-OFF BEFORE IMPLEMENTING

**Do not start this task without an explicit decision recorded in the plan
ledger.** It is the one task in this plan whose correctness rests on a judgment
call rather than on document evidence.

Gold expects `past_due` on Centracom. Measured 2026-08-07, the document's **only**
"past due" text across all 10 pages is one 10-word prose line on page 1:

```
"A LAST MONTH BALANCE," ARE CONSIDERED PAST DUE AND WILL
```

That is boilerplate the word-count filter correctly rejects. There is no aging
table and no past-due banner anywhere. The document is genuinely past due — $20,123.80
is outstanding — and **no text pattern can produce that answer.** The evidence is
the money.

The candidate rule is that for a monthly telecom bill, `past_due` means last
month's balance did not clear — which `retag_prior_balance` already computes:

| document | prior balance state | gold `past_due` |
|---|---|---|
| Centracom | `prior_balance_present` | **yes** |
| Comcast | `prior_balance_cleared` | no |
| Lumen | `prior_balance_cleared` | no |
| Windstream | `prior_balance_cleared` | no |

4/4. **The reasons to be cautious, which the reviewer must weigh:**

1. Four documents is a thin base for a rule.
2. The correlation may be circular — whoever labeled the gold may have reasoned
   exactly this way, in which case the rule reproduces the labeler rather than the
   documents.
3. It makes `past_due` fully redundant with `prior_balance_present` on this pack:
   two tags carrying one fact. If that is right, the honest change might be to
   drop one tag rather than derive it from the other.
4. It would mean a document with a genuine aging table but a cleared prior balance
   is *not* tagged — the label-based branch from Task 4 would have to be kept as a
   disjunction, not replaced.

**Before implementing, run the correlation against the telecom second-samples**
(`all-docs/second-samples/{windstream,lumen}`) and report the hit rate. If the
correlation does not hold there, the rule is wrong and this task should be closed
without implementing.

**Files (only if approved):**
- Modify: `src/docintel/packs/digitaldirection/ladder.py` (`retag_prior_balance`)
- Test: `tests/packs/test_digitaldirection_past_due.py` (extend)

**Interfaces:**
- Consumes: `retag_prior_balance` from the existing code, Task 4's label branch.
- Produces: no new public names.

- [ ] **Step 1: Measure the correlation on the second-samples and write the result into the plan ledger**
- [ ] **Step 2: Obtain and record an explicit approve/reject decision**
- [ ] **Step 3 (if approved): Write the failing test, pinning the real Centracom document and all three cleared documents**
- [ ] **Step 4 (if approved): Add the derivation to `retag_prior_balance`, keeping Task 4's label branch as a disjunction**
- [ ] **Step 5 (if approved): Verify centracom 29/32 → 30/32 and no other document gains `past_due`**
- [ ] **Step 6 (if approved): Commit**
- [ ] **Step 7 (if rejected): Record the rejection and its reasoning in `docs/corpus/gold/digitaldirection-centracom-0384043574.json`'s note, so the next person does not re-derive it**

---

## Expected end state

| | baseline 2026-08-07 | after Tasks 1-9 | after Task 10 if approved |
|---|---|---|---|
| tests passing | 1720 | ~1770 | ~1774 |
| `replay-gold` green | 1/11 | 1/11 | 1/11 |
| centracom | 28/31 | 29/32 | 30/32 |
| comcast | 28/31 | 30/32 | 30/32 |
| windstream | 26/29 | 28/30 | 28/30 |
| upak | 19/28 | 20/28 | 20/28 |
| verified false-positive tags | 2 (invisible) | **0 (and visible)** | 0 |
| ladders sharing signal mechanics | no | **yes** | yes |
| `claims()` precision | unmeasured | **measured** | measured |

**No document is expected to flip to green,** and the plan should not be judged on
that. Every remaining failure on these four documents is address, reference or
line-item extraction — separate subsystems, separately tracked. What this plan
buys is: zero verified-wrong tags, a scorecard that can *see* a wrong tag, one
tested implementation of the four techniques instead of two hand-copied ones, and
the first measurement of claim precision.

## Self-review notes

- **Spec coverage.** Issues A-F from the analysis map to Tasks 5, 4, 10, 6, 8, 7
  respectively. Structural items #1 (shared vocabulary) → Tasks 2-4, #3 (two-phase
  tagging) → Task 8, #4 (precision) → Task 9, #5 (real-document fixtures) → applied
  as a global constraint and in Tasks 4, 5, 7. Items #2 (evidence-bearing signals)
  and #6 (classification escalation) are explicitly deferred with reasons in the
  Scope section, and #7 (feedback loop) is out of scope for a code plan.
- **Ordering.** Task 1 is first because without it Tasks 4, 5 and 6 cannot be shown
  to have fixed anything. Task 2 precedes 3-7 because they call it. Task 3 precedes
  Task 4 because Northstar is the pack whose behavior must not change, which makes
  it the proof that the extraction is faithful.
- **Type consistency.** `signals.short_label_line` takes `max_words` positionally
  and `primary_only` keyword-only; `title_near_top` takes both `max_words` and
  `max_line_index` keyword-only. Task 3, 4, 6 and 7 call sites match. `_ctx`
  helpers in the new test files follow the `|`-separated-rows convention already
  used in `tests/packs/test_digitaldirection_ladder.py`.
- **Known soft spot.** Tasks 1 and 8 both require reading existing code before
  writing (the scorecard's assertion-builder name and `kind` dispatch; the persona
  field schema). Those steps say so explicitly rather than guessing at signatures
  the plan cannot verify from outside.
