"""Fix round 1 (revised): load_document must be cheap to call repeatedly
in-process without ever serving a stale answer.

tests/test_invariant.py's fault-injection matrix re-processes the same
10-document corpus 48 times in one process — 400+ re-parses of the same
native PDF without a memo. These tests prove the memo actually memoizes
(repeat calls for an unmodified file are a cache hit, not a re-parse) and
that it never serves a stale, wrong-document result.

Fix round 2: the (abspath, st_size, st_mtime_ns) key from round 1 has a real
hole — a file overwritten in place at the same path, padded to the same
byte size, with its mtime restored (rsync -t, cp --preserve=timestamps,
timestamp-preserving archive extraction) collides on all three and would
serve the previous content. `test_overwriting_the_file_in_place_...` below
reproduces that directly and must fail before the content-hash fix, pass
after it.
"""

from __future__ import annotations

import os
import shutil
import time

from docintel.extract.normalize import _load_document_cached, load_document

DOC_A = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
DOC_B = "docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf"


def test_overwriting_the_file_in_place_is_detected_even_with_same_size_and_mtime(tmp_path):
    """The real hazard: same path, same size, same mtime, different bytes.

    DOC_B is written first (it's the larger file), loaded, then overwritten
    *in place* with DOC_A's real content padded with trailing null bytes out
    to DOC_B's exact original size — trailing padding after a PDF's %%EOF is
    inert, pdfplumber/pypdfium2 parse straight through it, so this is a
    genuinely different, still-valid document at an identical size. The
    mtime is then restored to the exact original st_mtime_ns. A memo keyed
    only on (path, size, mtime) cannot tell these two states apart; one
    keyed on content hash must.
    """
    copy_path = tmp_path / "doc.pdf"
    with open(DOC_B, "rb") as fh:
        original_bytes = fh.read()
    copy_path.write_bytes(original_bytes)

    first_pages, _first_meta, _first_source = load_document(str(copy_path))

    stat_before = os.stat(copy_path)
    target_size = stat_before.st_size

    with open(DOC_A, "rb") as fh:
        new_real_content = fh.read()
    assert len(new_real_content) < target_size, "test fixture assumption: DOC_A is the smaller file"
    padded_content = new_real_content + b"\x00" * (target_size - len(new_real_content))
    copy_path.write_bytes(padded_content)
    os.utime(copy_path, ns=(stat_before.st_atime_ns, stat_before.st_mtime_ns))

    stat_after = os.stat(copy_path)
    assert stat_after.st_size == stat_before.st_size
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns

    second_pages, _second_meta, _second_source = load_document(str(copy_path))

    # DOC_B's first word must NOT be what's now on disk (DOC_A's content).
    assert second_pages[0].words[0].text != first_pages[0].words[0].text
    assert second_pages[0].words[0].text == "D.T.S.S.,"


def test_repeated_calls_are_a_cache_hit_not_a_reparse(tmp_path):
    copy_path = tmp_path / "doc.pdf"
    shutil.copyfile(DOC_A, copy_path)

    before = _load_document_cached.cache_info()
    first = load_document(str(copy_path))
    after_first = _load_document_cached.cache_info()
    assert after_first.misses == before.misses + 1

    second = load_document(str(copy_path))
    after_second = _load_document_cached.cache_info()
    assert after_second.hits == after_first.hits + 1
    assert after_second.misses == after_first.misses  # no re-parse
    assert first == second


def test_touching_mtime_forces_a_reparse_not_a_stale_hit(tmp_path):
    copy_path = tmp_path / "doc.pdf"
    shutil.copyfile(DOC_A, copy_path)

    load_document(str(copy_path))
    before_touch = _load_document_cached.cache_info()

    future = time.time() + 5
    os.utime(copy_path, (future, future))

    load_document(str(copy_path))
    after_touch = _load_document_cached.cache_info()
    assert after_touch.misses == before_touch.misses + 1
