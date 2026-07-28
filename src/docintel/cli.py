"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from docintel.adapters.intake.filesystem import FilesystemIntake
from docintel.adapters.vision.fake import FakeVision
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_pipeline


def _build_runner() -> Runner:
    return build_pipeline(vision=FakeVision())


def _cmd_process(args: argparse.Namespace) -> int:
    runner = _build_runner()
    dispositions: Counter[str] = Counter()

    for item in FilesystemIntake(args.paths).items():
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


def _cmd_replay_gold(args: argparse.Namespace) -> int:
    from docintel.scorecard import replay_gold

    card = replay_gold(runner_factory=_build_runner)
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        for doc in card["documents"]:
            mark = "PASS" if doc["passed"] else "FAIL"
            print(f"{mark}  {doc['gold_id']}  ({doc['passed_count']}/{doc['total_count']})")
        s = card["summary"]
        print(f"\n{s['passed']}/{s['total']} documents green")
    return 0 if card["summary"]["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
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
    p.set_defaults(func=_cmd_process)

    g = sub.add_parser("replay-gold", help="run the gold corpus and score it")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=_cmd_replay_gold)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
