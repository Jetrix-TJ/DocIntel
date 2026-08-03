"""GUARDRAIL 9: a selector must READ a value, not RESTATE it.

The corpus is ten sample documents. Production will bring other invoices from
these same senders, and new senders entirely, and a selector is only worth
shipping if it would find the right value on a document nobody has seen. Two
authoring habits quietly break that while scoring perfectly here:

1. **The anchor is the value.** `{"field": "vendor_address", "anchor":
   "7935 Clayton Rd"}` says "to find the address, first find the address". It
   also interacts with a real mechanism: `_apply_field` puts the anchor's words
   in `skip` and `_candidates` drops them, so the anchored line is deleted from
   the captured block.

2. **The pattern is the value.** `{"pattern": "(1025 Eldorado Blvd.,
   Broomfield, CO 80021)"}` cannot return anything else. It is an assertion
   wearing an extractor's clothes: on the next invoice it either reproduces the
   baked-in string or yields nothing, and either way it never read the page.

Both pass every corpus-only test, which is standing rule 2 exactly - corpus-only
tests confirm corpus-fit and cannot detect corpus-overfit. This file is the
mechanical check, so the habit cannot spread silently.

The two debt lists below are the instances that predate this guardrail. They are
deliberately enumerated rather than tolerated by a blanket rule: the test fails
on a NEW instance, and it also fails when a listed entry is fixed and not
removed, so the lists can only shrink.
"""

from __future__ import annotations

import glob
import json
import os
import re

from docintel.scorecard import load_gold

# Named pattern types resolved by `patterns.resolve`. Anything else is a regex a
# persona author wrote, which is where a literal answer can hide.
NAMED_PATTERNS = frozenset({
    "currency", "currency_signed", "integer", "decimal", "date", "date_loose",
    "text", "text_block", "account_number", "phone", "postal_code", "tax_id",
    "digits_run",
})

# (persona, field) where the anchor is part of the value it captures.
#
# `edco/remit_address` CLEARED (task-6/8c). It anchored on `P.O. BOX 5488` - the
# first line of its own answer - because the honest anchor, the payee name printed
# above the block, occurs three times on the primary page and the remittance block
# is under the MIDDLE one, which neither `anchor_occurrence: "first"` nor `"last"`
# can reach. `anchor_occurrence: "mid_line"` reaches it (the stub prints the payee
# beside the bill-to column, so it is the only occurrence that does not begin its
# line), and the selector now anchors on `EDCO WASTE & RECYCLING SERVICE`.
#
# The two that remain are blocked on the column boundary, not on authoring: the
# line above each address is a payee name that also appears EARLIER on the page,
# and reaching the right occurrence leaves the fixed x-window contaminating the
# block. They clear when that boundary does.
# `upak/vendor_name` is the one to read the docstring of `test_scorecard.py` about:
# it is a DEAD selector (`same-row` + anchor-equals-value leaves an empty span)
# whose assertion passes only through the scorecard's `derived` fallback, and any
# working replacement would currently turn a passing assertion red. This guardrail
# found it independently, which is a useful sign the check is measuring something.
ANCHOR_IN_VALUE_DEBT = frozenset({
    ("federal_recycling", "vendor_address"),
    ("upak", "vendor_name"),
})

# (persona, field) where the pattern spells out the answer.
#
# **EMPTY, and it stays that way.** All sixteen entries were cleared, and the rule
# is now enforced at write time by grammar V14 (`_check_literal_capture`) rather
# than only here: a persona whose pattern captures fixed text on a whole-page
# region with no anchor is rejected by the validator, so it cannot reach the repo
# to be counted by this test. This list therefore has nothing left to tolerate,
# and `test_the_debt_lists_only_shrink` keeps it at nothing.
#
# How the sixteen were cleared, because the answer differed by field:
#
#   a printed label existed      anchor on it - `Make checks payable to`,
#                                `payable to`, `Name`, `cheque payable to`
#   a shape described the field  `(ATTN[ :][A-Z0-9 .,&'-]{2,40})` reads any
#                                attention line; a PO-box shape reads any stub
#   the print was unreadable     the pack's table supplies it: `DISPLAY_NAMES`
#                                for a logo that is an image, and the new
#                                `bill_to_roster` for the two telecom templates
#                                that print their bill-to with no label at all
#   neither applied              the selector was DELETED and the field is left
#                                empty for `core.coverage` to report -
#                                `edco/bill_to_attention` and
#                                `complete_beverage/bill_to_attention`, whose
#                                assertions were retired rather than faked
LITERAL_PATTERN_DEBT: frozenset[tuple[str, str]] = frozenset()


def _gold_by_persona() -> dict[str, dict[str, str]]:
    """Each persona's printed string fields, keyed by persona file stem."""
    out: dict[str, dict[str, str]] = {}
    for gold in load_gold():
        fields = {
            k: v for k, v in (gold.get("fields") or {}).items() if isinstance(v, str)
        }
        out[gold["gold_id"]] = fields
    return out


def _persona_files() -> list[tuple[str, dict]]:
    found = []
    for path in sorted(glob.glob("src/docintel/packs/*/personas/*.json")):
        with open(path) as fh:
            found.append((os.path.basename(path)[:-5], json.load(fh)))
    return found


def _gold_for(stem: str, gold: dict[str, dict[str, str]]) -> dict[str, str]:
    """The gold fields for a persona, matched on the fingerprint's vendor half."""
    probe = stem.replace("_", "")[:7]
    for gid, fields in gold.items():
        if probe in gid.replace("-", "").replace("_", ""):
            return fields
    return {}


def _alnum(text: str) -> str:
    """Letters and digits only, lowercased.

    Both sides of every comparison go through this. An earlier version stripped
    punctuation from the PATTERN and not from the gold value, so any literal
    containing a comma - which is most printed addresses and company names -
    escaped detection while the test still passed. Normalising one side only is
    the classic way a guardrail reports coverage it does not have.
    """
    return re.sub(r"[^a-z0-9]", "", text.lower())


def _literal_text(pattern: str) -> str:
    """The pattern's literal content, with regex machinery removed.

    Character classes and quantifiers are deleted whole rather than
    character-by-character, so a structural pattern reduces to nothing:
    `([0-9]{1,6} .{3,60}, [A-Z]{2} [0-9]{5})` -> `''`, while
    `(1025 Eldorado Blvd., Broomfield, CO 80021)` keeps every letter and digit.
    That difference is the entire signal this guardrail reads.
    """
    stripped = re.sub(r"\[[^\]]*\]", " ", pattern)   # character classes
    stripped = re.sub(r"\{[^}]*\}", " ", stripped)   # quantifiers
    stripped = re.sub(r"\\[a-zA-Z]", " ", stripped)  # \d \w \s escapes
    return _alnum(stripped)


def test_no_anchor_is_part_of_the_value_it_captures() -> None:
    gold = _gold_by_persona()
    offenders = set()
    for stem, persona in _persona_files():
        fields = _gold_for(stem, gold)
        for selector in persona["field_selectors"]:
            name, anchor = selector.get("field"), selector.get("anchor")
            if not name or not anchor or name not in fields:
                continue
            key = _alnum(anchor)
            if key and key in _alnum(fields[name]):
                offenders.add((stem, name))
    new = offenders - ANCHOR_IN_VALUE_DEBT
    assert not new, (
        f"anchor is part of the value it captures: {sorted(new)}. Anchor on stable "
        f"layout furniture (a label, the name line above) instead - the anchored "
        f"line is deleted from a text_block capture."
    )


def test_no_pattern_restates_the_value_it_should_read() -> None:
    gold = _gold_by_persona()
    offenders = set()
    for stem, persona in _persona_files():
        fields = _gold_for(stem, gold)
        for selector in persona["field_selectors"]:
            name, pattern = selector.get("field"), selector.get("pattern")
            if not name or not pattern or name not in fields:
                continue
            if pattern in NAMED_PATTERNS:
                continue
            literal = _literal_text(pattern)
            if len(literal) > 8 and literal in _alnum(fields[name]):
                offenders.add((stem, name))
    new = offenders - LITERAL_PATTERN_DEBT
    assert not new, (
        f"pattern spells out the value instead of describing its shape: "
        f"{sorted(new)}. Use a structural pattern - "
        f"'([0-9]{{1,6}} .{{3,60}}, [A-Z]{{2}} [0-9]{{5}})' reads any US street "
        f"address; '(1025 Eldorado Blvd., Broomfield, CO 80021)' reads exactly one."
    )


def test_the_debt_lists_only_shrink() -> None:
    """A fixed entry must be removed from its list.

    Without this the lists rot into permission slips: someone fixes a selector,
    leaves the entry behind, and the next author copies it as precedent.
    """
    gold = _gold_by_persona()
    anchors: set[tuple[str, str]] = set()
    literals: set[tuple[str, str]] = set()
    for stem, persona in _persona_files():
        fields = _gold_for(stem, gold)
        for selector in persona["field_selectors"]:
            name = selector.get("field")
            if not name or name not in fields:
                continue
            value = _alnum(fields[name])
            anchor = selector.get("anchor")
            if anchor and _alnum(anchor) and _alnum(anchor) in value:
                anchors.add((stem, name))
            pattern = selector.get("pattern")
            if pattern and pattern not in NAMED_PATTERNS:
                literal = _literal_text(pattern)
                if len(literal) > 8 and literal in value:
                    literals.add((stem, name))

    assert ANCHOR_IN_VALUE_DEBT - anchors == set(), (
        f"fixed, remove from ANCHOR_IN_VALUE_DEBT: "
        f"{sorted(ANCHOR_IN_VALUE_DEBT - anchors)}"
    )
    assert LITERAL_PATTERN_DEBT - literals == set(), (
        f"fixed, remove from LITERAL_PATTERN_DEBT: "
        f"{sorted(LITERAL_PATTERN_DEBT - literals)}"
    )
