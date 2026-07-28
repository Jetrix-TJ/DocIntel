"""The printed-fields-only rule, asserted structurally rather than per document."""

from __future__ import annotations

from docintel.core.models import DERIVED_ONLY
from docintel.packs.digitaldirection import fields


def test_no_registered_field_is_derived_only() -> None:
    """The machine-checkable form of the whole printed-fields-only design.

    V10 already stops a selector targeting a derived name at validation time.
    This is stricter and earlier: the name is not even registered, so a persona
    author cannot write the selector in the first place.
    """
    assert not (fields.FIELDS & DERIVED_ONLY)


def test_required_is_a_subset_of_fields() -> None:
    assert fields.REQUIRED <= fields.FIELDS


def test_every_any_of_group_is_non_empty_and_registered() -> None:
    assert fields.REQUIRED_ANY_OF, "an empty group tuple makes V13's clause a no-op"
    for group in fields.REQUIRED_ANY_OF:
        assert group, "an empty group can never be satisfied"
        assert group <= fields.FIELDS, f"{sorted(group - fields.FIELDS)} not registered"


def test_the_inference_ladder_outputs_are_gone() -> None:
    """`currency` comes from the F14 ladder and `prior_balance_basis` from a
    vendor convention. Neither is ink on the page."""
    for name in ("currency", "prior_balance_basis"):
        assert name not in fields.FIELDS


def test_normalized_names_are_gone() -> None:
    """A normalized account number is computed from the printed one."""
    assert not {n for n in fields.FIELDS if n.endswith("_normalized")}


def test_account_number_is_unconditionally_required() -> None:
    """DD's identity key, not `invoice_number`: three of the four carriers print
    no invoice number at all (F6), and the field spec measures the carrier
    account number present on 100% of readable invoices."""
    assert "account_number" in fields.REQUIRED
    assert "invoice_number" not in fields.REQUIRED


def test_the_row_classifications_are_not_registered() -> None:
    """Service type, charge type and the C/S/U row flag are closed-list
    classifications of a row, not printed values - so they are deferred with the
    rest of the derived work rather than added."""
    for name in ("service_type", "charge_type", "row_type"):
        assert name not in fields.FIELDS
