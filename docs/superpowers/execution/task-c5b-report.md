# Cluster C5b — the Digital Direction pack

**Delivers:** the second pack (7 modules), four carrier personas, the claim-gating
fix in the registry, and GUARDRAIL 6.

```
tests     1,242 passing in 7.2s     (1,217 -> 1,242)
mypy      strict, 18 files          0 errors
ruff      src + tests               clean
gold      validate_gold.py          95 checks green
scorecard 0/10 documents, 211/339   (was 130/339)
```

| Document | Before | After |
|---|--:|--:|
| Lumen | 5/39 | 26/39 |
| Centracom | 4/39 | 25/39 |
| Windstream | 4/36 | 25/36 |
| Comcast | 4/38 | 17/38 |
| (the six Northstar documents) | | unchanged |

---

## The headline: Centracom derives correctly

From the pack spec, §7: *"This is the single most important test in the
repository. It is also the one most likely to be 'simplified' away by someone who
notices that `total_printed == current_charges` on three of the four sample
bills."*

```
total_printed    33,876.40     printed in the largest font, AND encoded in the scan line
prior_balance    20,123.80     already net of a 24,120.20 payment
current_charges  13,752.60
carried_balance  20,123.80     NOT 20,123.80 - 24,120.20 = -3,996.40
amount_payable   13,752.60     <- correct
payable_basis    current_charges
closure          20,123.80 + 13,752.60 == 33,876.40  ✓
```

**What makes this worse than EDCO's version of the same trap is that every
corroboration signal points at the wrong number.** 33,876.40 is the biggest
figure on the page, it is what the remittance scan line encodes, and it is what
the stub says to remit. The only evidence for 13,752.60 is the composition.

Pinned by `tests/test_f1_centracom_trap.py` (**GUARDRAIL 6**), including a test
asserting `amount_payable` is *not* in `scanline.CORROBORATABLE_FIELDS` — because
a scan line "confirming" the payable would confirm the wrong number.

---

## The registry bug, and why it mattered

**Every hook in a `HookRegistry` runs on every document.** So registering a
second pack meant Digital Direction's ladder overwrote Northstar's `doc_type`
with `telecom_bill` — after which all six Northstar persona lookups missed by key
and the documents fell back to the vision path.

DTSS dropped from 23 passing assertions to 4. **Nothing failed. No test broke.
Only the scorecard noticed**, and only because I happened to run it.

Pack hooks are now gated on that pack having claimed the document, via a
`_ClaimGatedRegistry` facade in `packs/registry.py`. The gate lives in the
registry rather than in each pack's hooks deliberately: it is a registry
invariant, a pack author should not have to remember it, and a pack that forgot
would break a **different** pack — the worst kind of coupling.

Sockets that fire before Stage 3 (`beforeIntake`, `afterFilter`) are ungated,
because there is no claim to gate on yet.

---

## Design decisions

### This pack claims by the carrier, not the bill-to

Northstar can use a bill-to guard because all six of its documents are billed to
Northstar. Digital Direction is a telecom expense manager whose bills are
addressed to several managed clients — `CLYDE COMPANIES`, `Clyde Administration
Servi`, `City of Dublin`, `Choctaw Travel Mart`. There is no single recipient.

What every one of its documents shares is that the **sender** is a known carrier,
which is the pack's domain by definition. The managed-client list is kept as a
secondary signal, because the pack spec asks for `bill_to_name` to be a guard and
a carrier bill addressed to a non-client is worth flagging.

This is why `claims()` is the pack's own decision rather than a rule the registry
imposes, and `registry.py`'s docstring now says so.

### No `statement_of_account` type, deliberately

Centracom's page 1 is titled `Account Summary` and the word "statement" appears
twice (`Balance from last statement`). A statement signal above the default would
misclassify **the riskiest document in the corpus** and run the wrong persona's
rules (F9). The rule the pack settles on: *a document with a payable amount and
service line items is a bill, whatever its header says.*

### `near-anchor` everywhere, because these layouts are two-column

All four page-1 dumps are two-column layouts flattened into one interleaved line
stream — left-column and right-column lines alternate. `same-row` uses the full
page width and reliably picks up the *other* column:

```
Account Number: 0384043574 Special Circuit Charges 13,611.50
To log in or register, go to https://www.lumen.com/login/. Balance 0.00
131 W MATTHEWS ST. Amount Due $1,230.14
```

`near-anchor` is bounded in x as well as y, so it stays inside the column. Almost
every selector in these four personas uses it.

### `normalize_credit_sign` earns its keep four different ways

The four documents encode a credit four different ways, and one of them has no
marker at all:

```
Comcast     Credit Card Payment Dec 09, 2025 -212.87 cr   minus AND cr
Lumen       Payment Received - Thank You! (249.84)        parens
Windstream  Payments/Adjustments thru 07/18 $1,231.74 CR  trailing CR
Centracom   Payments Received 24,120.20                   NO MARKER AT ALL
```

`parse_money` resolves the first three with an OR rather than negating twice — so
Comcast's `-212.87 cr` does not flip back to positive. Centracom's is why
`normalize_credit_sign` exists: the sign is not on the page, it is in the label.

### The billing-convention table again

`conventions.py` mirrors Northstar's. Centracom is `net_of_payments` and the other
three are `gross`, and nothing on any page states which. Reading Centracom's net
prior as gross subtracts its payment a second time (−3,996.40); reading the other
three's gross prior as net carries a paid-off balance forward.

---

## What is still failing

Same three classes as C5a, plus one new one:

1. **Addresses.** Every gold address is a comma-joined multi-line block and most
   are further from their label than `near-anchor` reaches, or are interleaved
   with the other column.
2. **Vendor names the text layer does not contain.** Lumen's `LUMEN` letterhead is
   an *image* — the token appears zero times in the text layer. Windstream's is
   broken mid-word (`Kinetic Business by Windstre am`). Neither can be captured
   exactly by any pattern.
3. **`charges` row groups.** Centracom's charges are a summary block with no table
   header, so `table_anchor: "This Month"` finds the section but the column grid
   has nothing to build from.
4. **`reference_list` and `carrier_canonical`** need a Digital Direction
   `references.py` and an alias-output field, neither of which C5b built.

The extraction that matters works on all four: totals, priors, payments, current
charges, identity, and the F1 derivation.

---

## Notes for whoever continues

- **The corpus is 211/339 and 0/10 green.** No document is fully clean. The
  closest are DTSS (23/24, one address) and Windstream (25/36).
- The remaining gap is dominated by **addresses and vendor names**, which are
  formatting and text-layer problems rather than extraction logic. A region
  between `near-anchor` and `header-block` — say `label-block`, the anchor's
  column from the anchor line down to the next blank line — would close most of
  the address failures in one change.
- C6 (vision adapter with cassettes) and C7 (SQLite persona store) remain, and
  neither is on the critical path for the score.
