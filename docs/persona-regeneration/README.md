# Blind persona regeneration

One folder per corpus document. Each contains the PDF, an empty persona
skeleton, and an instructions file. Run the instructions in a fresh session —
one document per session — and each produces a `persona.json` authored without
sight of the expected answers. The folders are named by lookup key rather than by
vendor, because the vendor's printed name is itself a graded field.

## Why the reference copies are redacted

The pack specs and the grammar doc print the expected invoice numbers, totals,
doc types and routing lanes for these very documents. A first trial run of this
exercise was contaminated exactly that way: the author read the pack spec as
instructed and three of its extracted values were sitting in a table on that
page. The copies in `reference/` have every corpus answer replaced with `···`,
and every line that discusses a specific corpus document removed. What remains
is the grammar and the pack contract, which is what a rule author legitimately
has.

## Layout

```
reference/
  selector-grammar.md          redacted copy of the grammar spec
  pack-northstar.md            redacted copy of the AP-invoice pack contract
  pack-digitaldirection.md     redacted copy of the telecom pack contract
  vocabulary-northstar.md      legal regions/patterns/ops/fields, generated from code
  vocabulary-digitaldirection.md
  persona-skeleton.json        the output format
  try_persona.py               run a candidate persona, see what it extracts
01-dtss/ … 10-lumen/
  document.pdf                 the PDF, renamed — the original filenames are
                               human annotations that give the answer away
  persona-skeleton.json        local copy of the format
  meta.json                    fingerprint and pack for this document
  INSTRUCTIONS.md              the brief to run
  persona.json                 ← what the run produces
```

## Running one

Start a fresh session at the repository root and give it the instructions file,
e.g. `docs/persona-regeneration/01-dtss/INSTRUCTIONS.md`. Keep sessions separate:
an author who has seen another document's answers is no longer blind, because
several of these documents are billed to the same customer.

## Checking the results

Hand the produced `persona.json` files back. Scoring compares each against the
hand-labelled corpus and against the persona we currently ship, on three
questions: does it extract the same values, does it pass the same assertions,
and where the two differ, which one is reading the page and which one is
restating an answer.

## Document index

| Folder | Pack |
|---|---|
| `01-dtss` | `northstar` |
| `02-veritiv` | `northstar` |
| `03-complete-beverage` | `northstar` |
| `04-federal-recycling` | `northstar` |
| `05-upak` | `northstar` |
| `06-edco` | `northstar` |
| `07-centracom` | `digitaldirection` |
| `08-comcast` | `digitaldirection` |
| `09-windstream` | `digitaldirection` |
| `10-lumen` | `digitaldirection` |
