# Author a persona for `05-upak` — blind

You are writing the extraction rule file for one vendor's document. Everything
you need is in this folder or in `../reference/`. Work only from the PDF and the
grammar: the point of this exercise is to find out whether rules written without
sight of the expected answers extract the same data as the rules we already ship.

## Deliverable

One file: **`05-upak/persona.json`**, in the format of
`./persona-skeleton.json`. Nothing else.

## Values you must declare exactly

Declare `sender_fingerprint` as exactly:

```
northstar|upak
```

Stage 4 looks personas up by `(sender_fingerprint, doc_type)`. Get either wrong
and your rules are never executed at all — the document falls through with an
empty record.

`doc_type` is **yours to decide**. The classifier computes it independently from
the document; if your declared value disagrees with what it computes, your
persona is never found. The legal values and the rules that select between them
are in `../reference/vocabulary-northstar.md` and `../reference/pack-northstar.md`.

## Read these

- **`./document.pdf`** — the document itself, and the only source of truth for
  what is printed on the page.
- `./persona-skeleton.json` — the exact output shape, key by key.
- `../reference/selector-grammar.md` — the closed grammar: selector kinds,
  regions, patterns, `adjust` ops, and validation rules V1–V14.
- `../reference/vocabulary-northstar.md` — the legal regions, pattern kinds, adjust
  ops, doc types and field names, generated from the code.
- `../reference/pack-northstar.md` — the pack contract: required fields, rosters,
  alias tables, routing.
- In the repository: `src/docintel/grammar/schema.py`, `validator.py`,
  `regions.py`, `patterns.py` and `ops/` — the real semantics of every region,
  pattern and op. The prose describes them; these define them.

## Do not read — this is the whole point

- `docs/corpus/**` — the hand-labelled expected answers
- `docs/corpus-analysis.md`, `docs/STATUS-SUMMARY.md`, `docs/superpowers/**`
- `tests/**`, `src/docintel/scorecard.py`
- `src/docintel/packs/*/personas/**` — the personas we already ship, including
  the one for this document
- the un-redacted originals `docs/architecture/selector-grammar.md` and
  `docs/packs/*.md` — use the copies in `../reference/`, which have the corpus
  answers removed

Do not run `replay-gold` or any scorecard. Do not infer values from a filename.

If you see prohibited content by accident, say so plainly in your report. A
disclosed leak keeps the result interpretable; a hidden one destroys it.

## How to see the document

From the repository root:

```python
from docintel.extract.normalize import load_document
pages, meta, source = load_document("docs/persona-regeneration/05-upak/document.pdf")
for p in pages:
    print(p.text)
# word-level geometry is on p.words — each word has x0, y0, x1, y1, text
```

Geometry matters more than it looks. Several regions are defined by point
offsets (`NEAR_ANCHOR_LEFT`, `LABEL_BLOCK_GAP_FLOOR` and friends in
`regions.py`); a value can sit a few points outside the band its own label
projects, and then no anchored selector reaches it. Measure before concluding a
field is unreadable.

## How to test what you wrote

```bash
python3 docs/persona-regeneration/reference/try_persona.py 05-upak
```

It validates your persona, runs it against the PDF, and prints every value your
rules read, with confidence and coverage. It never compares anything to the
expected answers — iterate against what is printed on the page, which you can
see, not against a score, which you cannot.

## The rules that matter

1. **Every selector must read a value, never restate one.** A pattern that
   contains the answer is not a rule; it is a transcription that stops working on
   the next document. Validation rule V14 rejects the blatant form. It does not
   catch every form — an alternation with one variable branch slips past it, and
   so does a narrow-looking region on a single-page document. Do not use the
   validator as your conscience.
2. **Never anchor on the customer's name.** The end customer changes; the
   template does not. Anchoring on a party name produces a rule that silently
   returns nothing the day a different customer is billed.
3. **Anchoring on the vendor's own name is a last resort.** Sometimes there is no
   printed label near a letterhead address. If you must, mark the field
   `required: false` and say so in your report.
4. **Assume next month's copy.** Different numbers, different dates, possibly a
   different end customer. A rule that works only on this copy is a defect even
   when it extracts the right value today.
5. **An honest empty field beats a fitted rule.** A missing required field
   escalates the document to review, which is a working safety net. A rule that
   will break silently has no safety net at all. If a field cannot be read
   honestly, leave it out and explain why.
6. **Cover what the document actually supports** — the declared fields that are
   genuinely printed, the line-item table if there is one, and the layout
   fingerprint.

## Report back

1. A table: every field you covered, and the value your selector actually
   extracted.
2. What is visible on the page that you deliberately did not attempt, and why.
3. **Every place you were tempted to hardcode, or had to anchor on something
   vendor- or customer-specific.** Be blunt. This is the most valuable part of
   the report — it is where the grammar's real gaps show up.
4. Confirmation that you read nothing on the prohibited list.
