# Weakness Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the three weaknesses that can put a wrong value on a payment silently, then the six that make the pipeline fragile on an unseen sender, without regressing the 202/263 baseline.

**Architecture:** Every fix follows the project's existing shape — a signal is *measured* by a small pure function, *recorded* on the record, and *acted on* by Stage 7. Nothing new is invented: `bill_to_mismatch` reuses the `DEFAULT_FORCED_REVIEW_TAGS` mechanism that F3 already uses, per-page OCR reuses `ocr.ocr_pages`'s existing page-list parameter, and the geometry fixes replace absolute constants with the measured-pitch pattern already used by `HEADER_BAND`.

**Tech Stack:** Python 3.12, pdfplumber, Tesseract, pytest, mypy, ruff. No new dependencies.

## Global Constraints

- **`docs/corpus/gold/*.json` is READ-ONLY.** A test byte-compares all ten every run. A gold change requires re-reading the source PDF and a written justification.
- **Never classify or extract from the filename.** Three Northstar filenames state the answer outright.
- **Corpus-only tests confirm corpus-fit and cannot detect corpus-overfit.** Every task below that changes behaviour requires at least one *synthetic* fixture for a case the ten documents do not contain.
- **No assertion may pass against an empty record** (`tests/test_scorecard_coverage.py`, GUARDRAIL 3). A new assertion that an empty record satisfies must be keyed into `VACUOUS_BY_CONSTRUCTION` with a written reason.
- **Baseline to hold or beat: 202/263 assertions, 1/10 documents green.** Get the live figure with `python3 -m docintel.cli replay-gold`. `.loop/scorecard.json` is stale — do not trust it.
- **Verify with:** `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
- `replay-gold` exits 1 while any document fails. That is expected, not a broken build.
- **Guardrails 2 and 6 are skipped deliberately.** Un-skip them only in the same commit that re-registers `derive_amount_payable` (Task 11).
- Commit after every task. One task, one commit, message in the repo's existing `type(scope): sentence` style.

---

## Verification status of every weakness this plan addresses

All figures below were produced by executing the code on commit `fcf47f3`, not read from documentation.

| # | Weakness | How it was verified | Verdict |
|---|---|---|---|
| A1 | Confidence anti-correlated with correctness: 0.99 band 89% accurate, 0.90 band 93%; 8 wrong at 0.99 (1 money error of $6,621.41, 5 truncated addresses, 1 date format, 1 contaminated address) | computed per-band accuracy from `replay-gold --json` joined to each record's `confidence` map | **VALID** |
| A2 | Wrong-inbox invoices are claimed and unverified: the claim is a whole-page substring match; `resolve_bill_to_alias` prefers the printed name and never compares it to the roster | synthetic invoice billed to Contoso mentioning Northstar in a note → `claim: northstar`, `standard_invoice`; code read at `grammar/ops/infer.py:243` | **VALID** |
| A3 | No payable amount is emitted | records carry `total_printed` 33876.40 (Centracom) and 367.96 (EDCO) with `derived.amount_payable` **absent**; gold says 13752.60 and 69.62 | **VALID** |
| B1 | `doc_type` is half the persona key and derives from page count | same invoice content one page → `standard_invoice`, plus a T&C page → `invoice_with_attachment`; `('northstar\|veritiv','invoice_with_attachment')` → MISS; flipping DTSS's `doc_type` on the real PDF → `disposition=dead_letter`, 0 fields | **VALID** |
| B2 | `_LINE_TOLERANCE = 3.0` has under 0.6pt of margin on **6 of 10** documents (3.02, 3.06, 3.10, 3.19, 3.24, 3.60) | measured the tightest genuine inter-line gap per document from the real PDFs | **VALID — worse than documented** ("4 of 8") |
| B2b | The constant is **defined twice** — `core/models.py:30` and `grammar/regions.py:36` — with only a comment binding them | grep | **VALID, new** |
| B3 | `pitch = min(pitch, gap)` still live in `_label_block` | read at `grammar/regions.py:480` | **VALID** |
| B4 | Five absolute point constants are font-size dependent (`NEAR_ANCHOR_BELOW 40`, `TOTALS_BAND 80`, `LABEL_BLOCK_MAX 140`, `CELL_GAP 12`, `NEAR_ANCHOR_RIGHT 300`) | read at `grammar/regions.py:36-69` | **VALID** (risk, not a measured failure) |
| B5 | OCR is one document-wide average, so a mixed document is untested: a native invoice (2,343 chars) plus three scanned pages averages ~586 → no OCR, and those pages get role `unknown` | measured per-page char counts: every document is 0 or 500–2,500, never mixed | **VALID** |
| B6 | A persona miss falls to vision, and under the default `--vision cassette` a cassette miss becomes `dead_letter` | observed while verifying B1 | **VALID** |
| C1 | 8 of 10 documents classify on the default branch; 9 ladder branches exist, 2 fire on a real document; `statement_of_account`, DD `credit_memo` and DD `disconnect_notice` have no corpus document, and the last two have no test | probed every ladder branch with synthetic fixtures | **VALID** |
| C4 | 61 failures decompose as **29** fields with no selector declared → empty, **17** where an op produced a wrong value, **15** not field reads | classified every failing assertion against its persona's declared selectors | **VALID** (my split; the docs' 33/14/15 counts categories slightly differently) |
| D1 | mypy covers 3 of 8 packages; `pipeline` and `packs` unchecked | `pyproject.toml:34` | **VALID** |
| D2 | `possible_duplicate_of` is in the contract, type-checked, and never assigned | grep: only declared and copied, never set | **VALID** |
| ~~C2~~ | ~~21 value-keyed selectors, 16 unfixed including DD's `bill_to_name`~~ | **CORRECTED.** Live guardrail state is `LITERAL_PATTERN_DEBT = 0`, `ANCHOR_IN_VALUE_DEBT = 5`. All four DD personas have **no** `bill_to` selector — the roster op supplies it. My earlier claim came from `RESUME.md`, which predates the generalisation-pass commits | **STALE, withdrawn** |
| A4 | **New finding.** 3 of the 5 remaining anchor-in-value debts (`edco`, `veritiv`, `windstream` → `remit_address`) are the direct cause of 3 of the 8 wrong-at-0.99 values: the anchor sits inside its own value, `_apply_field` puts anchor words in `skip`, and `_candidates` drops them — deleting the address's first line | joined the guardrail-9 debt set to the failing assertions at 0.99 | **VALID, new** |

The one genuinely unfixable-by-code item stands: **one invoice per vendor means no generalisation claim is testable.** Task 14 is gated on it.

---

## File Structure

| File | Responsibility | Tasks |
|---|---|---|
| `src/docintel/core/senders.py` | Add `bill_to_matches_roster` — a pure comparison, no context mutation | 1 |
| `src/docintel/grammar/ops/infer.py:243` | Tag a printed bill-to that is not on the roster | 1 |
| `src/docintel/pipeline/stages/s7_gate.py:66` | Add `bill_to_mismatch` to the forced-review tag set | 1 |
| `src/docintel/grammar/regions.py:480` | Median pitch, not min | 2 |
| `src/docintel/extract/normalize.py:106` | Per-page OCR routing | 3 |
| `src/docintel/core/models.py:163` | `text_source` gains `"mixed"` | 3 |
| `src/docintel/core/duplicates.py` | **New.** Within-run identity index | 4 |
| `src/docintel/packs/*/personas/*.json` | Re-anchor 3 `remit_address` selectors | 5 |
| `tests/packs/test_digitaldirection_ladder.py` | Fixtures for the two untested DD branches | 6 |
| `src/docintel/core/geometry.py` | **New.** One `line_tolerance(page)`, replacing both constants | 7 |
| `pyproject.toml:34` | mypy scope | 13 |

---

## Wave 1 — stop the silent failures

These five tasks need no decision from anyone and buy **+3 assertions** between them (Task 5). The other four buy zero, which is exactly why the scorecard would never prioritise them.

### Task 1: A wrong-inbox invoice must not auto-approve

**Files:**
- Modify: `src/docintel/core/senders.py`
- Modify: `src/docintel/grammar/ops/infer.py:243-257`
- Modify: `src/docintel/pipeline/stages/s7_gate.py:66`
- Test: `tests/core/test_senders.py`, `tests/grammar/ops/test_infer.py`, `tests/test_f3_forced_review.py`

**Interfaces:**
- Consumes: `packs.registry.normalize_name`, `Pack.bill_to_roster` (Northstar ships `aliases.BILL_TO_RENDERINGS`; Digital Direction ships `aliases.MANAGED_CLIENTS`)
- Produces: `core.senders.bill_to_matches_roster(printed: str | None, roster: tuple[str, ...]) -> bool`, and the tag string `"bill_to_mismatch"` on `ctx.tags`

- [ ] **Step 1: Write the failing test for the comparison**

```python
# tests/core/test_senders.py
from docintel.core.senders import bill_to_matches_roster

ROSTER = ("Northstar Recycling Company, LLC", "Northstar-Bimbo-Market Street")


def test_a_rendering_variant_still_matches() -> None:
    """One party, many spellings — the variation is the vendors', not the client's."""
    assert bill_to_matches_roster("NORTHSTAR RECYCLING COMPANY LLC", ROSTER)
    assert bill_to_matches_roster("NorthStar Recycling Company, LLC", ROSTER)


def test_a_different_company_does_not_match() -> None:
    assert not bill_to_matches_roster("Contoso Manufacturing Inc", ROSTER)


def test_nothing_printed_is_not_a_mismatch() -> None:
    """An empty bill-to is coverage's problem, not a mismatch. Distinct signals."""
    assert bill_to_matches_roster(None, ROSTER)
    assert bill_to_matches_roster("", ROSTER)


def test_an_empty_roster_never_accuses() -> None:
    """A pack that ships no roster cannot make a mismatch claim about anything."""
    assert bill_to_matches_roster("Anyone At All", ())
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/core/test_senders.py -q`
Expected: FAIL, `ImportError: cannot import name 'bill_to_matches_roster'`

- [ ] **Step 3: Implement the comparison**

```python
# src/docintel/core/senders.py — append
def bill_to_matches_roster(printed: str | None, roster: tuple[str, ...]) -> bool:
    """Whether the printed bill-to is a rendering of a party on the pack's roster.

    True when there is nothing to check: an absent bill-to is `core.coverage`'s
    business (a missing required field), and conflating the two would report one
    problem as the other. An empty roster is also True — a pack that declares no
    parties has made no claim that this document violates.

    Substring in both directions, on normalized names, because renderings differ
    by more than punctuation: a vendor may print `Northstar Recycling` where the
    roster says `Northstar Recycling Company, LLC`, and another may print the
    longer form where the roster holds the short one.
    """
    if not printed or not roster:
        return True
    needle = normalize_name(printed)
    if not needle:
        return True
    return any(
        needle in normalize_name(entry) or normalize_name(entry) in needle
        for entry in roster
    )
```

Add `from docintel.packs.registry import normalize_name` — if that import is circular, move `normalize_name` into `core/senders.py` and have `packs/registry.py` re-export it, so there is still exactly one implementation.

- [ ] **Step 4: Run it and confirm it passes**

Run: `python3 -m pytest tests/core/test_senders.py -q`
Expected: PASS

- [ ] **Step 5: Write the failing test for the tag**

```python
# tests/grammar/ops/test_infer.py — append
def test_a_printed_bill_to_off_the_roster_is_tagged() -> None:
    """The wrong-inbox case. The pack claim is a whole-page substring match, so a
    document that merely MENTIONS the client is claimed; this is what catches it.
    """
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx.extracted["bill_to_name"] = "Contoso Manufacturing Inc"
    ctx = resolve_bill_to_alias(ctx)
    assert "bill_to_mismatch" in ctx.tags
    assert ctx.derived.get("bill_to_basis") == "printed"


def test_a_roster_party_is_not_tagged() -> None:
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx.extracted["bill_to_name"] = "NORTHSTAR RECYCLING COMPANY LLC"
    ctx = resolve_bill_to_alias(ctx)
    assert "bill_to_mismatch" not in ctx.tags


def test_a_roster_supplied_name_is_never_tagged() -> None:
    """Rung 2 read the name OFF the roster, so it cannot disagree with it."""
    ctx = _ctx_with_pack_roster(("Northstar Recycling Company, LLC",))
    ctx = resolve_bill_to_alias(ctx)          # nothing extracted
    assert "bill_to_mismatch" not in ctx.tags
```

Write `_ctx_with_pack_roster` as a local helper building a `new_context` with a stub pack exposing `bill_to_roster`; follow the existing fixture style in that file rather than inventing a new one.

- [ ] **Step 6: Run it and confirm it fails**

Run: `python3 -m pytest tests/grammar/ops/test_infer.py -q -k bill_to`
Expected: FAIL, `assert 'bill_to_mismatch' in []`

- [ ] **Step 7: Tag the mismatch in `resolve_bill_to_alias`**

At `src/docintel/grammar/ops/infer.py:243`, replace the `printed is not None` branch:

```python
    printed = _clean(ctx.extracted.get("bill_to_name"))
    if printed is not None:
        ctx.derived.set("bill_to_basis", "printed")
        party: str | None = printed
        # The pack claim is a substring match over the whole primary page, so a
        # document that merely MENTIONS the client is claimed. Comparing the
        # printed party against the roster is what turns that into a signal
        # instead of a silent auto-approval. Only the PRINTED rung can disagree;
        # rung 2 read the name off the roster itself.
        if not bill_to_matches_roster(printed, _pack_bill_to_roster(ctx)):
            ctx.add_tag("bill_to_mismatch")
            ctx.log(
                f"s6: bill_to_name {printed!r} is not on the pack roster - "
                "this document may have arrived in the wrong inbox"
            )
```

- [ ] **Step 8: Run it and confirm it passes**

Run: `python3 -m pytest tests/grammar/ops/test_infer.py -q -k bill_to`
Expected: PASS

- [ ] **Step 9: Write the failing test that the tag forces review**

```python
# tests/test_f3_forced_review.py — append
def test_a_bill_to_mismatch_forces_review_whatever_the_confidence() -> None:
    """GUARDRAIL 4's sibling: a document billed to somebody else must reach a
    human even when every field extracted at 0.99. Unconditional, like F3.
    """
    ctx = _high_confidence_ctx()
    ctx.add_tag("bill_to_mismatch")
    ctx = Gate().run(ctx)
    assert ctx.review_flag is True
    assert any("bill_to_mismatch" in e for e in ctx.events)
```

- [ ] **Step 10: Run it and confirm it fails**

Run: `python3 -m pytest tests/test_f3_forced_review.py -q -k bill_to`
Expected: FAIL, `assert False is True`

- [ ] **Step 11: Add the tag to the forced set**

At `src/docintel/pipeline/stages/s7_gate.py:66`:

```python
# `flattened_annotations` forces review *unconditionally* ...
# `bill_to_mismatch` joins it for the same reason: the printed bill-to disagrees
# with the pack's roster, which means the pack's claim may be wrong - and a
# confidence score computed under a wrong claim is not evidence of anything.
DEFAULT_FORCED_REVIEW_TAGS: frozenset[str] = frozenset(
    {"has_flattened_annotations", "bill_to_mismatch"}
)
```

- [ ] **Step 12: Run the whole suite and the scorecard**

Run: `python3 -m pytest -q && python3 -m docintel.cli replay-gold`
Expected: all tests pass; **202/263, 1/10 unchanged** — all ten corpus documents are billed to their pack's roster, so no document should gain a tag. If any does, the roster or the comparison is wrong; fix that before committing.

- [ ] **Step 13: Commit**

```bash
git add src/docintel/core/senders.py src/docintel/grammar/ops/infer.py \
        src/docintel/pipeline/stages/s7_gate.py tests/
git commit -m "fix(senders): a printed bill-to off the roster forces review

The pack claim is a substring match over the whole primary page, so an
invoice billed to somebody else that merely mentions the client was
claimed, extracted in full and routed high. Nothing compared the printed
party to the roster - resolve_bill_to_alias preferred print unverified.
Zero cost on the corpus: all ten are billed to their pack's roster."
```

### Task 2: One tight line must not redefine a block's rhythm

> **DEFERRED TO WAVE 2 by human ruling, 2026-07-29 — do not execute in Wave 1.**
> Attempted, proven impossible under this task's own constraints, reverted. Execute
> **after Task 8**, when `LABEL_BLOCK_GAP_FACTOR` and `LABEL_BLOCK_GAP_FLOOR` are in
> play and a full 263-assertion re-baseline is already budgeted. The abandoned patch is
> at `.superpowers/sdd/2026-07-29-weakness-remediation/task-2-abandoned.patch` and the
> full hand-traced diagnosis is in `task-2-report.md`.
>
> **What the attempt proved, measured against the real PDFs:**
>
> 1. **The fix works and the corpus rejects it.** Median pitch fixes the truncation
>    direction (synthetic test RED → GREEN) and moves the scorecard **202 → 200**,
>    turning DTSS — the only fully-correct document — red.
> 2. **Two of the 202 currently pass because of the bug.** `min`'s collapse pins the
>    break threshold near `LABEL_BLOCK_GAP_FLOOR` (24.0), and *that* is what correctly
>    ends two real blocks: DTSS's `vendor_address` at a 48.14pt section gap and
>    Centracom's `charges` ladder at 24.33pt. A genuinely more accurate pitch raises the
>    threshold and both real section breaks stop breaking. This belongs in the
>    "defensible figure" accounting — those two passes are not evidence of correctness.
> 3. **The first gap is not a pitch sample.** On DTSS the label-to-first-content gap is
>    36.0pt against a body pitch of 14.16pt, dragging a two-sample median to 25.08.
>    Excluding it is principled and independent of min-vs-median — but it fixes DTSS
>    only, leaving Centracom regressed at 201/263, so it is not a solution alone.
> 4. **Centracom has no outlier to reject.** Its gaps are 9.92 / 14.0 / 14.0 then 24.33.
>    14.0 *is* the representative pitch, and representative pitch at `FACTOR = 2.0` is
>    simply too permissive to reject a 24.33pt section break. No pitch estimator fixes
>    this. Only a `FACTOR`/`FLOOR` change, or a break signal that is not pitch-based.
>
> Two mitigations were tried and correctly reverted: a minimum-sample gate (structural
> conflict — Centracom needs the gate closed at exactly the sample count the synthetic
> test needs it open) and excluding blank-crossing gaps from the median pool (no effect
> on either regression, and it dropped U-PAK from 12/25 to 11/25).
>
> **Also corrected: this task's own fixture was wrong.** The y-values below (gaps
> 14, 4, 14, 14) cannot reproduce the bug at all — a collapsed pitch of 4 gives
> `max(24, 8) = 24`, and a 14pt gap never exceeds it. A fixture that shows the bug needs
> two ordinary gaps before the outlier so the median has a majority, then a gap above the
> floor but below the uncollapsed threshold: gaps `14, 14, 4, 26, 14`. Use the verified
> version from `task-2-abandoned.patch`, not the snippet below.

**Files:**
- Modify: `src/docintel/grammar/regions.py:476-481`
- Test: `tests/grammar/test_regions.py`

**Interfaces:**
- Consumes: nothing new
- Produces: no API change — `_label_block`'s behaviour only

This is the same bug already fixed for row groups (`26a485d`), still live in `_label_block`. `pitch` starts as the first gap and then only ever shrinks, so one tight line permanently redefines the block's rhythm as that outlier and the *next ordinary* gap exceeds `pitch * LABEL_BLOCK_GAP_FACTOR` and truncates the block.

- [ ] **Step 1: Write the failing test**

```python
# tests/grammar/test_regions.py — append
def test_one_tight_line_does_not_truncate_the_block() -> None:
    """A label block with a normal 14pt rhythm and one 4pt continuation line.

    With `pitch = min(pitch, gap)` the 4pt line redefines the rhythm, so the
    NEXT ordinary 14pt gap reads as a block break and the last line is lost.
    Centracom's vendor_address is this bug's live instance.
    """
    page = _page_from_rows([
        (100.0, "Remit To"),
        (114.0, "CENTRACOM"),
        (118.0, "a continuation line printed tight"),   # 4pt gap
        (132.0, "PO Box 7"),                            # ordinary 14pt gap
        (146.0, "Fairview UT 84629"),
    ])
    block = _label_block(page, _anchor(page, "Remit To"))
    text = " ".join(w.text for w in block[0].words)
    assert "84629" in text, f"the block was truncated: {text!r}"
```

Compute the row arithmetic by hand and check it against the fixture helper's actual behaviour before trusting the comment — standing rule 7 exists because a green test once asserted the opposite of its own docstring.

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/grammar/test_regions.py -q -k tight_line`
Expected: FAIL, the assertion message shows the block ending at `PO Box 7`

- [ ] **Step 3: Replace min with a running median**

```python
        if prev_y is not None:
            gap = y - prev_y
            gaps.append(gap)
            if pitch is None:
                pitch = gap
            elif gap > max(LABEL_BLOCK_GAP_FLOOR, pitch * LABEL_BLOCK_GAP_FACTOR):
                break
            else:
                # Median, not min: `min` let one tight line permanently redefine
                # the block's rhythm, after which the next ORDINARY gap read as a
                # block break. Fixed for row groups in 26a485d; this is the same
                # bug in the other caller.
                pitch = statistics.median(gaps)
```

Declare `gaps: list[float] = []` beside `pitch` and add `import statistics` at the top.

- [ ] **Step 4: Run the test, then the full suite and scorecard**

Run: `python3 -m pytest -q && python3 -m docintel.cli replay-gold`
Expected: the new test passes; **≥202/263**. Centracom's `vendor_address` currently carries a trailing promo line — if it now passes, the count rises; it must not fall.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/grammar/regions.py tests/grammar/test_regions.py
git commit -m "fix(grammar): median pitch in _label_block, not min

The row-group fix in 26a485d left the same bug in the other caller."
```

### Task 3: Decide OCR per page, not per document

**Files:**
- Modify: `src/docintel/extract/normalize.py:106-114`
- Test: `tests/extract/test_normalize.py`

**Interfaces:**
- Consumes: `ocr.ocr_pages(path, page_numbers)` — already takes a page list
- Produces: `load_document` returns `text_source` in `{"native", "ocr"}` — **unchanged**

**ENG REVIEW DECISION (2026-07-29).** A first draft of this task added a third
`text_source` value, `"mixed"`. Three places test `text_source == "ocr"` **exactly** —
`s6_capture.py:73` (the `ocr_source` confidence modifier), `northstar/ladder.py:176`
(the `ocr_only` tag) and `northstar/ladder.py:196` (`_handwritten_supporting`) — so a
`"mixed"` document would have silently skipped the OCR confidence penalty on its
scanned pages. That is the same class of silent confidence inflation Wave 1 exists to
remove, so the value was rejected. **A document with any starved page reports `"ocr"`.**
That is strictly conservative: it errs toward the penalty, the tag and review, never
away from them. Per-page provenance (scoping the penalty to fields actually read off an
OCR'd page) is the correct end state and is logged in the ledger as a C7-era item — it
rewrites confidence scoring, and A1 says there is no calibration evidence to do that
safely yet.

Cache safety, checked: `ocr_cache.cache_key` folds `page_numbers` into the hash, so a
mixed document gets its own entry and the all-scanned path keeps the key it has today.
No existing cached OCR is invalidated by this change.

The corpus is bimodal — every document averages 0 chars/page or 500–2,500 — so the document-wide threshold has never met a mixed document. A native invoice plus three scanned attachment pages averages ~586 chars and takes the native path, leaving those pages wordless; a wordless page gets role `unknown`, so reference matching across attachments (the stated purpose of F10) silently returns nothing.

- [ ] **Step 1: Write the failing test**

```python
# tests/extract/test_normalize.py — append
def test_a_mixed_document_ocrs_only_the_starved_pages(tmp_path) -> None:
    """A native invoice with scanned attachment pages.

    No corpus document has this shape - all ten are 0 chars/page or 500+ - so
    this fixture is synthetic on purpose: corpus-only tests cannot detect the
    gap they do not contain.
    """
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    pages, meta, text_source = load_document(str(path))
    assert [p.source for p in pages] == ["native", "ocr", "ocr", "ocr"]
    assert all(p.words for p in pages), "an OCR'd page must not come back wordless"


def test_any_starved_page_makes_the_document_ocr_sourced(tmp_path) -> None:
    """Deliberately conservative, and it is the reason "mixed" was rejected.

    `s6_capture` applies the `ocr_source` confidence penalty on
    `text_source == "ocr"`, and the Northstar ladder keys `ocr_only` and its
    handwriting check off the same value. A third value would have skipped all
    three on exactly the document whose text we trust least.
    """
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    _, _, text_source = load_document(str(path))
    assert text_source == "ocr"


def test_an_all_native_document_still_reports_native(tmp_path) -> None:
    path = _pdf_with_page_char_counts(tmp_path, [2343, 1800])
    _, _, text_source = load_document(str(path))
    assert text_source == "native"


def test_an_all_scanned_document_still_reports_ocr(tmp_path) -> None:
    path = _pdf_with_page_char_counts(tmp_path, [0, 0])
    _, _, text_source = load_document(str(path))
    assert text_source == "ocr"


def test_only_the_starved_pages_are_sent_to_tesseract(tmp_path, monkeypatch) -> None:
    """The whole point of the change: OCR is the expensive step. A four-page
    document with one native page must OCR three pages, not four.
    """
    seen: list[list[int]] = []
    real = ocr.ocr_pages
    monkeypatch.setattr(ocr, "ocr_pages", lambda p, n: seen.append(n) or real(p, n))
    path = _pdf_with_page_char_counts(tmp_path, [2343, 0, 0, 0])
    load_document(str(path))
    assert seen == [[2, 3, 4]]
```

`_pdf_with_page_char_counts` builds a PDF whose pages carry the given approximate character counts — a scanned page is a page with an image and no text layer. Follow the fixture-building style already in `tests/extract/`.

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/extract/test_normalize.py -q -k mixed`
Expected: FAIL, `assert 'native' == 'mixed'`

- [ ] **Step 3: Route per page**

```python
def _load_document_uncached(path: str) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]:
    meta = pdf.read_meta(path)
    # Per PAGE, not per document. The document-wide average was fitted to a
    # bimodal corpus (every document is 0 chars/page or 500+); a native invoice
    # with three scanned attachment pages averages ~586, took the native path,
    # and left those pages wordless - and a wordless page is role `unknown`, so
    # reference matching across attachments silently found nothing.
    #
    # `text_source` stays a two-valued document summary: ANY starved page makes
    # the document "ocr". Per-page provenance already travels on
    # `PageText.source` and on `Span.source`. A third value would have skipped
    # the `ocr_source` confidence penalty (s6_capture.py:73), the `ocr_only` tag
    # and `_handwritten_supporting` (ladder.py:176,196), all three of which test
    # `== "ocr"` exactly - inflating confidence on precisely the pages whose text
    # we trust least. Conservative on purpose.
    starved = [m.page_number for m in meta if m.char_count < NATIVE_CHAR_THRESHOLD]
    if not starved:
        return pdf.read_pages(path), meta, "native"
    if len(starved) == len(meta):
        return ocr.ocr_pages(path, starved), meta, "ocr"

    native = {p.page_number: p for p in pdf.read_pages(path)}
    ocred = {p.page_number: p for p in ocr.ocr_pages(path, starved)}
    # ENG REVIEW: without this, a short OCR result falls back to the WORDLESS
    # native page - silent data loss on exactly the page this change exists to
    # rescue. A raise here becomes a dead_letter with a reason, which is visible.
    missing = [n for n in starved if n not in ocred]
    if missing:
        raise TransientError(
            f"OCR returned no page for {missing} of {path!r}; "
            "refusing to fall back to a page with no text layer"
        )
    pages = tuple(ocred.get(m.page_number) or native[m.page_number] for m in meta)
    return pages, meta, "ocr"
```

`TransientError` from `docintel.core.errors`, not `PermanentError`: a short OCR result is
most often a tesseract hiccup, and `runner._run_one` already retries `TransientError`
`max_retries + 1` times before routing to the dead-letter queue with the reason on the
record (`runner.py:136-141`). A genuinely un-OCR-able page therefore still ends up as a
visible dead letter — it just gets a couple of attempts first. Add a test that patches
`ocr.ocr_pages` to return a short tuple and asserts the raise, so the fallback can never
silently return.

- [ ] **Step 4: Run the suite and the scorecard**

Run: `python3 -m pytest -q && python3 docs/corpus/validate_gold.py && python3 -m docintel.cli replay-gold`
Expected: all pass; **202/263 unchanged**, and all ten `text_source` assertions still pass — no corpus document is mixed, so none should change value. Gold is read-only; if a gold `text_source` assertion goes red, the routing is wrong, not the label.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/extract/normalize.py tests/extract/test_normalize.py
git commit -m "fix(extract): decide OCR per page, not per document

A native invoice with scanned attachment pages averaged above the
threshold and took the native path, leaving those pages wordless."
```

### Task 4: A permanently-null duplicate field reads as "no duplicates found"

**Files:**
- Create: `src/docintel/core/duplicates.py`
- Modify: `src/docintel/pipeline/runner.py` (index each emitted record)
- Test: `tests/core/test_duplicates.py`

**Interfaces:**
- Consumes: `derived.document_identity` — already computed unconditionally on every record (that is why the printed-fields-only narrowing kept it)
- Produces: `core.duplicates.IdentityIndex` with `see(document_id: str, identity: str | None) -> str | None`, returning the `document_id` first seen with that identity, or `None`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_duplicates.py
from docintel.core.duplicates import IdentityIndex


def test_the_first_sighting_of_an_identity_is_not_a_duplicate() -> None:
    assert IdentityIndex().see("doc-1", "northstar|veritiv|715-33905296") is None


def test_a_second_sighting_names_the_first_document() -> None:
    idx = IdentityIndex()
    idx.see("doc-1", "northstar|veritiv|715-33905296")
    assert idx.see("doc-2", "northstar|veritiv|715-33905296") == "doc-1"


def test_an_unidentifiable_document_is_never_called_a_duplicate() -> None:
    """`document_identity` is None when nothing on the page identified it.

    Two unidentifiable documents are not evidence of the same document twice,
    and saying so would be worse than saying nothing.
    """
    idx = IdentityIndex()
    assert idx.see("doc-1", None) is None
    assert idx.see("doc-2", None) is None


def test_the_same_document_id_twice_is_a_replay_not_a_duplicate() -> None:
    """Re-processing one document must not accuse it of duplicating itself."""
    idx = IdentityIndex()
    idx.see("doc-1", "x")
    assert idx.see("doc-1", "x") is None
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/core/test_duplicates.py -q`
Expected: FAIL, `ModuleNotFoundError: docintel.core.duplicates`

- [ ] **Step 3: Implement the index**

```python
"""Within-run duplicate detection, keyed on `derived.document_identity`.

`possible_duplicate_of` has been in the output contract since C2b, type-checked
by `validate_record`, and never assigned - so every record has reported "no
duplicate" whether or not anything looked. A permanently-null field is worse
than an absent one: it reads as a completed check.

Scope is deliberately ONE RUN. A cross-run index needs the persona store's
database (cluster C7) and a retention policy nobody has decided; claiming
cross-run coverage from an in-memory dict would be the same false completeness
this module exists to remove.
"""

from __future__ import annotations


class IdentityIndex:
    def __init__(self) -> None:
        self._first: dict[str, str] = {}

    def see(self, document_id: str, identity: str | None) -> str | None:
        """The document_id first seen with `identity`, or None.

        None for an unidentifiable document: two documents nothing could
        identify are not evidence of one document twice.
        """
        if identity is None:
            return None
        first = self._first.setdefault(identity, document_id)
        return None if first == document_id else first
```

- [ ] **Step 4: Run it and confirm it passes**

Run: `python3 -m pytest tests/core/test_duplicates.py -q`
Expected: PASS

- [ ] **Step 5: Wire it into the runner and add a whole-path test**

Construct one `IdentityIndex` per `Runner` and, in `_emit`, set `ctx.possible_duplicate_of` before the record is built. Then add to `tests/test_printed_fields_only_path.py`:

```python
def test_the_same_invoice_processed_twice_reports_the_first_document() -> None:
    runner = _runner()
    runner.process(document_id="first", source_path=VERITIV_PDF)
    second = runner.process(document_id="second", source_path=VERITIV_PDF)
    assert second["possible_duplicate_of"] == "first"
```

Standing rule 10: a task that adds a pipeline capability finishes with one whole-path test.

- [ ] **Step 6: Run the suite and the scorecard**

Run: `python3 -m pytest -q && python3 -m docintel.cli replay-gold`
Expected: all pass; **202/263 unchanged** — `replay-gold` processes each document once under a distinct `gold_id`, so nothing should be flagged. If a document flags itself, `document_identity` is not as unique as assumed and that is a finding worth recording in the ledger.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/core/duplicates.py src/docintel/pipeline/runner.py tests/
git commit -m "feat(core): populate possible_duplicate_of within a run

The key was in the contract and never assigned, so every record reported
no duplicate whether or not anything had looked."
```

### Task 5: Three addresses whose anchor deletes their own first line

**Files:**
- Modify: `src/docintel/packs/northstar/personas/edco.json`, `veritiv.json`, `src/docintel/packs/digitaldirection/personas/windstream.json`
- Modify: `tests/packs/test_no_hardcoded_values.py` (shrink `ANCHOR_IN_VALUE_DEBT`)
- Test: the scorecard is the test

**Interfaces:**
- Consumes: existing selector grammar — this is configuration, not code
- Produces: 3 fewer entries in `ANCHOR_IN_VALUE_DEBT`

This is the highest-value task in Wave 1: the same three selectors are simultaneously guardrail-9 debt *and* three of the eight values wrong at 0.99 confidence. `_apply_field` puts the anchor's words in `skip` and `_candidates` drops them, so an anchor on the address's own first line deletes that line — which is why all three return city/state/ZIP with the PO box gone:

```
edco       expected 'P.O. Box 5488, Buena Park, CA 90622-5488'   got 'BUENA PARK, CA 90622-5488'
veritiv    expected 'P.O. Box 409884, Atlanta, GA 30384-9884'    got 'ATLANTA, GA. 30384-9884'
windstream expected 'PO Box 9001908, Louisville, KY 40290-1908'  got 'LOUISVILLE, KY 40290-1908, AAAATTFDFTA'
```

- [ ] **Step 1: Record the exact current failure for all three**

Run: `python3 -m docintel.cli replay-gold --json > /tmp/before.json`
Extract the three `fields.remit_address` entries and keep them — this is the before/after evidence.

- [ ] **Step 2: Read each PDF's remittance block and find a printed label above the address**

For each of the three, find text printed *above* the PO box line to anchor on — `Remit To`, `Make checks payable to`, `Please mail payment to`, or the payee name. The pattern already used elsewhere in this repo (commit `cbe011c`) is exactly this: re-anchor off the value's neighbour, never off the value.

- [ ] **Step 3: Rewrite one selector, re-run, keep or revert**

Change `edco.json` only. Run `python3 -m docintel.cli replay-gold`. The `fields.remit_address` assertion for EDCO must flip FAIL → PASS and the total must rise by exactly 1. If it does not, revert and try a different anchor before touching the next persona — one at a time, so a regression is attributable.

- [ ] **Step 4: Repeat for `veritiv.json`, then `windstream.json`**

Windstream's captured value carries OCR junk (`AAAATTFDFTA`); if re-anchoring alone does not clear it, that is a separate finding — record it and leave the assertion failing rather than adding a cleanup rule that only works on this string.

- [ ] **Step 5: Shrink the debt set**

Remove the three cleared entries from `ANCHOR_IN_VALUE_DEBT` in `tests/packs/test_no_hardcoded_values.py`. The guardrail asserts `DEBT - found == set()`, so a stale entry fails the test — the list can only shrink, which is the point.

- [ ] **Step 6: Verify**

Run: `python3 -m pytest -q && python3 -m docintel.cli replay-gold`
Expected: **205/263** if all three clear; each one that does not must be left failing with a written reason, not forced.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/packs tests/packs/test_no_hardcoded_values.py
git commit -m "fix(packs): re-anchor three remit_address selectors off their neighbour

The anchor sat inside its own value, and _apply_field puts anchor words
in skip - so the anchor deleted the address's first line. All three were
wrong at 0.99 confidence."
```

### Task 6: The two classification branches with no test at all

**Files:**
- Modify: `tests/packs/test_digitaldirection_ladder.py`
- Test: itself

**Interfaces:**
- Consumes: `packs.digitaldirection.ladder.doc_type_for`
- Produces: nothing — coverage only

DD's ladder has three types and only the default has a test. `credit_memo` and `disconnect_notice` have no corpus document *and* no fixture, so nothing would notice if either branch stopped working. `statement_of_account` on the Northstar side is in the same position.

- [ ] **Step 1: Write the tests**

```python
# tests/packs/test_digitaldirection_ladder.py — append
def test_a_credit_memo_title_wins_over_everything() -> None:
    ctx = _ctx(_page("COMCAST BUSINESS|Credit Memo|Billing Account Number 8495|Current Charges 412.00"))
    assert doc_type_for(ctx)[0] == "credit_memo"


def test_suspension_language_without_current_charges_is_a_disconnect_notice() -> None:
    ctx = _ctx(_page("COMCAST BUSINESS|DISCONNECT NOTICE|Billing Account Number 8495|Balance Due 1,204.00"))
    assert doc_type_for(ctx) == ("disconnect_notice", "suspension_without_current_charges")


def test_a_bill_that_merely_warns_about_disconnection_is_still_a_bill() -> None:
    """Both halves of the signal are required. A bill carrying suspension
    language AND a current-charges block is a bill - misclassifying it would
    run the wrong persona's rules, which on Centracom costs $20,123.80.
    """
    ctx = _ctx(_page("COMCAST BUSINESS|Service will be disconnected if unpaid|"
                     "Current Charges 412.00|Billing Account Number 8495"))
    assert doc_type_for(ctx)[0] == "telecom_bill"


def test_an_account_summary_naming_statements_is_still_a_bill() -> None:
    """Centracom's real shape: page 1 titled `Account Summary`, the word
    "statement" printed twice. This pack has no statement type on purpose.
    """
    ctx = _ctx(_page("CENTRACOM|Account Summary|Balance from last statement 1,204.00|"
                     "Current Charges 412.00|Billing Account Number 8495"))
    assert doc_type_for(ctx)[0] == "telecom_bill"
```

Add the matching `statement_of_account` and negative-case tests to `tests/packs/test_northstar_ladder.py`, using that file's existing `_page` / `_ctx` helpers. Note the fixture trap: `_is_own_paperwork` reads only the first 4 lines of page 1, so a filler letterhead is needed above any Northstar bill-to or the wrong branch fires — I hit exactly this while probing.

- [ ] **Step 2: Run them**

Run: `python3 -m pytest tests/packs/ -q`
Expected: PASS on first run — these document existing behaviour rather than driving new code. A failure here is a real bug found, and becomes its own task.

- [ ] **Step 3: Commit**

```bash
git add tests/packs/
git commit -m "test(packs): cover the four untested ladder branches

credit_memo and disconnect_notice had no corpus document and no fixture."
```

---

## Wave 2 — make the geometry survive an unseen sender

Three tasks now, in this order: **7, then 8, then 2.** Each changes measurements every
selector depends on, so each needs a full re-baseline. Do not interleave them with Wave 3.

**Task 2 was moved here from Wave 1** by human ruling after its Wave 1 attempt proved it
cannot be done with `LABEL_BLOCK_GAP_FACTOR` and `LABEL_BLOCK_GAP_FLOOR` frozen. It runs
**last**, because Task 7 changes which words share a line and Task 8 rescales the very
constants Task 2 needs — so its gap arithmetic must be measured against the post-7-and-8
geometry, not today's. Read Task 2's deferral banner above before starting it: it carries
four measured findings, and one of them (two corpus assertions passing only because of
accidental floor-clamping) means **Task 2 may legitimately end at 200/263 with a written
justification rather than at 202.** That is a decision for whoever runs Wave 2, and it is
the one place in this plan where a lower number can be the right answer.

### Task 7: Derive the line tolerance from the page, and define it once

**Files:**
- Create: `src/docintel/core/geometry.py`
- Modify: `src/docintel/core/models.py:30,68-78` (`PageText`), `src/docintel/grammar/regions.py:36,129-141` (`Span`)
- Modify: `src/docintel/extract/normalize.py`, `src/docintel/extract/ocr.py` (compute the tolerance at construction)
- Test: `tests/core/test_geometry.py`

**Interfaces:**
- Produces: `core.geometry.line_tolerance(words: tuple[Word, ...]) -> float` and `core.geometry.group_lines(words: tuple[Word, ...], tolerance: float) -> list[list[Word]]`
- Produces: `PageText.line_tolerance: float` and `Span.line_tolerance: float` — carried, not recomputed

Two findings in one task. **B2:** 6 of 10 documents have their tightest genuine inter-line gap between 3.02 and 3.60pt against a 3.0pt threshold — under 0.6pt of margin, and a tighter document merges two logical lines and corrupts every row and column derived from them. **B2b:** the constant is defined *twice*, in `core/models.py:30` and `grammar/regions.py:36`, bound only by a comment.

**ENG REVIEW CORRECTION (2026-07-29).** The first draft of this task was wrong in two
ways, and both are worth stating because they change the design:

1. **The duplication is worse than a constant.** `PageText.lines()`
   (`core/models.py:68`) and `Span.lines()` (`grammar/regions.py:129`) are the *same
   nine-line grouping algorithm*, copy-pasted, each reading its own module's copy of the
   constant. Fixing the constant alone leaves two implementations free to drift.
2. **`lines()` is not cached and is called 21 times, several inside loops**
   (`executor.py:184,202,261,306,324,528,603`, `regions.py:226,388`). Computing a median
   *inside* `lines()` would add an O(n log n) pass to every one of those calls. The
   tolerance must be computed **once per page, at construction**, and carried as a field.

So this task is now a **de-duplication that happens to fix a threshold**, not an addition.
Net effect: one grouping implementation, one tolerance per page, computed once.

```
BEFORE                                  AFTER
core/models.py                          core/geometry.py
  _LINE_TOLERANCE = 3.0  ──┐              line_tolerance(words) -> float
  PageText.lines()  ───────┼─ same        group_lines(words, tol) -> lines
                           │  algo,            ▲          ▲
grammar/regions.py         │  twice           │          │
  _LINE_TOLERANCE = 3.0  ──┘            PageText     Span
  Span.lines()                          .line_tolerance (a field, set once)
                                        .lines() -> group_lines(words, self.line_tolerance)
```

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_geometry.py
from docintel.core.geometry import line_tolerance


def test_tolerance_scales_with_a_tight_page() -> None:
    """A 6pt-leading page must not use the same tolerance as a 20pt one."""
    tight = _words_at_pitch(6.0)
    loose = _words_at_pitch(20.0)
    assert line_tolerance(tight) < line_tolerance(loose)


def test_tolerance_never_reaches_the_pitch_itself() -> None:
    """A tolerance at or above the pitch merges every line into one."""
    for pitch in (6.0, 12.0, 20.0):
        assert line_tolerance(_words_at_pitch(pitch)) < pitch


def test_no_page_is_grouped_more_loosely_than_today() -> None:
    """3.0 is a CEILING, not a floor. A loose page keeps today's behaviour;
    a tight page is allowed below it, which is the entire fix.
    """
    assert line_tolerance(_words_at_pitch(20.0)) == 3.0
    assert line_tolerance(_words_at_pitch(5.8)) < 3.02


def test_a_single_line_falls_back_to_the_default() -> None:
    """No second baseline, so no pitch to measure."""
    assert line_tolerance(_words_at_pitch(14.0, rows=1)) == 3.0
```

- [ ] **Step 2: Run it and confirm it fails**

Run: `python3 -m pytest tests/core/test_geometry.py -q`
Expected: FAIL, `ModuleNotFoundError`

- [ ] **Step 3: Implement both functions in `core/geometry.py`**

`line_tolerance` is the median of distinct-baseline gaps times a fraction well below 1.0, **capped at today's 3.0** — a *larger* tolerance groups more words onto one line, so the risk this task exists to remove is a tolerance that is too big for a tight page. The cap guarantees no page is grouped more loosely than it is today, while a tight page is free to go *below* 3.0, which is the whole point. `3.0` is also the default when a page has fewer than two distinct baselines and there is no pitch to measure.

**PRE-FLIGHT CORRECTION (2026-07-29):** the first draft of this step said "floored at today's 3.0", which is backwards — a floor would have pinned every tight page at exactly the tolerance that endangers it and delivered none of the fix. Cap, not floor.

Document the fraction against the measurement: corpus median pitch is 5.8–12.4pt and the tightest genuine gaps are 3.02–3.60pt, so the fraction must put a 5.8pt-pitch page below 3.02. `group_lines` is the nine-line algorithm lifted verbatim from `PageText.lines()`, with the tolerance passed in rather than read from a module global.

- [ ] **Step 4: Add the field and delegate both `lines()` implementations**

Add `line_tolerance: float` to `PageText` and to `Span`. `PageText.lines()` and `Span.lines()` both become `return group_lines(self.words, self.line_tolerance)`. A `Span` inherits the tolerance of the page it was cut from — a region is a window onto one page, so recomputing from the window's own words would give a different answer for the same ink. Delete both module-level `_LINE_TOLERANCE` constants so a third copy cannot appear, and replace the seven direct uses in `regions.py` (lines 353, 372, 414, 428, 453, 537) with the page's field.

- [ ] **Step 5: Set the tolerance once, where pages are built**

`PageText` is constructed in exactly two places — `extract/pdf.py` (native) and `extract/ocr.py` (OCR). Both compute `line_tolerance(words)` once at construction. `Span` is constructed in `regions.py::_span`, which already has the page in hand and copies the value across. Assert this in a test: no call site may compute a tolerance per `lines()` call.

```python
def test_the_tolerance_is_computed_once_not_per_lines_call(monkeypatch) -> None:
    """lines() is called 21 times across the grammar, several inside loops.
    Computing the median inside it would add an O(n log n) pass to each one.
    """
    calls = 0
    real = geometry.line_tolerance

    def counted(words):
        nonlocal calls
        calls += 1
        return real(words)

    monkeypatch.setattr(geometry, "line_tolerance", counted)
    page = _page_from_rows([(100.0, "a"), (114.0, "b"), (128.0, "c")])
    before = calls
    for _ in range(5):
        page.lines()
    assert calls == before, "line_tolerance was recomputed inside lines()"
```

- [ ] **Step 6: Re-baseline**

Run: `python3 -m pytest -q && python3 -m mypy && ruff check src tests && python3 -m docintel.cli replay-gold`
Expected: **≥202/263 (or ≥205 if Task 5 landed).** This change moves line grouping on every document; any assertion that flips must be explained in the ledger before committing. A net drop means revert, not adjust. **Re-check Task 5's three `remit_address` assertions specifically** — they are anchored on text whose line membership this change can move.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/core/geometry.py src/docintel/core/models.py \
        src/docintel/grammar/regions.py src/docintel/extract/pdf.py \
        src/docintel/extract/ocr.py tests/core/test_geometry.py
git commit -m "refactor(geometry): one line-grouping implementation, tolerance from pitch

3.0pt absolute left under 0.6pt of margin on 6 of 10 documents. The
constant AND the nine-line grouping algorithm were both duplicated
between core/models.py and grammar/regions.py; now there is one of each,
and the tolerance is computed once per page at construction rather than
inside lines(), which is called 21 times and never cached."
```

### Task 8: Scale the five remaining absolute constants

**Files:**
- Modify: `src/docintel/grammar/regions.py:41-69`
- Test: `tests/grammar/test_regions.py`

- [ ] **Step 1: Write one synthetic test per constant** at 6pt and 20pt leading, asserting the region covers the same number of *lines* at both — that is what each constant is really trying to express (`LABEL_BLOCK_MAX`'s own comment says "~10 lines" while hard-coding 140.0, which assumes 14pt).
- [ ] **Step 2: Run them and confirm they fail at 20pt leading.**
- [ ] **Step 3: Express each as `max(<today's absolute>, pitch × N)`**, mirroring `HEADER_BAND_PITCHES`, so no corpus document narrows.
- [ ] **Step 4: Re-baseline** as in Task 7, Step 5. Expected: **≥ the Wave 2 baseline**.
- [ ] **Step 5: Commit** — `fix(grammar): scale five absolute point constants to line pitch`.

---

## Wave 3 — the decision gates

Each task below is blocked on a business or design call, not on engineering. **Do not start these without an answer recorded in `docs/superpowers/execution/ledger.md`.**

### Task 9: The `doc_type` / persona coupling (B1) — GATE

Verified: the same invoice content gains a boilerplate page 2, `doc_type` flips `standard_invoice` → `invoice_with_attachment`, the persona key misses, and the document dead-letters with 0 of 10 fields.

| Option | Consequence |
|---|---|
| **A. Fall back** in `PackPersonaStore.lookup` (`packs/store.py:41`): try `(fingerprint, doc_type)`, then `(fingerprint, *)`, recording `persona_basis: "doc_type_fallback"` on the record | Recovers extraction when layout is unchanged; risks running a `standard_invoice` persona against a genuinely different shape |
| **B. Decouple the ladder** — make "has supporting pages" a tag, not a type | Cleanest: page roles already restrict where selectors read. But `doc_type` is a gold-asserted field and gold is read-only, so it needs a justified gold change |
| **C. Keep strict** | A page-count change *is* a template change and deserves a human. Safest, most expensive |

First step once decided, for option A: write the failing test asserting `lookup("northstar|veritiv", "invoice_with_attachment")` returns the `standard_invoice` persona *and* that the record says it fell back.

### Task 10: Confidence recalibration (A1) — GATE

Measured: 0.99 band 89% accurate against 0.90's 93%; 13 of 74 configured thresholds sit strictly inside the observed dead band; 3 lanes and 2 review flags are wrong as a direct result. Task 5 removes 3 of the 8 top-band errors, so **re-measure the bands after Wave 1 before designing this.** The gate: recalibrate per-document alongside persona work (where the evidence is), or wire the crosscheck corroboration boosts back on first? The dead band exists because those boosts are unwired.

**Interim, and it needs no decision: no auto-approval threshold below 1.0.** All eight wrong values sit at 0.99.

### Task 11: The payable amount (A3) — GATE

Verified: records carry `total_printed` 33,876.40 (Centracom) and 367.96 (EDCO); `derived.amount_payable` is absent; gold says 13,752.60 and 69.62. Either re-register `derive_amount_payable` **and** un-skip guardrails 2 and 6 in the same commit, or state in the output contract that downstream owns the payable. It is currently neither, which is the problem.

### Task 12: The vision fallback policy (B6) — GATE

A persona miss falls to Stage 5b, and under the default `--vision cassette` a cassette miss becomes `dead_letter`. Decide whether an OCR-sourced document earns a vision second opinion (RESUME's open decision #3). Task 9 reduces how often this path is reached but does not remove it.

---

## Wave 4 — coverage and hygiene

### Task 13: Extend mypy to the pipeline and the packs (D1)

- [ ] **Step 1:** add `"src/docintel/pipeline"` and `"src/docintel/packs"` to `files` in `pyproject.toml:34`.
- [ ] **Step 2:** run `python3 -m mypy` and capture the error count.
- [ ] **Step 3:** fix in per-module commits, smallest module first. Do not add blanket `# type: ignore`; each one that survives needs a reason on the same line.
- [ ] **Step 4:** `python3 -m pytest -q && python3 -m docintel.cli replay-gold` — expected unchanged.

### Task 14: The 29 unwritten selectors (C4) — GATED ON BUSINESS INPUT

29 fields have no selector at all; 46 of 47 failing field values are present in text the pipeline already extracts. Clearing them reaches roughly **248/263 (94%)**. Concentrated: Veritiv alone accounts for 9, and `remit_address` for 7 across documents.

**Do not start this before a second invoice per vendor exists.** Every selector written against a single sample is unverifiable — a rule anchored on a label that appears on the one document we have is indistinguishable from one that reads the page. Writing 29 now adds 29 unfalsifiable rules, which is the debt Wave 1's Task 5 exists to pay down.

**What to ask the business for:** one additional invoice per vendor from a different billing period, and for the telecom client, invoices addressed to *different end customers*. This costs no engineering time and is the highest-value input available.

---

## Eng review: test coverage of every codepath this plan adds

```
CODE PATH COVERAGE
==================================================================
[+] core/senders.py :: bill_to_matches_roster            (Task 1)
    ├── [★★★ PLANNED] variant rendering matches         test_senders.py
    ├── [★★★ PLANNED] different company does not         test_senders.py
    ├── [★★★ PLANNED] nothing printed -> not a mismatch  test_senders.py
    └── [★★★ PLANNED] empty roster never accuses         test_senders.py

[+] grammar/ops/infer.py :: resolve_bill_to_alias        (Task 1)
    ├── [★★★ PLANNED] printed + off-roster  -> tag       test_infer.py
    ├── [★★★ PLANNED] printed + on-roster   -> no tag    test_infer.py
    ├── [★★★ PLANNED] roster-supplied       -> no tag    test_infer.py
    └── [★★  PLANNED] whole path: no corpus doc tagged   replay-gold

[+] s7_gate.py :: forced review                          (Task 1)
    └── [★★★ PLANNED] tag forces review at 0.99          test_f3_forced_review.py

[+] grammar/regions.py :: _label_block pitch             (Task 2)
    ├── [★★★ PLANNED] tight line does not truncate       test_regions.py
    └── [★★  EXISTING] genuine block break still breaks  test_regions.py

[+] extract/normalize.py :: per-page OCR routing         (Task 3)
    ├── [★★★ PLANNED] mixed -> only starved pages OCR'd  test_normalize.py
    ├── [★★★ PLANNED] mixed -> text_source "ocr"         test_normalize.py
    ├── [★★★ PLANNED] all native -> "native"             test_normalize.py
    ├── [★★★ PLANNED] all scanned -> "ocr"               test_normalize.py
    └── [★★★ PLANNED] tesseract sees 3 pages, not 4      test_normalize.py

[+] core/duplicates.py :: IdentityIndex.see              (Task 4)
    ├── [★★★ PLANNED] first sighting -> None             test_duplicates.py
    ├── [★★★ PLANNED] second -> names the first          test_duplicates.py
    ├── [★★★ PLANNED] identity None -> never accused     test_duplicates.py
    ├── [★★★ PLANNED] same doc_id twice -> replay        test_duplicates.py
    └── [★★  PLANNED] whole path: same PDF twice         test_printed_fields_only_path.py

[+] core/geometry.py :: line_tolerance / group_lines     (Task 7)
    ├── [★★★ PLANNED] scales with page pitch             test_geometry.py
    ├── [★★★ PLANNED] never reaches the pitch itself     test_geometry.py
    ├── [★★★ PLANNED] single line -> 3.0 floor           test_geometry.py
    └── [★★★ PLANNED] not recomputed inside lines()      test_geometry.py

[+] packs/*/ladder.py :: untested branches               (Task 6)
    ├── [★★★ PLANNED] DD credit_memo                     test_dd_ladder.py
    ├── [★★★ PLANNED] DD disconnect_notice               test_dd_ladder.py
    ├── [★★★ PLANNED] DD suspension + charges = bill      test_dd_ladder.py
    ├── [★★★ PLANNED] DD account summary = bill           test_dd_ladder.py
    └── [★★★ PLANNED] NS statement_of_account            test_ns_ladder.py

REGRESSION TESTS (mandatory, per the iron rule)
==================================================================
Task 2 changes existing block extraction  -> the tight-line test IS the regression test
Task 3 changes existing OCR routing       -> all-native and all-scanned tests pin
                                             today's behaviour before the new branch
Task 7 changes existing line grouping     -> full 263-assertion re-baseline is the
                                             regression test; per-assertion diff required
──────────────────────────────────────────────────────────────────
PLANNED COVERAGE: 27/27 new paths (100%)     ★★★: 24  ★★: 3  ★: 0
──────────────────────────────────────────────────────────────────
```

No path in this plan is left without a test, and no test is a smoke test. The three `★★` entries are whole-path assertions that depend on the corpus rather than a fixture, which is the correct instrument for them (standing rule 10).

## Eng review: failure modes

| New codepath | Realistic production failure | Test? | Error handling? | Visible? |
|---|---|---|---|---|
| `bill_to_matches_roster` | A legitimate vendor renders the client's name in a way the roster has never seen → false `bill_to_mismatch` → unnecessary review | yes | n/a | **yes** — review flag with the reason code. Fails toward a human, which is the correct direction for this control |
| Per-page OCR | Tesseract fails on one page of a mixed document → `ocr_pages` returns fewer pages than requested → `ocred.get()` misses → the native (wordless) page is used | **no** | **no** | **silent** — **critical gap, see below** |
| `IdentityIndex` | Two genuinely different invoices share a `document_identity` → a real invoice is flagged as a duplicate of another | partially | n/a | yes — the field names the other document, so a human can compare |
| `line_tolerance` | A page with two words on one baseline yields a degenerate median → tolerance collapses | yes (floor test) | yes — floored at 3.0 | yes |
| Forced-review tag | `bill_to_mismatch` added to the forced set but the pack ships no roster → the guard silently never fires | yes (empty-roster test) | n/a | partial — see the note on V13 below |

**CRITICAL GAP, and it gets a step in Task 3.** If `ocr.ocr_pages` returns a short or
empty tuple for a mixed document, `ocred.get(page_number) or native[page_number]` falls
back to the wordless native page with no error and no tag. That is a silent data loss on
the exact page the change exists to rescue. **Task 3 gains a step: assert that every
requested page came back, and raise if not** — the pipeline already turns a stage
exception into a `dead_letter` with a reason, which is visible; a wordless page is not.

**Note on the roster guard's enforcement (P2, confidence 5/10).** The wrong-inbox check
rides on a persona declaring `resolve_bill_to_alias`. All ten personas declare it today,
and dropping it makes V13 complain about `bill_to_name` coverage (`validator.py:455`), so
it is enforced transitively — but only because `bill_to_name` is a required field in both
packs. A future pack where it is not required would lose the guard with nothing failing.
Medium confidence that this matters; recorded in the ledger rather than fixed, because
adding a V-rule for a hypothetical pack is the premature abstraction this plan is trying
to avoid.

## Eng review: what already exists

This plan writes very little new machinery. That is deliberate.

| Sub-problem | Existing code reused | New code |
|---|---|---|
| Force a document to review | `DEFAULT_FORCED_REVIEW_TAGS` + `_forced_reasons` (the F3 path, GUARDRAIL 4) | one tag string |
| Know the pack's roster | `Pack.bill_to_roster`, `_pack_bill_to_roster`, `aliases.BILL_TO_RENDERINGS`, `aliases.MANAGED_CLIENTS` | one comparison function |
| Compare renderings of a name | `packs.registry.normalize_name` | none |
| Median pitch instead of min | the row-group fix in `26a485d` | none — copy the pattern |
| OCR a subset of pages | `ocr.ocr_pages(path, page_numbers)` already takes a page list; `ocr_cache.cache_key` already folds it into the hash | routing only |
| Identify a document | `derive_document_identity`, run unconditionally on every record | a 15-line index |
| Scale a constant to line pitch | `HEADER_BAND_PITCHES`, `LABEL_BLOCK_GAP_FACTOR`, `TABLE_BREAK_FACTOR` | one function |
| Synthetic ladder fixtures | `_page` / `_ctx` helpers in both ladder test files | fixtures only |

Two new modules total (`core/duplicates.py`, `core/geometry.py`), and `geometry.py`
**removes** two duplicated implementations, so the net structural change is one module.

## Eng review: NOT in scope

| Deferred | Why |
|---|---|
| Per-field OCR provenance (scoping the `ocr_source` penalty to fields read off scanned pages) | Correct end state, but it rewrites confidence scoring and A1 says there is no calibration evidence to do that safely yet. Ledger item |
| Cross-run duplicate detection | Needs cluster C7's persona store and a retention policy nobody has decided. Within-run is honest about its scope in the docstring |
| A V-rule requiring `resolve_bill_to_alias` when a pack has a roster | Enforced transitively by V13 today; a rule for a hypothetical future pack is premature |
| Re-enabling derivation (`amount_payable`) | Task 11, decision-gated. Requires un-skipping guardrails 2 and 6 in the same commit |
| Confidence recalibration | Task 10, and its measurement must be re-run after Wave 1 changes three of the eight top-band errors |
| The 29 unwritten selectors | Task 14, gated on a second invoice per vendor. Writing them now adds 29 unfalsifiable rules |
| Vision escalation policy | Task 12, decision-gated |
| A `TODOS.md` file | This repo already has `docs/superpowers/execution/ledger.md` as its deferral register, and standing convention beats a new file |

## Eng review: worktree parallelization

| Task | Modules touched | Depends on |
|---|---|---|
| 1 (bill-to) | `core/`, `grammar/ops/`, `pipeline/stages/` | — |
| 2 (median pitch) | `grammar/` | — |
| 3 (per-page OCR) | `extract/` | — |
| 4 (duplicates) | `core/`, `pipeline/` | — |
| 5 (re-anchor 3 selectors) | `packs/*/personas/` | — |
| 6 (ladder fixtures) | `tests/packs/` | — |
| 7 (geometry) | `core/`, `grammar/`, `extract/` | 2, 3 |
| 8 (scale constants) | `grammar/` | 7 |

```
Lane A:  Task 1 -> Task 4          (sequential, both touch core/ + pipeline/)
Lane B:  Task 2                    (grammar/ only)
Lane C:  Task 3                    (extract/ only)
Lane D:  Task 5 -> Task 6          (config + tests only, no source overlap)
                 |
         ========= merge all four, re-baseline =========
                 |
Lane E:  Task 7 -> Task 8          (touches core/ + grammar/ + extract/: must be alone)
```

Launch A, B, C, D in parallel worktrees. **Conflict flag:** Lane A and Lane E both touch
`core/`; Lane B and Lane E both touch `grammar/`; Lane C and Lane E both touch `extract/`.
Task 7 is a cross-cutting refactor and must not run beside anything. Merge Waves 1's four
lanes, re-baseline, then run Lane E alone.

## Self-Review

**Spec coverage.** Every VALID row in the verification table maps to a task: A1→10, A2→1, A3→11, A4→5, B1→9, B2+B2b→7, B3→2, B4→8, B5→3, B6→12, C1→6, C3→9/12 (the miss path), C4→14, D1→13, D2→4. C2 is withdrawn as stale, with the correction recorded. C3's closed-set sender identity is inherent to a config-driven design and is mitigated, not removed, by Tasks 9 and 12.

**Placeholder scan.** Tasks 1–7 carry runnable code. Tasks 8 and 13 are mechanical repetitions of a pattern established in Task 7 and stated in full. Tasks 9–12 and 14 are explicit decision gates with the options, consequences and first concrete step named — not deferred work described as "TBD".

**Type consistency.** `bill_to_matches_roster(printed, roster) -> bool` is used with that signature in Task 1 Steps 1, 3 and 7. `IdentityIndex.see(document_id, identity) -> str | None` matches across Task 4 Steps 1, 3 and 5. `line_tolerance(words) -> float` is consistent across Task 7 Steps 1, 3 and 4. The tag string is `"bill_to_mismatch"` in all four places it appears.

**Sequencing risk.** Task 5 changes three values currently wrong at 0.99, so Task 10's band measurement must be re-run after Wave 1 — stated in Task 10. Tasks 7 and 8 both move geometry every selector depends on, so each re-baselines independently and neither may be interleaved with Task 14's selector authoring.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 0 | — | — |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES_RESOLVED | 4 issues, 1 critical gap, 2 decisions taken |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | n/a — no UI | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | n/a | — |

**UNRESOLVED:** 0 in Wave 1–2. Four decision gates remain by design in Wave 3 (Tasks 9–12) and one business-input gate in Wave 4 (Task 14).

**VERDICT:** ENG CLEARED for Waves 1 and 2 — 27/27 new codepaths have planned tests, the one critical silent-failure gap is closed with a raise plus a test, and both cross-cutting decisions are recorded in the plan.
