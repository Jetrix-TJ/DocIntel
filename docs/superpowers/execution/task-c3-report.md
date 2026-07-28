# Cluster C3 — adjust ops, capture, and the F1 machinery

**Delivers:** the 23 `adjust` ops, an unconditional `derive_document_identity`, a
real Stage 6, the carried-over `validate_record` identity requirement, and
`tests/test_f1_antiregression.py`.

Executed inline. No fix rounds. One defect and two measurement findings, below.

```
tests     994 passing in 7.9s      (558 -> 994; 436 new)
mypy      strict, 18 files         0 errors
ruff      src + tests              clean
gold      validate_gold.py         95 checks green
scorecard 0/10 documents, 39/252 assertions   (was 39/242)
```

**The score did not move, and the plan predicted it would.** The plan's "Score
after: some `derived.*`" was optimistic: every op in this cluster only runs when a
persona declares it in `adjust`, and no personas exist until C5. U-PAK's two
`derived` assertions already passed before C3 (its gold expects `null`, and a
`.get` on an absent key also returns `None`), so there was nothing for C3 to win.
Verified rather than assumed: the per-document pass counts are unchanged.

The +10 in the denominator is the `lane` assertion — see finding 2.

---

## The F1 rule, and one correction to the spec

What is payable is the *current* charges whenever a balance is genuinely carried
forward, and the *printed total* when nothing is. Deciding which needs to know
what the printed prior balance means, and that differs by vendor (F1b):

| `prior_balance_basis` | Carried balance is |
|---|---|
| `gross` | `prior_balance + payments_credits` — the payment is inside the prior |
| `net_of_payments` | `prior_balance` exactly as printed |
| absent | **undeterminable**: review flag, never a default |

There is no safe default because the two wrong answers fail in opposite
directions: guessing `gross` double-subtracts on Centracom, guessing
`net_of_payments` carries a paid-off balance forward on Comcast.

**Spec correction.** §4.2 words the closure check as
`prior_balance + current_charges != total_printed`. That predates F1b and is only
correct for `net_of_payments`. Measured across all five corpus documents that
print a prior balance:

```
Centracom  20123.80 + 13752.60 == 33876.40   net_of_payments   (carried == prior)
EDCO         298.34 +    69.62 ==   367.96   gross, no payment
Comcast        0.00 +   221.11 ==   221.11   gross, payment clears it
Lumen          0.00 +   248.09 ==   248.09   gross, payment clears it
Windstream     0.00 +  1230.14 ==  1230.14   gross, payment clears it
```

Against the **raw prior**, Comcast reads `212.87 + 221.11 = 433.98` against a
printed `221.11` — a false mismatch on a completely correct extraction. The check
is therefore written against the carried balance, which reduces to the spec's
wording in the `net_of_payments` case. Pinned by
`test_closure_is_checked_against_the_carried_balance_not_the_raw_prior`.

### Three ways `derive_amount_payable` refuses

Each is a real document, not a defensive hypothetical:

1. **Two printed payables that disagree** — U-PAK prints `14,789.77` as its total
   and `14,740.85` as `Please Pay`, aging columns all zero, nothing on the page
   explaining the 48.92 (F8).
2. **A prior balance whose basis is undeterminable.**
3. **Arithmetic that does not close** — `carried + current != printed`.

All three set `amount_payable` and `payable_basis` to `None` *explicitly* rather
than leaving them absent, so a consumer can distinguish "we looked and could not
decide" from "this pipeline never tried". U-PAK's gold label has exactly that
shape.

The tolerance is `0.01` — a rounding allowance, not a fudge factor. There is a
test asserting two cents is *not* absorbed, because U-PAK's 48.92 must never be.

---

## Design decisions

### Two op shapes, one closed enum

§4 describes two genuinely different kinds of work, so there are two registries:

- `base.VALUE_OPS: dict[str, Callable[[Any], Any]]` — §4.1, transforms one
  field's value; which field comes from the selector that declared it.
- `OPS: dict[str, Callable[[JobContext], JobContext]]` — §4.2–4.4, reasons across
  fields.

`ALL_OP_NAMES` is the union, and `tests/grammar/ops/test_registry.py` asserts it
equals `schema.BASE_ADJUST_OPS` **in both directions**. Either drift is a silent
failure: declared-but-unimplemented means the validator accepts a persona and
Stage 6 quietly skips the op, so a document is scored as if a cross-check passed
when nothing ran; implemented-but-undeclared means the op is unreachable.

### Op order is pinned, not the persona's

`ops.ORDER` fixes the dependency order and `ops.ordered()` sorts a persona's
requested ops into it. A persona listing `derive_amount_payable` before
`resolve_carried_balance` would otherwise read a `carried_balance` that did not
exist yet and fall back to the printed total — **the F1 bug, reachable purely by
how a persona happened to be written.** There is a test that lists the three ops
backwards and asserts Centracom still comes out at 13752.60.

Value ops *do* run in declaration order, because there the composition is the
author's intent (`collapse_internal_spaces` then `uppercase`).

### `derive_document_identity` is not an adjust op

The plan's carried-over requirement says `validate_record` must require
`document_identity` / `identity_basis` on processed records — but the plan lists
no op that produces them. Rather than adding a 24th name to a closed enum §4 does
not contain, identity derivation is an **unconditional Stage 6 step**. A persona
must not be able to opt out of something the contract requires by omitting a name.
`test_document_identity_is_not_an_adjust_op` pins that.

The ladder, measured against gold:

1. `invoice_number` → basis `invoice_number` (Lumen: `752233001`)
2. account number **normalized** + `|` + period → basis `account_period`
3. neither → both keys set to `None`

Rung 2's normalization is the whole point of F6: Comcast prints
`8495 44 462 0365242` and its gold identity is `8495444620365242`. A key built
from the printed form would not join against the same account written unspaced,
which is exactly the failure F6 describes.

### The identity requirement demands presence, not a value

This looked like a sequencing problem — the plan schedules the requirement in C3,
but nothing extracts until C5, so a non-null requirement would dead-letter all ten
documents and destroy the loop's signal for two clusters.

It resolves cleanly: **presence** is required, `None` is a valid value.
`derive_document_identity` always sets both keys, using `None` for "looked and
could not build one" — materially different from "never tried", and the only one
of the two a reviewer can act on. Demanding non-null would also break
`count(intaken) == count(emitted)`, since a document whose identity cannot be
built still has to be emitted and routed.

### Cross-checks score, derivations decide

§4.3 ops may never change a value; there is a registry-wide test asserting it for
all six. `derive_amount_payable` *refuses* on bad arithmetic because it has to
decide a number; `crosscheck_balance_composition` *scores* the same arithmetic
because confidence is a separate question from correctness. Both are in §4 and
both are needed.

Boosts apply **after** modifiers and are capped, so corroboration cannot lift an
OCR'd field back to the confidence of a native-text one — three agreeing
renderings of an OCR'd number can still all be wrong the same way.

### Two vendors, two total compositions

Measured, and no single formula covers both:

```
U-PAK    subtotal 8119.44 + charges 6670.33               == 14789.77
         (its 2325.69 H.S.T. is already inside those parts)
Veritiv  subtotal 4608.45 +                  tax 299.55   ==  4908.00
```

`crosscheck_total_composition` therefore tries every plausible decomposition and
boosts if **any** closes, flagging only when none does. Picking one formula would
false-flag whichever vendor did not use it, and a false mismatch on a correct
extraction is worse than a missed corroboration — it trains reviewers to ignore
the flag.

### `crosscheck_line_sum` and the EDCO trap

C2b's report warned that EDCO's statement table prints its own
`CURRENT CHARGES:` summary row *inside* the table body, so its amount columns sum
to 805.54 against a printed total of 367.96 — faithfully transcribed, not an error.

The op turns out to be safe by construction: it requires a printed `subtotal`, and
EDCO prints none. Only Veritiv (4608.45, closes exactly) exercises it in the
corpus. There is a test asserting EDCO is *skipped* rather than flagged, so a
future change that loosens the subtotal requirement fails loudly.

### `infer_currency` stops short on purpose

Nine of the ten corpus documents are USD and resolve to **nothing** here. That is
correct, not a gap: "most invoices are USD" is a *pack policy*, not something the
document says, so the rung that supplies it is `pack_default` and packs arrive in
C5. Only U-PAK is CAD and it says so via its H.S.T. line, which is rung 2.

VAT is deliberately not a currency signal — it spans the UK and the whole euro
area, so inferring either would be a guess wearing a basis.

---

## Defect found during the run

**A fixture that was arithmetically impossible.** My synthetic partially-paid case
used prior 500 `gross`, payments −400, current 100 and printed 600. The carried
balance is 100, so `100 + 100 != 600` and `derive_amount_payable` correctly
refused — the test was asserting a payable the arithmetic forbids. Printed total
corrected to 200, with the arithmetic spelled out in the docstring.

This is standing rule 7 landing a second time, from the other direction: in C2a
the bad fixtures made tests *pass* for the wrong reason; here one made a correct
implementation look broken.

---

## Finding 1 — `lane` was never asserted (fixed)

All ten gold files specify `expected_routing.lane` and the scorecard asserted only
`review_flag` and `regen_flag`. The lane **is** the routing decision, so a
scorecard that checks the two booleans but not which lane a document landed in
cannot tell a correctly-routed document from a wrongly-routed one — the same
blind-spot class as the tags / `reference_list` / `page_roles` gaps before it.

Now asserted (+10, all failing, since `s7_gate` is still a stub). Implementing it
is C4's; **measuring it starts now so C4 has a visible target rather than an
unstated one.**

## Finding 2 — 68 hand-written gold assertions are ignored (NOT fixed)

Every gold file carries an `assertions` array the scorecard **never reads**. 68
entries across 55 distinct `check` names, of which **37 carry a machine-checkable
`equals`**:

```
entry shape                        count
check + equals                         7
check + equals + expr                 17
check + equals + expr + note          12*
check + note (prose only)             31
                                    ---
machine-checkable                     37
```

Example, from EDCO:

```jsonc
{"check": "balance_composition", "expr": "298.34 + 69.62", "equals": 367.96}
{"check": "amount_payable", "equals": 69.62,
 "note": "NOT 367.96 - this is the whole point of the document"}
{"check": "scanline_agrees_with_printed_total", "equals": 367.96}
```

Some duplicate coverage the scorecard already has (`amount_payable`,
`payable_basis`, `line_sum`). Several do not, and they are precisely C3's output:
`balance_composition` (5 documents), `total_composition` (2),
`current_charges_composition`, `duplicate_anchor_agrees` (2),
`scanline_agrees_with_printed_total`, `filename_crosscheck`, `currency_inferred`,
`arith_balance_mismatch_applied`.

**Underneath it is a bigger gap: `confidence_modifiers` is not asserted at all.**
The entire §5 modifier mechanism — 16 modifiers, of which C3 emits 8 — is
unmeasured. Nothing in the scorecard would notice if `arith_balance_mismatch`
stopped being applied.

This is the same class of miss standing rule 3 was written for, and it means
**10/10 green still does not fully mean the corpus is satisfied** — the caveat C2b
discharged for the four contract keys reappears here for modifiers and routing.

Not fixed in C3 because it is a real piece of work with its own design questions
(the `expr` strings need evaluating or ignoring; 55 `check` names map to record
locations non-uniformly; ~18 of the 31 prose-only entries are about C4/C5
capabilities), and doing it inside C3 would have been an unreviewed scope
expansion. **Recommendation: a small C3b before C4**, wiring the 37 `equals`
entries plus a `confidence_modifiers` superset assertion. Estimated 150–250 src
lines, mostly a check-name → getter table.

---

## Notes for C4

- `lane` is now asserted for all ten documents and all ten fail. That is C4's
  scoreboard.
- `s7_gate` still does not read `ctx.tags`. `flattened_annotations` is applied as
  a *modifier* by Stage 6 now, but §5 says it must also force review
  unconditionally — that wiring is C4's, and Federal Recycling cannot reach its
  gold routing until it lands.
- `ctx.review_flag` is already set by `derive_amount_payable` (on all three
  refusals) and by `crosscheck_balance_composition` and
  `crosscheck_duplicate_anchor`. C4's gate should treat it as an input it may
  raise but must never clear.
- `ctx.boosts` is new on `JobContext`: per-field corroboration counts, applied
  after modifiers and capped.
- `confidence["amount_payable"]` is inherited from whichever field
  `payable_basis` names. A refused payable deliberately gets no confidence entry —
  there is no number to be confident about.
