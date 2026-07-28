"""The vendor alias table (pack spec section 4) — F5.

Without this, one carrier becomes several cold-start personas.
"""

from __future__ import annotations

import pytest

from docintel.packs.northstar.aliases import KNOWN_VENDORS, canonical


@pytest.mark.parametrize("printed", [
    "D.T.S.S., Inc.", "D T S S INC", "DTSS", "d.t.s.s.",
])
def test_dtss_renderings_collapse_to_one_key(printed: str) -> None:
    """The corpus prints this vendor three different ways. Keying on punctuation
    would need one table entry per rendering."""
    assert canonical(printed) == "dtss"


@pytest.mark.parametrize("printed", [
    "Federal Recycling & Waste Solutions",
    "Federal International Recycling and Waste Solutions, LLC",
    "FEDERAL RECYCLING",
])
def test_federal_recyclings_two_legal_names_collapse(printed: str) -> None:
    """The live F5 case: the letterhead and the check remittance are different
    legal names, and a persona keyed on the letterhead would never match a
    re-scan of the remittance stub."""
    assert canonical(printed) == "federal_recycling"


@pytest.mark.parametrize("printed,expected", [
    ("U-PAK DISPOSALS(1989) LTD", "upak"),
    ("U-Pak Disposals", "upak"),
    ("Veritiv Operating Company", "veritiv"),
    ("Complete Beverage Destruction, LLC", "complete_beverage_destruction"),
    ("EDCO WASTE & RECYCLING SERVICE", "edco"),
    ("EDCO Disposal Corporation", "edco"),
])
def test_the_remaining_corpus_vendors(printed: str, expected: str) -> None:
    assert canonical(printed) == expected


def test_the_payee_wins_over_the_letterhead() -> None:
    """The legal entity survives rebrands; the logo does not, and the money goes
    where the payee says."""
    assert canonical("Some Rebranded Logo", payee="Veritiv Operating Company") == "veritiv"


def test_the_letterhead_is_used_when_there_is_no_payee() -> None:
    assert canonical("Veritiv Operating Company", payee=None) == "veritiv"


def test_an_unrecognized_payee_falls_through_to_the_letterhead() -> None:
    assert canonical("EDCO Disposal", payee="Not A Known Vendor") == "edco"


def test_an_unknown_vendor_returns_none_rather_than_a_guess() -> None:
    """A cold start is the correct outcome for a genuinely new vendor. Inventing a
    key from the letterhead would create a persona nobody can find again."""
    assert canonical("Acme Widgets Incorporated") is None


def test_empty_input_is_not_a_vendor() -> None:
    assert canonical("") is None
    assert canonical(None) is None


def test_known_vendors_covers_every_canonical_key() -> None:
    assert "edco" in KNOWN_VENDORS
    assert len(KNOWN_VENDORS) == 6, "one key per corpus vendor"


# --------------------------------------------------------------------------
# Display names — the alias table's output
# --------------------------------------------------------------------------


def test_every_canonical_key_has_a_display_name() -> None:
    """A canonical key with no display name would leave `vendor_name` empty on
    exactly the documents whose letterhead cannot be read."""
    from docintel.packs.northstar.aliases import DISPLAY_NAMES, KNOWN_VENDORS

    assert set(DISPLAY_NAMES) == KNOWN_VENDORS


def test_digital_direction_display_names_cover_its_carriers() -> None:
    from docintel.packs.digitaldirection.aliases import DISPLAY_NAMES, KNOWN_CARRIERS

    assert set(DISPLAY_NAMES) == KNOWN_CARRIERS


def test_the_two_unreadable_letterheads_have_display_names() -> None:
    """Lumen's letterhead is an IMAGE (zero text-layer hits for the token) and
    Windstream's text layer breaks the brand mid-word (`Windstre am`). Neither can
    be captured by any pattern, which is why the table exists."""
    from docintel.packs.digitaldirection.aliases import DISPLAY_NAMES

    assert DISPLAY_NAMES["lumen"] == "Lumen"
    assert DISPLAY_NAMES["windstream"] == "Kinetic Business by Windstream"
