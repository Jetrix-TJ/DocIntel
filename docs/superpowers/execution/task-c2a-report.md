# Cluster C2a — the grammar's closed vocabularies and the validator

**Delivers:** `schema.py`, `patterns.py`, `regions.py`, `validator.py` (V1–V13).
**Does not deliver:** `executor.py` and the four contract keys — those are C2b.

Executed inline in the controller session rather than by a dispatched implementer
(the session forbade subagent use). No fix rounds were needed; the three defects
found came out of a self-review pass before the commit and are listed below.

```
tests     503 passing in 7.6s   (275 before + 228 new grammar tests)
mypy      python3 -m mypy       -> 0 errors, 12 source files, strict
ruff      ruff check src tests  -> clean
gold      validate_gold.py      -> 95 checks green
scorecard 0/10 documents, 39/223 assertions   (UNCHANGED, as predicted)
```

The scorecard is unchanged on purpose and this was checked, not assumed (standing
rule 3). C2a adds a *validator*, not an extraction capability: nothing it produces
is observable in a Stage 8 record, so there is no new assertion for the scorecard
to carry. The rule is satisfied by that reasoning, not by an exemption. The first
real scorecard movement is still C3.

---

## Design decisions

### `Span`, and why regions do not return `PageText`

A region resolver returns `tuple[Span, ...]`, where `Span` is a new frozen type
carrying `page_number`, `source`, `words` and the region's own `bbox`, plus
`lines()`/`text` helpers mirroring `PageText`.

The cheaper option was to return trimmed `PageText` objects — zero new types, and
`lines()`/`text` for free. Rejected because it fabricates a `PageText` whose word
set is not the page's while its `width`/`height` still describe the page, and it
throws away the region bbox that a captured field wants for provenance. `Span`
also keeps `source` attached, so the executor can apply `ocr_source` without
re-deriving where text came from.

**The tuple order is the search order.** `totals-block` returns the last page
*before* page 1, because U-PAK's payable is on page 5 of 5 while page 1's
`Please Pay` cell is blank (F9). Searching page 1 first finds the empty cell and
reports a confident miss. There is a test that pins the order, not just the hit.

### `Anchor`, discovered mid-test

The resolver signature is uniform — `(pages, meta, anchor) -> tuple[Span, ...]` —
with a single `RESOLVERS` dict and one call site in the executor. Writing the
"a table anchor on page 3 must not resolve against page 1" test exposed that a
bare `Word` cannot express which page it was found on, and `Word` is a frozen
contract owned by `core.models`. Hence `Anchor(word, page_number)`: the page is
part of the *location*, not context the caller supplies separately.

`ANCHOR_REQUIRED` turned out to be **five** regions, not the three the spec's
prose implies: `near-anchor`, `same-row`, `same-cell`, plus `line_items` and
`last-table-row`, both of which are defined relative to a table header row and
have nothing to resolve against without it.

### Regions are pure geometry

Section 7 forbids taking field values off a `supporting` page, and that rule is
deliberately **not** applied in `regions.py`. Reference-pattern matching must run
across every page and uses these same resolvers, so `any-page` really does mean
every page. Filtering on `PageMeta.role` belongs to the executor, which is the
only layer that knows whether it is capturing a field or a reference. There is a
test asserting `any-page` does *not* filter, so a later "fix" cannot quietly
break reference matching.

### V5 read as "region is always required"

Section 1.1 makes `region` "required unless the anchor is provably unique".
Anchor uniqueness is a property of a *document*, not of a persona, so it cannot
be established at write time. The honest static rule is that `region` is always
required — a persona with a genuinely unique anchor loses nothing by naming
`any-page` explicitly, and gains a reviewable statement of intent.

### V6's bare-digit test

`_literal_alnum` walks the pattern skipping escapes, character classes,
quantifier braces and group prefixes, leaving only genuinely printed text
context. Bare-digit = *references digits* AND *has no literal alnum context*.

`(\d{3}-\d{4})` counts as bare: a dash is not context, and that pattern is
indistinguishable from a phone number (F11). `NS\s?#\s?(\d{7})` is not bare. The
rule never fires on named patterns — `integer` on `any-page` is a judgement call
about precision, not a grammar violation.

### The nested-quantifier rejection

Section 3.2 rejects unbounded quantifiers. That is not sufficient:
`(?:a{0,20}){0,20}` is bounded at every level and still exponential. Static
bounds alone do not buy linear time, so `compile_restricted` also rejects a
quantifier nested inside a quantified group rather than leaving it for the
runtime timeout to absorb.

Check order inside `compile_restricted` is load-bearing: length before structure
(so a 250-char pattern reports the length), and backreferences independently of
the capture count (`(a)\1` is *within* the 1-capture budget and still forbidden).

### `BASE_ADJUST_OPS` lives here, implementations do not

The 23 op names from §4.1–4.4 are enumerated in `schema.py` so V2 can reject an
unregistered op today. C3 supplies the callables. Splitting it this way means an
agent cannot invent an op in the window before C3 lands.

---

## Two spec errata

**1. §3.2's linear-time engine is not implementable as written.** It specifies
"RE2 / `regex` with backtracking disabled". The `regex` module has no
backtracking-disabled mode, and true RE2 means a new binary dependency
(`google-re2`). Built on stdlib `re` plus the static restrictions, with the 50 ms
per-field runtime budget (C2b) as the second half of the guarantee. Surfaced to
the user, who left it as-is. **If a linear-time guarantee is later required in
earnest, `google-re2` is the change, and it is not a drop-in — RE2 rejects
lookahead, which §3.2 permits.**

**2. §9's worked example violates §1.3.** The EDCO persona asserts
`invoice_account` in its scanline; §1.3 permits only `total_printed`,
`account_number`, `invoice_number`, `due_date`. §1.3 is normative and
load-bearing — it is what stops the F1 bug being cemented through F7 — while §9's
field naming is illustrative and already diverges from the Northstar pack
elsewhere (`invoice_account` vs `vendor_account_number`, `bill_date` vs
`invoice_date`). Read as a typo for `account_number`. §9's persona is reproduced
as a validator test with that one correction, so the grammar is pinned against
the spec's own worked example.

---

## Tightening applied beyond the plan

§1.3 writes the scanline's region as its own narrower enum
(`last-page | page:1 | remittance-block`) than the §2 vocabulary. The first draft
accepted any known region there. Tightened to `{last-page, remittance-block}` plus
any `page:N`, because an OCR-A remittance line is a physical feature of the payment
stub — a persona claiming one in a `header-block` describes something that cannot
exist — and the spec's whole position is that closed vocabularies are rejected at
write time. `page:N` generalizes §1.3's literal `page:1`: a five-page bill's stub
is on page five, and a single named page is exactly as narrow as page one.

---

## Defects found in self-review, before the commit

1. **`same-cell` test passed for the wrong reason.** The fixture helper gives each
   character 6pt, so `BALANCE` ended at x=142 and `FORWARD` at x=165 was a 23pt
   gap — a genuine column gap, not the 5pt the comment claimed. The test was
   asserting that a two-word cell splits. Fixture corrected to match its stated
   intent; `CELL_GAP` left at 12pt.
2. **A V6 test used an anchor-relative region with no anchor.** `same-row` was
   picked as the "narrowing region" example; the new anchor-presence check
   correctly rejected it. The check is right, the test was careless. Split into
   two tests, one with the anchor supplied and one asserting the rejection.
3. **A test's name contradicted its body.**
   `test_V4_rejects_an_unknown_pattern_name_as_a_regex` asserted the opposite —
   that `currancy` is *accepted* as a literal regex. Renamed to
   `..._treats_...`, and the docstring now states the real limitation plainly:
   the grammar cannot distinguish a typo'd pattern name from a deliberate
   literal matcher (`BALANCE FORWARD` is exactly that shape and is legitimate),
   so what catches this is the eval attached to a persona write, not V4.

Also fixed: a `TypeError` leak in V12 when `source_tags` was neither a string nor
a sequence. The boundary must raise `ValidationError` or nothing.

---

## Anti-overfit coverage (standing rule 2)

Corpus-only tests confirm corpus-fit and cannot detect corpus-overfit, so every
test file separates the two and the synthetic half covers notations the ten
documents do not contain but a real invoice plainly could:

- `phone` — the corpus shows only `416-675-3700`; `(416) 675-3700`,
  `416.675.3700` and `1-416-675-3700` are tested.
- `account_number` — dashed (`041-069-076`) and alphanumeric (`5-QXH7QKM7`)
  forms, so normalization does not strip letters and collide identities.
- `integer` — `1,07` must not read as `107`; it is a mis-OCR'd group.
- `date` — `13/45/2025` must not silently become a January date.
- `postal_code` — `4378107` must not read as a zip (F11).
- `compile_restricted` — every unbounded form (`.+`, `\d*`, `a{2,}`, `[a-z]*`,
  `(?:ab)+`), not just the `.*` the plan names.
- `totals-block` — a synthetic cover-page case, and a one-page document where
  last-page and page 1 coincide and must not be searched twice.
- `page:N` beyond the document's length — an empty result, not a crash, because a
  fingerprint drift that shortens a bill is a field miss.

---

## Notes for C2b

- `regions.Span` is the executor's input surface. Search order is carried by
  tuple order — do not sort or set-ify resolver output.
- `PageMeta.role` filtering for field capture is C2b's to add, and there is a
  test in `test_regions.py` asserting regions do *not* do it.
- `patterns.resolve(pattern)` returns a callable for either pattern kind, so the
  executor never has to ask which kind it is holding.
- The 50 ms per-field timeout is unimplemented. `pattern_timeout` (×0.50) exists
  in the modifier enum with nothing emitting it yet.
- `validate_persona` runs on the raw mapping and `parse_persona` on an
  already-validated one. Keep that order; `parse_persona` does not re-check
  vocabularies and is not a boundary.
- Still outstanding and unchanged: the four contract keys (`line_items`,
  `charges`, `scanline`, `sub_account`). **10/10 green before they land does not
  mean the corpus is satisfied.**
