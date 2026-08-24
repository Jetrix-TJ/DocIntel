"""Recorded vision calls, replayed byte-for-byte. The default vision path.

**Why a cassette rather than a mock.** `FakeVision` returns whatever a test hands
it, which proves the wiring and nothing else. A cassette holds what a real model
actually said about a real page, so a replay run exercises the same parsing,
sanitizing and capture path as a live call - deterministically, offline, and
without a key. That is what makes `replay-gold` usable as an objective function
with vision in the loop.

**A miss is a failure, loudly.** The tempting alternative - return an empty
`VisionResult` when the cassette has no entry - is the exact silent-degradation
pattern this project keeps removing (see the C1a dead cache bypass, and the
rejected persona that turned into a silent vision fallback). An empty result would
make "vision ran and found nothing" indistinguishable from "vision never ran", and
the document would score as though the model had been asked and had failed. So
replay raises. The runner turns that into one dead-lettered document with an
actionable reason, and the emit-always invariant still holds.

**The key is the document's content, not its path.** Same reasoning as the C1a
cache-key fix: a cassette stays valid when the corpus directory moves, and goes
stale - as a loud miss - the moment the PDF itself changes. A path-keyed cassette
would do the opposite of both.

Entries are also sanitized on replay. A cassette is a JSON file a human can edit,
which makes it untrusted input in exactly the way a model response is; `policy`
is the boundary, so it runs on both paths.
"""

from __future__ import annotations

import hashlib
import json
import os
from typing import Any

from docintel.adapters.vision.policy import sanitize
from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText

Mode = str  # "replay" | "record"

# Bumped if the key derivation changes, so old cassettes miss loudly instead of
# matching the wrong call.
KEY_VERSION = b"docintel-vision-1"

_KEY_LENGTH = 16

# How an entry came to exist. `authored` means a human wrote the expected output
# by hand (the first-pass bootstrap before a key existed); `recorded` means a real
# model produced it. The distinction has to survive in the file rather than only in
# a journal entry, because an authored cassette scored against gold is circular and
# anyone reading a green run deserves to see that from the artifact.
PROVENANCE = ("recorded", "authored")


class CassetteVision:
    """Replay recorded vision calls, or record new ones through `inner`."""

    def __init__(
        self,
        inner: object | None,
        path: str,
        mode: Mode = "replay",
        model: str | None = None,
    ) -> None:
        if mode not in ("replay", "record"):
            raise ValueError(f"mode must be 'replay' or 'record', got {mode!r}")
        if mode == "record" and inner is None:
            raise ValueError("record mode needs an inner extractor to record from")
        self.inner = inner
        self.path = path
        self.mode = mode
        self.model = model

    # -- keying ------------------------------------------------------------

    def key(
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        source_path: str | None = None,
        field_hints: dict[str, str] | None = None,
        table_requests: dict[str, list[str]] | None = None,
    ) -> str:
        """A stable identifier for "this document, these fields, these hints".

        Prefers the source bytes, because that is what a real adapter sends. Falls
        back to the text layer so a cassette can be keyed for a caller that has no
        file - the two are domain-separated so they can never collide.

        `field_hints` only enters the hash when non-empty, so a caller that never
        passes hints (every cassette recorded before this parameter existed)
        gets the exact same key as before - the change is additive, not a mass
        invalidation. A hint set DOES belong in the key once it is used: it is
        as much a part of "what we asked for" as `field_names` already is, and
        two different hint sets asked about the same fields can legitimately
        get different answers.
        """
        h = hashlib.sha256()
        h.update(KEY_VERSION)
        h.update(b"\0")
        digest = _file_digest(source_path)
        if digest is not None:
            h.update(b"doc\0")
            h.update(digest)
        else:
            h.update(b"txt\0")
            for page in pages:
                h.update(
                    f"{page.page_number}|{page.width:.2f}x{page.height:.2f}"
                    f"|{page.source}\n".encode()
                )
                h.update(page.text.encode())
                h.update(b"\0")
        h.update(b"fields\0")
        for name in field_names:
            h.update(name.encode())
            h.update(b"\0")
        if field_hints:
            h.update(b"hints\0")
            for name in sorted(field_hints):
                h.update(name.encode())
                h.update(b"\0")
                h.update(field_hints[name].encode())
                h.update(b"\0")
        if table_requests:
            # Same additive-only reasoning as `field_hints` above: a cassette
            # recorded before table support existed has no table_requests, so
            # this only enters the key (and changes it) once a caller actually
            # asks for a table.
            h.update(b"tables\0")
            for name in sorted(table_requests):
                h.update(name.encode())
                h.update(b"\0")
                for col in table_requests[name]:
                    h.update(col.encode())
                    h.update(b"\0")
        return h.hexdigest()[:_KEY_LENGTH]

    # -- the port ----------------------------------------------------------

    def extract(
        self,
        pages: tuple[PageText, ...],
        field_names: list[str],
        *,
        source_path: str | None = None,
        field_hints: dict[str, str] | None = None,
        table_requests: dict[str, list[str]] | None = None,
        table_hints: dict[str, dict[str, str]] | None = None,
    ) -> VisionResult:
        cassette_key = self.key(pages, field_names, source_path, field_hints, table_requests)
        if self.mode == "replay":
            return self._replay(cassette_key, field_names, source_path, table_requests)
        return self._record(
            cassette_key, pages, field_names, source_path, field_hints, table_requests, table_hints
        )

    def _replay(
        self,
        cassette_key: str,
        field_names: list[str],
        source_path: str | None,
        table_requests: dict[str, list[str]] | None,
    ) -> VisionResult:
        entries = self._load()
        entry = entries.get(cassette_key)
        if entry is None:
            raise KeyError(
                f"no cassette entry {cassette_key!r} in {self.path!r} for "
                f"{os.path.basename(source_path or '<no source>')} "
                f"fields={field_names}; re-run with --vision record to record it"
            )
        return sanitize(_result_from(entry), field_names, table_requests)

    def _record(
        self,
        cassette_key: str,
        pages: tuple[PageText, ...],
        field_names: list[str],
        source_path: str | None,
        field_hints: dict[str, str] | None,
        table_requests: dict[str, list[str]] | None,
        table_hints: dict[str, dict[str, str]] | None,
    ) -> VisionResult:
        assert self.inner is not None  # guaranteed by __init__
        result = self.inner.extract(  # type: ignore[attr-defined]
            pages, field_names, source_path=source_path, field_hints=field_hints,
            table_requests=table_requests, table_hints=table_hints,
        )
        entries = self._load()
        entries[cassette_key] = {
            "provenance": "recorded",
            "model": self.model,
            "document": os.path.basename(source_path) if source_path else None,
            "field_names": list(field_names),
            "field_hints": dict(field_hints) if field_hints else {},
            "fields": dict(result.fields),
            "confidence": dict(result.confidence),
            "irregularities": list(result.irregularities),
            "tables": {name: [dict(row) for row in rows] for name, rows in result.row_groups.items()},
        }
        self._save(entries)
        return sanitize(result, field_names, table_requests)

    # -- file --------------------------------------------------------------

    def _load(self) -> dict[str, Any]:
        if not os.path.isfile(self.path):
            return {}
        with open(self.path, encoding="utf-8") as fh:
            loaded = json.load(fh)
        if not isinstance(loaded, dict):
            raise ValueError(f"cassette {self.path!r} must be a JSON object")
        return loaded

    def _save(self, entries: dict[str, Any]) -> None:
        """Write atomically. A half-written cassette is worse than no cassette:
        it replays as a miss on some documents and a KeyError on others, and the
        difference looks like a pipeline bug rather than a truncated file."""
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, self.path)


def _result_from(entry: Any) -> VisionResult:
    if not isinstance(entry, dict):
        raise ValueError(f"cassette entry must be an object, got {type(entry).__name__}")
    fields = entry.get("fields") or {}
    confidence = entry.get("confidence") or {}
    irregularities = entry.get("irregularities") or []
    tables = entry.get("tables") or {}
    if not isinstance(fields, dict) or not isinstance(confidence, dict):
        raise ValueError("cassette entry 'fields' and 'confidence' must be objects")
    if not isinstance(irregularities, list):
        raise ValueError("cassette entry 'irregularities' must be an array")
    if not isinstance(tables, dict):
        raise ValueError("cassette entry 'tables' must be an object")
    row_groups = {
        name: [row for row in rows if isinstance(row, dict)]
        for name, rows in tables.items()
        if isinstance(rows, list)
    }
    return VisionResult(
        fields=dict(fields),
        confidence=dict(confidence),
        irregularities=list(irregularities),
        row_groups=row_groups,
    )


def _file_digest(path: str | None) -> bytes | None:
    """sha256 of the file, or None when there is no readable file.

    Read in chunks: a corpus PDF is small, but the vision path is the one that
    handles the biggest documents, and slurping is the habit that makes that hurt.
    """
    if not path or not os.path.isfile(path):
        return None
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.digest()
