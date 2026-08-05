"""Run YOUR persona against YOUR document and print what it reads off the page.

    python3 docs/persona-regeneration/reference/try_persona.py 01-dtss

Run it from the repository root. It validates the persona, swaps it into an
in-memory persona store, processes the PDF, and prints every value the rules
extracted, plus per-field confidence and the pack's coverage verdict.

It deliberately does NOT compare anything against the hand-labelled corpus. It
answers "what do my rules read?", never "is that the expected answer?" — that
comparison happens after you hand the persona back, and doing it here would turn
rule authoring into answer fitting, which is the failure mode this whole exercise
exists to measure.
"""
from __future__ import annotations

import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent


def main(folder: str) -> int:
    from docintel.adapters.vision.fake import FakeVision
    from docintel.grammar.schema import parse_persona
    from docintel.grammar.validator import ValidationError, validate_persona
    from docintel.packs.registry import load_packs, register_all
    from docintel.packs.store import PackPersonaStore
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner
    from docintel.pipeline.stages import build_default_stages

    d = HERE.parent / folder
    persona_path = d / "persona.json"
    if not persona_path.exists():
        print(f"no persona yet at {persona_path}")
        return 2
    raw = json.loads(persona_path.read_text())
    meta = json.loads((d / "meta.json").read_text())

    packs = load_packs()
    by_name = {p.name: p for p in packs}
    pack = by_name.get(meta["pack"])

    try:
        validate_persona(raw, pack)
    except ValidationError as exc:
        print(f"REJECTED by the validator:\n  {exc}")
        return 1
    print("validator: accepted")

    hooks = HookRegistry()
    register_all(hooks, packs)
    store = PackPersonaStore(packs)
    persona = parse_persona(raw)
    # Override just this vendor's entry; every other pack behaviour is untouched.
    store._by_key[(persona.sender_fingerprint, persona.doc_type)] = persona
    store._raw[(persona.sender_fingerprint, persona.doc_type)] = raw

    runner = Runner(
        stages=build_default_stages(
            vision=FakeVision(), hooks=hooks, packs=packs, store=store,
        ),
        hooks=hooks,
    )
    record = runner.process(document_id=folder, source_path=str(d / "document.pdf"))

    print(f"\ndoc_type resolved  : {record['doc_type']}")
    print(f"sender_fingerprint : {record['sender_fingerprint']}")
    if record["sender_fingerprint"] != persona.sender_fingerprint:
        print("  !! this does not match your persona — Stage 4 will not find it")
    if record["doc_type"] != persona.doc_type:
        print("  !! the classifier disagrees with your persona's doc_type — it will not be found")
    print(f"text_source        : {record['text_source']}")
    print(f"page_roles         : {record['page_roles']}")

    print("\nfields read off the page:")
    fields = {k: v for k, v in record["fields"].items() if v is not None}
    if not fields:
        print("  (nothing — no selector matched)")
    for k, v in sorted(fields.items()):
        conf = record["confidence"].get(k)
        print(f"  {k:26s} {str(v)[:58]:60s} conf={conf}")

    derived = {k: v for k, v in record["derived"].items() if v is not None}
    if derived:
        print("\nderived (computed by pack ops, not read by your selectors):")
        for k, v in sorted(derived.items()):
            print(f"  {k:26s} {str(v)[:58]}")

    rows = record.get("line_items") or []
    print(f"\nline items: {len(rows)}")
    for r in rows[:15]:
        print(f"  {json.dumps(r, default=str)[:110]}")

    print(f"\ncoverage : {record['extraction_coverage']}")
    print(f"tags     : {record.get('tags')}")
    print(f"lane={record['lane']}  review_flag={record['review_flag']}  "
          f"regen_flag={record['regen_flag']}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        raise SystemExit(2)
    raise SystemExit(main(sys.argv[1]))
