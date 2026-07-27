# Document Processing Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A CLI that accepts any PDF and runs it through all 8 pipeline stages, emitting a schema-valid Stage 8 record, converging via a measured loop until all 10 gold documents pass end-to-end.

**Architecture:** Ports and adapters in Python. `core/` holds pure value types and functions with no dependencies. `extract/` turns PDFs (native or OCR) into one normalized `PageText` shape. `grammar/` executes declarative selectors against `PageText`. `pipeline/` sequences 10 stage modules and guarantees every document emits. `packs/` supply domain knowledge only. Build order is a thin end-to-end walking skeleton first (Part A), then a scorecard-driven convergence loop (Part B).

**Tech Stack:** Python 3.12 · pdfplumber 0.11.9 · pytesseract/tesseract · anthropic SDK (behind a port) · SQLite (stdlib) · pytest · ruff · mypy

## Global Constraints

Every task's requirements implicitly include this section. Values are copied verbatim from `docs/architecture/selector-grammar.md` and `docs/superpowers/specs/2026-07-27-pipeline-implementation-design.md`.

- **Python 3.12.** No web framework. Stdlib `sqlite3`, no ORM.
- **Money is `Decimal`, never `float`.** Arithmetic closure checks use **exact equality**, not tolerance.
- **`amount_payable` is `derived_only`.** It must never appear on `ExtractedFields`. Grammar rule V10.
- **Confidence:** boosts multiply to at most **×1.10**; a field may never exceed **0.99**.
- **Regex limits:** linear-time engine only, no backreferences, no lookbehind, max **200** characters, max **1** capture group, **50 ms** timeout per field per document, unbounded quantifiers (`.*`, `.+`) rejected unless bounded.
- **Persona limits:** serialized size ≤ **64 KB**; `few_shot_examples` ≤ **3**.
- **The invariant:** `count(intaken) == count(emitted)`. Every document emits a Stage 8 record, including skips and dead letters.
- **`docs/corpus/gold/*.json` is READ-ONLY.** Changing a gold value requires re-reading the source PDF and writing a justification in `.loop/journal.md`. The gold set is the spec.
- **`python3 docs/corpus/validate_gold.py` must stay green** at every commit (95 checks).
- **Runtime state lives in `var/`** (gitignored). Loop artifacts live in `.loop/` and ARE committed.
- Commit after every task. Never commit without the full test suite green.

## Confidence modifier values (exact)

Used by Task A5 and Cluster C3. From `selector-grammar.md` §5.

| Name | Multiplier |
|---|---|
| `soft_miss` | 0.80 |
| `draft_rules` | 0.85 |
| `ocr_source` | 0.90 |
| `ambiguous_anchor` | 0.90 |
| `anchor_alt_used` | 0.95 |
| `pattern_timeout` | 0.50 |
| `arith_lines_mismatch` | 0.85 |
| `arith_total_mismatch` | 0.85 |
| `arith_balance_mismatch` | 0.80 |
| `scanline_mismatch` | 0.85 |
| `filename_disagree` | 0.95 |
| `currency_inferred_weak` | 0.90 |
| `ambiguous_two_digit_year` | 0.95 |
| `handwriting_detected` | 0.60 |
| `high_skew` | 0.85 |
| `flattened_annotations` | 0.75 |

---

## File Structure

### Part A creates

| File | Responsibility |
|---|---|
| `pyproject.toml` | Package metadata, deps, pytest/ruff/mypy config |
| `src/docintel/__init__.py` | Version only |
| `src/docintel/core/money.py` | Parse every money notation in the corpus → signed `Decimal` |
| `src/docintel/core/dates.py` | Date parse ladder → ISO, with ambiguity flags |
| `src/docintel/core/models.py` | `Word`, `PageText`, `PageMeta`, `ExtractedFields`, `DerivedFields`, `ReferenceHit`, `JobContext` |
| `src/docintel/core/errors.py` | Error taxonomy |
| `src/docintel/core/confidence.py` | Modifier registry, multiplicative application, boost cap |
| `src/docintel/core/contract.py` | Stage 8 record construction + schema validation |
| `src/docintel/pipeline/hooks.py` | 8 sockets, chain dispatch with `next()`, failure isolation |
| `src/docintel/pipeline/runner.py` | Stage sequencing + the emit-always guarantee |
| `src/docintel/pipeline/stages/s1_intake.py` … `s8_emit.py` | 10 thin stage modules |
| `src/docintel/adapters/intake/port.py` + `filesystem.py` | `IntakeItem` source |
| `src/docintel/adapters/vision/port.py` + `fake.py` | Vision port + deterministic fake |
| `src/docintel/cli.py` | `process`, `replay-gold` |
| `src/docintel/scorecard.py` | Gold comparison → machine-readable scorecard |

### Part B creates (per cluster)

| Cluster | Files |
|---|---|
| C1 extract | `extract/{pdf,ocr,normalize,annotations,pageroles,scanline}.py` |
| C2 grammar | `grammar/{schema,validator,patterns,regions,executor}.py` |
| C3 ops + capture | `grammar/ops/{base,derive,crosscheck,infer}.py`, real `s6_capture.py` |
| C4 gate | real `s7_gate.py` |
| C5 packs | `packs/registry.py`, `packs/northstar/*`, `packs/digitaldirection/*`, 8 persona JSON files |
| C6 vision | `adapters/vision/{anthropic,cassette}.py`, real `s5b_vision.py` |
| C7 persona store | `personas/{store,export}.py`, real `s4_persona.py`, `s5c_agent.py` |

---

# PART A — Bootstrap (linear, 11 tasks)

Part A is not iterative. It ends when: any PDF traverses all 8 stages and emits a valid record, `replay-gold --json` produces a scorecard, and the invariant test passes. **Correctness is expected to be near zero.** Part A builds the instrument; Part B moves the needle.

---

### Task A1: Project scaffold + Money

**Files:**
- Create: `pyproject.toml`, `src/docintel/__init__.py`, `src/docintel/core/__init__.py`, `src/docintel/core/money.py`
- Test: `tests/core/test_money.py`

**Interfaces:**
- Consumes: nothing
- Produces: `parse_money(raw: str) -> Decimal | None`, `is_money(raw: str) -> bool`, `MONEY_RE: re.Pattern`

Scaffold is folded in here because a scaffold alone is not testable; money is the first pure unit and the one every later calculation depends on.

- [ ] **Step 1: Write the failing test**

Every literal below is copied from a real corpus document. Do not simplify this list.

```python
# tests/core/test_money.py
from decimal import Decimal
import pytest
from docintel.core.money import parse_money, is_money


@pytest.mark.parametrize("raw,expected", [
    # plain
    ("699.00", Decimal("699.00")),
    ("1,177.70", Decimal("1177.70")),
    ("$1,177.70", Decimal("1177.70")),
    ("4,908.00", Decimal("4908.00")),
    ("83.7900", Decimal("83.7900")),        # Veritiv unit price, 4dp
    ("0.027", Decimal("0.027")),            # CBD environmental fee
    ("$.00", Decimal("0.00")),              # Windstream "Amount Previously Due"
    # negatives, three notations
    ("-99.80", Decimal("-99.80")),          # Federal Recycling OCC
    ("-40.500", Decimal("-40.500")),        # U-Pak cardboard weights
    ("(249.84)", Decimal("-249.84")),       # Lumen payment received
    ("212.87 cr", Decimal("-212.87")),      # Comcast credit card payment
    ("$1,231.74 CR", Decimal("-1231.74")),  # Windstream payments/adjustments
    # currency suffix
    ("481.20 USD", Decimal("481.20")),
    ("14789.77", Decimal("14789.77")),
    # rate notation - the number only
    ("-40.00/ST", Decimal("-40.00")),
])
def test_parse_money(raw, expected):
    assert parse_money(raw) == expected


@pytest.mark.parametrize("raw", [
    "123142812RT0001",   # U-Pak HST registration number - NOT money (F14)
    "0384043574",        # Centracom account number
    "8495 44 462 0365242",
    "416-675-3700",
    "NO MARKET VALUE",
    "",
    "Total",
])
def test_not_money(raw):
    assert parse_money(raw) is None
    assert is_money(raw) is False


def test_exact_decimal_no_float_drift():
    """The F8 closure checks demand exact equality, so parsing must not go via float."""
    assert parse_money("298.34") + parse_money("69.62") == Decimal("367.96")
    assert parse_money("13752.60") + parse_money("20123.80") == Decimal("33876.40")
    assert parse_money("0.027") * Decimal(4000) == Decimal("108.000")


def test_tax_id_is_not_money_even_though_it_has_digits():
    """H.S.T. # 123142812RT0001   2,325.69 - a naive number grab takes the wrong token."""
    assert parse_money("123142812RT0001") is None
    assert parse_money("2,325.69") == Decimal("2325.69")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_money.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel'`

- [ ] **Step 3: Create the scaffold**

```toml
# pyproject.toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "docintel"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "pdfplumber==0.11.9",
    "pytesseract>=0.3.10",
    "Pillow>=10.0",
]

[project.optional-dependencies]
dev = ["pytest>=8.0", "ruff>=0.5", "mypy>=1.10"]
vision = ["anthropic>=0.40"]

[project.scripts]
docintel = "docintel.cli:main"

[tool.setuptools.packages.find]
where = ["src"]

[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.mypy]
files = ["src/docintel/core", "src/docintel/grammar"]
python_version = "3.12"
strict = true
```

```python
# src/docintel/__init__.py
__version__ = "0.1.0"
```

```python
# src/docintel/core/__init__.py
```

- [ ] **Step 4: Write the money implementation**

```python
# src/docintel/core/money.py
"""Money parsing for every notation the corpus actually uses.

Decimal throughout, never float: the F8 arithmetic-closure checks demand exact
equality, and a float tolerance is where bugs hide.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

# A money token: optional currency symbol, digit groups, required decimal part.
# The required decimal part is what keeps account numbers and tax IDs out.
MONEY_RE = re.compile(
    r"""
    ^\s*
    (?P<open_paren>\()?
    \s*
    (?P<sign>-)?
    \s*
    [$€£]?
    \s*
    (?P<num>
        (?:\d{1,3}(?:,\d{3})+ | \d*)     # grouped or bare integer part
        \.\d{1,4}                         # REQUIRED decimal part, 1-4 places
    )
    \s*
    (?P<close_paren>\))?
    \s*
    (?:/[A-Za-z]{1,4})?                   # rate suffix: -40.00/ST
    \s*
    (?:USD|CAD|EUR|GBP)?
    \s*
    (?P<cr>cr|CR)?
    \s*$
    """,
    re.VERBOSE,
)


def parse_money(raw: str) -> Decimal | None:
    """Parse a money token to a signed Decimal, or None if not money-shaped.

    Negative is expressed three different ways across the corpus and all three
    must normalize to a leading minus:
      -99.80        Federal Recycling line amounts
      (249.84)      Lumen "Payment Received"
      212.87 cr     Comcast credit-card payment
    """
    if not raw:
        return None
    m = MONEY_RE.match(raw)
    if m is None:
        return None

    num = m.group("num").replace(",", "")
    if num.startswith("."):
        num = "0" + num
    try:
        value = Decimal(num)
    except InvalidOperation:
        return None

    negative = bool(m.group("sign")) or bool(m.group("cr"))
    if m.group("open_paren") and m.group("close_paren"):
        negative = True
    return -value if negative else value


def is_money(raw: str) -> bool:
    return parse_money(raw) is not None
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pip install -e '.[dev]' && python3 -m pytest tests/core/test_money.py -v`
Expected: PASS, 25 tests

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml src/docintel/__init__.py src/docintel/core/ tests/core/test_money.py
git commit -m "feat(core): project scaffold and Decimal money parsing"
```

---

### Task A2: Date parsing

**Files:**
- Create: `src/docintel/core/dates.py`
- Test: `tests/core/test_dates.py`

**Interfaces:**
- Consumes: nothing
- Produces: `DateResult` (frozen dataclass: `iso: str | None`, `raw: str`, `parsed: bool`, `ambiguous_two_digit_year: bool`), `parse_date(raw: str) -> DateResult`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_dates.py
import pytest
from docintel.core.dates import parse_date


@pytest.mark.parametrize("raw,iso", [
    ("9/15/2025", "2025-09-15"),            # D.T.S.S.
    ("08/14/2025", "2025-08-14"),           # Veritiv
    ("10/24/2025", "2025-10-24"),           # Complete Beverage
    ("05/31/2025", "2025-05-31"),           # Federal Recycling
    ("Dec 09, 2025", "2025-12-09"),         # Comcast
    ("September 01, 2025", "2025-09-01"),   # Lumen
    ("January 01, 2026", "2026-01-01"),     # Centracom
    ("July 22, 2025", "2025-07-22"),        # Windstream
    ("MARCH 31, 2025", "2025-03-31"),       # U-Pak service dates, all caps
])
def test_parse_date(raw, iso):
    r = parse_date(raw)
    assert r.parsed is True
    assert r.iso == iso
    assert r.ambiguous_two_digit_year is False


def test_two_digit_year_parses_but_is_flagged():
    """U-Pak 03/31/25 and EDCO 04/30/25 - resolvable but must carry a penalty."""
    r = parse_date("03/31/25")
    assert r.iso == "2025-03-31"
    assert r.ambiguous_two_digit_year is True


@pytest.mark.parametrize("raw", [
    "25TH OF THE MONTH",   # Centracom due date - NOT a date (F9)
    "EOM plus 15",         # Federal Recycling payment terms
    "Due on receipt",      # D.T.S.S.
    "Net 30",
    "",
])
def test_unparseable_passes_through_without_inventing_a_day(raw):
    r = parse_date(raw)
    assert r.parsed is False
    assert r.iso is None
    assert r.raw == raw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_dates.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.core.dates'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/core/dates.py
"""Date parsing ladder.

Never invents a value. Centracom's due date is literally "25TH OF THE MONTH";
passing that through unparsed is correct behaviour, not a failure (F9).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

_NUMERIC = re.compile(r"^\s*(\d{1,2})/(\d{1,2})/(\d{2}|\d{4})\s*$")
_MONTH_NAME = re.compile(r"^\s*([A-Za-z]{3,9})\s+(\d{1,2}),?\s+(\d{4})\s*$")

_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9,
    "oct": 10, "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


@dataclass(frozen=True)
class DateResult:
    raw: str
    iso: str | None
    parsed: bool
    ambiguous_two_digit_year: bool


def _ok(raw: str, y: int, m: int, d: int, ambiguous: bool) -> DateResult:
    try:
        iso = date(y, m, d).isoformat()
    except ValueError:
        return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)
    return DateResult(raw=raw, iso=iso, parsed=True, ambiguous_two_digit_year=ambiguous)


def parse_date(raw: str) -> DateResult:
    if not raw:
        return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)

    m = _NUMERIC.match(raw)
    if m:
        month, day, year_s = int(m.group(1)), int(m.group(2)), m.group(3)
        ambiguous = len(year_s) == 2
        year = 2000 + int(year_s) if ambiguous else int(year_s)
        return _ok(raw, year, month, day, ambiguous)

    m = _MONTH_NAME.match(raw)
    if m:
        month = _MONTHS.get(m.group(1).lower())
        if month is not None:
            return _ok(raw, int(m.group(3)), month, int(m.group(2)), False)

    return DateResult(raw=raw, iso=None, parsed=False, ambiguous_two_digit_year=False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_dates.py -v`
Expected: PASS, 15 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/core/dates.py tests/core/test_dates.py
git commit -m "feat(core): date parse ladder with two-digit-year flagging"
```

---

### Task A3: Core models with the extracted/derived type split

**Files:**
- Create: `src/docintel/core/models.py`
- Test: `tests/core/test_models.py`

**Interfaces:**
- Consumes: `docintel.core.money`
- Produces:
  - `Word(text: str, x0: float, y0: float, x1: float, y1: float)` frozen
  - `PageText(page_number: int, words: tuple[Word, ...], width: float, height: float, source: str)` frozen, with `.text` property and `.lines()` method
  - `PageRole = Literal["primary", "supporting", "unknown"]`
  - `PageMeta(page_number: int, char_count: int, image_count: int, annot_count: int, role: PageRole)` frozen
  - `ReferenceHit(value: str, source_field: str, page: int, pattern_id: str)` frozen
  - `ExtractedFields` with `set(name, value, match_quality)`, `get(name)`, `.values`, `.match_quality`
  - `DerivedFields` with `set(name, value)`, `get(name)`, `.values`
  - `JobContext` mutable dataclass, `new_context(document_id, source_path, ...) -> JobContext`

This is the task that makes grammar rule V10 structurally true.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_models.py
from decimal import Decimal
import pytest
from docintel.core.models import (
    DerivedFields, ExtractedFields, PageText, ReferenceHit, Word, new_context,
)

DERIVED_ONLY = {"amount_payable", "payable_basis", "document_identity", "identity_basis"}


def test_extracted_fields_refuse_derived_only_names():
    """Grammar V10: no selector may target amount_payable. Enforced by type, not convention."""
    ef = ExtractedFields()
    for name in DERIVED_ONLY:
        with pytest.raises(ValueError, match="derived_only"):
            ef.set(name, Decimal("13752.60"), match_quality=1.0)


def test_extracted_fields_accept_printed_values():
    ef = ExtractedFields()
    ef.set("total_printed", Decimal("33876.40"), match_quality=0.98)
    ef.set("current_charges", Decimal("13752.60"), match_quality=0.97)
    assert ef.get("total_printed") == Decimal("33876.40")
    assert ef.match_quality["current_charges"] == 0.97


def test_derived_fields_accept_amount_payable():
    df = DerivedFields()
    df.set("amount_payable", Decimal("13752.60"))
    df.set("payable_basis", "current_charges")
    assert df.get("amount_payable") == Decimal("13752.60")


def test_pagetext_lines_groups_words_by_row():
    words = (
        Word("CURRENT", 10.0, 100.0, 60.0, 110.0),
        Word("CHARGES:", 62.0, 100.0, 120.0, 110.0),
        Word("69.62", 300.0, 100.0, 340.0, 110.0),
        Word("BALANCE", 10.0, 130.0, 70.0, 140.0),
    )
    page = PageText(page_number=1, words=words, width=612.0, height=792.0, source="native")
    lines = page.lines()
    assert len(lines) == 2
    assert [w.text for w in lines[0]] == ["CURRENT", "CHARGES:", "69.62"]
    assert "CURRENT CHARGES: 69.62" in page.text


def test_pagetext_source_is_constrained():
    with pytest.raises(ValueError):
        PageText(page_number=1, words=(), width=1.0, height=1.0, source="magic")


def test_new_context_starts_with_the_invariant_unsatisfied():
    ctx = new_context(document_id="doc1", source_path="/tmp/x.pdf")
    assert ctx.emitted is False
    assert ctx.disposition == "processed"
    assert ctx.reference_list == []
    assert ctx.modifiers == []


def test_reference_hit_carries_provenance():
    """F11: reference_list is objects, not strings, so annotation-sourced keys stay identifiable."""
    hit = ReferenceHit(value="2436687", source_field="Reference", page=1, pattern_id="ref_column")
    assert hit.source_field == "Reference"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.core.models'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/core/models.py
"""Value types threaded through the pipeline.

The ExtractedFields / DerivedFields split is load-bearing. On 7 of the 10 corpus
documents a selector pointed straight at amount_payable would produce the right
answer, which makes the F1 bug invisible to casual testing. Separating the types
makes grammar rule V10 impossible to violate rather than merely forbidden.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

PageRole = Literal["primary", "supporting", "unknown"]
TextSource = Literal["native", "ocr"]
Disposition = Literal["processed", "skipped", "dead_letter"]
PersonaStatus = Literal["hit", "soft_miss", "hard_miss"]

# Fields that may only ever be computed by an adjust op, never read off a page.
DERIVED_ONLY: frozenset[str] = frozenset({
    "amount_payable",
    "payable_basis",
    "document_identity",
    "identity_basis",
    "carried_balance",
})

_LINE_TOLERANCE = 3.0  # points; words within this vertical distance share a line


@dataclass(frozen=True)
class Word:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True)
class PageText:
    """Normalized page text. Identical shape whether it came from pdfplumber or OCR.

    This is the seam that makes OCR cheap (F2): grammar/executor never learns
    which source produced it.
    """

    page_number: int
    words: tuple[Word, ...]
    width: float
    height: float
    source: TextSource

    def __post_init__(self) -> None:
        if self.source not in ("native", "ocr"):
            raise ValueError(f"source must be 'native' or 'ocr', got {self.source!r}")

    def lines(self) -> list[list[Word]]:
        """Group words into visual lines, each sorted left to right."""
        out: list[list[Word]] = []
        for w in sorted(self.words, key=lambda w: (w.y0, w.x0)):
            if out and abs(out[-1][0].y0 - w.y0) <= _LINE_TOLERANCE:
                out[-1].append(w)
            else:
                out.append([w])
        for line in out:
            line.sort(key=lambda w: w.x0)
        return out

    @property
    def text(self) -> str:
        return "\n".join(" ".join(w.text for w in line) for line in self.lines())


@dataclass(frozen=True)
class PageMeta:
    page_number: int
    char_count: int
    image_count: int
    annot_count: int
    role: PageRole = "unknown"


@dataclass(frozen=True)
class ReferenceHit:
    value: str
    source_field: str
    page: int
    pattern_id: str


@dataclass
class ExtractedFields:
    """Values read off the page. Never holds a derived field."""

    values: dict[str, Any] = field(default_factory=dict)
    match_quality: dict[str, float] = field(default_factory=dict)

    def set(self, name: str, value: Any, match_quality: float) -> None:
        if name in DERIVED_ONLY:
            raise ValueError(
                f"{name!r} is derived_only (grammar V10) and cannot be extracted; "
                "compute it with an adjust op and store it on DerivedFields"
            )
        self.values[name] = value
        self.match_quality[name] = match_quality

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)


@dataclass
class DerivedFields:
    """Values computed by adjust ops from extracted values."""

    values: dict[str, Any] = field(default_factory=dict)

    def set(self, name: str, value: Any) -> None:
        self.values[name] = value

    def get(self, name: str, default: Any = None) -> Any:
        return self.values.get(name, default)


@dataclass
class JobContext:
    # identity (s1)
    document_id: str
    source_path: str
    received_at: str = ""
    sender_email: str | None = None
    email_id: str | None = None
    possible_duplicate_of: str | None = None
    suspected_batch: bool = False

    # text (s2)
    pages: tuple[PageText, ...] = ()
    page_meta: tuple[PageMeta, ...] = ()
    text_source: str = "native"

    # classification (s3)
    doc_type: str | None = None
    tags: list[str] = field(default_factory=list)
    classification_confidence: float | None = None
    signal_that_fired: str | None = None

    # persona (s4)
    sender_fingerprint: str | None = None
    persona: Any | None = None
    persona_status: PersonaStatus | None = None
    extraction_rule_version: str | None = None

    # extraction (s5*)
    extracted: ExtractedFields = field(default_factory=ExtractedFields)
    derived: DerivedFields = field(default_factory=DerivedFields)
    reference_list: list[ReferenceHit] = field(default_factory=list)
    extraction_route: str | None = None

    # capture + gate (s6, s7)
    confidence: dict[str, float] = field(default_factory=dict)
    modifiers: list[str] = field(default_factory=list)
    lane: str | None = None
    review_flag: bool = False
    regen_flag: bool = False
    audit_sample: bool = False

    # emit (s8)
    disposition: Disposition = "processed"
    skip_reason: str | None = None
    emitted: bool = False
    events: list[str] = field(default_factory=list)

    def add_modifier(self, name: str) -> None:
        if name not in self.modifiers:
            self.modifiers.append(name)

    def add_tag(self, name: str) -> None:
        if name not in self.tags:
            self.tags.append(name)

    def log(self, message: str) -> None:
        self.events.append(message)


def new_context(document_id: str, source_path: str, **kwargs: Any) -> JobContext:
    return JobContext(document_id=document_id, source_path=source_path, **kwargs)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_models.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/core/models.py tests/core/test_models.py
git commit -m "feat(core): job context with structural extracted/derived split (V10)"
```

---

### Task A4: Error taxonomy and confidence

**Files:**
- Create: `src/docintel/core/errors.py`, `src/docintel/core/confidence.py`
- Test: `tests/core/test_confidence.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `DocIntelError`, `TransientError`, `PermanentError`, `PackError`, `ValidationError`, `ContractError`
  - `MODIFIERS: dict[str, Decimal]`, `BOOST_CAP: Decimal`, `CEILING: Decimal`
  - `apply_modifiers(base: float, names: Sequence[str]) -> float`
  - `apply_boosts(base: float, count: int) -> float`

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_confidence.py
import pytest
from docintel.core.confidence import (
    BOOST_CAP, CEILING, MODIFIERS, apply_boosts, apply_modifiers,
)


def test_all_sixteen_modifiers_are_registered():
    """The modifier enum is closed - selector-grammar.md section 5."""
    assert len(MODIFIERS) == 16
    assert float(MODIFIERS["soft_miss"]) == 0.80
    assert float(MODIFIERS["ocr_source"]) == 0.90
    assert float(MODIFIERS["pattern_timeout"]) == 0.50
    assert float(MODIFIERS["flattened_annotations"]) == 0.75
    assert float(MODIFIERS["arith_balance_mismatch"]) == 0.80


def test_modifiers_are_multiplicative_and_composable():
    # draft rules on an OCR'd document
    assert apply_modifiers(1.0, ["draft_rules", "ocr_source"]) == pytest.approx(0.765)


def test_unknown_modifier_is_rejected():
    with pytest.raises(ValueError, match="unknown confidence modifier"):
        apply_modifiers(1.0, ["vibes"])


def test_modifier_order_does_not_matter():
    a = apply_modifiers(1.0, ["ocr_source", "soft_miss"])
    b = apply_modifiers(1.0, ["soft_miss", "ocr_source"])
    assert a == pytest.approx(b)


def test_boosts_are_capped_at_1_10():
    assert apply_boosts(0.50, count=99) == pytest.approx(0.50 * float(BOOST_CAP))


def test_boost_can_never_exceed_the_ceiling():
    """Three agreeing renderings of an OCR'd number can still all be wrong the same way."""
    assert apply_boosts(0.98, count=3) == pytest.approx(float(CEILING))
    assert apply_boosts(1.0, count=1) == pytest.approx(float(CEILING))


def test_confidence_floors_at_zero():
    assert apply_modifiers(0.0, ["pattern_timeout"]) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_confidence.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.core.confidence'`

- [ ] **Step 3: Write the implementations**

```python
# src/docintel/core/errors.py
"""Error taxonomy. Every class still results in an emitted Stage 8 record."""


class DocIntelError(Exception):
    """Base for everything this package raises."""


class TransientError(DocIntelError):
    """Retry with backoff; on exhaustion route to the dead-letter queue."""


class PermanentError(DocIntelError):
    """Corrupt or unsupported input. DLQ + disposition dead_letter."""


class PackError(DocIntelError):
    """A pack hook threw. This document goes to the DLQ; the run continues."""


class ValidationError(DocIntelError):
    """A persona write violated the closed grammar (V1-V13). Whole write rejected."""


class ContractError(DocIntelError):
    """An emitted record failed Stage 8 schema validation."""
```

```python
# src/docintel/core/confidence.py
"""The closed confidence-modifier enum.

One mechanism, multiplicative, every applied modifier recorded on the emitted
record (spec Stage 6). There is deliberately no other way to lower confidence.
"""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal

MODIFIERS: dict[str, Decimal] = {
    "soft_miss": Decimal("0.80"),
    "draft_rules": Decimal("0.85"),
    "ocr_source": Decimal("0.90"),
    "ambiguous_anchor": Decimal("0.90"),
    "anchor_alt_used": Decimal("0.95"),
    "pattern_timeout": Decimal("0.50"),
    "arith_lines_mismatch": Decimal("0.85"),
    "arith_total_mismatch": Decimal("0.85"),
    "arith_balance_mismatch": Decimal("0.80"),
    "scanline_mismatch": Decimal("0.85"),
    "filename_disagree": Decimal("0.95"),
    "currency_inferred_weak": Decimal("0.90"),
    "ambiguous_two_digit_year": Decimal("0.95"),
    "handwriting_detected": Decimal("0.60"),
    "high_skew": Decimal("0.85"),
    "flattened_annotations": Decimal("0.75"),
}

BOOST_CAP = Decimal("1.10")
CEILING = Decimal("0.99")
_PER_BOOST = Decimal("1.03")


def apply_modifiers(base: float, names: Sequence[str]) -> float:
    value = Decimal(str(base))
    for name in names:
        if name not in MODIFIERS:
            raise ValueError(f"unknown confidence modifier: {name!r}")
        value *= MODIFIERS[name]
    return float(max(Decimal("0"), value))


def apply_boosts(base: float, count: int) -> float:
    """Corroboration raises confidence, but only a little and never to certainty."""
    if count <= 0:
        return base
    factor = min(BOOST_CAP, _PER_BOOST ** count)
    return float(min(CEILING, Decimal(str(base)) * factor))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_confidence.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/core/errors.py src/docintel/core/confidence.py tests/core/test_confidence.py
git commit -m "feat(core): error taxonomy and closed confidence-modifier enum"
```

---

### Task A5: Stage 8 contract

**Files:**
- Create: `src/docintel/core/contract.py`
- Test: `tests/core/test_contract.py`

**Interfaces:**
- Consumes: `docintel.core.models`, `docintel.core.errors`
- Produces: `SCHEMA_VERSION: str`, `REQUIRED_KEYS: frozenset[str]`, `build_record(ctx: JobContext) -> dict`, `validate_record(rec: dict) -> None`

Includes the 5 corpus-analysis §6 deltas: `text_source`, `document_identity`, `identity_basis`, `page_roles`, and `reference_list` as objects.

- [ ] **Step 1: Write the failing test**

```python
# tests/core/test_contract.py
from decimal import Decimal
import pytest
from docintel.core.contract import (
    REQUIRED_KEYS, SCHEMA_VERSION, build_record, validate_record,
)
from docintel.core.errors import ContractError
from docintel.core.models import PageMeta, ReferenceHit, new_context


def _ctx():
    ctx = new_context(document_id="d1", source_path="/tmp/a.pdf")
    ctx.doc_type = "telecom_bill"
    ctx.sender_fingerprint = "centracom|centracom"
    ctx.text_source = "native"
    ctx.extraction_rule_version = "v1"
    ctx.page_meta = (PageMeta(1, 1209, 15, 0, "primary"),)
    ctx.extracted.set("total_printed", Decimal("33876.40"), 0.98)
    ctx.derived.set("amount_payable", Decimal("13752.60"))
    ctx.derived.set("payable_basis", "current_charges")
    ctx.derived.set("document_identity", "0384043574|2026-01-01")
    ctx.derived.set("identity_basis", "account_period")
    ctx.confidence["total_printed"] = 0.98
    ctx.reference_list.append(ReferenceHit("0384043574", "Account Number", 1, "account"))
    return ctx


def test_record_has_every_required_key():
    rec = build_record(_ctx())
    assert REQUIRED_KEYS <= set(rec)
    validate_record(rec)


def test_schema_version_is_stamped():
    assert build_record(_ctx())["schema_version"] == SCHEMA_VERSION


def test_money_serializes_as_string_not_float():
    """Decimal must survive the contract boundary without float drift."""
    rec = build_record(_ctx())
    assert rec["fields"]["total_printed"] == "33876.40"
    assert rec["derived"]["amount_payable"] == "13752.60"


def test_reference_list_entries_are_objects_with_provenance():
    rec = build_record(_ctx())
    assert rec["reference_list"] == [
        {"value": "0384043574", "source_field": "Account Number",
         "page": 1, "pattern_id": "account"}
    ]


def test_text_source_and_page_roles_are_present():
    rec = build_record(_ctx())
    assert rec["text_source"] == "native"
    assert rec["page_roles"] == ["primary"]


def test_skipped_document_still_produces_a_valid_record():
    """Spec Stage 2: never silently drop."""
    ctx = new_context(document_id="d2", source_path="/tmp/b.png")
    ctx.disposition = "skipped"
    ctx.skip_reason = "file type not in allowlist"
    rec = build_record(ctx)
    validate_record(rec)
    assert rec["disposition"] == "skipped"
    assert rec["reason"] == "file type not in allowlist"


def test_dead_letter_still_produces_a_valid_record():
    ctx = new_context(document_id="d3", source_path="/tmp/c.pdf")
    ctx.disposition = "dead_letter"
    ctx.skip_reason = "corrupt PDF"
    rec = build_record(ctx)
    validate_record(rec)
    assert rec["disposition"] == "dead_letter"


def test_validate_rejects_missing_key():
    rec = build_record(_ctx())
    del rec["disposition"]
    with pytest.raises(ContractError, match="disposition"):
        validate_record(rec)


def test_validate_rejects_unknown_disposition():
    rec = build_record(_ctx())
    rec["disposition"] = "maybe"
    with pytest.raises(ContractError, match="disposition"):
        validate_record(rec)


def test_validate_rejects_float_money():
    rec = build_record(_ctx())
    rec["fields"]["total_printed"] = 33876.40
    with pytest.raises(ContractError, match="string"):
        validate_record(rec)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/core/test_contract.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.core.contract'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/core/contract.py
"""The Stage 8 record: the only interface downstream systems see.

Includes the five deltas from corpus-analysis.md section 6: text_source,
document_identity, identity_basis, page_roles, and reference_list as objects.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from docintel.core.errors import ContractError
from docintel.core.models import JobContext

SCHEMA_VERSION = "1"

REQUIRED_KEYS = frozenset({
    "schema_version", "doc_type", "sender_fingerprint", "fields", "derived",
    "confidence", "reference_list", "extraction_rule_version",
    "confidence_modifiers", "possible_duplicate_of", "disposition",
    "review_flag", "regen_flag", "audit_sample", "text_source", "page_roles",
    "tags", "document_id",
})

_DISPOSITIONS = {"processed", "skipped", "dead_letter"}


def _serialize(value: Any) -> Any:
    """Decimal becomes a string so no consumer can accidentally use a float."""
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, dict):
        return {k: _serialize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_serialize(v) for v in value]
    return value


def build_record(ctx: JobContext) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "document_id": ctx.document_id,
        "doc_type": ctx.doc_type,
        "tags": list(ctx.tags),
        "sender_fingerprint": ctx.sender_fingerprint,
        "text_source": ctx.text_source,
        "page_roles": [m.role for m in ctx.page_meta],
        "fields": _serialize(ctx.extracted.values),
        "derived": _serialize(ctx.derived.values),
        "confidence": dict(ctx.confidence),
        "confidence_modifiers": list(ctx.modifiers),
        "reference_list": [
            {"value": r.value, "source_field": r.source_field,
             "page": r.page, "pattern_id": r.pattern_id}
            for r in ctx.reference_list
        ],
        "extraction_rule_version": ctx.extraction_rule_version,
        "extraction_route": ctx.extraction_route,
        "possible_duplicate_of": ctx.possible_duplicate_of,
        "disposition": ctx.disposition,
        "reason": ctx.skip_reason,
        "review_flag": ctx.review_flag,
        "regen_flag": ctx.regen_flag,
        "audit_sample": ctx.audit_sample,
        "lane": ctx.lane,
    }


def validate_record(rec: dict[str, Any]) -> None:
    missing = REQUIRED_KEYS - set(rec)
    if missing:
        raise ContractError(f"record missing required keys: {sorted(missing)}")

    if rec["disposition"] not in _DISPOSITIONS:
        raise ContractError(
            f"disposition must be one of {sorted(_DISPOSITIONS)}, got {rec['disposition']!r}"
        )

    for bucket in ("fields", "derived"):
        for name, value in rec[bucket].items():
            if isinstance(value, float):
                raise ContractError(
                    f"{bucket}.{name} is a float; money must cross the contract as a string"
                )

    for entry in rec["reference_list"]:
        if set(entry) != {"value", "source_field", "page", "pattern_id"}:
            raise ContractError(f"reference_list entry has wrong shape: {entry!r}")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/core/test_contract.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/core/contract.py tests/core/test_contract.py
git commit -m "feat(core): Stage 8 record contract with corpus-analysis deltas"
```

---

### Task A6: Hook sockets with failure isolation

**Files:**
- Create: `src/docintel/pipeline/__init__.py`, `src/docintel/pipeline/hooks.py`
- Test: `tests/pipeline/test_hooks.py`

**Interfaces:**
- Consumes: `docintel.core.models`, `docintel.core.errors`
- Produces: `SOCKETS: tuple[str, ...]` (8 names), `HookFn` type alias, `HookRegistry` with `.register(socket, fn, pack)`, `.run(socket, ctx) -> JobContext`, `.registered(socket) -> list[str]`

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_hooks.py
import pytest
from docintel.core.errors import PackError
from docintel.core.models import new_context
from docintel.pipeline.hooks import SOCKETS, HookRegistry


def test_eight_sockets_exactly():
    assert SOCKETS == (
        "beforeIntake", "afterFilter", "classifySignals", "beforePersonaLookup",
        "afterExtraction", "beforeConfidenceGate", "beforeEmit", "onRegenTrigger",
    )


def test_registering_an_unknown_socket_fails_loudly():
    reg = HookRegistry()
    with pytest.raises(ValueError, match="unknown socket"):
        reg.register("afterLunch", lambda ctx, nxt: nxt(ctx), pack="test")


def test_chain_runs_in_registration_order():
    reg = HookRegistry()

    def a(ctx, nxt):
        ctx.log("a")
        return nxt(ctx)

    def b(ctx, nxt):
        ctx.log("b")
        return nxt(ctx)

    reg.register("afterFilter", a, pack="p1")
    reg.register("afterFilter", b, pack="p1")
    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    assert ctx.events == ["a", "b"]


def test_hook_can_short_circuit_by_not_calling_next():
    reg = HookRegistry()
    reg.register("afterFilter", lambda ctx, nxt: ctx, pack="p1")
    reg.register("afterFilter", lambda ctx, nxt: (ctx.log("never"), nxt(ctx))[1], pack="p1")
    ctx = reg.run("afterFilter", new_context("d", "/x.pdf"))
    assert ctx.events == []


def test_a_throwing_hook_raises_PackError_naming_the_pack():
    """Spec Part 4: a throwing hook never crashes the run; the runner routes it to the DLQ."""
    reg = HookRegistry()

    def boom(ctx, nxt):
        raise RuntimeError("pack bug")

    reg.register("afterExtraction", boom, pack="northstar")
    with pytest.raises(PackError, match="northstar"):
        reg.run("afterExtraction", new_context("d", "/x.pdf"))


def test_empty_socket_is_a_no_op():
    reg = HookRegistry()
    ctx_in = new_context("d", "/x.pdf")
    assert reg.run("beforeEmit", ctx_in) is ctx_in


def test_registered_reports_pack_qualified_names():
    reg = HookRegistry()
    reg.register("beforeEmit", lambda ctx, nxt: nxt(ctx), pack="northstar")
    assert reg.registered("beforeEmit") == ["northstar.<lambda>"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/pipeline/test_hooks.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.pipeline'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/pipeline/hooks.py
"""The 8 hook sockets.

Middleware chains, same shape as Express.js: each function receives the context
and a next(). It can transform and pass along, stop the chain by not calling
next(), or throw - in which case the document goes to the dead-letter queue and
the run continues (spec Part 4).
"""

from __future__ import annotations

from collections.abc import Callable

from docintel.core.errors import PackError
from docintel.core.models import JobContext

SOCKETS: tuple[str, ...] = (
    "beforeIntake",
    "afterFilter",
    "classifySignals",
    "beforePersonaLookup",
    "afterExtraction",
    "beforeConfidenceGate",
    "beforeEmit",
    "onRegenTrigger",
)

Next = Callable[[JobContext], JobContext]
HookFn = Callable[[JobContext, Next], JobContext]


class HookRegistry:
    def __init__(self) -> None:
        self._chains: dict[str, list[tuple[str, HookFn]]] = {s: [] for s in SOCKETS}

    def register(self, socket: str, fn: HookFn, pack: str) -> None:
        if socket not in self._chains:
            raise ValueError(f"unknown socket {socket!r}; expected one of {list(SOCKETS)}")
        self._chains[socket].append((pack, fn))

    def registered(self, socket: str) -> list[str]:
        return [f"{pack}.{fn.__name__}" for pack, fn in self._chains[socket]]

    def run(self, socket: str, ctx: JobContext) -> JobContext:
        chain = self._chains[socket]
        if not chain:
            return ctx

        def step(index: int) -> Next:
            def call(c: JobContext) -> JobContext:
                if index >= len(chain):
                    return c
                pack, fn = chain[index]
                try:
                    return fn(c, step(index + 1))
                except PackError:
                    raise
                except Exception as exc:
                    raise PackError(
                        f"hook {pack}.{fn.__name__} at socket {socket!r} raised: {exc}"
                    ) from exc

            return call

        return step(0)(ctx)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/pipeline/test_hooks.py -v`
Expected: PASS, 7 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/pipeline/ tests/pipeline/test_hooks.py
git commit -m "feat(pipeline): 8 hook sockets with chain dispatch and failure isolation"
```

---

### Task A7: Runner with the emit-always guarantee

**Files:**
- Create: `src/docintel/pipeline/runner.py`
- Test: `tests/pipeline/test_runner.py`

**Interfaces:**
- Consumes: `docintel.core.{models,contract,errors}`, `docintel.pipeline.hooks`
- Produces: `Stage` Protocol (`name: str`, `run(ctx) -> JobContext`), `Runner(stages, hooks)`, `Runner.process(document_id, source_path, **kw) -> dict`, `Runner.stats -> dict[str, int]` with keys `intaken` and `emitted`

The guarantee lives here so no stage has to remember it.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_runner.py
import pytest
from docintel.core.contract import validate_record
from docintel.core.errors import PackError, PermanentError, TransientError
from docintel.core.models import JobContext
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner


class Ok:
    name = "ok"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("ok")
        return ctx


class Boom:
    name = "boom"

    def __init__(self, exc):
        self.exc = exc

    def run(self, ctx: JobContext) -> JobContext:
        raise self.exc


def _runner(stages):
    return Runner(stages=stages, hooks=HookRegistry())


def test_happy_path_emits_a_valid_record():
    r = _runner([Ok(), Ok()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "processed"
    assert r.stats == {"intaken": 1, "emitted": 1}


@pytest.mark.parametrize("exc", [
    PermanentError("corrupt"),
    PackError("pack blew up"),
    RuntimeError("unexpected"),
    ValueError("nonsense"),
])
def test_any_stage_failure_still_emits_a_dead_letter(exc):
    """The one failure mode this design refuses is silence."""
    r = _runner([Ok(), Boom(exc), Ok()])
    rec = r.process("d1", "/tmp/a.pdf")
    validate_record(rec)
    assert rec["disposition"] == "dead_letter"
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_transient_error_is_retried_then_dead_lettered():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def run(self, ctx):
            self.calls += 1
            raise TransientError("timeout")

    flaky = Flaky()
    r = Runner(stages=[flaky], hooks=HookRegistry(), max_retries=2)
    rec = r.process("d1", "/tmp/a.pdf")
    assert flaky.calls == 3            # initial + 2 retries
    assert rec["disposition"] == "dead_letter"
    assert r.stats == {"intaken": 1, "emitted": 1}


def test_transient_error_that_recovers_emits_processed():
    class Flaky:
        name = "flaky"

        def __init__(self):
            self.calls = 0

        def run(self, ctx):
            self.calls += 1
            if self.calls < 2:
                raise TransientError("timeout")
            return ctx

    r = Runner(stages=[Flaky()], hooks=HookRegistry(), max_retries=2)
    assert r.process("d1", "/tmp/a.pdf")["disposition"] == "processed"


def test_the_invariant_holds_over_a_burst_with_mixed_failures():
    """count(intaken) == count(emitted), the alertable promise from spec Stage 8."""
    r = _runner([Ok(), Boom(RuntimeError("x")), Ok()])
    records = [r.process(f"d{i}", f"/tmp/{i}.pdf") for i in range(50)]
    assert len(records) == 50
    assert r.stats["intaken"] == r.stats["emitted"] == 50
    for rec in records:
        validate_record(rec)


def test_a_stage_that_returns_none_is_a_programming_error_not_silent_data_loss():
    class Bad:
        name = "bad"

        def run(self, ctx):
            return None

    rec = _runner([Bad()]).process("d1", "/tmp/a.pdf")
    assert rec["disposition"] == "dead_letter"
    assert "must return a JobContext" in rec["reason"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/pipeline/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.pipeline.runner'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/pipeline/runner.py
"""Stage sequencing plus the emit-always guarantee.

count(intaken) == count(emitted) is spec Stage 8's machine-checkable promise.
Rather than trusting every code path to remember, process() wraps each document
so that any escape route - unhandled exception, retry exhaustion, a pack hook
throwing - still produces a record.
"""

from __future__ import annotations

import datetime as _dt
from typing import Any, Protocol

from docintel.core.contract import build_record, validate_record
from docintel.core.errors import TransientError
from docintel.core.models import JobContext, new_context
from docintel.pipeline.hooks import HookRegistry


class Stage(Protocol):
    name: str

    def run(self, ctx: JobContext) -> JobContext: ...


class Runner:
    def __init__(
        self,
        stages: list[Stage],
        hooks: HookRegistry,
        max_retries: int = 0,
    ) -> None:
        self.stages = stages
        self.hooks = hooks
        self.max_retries = max_retries
        self._intaken = 0
        self._emitted = 0

    @property
    def stats(self) -> dict[str, int]:
        return {"intaken": self._intaken, "emitted": self._emitted}

    def process(self, document_id: str, source_path: str, **kw: Any) -> dict[str, Any]:
        self._intaken += 1
        ctx = new_context(
            document_id=document_id,
            source_path=source_path,
            received_at=_dt.datetime.now(_dt.UTC).isoformat(),
            **kw,
        )
        try:
            ctx = self._run_stages(ctx)
        except Exception as exc:  # noqa: BLE001 - deliberate catch-all
            ctx.disposition = "dead_letter"
            ctx.skip_reason = str(exc)
            ctx.review_flag = True
            ctx.log(f"dead_letter: {type(exc).__name__}: {exc}")
        finally:
            self._emitted += 1
            ctx.emitted = True

        record = build_record(ctx)
        validate_record(record)
        return record

    def _run_stages(self, ctx: JobContext) -> JobContext:
        for stage in self.stages:
            ctx = self._run_one(stage, ctx)
            if ctx.disposition != "processed":
                break
        return ctx

    def _run_one(self, stage: Stage, ctx: JobContext) -> JobContext:
        attempts = self.max_retries + 1
        last: Exception | None = None
        for _ in range(attempts):
            try:
                result = stage.run(ctx)
            except TransientError as exc:
                last = exc
                continue
            if not isinstance(result, JobContext):
                raise TypeError(f"stage {stage.name!r} must return a JobContext")
            return result
        assert last is not None
        raise last
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/pipeline/test_runner.py -v`
Expected: PASS, 10 tests

- [ ] **Step 5: Commit**

```bash
git add src/docintel/pipeline/runner.py tests/pipeline/test_runner.py
git commit -m "feat(pipeline): runner with emit-always invariant and retry policy"
```

---

### Task A8: The 10 thin stage modules (walking skeleton)

**Files:**
- Create: `src/docintel/pipeline/stages/__init__.py`, `s1_intake.py`, `s2_filter.py`, `s3_classify.py`, `s4_persona.py`, `s5a_cached.py`, `s5b_vision.py`, `s5c_agent.py`, `s6_capture.py`, `s7_gate.py`, `s8_emit.py`
- Create: `src/docintel/adapters/__init__.py`, `src/docintel/adapters/vision/__init__.py`, `src/docintel/adapters/vision/port.py`, `src/docintel/adapters/vision/fake.py`
- Test: `tests/pipeline/test_stages_skeleton.py`

**Interfaces:**
- Consumes: everything from A3–A7
- Produces:
  - `VisionExtractor` Protocol: `extract(pages: tuple[PageText, ...], field_names: list[str]) -> VisionResult`
  - `VisionResult(fields: dict[str, str], confidence: dict[str, float], irregularities: list[str])` frozen
  - `FakeVision(canned: dict[str, str] | None = None)`
  - `build_default_stages(vision: VisionExtractor) -> list[Stage]` in `stages/__init__.py`
  - Each stage class named `Intake`, `AttachmentFilter`, `Classify`, `PersonaLookup`, `ApplyCachedRules`, `VisionOneShot`, `AgentEscalation`, `CaptureFields`, `ConfidenceGate`, `EmitRecord`

Every stage is real enough to run and log; each will be deepened by a Part B cluster. The routing logic in stage 5 is real from the start because it is the branch the whole design turns on.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_stages_skeleton.py
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def _runner():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_every_stage_runs_and_is_logged():
    rec = _runner().process("d1", CORPUS)
    validate_record(rec)


def test_the_default_sequence_is_ten_modules_in_pipeline_order():
    names = [s.name for s in build_default_stages(vision=FakeVision())]
    assert names == [
        "intake", "attachment_filter", "classify", "persona_lookup",
        "apply_cached_rules", "vision_one_shot", "agent_escalation",
        "capture_fields", "confidence_gate", "emit_record",
    ]


def test_every_stage_records_that_it_ran():
    """'Pass any PDF and it traverses all 8 stages' must be OBSERVABLY true.

    Asserts on the event log itself, which is the only evidence a stage ran.
    5a is absent by design here: no persona exists, so the document is a hard
    miss and routes to 5b.
    """
    captured = {}

    class Spy:
        name = "spy"

        def run(self, ctx):
            captured["events"] = list(ctx.events)
            return ctx

    stages = build_default_stages(vision=FakeVision())
    stages.append(Spy())
    Runner(stages=stages, hooks=HookRegistry()).process("d1", CORPUS)

    log = " ".join(captured["events"])
    for marker in ("s1:", "s2:", "s3:", "s4:", "s5b:", "s6:", "s7:", "s8:"):
        assert marker in log, f"no evidence stage {marker} ran; log was {log!r}"


def test_hard_miss_routes_to_vision_not_cached_rules():
    """Skeleton has no personas, so every document is a hard miss -> 5b."""
    rec = _runner().process("d1", CORPUS)
    assert rec["extraction_route"] == "5b_vision"


def test_unsupported_file_type_is_skipped_with_a_reason_never_dropped():
    rec = _runner().process("d2", "/tmp/notes.txt")
    validate_record(rec)
    assert rec["disposition"] == "skipped"
    assert rec["reason"]


def test_document_id_is_stable_for_the_same_source():
    r = _runner()
    a = r.process("stable-id", CORPUS)
    b = r.process("stable-id", CORPUS)
    assert a["document_id"] == b["document_id"] == "stable-id"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/pipeline/test_stages_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.adapters'`

- [ ] **Step 3: Write the vision port and fake**

```python
# src/docintel/adapters/vision/port.py
"""The vision-extraction port. Stage 5b talks to this, never to a vendor SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from docintel.core.models import PageText


@dataclass(frozen=True)
class VisionResult:
    fields: dict[str, str] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    irregularities: list[str] = field(default_factory=list)


class VisionExtractor(Protocol):
    def extract(
        self, pages: tuple[PageText, ...], field_names: list[str]
    ) -> VisionResult: ...
```

```python
# src/docintel/adapters/vision/fake.py
"""Deterministic vision stand-in. Carries the loop until an API key exists."""

from __future__ import annotations

from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText


class FakeVision:
    def __init__(self, canned: dict[str, str] | None = None) -> None:
        self.canned = canned or {}
        self.calls: list[list[str]] = []

    def extract(
        self, pages: tuple[PageText, ...], field_names: list[str]
    ) -> VisionResult:
        self.calls.append(list(field_names))
        fields = {k: v for k, v in self.canned.items() if k in field_names}
        return VisionResult(
            fields=fields,
            confidence={k: 0.50 for k in fields},
            irregularities=[],
        )
```

- [ ] **Step 4: Write the 10 thin stages**

```python
# src/docintel/pipeline/stages/s1_intake.py
"""Stage 1: catch the document, keep everything. Nothing is ever discarded here."""

from __future__ import annotations

import hashlib
import os

from docintel.core.models import JobContext


class Intake:
    name = "intake"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s1: intake")
        # Soft fingerprint: clusters likely duplicates, never rejects them.
        try:
            size = os.path.getsize(ctx.source_path)
        except OSError:
            size = -1
        basename = os.path.basename(ctx.source_path)
        ctx.derived.set(
            "soft_fingerprint",
            hashlib.sha256(f"{ctx.sender_email}|{basename}|{size}".encode()).hexdigest()[:16],
        )
        return ctx
```

```python
# src/docintel/pipeline/stages/s2_filter.py
"""Stage 2: worth processing, or politely skipped? Never silently drop."""

from __future__ import annotations

import os

from docintel.core.models import JobContext

ALLOWED_SUFFIXES = {".pdf"}


class AttachmentFilter:
    name = "attachment_filter"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s2: attachment_filter")
        suffix = os.path.splitext(ctx.source_path)[1].lower()
        if suffix not in ALLOWED_SUFFIXES:
            ctx.disposition = "skipped"
            ctx.skip_reason = f"file type {suffix or '(none)'} not in allowlist"
            return ctx
        if not os.path.exists(ctx.source_path):
            ctx.disposition = "skipped"
            ctx.skip_reason = "source file does not exist"
            return ctx
        return ctx
```

```python
# src/docintel/pipeline/stages/s3_classify.py
"""Stage 3: what kind of document? Content only, never the filename."""

from __future__ import annotations

from docintel.core.models import JobContext


class Classify:
    name = "classify"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s3: classify")
        # Pack signal ladders arrive at the classifySignals socket in cluster C5.
        # Until then every document takes the default branch below.
        if ctx.doc_type is None:
            ctx.doc_type = "standard_invoice"
            ctx.signal_that_fired = "default"
            ctx.classification_confidence = 0.50
        return ctx
```

```python
# src/docintel/pipeline/stages/s4_persona.py
"""Stage 4: have we seen this sender and doc type before?"""

from __future__ import annotations

from docintel.core.models import JobContext


class PersonaLookup:
    name = "persona_lookup"

    def __init__(self, store: object | None = None) -> None:
        self.store = store

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s4: persona_lookup")
        if ctx.sender_fingerprint is None:
            ctx.sender_fingerprint = "unknown|unknown"
        if self.store is None:
            ctx.persona_status = "hard_miss"
            return ctx
        persona = self.store.lookup(ctx.sender_fingerprint, ctx.doc_type)  # type: ignore[attr-defined]
        ctx.persona = persona
        ctx.persona_status = "hard_miss" if persona is None else "hit"
        if persona is not None:
            ctx.extraction_rule_version = persona.rule_version
        return ctx
```

```python
# src/docintel/pipeline/stages/s5a_cached.py
"""Stage 5a: run the saved selectors. Zero AI calls. The high-volume fast lane."""

from __future__ import annotations

from docintel.core.models import JobContext


class ApplyCachedRules:
    name = "apply_cached_rules"

    def __init__(self, executor: object | None = None) -> None:
        self.executor = executor

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status not in ("hit", "soft_miss"):
            return ctx
        ctx.log("s5a: apply_cached_rules")
        if self.executor is None:
            return ctx
        ctx = self.executor.apply(ctx)  # type: ignore[attr-defined]
        ctx.extraction_route = "5a_cached"
        return ctx
```

```python
# src/docintel/pipeline/stages/s5b_vision.py
"""Stage 5b: no rules, or the rules collapsed? Send the pages to a vision model."""

from __future__ import annotations

from docintel.core.models import JobContext

COLLAPSE_THRESHOLD = 0.50
DEFAULT_FIELDS = ["vendor_name", "invoice_number", "invoice_date", "total_printed"]


def _collapsed(ctx: JobContext) -> bool:
    """Several fields below threshold means the rules failed, not the document."""
    if not ctx.extracted.match_quality:
        return True
    weak = [q for q in ctx.extracted.match_quality.values() if q < COLLAPSE_THRESHOLD]
    return len(weak) >= 2


class VisionOneShot:
    name = "vision_one_shot"

    def __init__(self, vision: object, field_names: list[str] | None = None) -> None:
        self.vision = vision
        self.field_names = field_names or DEFAULT_FIELDS

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.extraction_route == "5a_cached" and not _collapsed(ctx):
            return ctx
        ctx.log("s5b: vision_one_shot")
        result = self.vision.extract(ctx.pages, self.field_names)  # type: ignore[attr-defined]
        for name, value in result.fields.items():
            ctx.extracted.set(name, value, result.confidence.get(name, 0.50))
        ctx.extraction_route = "5b_vision"
        if result.irregularities:
            for flag in result.irregularities:
                ctx.add_tag(flag)
        return ctx
```

```python
# src/docintel/pipeline/stages/s5c_agent.py
"""Stage 5c: escalate. Enqueue ONE rule-writing job per persona key, async.

Rule authoring is deliberately out of scope for this build; the job record and
its single-flight guarantee are real, so the seam is honest.
"""

from __future__ import annotations

from docintel.core.models import JobContext

WEAK = 0.60


class AgentEscalation:
    name = "agent_escalation"

    def __init__(self, jobs: object | None = None) -> None:
        self.jobs = jobs

    def run(self, ctx: JobContext) -> JobContext:
        if ctx.persona_status != "hard_miss":
            return ctx
        confidences = list(ctx.extracted.match_quality.values())
        if confidences and min(confidences) >= WEAK:
            return ctx
        ctx.log("s5c: agent_escalation (job queued, authoring deferred)")
        if self.jobs is not None:
            self.jobs.enqueue_once(ctx.sender_fingerprint, ctx.doc_type)  # type: ignore[attr-defined]
        ctx.regen_flag = True
        return ctx
```

```python
# src/docintel/pipeline/stages/s6_capture.py
"""Stage 6: per-field confidence, adjust ops, arithmetic cross-checks."""

from __future__ import annotations

from docintel.core.confidence import apply_modifiers
from docintel.core.models import JobContext


class CaptureFields:
    name = "capture_fields"

    def __init__(self, ops: list[object] | None = None) -> None:
        self.ops = ops or []

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s6: capture_fields")
        if ctx.text_source == "ocr":
            ctx.add_modifier("ocr_source")
        for op in self.ops:
            ctx = op(ctx)  # type: ignore[operator]
        for name, quality in ctx.extracted.match_quality.items():
            ctx.confidence[name] = apply_modifiers(quality, ctx.modifiers)
        return ctx
```

```python
# src/docintel/pipeline/stages/s7_gate.py
"""Stage 7: three exits, but every document leaves."""

from __future__ import annotations

import random

from docintel.core.models import JobContext

DEFAULT_THRESHOLD = 0.90
VERY_LOW_SHARE = 0.60


class ConfidenceGate:
    name = "confidence_gate"

    def __init__(
        self,
        thresholds: dict[str, float] | None = None,
        audit_rate: float = 0.0,
        rng: random.Random | None = None,
    ) -> None:
        self.thresholds = thresholds or {}
        self.audit_rate = audit_rate
        self.rng = rng or random.Random(0)

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s7: confidence_gate")
        if not ctx.confidence:
            ctx.lane = "low"
            ctx.review_flag = True
            return ctx

        short = [
            name for name, score in ctx.confidence.items()
            if score < self.thresholds.get(name, DEFAULT_THRESHOLD)
        ]
        share = len(short) / len(ctx.confidence)

        if not short:
            ctx.lane = "high"
            if self.audit_rate and self.rng.random() < self.audit_rate:
                ctx.audit_sample = True
                ctx.review_flag = True
        elif share >= VERY_LOW_SHARE:
            ctx.lane = "low"
            ctx.regen_flag = True
            ctx.review_flag = True
        else:
            ctx.lane = "medium"
            ctx.review_flag = True
        return ctx
```

```python
# src/docintel/pipeline/stages/s8_emit.py
"""Stage 8: the hard contract. Reached by every intaken document."""

from __future__ import annotations

from docintel.core.models import JobContext


class EmitRecord:
    name = "emit_record"

    def run(self, ctx: JobContext) -> JobContext:
        ctx.log("s8: emit_record")
        if ctx.extraction_rule_version is None:
            ctx.extraction_rule_version = "none"
        return ctx
```

```python
# src/docintel/pipeline/stages/__init__.py
"""Default stage sequence: 8 stages across 10 modules (stage 5 has three variants)."""

from __future__ import annotations

from docintel.pipeline.stages.s1_intake import Intake
from docintel.pipeline.stages.s2_filter import AttachmentFilter
from docintel.pipeline.stages.s3_classify import Classify
from docintel.pipeline.stages.s4_persona import PersonaLookup
from docintel.pipeline.stages.s5a_cached import ApplyCachedRules
from docintel.pipeline.stages.s5b_vision import VisionOneShot
from docintel.pipeline.stages.s5c_agent import AgentEscalation
from docintel.pipeline.stages.s6_capture import CaptureFields
from docintel.pipeline.stages.s7_gate import ConfidenceGate
from docintel.pipeline.stages.s8_emit import EmitRecord

__all__ = [
    "AgentEscalation", "ApplyCachedRules", "AttachmentFilter", "CaptureFields",
    "Classify", "ConfidenceGate", "EmitRecord", "Intake", "PersonaLookup",
    "VisionOneShot", "build_default_stages",
]


def build_default_stages(vision: object) -> list[object]:
    return [
        Intake(),
        AttachmentFilter(),
        Classify(),
        PersonaLookup(),
        ApplyCachedRules(),
        VisionOneShot(vision=vision),
        AgentEscalation(),
        CaptureFields(),
        ConfidenceGate(),
        EmitRecord(),
    ]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest tests/pipeline/test_stages_skeleton.py -v`
Expected: PASS, 5 tests

- [ ] **Step 6: Run the whole suite**

Run: `python3 -m pytest -q && python3 docs/corpus/validate_gold.py`
Expected: all green

- [ ] **Step 7: Commit**

```bash
git add src/docintel/pipeline/stages/ src/docintel/adapters/ tests/pipeline/test_stages_skeleton.py
git commit -m "feat(pipeline): walking skeleton - all 8 stages execute end to end"
```

---

### Task A9: Intake adapter and `docintel process`

**Files:**
- Create: `src/docintel/adapters/intake/__init__.py`, `port.py`, `filesystem.py`, `src/docintel/cli.py`
- Test: `tests/adapters/test_filesystem_intake.py`, `tests/test_cli_process.py`

**Interfaces:**
- Consumes: A7, A8
- Produces:
  - `IntakeItem(document_id: str, source_path: str, sender_email: str | None, email_id: str | None)` frozen
  - `IntakeSource` Protocol: `items() -> Iterator[IntakeItem]`
  - `FilesystemIntake(paths: list[str])` — stable ID derived from absolute path + size
  - `main(argv: list[str] | None = None) -> int`, subcommands `process`, `replay-gold`

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_filesystem_intake.py
from docintel.adapters.intake.filesystem import FilesystemIntake

CORPUS = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def test_ids_are_stable_across_runs():
    """Spec Stage 1: a crashed listener re-reading yields the same id, not a duplicate."""
    a = list(FilesystemIntake([CORPUS]).items())
    b = list(FilesystemIntake([CORPUS]).items())
    assert [i.document_id for i in a] == [i.document_id for i in b]


def test_ids_differ_between_documents():
    items = list(FilesystemIntake([
        CORPUS,
        "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf",
    ]).items())
    assert len({i.document_id for i in items}) == 2


def test_directory_expands_to_its_pdfs():
    items = list(FilesystemIntake(["docs"]).items())
    assert len(items) == 10
```

```python
# tests/test_cli_process.py
import json
from docintel.cli import main

CORPUS = "docs/Centracom_0384043574_01012026_BILL.pdf"


def test_process_prints_a_valid_record(capsys):
    assert main(["process", CORPUS, "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["schema_version"] == "1"
    assert rec["disposition"] in {"processed", "skipped", "dead_letter"}


def test_process_reports_the_invariant(capsys):
    assert main(["process", "docs", "--json"]) == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 10          # one record per document, none dropped


def test_missing_file_is_a_skip_not_a_crash(capsys):
    assert main(["process", "/nope/missing.pdf", "--json"]) == 0
    rec = json.loads(capsys.readouterr().out)
    assert rec["disposition"] == "skipped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/adapters tests/test_cli_process.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.adapters.intake'`

- [ ] **Step 3: Write the intake adapter**

```python
# src/docintel/adapters/intake/port.py
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class IntakeItem:
    document_id: str
    source_path: str
    sender_email: str | None = None
    email_id: str | None = None


class IntakeSource(Protocol):
    def items(self) -> Iterator[IntakeItem]: ...
```

```python
# src/docintel/adapters/intake/filesystem.py
"""Filesystem intake: the 'pass any PDF' path.

An IMAP source slots in behind the same port later without the pipeline changing.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator

from docintel.adapters.intake.port import IntakeItem


def _stable_id(path: str) -> str:
    try:
        size = os.path.getsize(path)
    except OSError:
        size = -1
    key = f"{os.path.abspath(path)}|{size}"
    return "fs-" + hashlib.sha256(key.encode()).hexdigest()[:16]


class FilesystemIntake:
    def __init__(self, paths: list[str]) -> None:
        self.paths = paths

    def items(self) -> Iterator[IntakeItem]:
        for path in self.paths:
            if os.path.isdir(path):
                for name in sorted(os.listdir(path)):
                    if name.lower().endswith(".pdf"):
                        full = os.path.join(path, name)
                        yield IntakeItem(_stable_id(full), full)
            else:
                yield IntakeItem(_stable_id(path), path)
```

- [ ] **Step 4: Write the CLI**

```python
# src/docintel/cli.py
"""Command-line entry point."""

from __future__ import annotations

import argparse
import json
import sys

from docintel.adapters.intake.filesystem import FilesystemIntake
from docintel.adapters.vision.fake import FakeVision
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages


def _build_runner() -> Runner:
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def _cmd_process(args: argparse.Namespace) -> int:
    runner = _build_runner()
    for item in FilesystemIntake(args.paths).items():
        record = runner.process(
            document_id=item.document_id,
            source_path=item.source_path,
            sender_email=item.sender_email,
            email_id=item.email_id,
        )
        if args.json:
            print(json.dumps(record, separators=(",", ":")))
        else:
            print(
                f"{record['disposition']:<12} {record['lane'] or '-':<7} "
                f"{record['doc_type'] or '-':<22} {item.source_path}"
            )
    stats = runner.stats
    if stats["intaken"] != stats["emitted"]:
        print(f"INVARIANT VIOLATED: {stats}", file=sys.stderr)
        return 2
    return 0


def _cmd_replay_gold(args: argparse.Namespace) -> int:
    from docintel.scorecard import replay_gold

    card = replay_gold(runner_factory=_build_runner)
    if args.json:
        print(json.dumps(card, indent=2))
    else:
        for doc in card["documents"]:
            mark = "PASS" if doc["passed"] else "FAIL"
            print(f"{mark}  {doc['gold_id']}  ({doc['passed_count']}/{doc['total_count']})")
        s = card["summary"]
        print(f"\n{s['passed']}/{s['total']} documents green")
    return 0 if card["summary"]["failed"] == 0 else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="docintel")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("process", help="run one or more PDFs through the pipeline")
    p.add_argument("paths", nargs="+")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=_cmd_process)

    g = sub.add_parser("replay-gold", help="run the gold corpus and score it")
    g.add_argument("--json", action="store_true")
    g.set_defaults(func=_cmd_replay_gold)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/adapters tests/test_cli_process.py -v`
Expected: PASS, 6 tests

- [ ] **Step 6: Verify by hand that any PDF traverses the pipeline**

Run: `python3 -m docintel.cli process docs`
Expected: 10 lines, one per document, no crash, no invariant warning

- [ ] **Step 7: Commit**

```bash
git add src/docintel/adapters/intake/ src/docintel/cli.py tests/adapters tests/test_cli_process.py
git commit -m "feat(cli): filesystem intake and docintel process"
```

---

### Task A10: The scorecard

**Files:**
- Create: `src/docintel/scorecard.py`
- Test: `tests/test_scorecard.py`

**Interfaces:**
- Consumes: A9, `docs/corpus/gold/*.json`
- Produces: `load_gold() -> list[dict]`, `assertions_for(gold: dict) -> list[Assertion]`, `Assertion(name: str, expected: Any, getter: Callable[[dict], Any])`, `replay_gold(runner_factory) -> dict`

The scorecard is what makes Part B a loop rather than guesswork. It must never mutate gold.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scorecard.py
import json
import pathlib
from docintel.scorecard import load_gold, replay_gold
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages
from docintel.adapters.vision.fake import FakeVision

GOLD_DIR = pathlib.Path("docs/corpus/gold")


def _factory():
    return Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())


def test_loads_all_ten_gold_documents():
    assert len(load_gold()) == 10


def test_every_gold_source_file_exists():
    for gold in load_gold():
        assert (pathlib.Path("docs") / gold["source_file"]).exists(), gold["gold_id"]


def test_scorecard_shape():
    card = replay_gold(runner_factory=_factory)
    assert card["summary"]["total"] == 10
    assert set(card["summary"]) == {"total", "passed", "failed", "assertions_passed",
                                    "assertions_total"}
    for doc in card["documents"]:
        assert {"gold_id", "passed", "assertions", "passed_count", "total_count"} <= set(doc)


def test_scorecard_actually_evaluates_assertions():
    """Guards the instrument, not the score.

    Deliberately does NOT assert a specific failing count: the whole point of
    Part B is to drive that count down, so pinning it would make this test fail
    on every successful iteration.
    """
    card = replay_gold(runner_factory=_factory)
    assert card["summary"]["assertions_total"] > 50
    assert card["summary"]["passed"] + card["summary"]["failed"] == 10
    assert all("passed" in a for d in card["documents"] for a in d["assertions"])


def test_money_assertions_compare_by_value_not_by_string():
    """Gold holds 33876.4; the record serializes "33876.40". Same amount."""
    from docintel.scorecard import matches
    assert matches(33876.4, "33876.40", kind="money") is True
    assert matches(83.79, "83.7900", kind="money") is True
    assert matches(33876.4, "13752.60", kind="money") is False
    assert matches(None, None, kind="money") is True
    assert matches(69.62, None, kind="money") is False
    # exact kind stays strict
    assert matches("current_charges", "current_charges", kind="exact") is True
    assert matches(33876.4, "33876.40", kind="exact") is False


def test_centracom_assertions_include_the_trap():
    card = replay_gold(runner_factory=_factory)
    doc = next(d for d in card["documents"] if "centracom" in d["gold_id"])
    names = {a["name"] for a in doc["assertions"]}
    assert "derived.amount_payable" in names
    assert "derived.payable_basis" in names


def test_replay_never_mutates_gold():
    before = {p.name: p.read_bytes() for p in GOLD_DIR.glob("*.json")}
    replay_gold(runner_factory=_factory)
    after = {p.name: p.read_bytes() for p in GOLD_DIR.glob("*.json")}
    assert before == after, "gold files are READ-ONLY to the loop"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_scorecard.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docintel.scorecard'`

- [ ] **Step 3: Write the implementation**

```python
# src/docintel/scorecard.py
"""Run the gold corpus through the real pipeline and score the result.

This is the objective function for the Part B convergence loop. It reads
docs/corpus/gold/*.json and never writes to it.
"""

from __future__ import annotations

import glob
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

GOLD_DIR = os.path.join("docs", "corpus", "gold")
DOCS_DIR = "docs"


@dataclass(frozen=True)
class Assertion:
    name: str
    expected: Any
    getter: Callable[[dict[str, Any]], Any]
    kind: str = "exact"       # "exact" | "money"


def matches(expected: Any, actual: Any, kind: str) -> bool:
    """Compare a gold expectation against a record value.

    Money needs value equality, not string equality: gold holds 33876.4 (JSON
    drops the trailing zero) while the record serializes Decimal("33876.40") as
    "33876.40". Both denote the same amount.
    """
    if kind != "money":
        return expected == actual
    if expected is None or actual is None:
        return expected == actual
    try:
        return Decimal(str(expected)) == Decimal(str(actual))
    except (InvalidOperation, ValueError):
        return False


def load_gold() -> list[dict[str, Any]]:
    out = []
    for path in sorted(glob.glob(os.path.join(GOLD_DIR, "*.json"))):
        with open(path) as fh:
            out.append(json.load(fh))
    return out


MONEY_FIELDS = frozenset({
    "total_printed", "current_charges", "prior_balance", "payments_credits",
    "subtotal", "tax_amount", "balance_due", "please_pay", "amount_payable",
})

CHECKED_FIELDS = (
    "total_printed", "current_charges", "prior_balance", "subtotal", "tax_amount",
    "invoice_number", "invoice_date", "vendor_name", "account_number", "bill_date",
    "currency", "service_location",
)

CHECKED_DERIVED = ("amount_payable", "payable_basis", "document_identity", "identity_basis")


def assertions_for(gold: dict[str, Any]) -> list[Assertion]:
    cls = gold["classification"]
    fields = gold.get("fields", {})
    derived = gold.get("derived", {})
    routing = gold["expected_routing"]

    items: list[Assertion] = [
        Assertion("doc_type", cls["doc_type"], lambda r: r["doc_type"]),
        Assertion("text_source", cls["text_source"], lambda r: r["text_source"]),
        Assertion("review_flag", routing["review_flag"], lambda r: r["review_flag"]),
        Assertion("regen_flag", routing["regen_flag"], lambda r: r["regen_flag"]),
    ]

    for name in CHECKED_FIELDS:
        if fields.get(name) is not None:
            items.append(Assertion(
                f"fields.{name}", fields[name],
                lambda r, n=name: r["fields"].get(n),
                kind="money" if name in MONEY_FIELDS else "exact",
            ))

    for name in CHECKED_DERIVED:
        if name in derived:
            items.append(Assertion(
                f"derived.{name}", derived[name],
                lambda r, n=name: r["derived"].get(n),
                kind="money" if name in MONEY_FIELDS else "exact",
            ))

    return items


def replay_gold(runner_factory: Callable[[], Any]) -> dict[str, Any]:
    documents = []
    a_passed = a_total = 0

    for gold in load_gold():
        runner = runner_factory()
        source = os.path.join(DOCS_DIR, gold["source_file"])
        record = runner.process(document_id=gold["gold_id"], source_path=source)

        results = []
        for assertion in assertions_for(gold):
            try:
                actual = assertion.getter(record)
            except Exception as exc:  # noqa: BLE001
                actual = f"<error: {exc}>"
            results.append({
                "name": assertion.name,
                "kind": assertion.kind,
                "expected": assertion.expected,
                "actual": actual,
                "passed": matches(assertion.expected, actual, assertion.kind),
            })

        passed_count = sum(1 for r in results if r["passed"])
        a_passed += passed_count
        a_total += len(results)
        documents.append({
            "gold_id": gold["gold_id"],
            "source_file": gold["source_file"],
            "priority": gold.get("priority"),
            "teaches": gold.get("teaches", []),
            "passed": passed_count == len(results),
            "passed_count": passed_count,
            "total_count": len(results),
            "assertions": results,
        })

    passed_docs = sum(1 for d in documents if d["passed"])
    return {
        "documents": documents,
        "summary": {
            "total": len(documents),
            "passed": passed_docs,
            "failed": len(documents) - passed_docs,
            "assertions_passed": a_passed,
            "assertions_total": a_total,
        },
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_scorecard.py -v`
Expected: PASS, 6 tests

- [ ] **Step 5: Produce the first scorecard**

```bash
mkdir -p .loop
python3 -m docintel.cli replay-gold --json > .loop/scorecard.json
python3 -m docintel.cli replay-gold
```

Expected: `0/10 documents green`. This is the intended starting point.

- [ ] **Step 6: Seed the loop journal**

```bash
cat > .loop/journal.md <<'EOF'
# Convergence loop journal

Append one entry per iteration. Never edit `docs/corpus/gold/` to make a test
pass — see the guardrails in the plan.

## Iteration 0 — baseline
- Cluster: none (Part A bootstrap complete)
- Score: 0/10 documents green
- Note: skeleton routes every document to the fake vision extractor, so almost
  every assertion fails. Instrument works; needle not yet moved.
EOF
```

- [ ] **Step 7: Commit**

```bash
git add src/docintel/scorecard.py tests/test_scorecard.py .loop/
git commit -m "feat: gold scorecard - the convergence loop objective function"
```

---

### Task A11: The invariant test

**Files:**
- Create: `tests/test_invariant.py`
- Test: itself

**Interfaces:**
- Consumes: A7–A10
- Produces: nothing importable; this is the guard on the design's central promise

- [ ] **Step 1: Write the test**

```python
# tests/test_invariant.py
"""count(intaken) == count(emitted) under burst load with injected failures.

If this test ever fails, "nothing is ever dropped" has stopped being true - the
one failure mode the design refuses.
"""

import pytest
from docintel.adapters.vision.fake import FakeVision
from docintel.core.contract import validate_record
from docintel.core.errors import PermanentError, TransientError
from docintel.core.models import JobContext
from docintel.pipeline.hooks import HookRegistry
from docintel.pipeline.runner import Runner
from docintel.pipeline.stages import build_default_stages

CORPUS_DIR = "docs"
INJECTED = [
    PermanentError("corrupt PDF"),
    TransientError("vision timeout"),
    RuntimeError("unexpected"),
    MemoryError("resource exhausted"),
]


def _stages_with_failure_at(index: int, exc: Exception) -> list:
    stages = build_default_stages(vision=FakeVision())

    class Saboteur:
        name = f"saboteur_{index}"

        def run(self, ctx: JobContext) -> JobContext:
            raise exc

    stages.insert(index, Saboteur())
    return stages


@pytest.mark.parametrize("index", range(10))
@pytest.mark.parametrize("exc", INJECTED)
def test_invariant_holds_with_a_failure_injected_at_every_stage(index, exc):
    runner = Runner(stages=_stages_with_failure_at(index, exc), hooks=HookRegistry())
    records = [runner.process(f"d{i}", "docs/Lumen - 5-QXH7QKM7.pdf") for i in range(10)]
    assert len(records) == 10
    assert runner.stats["intaken"] == runner.stats["emitted"] == 10
    for rec in records:
        validate_record(rec)
        assert rec["disposition"] == "dead_letter"


def test_a_throwing_pack_hook_is_isolated_as_a_PackError():
    """Not an invariant test yet.

    Stages do not dispatch hooks until cluster C5, so this asserts only what
    exists today: the registry converts a pack exception into PackError, which
    the runner already routes to a dead letter (see test_runner.py). C5 must add
    the end-to-end invariant case once a stage owns the socket.
    """
    from docintel.core.errors import PackError
    from docintel.core.models import new_context

    hooks = HookRegistry()

    def boom(ctx, nxt):
        raise RuntimeError("pack bug")

    hooks.register("afterExtraction", boom, pack="northstar")
    with pytest.raises(PackError, match="northstar"):
        hooks.run("afterExtraction", new_context("d", "/x.pdf"))


def test_invariant_holds_across_the_whole_corpus():
    runner = Runner(stages=build_default_stages(vision=FakeVision()), hooks=HookRegistry())
    from docintel.adapters.intake.filesystem import FilesystemIntake
    items = list(FilesystemIntake([CORPUS_DIR]).items())
    for item in items:
        runner.process(item.document_id, item.source_path)
    assert runner.stats["intaken"] == runner.stats["emitted"] == len(items) == 10
```

- [ ] **Step 2: Run it and confirm it passes**

Run: `python3 -m pytest tests/test_invariant.py -q`
Expected: PASS, 42 tests

- [ ] **Step 3: Run the full suite and the gold validator**

Run: `python3 -m pytest -q && python3 docs/corpus/validate_gold.py && ruff check src tests`
Expected: all green

- [ ] **Step 4: Commit**

```bash
git add tests/test_invariant.py
git commit -m "test: invariant holds under injected failures at every stage"
```

**PART A EXIT CHECK.** All three must be true before starting Part B:
1. `python3 -m docintel.cli process docs` emits 10 records, no crash — ✅ Task A9
2. `python3 -m docintel.cli replay-gold --json` writes a scorecard — ✅ Task A10
3. `python3 -m pytest tests/test_invariant.py` passes — ✅ Task A11

---

# PART B — Convergence loop

Part B is **not a fixed task sequence**. Each iteration reads the scorecard and picks the highest-value failure cluster. The clusters below are fully specified; the loop decides the order.

## The loop

```
LOOP:
  1. python3 -m docintel.cli replay-gold --json > .loop/scorecard.json
  2. python3 -m docintel.cli replay-gold                     # human-readable
  3. Cluster the failing assertions by root cause, then rank:
       tier 1  a whole stage or layer is missing         (affects many documents)
       tier 2  one shared op / pattern / region is wrong  (affects several)
       tier 3  one persona selector is wrong             (affects one)
     Within a tier, cheapest first.
  4. Pick EXACTLY ONE cluster. Announce which and why.
  5. Write a failing test at the LOWEST level that reproduces it.
  6. Implement the minimum fix.
  7. Verify:  python3 -m pytest -q
              python3 docs/corpus/validate_gold.py
              python3 -m docintel.cli replay-gold
  8. Regression in any previously-passing assertion?
       -> git revert, narrow the cluster, return to step 5.
  9. Append an entry to .loop/journal.md: cluster, fix, score before -> after.
 10. Commit.
 11. Exit if ALL of:
       - summary.failed == 0
       - tests/test_invariant.py passes
       - validate_gold.py green
       - ruff clean
     Otherwise return to step 1.
```

## Guardrails

| # | Guardrail | How it is enforced |
|--:|---|---|
| 1 | **`docs/corpus/gold/*.json` is read-only** | `test_replay_never_mutates_gold` (Task A10) fails if the loop writes to it. Changing a gold value requires re-reading the source PDF and a written justification in the journal. |
| 2 | **The F1 anti-regression test is undeletable** | Cluster C3 creates `tests/test_f1_antiregression.py`. Its removal is exactly the shape of the bug it guards. |
| 3 | **`validate_gold.py` stays green** | Step 7 of every iteration. Stops "fixing" a label into internal inconsistency. |
| 4 | **Stuck detector** | If the same cluster appears in two consecutive journal entries without the score improving, STOP and escalate to the user. Two failures mean the fix is architectural, not local. |
| 5 | **Hard iteration cap: 20** | On reaching it, stop and report the remaining clusters rather than churning. |

## Cluster catalog

Each cluster is a task in the Part A sense: files, interfaces, TDD steps, commit. Order is decided by the scorecard, but dependencies are noted.

---

### Cluster C1: The extract layer

**Unblocks:** every `fields.*` assertion. Expect this to be tier 1 on the first iteration.
**Depends on:** A3.

**Files:**
- Create: `src/docintel/extract/__init__.py`, `pdf.py`, `ocr.py`, `normalize.py`, `pageroles.py`, `annotations.py`, `scanline.py`
- Modify: `src/docintel/pipeline/stages/s2_filter.py` — call `normalize.load_document`, set `ctx.pages`, `ctx.page_meta`, `ctx.text_source`
- Test: `tests/extract/test_pdf.py`, `test_ocr.py`, `test_normalize.py`, `test_pageroles.py`, `test_annotations.py`, `test_scanline.py`

**Interfaces:**
- Produces:
  - `pdf.read_pages(path) -> tuple[PageText, ...]`, `pdf.read_meta(path) -> tuple[PageMeta, ...]`
  - `ocr.ocr_pages(path, page_numbers: list[int]) -> tuple[PageText, ...]`
  - `normalize.load_document(path) -> tuple[tuple[PageText, ...], tuple[PageMeta, ...], str]` returning `(pages, meta, text_source)`; **OCR happens here exactly once**
  - `pageroles.assign(pages, meta) -> tuple[PageMeta, ...]`
  - `annotations.detect_flattened(path, pages, meta) -> bool`
  - `scanline.find(pages) -> str | None`, `scanline.corroborates(scanline: str, value) -> bool`

**Key tests (measured facts from corpus-analysis §2, so these are assertions about reality, not guesses):**

```python
# tests/extract/test_normalize.py
import pytest
from docintel.extract.normalize import load_document

NATIVE = [
    ("docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf", 1),
    ("docs/_AP Invoice 715-33905296    Veritiv Operating Company 4908.00000.pdf", 1),
    ("docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf", 5),
    ("docs/Centracom_0384043574_01012026_BILL.pdf", 10),
    ("docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf", 6),
    ("docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf", 1),
    ("docs/Lumen - 5-QXH7QKM7.pdf", 6),
    ("docs/Windstream_041069076_07222025_BILL.pdf", 4),
]
IMAGE_ONLY = [
    ("docs/_AP Invoice 32930 Complete Beverage Destruction 1177.70000.pdf", 4),
    ("docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf", 1),
]


@pytest.mark.parametrize("path,pages", NATIVE)
def test_native_documents_use_the_text_layer(path, pages):
    got_pages, meta, source = load_document(path)
    assert source == "native"
    assert len(got_pages) == pages


@pytest.mark.parametrize("path,pages", IMAGE_ONLY)
def test_image_only_documents_route_to_ocr(path, pages):
    """20% of the corpus has zero text layer, and both render crisply (F2)."""
    got_pages, meta, source = load_document(path)
    assert source == "ocr"
    assert len(got_pages) == pages
    assert sum(len(p.words) for p in got_pages) > 0


def test_ocr_output_has_the_same_shape_as_native():
    """The seam that makes the grammar executor blind to source."""
    native, _, _ = load_document(NATIVE[0][0])
    ocr, _, _ = load_document(IMAGE_ONLY[1][0])
    assert type(native[0]) is type(ocr[0])
    for page in ocr:
        assert page.source == "ocr"
        assert all(w.x1 >= w.x0 for w in page.words)


def test_edco_current_charges_survives_extraction():
    """The F1 trap must be reachable: 69.62 distinguishable from 367.96."""
    pages, _, _ = load_document(
        "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    )
    text = pages[0].text
    assert "CURRENT CHARGES" in text
    assert "69.62" in text
    assert "298.34" in text


def test_upak_total_is_on_the_last_page_not_the_first():
    """F9: page 1's Please Pay cell is blank."""
    pages, _, _ = load_document("docs/CANADIAN WITHOUT NOTES U- PAK 4378107 (1).pdf")
    assert "14740.85" in pages[-1].text.replace(",", "")
    assert "14740.85" not in pages[0].text.replace(",", "")
```

```python
# tests/extract/test_annotations.py
from docintel.extract.annotations import detect_flattened
from docintel.extract.normalize import load_document

FEDERAL = "docs/CONTRA ONLY Everything already on AR Federal Recycling 1330123.pdf"
CLEAN = "docs/_AP Invoice 6060DTSS        D.T.S.S. Inc. 699.00000.pdf"


def test_federal_recycling_flattened_annotations_are_detected():
    """F3: annots==0 because the overlays were flattened into the page image."""
    pages, meta, _ = load_document(FEDERAL)
    assert meta[0].annot_count == 0          # no annotation layer to strip
    assert detect_flattened(FEDERAL, pages, meta) is True


def test_clean_document_is_not_flagged():
    pages, meta, _ = load_document(CLEAN)
    assert detect_flattened(CLEAN, pages, meta) is False
```

```python
# tests/extract/test_scanline.py
import pytest
from docintel.extract.normalize import load_document
from docintel.extract.scanline import corroborates, find

CASES = [
    ("docs/Lumen - 5-QXH7QKM7.pdf", "24809"),
    ("docs/Comcast_8495 44 462 0365242_12092025_BILL.pdf", "22111"),
    ("docs/Centracom_0384043574_01012026_BILL.pdf", "3387640"),
    ("docs/Windstream_041069076_07222025_BILL.pdf", "123014"),
    ("docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf", "36796"),
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
```

**Steps:** for each of the 6 modules — write the failing test, run it, implement, run it, commit. Then modify `s2_filter.py` to call `load_document` and set the three context slots, add a test that `ctx.text_source` reaches the record, and commit.

**Exit criterion:** `fields.*` assertions become *reachable* (they will still fail — nothing extracts yet). `text_source` assertions go green for all 10 documents.

---

### Cluster C2: The grammar

**Unblocks:** all `fields.*` assertions on native-text documents.
**Depends on:** C1.

**Files:**
- Create: `src/docintel/grammar/__init__.py`, `schema.py`, `patterns.py`, `regions.py`, `validator.py`, `executor.py`
- Modify: `s5a_cached.py` — accept a real executor
- Test: `tests/grammar/test_schema.py`, `test_patterns.py`, `test_regions.py`, `test_validator.py`, `test_executor.py`

**Interfaces:**
- Produces:
  - `schema.FieldSelector`, `schema.RowGroupSelector`, `schema.ScanlineSelector`, `schema.Persona`, `schema.parse_persona(dict) -> Persona`
  - `patterns.NAMED: dict[str, Callable[[str], Any]]` — the 14 named patterns from grammar §3.1
  - `patterns.compile_restricted(pattern: str) -> re.Pattern` — enforces the §3.2 limits
  - `regions.RESOLVERS: dict[str, Callable]` — the 14 regions from grammar §2
  - `validator.validate_persona(persona: dict, pack: Pack) -> None` — raises `ValidationError`; implements V1–V13
  - `executor.Executor(persona).apply(ctx) -> JobContext`

**Key tests:**

```python
# tests/grammar/test_validator.py
import pytest
from docintel.core.errors import ValidationError
from docintel.grammar.validator import validate_persona


def _base(**over):
    p = {
        "sender_fingerprint": "x|y", "doc_type": "standard_invoice",
        "rule_version": "v1", "status": "draft", "field_selectors": [],
        "layout_fingerprint": {},
    }
    p.update(over)
    return p


def test_V10_selector_may_not_target_amount_payable():
    """The single easiest way to reintroduce the F1 bug."""
    p = _base(field_selectors=[
        {"field": "amount_payable", "anchor": "Total Amount Due",
         "region": "totals-block", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="derived_only"):
        validate_persona(p, pack=None)


def test_V7_scanline_may_not_assert_amount_payable():
    """Centracom's scanline encodes the trap value (F7)."""
    p = _base(field_selectors=[
        {"scanline": True, "region": "remittance-block",
         "asserts": [{"field": "amount_payable", "as": "digits_no_decimal"}]}
    ])
    with pytest.raises(ValidationError, match="amount_payable"):
        validate_persona(p, pack=None)


def test_V6_bare_digit_regex_needs_a_narrowing_region():
    p = _base(field_selectors=[
        {"field": "reference", "region": "any-page", "pattern": r"(\d{7})"}
    ])
    with pytest.raises(ValidationError, match="narrowing region"):
        validate_persona(p, pack=None)


def test_V4_unbounded_quantifier_is_rejected():
    p = _base(field_selectors=[
        {"field": "vendor_name", "region": "header-block", "pattern": ".*"}
    ])
    with pytest.raises(ValidationError, match="unbounded"):
        validate_persona(p, pack=None)


def test_V3_unknown_region_is_rejected():
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "middle-ish", "pattern": "currency"}
    ])
    with pytest.raises(ValidationError, match="region"):
        validate_persona(p, pack=None)


def test_V8_sub_group_nesting_depth_is_capped_at_one():
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "Description",
        "columns": {"amount": "currency"},
        "sub_group": {"anchor": "WORK ORDER#:", "field": "work_order",
                      "pattern": r"(\d{7})",
                      "sub_group": {"anchor": "x", "field": "y", "pattern": "z"}},
    }])
    with pytest.raises(ValidationError, match="nesting"):
        validate_persona(p, pack=None)


def test_V9_row_count_must_be_a_range():
    p = _base(field_selectors=[{
        "row_group": "line_items", "table_anchor": "Description",
        "columns": {"amount": "currency"}, "row_count": 10,
    }])
    with pytest.raises(ValidationError, match="range"):
        validate_persona(p, pack=None)


def test_V11_persona_over_64kb_is_rejected():
    p = _base(few_shot_examples=[{"blob": "x" * 70_000}])
    with pytest.raises(ValidationError, match="64"):
        validate_persona(p, pack=None)


def test_V12_few_shot_examples_capped_at_three():
    p = _base(few_shot_examples=[{}, {}, {}, {}])
    with pytest.raises(ValidationError, match="few_shot"):
        validate_persona(p, pack=None)


def test_a_valid_persona_passes():
    validate_persona(_base(field_selectors=[
        {"field": "total_printed", "anchor": "Total Amount Due",
         "region": "totals-block", "pattern": "currency"}
    ]), pack=None)


def test_rejection_is_all_or_nothing():
    """A persona is never half-migrated to a bad rule set."""
    p = _base(field_selectors=[
        {"field": "total_printed", "region": "totals-block", "pattern": "currency"},
        {"field": "amount_payable", "region": "totals-block", "pattern": "currency"},
    ])
    with pytest.raises(ValidationError):
        validate_persona(p, pack=None)
```

```python
# tests/grammar/test_patterns.py
import pytest
from docintel.core.errors import ValidationError
from docintel.grammar.patterns import NAMED, compile_restricted


def test_all_thirteen_named_patterns_exist():
    """The pattern vocabulary is closed - selector-grammar.md section 3.1."""
    assert set(NAMED) == {
        "currency", "currency_signed", "integer", "decimal", "date", "date_loose",
        "text", "text_block", "account_number", "phone", "postal_code", "tax_id",
        "digits_run",
    }


def test_tax_id_and_currency_are_mutually_exclusive():
    """H.S.T. # 123142812RT0001  2,325.69 - the anchor hazard from F14."""
    assert NAMED["tax_id"]("123142812RT0001") is not None
    assert NAMED["currency"]("123142812RT0001") is None


def test_account_number_preserves_and_normalizes():
    result = NAMED["account_number"]("8495 44 462 0365242")
    assert result.raw == "8495 44 462 0365242"
    assert result.normalized == "8495444620365242"


def test_canadian_postal_codes_parse():
    assert NAMED["postal_code"]("N1G 4N4") is not None
    assert NAMED["postal_code"]("M9W 7E9") is not None


@pytest.mark.parametrize("bad,reason", [
    (".*", "unbounded"),
    ("(a)(b)", "capture group"),
    ("x" * 250, "200"),
    (r"(?<=foo)bar", "lookbehind"),
    (r"(a)\1", "backreference"),
])
def test_restricted_regex_rejects_dangerous_patterns(bad, reason):
    with pytest.raises(ValidationError, match=reason):
        compile_restricted(bad)


def test_bounded_quantifier_is_allowed():
    assert compile_restricted(r"NS\s?#\s?(\d{7})") is not None
    assert compile_restricted(r".{0,80}") is not None
```

**Exit criterion:** the validator passes all 13 rules; the executor extracts fields from a fixture `PageText`. `replay-gold` still near zero because no personas exist yet — that is C5.

---

### Cluster C3: Adjust ops, capture, and the F1 machinery

**Unblocks:** `derived.amount_payable`, `derived.payable_basis` — the highest-value assertions in the corpus.
**Depends on:** C2.

**Files:**
- Create: `src/docintel/grammar/ops/__init__.py`, `base.py`, `derive.py`, `crosscheck.py`, `infer.py`
- Modify: `src/docintel/pipeline/stages/s6_capture.py` — run the op chain, apply both confidence inputs
- Test: `tests/grammar/ops/test_base.py`, `test_derive.py`, `test_crosscheck.py`, `test_infer.py`, `tests/test_f1_antiregression.py`

**Interfaces:**
- Produces:
  - `ops.OPS: dict[str, Callable[[JobContext], JobContext]]` — the closed enum from grammar §4
  - `derive.resolve_carried_balance`, `derive.derive_amount_payable`, `derive.normalize_credit_sign`
  - `crosscheck.crosscheck_line_sum`, `crosscheck_total_composition`, `crosscheck_balance_composition`, `crosscheck_scanline`, `crosscheck_duplicate_anchor`, `crosscheck_filename`
  - `infer.infer_currency`, `infer.resolve_vendor_alias`

**The two tests that matter most:**

```python
# tests/grammar/ops/test_derive.py
from decimal import Decimal
import pytest
from docintel.core.models import new_context
from docintel.grammar.ops.derive import derive_amount_payable, resolve_carried_balance


def _ctx(prior, current, printed, basis, payments=None):
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal(prior), 1.0)
    ctx.extracted.set("current_charges", Decimal(current), 1.0)
    ctx.extracted.set("total_printed", Decimal(printed), 1.0)
    ctx.extracted.set("prior_balance_basis", basis, 1.0)
    if payments is not None:
        ctx.extracted.set("payments_credits", Decimal(payments), 1.0)
    return ctx


def test_centracom_net_of_payments_yields_the_current_charges():
    """THE test. Wrong here costs $20,123.80."""
    ctx = _ctx("20123.80", "13752.60", "33876.40", "net_of_payments", "-24120.20")
    ctx = resolve_carried_balance(ctx)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("carried_balance") == Decimal("20123.80")
    assert ctx.derived.get("amount_payable") == Decimal("13752.60")
    assert ctx.derived.get("payable_basis") == "current_charges"
    assert ctx.review_flag is False


def test_edco_balance_forward_yields_the_current_charges():
    ctx = _ctx("298.34", "69.62", "367.96", "gross", "0.00")
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("amount_payable") == Decimal("69.62")
    assert ctx.derived.get("payable_basis") == "current_charges"


@pytest.mark.parametrize("prior,payments,current,printed", [
    ("212.87", "-212.87", "221.11", "221.11"),      # Comcast
    ("1231.74", "-1231.74", "1230.14", "1230.14"),  # Windstream
    ("249.84", "-249.84", "248.09", "248.09"),      # Lumen
])
def test_gross_prior_cleared_to_zero_yields_the_printed_total(prior, payments, current, printed):
    """F1b: prior is gross, a signed credit zeroes it, so the printed total IS payable."""
    ctx = _ctx(prior, current, printed, "gross", payments)
    ctx = derive_amount_payable(resolve_carried_balance(ctx))
    assert ctx.derived.get("carried_balance") == Decimal("0.00")
    assert ctx.derived.get("amount_payable") == Decimal(printed)
    assert ctx.derived.get("payable_basis") == "total_printed"


def test_net_basis_must_not_subtract_payments_twice():
    """Double-subtracting fails LOW, which is as wrong as F1 and harder to notice."""
    ctx = _ctx("20123.80", "13752.60", "33876.40", "net_of_payments", "-24120.20")
    ctx = resolve_carried_balance(ctx)
    assert ctx.derived.get("carried_balance") != Decimal("-3996.40")


def test_unexplained_gap_refuses_to_guess():
    """U-Pak: 14789.77 printed, 14740.85 payable, aging all zero. Human required."""
    ctx = new_context("d", "/x.pdf")
    ctx.extracted.set("total_printed", Decimal("14789.77"), 1.0)
    ctx.extracted.set("please_pay", Decimal("14740.85"), 1.0)
    ctx = derive_amount_payable(ctx)
    assert ctx.derived.get("amount_payable") is None
    assert ctx.review_flag is True
    assert "arith_balance_mismatch" in ctx.modifiers


def test_missing_basis_is_a_review_flag_not_a_default():
    ctx = _ctx("100.00", "50.00", "150.00", basis=None)
    ctx = resolve_carried_balance(ctx)
    assert ctx.review_flag is True
```

```python
# tests/test_f1_antiregression.py
"""GUARDRAIL 2 — DO NOT DELETE THIS FILE.

On 7 of the 10 corpus documents, `amount_payable == total_printed`. Anyone
optimizing this code will be tempted to collapse the derivation into "read the
total". That change passes 7 of 10 gold documents and is wrong by $20,123.80 on
Centracom, the largest invoice in the corpus.

If this test is failing, DO NOT relax it. Read docs/corpus-analysis.md section F1.
"""

from decimal import Decimal
from docintel.core.models import new_context
from docintel.grammar.ops.derive import derive_amount_payable, resolve_carried_balance

CENTRACOM_PRINTED = Decimal("33876.40")
CENTRACOM_PAYABLE = Decimal("13752.60")
COST_OF_BEING_WRONG = Decimal("20123.80")


def _centracom():
    ctx = new_context("centracom", "/x.pdf")
    ctx.extracted.set("prior_balance", Decimal("20123.80"), 1.0)
    ctx.extracted.set("payments_credits", Decimal("-24120.20"), 1.0)
    ctx.extracted.set("current_charges", CENTRACOM_PAYABLE, 1.0)
    ctx.extracted.set("total_printed", CENTRACOM_PRINTED, 1.0)
    ctx.extracted.set("prior_balance_basis", "net_of_payments", 1.0)
    return ctx


def test_the_naive_answer_is_not_produced():
    ctx = derive_amount_payable(resolve_carried_balance(_centracom()))
    payable = ctx.derived.get("amount_payable")
    assert payable != CENTRACOM_PRINTED, (
        f"REGRESSION: amount_payable returned the printed total {CENTRACOM_PRINTED}. "
        f"That overpays by {COST_OF_BEING_WRONG}. See corpus-analysis.md F1."
    )
    assert payable == CENTRACOM_PAYABLE


def test_the_derivation_records_why():
    ctx = derive_amount_payable(resolve_carried_balance(_centracom()))
    assert ctx.derived.get("payable_basis") == "current_charges"


def test_sanity_the_two_numbers_really_do_differ_by_the_prior_balance():
    assert CENTRACOM_PRINTED - CENTRACOM_PAYABLE == COST_OF_BEING_WRONG
```

**Exit criterion:** all `derived.*` assertions pass for documents whose fields already extract. `tests/test_f1_antiregression.py` green.

---

### Cluster C4: The confidence gate

**Unblocks:** `review_flag`, `regen_flag` assertions on all 10 documents.
**Depends on:** C3.

**Files:**
- Modify: `src/docintel/pipeline/stages/s7_gate.py` — per-field pack thresholds, forced-review overrides, deterministic audit sampling
- Test: `tests/pipeline/test_gate.py`

**Interfaces:** `ConfidenceGate(thresholds: dict[str, float], forced_review_tags: set[str], audit_rate: float, rng: random.Random)`

**Key tests:**

```python
# tests/pipeline/test_gate.py
import random
from docintel.pipeline.stages.s7_gate import ConfidenceGate
from docintel.core.models import new_context


def _gate(**kw):
    kw.setdefault("rng", random.Random(0))
    return ConfidenceGate(**kw)


def test_all_fields_clear_thresholds_goes_high():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.98, "invoice_number": 0.95}
    out = _gate(thresholds={"total_printed": 0.95, "invoice_number": 0.92}).run(ctx)
    assert out.lane == "high"
    assert out.review_flag is False


def test_one_weak_field_goes_medium_with_review():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"vendor_name": 0.97, "total_printed": 0.55}
    out = _gate(thresholds={"total_printed": 0.95, "vendor_name": 0.90}).run(ctx)
    assert out.lane == "medium"
    assert out.review_flag is True
    assert out.regen_flag is False


def test_most_fields_weak_goes_low_with_regen_not_just_review():
    """Systemic failure means 'fix the rules', not 'a human reads this one'."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"a": 0.2, "b": 0.3, "c": 0.25, "d": 0.9}
    out = _gate(thresholds={}).run(ctx)
    assert out.lane == "low"
    assert out.regen_flag is True


def test_flattened_annotations_force_review_regardless_of_confidence():
    """F3: Federal Recycling. Never fast-lane an annotated document."""
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    ctx.add_tag("has_flattened_annotations")
    out = _gate(thresholds={}, forced_review_tags={"has_flattened_annotations"}).run(ctx)
    assert out.review_flag is True
    assert out.lane != "high"


def test_audit_sampling_is_deterministic_under_a_seeded_rng():
    lanes = []
    for seed in range(20):
        ctx = new_context("d", "/x.pdf")
        ctx.confidence = {"total_printed": 0.99}
        out = ConfidenceGate(thresholds={}, audit_rate=0.5,
                             rng=random.Random(seed)).run(ctx)
        lanes.append(out.audit_sample)
    assert any(lanes) and not all(lanes)


def test_audit_sample_stays_in_the_high_lane_but_is_flagged():
    ctx = new_context("d", "/x.pdf")
    ctx.confidence = {"total_printed": 0.99}
    out = ConfidenceGate(thresholds={}, audit_rate=1.0, rng=random.Random(1)).run(ctx)
    assert out.lane == "high"
    assert out.audit_sample is True
    assert out.review_flag is True


def test_no_confidence_at_all_is_low_not_high():
    """An empty confidence dict must never be read as 'nothing fell short'."""
    out = _gate(thresholds={}).run(new_context("d", "/x.pdf"))
    assert out.lane == "low"
    assert out.review_flag is True
```

**Exit criterion:** routing assertions green for every document whose fields extract.

---

### Cluster C5: The two packs and 8 authored personas

**Unblocks:** most remaining assertions. The largest cluster; split into C5a (registry + Northstar) and C5b (Digital Direction) if the scorecard lets you.
**Depends on:** C2, C3, C4.

**Files:**
- Create: `src/docintel/packs/__init__.py`, `registry.py`
- Create: `src/docintel/packs/northstar/__init__.py`, `ladder.py`, `fields.py`, `references.py`, `aliases.py`, `hooks.py`, `thresholds.py`
- Create: `src/docintel/packs/digitaldirection/` — same six modules
- Create: `src/docintel/packs/northstar/personas/*.json` (6), `src/docintel/packs/digitaldirection/personas/*.json` (2 for Lumen + Centracom; Comcast and Windstream authored too if the scorecard demands)
- Modify: `s3_classify.py`, `s4_persona.py`, `cli.py` — load packs, dispatch `classifySignals`, build the lookup key
- Test: `tests/packs/test_registry.py`, `test_northstar_ladder.py`, `test_digitaldirection_ladder.py`, `test_aliases.py`, `test_personas_validate.py`

**Interfaces:**
- `registry.Pack` Protocol: `name`, `doc_types`, `field_set(doc_type)`, `thresholds`, `register_hooks(reg: HookRegistry)`, `personas() -> list[dict]`
- `registry.load_packs() -> list[Pack]`
- `registry.resolve_pack(ctx) -> Pack`

**Key tests:**

```python
# tests/packs/test_digitaldirection_ladder.py
from docintel.packs.digitaldirection.ladder import classify
from docintel.core.models import new_context, PageText, Word


def _page(text: str) -> PageText:
    words = tuple(
        Word(tok, i * 10.0, 0.0, i * 10.0 + 8, 10.0)
        for i, tok in enumerate(text.split())
    )
    return PageText(page_number=1, words=words, width=612.0, height=792.0, source="native")


def test_centracom_account_summary_is_still_a_bill_not_a_statement():
    """F9: page 1 is titled 'Account Summary' and says 'statement' twice."""
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page(
        "Account Summary Last Month Balance from last statement 44,244.00 "
        "Previous Balance Due 20,123.80 This Month Subtotal Current Charges 13,752.60 "
        "Total Amount Due 33,876.40"
    ),)
    out = classify(ctx)
    assert out.doc_type == "telecom_bill"


def test_a_document_with_a_payable_block_and_line_items_is_a_bill():
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page("Amount due 221.11 New charges Comcast Business services 217.89"),)
    assert classify(ctx).doc_type == "telecom_bill"


def test_prior_balance_present_is_tagged_separately_from_cleared():
    ctx = new_context("d", "/x.pdf")
    ctx.pages = (_page("Previous Balance Due 20,123.80 Total Amount Due 33,876.40"),)
    out = classify(ctx)
    assert "prior_balance_present" in out.tags
```

```python
# tests/packs/test_aliases.py
import pytest
from docintel.packs.digitaldirection.aliases import canonical


@pytest.mark.parametrize("printed", [
    "Lumen", "LUMEN", "Level 3 Communications, LLC",
    "Level 3 Communications", "CenturyLink",
])
def test_lumen_three_printed_names_collapse_to_one_persona(printed):
    """F5: without this, one carrier becomes three cold-start personas."""
    assert canonical(printed) == "lumen"


@pytest.mark.parametrize("printed", [
    "Windstream", "Kinetic Business by Windstream",
    "OKLAHOMA WINDSTREAM, LLC", "TEXAS WINDSTREAM, LLC",
])
def test_windstream_state_entities_match_as_a_pattern_not_a_literal(printed):
    assert canonical(printed) == "windstream"


def test_payee_wins_over_letterhead():
    """The legal entity survives rebrands; the logo does not."""
    assert canonical("Lumen", payee="Level 3 Communications, LLC") == "lumen"
```

```python
# tests/packs/test_personas_validate.py
from docintel.grammar.validator import validate_persona
from docintel.packs.registry import load_packs


def test_every_shipped_persona_passes_the_closed_grammar():
    """A persona that cannot pass V1-V13 must never reach the repo."""
    packs = load_packs()
    assert packs
    total = 0
    for pack in packs:
        for persona in pack.personas():
            validate_persona(persona, pack=pack)
            total += 1
    assert total >= 8


def test_no_shipped_persona_targets_amount_payable():
    for pack in load_packs():
        for persona in pack.personas():
            for sel in persona["field_selectors"]:
                assert sel.get("field") != "amount_payable"
```

**Exit criterion:** `replay-gold` reaches 8/10 (the 8 native-text documents).

---

### Cluster C6: Real vision adapter with cassettes

**Unblocks:** the 2 image-only documents.
**Depends on:** C1, C5.

**Files:**
- Create: `src/docintel/adapters/vision/anthropic.py`, `cassette.py`
- Create: `tests/fixtures/cassettes/*.json`
- Modify: `cli.py` — `--vision {fake,cassette,live}`, default `cassette`
- Test: `tests/adapters/test_cassette.py`, `tests/adapters/test_anthropic_adapter.py`

**Interfaces:**
- `cassette.CassetteVision(inner: VisionExtractor | None, path: str, mode: "replay" | "record")`
- `anthropic_adapter.AnthropicVision(model: str = "claude-opus-5", api_key: str | None = None)` — renders pages to PNG, sends with the pack's field list, parses a structured response into `VisionResult`

**Key tests:**

```python
# tests/adapters/test_cassette.py
import json
import pytest
from docintel.adapters.vision.cassette import CassetteVision
from docintel.adapters.vision.port import VisionResult
from docintel.core.models import PageText


def _pages():
    return (PageText(page_number=1, words=(), width=1.0, height=1.0, source="ocr"),)


def test_replay_returns_the_recorded_result_without_calling_the_inner_adapter(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({
        "d41d8cd9": {"fields": {"total_printed": "1177.70"},
                     "confidence": {"total_printed": 0.82},
                     "irregularities": []}
    }))

    class Exploding:
        def extract(self, pages, field_names):
            raise AssertionError("must not be called in replay mode")

    v = CassetteVision(inner=Exploding(), path=str(path), mode="replay")
    result = v.extract(_pages(), ["total_printed"])
    assert result.fields["total_printed"] == "1177.70"


def test_replay_miss_is_a_loud_failure_not_a_silent_empty_result(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{}")
    v = CassetteVision(inner=None, path=str(path), mode="replay")
    with pytest.raises(KeyError, match="no cassette entry"):
        v.extract(_pages(), ["total_printed"])


def test_record_mode_persists_the_inner_result(tmp_path):
    path = tmp_path / "c.json"

    class Stub:
        def extract(self, pages, field_names):
            return VisionResult(fields={"total_printed": "481.20"},
                                confidence={"total_printed": 0.9})

    v = CassetteVision(inner=Stub(), path=str(path), mode="record")
    v.extract(_pages(), ["total_printed"])
    saved = json.loads(path.read_text())
    assert any(e["fields"]["total_printed"] == "481.20" for e in saved.values())


def test_cassette_key_is_stable_for_the_same_pages_and_fields(tmp_path):
    v = CassetteVision(inner=None, path=str(tmp_path / "c.json"), mode="replay")
    assert v.key(_pages(), ["a", "b"]) == v.key(_pages(), ["a", "b"])
    assert v.key(_pages(), ["a"]) != v.key(_pages(), ["a", "b"])
```

**Note on no API key:** cassettes for Complete Beverage and Federal Recycling are hand-authored from the gold files for the first pass (they are the expected vision output), then re-recorded live once a key exists. The journal must record that they are authored, not recorded.

**Exit criterion:** `replay-gold` reaches 10/10.

---

### Cluster C7: Persona store and single-flight jobs

**Unblocks:** nothing in the gold set directly; makes the fast lane real and 5c honest.
**Depends on:** C5.

**Files:**
- Create: `src/docintel/personas/__init__.py`, `store.py`, `export.py`
- Modify: `s4_persona.py` (real lookup + soft-miss detection), `s5c_agent.py` (real enqueue), `cli.py` (`personas` subcommand)
- Test: `tests/personas/test_store.py`, `test_export.py`, `tests/pipeline/test_fast_lane.py`

**Interfaces:**
- `store.PersonaStore(db_path: str)` with `.lookup(fingerprint, doc_type) -> Persona | None`, `.upsert(persona)`, `.enqueue_once(fingerprint, doc_type) -> bool`, `.claim_job() -> Job | None`, `.record_clean_extraction(fingerprint, doc_type) -> str` (returns new status), `.record_correction(...)`
- `export.dump(store, directory)`, `export.load(directory, store)`

**Key tests:**

```python
# tests/personas/test_store.py
from docintel.personas.store import PersonaStore


def test_enqueue_once_is_single_flight(tmp_path):
    """A burst of first-time documents must queue ONE job, not N."""
    s = PersonaStore(str(tmp_path / "p.sqlite3"))
    first = s.enqueue_once("acme.com|acme", "standard_invoice")
    rest = [s.enqueue_once("acme.com|acme", "standard_invoice") for _ in range(20)]
    assert first is True
    assert not any(rest)
    assert len(s.pending_jobs()) == 1


def test_different_persona_keys_get_their_own_job(tmp_path):
    s = PersonaStore(str(tmp_path / "p.sqlite3"))
    assert s.enqueue_once("a.com|a", "standard_invoice") is True
    assert s.enqueue_once("b.com|b", "standard_invoice") is True
    assert len(s.pending_jobs()) == 2


def test_claim_job_is_atomic(tmp_path):
    s = PersonaStore(str(tmp_path / "p.sqlite3"))
    s.enqueue_once("a.com|a", "standard_invoice")
    assert s.claim_job() is not None
    assert s.claim_job() is None


def test_promotion_needs_n_consecutive_clean_extractions(tmp_path):
    s = PersonaStore(str(tmp_path / "p.sqlite3"), promotion_threshold=3)
    s.upsert({"sender_fingerprint": "a|a", "doc_type": "standard_invoice",
              "rule_version": "v1", "status": "draft", "field_selectors": [],
              "layout_fingerprint": {}})
    assert s.record_clean_extraction("a|a", "standard_invoice") == "draft"
    assert s.record_clean_extraction("a|a", "standard_invoice") == "draft"
    assert s.record_clean_extraction("a|a", "standard_invoice") == "stable"


def test_a_correction_resets_the_counter_and_requeues(tmp_path):
    s = PersonaStore(str(tmp_path / "p.sqlite3"), promotion_threshold=3)
    s.upsert({"sender_fingerprint": "a|a", "doc_type": "standard_invoice",
              "rule_version": "v1", "status": "draft", "field_selectors": [],
              "layout_fingerprint": {}})
    s.record_clean_extraction("a|a", "standard_invoice")
    s.record_clean_extraction("a|a", "standard_invoice")
    s.record_correction("a|a", "standard_invoice", field="total_printed")
    assert s.record_clean_extraction("a|a", "standard_invoice") == "draft"
    assert len(s.pending_jobs()) == 1
```

```python
# tests/pipeline/test_fast_lane.py
def test_second_document_from_the_same_sender_takes_the_fast_lane(tmp_path):
    """The economic claim: pay the agent once, reuse forever."""
    from docintel.adapters.vision.fake import FakeVision
    from docintel.personas.store import PersonaStore
    from docintel.pipeline.hooks import HookRegistry
    from docintel.pipeline.runner import Runner
    from docintel.pipeline.stages import build_default_stages

    store = PersonaStore(str(tmp_path / "p.sqlite3"))
    # seeded with the authored EDCO persona from the Northstar pack
    from docintel.packs.registry import load_packs
    for pack in load_packs():
        for persona in pack.personas():
            store.upsert(persona)

    vision = FakeVision()
    runner = Runner(
        stages=build_default_stages(vision=vision, store=store),
        hooks=HookRegistry(),
    )
    path = "docs/EDCO 77087APR25 current charges can be misleading, paying $69.62.pdf"
    rec = runner.process("d1", path)
    assert rec["extraction_route"] == "5a_cached"
    assert vision.calls == [], "the fast lane must make ZERO vision calls"
```

**Exit criterion:** the fast lane makes zero vision calls; single-flight and promotion tests green; `replay-gold` stays 10/10.

---

## Loop completion

When the exit condition is met, do these three things and stop:

- [ ] **Write the final scorecard and journal entry**

```bash
python3 -m docintel.cli replay-gold --json > .loop/scorecard.json
python3 -m docintel.cli replay-gold | tee -a .loop/journal.md
```

- [ ] **Verify the whole gate**

```bash
python3 -m pytest -q
python3 docs/corpus/validate_gold.py
ruff check src tests
mypy
python3 -m docintel.cli process docs
```

Expected: tests green · 95 gold checks green · ruff clean · mypy clean · 10 records emitted

- [ ] **Report to the user, do not push**

Report: documents green, assertions green, which clusters landed, any gold value changed (with its justification), and anything left in the risk table.

---

## Self-review

**Spec coverage.** Every section of the design maps to work here: §1 architecture → the file structure and A1–A11 · §2 data flow → A8 plus C1 · §3.1 Decimal → A1 · §3.2 PageText seam → A3 and C1 · §3.3 type split → A3 and C2's V10 test · §3.4 two confidence inputs → A4 and C3 · §3.5 context manager → A7 · §4 error handling → A4 and A7 · §5 testing → A11 and every cluster · §6 bootstrap-then-converge → Parts A and B · §6 guardrails → the guardrail table plus `test_replay_never_mutates_gold` and `tests/test_f1_antiregression.py` · §7 risks → carried into cluster notes.

**Known gap, deliberate.** Design §6 lists a `show-record`, `personas` and `validate-grammar` CLI surface. Only `process` and `replay-gold` are specified as tasks, because those two are what the done bar needs; `personas` appears in C7 and the other two are not required to reach 10/10. They are noted here rather than silently dropped.

**Type consistency.** `JobContext` field names are fixed in A3 and used unchanged by every later task. `ExtractedFields.set(name, value, match_quality)` keeps its 3-arg signature throughout. `VisionExtractor.extract(pages, field_names) -> VisionResult` is identical in A8, C6 and every test. `Runner.stats` returns `{"intaken", "emitted"}` in A7, A9 and A11. `PersonaStore.enqueue_once` returns `bool` in both C7 tests and `s5c_agent.py`. `build_default_stages` gains a `store=` keyword in C7 — flagged there explicitly because A8 defines it with `vision` only.
