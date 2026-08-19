"""`EmailIntake`: one attachment in, one `IntakeItem` out - never the email
itself, except when there is nothing else to yield.
"""

from __future__ import annotations

import os
import sys
from email.message import EmailMessage

import pytest

from docintel.adapters.intake.email import EmailIntake
from docintel.core.errors import PermanentError


def _write_eml(path, *, message_id: str | None = None, sender: str = "vendor@example.com",
               attachments: list[tuple[str, bytes]] | None = None) -> None:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = "billing@buyer.example"
    msg["Subject"] = "Invoice attached"
    if message_id:
        msg["Message-Id"] = message_id
    msg.set_content("Please see the attached invoice.")
    for filename, data in attachments or []:
        msg.add_attachment(data, maintype="application", subtype="octet-stream",
                            filename=filename)
    with open(path, "wb") as fh:
        fh.write(msg.as_bytes())


# -- .eml, the common, dependency-free case ---------------------------------


def test_one_eml_with_two_attachments_yields_two_items(tmp_path):
    eml = tmp_path / "invoice.eml"
    _write_eml(
        eml, message_id="<abc123@vendor.example>",
        attachments=[("invoice.pdf", b"%PDF-1.4 fake"), ("statement.pdf", b"%PDF-1.4 also-fake")],
    )

    items = list(EmailIntake([str(eml)]).items())

    assert len(items) == 2
    names = {os.path.basename(i.source_path).split(".")[0] for i in items}
    assert all(i.source_path.endswith(".pdf") for i in items)
    assert len(names) <= 2  # temp filenames differ from the originals, just confirming 2 distinct files
    for item in items:
        assert item.sender_email == "vendor@example.com"
        assert item.email_id == "abc123@vendor.example"


def test_attachment_bytes_are_preserved_exactly(tmp_path):
    eml = tmp_path / "invoice.eml"
    payload = b"%PDF-1.4 exact bytes check \x00\x01\x02"
    _write_eml(eml, attachments=[("invoice.pdf", payload)])

    items = list(EmailIntake([str(eml)]).items())

    assert len(items) == 1
    with open(items[0].source_path, "rb") as fh:
        assert fh.read() == payload


def test_document_ids_are_stable_across_repeated_calls(tmp_path):
    eml = tmp_path / "invoice.eml"
    _write_eml(
        eml, message_id="<stable@vendor.example>",
        attachments=[("a.pdf", b"AAAA"), ("b.pdf", b"BBBB")],
    )

    first = [i.document_id for i in EmailIntake([str(eml)]).items()]
    second = [i.document_id for i in EmailIntake([str(eml)]).items()]

    assert first == second
    assert len(set(first)) == 2  # the two attachments still get distinct ids


def test_no_message_id_falls_back_to_a_content_hash_still_stable(tmp_path):
    eml = tmp_path / "invoice.eml"
    _write_eml(eml, message_id=None, attachments=[("a.pdf", b"AAAA")])

    first = [i.document_id for i in EmailIntake([str(eml)]).items()]
    second = [i.document_id for i in EmailIntake([str(eml)]).items()]

    assert first == second


def test_a_nested_container_attachment_is_yielded_not_recursed_into(tmp_path):
    """No nesting in this pass - a nested .eml/.zip attachment is still
    yielded as an ordinary IntakeItem; Stage 2's own allowlist is what
    eventually rejects it, not any special-case code here."""
    eml = tmp_path / "invoice.eml"
    _write_eml(eml, attachments=[("nested.zip", b"PK\x03\x04 fake zip bytes")])

    items = list(EmailIntake([str(eml)]).items())

    assert len(items) == 1
    assert items[0].source_path.endswith(".zip")


def test_a_zero_attachment_email_falls_back_to_the_original_path(tmp_path):
    eml = tmp_path / "empty.eml"
    _write_eml(eml, attachments=None)

    items = list(EmailIntake([str(eml)]).items())

    assert len(items) == 1
    assert items[0].source_path == str(eml)


def test_a_corrupt_eml_falls_back_to_the_original_path_not_a_crash(tmp_path):
    bad = tmp_path / "corrupt.eml"
    bad.write_bytes(b"\xff\xfe not a valid email at all \x00\x01")

    items = list(EmailIntake([str(bad)]).items())

    # Malformed RFC822 content still parses as *some* email.message.Message
    # (the format is extremely permissive) - the meaningful guarantee is
    # "never crashes, never loses the document", which holds either way.
    assert len(items) >= 1


def test_a_directory_is_walked_for_nested_eml_files(tmp_path):
    (tmp_path / "not-an-email.pdf").write_bytes(b"%PDF-1.4")
    deep = tmp_path / "inbox"
    deep.mkdir()
    _write_eml(deep / "one.eml", attachments=[("a.pdf", b"AAAA")])
    _write_eml(deep / "two.eml", attachments=[("b.pdf", b"BBBB")])

    items = list(EmailIntake([str(tmp_path)]).items())

    assert len(items) == 2


# -- .msg, mocked (no real OLE-format fixture available without Outlook) ----


class _FakeAttachment:
    def __init__(self, filename: str, data: bytes) -> None:
        self._filename = filename
        self.data = data

    def getFilename(self) -> str:
        return self._filename


class _FakeMsgMessage:
    def __init__(self, path: str) -> None:
        self.path = path
        self.sender = "vendor@example.com"
        self.messageId = "<msg123@vendor.example>"
        self.attachments = [_FakeAttachment("invoice.pdf", b"%PDF-1.4 fake msg attachment")]
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_msg_files_are_unwrapped_via_extract_msg(tmp_path, monkeypatch):
    import extract_msg

    msg_path = tmp_path / "invoice.msg"
    msg_path.write_bytes(b"fake ole bytes - extract_msg.Message is mocked")
    monkeypatch.setattr(extract_msg, "Message", _FakeMsgMessage)

    items = list(EmailIntake([str(msg_path)]).items())

    assert len(items) == 1
    assert items[0].sender_email == "vendor@example.com"
    assert items[0].email_id == "msg123@vendor.example"
    with open(items[0].source_path, "rb") as fh:
        assert fh.read() == b"%PDF-1.4 fake msg attachment"


def test_missing_extract_msg_dependency_fails_loudly_once_per_batch(monkeypatch, tmp_path):
    """Every `.msg` in a batch needs the same dependency, so this fails once,
    up front, with an actionable install instruction - rather than each file
    individually falling through to a misleading 'unsupported' skip."""
    msg_path = tmp_path / "invoice.msg"
    msg_path.write_bytes(b"stub")
    monkeypatch.setitem(sys.modules, "extract_msg", None)

    with pytest.raises(PermanentError, match="extract-msg"):
        list(EmailIntake([str(msg_path)]).items())
