

def test_private_use_glyphs_are_stripped_from_word_text():
    """A real corpus finding, and it silently cost an entire field.

    Comcast's bill maps `$` into the Unicode Private Use Area, so its total
    arrives from pdfplumber as `221.11`. A private-use codepoint has no
    portable meaning - it means whatever the producing font says - so left in
    place it defeats `parse_money`, `total_printed` fails to extract, and that
    cascades into a refused `amount_payable` and a forced review.
    """
    from docintel.extract.pdf import _clean

    assert _clean("221.11") == "221.11"
    assert _clean("plain") == "plain"
    assert _clean("") == ""


def test_a_word_that_was_only_private_use_glyphs_is_dropped():
    """Keeping it as an empty-text Word would put a zero-width phantom into every
    line, which changes cell boundaries and line grouping."""
    from docintel.extract.pdf import _clean

    assert not _clean("")


def test_comcast_total_survives_the_font_encoding():
    """The whole-path check on the finding above."""
    import os

    from docintel.extract.normalize import load_document
    from docintel.grammar.patterns import NAMED

    path = os.path.join("docs", "Comcast_8495 44 462 0365242_12092025_BILL.pdf")
    pages, _, _ = load_document(path)
    tokens = {w.text for w in pages[0].words}
    assert "221.11" in tokens, "the total must arrive as plain text"
    assert NAMED["currency"]("221.11") is not None
