from docintel.core.senders import bill_to_matches_roster

ROSTER = ("Northstar Recycling Company, LLC", "Northstar-Bimbo-Market Street")


def test_a_rendering_variant_still_matches() -> None:
    """One party, many spellings — the variation is the vendors', not the client's."""
    assert bill_to_matches_roster("NORTHSTAR RECYCLING COMPANY LLC", ROSTER)
    assert bill_to_matches_roster("NorthStar Recycling Company, LLC", ROSTER)


def test_a_different_company_does_not_match() -> None:
    assert not bill_to_matches_roster("Contoso Manufacturing Inc", ROSTER)


def test_nothing_printed_is_not_a_mismatch() -> None:
    """An empty bill-to is coverage's problem, not a mismatch. Distinct signals."""
    assert bill_to_matches_roster(None, ROSTER)
    assert bill_to_matches_roster("", ROSTER)


def test_an_empty_roster_never_accuses() -> None:
    """A pack that ships no roster cannot make a mismatch claim about anything."""
    assert bill_to_matches_roster("Anyone At All", ())
