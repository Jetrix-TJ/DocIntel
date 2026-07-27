"""Fix round 1 (revised): load_document must be cheap to call repeatedly
in-process without ever serving a stale answer.

tests/test_invariant.py's fault-injection matrix re-processes the same
10-document corpus 48 times in one process — 400+ re-parses of the same
native PDF without a memo. This proves the memo actually memoizes (repeat
calls for an unmodified file are a cache hit, not a re-parse) and that it
never collides across different files or a file that changed underneath it.
"""

from __future__ import annotations

import os
import shutil
import time

from docintel.extract.normalize import _load_document_cached, load_document

DOC_A = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
DOC_B = "docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf"


def test_different_files_do_not_collide_in_the_memo(tmp_path):
    copy_a = tmp_path / "a.pdf"
    copy_b = tmp_path / "b.pdf"
    shutil.copyfile(DOC_A, copy_a)
    shutil.copyfile(DOC_B, copy_b)

    pages_a, meta_a, source_a = load_document(str(copy_a))
    pages_b, meta_b, source_b = load_document(str(copy_b))

    assert pages_a != pages_b
    assert pages_a[0].words != pages_b[0].words


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
