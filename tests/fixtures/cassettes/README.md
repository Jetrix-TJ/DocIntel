# Vision cassettes

A cassette holds what a vision model actually said about a real document, keyed by
that document's content. Replaying one exercises the whole vision path — request
parsing, `policy` sanitizing, Stage 5b capture, Stage 6 pricing — deterministically,
offline, with no API key. That is what lets `replay-gold` stay an objective function
once vision is in the loop.

`corpus.json` is the default (`--vision cassette`). It is currently **empty**, which
is the honest state: no live call has been recorded, because no API key exists in
this environment yet.

## Format

A flat JSON object, `key -> entry`:

```json
{
  "3f2a9c1d55e0b7aa": {
    "provenance": "recorded",
    "model": "claude-opus-5",
    "document": "Complete_Beverage_32930.pdf",
    "field_names": ["vendor_name", "invoice_number", "invoice_date", "total_printed"],
    "field_hints": {"total_printed": "labelled \"Total Amount Due\", in the totals box"},
    "fields": {"total_printed": "1,177.70"},
    "confidence": {"total_printed": 0.82},
    "irregularities": ["handwriting_detected"]
  }
}
```

The key is `sha256(version || source bytes || field names || field hints)`,
truncated — see `CassetteVision.key`. Hints only enter the hash when a call
actually passes them, so a cassette recorded with none still keys the same way
it always did. It follows the **document's content**, not its path, so a
cassette survives the corpus directory moving and goes stale (as a loud miss)
the moment the PDF itself changes.

`provenance` is the field to read first:

| Value | Meaning |
|---|---|
| `recorded` | A real model produced this. Replaying it is evidence. |
| `authored` | A human wrote the expected output by hand. Replaying it is **not** evidence. |

## Why `authored` entries are kept out of `corpus.json`

The implementation plan proposed hand-authoring cassettes for Complete Beverage and
Federal Recycling from their gold files, so `replay-gold` could reach 10/10 before a
key existed. That would work mechanically and it would corrupt the only instrument
this project trusts: the gold answer would be fed in as the model's answer and then
scored against the gold answer. A green run would mean nothing, and — worse — it
would *look* like it meant something.

`test_cassette_provenance.py` therefore fails if `corpus.json` gains an `authored`
entry. Authoring one is still allowed; it just cannot be done silently. Author it,
change that test, and write down why — the same rule the gold files live under.

## Recording a real one

```sh
export ANTHROPIC_API_KEY=...            # or: ant auth login
pip install 'docintel[vision]'
python3 -m docintel.cli process --vision record docs/<document>.pdf
```

`record` calls the API and writes the result into the cassette; every later run
replays it. Use `--vision live` to call without recording, and `--cassette PATH` to
write somewhere other than the default.

Note that a document only reaches Stage 5b when it has no persona or its cached
rules collapsed (`s5b_vision.COLLAPSE_THRESHOLD`). All ten corpus documents
currently extract through `5a_cached`, so recording against them needs the trigger
widened first — a separate decision, deliberately not made here.
