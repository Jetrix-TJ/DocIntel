"""The guard on an unimplemented branch.

pipeline-v2.md:169 requires aggregator senders be keyed by printed vendor name
and never by the shared email domain: without this, every invoice routed through
bill.com resolves to one vendor. No corpus document arrives from an aggregator,
so nothing here would fail if the branch were simply missing - which is exactly
why the test exists.
"""

from __future__ import annotations

import pytest

from docintel.core.senders import AGGREGATOR_DOMAINS, is_aggregator


@pytest.mark.parametrize("email", [
    "ap@bill.com",
    "noreply@ariba.com",
    "invoices@quickbooks.com",
    "AP@BILL.COM",
    "  ap@bill.com  ",
])
def test_known_aggregators_are_recognized(email: str) -> None:
    assert is_aggregator(email)


@pytest.mark.parametrize("email", [
    "billing@acmehauling.com",
    "ar@dtss.com",
    "",
    "not-an-email",
])
def test_direct_senders_are_not_aggregators(email: str) -> None:
    assert not is_aggregator(email)


def test_a_subdomain_of_an_aggregator_still_counts() -> None:
    """mail.bill.com is bill.com's mail, not a vendor called mail.bill.com."""
    assert is_aggregator("ap@mail.bill.com")


def test_a_domain_merely_containing_an_aggregator_name_does_not() -> None:
    """`notbill.com` and `bill.com.example.org` are different senders."""
    assert not is_aggregator("ap@notbill.com")
    assert not is_aggregator("ap@bill.com.example.org")


def test_the_denylist_is_not_empty() -> None:
    """An empty list makes every check above vacuously false."""
    assert AGGREGATOR_DOMAINS
