"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from docintel.adapters.intake.filesystem import FilesystemIntake
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_pipeline

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
        return CassetteVision(inner=None, path=cassette, mode="replay")

    from docintel.adapters.vision.anthropic_adapter import MODEL, AnthropicVision

    live = AnthropicVision()
    if mode == "live":
        return live
    return CassetteVision(inner=live, path=cassette, mode="record", model=MODEL)


def _build_runner(args: argparse.Namespace | None = None) -> Runner:
    mode = getattr(args, "vision", None) or "cassette"
    cassette = getattr(args, "cassette", None) or DEFAULT_CASSETTE
    return build_pipeline(vision=_build_vision(mode, cassette))


def _cmd_process(args: argparse.Namespace) -> int:
    runner = _build_runner(args)
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

    card = replay_gold(runner_factory=lambda: _build_runner(args))
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        for doc in card["documents"]:
            mark = "PASS" if doc["passed"] else "FAIL"
            print(f"{mark}  {doc['gold_id']}  ({doc['passed_count']}/{doc['total_count']})")
        s = card["summary"]
        print(f"\n{s['passed']}/{s['total']} documents green")
    return 0 if card["summary"]["failed"] == 0 else 1


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
    _add_vision_args(p)
    p.set_defaults(func=_cmd_process)

    g = sub.add_parser("replay-gold", help="run the gold corpus and score it")
    g.add_argument("--json", action="store_true")
    _add_vision_args(g)
    g.set_defaults(func=_cmd_replay_gold)

    s = sub.add_parser("serve", help="start the local web UI (upload one PDF, see the result)")
    s.add_argument("--port", type=int, default=5000)
    s.add_argument("--no-browser", action="store_true", help="don't auto-open a browser tab")
    s.set_defaults(func=_cmd_serve)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
