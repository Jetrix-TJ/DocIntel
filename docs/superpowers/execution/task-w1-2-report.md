# Task 2 report: One tight line must not redefine a block's rhythm

## Status: BLOCKED

The fix specified in the brief (Step 3, applied verbatim) fixes the truncation
bug it targets and passes a verified synthetic test, but it **regresses the
gold scorecard from 202/263 (1/10 green) to 200/263 (0/10 green)**. I could
not find a variant that fixes the truncation direction without reopening the
swallowing direction on two real corpus documents. Per the brief's own
guardrail ("a net drop means the change is wrong, not the baseline") I have
**not committed** this change. Reporting for a decision.

## What I implemented

`src/docintel/grammar/regions.py`, `_label_block` (around line 456-489):
added `import statistics`, a `gaps: list[float] = []` accumulator beside
`pitch`, and replaced `pitch = min(pitch, gap)` with `pitch =
statistics.median(gaps)` — exactly the Step 3 code in the brief, verbatim,
including its comment.

`tests/grammar/test_regions.py`: added
`test_one_tight_line_does_not_truncate_the_block` (see "Fixture verification"
below for why the y-values differ from the brief's literal snippet).

## Substitutions from the brief's snippet (as flagged as likely necessary)

The brief's Step 1 snippet uses helpers `_page_from_rows` and calls
`_label_block(page, _anchor(page, "Remit To"))` directly. Neither exists in
this file. The real helpers (confirmed by reading the existing 60+ tests in
`tests/grammar/test_regions.py`) are:

- `_page(number, *("text", x0, y0), ...) -> PageText` — words as `(text, x0,
  y0)` triples, not `(y0, text)` pairs.
- `_anchor(text, x0, y0, page_number=1) -> Anchor`
- `resolve("label-block")((p,), _meta(p), _anchor(...))` — the region is
  invoked through the public `resolve()` dispatcher, not by calling
  `_label_block` directly.

I used these throughout.

## Fixture verification (standing rule 7)

The brief's literal row y-values (100, 114, 118, 132, 146 → gaps 14, 4, 14,
14) do **not** reproduce the bug given the actual constants
(`LABEL_BLOCK_GAP_FLOOR = 24.0`, `LABEL_BLOCK_GAP_FACTOR = 2.0`). I verified
this by hand and then by running it: with a collapsed pitch of 4, the break
threshold is `max(24, 4*2) = 24` (floor-dominated); with the true pitch of 14
uncollapsed, the threshold is `max(24, 14*2) = 28`. A 14pt gap never exceeds
either threshold, so neither the buggy nor the fixed code would ever break on
these numbers — the fixture as literally written cannot show the bug.

I also found that a *two*-gap run-up (one ordinary gap + one outlier) isn't
enough either: `median([14, 4]) = 9.0`, still low enough that `9.0 * 2 = 18 <
24`, so the threshold stays floor-clamped regardless of min vs. median — no
differentiation. A median only "wins" once real samples form a majority.

I therefore built a fixture with **two** ordinary 14pt gaps before the tight
outlier (so the median has a majority to hold onto), then a 26pt gap that is
deliberately chosen to be `> 24` (so the old min-collapsed floor-clamped
threshold breaks on it) but `<= 28` (so the correct median-preserved
threshold does not):

```
("Remit", 30.0, 100.0), ("To", 70.0, 100.0),
("CENTRACOM", 30.0, 114.0),                                     # gap 14
("Attn", 30.0, 128.0), ("Billing", 60.0, 128.0), ("Department", 110.0, 128.0),  # gap 14
("a", 30.0, 132.0), ("continuation", ...), ("tight", ...),      # gap 4
("PO", 30.0, 158.0), ("Box", 55.0, 158.0), ("7", 90.0, 158.0),  # gap 26
("Fairview", 30.0, 172.0), ("UT", 90.0, 172.0), ("84629", 120.0, 172.0),  # gap 14
```

Measured gaps (by subtraction, then confirmed by print/run): 14, 14, 4, 26,
14. I printed `resolve("label-block")` output directly against the
unmodified (buggy) and modified (fixed) source to confirm these numbers
actually produce the claimed truncation and the claimed fix — see TDD
evidence below.

## TDD Evidence

**RED** — ran the new test against the original (unfixed) `_label_block` via
`git stash`:

```
$ git stash push -- src/docintel/grammar/regions.py
$ python3 -m pytest tests/grammar/test_regions.py -q -k tight_line
...
E       AssertionError: the block was truncated: 'Remit To\nCENTRACOM\nAttn Billing Department\na continuation line printed tight'
E       assert '84629' in 'Remit To\nCENTRACOM\nAttn Billing Department\na continuation line printed tight'
1 failed, 63 deselected in 0.09s
$ git stash pop
```

This is exactly the failure the brief predicted: the block ends at the tight
continuation line, losing `PO Box 7` and `Fairview UT 84629` entirely (the
`break` exits the whole loop, so nothing after it is ever appended).

**GREEN** — same test, fixed source:

```
$ python3 -m pytest tests/grammar/test_regions.py -q -k tight_line
.                                                                        [100%]
1 passed, 63 deselected in 0.02s
```

Full region suite: `python3 -m pytest tests/grammar/test_regions.py -q` → `64
passed`.

Full suite: `python3 -m pytest -q` → `1485 passed, 12 skipped`.
`python3 -m mypy` → `Success: no issues found in 26 source files`.
`ruff check src tests` → `All checks passed!`.
`python3 docs/corpus/validate_gold.py` → `95 checks run, 0 failures`.

All of the above are clean. The problem is the scorecard.

## Scorecard: before → after

```
BEFORE (baseline, unmodified regions.py): assertions_passed=202, assertions_total=263, documents_passed=1
AFTER  (brief's Step 3 fix applied):      assertions_passed=200, assertions_total=263, documents_passed=0
```

Two assertions flip from pass to fail; none flip from fail to pass (Centracom's
`vendor_address`, the case named in the brief as the one that might clear,
does **not** clear — see root cause below, it is a different failure mode
than the one the fix addresses):

**1. `digitaldirection-centracom-0384043574` / `charges`**
```
expected: [['Internet Charges','140.9'], ['Internet Taxes, Surcharges, & Fees','0.2'], ['Special Circuit Charges','13611.5']]
before:   matches expected
after:    [['Internet Charges','140.9'], ['Internet Taxes, Surcharges, & Fees','0.2'], ['Previous Balance','20123.8'], ['Special Circuit Charges','13611.5']]
```
An extra bogus row, `Previous Balance 20123.8`, is now captured.

**2. `northstar-dtss-6060` / `fields.vendor_address`** (this was the corpus's
only green document; it is now red)
```
expected: "500 North Defiance Trail, Spencerville, OH 45887"
before:   matches expected
after:    "500 North Defiance Trail, Spencerville, OH 45887, Bill To, Northstar Recycling Company, LLC, P.O. Box 188, East Longmeadow, MA 01028"
```
The vendor address block now swallows the entire `Bill To` block beneath it.

## Root cause of the regression (why median, held to the brief's exact
constants, cannot both fix the bug and avoid this)

Both regressions are the **swallowing** direction of exactly the failure mode
26a485d's own commit message calls out as the *other* possible failure ("Gold
contains the SWALLOWING direction of the bug... this is the TRUNCATING
direction"). Fixing the truncating direction here reopens the swallowing one,
because `_label_block`'s window is genuinely two-column-porous by design (the
"column gutter NOT applied" comment a few lines below is load-bearing), so
real address blocks pick up sparse single-word "bleed" lines from the other
column at small, irregular gaps.

Traced by hand and independently confirmed by re-implementing the loop
outside the source and running it directly against the real PDFs
(`docs/Centracom_..._BILL.pdf`, `docs/_AP Invoice 6060DTSS...pdf`):

- **DTSS**: gaps are 36.0 (label line → first address line), 14.16 (street →
  city), then 48.14 (address → the next label's `Bill To`, correctly a block
  end). With `min`, pitch collapses to 14.16 after the second gap, giving
  threshold `max(24, 14.16*2) = 28.32` — 48.14 breaks correctly (today's
  passing behaviour). With `median([36, 14.16]) = 25.08`, threshold becomes
  `max(24, 25.08*2) = 50.16` — 48.14 no longer exceeds it. The median of only
  two samples is dragged up by the very first (label-to-content) gap, which
  is characteristically larger than the body's own line pitch and is not
  representative of it.

- **Centracom `charges`**: gaps are 9.92, 14.0, 14.0 (three genuine row
  gaps), then 24.33 (a gap that legitimately crosses a tolerated blank row
  into `Previous Balance`, which should NOT be part of this ladder). With
  `min`, pitch settles at 9.92 (simply the smallest of three genuine,
  non-outlier row gaps), giving a floor-clamped threshold of 24 — 24.33 just
  barely breaks it (today's passing behaviour, essentially by luck of which
  row happened to be tightest). With `median([9.92, 14, 14]) = 14.0`,
  threshold becomes `max(24, 28) = 28` — 24.33 no longer breaks it. Here
  there is no outlier at all to reject: 14.0 is the *genuinely representative*
  pitch, and it is representative pitch itself, at `FACTOR = 2.0`, that is
  too permissive for this document's actual section break.

I tried two mitigations before concluding this is not solvable within the
brief's constraints (both explored live in the working tree, then reverted
back to the brief's exact code for clean reporting):

1. **Minimum-sample gate** (use `min` until N gaps observed, only then trust
   `median`): traced by hand for N=3 and N=4. Neither value works for all
   three cases simultaneously — Centracom's `charges` needs the gate to still
   be closed at exactly the sample count where my own synthetic test needs it
   open (both reach their decisive gap on the 4th real gap). This is a
   structural conflict, not a tuning problem.

2. **Exclude gaps that cross a tolerated blank row from the median pool**
   (implemented, tested, then reverted): this does not help DTSS or
   Centracom's `charges` at all, because in both cases the corrupting effect
   happens *before* any blank-crossing gap is even reached (DTSS: the skew is
   from the very first non-blank-crossing gap, 36 vs 14.16; Centracom: 14.0 is
   not a corrupted value, it is the honest median of three real samples, and
   it's simply too high for `FACTOR=2.0`/`FLOOR=24` to reject 24.33). Running
   the full scorecard with this variant made things measurably worse (upak
   dropped from 12/25 to 11/25) for no gain on the two known regressions, so
   I reverted it.

Both real regressions ultimately trace to the same fact: `FLOOR = 24` and
`FACTOR = 2.0` were evidently tolerant of `min`'s collapse-to-small-value
behaviour (which happens to keep the effective threshold near the floor for
these two documents), and a genuinely more accurate pitch estimate raises the
effective threshold just enough to let a real section-ending gap through.
The brief states these two constants "already exist and their roles do not
change," which forecloses the change that would resolve this
(re-tuning `LABEL_BLOCK_GAP_FACTOR` down, or adding a break signal unrelated
to pitch) without a fresh decision.

## Scorecard figure

- **Baseline:** 202/263 assertions, 1/10 documents green (`northstar-dtss-6060`).
- **After the brief's fix, verbatim:** 200/263 assertions, 0/10 documents green.
- This is a **regression**, not an improvement — Centracom's `vendor_address`
  (the case named in the brief as the one that might clear) does not clear;
  a *different* field on a *different* document (`charges`) and the corpus's
  only green document (`dtss`, `vendor_address`) both flip to failing.

## Files changed (uncommitted — see Status)

- `src/docintel/grammar/regions.py` — `_label_block`, the brief's Step 3 fix
  verbatim (median pitch, `statistics` import, `gaps` accumulator).
- `tests/grammar/test_regions.py` — new test
  `test_one_tight_line_does_not_truncate_the_block`, with y-values adjusted
  from the brief's literal snippet as described above (documented in the
  test's own docstring).

No commit was made. `git diff` shows both files with the changes described
above; nothing is staged.

## Self-review

- The synthetic test itself is solid: verified by hand and by running
  against both the buggy and fixed code (RED then GREEN), matching standing
  rule 7's requirement not to trust an unverified fixture.
- The source fix is exactly what was specified — no scope creep, no
  unauthorized deviation left in the committed diff (my one exploratory
  deviation was reverted).
- The concern is entirely about the *consequence* of the specified fix on
  real corpus documents, which is empirical and reproducible (`git stash` /
  `git stash pop` toggles it cleanly).

## Issues / concerns — this is the whole point of the report

I need a decision on how to proceed, because the three paths I can see all
require authority I don't have on this task:

1. **Ship the fix anyway, accepting the regression** — contradicts the
   brief's explicit "it must not fall" / "a net drop means the change is
   wrong" guardrail. I did not do this.
2. **Retune `LABEL_BLOCK_GAP_FACTOR` / `LABEL_BLOCK_GAP_FLOOR`** — the brief
   explicitly says these "already exist and their roles do not change." I did
   not do this without sign-off.
3. **Find a fundamentally different termination signal** (e.g., something
   that distinguishes "crossed a blank + landed on unrelated content" from
   "crossed a blank + landed on the block's own continuation" more precisely
   than gap-vs-pitch) — plausible but is materially more design work than a
   one-line estimator swap, and is a scope decision, not mine to make
   unilaterally on this task.

I recommend (1) is rejected outright per the brief's own rule, and a human
decide between (2) and (3), or accept that this particular bug (label-block
truncation from a mid-block tight line) is not fixable in isolation from a
broader look at `LABEL_BLOCK_GAP_FACTOR`/`FLOOR`'s tuning.
