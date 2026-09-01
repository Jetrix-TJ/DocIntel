"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from collections import Counter
from collections.abc import Callable

from docintel.adapters.intake.email import EML_SUFFIX, MSG_SUFFIX, EmailIntake
from docintel.adapters.intake.filesystem import FilesystemIntake
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_pipeline

_EMAIL_SUFFIXES = {EML_SUFFIX, MSG_SUFFIX}

# Where recorded vision calls live by default. Under `tests/fixtures` because a
# cassette IS a fixture: it is checked in, it is what makes a run reproducible, and
# it has no meaning outside a run that replays it.
DEFAULT_CASSETTE = "tests/fixtures/cassettes/corpus.json"

VISION_MODES = ("cassette", "fake", "live", "record")


def _build_vision(mode: str, cassette: str) -> object:
    """The vision adapter for this run.

    `cassette` is the default because it is the only mode that is both real and
    reproducible: it replays what a model actually said, offline, with no key. The
    other three are each deliberately worse in one specific way - `fake` answers
    nothing, `live` answers differently every run and costs money, `record`
    rewrites a checked-in fixture.
    """
    if mode == "fake":
        from docintel.adapters.vision.fake import FakeVision

        return FakeVision()

    from docintel.adapters.vision.cassette import CassetteVision

    if mode == "cassette":
        # inner=None: a replay must not be able to fall through to a live call.
        # That fallthrough is how a "deterministic" run quietly starts billing and
        # stops being reproducible.
        if not os.path.isfile(cassette):
            print(
                f"warning: no cassette found at {cassette!r} - every vision lookup will "
                f"miss. This is expected in a fresh install with no recorded cassette; "
                f"pass --vision fake for a wiring check, or --vision live with "
                f"GEMINI_API_KEY set for a real read.",
                file=sys.stderr,
            )
        return CassetteVision(inner=None, path=cassette, mode="replay")

    from docintel.adapters.vision.gemini_adapter import MODEL, GeminiVision

    live = GeminiVision()
    if mode == "live":
        return live
    return CassetteVision(inner=live, path=cassette, mode="record", model=MODEL)


def _build_runner(args: argparse.Namespace | None = None, *, telemetry: bool = False) -> Runner:
    from docintel.jobs.store import SQLiteJobQueue

    mode = getattr(args, "vision", None) or "cassette"
    cassette = getattr(args, "cassette", None) or DEFAULT_CASSETTE
    # A real queue: `docintel process` is a genuine production entry point, so
    # a hard-miss sender or an unknown prior_balance_basis should land
    # somewhere a reviewer can act on it (see `docintel.jobs.store`,
    # `docintel.webui.app`'s /review routes), not just log a line no one reads.
    # `telemetry` defaults to False here because this same factory backs
    # replay-gold/accuracy-report/eval-gate/eval-vision/draft-gold too, and
    # those must NEVER write to the telemetry log - only `_cmd_process`, a
    # genuine production entry point, opts in by passing `telemetry=True` at
    # its own call site (see `Runner.process()`/`docintel.telemetry`).
    return build_pipeline(
        vision=_build_vision(mode, cassette), jobs=SQLiteJobQueue(), telemetry=telemetry,
    )


def _intake_items(paths: list[str]) -> list[object]:
    """Partition input paths between the two intake sources, then merge.

    A DIRECTORY goes to both - `FilesystemIntake._walk` and `EmailIntake`'s own
    walk each filter independently (documents vs. `.eml`/`.msg`), and the two
    sets never overlap, so nothing is double-counted. A literal FILE path goes
    to exactly one, by its own suffix: a literal `.eml`/`.msg` path handed to
    `FilesystemIntake` would bypass its suffix filter entirely (that filter
    only runs during a directory walk) and get yielded as-is, straight into
    Stage 2, which would reject it AND leave the email itself unwrapped - one
    spurious `skipped` record plus a real one lost, rather than the N
    attachment records it should produce.
    """
    email_paths = [
        p for p in paths
        if os.path.isdir(p) or os.path.splitext(p)[1].lower() in _EMAIL_SUFFIXES
    ]
    filesystem_paths = [
        p for p in paths
        if os.path.isdir(p) or os.path.splitext(p)[1].lower() not in _EMAIL_SUFFIXES
    ]
    return [
        *FilesystemIntake(filesystem_paths).items(),
        *EmailIntake(email_paths).items(),
    ]


def _cmd_process(args: argparse.Namespace) -> int:
    runner = _build_runner(args, telemetry=True)
    dispositions: Counter[str] = Counter()

    for item in _intake_items(args.paths):
        record = runner.process(
            document_id=item.document_id,
            source_path=item.source_path,
            sender_email=item.sender_email,
            email_id=item.email_id,
        )
        dispositions[record["disposition"]] += 1
        if args.json:
            print(json.dumps(record, separators=(",", ":")))
        else:
            print(
                f"{record['disposition']:<12} {record['lane'] or '-':<7} "
                f"{record['doc_type'] or '-':<22} {item.source_path}"
            )

    stats = runner.stats
    if not args.json and dispositions:
        # Exit 0 means "every document emitted", NOT "every document was clean".
        # Without this summary an operator reading only the exit code would take
        # a run full of dead letters for a success.
        summary = ", ".join(f"{n} {d}" for d, n in sorted(dispositions.items()))
        print(f"\n{stats['emitted']} emitted ({summary})")

    if stats["intaken"] != stats["emitted"]:
        print(f"INVARIANT VIOLATED: {stats}", file=sys.stderr)
        return 2
    return 0


def _add_history_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--record-history",
        action="store_true",
        help="persist this run's scorecard into the eval-history store",
    )
    parser.add_argument(
        "--label",
        default="manual",
        help="tag for this run in the history store, e.g. a git sha or 'ci' (default: manual)",
    )
    parser.add_argument(
        "--history-db",
        default=None,
        help="eval-history db path (default: var/eval_history.sqlite3)",
    )


def _maybe_record_history(
    args: argparse.Namespace, suite: str, card: dict
) -> None:
    if not getattr(args, "record_history", False):
        return
    from docintel.evals.history import EvalHistoryStore

    store = EvalHistoryStore(args.history_db) if args.history_db else EvalHistoryStore()
    vision_mode = getattr(args, "vision", None) or "cassette"
    store.record(suite=suite, label=args.label, vision_mode=vision_mode, card=card)


def _print_scorecard(card: dict) -> None:
    for doc in card["documents"]:
        mark = "PASS" if doc["passed"] else "FAIL"
        print(f"{mark}  {doc['gold_id']}  ({doc['passed_count']}/{doc['total_count']})")
    s = card["summary"]
    print(f"\n{s['passed']}/{s['total']} documents green")
    extra = {k: v for k, v in s.items() if k not in {
        "total", "passed", "failed", "assertions_passed", "assertions_total",
    }}
    for name, value in extra.items():
        print(f"{name}: {value}")


def _print_accuracy_report(card: dict, gold_meta: dict[str, tuple[str, str]]) -> None:
    """`replay_gold`'s own numbers, rendered for the non-engineer half of the
    testing cycle standup asked about: "how much accuracy do we get" needs a
    one-command answer, not a raw assertion-count JSON dump. Same scoring, a
    different rendering - grouped by company and by document type (from the
    gold label's own `pack`/`doc_type`, not a new classification), with every
    failing document named alongside exactly which values it got wrong.
    """
    s = card["summary"]
    a_total = s["assertions_total"]
    a_pct = 100 * s["assertions_passed"] / a_total if a_total else 0.0
    print("docintel accuracy report\n")
    print(
        f"  {s['passed']}/{s['total']} documents fully correct, "
        f"{s['assertions_passed']}/{a_total} individual values correct ({a_pct:.1f}%)\n"
    )

    def _bucket(key_fn: Callable[[dict], str]) -> dict[str, list[dict]]:
        buckets: dict[str, list[dict]] = {}
        for doc in card["documents"]:
            buckets.setdefault(key_fn(doc), []).append(doc)
        return buckets

    def _print_bucket(title: str, buckets: dict[str, list[dict]]) -> None:
        print(title)
        for key in sorted(buckets):
            docs = buckets[key]
            passed = sum(1 for d in docs if d["passed"])
            a_passed = sum(d["passed_count"] for d in docs)
            a_tot = sum(d["total_count"] for d in docs)
            print(f"  {key:<24} {passed}/{len(docs)} documents, {a_passed}/{a_tot} values")
        print()

    _print_bucket("By company:", _bucket(lambda d: gold_meta.get(d["gold_id"], ("-", "-"))[0]))
    _print_bucket("By document type:", _bucket(lambda d: gold_meta.get(d["gold_id"], ("-", "-"))[1]))

    failing = [d for d in card["documents"] if not d["passed"]]
    if not failing:
        print("No failing documents.")
        return
    print(f"Failing documents ({len(failing)}):\n")
    for doc in failing:
        print(f"  {doc['gold_id']}  ({doc['passed_count']}/{doc['total_count']})")
        for a in doc["assertions"]:
            if not a["passed"]:
                print(f"    {a['name']}: expected {a['expected']!r}, got {a['actual']!r}")
        print()


def _cmd_accuracy_report(args: argparse.Namespace) -> int:
    from docintel.scorecard import load_gold, replay_gold

    card = replay_gold(runner_factory=lambda: _build_runner(args))
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        gold_meta = {
            g["gold_id"]: (g.get("pack", "-"), g["classification"]["doc_type"])
            for g in load_gold()
        }
        _print_accuracy_report(card, gold_meta)
    return 0 if card["summary"]["failed"] == 0 else 1


def _cmd_replay_gold(args: argparse.Namespace) -> int:
    from docintel.scorecard import replay_gold

    card = replay_gold(runner_factory=lambda: _build_runner(args))
    _maybe_record_history(args, "full_pipeline", card)
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        _print_scorecard(card)
    return 0 if card["summary"]["failed"] == 0 else 1


def _cmd_eval_gate(args: argparse.Namespace) -> int:
    from docintel.evals.gate_eval import replay_gate

    card = replay_gate(runner_factory=lambda: _build_runner(args))
    _maybe_record_history(args, "gate_classifier", card)
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        _print_scorecard(card)
    return 0 if card["summary"]["failed"] == 0 else 1


def _cmd_eval_vision(args: argparse.Namespace) -> int:
    from docintel.evals.vision_eval import replay_vision

    vision = _build_vision(args.vision, args.cassette)
    card = replay_vision(runner_factory=lambda: _build_runner(args), vision=vision)
    _maybe_record_history(args, "vision_one_shot", card)
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        _print_scorecard(card)
    return 0 if card["summary"]["failed"] == 0 else 1


def _cmd_eval_history(args: argparse.Namespace) -> int:
    from docintel.evals.history import EvalHistoryStore

    store = EvalHistoryStore(args.history_db) if args.history_db else EvalHistoryStore()
    runs = store.history(args.suite, limit=args.limit)
    if args.json:
        print(json.dumps([run.to_dict() for run in runs], indent=2))
        return 0
    if not runs:
        print(f"No recorded runs for suite {args.suite!r}.")
        return 0
    for run in runs:
        s = run.summary
        print(
            f"{run.run_at}  #{run.id:<5} {run.label or '-':<20} "
            f"{s['passed']}/{s['total']} docs, "
            f"{s['assertions_passed']}/{s['assertions_total']} assertions"
        )
    return 0


def _cmd_eval_compare(args: argparse.Namespace) -> int:
    """Champion/challenger: exit 1 and name every assertion that regressed
    between two stored eval runs, exit 0 if none did (the candidate may
    freely gain passes). See `docintel.evals.compare` for what counts."""
    from docintel.evals.compare import compare
    from docintel.evals.history import EvalHistoryStore

    store = EvalHistoryStore(args.history_db) if args.history_db else EvalHistoryStore()
    baseline = store.find(args.suite, args.baseline)
    if baseline is None:
        print(
            f"No run found for baseline {args.baseline!r} under suite {args.suite!r}.",
            file=sys.stderr,
        )
        return 1
    candidate = store.find(args.suite, args.candidate)
    if candidate is None:
        print(
            f"No run found for candidate {args.candidate!r} under suite {args.suite!r}.",
            file=sys.stderr,
        )
        return 1

    regressions = compare(baseline, candidate)
    if args.json:
        print(json.dumps([r.__dict__ for r in regressions], indent=2))
    elif not regressions:
        cs, bs = candidate.summary, baseline.summary
        print(
            f"No regressions: candidate {cs['passed']}/{cs['total']} vs. "
            f"baseline {bs['passed']}/{bs['total']}"
        )
    else:
        print(f"{len(regressions)} regression(s):")
        for r in regressions:
            print(f"  {r.gold_id}: {r.assertion} (was passing, now failing)")
    return 0 if not regressions else 1


def _cmd_generate_persona(args: argparse.Namespace) -> int:
    """Draft a field-hint spec for a brand-new company from one PDF - the
    automated half of onboarding (see `docintel.generation.persona_agent`).

    Writes a JSON file to `--out`, unmistakably labelled as a draft, and
    prints what it found so a reviewer can decide immediately whether it's
    usable - never anything the real pipeline reads on its own.
    """
    from docintel.generation.persona_agent import generate_field_hints, write_draft

    try:
        spec = generate_field_hints(args.pdf, company_name=args.company, model=args.model)
    except Exception as exc:  # noqa: BLE001 - report clearly, exit nonzero, don't crash with a traceback
        print(f"generation failed: {exc}", file=sys.stderr)
        return 1

    out_path = args.out or os.path.join("docs", "onboarding", "generated", f"{_slug(args.company)}.hints.json")
    write_draft(spec, out_path, company_name=args.company, source_pdf=args.pdf)

    print(f"DRAFT - not reviewed, do not use in production. Wrote {out_path}\n")
    print(f"{len(spec.fields)} field(s), {len(spec.row_groups)} table(s):\n")
    for f in spec.fields:
        print(f"  {f.name:<26} {f.type:<16} {f.hint}")
    for g in spec.row_groups:
        cols = ", ".join(f"{c.name}:{c.type}" for c in g.columns)
        print(f"\n  [{g.name}] {cols}\n    {g.hint}")
    if spec.notes:
        print(f"\nnotes: {spec.notes}")
    print("\nA human must review this before it informs anything real - see docs/onboarding/CONFIG-SPACE.md.")
    return 0


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")


def _cmd_reconcile(args: argparse.Namespace) -> int:
    """Cross-check already-processed invoices against contracts on file.

    A second pass over records `docintel process --json` already produced -
    not a pipeline stage. Splits the input by `doc_type` into invoices and
    contracts, resolves which contract (if any) governs each invoice, and
    enqueues one finding per invoice into the SAME job queue `docintel serve`
    reads from. Stops there: no payment, no approval, no AP integration.

    `--pending` narrows this to only the invoices a persona's own processing
    profile (`s4b_processing_profile.py`) asked for automatically
    (`reconciliation_pending` jobs, enqueued by `ConfidenceGate` at process
    time) - the real-time counterpart to running this command over everything
    by hand. Each drained job is marked resolved so it is not reconsidered
    next run; a job whose `document_id` is missing from `records` (the JSONL
    given here doesn't cover it) is left open rather than silently dropped.
    """
    from docintel.jobs.store import SQLiteJobQueue
    from docintel.reconciliation import enqueue, evaluate, resolve

    records: list[dict] = []
    with open(args.records) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    contracts = [r for r in records if r.get("doc_type") == "contract"]
    all_invoices = [r for r in records if r.get("doc_type") != "contract"]

    jobs = SQLiteJobQueue(args.jobs_db) if args.jobs_db else SQLiteJobQueue()

    if args.pending:
        by_document_id = {r.get("document_id"): r for r in all_invoices}
        invoices = []
        drained_jobs = []
        for job in jobs.list_open("reconciliation_pending"):
            record = by_document_id.get(job.context.get("document_id"))
            if record is None:
                continue  # not in this batch of records - stays open
            invoices.append(record)
            drained_jobs.append(job)
    else:
        invoices = all_invoices
        drained_jobs = []

    counts: Counter[str] = Counter()
    for invoice in invoices:
        match = resolve(invoice, contracts)
        finding = evaluate(match)
        if finding is None:
            counts["clean"] += 1
            continue
        created = enqueue(finding, jobs)
        counts[finding.kind] += 1
        if not args.json:
            status = "queued" if created else "already open"
            print(
                f"{finding.kind:<28} {invoice.get('document_id', '?'):<24} "
                f"({status})"
            )

    for job in drained_jobs:
        jobs.resolve(job.id, {"note": "reconciliation ran"}, resolved_by="docintel reconcile --pending")

    if args.json:
        print(json.dumps({"invoices": len(invoices), "contracts": len(contracts),
                           "findings": dict(counts), "drained": len(drained_jobs)}, indent=2))
    else:
        print(
            f"\n{len(invoices)} invoices, {len(contracts)} contracts on file, "
            f"{sum(counts.values()) - counts.get('clean', 0)} findings: "
            + ", ".join(f"{n} {k}" for k, n in sorted(counts.items()) if k != "clean")
        )
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """Render already-processed records into a spreadsheet.

    A second pass over `docintel process --json` output, same shape as
    `docintel reconcile`: no in-pipeline state, just a file this command reads
    and a file it writes. `--pending` narrows this to only the records a
    persona's own processing profile asked for automatically
    (`excel_export_pending` jobs, enqueued by `ConfidenceGate` at process
    time) - the real-time counterpart to running this by hand over everything.
    """
    try:
        from docintel.export import write_records_to_xlsx
    except ModuleNotFoundError:
        print(
            "Excel export needs openpyxl, which isn't installed. "
            "Run: pip install 'docintel[export]'",
            file=sys.stderr,
        )
        return 1

    from docintel.jobs.store import SQLiteJobQueue

    records: list[dict] = []
    with open(args.records) as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    jobs = SQLiteJobQueue(args.jobs_db) if args.jobs_db else SQLiteJobQueue()

    if args.pending:
        by_document_id = {r.get("document_id"): r for r in records}
        drained_jobs = [
            job for job in jobs.list_open("excel_export_pending")
            if by_document_id.get(job.context.get("document_id")) is not None
        ]
        # Group by the layout each job actually asked for - a batch may mix
        # personas whose profiles named different layouts.
        by_layout: dict[str, list[dict]] = {}
        for job in drained_jobs:
            layout = job.context.get("layout", "standard")
            by_layout.setdefault(layout, []).append(by_document_id[job.context["document_id"]])
        if not by_layout:
            if args.json:
                print(json.dumps({"written": 0, "layouts": {}}, indent=2))
            else:
                print("no pending excel_export jobs matched this batch of records")
            return 0
        written = {}
        for layout, layout_records in by_layout.items():
            out_path = f"{args.out}.{layout}.xlsx" if len(by_layout) > 1 else args.out
            write_records_to_xlsx(layout_records, out_path, layout=layout)
            written[layout] = {"path": out_path, "records": len(layout_records)}
        for job in drained_jobs:
            jobs.resolve(job.id, {"note": "export written"}, resolved_by="docintel export --pending")
        result = {"written": len(drained_jobs), "layouts": written}
    else:
        write_records_to_xlsx(records, args.out, layout=args.layout)
        result = {"written": len(records), "layouts": {args.layout: {"path": args.out, "records": len(records)}}}

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        for layout, info in result["layouts"].items():
            print(f"{layout:<16} {info['records']:>5} record(s) -> {info['path']}")
    return 0


# Where an escalated webui upload's source bytes are retained - see
# `docintel.webui.app.CORRECTIONS_DIR`. Duplicated as a literal (not imported
# from webui.app) so this command works without the `[ui]` extra installed;
# `docintel process`-originated corrections never need this fallback at all
# since their `source_path` is already a real, durable file.
_RETAINED_CORRECTIONS_DIR = "var/eval_corrections"


def _cmd_new_pack(args: argparse.Namespace) -> int:
    """Scaffold a brand-new company's pack.json + a starter persona - never
    registered anywhere on its own (see `generation.pack_scaffold`'s own
    docstring). Reads a `generate-persona` hint-spec draft's field list, if
    one is given, so a reviewer starts from real field names instead of a
    blank persona.
    """
    from docintel.generation.pack_scaffold import scaffold_pack, scaffold_persona

    hints = None
    if args.hints:
        try:
            with open(args.hints, encoding="utf-8") as fh:
                payload = json.load(fh)
        except (OSError, json.JSONDecodeError) as exc:
            print(f"could not read hints file {args.hints!r}: {exc}", file=sys.stderr)
            return 1
        hints = payload.get("spec", payload)

    out_dir = os.path.join("docs", "onboarding", "generated", args.slug)
    if os.path.exists(out_dir) and not args.force:
        print(f"{out_dir} already exists. Pass --force to overwrite it.", file=sys.stderr)
        return 1

    os.makedirs(os.path.join(out_dir, "personas"), exist_ok=True)

    pack = scaffold_pack(args.company, args.slug, args.doc_type)
    pack_path = os.path.join(out_dir, "pack.json")
    with open(pack_path, "w", encoding="utf-8") as fh:
        json.dump(pack, fh, indent=2)
        fh.write("\n")

    vendor_slug = args.vendor or args.slug
    persona = scaffold_persona(args.slug, vendor_slug, args.doc_type[0], hints=hints)
    persona_path = os.path.join(out_dir, "personas", f"{vendor_slug}.json")
    with open(persona_path, "w", encoding="utf-8") as fh:
        json.dump(persona, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {pack_path}")
    print(f"Wrote {persona_path}\n")
    print(
        "Not registered anywhere - the real pipeline can't see this until a "
        "human reviews it and adds it to registry.PACK_FILES. Next:\n"
        f"  docintel validate-persona {persona_path} --pack-file {pack_path}"
    )
    return 0


def _cmd_validate_persona(args: argparse.Namespace) -> int:
    """A standalone self-check against `grammar.validator.validate_persona`
    (V1-V14) - no new validation logic, just an entry point that doesn't
    require the persona to already be wired into a registered pack first.

    `validate_persona` raises on the FIRST rule it finds broken, not every
    one at once - this command reports that one failure clearly rather than
    claiming to have checked everything past it.
    """
    from docintel.core.errors import ValidationError
    from docintel.grammar.validator import undeclared_risk_fields, validate_persona

    try:
        with open(args.persona, encoding="utf-8") as fh:
            persona = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read {args.persona!r}: {exc}", file=sys.stderr)
        return 1

    pack = None
    if args.pack_file:
        from docintel.packs.datapack import load_pack_file

        try:
            pack = load_pack_file(args.pack_file)
        except Exception as exc:  # noqa: BLE001 - report clearly, exit nonzero, don't crash with a traceback
            print(f"could not load pack file {args.pack_file!r}: {exc}", file=sys.stderr)
            return 1
    elif args.pack:
        from docintel.packs.registry import load_packs

        packs = load_packs()
        pack = next((p for p in packs if p.name == args.pack), None)
        if pack is None:
            names = ", ".join(sorted(p.name for p in packs))
            print(f"no registered pack named {args.pack!r}. Registered packs: {names}", file=sys.stderr)
            return 1

    try:
        validate_persona(persona, pack=pack)
    except ValidationError as exc:
        print(f"INVALID: {exc}", file=sys.stderr)
        return 1

    if pack is not None:
        print(f"OK: {args.persona} is valid against pack {pack.name!r}.")
        risky = undeclared_risk_fields(persona, pack)
        if risky:
            print(
                f"warning: {len(risky)} field(s) can silently disappear - declared by "
                "the pack, not required, no op supplies them, no selector covers them: "
                f"{', '.join(risky)}",
                file=sys.stderr,
            )
    else:
        print(
            f"OK: {args.persona} is structurally valid. "
            "No --pack/--pack-file given, so field-name registration (V1) wasn't checked."
        )
    return 0


def _cmd_draft_gold(args: argparse.Namespace) -> int:
    """Draft a gold fixture from one clean pipeline run - no review-queue
    correction required first (see `docintel.evals.draft_gold`'s own
    docstring for why `promote-correction` can't cover a brand-new company's
    first document at all).
    """
    from docintel.evals.draft_gold import draft_gold_fixture

    if os.path.exists(os.path.join("docs", "corpus", "gold", f"{args.gold_id}.json")) and not args.force:
        print(
            f"docs/corpus/gold/{args.gold_id}.json already exists. Pass --force to overwrite it.",
            file=sys.stderr,
        )
        return 1

    runner = _build_runner(args)
    record = runner.process(document_id=args.gold_id, source_path=args.source)

    fixture = draft_gold_fixture(record, args.gold_id, source_file="")
    dest_dir = os.path.join("docs", "corpus", fixture["pack"])
    os.makedirs(dest_dir, exist_ok=True)
    dest_pdf = os.path.join(dest_dir, f"{args.gold_id}.pdf")
    shutil.copyfile(args.source, dest_pdf)
    fixture["source_file"] = os.path.relpath(dest_pdf, "docs").replace(os.sep, "/")

    gold_dir = os.path.join("docs", "corpus", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    gold_path = os.path.join(gold_dir, f"{args.gold_id}.json")
    with open(gold_path, "w", encoding="utf-8") as fh:
        json.dump(fixture, fh, indent=2)
        fh.write("\n")

    print(f"Wrote {gold_path}\n")
    print(f"disposition: {record['disposition']}, doc_type: {record.get('doc_type')!r}")
    print(f"{len(fixture['fields'])} field(s) auto-filled from this run.")
    print(
        "\nStill needs a human, before this fixture counts toward anything:\n"
        "  - labelled_by, teaches, notes\n"
        "  - expected_routing.review_flag / regen_flag / lane - the whole point of a "
        "gold fixture is an independent answer, not the pipeline grading itself, so "
        "these are never auto-filled. See _draft_pipeline_observed for what the "
        "pipeline currently decided, and confirm or correct it by hand."
    )
    if fixture.get("line_items_complete") is False:
        print("  - line_items_complete - confirm the WHOLE table was captured, not just what fit on one page")
    if fixture.get("reference_list_complete") is False:
        print("  - reference_list_complete - confirm every reference on every page was captured")
    print(
        "\nThen:\n"
        "  python docs/corpus/validate_gold.py\n"
        "  docintel replay-gold --json"
    )
    return 0


def _cmd_promote_correction(args: argparse.Namespace) -> int:
    """Turn one accepted review correction into a real gold fixture.

    Deliberately a separate, human-run command from the webui route that
    *captures* the correction - see `docintel.evals.corrections`'s own
    docstring for why promotion into the scored gold set stays a reviewed
    gate rather than happening automatically the moment a reviewer submits.
    """
    from docintel.evals.corrections import CorrectionStore
    from docintel.evals.promote import build_gold_fixture, corrected_field_diff

    store = (
        CorrectionStore(args.corrections_db) if args.corrections_db else CorrectionStore()
    )
    correction = store.get(args.correction_id)
    if correction is None:
        print(f"No correction #{args.correction_id}.", file=sys.stderr)
        return 1
    if correction.status == "promoted" and not args.force:
        # A re-run must not silently clobber a human's manual follow-up edit
        # to the gold file it already wrote (e.g. filling in
        # expected_routing.lane, which this command's own printed reminder
        # tells them to do by hand) - the same "a silently partial/overwritten
        # gold label is worse than an absent one" posture docs/corpus/
        # README.md already states for this exact directory.
        print(
            f"Correction #{correction.id} was already promoted. "
            "Pass --force to overwrite the gold fixture anyway.",
            file=sys.stderr,
        )
        return 1

    gold_id = args.gold_id or f"correction-{correction.document_id}"

    retained = os.path.join(_RETAINED_CORRECTIONS_DIR, f"{correction.document_id}.pdf")
    source_pdf = retained if os.path.exists(retained) else correction.source_path
    if not os.path.exists(source_pdf):
        print(
            f"No source PDF found for document {correction.document_id!r} "
            f"(checked {retained!r} and {correction.source_path!r}).",
            file=sys.stderr,
        )
        return 1

    fixture = build_gold_fixture(correction, gold_id, source_file="")
    dest_dir = os.path.join("docs", "corpus", fixture["pack"])
    os.makedirs(dest_dir, exist_ok=True)
    dest_pdf = os.path.join(dest_dir, f"{gold_id}.pdf")
    shutil.copyfile(source_pdf, dest_pdf)
    fixture["source_file"] = os.path.relpath(dest_pdf, "docs").replace(os.sep, "/")

    gold_dir = os.path.join("docs", "corpus", "gold")
    os.makedirs(gold_dir, exist_ok=True)
    gold_path = os.path.join(gold_dir, f"{gold_id}.json")
    with open(gold_path, "w") as fh:
        json.dump(fixture, fh, indent=2)

    store.mark_promoted(correction.id)

    print(f"Wrote {gold_path}")
    diff = corrected_field_diff(correction)
    if diff:
        print("\nCorrected (human-verified) fields:")
        for name, (before, after) in sorted(diff.items()):
            print(f"  {name}: {before!r} -> {after!r}")
    untouched = sorted(set(fixture["fields"]) - set(diff))
    if untouched:
        print("\nUntouched fields (only as trustworthy as 'a reviewer did not object'):")
        for name in untouched:
            print(f"  {name}: {fixture['fields'][name]!r}")
    print(
        "\nNext: fill in expected_routing.lane by hand (Stage 7 hadn't run yet "
        "when this snapshot was taken), then run:\n"
        "  python docs/corpus/validate_gold.py\n"
        "  docintel replay-gold --json"
    )
    return 0


def _cmd_queue_status(args: argparse.Namespace) -> int:
    """The honest minimum "alerting" for a single-operator tool: poll this
    from cron/Task Scheduler rather than push-notify, since there's no
    on-call process yet to receive a push (docintel.telemetry's own
    docstring). Exit 1 only when `--fail-if-older-than-hours` is given and
    the oldest open job crosses it - otherwise this command never fails on
    its own, since a nonzero queue depth by itself is normal operation.
    """
    from docintel.jobs.store import SQLiteJobQueue

    jobs = SQLiteJobQueue(args.jobs_db) if args.jobs_db else SQLiteJobQueue()
    open_jobs = jobs.list_open()

    by_kind: Counter[str] = Counter(job.kind for job in open_jobs)
    oldest_created_at = min((job.created_at for job in open_jobs), default=None)
    oldest_age_hours = None
    if oldest_created_at is not None:
        from datetime import UTC, datetime

        age = datetime.now(UTC) - datetime.fromisoformat(oldest_created_at)
        oldest_age_hours = age.total_seconds() / 3600

    if args.json:
        print(json.dumps({
            "total_open": len(open_jobs),
            "by_kind": dict(by_kind),
            "oldest_created_at": oldest_created_at,
            "oldest_age_hours": round(oldest_age_hours, 2) if oldest_age_hours is not None else None,
        }, indent=2))
    else:
        print(f"{len(open_jobs)} open job(s)")
        for kind, count in sorted(by_kind.items()):
            print(f"  {kind}: {count}")
        if oldest_age_hours is not None:
            print(f"oldest open job: {oldest_created_at} ({oldest_age_hours:.1f}h ago)")

    if (
        args.fail_if_older_than_hours is not None
        and oldest_age_hours is not None
        and oldest_age_hours > args.fail_if_older_than_hours
    ):
        print(
            f"OLDEST OPEN JOB IS {oldest_age_hours:.1f}H OLD, over the "
            f"{args.fail_if_older_than_hours}h threshold",
            file=sys.stderr,
        )
        return 1
    return 0


def _cmd_telemetry_report(args: argparse.Namespace) -> int:
    from docintel import telemetry

    result = telemetry.aggregate(path=args.log_path, since_days=args.since_days)
    if args.json:
        print(json.dumps(result, indent=2))
        return 0

    print(f"{result['total']} document(s) logged")
    print(f"dead-letter rate: {result['dead_letter_rate']:.1%}")
    print(f"escalation rate (5b_vision): {result['escalation_rate']:.1%}")
    if result["mean_confidence"] is not None:
        print(f"mean confidence: {result['mean_confidence']:.3f}")
    for disposition, count in sorted(result["dispositions"].items()):
        print(f"  {disposition}: {count}")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the local web UI. Lazy-imports flask: the default install has no
    web dependency, and `docintel process`/`replay-gold` must keep working
    without it. Install with `pip install 'docintel[ui]'` to use this command.
    """
    try:
        from docintel.webui.app import create_app
    except ModuleNotFoundError as exc:
        print(
            "The web UI needs flask, which isn't installed. "
            "Run: pip install 'docintel[ui]'",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    app = create_app()
    url = f"http://127.0.0.1:{args.port}/"
    if not args.no_browser:
        import webbrowser

        webbrowser.open(url)
    print(f"Serving on {url} (Ctrl+C to stop)")
    app.run(host="127.0.0.1", port=args.port, debug=False)
    return 0


def _add_vision_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--vision",
        choices=VISION_MODES,
        default="cassette",
        help=(
            "cassette: replay recorded calls (default; offline, deterministic). "
            "fake: return nothing, for wiring checks. "
            "live: call the API. "
            "record: call the API and write the result into the cassette."
        ),
    )
    parser.add_argument(
        "--cassette",
        default=DEFAULT_CASSETTE,
        help=f"cassette file for --vision cassette/record (default: {DEFAULT_CASSETTE})",
    )


def _load_dotenv_if_available() -> None:
    """Populate `os.environ` from a `.env` file, if `python-dotenv` is
    installed. Lazy and best-effort: `--vision fake`/`--vision cassette` need
    no API key at all, so a dev without the `vision` extra installed must not
    have this fail the CLI on import. `load_dotenv()`'s own default never
    overrides a real, already-exported env var - only fills gaps - so this is
    safe to call unconditionally on every invocation.

    `usecwd=True` on the path lookup, not `load_dotenv()`'s own default search:
    that default walks up from the CALLING FILE's location (this module,
    inside the installed package), which only happens to find a real `.env`
    here because dev runs use an editable install sitting next to the repo
    root. A `docintel` installed to `site-packages` would search upward from
    THAT tree and never find a user's project `.env` at all. A CLI's `.env`
    lives wherever the user invokes it from - `usecwd=True` searches there.
    """
    try:
        from dotenv import find_dotenv, load_dotenv
    except ImportError:
        return
    load_dotenv(find_dotenv(usecwd=True))


def main(argv: list[str] | None = None) -> int:
    _load_dotenv_if_available()
    parser = argparse.ArgumentParser(prog="docintel")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser(
        "process",
        help="run one or more PDFs through the pipeline",
        description=(
            "Exit 0 means every intaken document emitted a record - including "
            "skipped and dead-lettered ones. It does NOT mean every document was "
            "processed cleanly; read the per-document dispositions for that. "
            "Exit 2 means a document was intaken and never emitted, which is a bug."
        ),
    )
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true")
    _add_vision_args(p)
    p.set_defaults(func=_cmd_process)

    g = sub.add_parser("replay-gold", help="run the gold corpus and score it")
    g.add_argument("--json", action="store_true")
    _add_vision_args(g)
    _add_history_args(g)
    g.set_defaults(func=_cmd_replay_gold)

    ar = sub.add_parser(
        "accuracy-report",
        help="a readable, non-engineer summary of gold-corpus accuracy",
        description=(
            "Runs the exact same gold-corpus scoring replay-gold does and renders it "
            "as a short, readable summary instead of a raw assertion dump: percent "
            "correct overall, broken down by company and by document type, and every "
            "failing document named with which values it got wrong. Not a new scoring "
            "mechanism - a different rendering of the same numbers replay-gold --json "
            "already reports."
        ),
    )
    ar.add_argument("--json", action="store_true", help="print the raw scorecard instead")
    _add_vision_args(ar)
    ar.set_defaults(func=_cmd_accuracy_report)

    eh = sub.add_parser("eval-history", help="show the eval score trend over time")
    eh.add_argument("--suite", default="full_pipeline")
    eh.add_argument("--limit", type=int, default=20)
    eh.add_argument("--history-db", default=None)
    eh.add_argument("--json", action="store_true")
    eh.set_defaults(func=_cmd_eval_history)

    eg = sub.add_parser(
        "eval-gate",
        help="score Stage 2/3 (attachment filter + classifier) alone against the gold corpus",
        description=(
            "Runs only intake/attachment_filter/classify against every gold "
            "document and scores doc_type/tags/text_source/disposition - "
            "independent of whether extraction (stages 4+) succeeds at all. "
            "Never builds or validates a full record."
        ),
    )
    eg.add_argument("--json", action="store_true")
    _add_vision_args(eg)
    _add_history_args(eg)
    eg.set_defaults(func=_cmd_eval_gate)

    ev = sub.add_parser(
        "eval-vision",
        help="score Stage 5b (vision one-shot) alone against the gold corpus",
        description=(
            "Runs intake through persona_lookup, then forces a Stage 5b "
            "vision call on every gold document (bypassing the normal "
            "collapse gate) and scores the four default fields it requests. "
            "With --vision cassette this reads real signal only once a real "
            "cassette entry exists (see Bug 5, docs/BUGS-FEATURES-PRODUCTION.md)."
        ),
    )
    ev.add_argument("--json", action="store_true")
    _add_vision_args(ev)
    _add_history_args(ev)
    ev.set_defaults(func=_cmd_eval_vision)

    ec = sub.add_parser(
        "eval-compare",
        help="diff two recorded eval runs; exit 1 and name every regression",
        description=(
            "Champion/challenger: compares two runs already recorded via "
            "--record-history (by numeric id or by label - the latest run "
            "under that label if more than one shares it) and names every "
            "assertion that passed in the baseline and now fails in the "
            "candidate. A candidate may freely gain passes; only a same-"
            "named assertion getting worse counts as a regression."
        ),
    )
    ec.add_argument("baseline", help="a recorded run's id or label")
    ec.add_argument("candidate", help="a recorded run's id or label")
    ec.add_argument("--suite", default="full_pipeline")
    ec.add_argument("--history-db", default=None)
    ec.add_argument("--json", action="store_true")
    ec.set_defaults(func=_cmd_eval_compare)

    r = sub.add_parser(
        "reconcile",
        help="cross-check processed invoices against contracts on file",
        description=(
            "Reads a JSONL file of already-processed records (docintel process "
            "--json output), splits them by doc_type into invoices and "
            "contracts, and enqueues one finding per invoice - no_matching_"
            "contract, rate_mismatch, billed_after_contract_expiry, or "
            "contract_precedence_ambiguous - into the same review queue "
            "docintel serve reads from. Stops there: no payment, no approval."
        ),
    )
    r.add_argument("records", help="a JSONL file of docintel process --json output")
    r.add_argument("--jobs-db", default=None, help="job queue path (default: var/jobs.sqlite3)")
    r.add_argument(
        "--pending", action="store_true",
        help="only drain reconciliation_pending jobs (auto-enqueued for personas whose "
             "processing_profile.reconciliation is 'auto'), instead of every invoice in records",
    )
    r.add_argument("--json", action="store_true")
    r.set_defaults(func=_cmd_reconcile)

    ex = sub.add_parser(
        "export",
        help="render already-processed records into a spreadsheet",
        description=(
            "Reads a JSONL file of already-processed records (docintel process "
            "--json output) and writes an .xlsx file. --layout picks which "
            "registered column layout to use (default: standard). --pending "
            "narrows this to only the records a persona's own processing_"
            "profile.export asked for automatically, one file per layout "
            "actually requested, and marks the underlying jobs resolved."
        ),
    )
    ex.add_argument("records", help="a JSONL file of docintel process --json output")
    ex.add_argument("--out", required=True, help="output .xlsx path")
    ex.add_argument("--layout", default="standard", help="registered export layout (default: standard)")
    ex.add_argument("--jobs-db", default=None, help="job queue path (default: var/jobs.sqlite3)")
    ex.add_argument(
        "--pending", action="store_true",
        help="only drain excel_export_pending jobs, instead of every record in records",
    )
    ex.add_argument("--json", action="store_true")
    ex.set_defaults(func=_cmd_export)

    np = sub.add_parser(
        "new-pack",
        help="scaffold a brand-new company's pack.json + a starter persona",
        description=(
            "Writes docs/onboarding/generated/<slug>/pack.json and "
            "personas/<vendor>.json - never registered anywhere on its own. "
            "--hints, if given, seeds real field names/types from a "
            "generate-persona draft; region/anchor/table_anchor are always "
            "left an explicit placeholder for a human to fill in - selector "
            "geometry doesn't generalize from a blind pass. Next step: "
            "docintel validate-persona --pack-file on the result."
        ),
    )
    np.add_argument("slug", help="the pack's name, e.g. acme_freight")
    np.add_argument("--company", required=True, help="the company's full name")
    np.add_argument(
        "--doc-type", dest="doc_type", action="append", required=True,
        help="a document type this company sends (repeat for more than one)",
    )
    np.add_argument("--vendor", default=None, help="the starter persona's vendor slug (default: same as slug)")
    np.add_argument("--hints", default=None, help="path to a generate-persona hint-spec draft")
    np.add_argument("--force", action="store_true", help="overwrite an existing scaffold")
    np.set_defaults(func=_cmd_new_pack)

    vp = sub.add_parser(
        "validate-persona",
        help="self-check a persona file against grammar.validator's V1-V14 rules",
        description=(
            "Runs grammar.validator.validate_persona against one persona JSON "
            "file, standalone - no need to already have it wired into a "
            "registered pack first. --pack checks it against an already-"
            "registered company (by name); --pack-file checks it against a "
            "draft pack.json that isn't registered yet (e.g. one docintel "
            "new-pack scaffolded). Neither given runs a structural-only check "
            "(no field-name registration check, V1)."
        ),
    )
    vp.add_argument("persona", help="path to a persona JSON file")
    vp_pack = vp.add_mutually_exclusive_group()
    vp_pack.add_argument("--pack", default=None, help="an already-registered pack's name")
    vp_pack.add_argument("--pack-file", default=None, help="path to a draft, unregistered pack.json")
    vp.set_defaults(func=_cmd_validate_persona)

    dg = sub.add_parser(
        "draft-gold",
        help="draft a docs/corpus/gold fixture from one clean pipeline run - no review correction needed first",
        description=(
            "Runs one document through the real pipeline and writes a "
            "docs/corpus/gold/<gold-id>.json draft directly from the record - "
            "fields, derived values, line_items/charges/sub_account/scanline/"
            "reference_list all auto-filled. expected_routing (review_flag/"
            "regen_flag/lane) is never auto-filled - that's the one thing a "
            "gold fixture exists to check independently, so it's always left "
            "for a human to set by hand (see _draft_pipeline_observed for what "
            "the pipeline currently decided). Does not replace promote-"
            "correction, which stays correct once a real reviewed correction "
            "exists - this is the fast path for everything else, especially a "
            "brand-new company's very first document, which promote-"
            "correction's hard-miss prerequisite can never reach."
        ),
    )
    dg.add_argument("gold_id")
    dg.add_argument("--source", required=True, help="one representative sample document")
    dg.add_argument("--force", action="store_true", help="overwrite an existing gold fixture with this id")
    _add_vision_args(dg)
    dg.set_defaults(func=_cmd_draft_gold)

    pc = sub.add_parser(
        "promote-correction",
        help="turn an accepted /review correction into a docs/corpus/gold fixture",
        description=(
            "Reads one Correction (docintel.evals.corrections) and writes a "
            "new docs/corpus/gold/<gold-id>.json fixture, copying its "
            "retained source PDF into docs/corpus/<pack>/. Does not run "
            "validate_gold.py or replay-gold automatically - a human checks "
            "the result before it's committed."
        ),
    )
    pc.add_argument("correction_id", type=int)
    pc.add_argument("--gold-id", default=None, help="default: correction-<document_id>")
    pc.add_argument(
        "--corrections-db", default=None, help="corrections db path (default: var/corrections.sqlite3)"
    )
    pc.add_argument(
        "--force", action="store_true",
        help="overwrite an already-promoted correction's gold fixture",
    )
    pc.set_defaults(func=_cmd_promote_correction)

    gp = sub.add_parser(
        "generate-persona",
        help="draft a field-hint spec for a new company from one PDF (needs pip install 'docintel[generation]')",
        description=(
            "Calls Claude once against one representative document to draft a "
            "field list - name, type, and a one-sentence location hint per "
            "field, from the closed field/pattern vocabularies this project "
            "already uses to score extraction. Never anchor/region selector "
            "geometry - that part does not generalize from one blind pass "
            "(see docintel.generation.persona_agent's module docstring) and "
            "stays a human's job. Writes a JSON file unmistakably labelled a "
            "draft; nothing here is read by the real pipeline on its own."
        ),
    )
    gp.add_argument("pdf", help="one representative sample document for this company")
    gp.add_argument("--company", required=True, help="the company's name")
    gp.add_argument("--out", default=None, help="default: docs/onboarding/generated/<company-slug>.hints.json")
    gp.add_argument("--model", default=os.environ.get("ANTHROPIC_MODEL", "claude-opus-5"))
    gp.set_defaults(func=_cmd_generate_persona)

    qs = sub.add_parser(
        "queue-status",
        help="report the review queue's depth and oldest-open-job age",
        description=(
            "Poll-based, not push: exits 1 only when --fail-if-older-than-hours "
            "is given and crossed - a nonzero queue depth by itself is normal "
            "operation, not a failure. Suitable for cron/Task Scheduler."
        ),
    )
    qs.add_argument("--jobs-db", default=None, help="job queue path (default: var/jobs.sqlite3)")
    qs.add_argument("--fail-if-older-than-hours", type=float, default=None)
    qs.add_argument("--json", action="store_true")
    qs.set_defaults(func=_cmd_queue_status)

    tr = sub.add_parser(
        "telemetry-report",
        help="aggregate dead-letter rate, escalation rate, and mean confidence from the process log",
    )
    tr.add_argument("--log-path", default=None, help="telemetry log path (default: var/logs/docintel.jsonl)")
    tr.add_argument("--since-days", type=float, default=None)
    tr.add_argument("--json", action="store_true")
    tr.set_defaults(func=_cmd_telemetry_report)

    s = sub.add_parser("serve", help="start the local web UI (upload one PDF, see the result)")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--no-browser", action="store_true", help="don't auto-open a browser tab")
    s.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
