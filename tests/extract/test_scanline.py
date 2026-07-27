import pytest

from docintel.extract.normalize import load_document
from docintel.extract.scanline import CORROBORATABLE_FIELDS, corroborates, find

CASES = [
    ("docs/Lumen - 5-QXH7QKM7.pdf", "24809"),
    ("docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf", "22111"),
    ("docs/Centracom_0384043574_01012026_BILL.pdf", "3387640"),
    ("docs/Windstream_041069076_07222025_BILL.pdf", "123014"),
    ("docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf", "36796"),
]

NO_SCANLINE = [
    "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf",
    "docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf",
    "docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf",
    "docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf",
    "docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf",
]


@pytest.mark.parametrize("path,digits", CASES)
def test_scanline_encodes_the_printed_total(path, digits):
    """F7: 5 of 10 documents carry machine-readable ground truth."""
    pages, _, _ = load_document(path)
    line = find(pages)
    assert line is not None
    assert digits in line.replace(" ", "")


def test_documents_without_a_scanline_return_none():
    pages, _, _ = load_document(
        "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"
    )
    assert find(pages) is None


@pytest.mark.parametrize("path", NO_SCANLINE)
def test_the_five_documents_without_a_scanline_all_return_none(path):
    pages, _, _ = load_document(path)
    assert find(pages) is None


def test_centracom_scanline_corroborates_the_printed_total_not_the_payable_amount():
    """The hard constraint from selector-grammar.md: Centracom's scan line
    encodes the misleading headline total (33,876.40), never the 13,752.60
    that is actually payable. Corroboration must reflect transcription
    fidelity, not business correctness.
    """
    pages, _, _ = load_document("docs/Centracom_0384043574_01012026_BILL.pdf")
    line = find(pages)
    assert line is not None
    assert corroborates(line, "33876.40", field="total_printed")
    assert not corroborates(line, "13752.60", field="total_printed")


def test_corroborates_strips_punctuation_from_a_decimal_value():
    from decimal import Decimal

    pages, _, _ = load_document("docs/Lumen - 5-QXH7QKM7.pdf")
    line = find(pages)
    assert line is not None
    assert corroborates(line, Decimal("248.09"), field="total_printed")
    assert corroborates(line, "752233001", field="invoice_number")
    assert not corroborates(line, "999999999", field="invoice_number")


def test_corroborates_rejects_degenerate_short_values():
    pages, _, _ = load_document("docs/Lumen - 5-QXH7QKM7.pdf")
    line = find(pages)
    assert line is not None
    assert not corroborates(line, "1", field="total_printed")
    assert not corroborates(line, "", field="total_printed")


def test_corroborates_accepts_exactly_the_four_grammar_fields():
    """docs/architecture/selector-grammar.md's hard constraint, enforced in
    code: the scan line may only ever be asked about these four fields.
    """
    assert CORROBORATABLE_FIELDS == {
        "total_printed", "account_number", "invoice_number", "due_date",
    }


@pytest.mark.parametrize("field", ["amount_payable", "current_charges"])
def test_corroborates_rejects_fields_outside_the_grammar_constraint(field):
    """The specific failure mode Finding 2 exists to prevent: wiring the
    scan line to a derived/business field (`amount_payable`) or any other
    field not on the allowed list (`current_charges`) must raise loudly
    rather than silently answering a question it has no business answering
    - Centracom's scan line encodes the misleading 33,876.40 headline
    total, not the 13,752.60 actually payable.
    """
    with pytest.raises(ValueError, match=field):
        corroborates("0384043574", "13752.60", field=field)
