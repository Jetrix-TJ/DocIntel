"""Email containers (.eml, .msg): one `IntakeItem` per ATTACHMENT, never for
the email itself.

The invoice is almost always an attachment, not the email body, so this
adapter's whole job is unwrapping - it never reads a field, never opens a
persona, never touches Stage 2. That happens exactly once, downstream,
for every attachment it yields, the same as any other document.

**Where this sits architecturally.** `Runner.process(document_id, source_path)
-> dict` is a strict 1:1, machine-checked invariant elsewhere in this
codebase (`count(intaken) == count(emitted)`) - one call, one record, never a
list. An email genuinely can contain several documents, so the 1:N expansion
has to happen ONE LAYER ABOVE the `Runner`, exactly where
`FilesystemIntake._walk` already turns one directory into many `IntakeItem`s.
This is the same seam, applied to one archive file instead of a directory
tree: the CLI's existing per-item loop (`cli.py::_cmd_process`) already calls
`runner.process()` once per yielded item, so it needs no change at all to
run N times for one email instead of once.

**No nesting.** An attachment that is itself a container (a nested `.eml`, a
`.zip`) is yielded exactly like any other attachment - not recursed into.
Its own suffix will not be in `extract.convert.ACCEPTED_SUFFIXES`, so Stage 2
skips it with a clear, honest reason, which already satisfies "nothing is
silently dropped" without any special-case code here.

**A parse failure, or zero attachments, still yields one item** - for the
ORIGINAL email path, not nothing. Stage 2 then rejects it (`.eml`/`.msg` are
containers, never accepted document types themselves), which is a real,
visible `skipped` disposition rather than the email vanishing before intake
even counted it.
"""

from __future__ import annotations

import email as email_stdlib
import hashlib
import logging
import os
import tempfile
from collections.abc import Iterator
from email import policy as email_policy

from docintel.adapters.intake.port import IntakeItem
from docintel.core.errors import PermanentError

_LOG = logging.getLogger(__name__)

MSG_SUFFIX = ".msg"
EML_SUFFIX = ".eml"


def _require_extract_msg() -> None:
    """Checked once per batch, before any `.msg` is opened - not per file.

    If this dependency is missing, EVERY `.msg` in the batch would fail
    identically, so failing loudly once, up front, with an actionable
    install instruction is more honest than letting each one individually
    fall through to a misleading "unsupported file type" skip.
    """
    try:
        import extract_msg  # noqa: F401
    except ImportError as exc:
        raise PermanentError(
            "reading .msg files needs the optional 'extract-msg' package - "
            "pip install 'docintel[email]'"
        ) from exc


def _stable_email_key(raw_bytes: bytes, message_id: str | None) -> str:
    """Prefer the email's own `Message-Id` (stable across re-delivery of the
    identical mail); fall back to a content hash of the email's own bytes
    when it is absent, so redelivery of the identical file still keys the
    same way."""
    if message_id:
        return message_id.strip("<>")
    return hashlib.sha256(raw_bytes).hexdigest()[:24]


def _attachment_document_id(email_key: str, index: int, filename: str, size: int) -> str:
    """Mirrors `FilesystemIntake._stable_id`'s shape exactly: a deterministic
    hash of everything that identifies THIS attachment, so re-processing the
    same email never mints a new id for the same attachment."""
    key = f"{email_key}|{index}|{filename}|{size}"
    return "eml-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _fallback_document_id(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1
    key = f"{os.path.abspath(path)}|{size}"
    return "eml-fallback-" + hashlib.sha256(key.encode()).hexdigest()[:16]


def _write_temp_attachment(filename: str, data: bytes) -> str:
    suffix = os.path.splitext(filename)[1]
    fd, path = tempfile.mkstemp(suffix=suffix, prefix="docintel-attachment-")
    with os.fdopen(fd, "wb") as fh:
        fh.write(data)
    return path


class EmailIntake:
    """Given email paths (`.eml`/`.msg`), yields one `IntakeItem` per
    attachment. Implements the same `IntakeSource` protocol as
    `FilesystemIntake` (`adapters/intake/port.py`)."""

    def __init__(self, paths: list[str]) -> None:
        self.paths = paths

    def items(self) -> Iterator[IntakeItem]:
        file_paths = list(self._expand(self.paths))
        if any(os.path.splitext(p)[1].lower() == MSG_SUFFIX for p in file_paths):
            _require_extract_msg()
        for path in file_paths:
            yield from self._items_for(path)

    @staticmethod
    def _expand(paths: list[str]) -> Iterator[str]:
        """Literal email paths pass through; a directory is walked for
        `.eml`/`.msg` files, deepest paths included - the same recursion
        `FilesystemIntake._walk` uses, so an email one directory down is
        never invisible here either."""
        for path in paths:
            if os.path.isdir(path):
                for dirpath, dirnames, filenames in os.walk(path):
                    dirnames.sort()
                    for name in sorted(filenames):
                        if os.path.splitext(name)[1].lower() in (EML_SUFFIX, MSG_SUFFIX):
                            yield os.path.join(dirpath, name)
            else:
                yield path

    def _items_for(self, path: str) -> Iterator[IntakeItem]:
        suffix = os.path.splitext(path)[1].lower()
        items: list[IntakeItem] = []
        try:
            if suffix == EML_SUFFIX:
                items = list(self._from_eml_resilient(path))
            elif suffix == MSG_SUFFIX:
                items = list(self._from_msg_resilient(path))
        except Exception:  # noqa: BLE001 - deliberate: a bad email must fall back, not crash
            items = []
        if items:
            yield from items
        else:
            yield IntakeItem(_fallback_document_id(path), path)

    def _from_eml_resilient(self, path: str) -> Iterator[IntakeItem]:
        """Wraps the per-attachment work in its own try/except so ONE bad
        attachment's exception doesn't discard every attachment already
        yielded before it. The old code wrapped the whole `list(...)` call in
        a single try/except in `_items_for`, so attachment 3 of 5 raising
        lost the first 2 that had already parsed fine - they were replaced by
        one fallback item for the raw, unparseable-as-a-document path."""
        with open(path, "rb") as fh:
            raw = fh.read()
        msg = email_stdlib.message_from_bytes(raw, policy=email_policy.default)
        email_key = _stable_email_key(raw, msg.get("Message-Id"))
        sender = msg.get("From")

        index = 0
        for position, part in enumerate(msg.iter_attachments(), start=1):
            try:
                data = part.get_payload(decode=True)
                if not data:
                    continue
                index += 1
                filename = part.get_filename() or f"attachment-{index}"
                temp_path = _write_temp_attachment(filename, data)
                document_id = _attachment_document_id(email_key, index, filename, len(data))
            except Exception:
                _LOG.warning(
                    "eml %s: attachment at position %d failed to decode, skipping it only",
                    path, position,
                )
                continue
            yield IntakeItem(
                document_id, temp_path, sender_email=sender, email_id=email_key
            )

    def _from_msg_resilient(self, path: str) -> Iterator[IntakeItem]:
        """Same per-attachment isolation as `_from_eml_resilient`, applied to
        `.msg` containers."""
        import extract_msg

        with open(path, "rb") as fh:
            raw = fh.read()
        msg = extract_msg.Message(path)
        try:
            email_key = _stable_email_key(raw, msg.messageId)
            sender = msg.sender

            index = 0
            for position, attachment in enumerate(msg.attachments, start=1):
                try:
                    data = attachment.data
                    if not data:
                        continue
                    index += 1
                    filename = attachment.getFilename() or f"attachment-{index}"
                    temp_path = _write_temp_attachment(filename, data)
                    document_id = _attachment_document_id(email_key, index, filename, len(data))
                except Exception:
                    _LOG.warning(
                        "msg %s: attachment at position %d failed to decode, skipping it only",
                        path, position,
                    )
                    continue
                yield IntakeItem(
                    document_id, temp_path, sender_email=sender, email_id=email_key
                )
        finally:
            msg.close()
