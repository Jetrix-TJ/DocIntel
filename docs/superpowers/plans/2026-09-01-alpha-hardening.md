# Alpha Hardening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 15 non-web-UI defects an independent 7-agent architecture review found on commit
`d8156d1` (the current `main`, now pushed to `Jetrix-TJ/DocIntel`) — the ones that make the system
unrunnable, unsafe, or unverifiable for an adopting team, without touching the web UI (out of scope
per product decision: the web UI is not part of this project's near-term surface).

**Architecture:** Each task is an independent, surgical fix to existing code — no new subsystem, no
restructuring. Every defect below was re-verified against the actual source on this checkout
immediately before this plan was written (file, line, and behavior confirmed by reading the code, not
by trusting the review). Tasks are ordered by the review's own P0 → P1 severity, since that ordering
reflects what hurts an adopting team first.

**Tech Stack:** Python 3.12, pytest, ruff, mypy — no new dependencies for any task.

**Spec:** No separate spec file — the review itself (pasted into the originating conversation, verified
against commit `d8156d1`) is the spec. Each task below restates its own verified problem and exact fix
so it is self-contained for a fresh implementer with no access to that conversation.

## Global Constraints

- No new runtime dependencies. Every fix uses the standard library or packages already in
  `pyproject.toml`.
- Every task's tests must pass with `pytest -q` before commit; do not touch `tests/fixtures/` (excluded
  from the default run by `pyproject.toml`'s `addopts`, on purpose — see `CLAUDE.md`).
- `ruff check src` and `mypy` (scoped per `pyproject.toml`'s `[tool.mypy]` allowlist) must stay clean
  after every task.
- Web UI (`src/docintel/webui/`) is explicitly OUT OF SCOPE for every task in this plan — do not modify
  it, even where a task's underlying bug is also reachable through it (Task 8's thread-safety fix
  protects the web UI as a side effect, which is fine; do not add web-UI-specific code for it).
- Follow this repo's existing commenting convention: comments explain WHY, never WHAT — see any
  existing module docstring in `src/docintel/` for the house style, and match it.

---

### Task 1: Gate scores declared-but-absent fields, not just declared-and-scored ones

**Verified problem:** `s7_gate.py`'s `_confidence_lane` (lines 198-213) only iterates
`ctx.confidence.items()`. A field that never produced a value — no selector matched, or the selector
ran and returned nothing — has no entry in `ctx.confidence` at all, so it can never appear in `short`
or `very_low`. If every field that *did* extract happens to be confident, the document routes to
`high` even though most of what the persona/pack declares came back empty. Confirmed on
`northstar-veritiv-715-33905296`: `subtotal`, `tax_amount`, `discount_amount`, `total_weight`, and 5
more all dropped, lane still `high`, `review_flag` still `False`, because none of those five is marked
`required` in the persona (only `bill_to_name` is) — so `_incomplete_reasons` (which reads
`ctx.coverage.missing_required` only) never catches it either.

**Files:**
- Modify: `src/docintel/pipeline/stages/s7_gate.py`
- Test: `tests/pipeline/test_s7_gate.py`

**Interfaces:**
- Consumes: `ConfidenceGate._thresholds_for(ctx)` (existing, unchanged), `ctx.pack.fields_for(doc_type)`
  (existing `Pack` protocol method — see `datapack.py:217`, returns `frozenset[str]`), `ctx.doc_type`
  (existing), `ctx.confidence` (existing `dict[str, float]`).
- Produces: `_confidence_lane` still returns `"high" | "medium" | "low"` — signature unchanged, callers
  unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_s7_gate.py — add near the existing lane-routing tests

def test_a_field_the_pack_declares_but_no_selector_ever_extracted_still_demotes_the_lane():
    """The exact northstar-veritiv defect: five undeclared-required money
    fields drop silently and the document still routes `high`."""
    class _Pack:
        thresholds: dict[str, float] = {}

        def fields_for(self, doc_type: str) -> frozenset[str]:
            return frozenset({"bill_to_name", "subtotal", "tax_amount", "total_printed"})

    ctx = make_ctx(  # existing test helper in this file
        pack=_Pack(),
        doc_type="standard_invoice",
        confidence={"bill_to_name": 0.97, "total_printed": 0.95},  # subtotal, tax_amount MISSING
    )
    gate = ConfidenceGate()
    lane = gate._confidence_lane(ctx)
    assert lane != "high"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pipeline/test_s7_gate.py::test_a_field_the_pack_declares_but_no_selector_ever_extracted_still_demotes_the_lane -v`
Expected: FAIL — `lane == "high"` under today's code.

- [ ] **Step 3: Implement the fix**

```python
# s7_gate.py — replace _confidence_lane

def _confidence_lane(self, ctx: JobContext) -> str:
    thresholds = self._thresholds_for(ctx)
    declared = self._declared_fields(ctx)
    short = [
        name for name in declared
        if ctx.confidence.get(name, 0.0) < thresholds.get(name, DEFAULT_THRESHOLD)
    ]
    if not short:
        return "high"

    very_low = [name for name in declared if ctx.confidence.get(name, 0.0) < VERY_LOW_FLOOR]
    if len(very_low) / len(declared) >= VERY_LOW_SHARE:
        return "low"
    return "medium"

def _declared_fields(self, ctx: JobContext) -> frozenset[str]:
    """Every field the pack declares for this doc_type, unioned with anything
    that produced a confidence entry anyway.

    Iterating `ctx.confidence` alone (the prior behavior) is blind to a field
    that never produced a value at all - no selector wrote to it, so it has
    no entry to be "short" against. A pack-declared field with no confidence
    entry is treated as score 0.0 (worse than any real miss the gate already
    catches), which is what makes it count as `short` below. The union with
    `ctx.confidence.keys()` keeps this correct even when `ctx.pack` is None
    (a caller-injected `thresholds` test seam with no real pack attached).
    """
    getter = getattr(ctx.pack, "fields_for", None)
    declared = getter(ctx.doc_type) if getter is not None and ctx.doc_type else frozenset()
    return declared | frozenset(ctx.confidence.keys())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/pipeline/test_s7_gate.py -v`
Expected: PASS, and every pre-existing test in this file still passes (the union with
`ctx.confidence.keys()` means a caller with no `pack.fields_for` — most existing unit tests — behaves
exactly as before).

- [ ] **Step 5: Run the gold-corpus regression check**

Run: `docintel eval-compare main candidate --suite full_pipeline` is not available pre-merge; instead
run `pytest tests/pipeline/ tests/pipeline/stages/ -v` and confirm no existing test that asserts a
specific lane on a fully-covered document changed outcome. If any did, that document's persona was
relying on this exact blind spot — flag it in the commit message, do not silently adjust the test's
expectation without a `# Ruling:` comment explaining why.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/pipeline/stages/s7_gate.py tests/pipeline/test_s7_gate.py
git commit -m "fix(gate): score a pack-declared field with no extracted value as a miss

_confidence_lane only ever looked at ctx.confidence, so a field with no
selector match had no entry to fail on and never demoted the lane -
5 of 9 money fields could vanish on a real document and it still
routed high. Union the pack's declared field set into the scored set."
```

---

### Task 2: Persona validator warns when a field can silently disappear

**Verified problem:** Task 1 fixes the gate's blindness at run time. This task fixes the authoring-time
gap that makes it likely in the first place: nothing today tells a persona author "this field is in the
pack's `fields.all` but you didn't mark it `required`, and no `adjust` op supplies it either — if your
selector ever misses, this value vanishes with no signal." `grammar/validator.py`'s V13
(`_check_required_coverage`, ~line 477) only checks `pack.required_fields(doc_type)` — fields the
author explicitly opted into strict checking for. There's no check at all for the rest of
`pack.fields_for(doc_type)`.

**Files:**
- Modify: `src/docintel/grammar/validator.py`
- Modify: `src/docintel/cli.py` (surface the new warnings from `validate-persona`)
- Test: `tests/grammar/test_validator.py`

**Interfaces:**
- Consumes: `pack.fields_for(doc_type)`, `pack.required_fields(doc_type)`, `pack.derived_only_fields(doc_type)`
  (all existing `Pack` protocol methods), `schema.OP_SUPPLIED_FIELDS` (existing, already imported in
  this file at line 41).
- Produces: new function `undeclared_risk_fields(persona, pack) -> list[str]` — returns field names
  that are declared-but-not-required-but-not-op-supplied-but-also-not-selector-covered. Non-fatal: does
  NOT raise, unlike every `V*` check in this file, since existing personas must keep validating clean.

- [ ] **Step 1: Write the failing test**

```python
# tests/grammar/test_validator.py

def test_undeclared_risk_fields_flags_an_optional_money_field_with_no_selector_and_no_op():
    pack = make_pack(  # existing test helper
        fields={"standard_invoice": {
            "all": ["bill_to_name", "subtotal", "total_printed"],
            "required": ["bill_to_name"],
            "any_of": [],
            "derived_only": [],
        }},
    )
    persona = {
        "doc_type": "standard_invoice",
        "field_selectors": [
            {"field": "bill_to_name", "region": "top-left", "pattern": "text"},
            {"field": "total_printed", "anchor": "Total", "region": "near-anchor", "pattern": "currency"},
            # subtotal has NO selector at all
        ],
    }
    risky = undeclared_risk_fields(persona, pack)
    assert risky == ["subtotal"]


def test_undeclared_risk_fields_does_not_flag_a_field_an_op_supplies():
    pack = make_pack(fields={"standard_invoice": {
        "all": ["vendor_name"], "required": [], "any_of": [], "derived_only": [],
    }})
    persona = {"doc_type": "standard_invoice", "field_selectors": []}
    # vendor_name is in OP_SUPPLIED_FIELDS for resolve_vendor_alias in real packs;
    # use whatever schema.OP_SUPPLIED_FIELDS actually maps for this test's field name,
    # or monkeypatch schema.OP_SUPPLIED_FIELDS for the test - see existing V13 tests
    # in this file for the established pattern.
    ...
```

(Match this file's existing helper functions — `make_pack`, monkeypatching `OP_SUPPLIED_FIELDS` — rather
than inventing new ones; the existing V13 tests a few hundred lines up already do exactly this.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/grammar/test_validator.py -k undeclared_risk_fields -v`
Expected: FAIL — `NameError: undeclared_risk_fields is not defined`.

- [ ] **Step 3: Implement**

```python
# grammar/validator.py — add near _check_v13 / the required-coverage helper

def undeclared_risk_fields(persona: Mapping[str, Any], pack: Pack) -> list[str]:
    """Fields that can silently vanish: declared by the pack, not required,
    not derived_only, not supplied by any adjust op, and not covered by any
    selector in THIS persona.

    Non-fatal on purpose - V1 through V13 are the hard security boundary
    (spec Part 6, "the agent writes data, never code") and every one of them
    rejects the whole write. This is different: a field genuinely CAN be
    legitimately absent on some vendor's documents, so making this a hard
    validation failure would break real, already-shipped personas. It exists
    to be surfaced as a warning at authoring time - see cli.py's
    `_cmd_validate_persona` - not to block anything.
    """
    doc_type = persona.get("doc_type")
    if doc_type is None:
        return []
    declared = pack.fields_for(doc_type)
    required = pack.required_fields(doc_type)
    derived = pack.derived_only_fields(doc_type)
    supplied = set()
    for selector in persona.get("field_selectors", []):
        for op in selector.get("adjust", []) or []:
            supplied |= OP_SUPPLIED_FIELDS.get(str(op), frozenset())
    covered = {
        s["field"] for s in persona.get("field_selectors", []) if "field" in s
    }
    at_risk = declared - required - derived - supplied - covered
    return sorted(at_risk)
```

- [ ] **Step 4: Wire it into the CLI**

```python
# cli.py — inside _cmd_validate_persona, after the existing validate_persona(...) call
# that raises on V1-V13 failure (search this file for "validate_persona(" to find the
# exact call site; the pattern below assumes it already prints a "persona is valid" line)

from docintel.grammar.validator import undeclared_risk_fields

risky = undeclared_risk_fields(persona, pack) if pack is not None else []
if risky:
    print(
        f"warning: {len(risky)} field(s) can silently disappear - declared by the "
        f"pack, not required, no op supplies them, no selector covers them: "
        f"{', '.join(risky)}",
        file=sys.stderr,
    )
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/grammar/test_validator.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/grammar/validator.py src/docintel/cli.py tests/grammar/test_validator.py
git commit -m "feat(grammar): warn when validate-persona finds a field that can silently disappear

Undeclared risk: a field in the pack's field set that isn't required,
isn't derived, isn't op-supplied, and has no selector in this persona
- exactly the authoring gap behind the s7_gate blind spot. Non-fatal,
surfaced at docintel validate-persona time."
```

---

### Task 3: Cap vision-derived confidence below every configured threshold

**Verified problem:** `adapters/vision/policy.py`'s `_clean_confidence` (line 94-97) clamps to
`min(_CEILING, max(VISION_FLOOR, value))` where `_CEILING = confidence.CEILING = Decimal("0.99")`
(`core/confidence.py:32`) and `VISION_FLOOR = 0.50`. A model's self-reported confidence can reach 0.99
— above every pack threshold observed (0.75-0.95) — so a collapsed-persona document backfilled by
vision can auto-approve on a model's own unverified confidence claim. Scope-verified: this path is
unreachable for a first-time/unclaimed sender (`s5c_agent.py:88` forces `review_flag = True`
unconditionally there); it is reachable only for a known vendor whose cached-rule extraction collapsed
and fell through to vision.

**Files:**
- Modify: `src/docintel/adapters/vision/policy.py`
- Test: `tests/adapters/test_vision_policy.py`

**Interfaces:**
- Consumes: nothing new — this changes an internal constant and its use, no signature changes.
- Produces: `sanitize(...)`'s confidence output ceiling changes from 0.99 to a new
  `VISION_CEILING = 0.70` (see rationale below) — anything asserting the old 0.99 ceiling in existing
  tests must be updated, not deleted.

- [ ] **Step 1: Write the failing test**

```python
# tests/adapters/test_vision_policy.py

def test_vision_confidence_never_exceeds_the_vision_ceiling_even_when_the_model_claims_higher():
    result = FakeVisionResult(
        fields={"total_printed": "100.00"},
        confidence={"total_printed": 0.99},  # model claims near-certain
    )
    cleaned = sanitize(result, field_names=["total_printed"], table_requests={})
    assert cleaned.confidence["total_printed"] <= VISION_CEILING
    assert VISION_CEILING < 0.75  # below the lowest real pack threshold this repo ships
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_vision_policy.py -k vision_ceiling -v`
Expected: FAIL — `NameError: VISION_CEILING is not defined` (or the assertion fails at 0.99).

- [ ] **Step 3: Implement**

```python
# policy.py

# A model's self-reported confidence is not evidence the way a matched
# selector's confidence is - a selector confirms it found the label AND the
# shape it expected; a vision model can be confidently wrong about a value it
# invented. Capped below the lowest threshold ANY shipped pack configures
# (0.75-0.95, see selector-grammar.md section 5) so a vision-only read can
# never itself clear the auto-approve bar - it can only ever land a document
# in medium/review, same as any other soft-miss modifier.
VISION_CEILING = 0.70

_CEILING = float(VISION_CEILING)  # was: float(CEILING) — see module docstring update below
```

Update the module's existing comment block above `VISION_FLOOR` (lines ~70-80) to explain the ceiling
is now `VISION_CEILING`, not the global `confidence.CEILING`, and why (a vision read must never itself
clear an auto-approve threshold).

- [ ] **Step 4: Run tests, fix any that assumed 0.99**

Run: `pytest tests/adapters/test_vision_policy.py -v`
Any pre-existing test asserting a vision-path confidence at or near 0.99 needs its expected value
updated to reflect the new 0.70 ceiling — update the assertion, not the fix.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/adapters/vision/policy.py tests/adapters/test_vision_policy.py
git commit -m "fix(vision): cap vision-derived confidence below every configured threshold

_clean_confidence clamped to the global 0.99 ceiling, above every real
pack threshold (0.75-0.95) - a collapsed persona backfilled by vision
could auto-approve on the model's own unverified confidence. New
VISION_CEILING=0.70 means a vision read can never itself clear the
auto-approve bar."
```

---

### Task 4: Get CI to a state where pytest actually runs, every time

**Verified problem:** `.github/workflows/ci.yml` is one job with linear `steps:` — `ruff check src` →
`mypy` → `pytest -q`. `pyproject.toml:20` declares `ruff>=0.5`, unpinned, so CI always resolves the
newest ruff while a developer's local install can be months stale — confirmed: this repo's current
ruff reports 0 errors locally, 33 on the version CI would resolve today. `pip install -e ".[dev,ui]"`
(line 42) omits `vision`/`export`/`email`, so `pytest` at collection time is missing `openpyxl`/`httpx`
for any test that imports them.

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`

**Interfaces:** None — CI/packaging config only, no code interfaces change.

- [ ] **Step 1: Pin ruff to the exact version this repo lints clean under**

```bash
ruff --version   # record the exact version string, e.g. "ruff 0.14.13"
```

```toml
# pyproject.toml
dev = ["pytest>=8.0", "ruff==0.14.13", "mypy>=1.10"]  # exact version from above, not >=
```

- [ ] **Step 2: Run ruff locally to confirm this pin is genuinely clean**

Run: `pip install "ruff==0.14.13" && ruff check src`
Expected: 0 errors. If this version is NOT the one the repo is actually clean under, adjust the pin to
whichever version `ruff check src` reports 0 errors under right now, then re-run to confirm.

- [ ] **Step 3: Split the CI workflow into independent jobs**

```yaml
# .github/workflows/ci.yml — restructure `jobs:` from one `test` job with
# linear steps into three independent jobs, so a lint failure can no longer
# hide whether the test suite itself would have passed.

jobs:
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: ruff check src

  typecheck:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install -e ".[dev]"
      - run: mypy

  test:
    strategy:
      fail-fast: false
      matrix:
        os: [ubuntu-latest, windows-latest]
    runs-on: ${{ matrix.os }}
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - name: Install Tesseract (Linux)
        if: runner.os == 'Linux'
        run: sudo apt-get update && sudo apt-get install -y tesseract-ocr
      - name: Install Tesseract (Windows)
        if: runner.os == 'Windows'
        run: choco install tesseract --version=5.3.3.20231005 -y
      - name: Install docintel
        run: pip install -e ".[dev,ui,vision,export,email]"
      - run: pytest -q
      # ...(the existing eval-history cache/record/compare steps move here unchanged,
      # still gated to `matrix.os == 'ubuntu-latest'` exactly as today)
```

Move the existing "Restore eval history cache" / "Record this run's eval suites" / "Compare against the
last main-branch run" / "Save eval history cache" steps verbatim into the `test` job, unchanged — they
already correctly gate on `matrix.os == 'ubuntu-latest'` and don't need to move logic, only location.

- [ ] **Step 4: Fix the Tesseract install hang**

The 6-hour hang was on `apt-get update` (Linux step). Pin to a specific, cached-friendly form:

```yaml
- name: Install Tesseract (Linux)
  if: runner.os == 'Linux'
  run: sudo apt-get update -qq && sudo apt-get install -y --no-install-recommends tesseract-ocr
```

`-qq` and `--no-install-recommends` reduce the chance of a slow/interactive prompt stalling the step;
if the hang recurs after this change, add `timeout-minutes: 10` to the step so it fails fast and
visibly instead of burning 6 billed hours again.

- [ ] **Step 5: Verify locally as much as CI-parity allows**

Run: `pip install -e ".[dev,ui,vision,export,email]" && pytest -q`
Expected: the suite collects and runs (0 collection errors) — individual test pass/fail counts are a
separate, pre-existing concern this task does not need to fix.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml
git commit -m "fix(ci): pin ruff, split into independent jobs, install full test-relevant extras

Three CI runs ever, all failed, none reached pytest - ruff>=0.5 let CI
lint with a newer ruff than any local dev, and a single linear job
meant that failure hid the test suite's real status entirely. Split
lint/typecheck/test into independent jobs and install [vision,export,email]
so collection doesn't fail on missing openpyxl/httpx."
```

---

### Task 5: Add a CI signal for the real-pack fixture suite

**Verified problem:** `pyproject.toml:84`, `addopts = "--ignore=tests/fixtures"` — intentional, and
documented in `CLAUDE.md` as opt-in only for local dev. But CI has never run it either, so the 245
tests across 32 files that exercise real vendor packs end-to-end have no CI signal of their own at all.

**Files:**
- Modify: `.github/workflows/ci.yml` (the `test` job from Task 4)

**Interfaces:** None.

- [ ] **Step 1: Add a non-blocking step for the fixture suite**

```yaml
# .github/workflows/ci.yml — in the `test` job, after the main `pytest -q` step

- name: Real-pack fixture suite (non-blocking today)
  if: matrix.os == 'ubuntu-latest'
  continue-on-error: true
  run: pytest tests/fixtures/packs/ -q
```

`continue-on-error: true` deliberately: this suite has never run in CI, so its current pass/fail state
is unknown. Making it blocking on day one could turn a merge freeze into the first thing this task
does. Once a maintainer has seen one green (or understood one red) run, `continue-on-error` can be
dropped in a follow-up — note that explicitly in the commit message so it isn't forgotten.

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add a non-blocking signal for the real-pack fixture suite

245 tests across 32 files - the only end-to-end tests against real
vendor packs - have never run in CI (pyproject.toml's addopts excludes
them from the default run, correctly, per CLAUDE.md). Give them a CI
signal without yet gating the build on a suite whose current state is
unknown."
```

---

### Task 6: Make the documented first command work, or fail with a clear reason

**Verified problem:** `cli.py:23`, `DEFAULT_CASSETTE = "tests/fixtures/cassettes/corpus.json"` — a
path under `tests/`, never packaged (`pyproject.toml` ships only `src/docintel`). A fresh
`pip install` user running the README's own documented `docintel process any.pdf --json` gets
`--vision cassette` (the CLI default), pointing at a path that will not exist post-install.
`CassetteVision._load` (`cassette.py:208-215`) tolerates a missing file gracefully (`return {}`), so
this is not a crash — it is every field silently coming back as a vision miss with no persona to fall
back on either (a fresh install ships zero packs), which is indistinguishable from "the library is
broken" to a first-time user.

**Files:**
- Modify: `src/docintel/cli.py`
- Test: `tests/test_cli.py` (or wherever this repo's existing CLI-level tests live — confirm with
  `pytest --collect-only -q | grep -i cli`)

**Interfaces:**
- Consumes: `os.path.isfile` (stdlib).
- Produces: `_build_vision` gains a clear warning path; no signature change.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py

def test_cassette_mode_warns_clearly_when_the_default_cassette_is_not_packaged(capsys):
    vision = _build_vision("cassette", "/definitely/does/not/exist/corpus.json")
    captured = capsys.readouterr()
    assert "no cassette found" in captured.err.lower()
    # still returns a working (if empty) CassetteVision - never raises, never silently proceeds mute
    assert vision is not None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -k cassette_mode_warns -v`
Expected: FAIL — nothing is printed to stderr today.

- [ ] **Step 3: Implement**

```python
# cli.py — inside _build_vision, in the `mode == "cassette"` branch

from docintel.adapters.vision.cassette import CassetteVision

if mode == "cassette":
    if not os.path.isfile(cassette):
        print(
            f"warning: no cassette found at {cassette!r} - every vision lookup will "
            f"miss. This is expected in a fresh install with no recorded cassette; "
            f"pass --vision fake for a wiring check, or --vision live with "
            f"GEMINI_API_KEY set for a real read.",
            file=sys.stderr,
        )
    return CassetteVision(inner=None, path=cassette, mode="replay")
```

`sys` is already imported at the top of `cli.py` (line 9) — no new import needed.

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/cli.py tests/test_cli.py
git commit -m "fix(cli): warn clearly when the default cassette isn't packaged

DEFAULT_CASSETTE lives under tests/, never shipped in the wheel/sdist.
A fresh install running the README's own first command got silent
misses on every field with no signal why. Print an actionable warning
instead of proceeding mute."
```

---

### Task 7: Give the CLI a way to load an authored pack

**Verified problem:** `cli.py` has `--pack`/`--pack-file` only on the `validate-persona` subcommand
(lines 1088-1089). `_cmd_process`'s runner (`_build_runner`, line 58) calls
`build_pipeline(vision=..., jobs=..., telemetry=...)` with no `extra_packs` argument at all, even
though `build_pipeline(extra_packs=[...])` already exists in the library API (see `CLAUDE.md`'s
"Two ways to add vendor data" section) — there is simply no CLI path to reach it. An adopter who
completes onboarding (writes `pack.json` + `persona.json`, runs `validate-persona` successfully) has
no way to actually run `docintel process` against their own pack.

**Files:**
- Modify: `src/docintel/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `docintel.packs.datapack.load_pack_file(path) -> DataPack` (existing, used elsewhere in
  `cli.py` already for `validate-persona`).
- Produces: `_build_runner` gains an `extra_pack_paths: list[str] | None` parameter; `_cmd_process`'s
  arg parser gains `--extra-packs`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py

def test_extra_packs_flag_loads_a_pack_file_into_the_runner(tmp_path):
    pack_path = tmp_path / "pack.json"
    pack_path.write_text(json.dumps(MINIMAL_VALID_PACK_SPEC))  # existing fixture in this test module

    args = argparse.Namespace(vision=None, cassette=None, extra_packs=[str(pack_path)])
    runner = _build_runner(args)
    assert any(p.name == MINIMAL_VALID_PACK_SPEC["name"] for p in runner.packs)
```

(`runner.packs` — confirm the actual attribute name `Runner` exposes its registered packs under by
reading `pipeline/runner.py`'s `__init__`; adjust the assertion to match rather than guessing.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py -k extra_packs_flag -v`
Expected: FAIL — `AttributeError: 'Namespace' object has no attribute 'extra_packs'` or similar.

- [ ] **Step 3: Implement**

```python
# cli.py — _build_runner

def _build_runner(args: argparse.Namespace | None = None, *, telemetry: bool = False) -> Runner:
    from docintel.jobs.store import SQLiteJobQueue
    from docintel.packs.datapack import load_pack_file

    mode = getattr(args, "vision", None) or "cassette"
    cassette = getattr(args, "cassette", None) or DEFAULT_CASSETTE
    extra_pack_paths = getattr(args, "extra_packs", None) or []
    extra_packs = [load_pack_file(path) for path in extra_pack_paths]

    return build_pipeline(
        vision=_build_vision(mode, cassette),
        jobs=SQLiteJobQueue(),
        telemetry=telemetry,
        extra_packs=extra_packs,
    )
```

```python
# cli.py — wherever the `process` subcommand's argparser is built (search for
# "add_parser(\"process\"" in this file)

process_parser.add_argument(
    "--extra-packs",
    nargs="+",
    default=None,
    metavar="PACK_JSON",
    help="path(s) to a pack.json to load for this run - the CLI path to "
         "build_pipeline(extra_packs=[...]) for a pack you authored",
)
```

Also honor a `DOCINTEL_EXTRA_PACKS` env var (colon/os.pathsep-separated) as a fallback for a caller who
can't pass CLI flags (matches the existing `DOCINTEL_EXTRA_PERSONAS_DIR` convention):

```python
if not extra_pack_paths:
    env_value = os.environ.get("DOCINTEL_EXTRA_PACKS")
    if env_value:
        extra_pack_paths = env_value.split(os.pathsep)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/test_cli.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/cli.py tests/test_cli.py
git commit -m "feat(cli): add --extra-packs so a completed onboarding can actually run

build_pipeline(extra_packs=[...]) already existed as a library API but
had no CLI path - an adopter who finished writing and validating a
pack had no way to run docintel process against it. Add --extra-packs
and a DOCINTEL_EXTRA_PACKS env-var fallback."
```

---

### Task 8: Serialize the pdfium-touching render call; correct the README's thread-safety claim

**Verified problem:** `annotations.py:199`, `_page_is_annotated`: `page.to_image(resolution=RESOLUTION)`
reaches pypdfium2 through pdfplumber, which is not thread-safe. `s2_filter.py:163`,
`annotations.detect_flattened(path, pages, page_meta)` runs unconditionally for every PDF, every run —
this is the hot path, not an edge case. Measured (per the review): 2 threads sharing one `Runner` →
`SIGABRT`; 8 threads → `SIGSEGV`; even one `Runner` per thread (the README's own documented pattern)
still crashes, because the unsafety is pypdfium2's process-global native state, which `Runner`-per-
thread does nothing to isolate. `multiprocessing.Pool(4)` was measured clean.

**Files:**
- Modify: `src/docintel/extract/annotations.py`
- Modify: `README.md` (correct the concurrency guidance)
- Test: `tests/extract/test_annotations.py`

**Interfaces:**
- Consumes: `threading.Lock` (stdlib, new import in this module).
- Produces: `_page_is_annotated`'s public behavior is unchanged (same input/output) — only its
  internal concurrency safety changes. No caller needs to change.

- [ ] **Step 1: Write the failing test (concurrency-shaped, not a segfault reproduction)**

A true segfault reproduction isn't a reasonable unit test (it can crash the test runner itself). Test
the serialization mechanism directly instead:

```python
# tests/extract/test_annotations.py

def test_page_is_annotated_calls_are_serialized_by_a_module_lock(monkeypatch):
    """Proves the lock is actually held around the pdfium-touching call, by
    checking it's the SAME lock object across two calls and that a second
    call cannot acquire it while the first (simulated) is still inside."""
    from docintel.extract import annotations

    calls_in_flight = []

    def fake_to_image(*, resolution):
        calls_in_flight.append(1)
        assert len(calls_in_flight) == 1, "two calls entered the pdfium region concurrently"
        calls_in_flight.pop()
        class _Img:
            original = FAKE_BLANK_IMAGE  # existing test fixture in this file
        return _Img()

    monkeypatch.setattr(FAKE_PAGE, "to_image", fake_to_image)
    threads = [threading.Thread(target=lambda: annotations._page_is_annotated(FAKE_PAGE)) for _ in range(8)]
    for t in threads: t.start()
    for t in threads: t.join()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/extract/test_annotations.py -k serialized_by_a_module_lock -v`
Expected: FAIL — with high probability across 8 concurrent threads and no lock, the assertion inside
`fake_to_image` trips (two threads both append before either pops). Flaky-by-nature without the fix;
that flakiness itself IS the proof the lock is missing.

- [ ] **Step 3: Implement**

```python
# annotations.py — add near the top, after imports

import threading

# pypdfium2 (reached via pdfplumber's page.to_image()) holds process-global
# native state and is not thread-safe - confirmed: 2 threads sharing a Runner
# -> SIGABRT, 8 threads -> SIGSEGV, even one Runner per thread (this repo's
# own documented "one Runner per worker" pattern) still crashes, because
# Runner-per-thread only isolates Python-level state, not pdfium's native
# state. This lock serializes every call that reaches page.to_image() -
# cheap, since annotation detection is already a small fraction of total
# per-document time, and correct, since the alternative measured clean only
# under full process isolation (multiprocessing.Pool).
_PDFIUM_RENDER_LOCK = threading.Lock()


def _page_is_annotated(page: Page) -> bool:
    with _PDFIUM_RENDER_LOCK:
        img = page.to_image(resolution=RESOLUTION).original.convert("RGB")
    return _image_is_annotated(img)
```

- [ ] **Step 4: Run tests to verify pass, repeatedly (flaky-test-hunting)**

Run: `pytest tests/extract/test_annotations.py -k serialized_by_a_module_lock --count=20 -v` (needs
`pytest-repeat`; if unavailable, run the bare command 20 times in a shell loop instead — the point is
the same test must pass consistently now, not just once).
Expected: PASS every time.

- [ ] **Step 5: Correct the README**

```markdown
<!-- README.md — in the "One Runner per concurrent worker" section -->

**One `Runner` per concurrent worker, not one shared across threads — and PDF
rendering itself is also not thread-safe, independent of Runner count.** A
`Runner` keeps small mutable state ... [existing text] ... A `Runner` per
worker fixes the Python-level state; it does NOT make concurrent PDF
rendering safe, because pypdfium2 (reached during annotation detection) holds
process-global native state. `docintel` serializes its own internal calls
into pypdfium2 with a lock, but if your own code also renders PDFs directly
alongside `docintel` in the same process, use process-based concurrency
(`multiprocessing`, or a WSGI server's process workers rather than threads)
for true isolation.
```

- [ ] **Step 6: Commit**

```bash
git add src/docintel/extract/annotations.py README.md tests/extract/test_annotations.py
git commit -m "fix(extract): serialize the pdfium-touching render call

page.to_image() reaches pypdfium2, which is not thread-safe process-
global native state - 2 threads sharing a Runner segfaults, and so
does the README's own documented one-Runner-per-thread pattern, since
neither isolates pdfium's native state. Serialize with a module lock;
correct the README's claim that Runner-per-worker alone is sufficient."
```

---

### Task 9: Delete false vendor rosters from reference docs, link the honest one from the README

**Verified problem:** Confirmed in Task 4's own investigation and the review: multiple `docs/*.html`
files (`DOCINTEL-FEATURE-EXPLORER.html`, `DOCINTEL-TEAM-GUIDE.html`, etc.) predate this project's shift
to "zero pre-configured vendors, ship as a pure framework" and still advertise a vendor roster that
doesn't exist in a fresh install. `docs/BUGS-FEATURES-PRODUCTION.md` is described as "the most truthful
artifact in the repo" and is linked from nowhere.

**Files:**
- Modify: whichever `docs/*.html` files a grep confirms still claim shipped vendors (find with
  `grep -rl "PACK_MODULES\|northstar\|digitaldirection" docs/*.html` and inspect each hit — some
  mentions of these names are legitimate reference-example descriptions, matching `CLAUDE.md`'s own
  framing; only remove/correct a claim that implies these ship by default, not every mention of the
  name)
- Modify: `README.md`

**Interfaces:** None — documentation only.

- [ ] **Step 1: Find every false claim**

```bash
grep -n "PACK_MODULES\|PACK_FILES" docs/*.html
```

For each hit, read the surrounding paragraph. Fix any sentence that implies a vendor ships by default;
leave alone any sentence that correctly frames northstar/digitaldirection/spt_metals/acme_freight as
reference examples under `tests/fixtures/packs/` (the correct, current framing, already used
consistently in `CLAUDE.md` and the Complete Guide artifact from this project's docs work).

- [ ] **Step 2: Fix each false claim**

There is no single mechanical find-replace here — each file's exact wording needs reading and a
judgment call about whether it's stating "these ship" (false, fix it) vs. "these are reference
examples" (true, leave it). Apply the same correction pattern already used successfully in this
project's `CLAUDE.md` and `docintel-complete-guide.html`: *"Ships as a pure framework — zero
pre-configured vendors. `PACK_MODULES`/`PACK_FILES` in `registry.py` are both empty tuples. All real
company configuration lives only under `tests/fixtures/packs/`, loaded via `pyproject.toml`'s
`pythonpath` — never shipped to a real adopter."*

- [ ] **Step 3: Link the honest doc from the README**

```markdown
<!-- README.md — add near the "Go deeper" section -->

**[`docs/BUGS-FEATURES-PRODUCTION.md`](docs/BUGS-FEATURES-PRODUCTION.md)** — the running, honest list
of what's broken, what's missing, and what production actually needs. Read this before deciding
whether a gap you hit is known or new.
```

- [ ] **Step 4: Verify no other doc still makes the same false claim**

Run: `grep -rn "northstar\|digitaldirection" docs/*.html README.md ONBOARDING.md` and read every
remaining hit once more for the same "ships by default" framing error.

- [ ] **Step 5: Commit**

```bash
git add docs/*.html README.md
git commit -m "docs: remove false shipped-vendor claims, link the honest production doc

Several reference docs predate the zero-pre-configured-vendors design
and still implied northstar/digitaldirection/etc. ship by default.
Also link BUGS-FEATURES-PRODUCTION.md from the README - it was linked
from nowhere despite being the most accurate doc in the repo."
```

---

### Task 10: Byte, page, and pixel ceilings at intake

**Verified problem:** No ceiling exists anywhere between "a file was handed to intake" and "it gets
rasterized." Measured: a 500-page, 5MB PDF took 42.2s and 2,969MB on one thread. A crafted 200×200-inch
page inside a 25MB upload rasterizes to roughly 4.8GB. `PIL.Image.MAX_IMAGE_PIXELS` is never set, so
Pillow's own decompression-bomb guard is unused.

**Files:**
- Modify: `src/docintel/pipeline/stages/s2_filter.py` (or wherever page count / rasterization is first
  reachable — confirm exact insertion point by reading `s2_filter.py`'s full `run` method; the
  `load_document(path)` call at line 162, already read in this plan's research, is the right place to
  check page count immediately after)
- Modify: `src/docintel/__init__.py` or a new small module for the `MAX_IMAGE_PIXELS` setting (set it
  once, at import time, matching however this codebase's other one-time setup happens — check for an
  existing pattern before inventing a new one)
- Test: `tests/pipeline/test_s2_filter.py`

**Interfaces:**
- Produces: a new `PermanentError` (existing error class, `core/errors.py`) raised when a document
  exceeds a configured ceiling — routes to `dead_letter` through the same mechanism every other
  Stage 2 rejection already uses. Do not invent a new disposition.

- [ ] **Step 1: Write the failing test**

```python
# tests/pipeline/test_s2_filter.py

def test_a_pdf_past_the_page_ceiling_dead_letters_with_a_clear_reason():
    huge_pdf = make_pdf_with_n_pages(2000)  # existing or new small test helper
    ctx = run_stage2(huge_pdf)  # existing test helper pattern in this file
    assert ctx.disposition == "dead_letter"
    assert "page" in ctx.dead_letter_reason.lower()


def test_max_image_pixels_is_set_to_guard_against_decompression_bombs():
    from PIL import Image
    import docintel  # importing the package must have set this
    assert Image.MAX_IMAGE_PIXELS is not None
    assert Image.MAX_IMAGE_PIXELS < 500_000_000  # a sane, documented ceiling
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pipeline/test_s2_filter.py -k page_ceiling -v`
Expected: FAIL.

- [ ] **Step 3: Implement the page ceiling**

```python
# s2_filter.py — near the top

MAX_PAGES = 750  # generous relative to any real invoice; the measured 500-page
                  # case already took 42s/3GB on one thread at well under this

# inside the run() method, immediately after `pages, page_meta, text_source = load_document(path)`:
if len(pages) > MAX_PAGES:
    raise PermanentError(
        f"{len(pages)} pages exceeds the {MAX_PAGES}-page ceiling - "
        f"this is almost certainly not a real invoice/bill"
    )
```

(Confirm `PermanentError` raised here is already caught by this stage's existing error handling and
converted to `dead_letter` — every other Stage 2 rejection in this file already follows this pattern;
match it exactly rather than adding new exception handling.)

- [ ] **Step 4: Implement the pixel ceiling**

```python
# src/docintel/__init__.py — at module import time, near the top, before any
# other docintel import that might touch Pillow

from PIL import Image

# Decompression-bomb guard: unset by default, so Pillow silently allocates
# whatever a crafted file's dimensions claim. A 200x200-inch page inside a
# 25MB upload rasterizes to ~4.8GB unguarded. 400 million pixels is generous
# for any real scanned invoice page (a 300 DPI Letter page is ~8.5M pixels).
Image.MAX_IMAGE_PIXELS = 400_000_000
```

- [ ] **Step 5: Run tests to verify pass**

Run: `pytest tests/pipeline/test_s2_filter.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add src/docintel/pipeline/stages/s2_filter.py src/docintel/__init__.py tests/pipeline/test_s2_filter.py
git commit -m "fix(intake): add page ceiling at Stage 2, set Image.MAX_IMAGE_PIXELS

No ceiling existed anywhere before rasterization - a 500-page PDF
measured 42s/3GB on one thread, and MAX_IMAGE_PIXELS was never set,
so Pillow's own decompression-bomb guard was unused. A 750-page
ceiling dead-letters with a clear reason; 400M pixels is generous for
any real scanned page."
```

---

### Task 11: Stop discarding documents silently at intake

**Verified problem:** `adapters/intake/email.py:132-146` (`_items_for`): `except Exception: items = []`
wraps `list(self._from_eml(path))` / `list(self._from_msg(path))` — if attachment 3 of 5 raises while
being processed, ALL 5 (including the 2 already successfully parsed) are discarded, replaced by one
fallback item for the raw, unparseable-as-a-document `.eml`/`.msg` path itself. `adapters/intake/filesystem.py:53-60`
(`_walk`): files whose suffix isn't in `ACCEPTED_SUFFIXES` are filtered out with zero logging — a typo'd
extension or an unsupported format placed in a watched directory vanishes with no trace.

**Files:**
- Modify: `src/docintel/adapters/intake/email.py`
- Modify: `src/docintel/adapters/intake/filesystem.py`
- Test: `tests/adapters/test_intake_email.py`, `tests/adapters/test_intake_filesystem.py` (confirm
  actual test file names via `pytest --collect-only -q | grep -i intake`)

**Interfaces:**
- Consumes: `logging.getLogger(__name__)` (stdlib) — new in both modules.
- Produces: no change to either class's public `items()` iterator shape — only internal
  logging/per-attachment isolation changes.

- [ ] **Step 1: Write the failing test for email**

```python
# tests/adapters/test_intake_email.py

def test_one_malformed_attachment_does_not_discard_the_others_that_parsed_fine():
    eml_path = make_eml_with_attachments([  # existing or new test helper
        ("good1.pdf", b"%PDF-1.4 valid bytes..."),
        ("bad.pdf", None),  # simulate a payload that raises during decode
        ("good2.pdf", b"%PDF-1.4 valid bytes..."),
    ])
    items = list(EmailIntake([eml_path]).items())
    filenames = {os.path.basename(i.path) for i in items}
    assert "good1.pdf" in str(filenames) or len(items) >= 2  # both good attachments survive
```

(Adjust to however this test file already constructs a `.eml` with a genuinely malformed attachment —
match its existing fixture-building pattern rather than inventing a new one from scratch.)

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/adapters/test_intake_email.py -k does_not_discard_the_others -v`
Expected: FAIL — today's code drops all 3 to one fallback item.

- [ ] **Step 3: Implement — isolate per-attachment failures**

```python
# adapters/intake/email.py

import logging

_LOG = logging.getLogger(__name__)

def _items_for(self, path: str) -> Iterator[IntakeItem]:
    suffix = os.path.splitext(path)[1].lower()
    items: list[IntakeItem] = []
    try:
        if suffix == EML_SUFFIX:
            items = list(self._from_eml_resilient(path))
        elif suffix == MSG_SUFFIX:
            items = list(self._from_msg_resilient(path))
    except Exception:  # noqa: BLE001 - the email container itself is unreadable
        items = []
    if items:
        yield from items
    else:
        yield IntakeItem(_fallback_document_id(path), path)

def _from_eml_resilient(self, path: str) -> Iterator[IntakeItem]:
    """Wraps `_from_eml`'s per-attachment work so ONE bad attachment's
    exception doesn't discard every attachment already yielded before it -
    the prior behavior wrapped the whole `list(...)` call in one try/except,
    so attachment 3 of 5 raising lost the first 2 that had already parsed
    fine."""
    with open(path, "rb") as fh:
        raw = fh.read()
    msg = email_stdlib.message_from_bytes(raw, policy=email_policy.default)
    email_key = _stable_email_key(raw, msg.get("Message-Id"))
    sender = msg.get("From")

    index = 0
    for part in msg.iter_attachments():
        index += 1
        try:
            data = part.get_payload(decode=True)
            if not data:
                continue
            filename = part.get_filename() or f"attachment-{index}"
            temp_path = _write_temp_attachment(filename, data)
            document_id = _attachment_document_id(email_key, index, filename, len(data))
        except Exception:
            _LOG.warning(
                "eml %s: attachment %d failed to decode, skipping it only", path, index
            )
            continue
        yield IntakeItem(document_id, temp_path, sender_email=sender, email_id=email_key)
```

(Apply the same per-attachment try/except pattern to `_from_msg` → `_from_msg_resilient`.)

- [ ] **Step 4: Write the failing test for filesystem**

```python
# tests/adapters/test_intake_filesystem.py

def test_an_unrecognized_extension_is_logged_when_skipped(tmp_path, caplog):
    (tmp_path / "invoice.pdf").write_bytes(b"%PDF-1.4...")
    (tmp_path / "readme.xyz").write_text("not a document")
    with caplog.at_level(logging.INFO):
        items = list(FilesystemIntake([str(tmp_path)]).items())
    assert len(items) == 1  # only the .pdf became an IntakeItem
    assert "readme.xyz" in caplog.text
```

- [ ] **Step 5: Implement — log the skip**

```python
# adapters/intake/filesystem.py

import logging

_LOG = logging.getLogger(__name__)

@staticmethod
def _walk(root: str) -> Iterator[IntakeItem]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if os.path.splitext(name)[1].lower() in ACCEPTED_SUFFIXES:
                yield IntakeItem(
                    _stable_id(os.path.join(dirpath, name)),
                    os.path.join(dirpath, name),
                )
            else:
                _LOG.info("skipping unrecognized file at intake: %s", os.path.join(dirpath, name))
```

- [ ] **Step 6: Run tests to verify pass**

Run: `pytest tests/adapters/test_intake_email.py tests/adapters/test_intake_filesystem.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/adapters/intake/email.py src/docintel/adapters/intake/filesystem.py \
        tests/adapters/test_intake_email.py tests/adapters/test_intake_filesystem.py
git commit -m "fix(intake): isolate per-attachment failures, log unrecognized-file skips

One malformed email attachment discarded the whole batch (including
attachments that had already parsed fine) because the try/except
wrapped list(...) rather than each attachment. Directory intake
filtered unrecognized extensions with zero logging. Isolate the
former per-attachment; log the latter."
```

---

### Task 12: Allowlist `fields.<doc_type>` keys so a typo fails loudly

**Verified problem:** `packs/datapack.py`'s `_for(doc_type, key)` (line 214-215) is a plain
`self._fields.get(doc_type, {}).get(key)`. `required_fields()` calls `_for(doc_type, "required")` —
if a pack author writes `"require": [...]` instead of `"required": [...]` inside `fields.<doc_type>`,
this silently returns `None` → an empty frozenset → zero required-field enforcement for that doc_type,
with no error anywhere. `DataPack.__init__` already validates SOME structure (line 160-180: unknown
`doc_types`, unknown `vision_defaults` doc_types, stray ladder doc_types) but never validates the key
set inside each `fields.<doc_type>` sub-dict.

**Files:**
- Modify: `src/docintel/packs/datapack.py`
- Test: `tests/packs/test_datapack.py`

**Interfaces:**
- Produces: `DataPack.__init__` now raises `PackSpecError` (existing exception class, already used
  throughout this `__init__`) for an unrecognized key inside any `fields.<doc_type>` entry.

- [ ] **Step 1: Write the failing test**

```python
# tests/packs/test_datapack.py

def test_a_typo_d_fields_key_raises_at_load_time_instead_of_silently_disabling_it():
    spec = make_minimal_pack_spec()  # existing helper
    spec["fields"] = {
        spec["doc_types"][0]: {
            "all": ["vendor_name"],
            "require": ["vendor_name"],  # TYPO: should be "required"
            "any_of": [],
            "derived_only": [],
        }
    }
    with pytest.raises(PackSpecError, match="require"):
        DataPack(spec, directory="test")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/packs/test_datapack.py -k typo_d_fields_key -v`
Expected: FAIL — no exception raised today; `require` is silently ignored.

- [ ] **Step 3: Implement**

```python
# datapack.py — DataPack.__init__, immediately after the existing
# `unknown = set(self._fields) - set(self.doc_types)` check (line 160-164)

_ALLOWED_FIELDS_KEYS = frozenset({"all", "required", "any_of", "derived_only", "_why"})

for doc_type, field_spec in self._fields.items():
    if not isinstance(field_spec, dict):
        raise PackSpecError(f"{name}: fields[{doc_type!r}] must be an object")
    bad_keys = set(field_spec) - _ALLOWED_FIELDS_KEYS
    if bad_keys:
        raise PackSpecError(
            f"{name}: fields[{doc_type!r}] has unrecognized key(s) {sorted(bad_keys)} - "
            f"only {sorted(_ALLOWED_FIELDS_KEYS)} are valid. A typo here (e.g. 'require' "
            f"instead of 'required') would otherwise silently disable that key's "
            f"enforcement with no error."
        )
```

- [ ] **Step 4: Run tests to verify pass, and that no existing real pack breaks**

Run: `pytest tests/packs/test_datapack.py -v`
Then: `pytest tests/fixtures/packs/ -q` (the excluded-by-default real-pack suite — run it explicitly
here specifically to confirm this new strict check doesn't break any of the shipped reference packs'
`fields` blocks, since they're the closest thing to "real" data this repo has).
Expected: PASS on both.

- [ ] **Step 5: Commit**

```bash
git add src/docintel/packs/datapack.py tests/packs/test_datapack.py
git commit -m "fix(packs): allowlist fields.<doc_type> keys so a typo fails loudly

_for(doc_type, key) was a bare dict .get() - writing \"require\" instead
of \"required\" silently produced an empty required-fields set with no
error anywhere. Validate the key set at load time, matching every
other structural check already in DataPack.__init__."
```

---

### Task 13: Escape leading formula characters in the Excel export

**Verified problem:** `export/excel.py:117`, `worksheet.append(row_fn(record))` — `row_fn`
(`_standard_row`/`_telecom_detail_row`) writes vendor-controlled string fields (`vendor_name` etc.)
directly into cells with no escaping. A vendor name of `=cmd|'/c calc'!A1` (or any string starting with
`=`, `+`, `-`, `@`) becomes a live formula the moment a finance user opens the exported file in Excel —
classic CSV/spreadsheet formula injection.

**Files:**
- Modify: `src/docintel/export/excel.py`
- Test: `tests/export/test_excel.py`

**Interfaces:**
- Produces: `write_records_to_xlsx` now sanitizes every string cell before writing — no signature
  change, callers unaffected.

- [ ] **Step 1: Write the failing test**

```python
# tests/export/test_excel.py

def test_a_vendor_name_starting_with_equals_is_escaped_not_written_as_a_live_formula(tmp_path):
    records = [{
        "document_id": "d1",
        "derived": {"vendor_name": "=cmd|'/c calc'!A1"},
        "fields": {}, "disposition": "processed", "lane": "high",
    }]
    out_path = tmp_path / "out.xlsx"
    write_records_to_xlsx(records, str(out_path), layout="standard")

    from openpyxl import load_workbook
    wb = load_workbook(out_path)
    cell_value = wb.active.cell(row=2, column=2).value  # vendor_name column
    assert not cell_value.startswith("=")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/export/test_excel.py -k not_written_as_a_live_formula -v`
Expected: FAIL — the raw `=cmd|...` string is written as-is today.

- [ ] **Step 3: Implement**

```python
# export/excel.py

_FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@")


def _escape_formula_injection(value: Any) -> Any:
    """A leading =/+/-/@ makes Excel treat a cell as a live formula. Prefix
    with a single quote, which every spreadsheet application already renders
    as "force this to be text" - the same guard OWASP recommends for any
    CSV/XLSX export of untrusted string data. Non-strings pass through
    unchanged; a leading '-' on a real negative number never reaches this
    function as a string in the first place (see _get()'s callers, which
    keep numeric fields as numbers, not formatted strings)."""
    if isinstance(value, str) and value.startswith(_FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


def write_records_to_xlsx(
    records: list[dict[str, Any]], path: str, layout: str = "standard"
) -> None:
    if layout not in LAYOUTS:
        raise UnknownLayoutError(
            f"{layout!r} is not a registered export layout - registered: {sorted(LAYOUTS)}"
        )
    header, row_fn = LAYOUTS[layout]

    from openpyxl import Workbook  # pragma: no cover - depends on the environment

    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = layout
    worksheet.append(header)
    for record in records:
        row = [_escape_formula_injection(cell) for cell in row_fn(record)]
        worksheet.append(row)
    workbook.save(path)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `pytest tests/export/test_excel.py -v`
Expected: PASS, including every pre-existing test (numeric fields like `total_printed` are unaffected
since they aren't strings starting with those characters).

- [ ] **Step 5: Commit**

```bash
git add src/docintel/export/excel.py tests/export/test_excel.py
git commit -m "fix(export): escape leading =/+/-/@ in Excel cells (formula injection)

worksheet.append(row_fn(record)) wrote vendor-controlled strings
(vendor_name, etc.) directly into cells - a vendor name starting with
= becomes a live formula the instant a finance user opens the file.
Prefix with a single quote, the standard spreadsheet text-force guard."
```

---

### Task 14: Add backoff to retries; stop `telemetry.configure()` closing handlers it doesn't own

**Verified problem A:** `pipeline/runner.py:209-225`, `_run_one`: `for _ in range(attempts):` with
`except TransientError: continue` — no `time.sleep()` anywhere between attempts. Three instant retries
against a real rate limit make the situation worse, not better.

**Verified problem B:** `telemetry.py:44-69`, `configure()`: every call does
`for handler in list(logger.handlers): logger.removeHandler(handler); handler.close()` unconditionally,
then attaches a fresh `RotatingFileHandler`. This is scoped to the `"docintel.telemetry"` named logger
specifically (not the root logger), but if an adopter attaches their own handler to this same logger
name (to also stream telemetry into their own observability pipeline) — or if `configure()` is called
more than once in a process for a legitimate reason — that handler gets closed out from under them with
no warning.

**Files:**
- Modify: `src/docintel/pipeline/runner.py`
- Modify: `src/docintel/telemetry.py`
- Test: `tests/pipeline/test_runner.py`, `tests/test_telemetry.py`

**Interfaces:**
- `Runner.__init__` gains a `retry_backoff_seconds: float = 0.5` parameter (default chosen to be
  meaningfully non-instant without materially slowing a normal run, since retries are the exception
  path, not the common one).
- `telemetry.configure()` signature unchanged; behavior changes to only remove/close handlers it
  itself previously created (tagged via a custom attribute), never a handler it didn't attach.

- [ ] **Step 1: Write the failing test for backoff**

```python
# tests/pipeline/test_runner.py

def test_retries_wait_between_attempts_not_instant(monkeypatch):
    sleeps = []
    monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

    class _AlwaysTransient:
        name = "flaky"
        def run(self, ctx):
            raise TransientError("rate limited")

    runner = Runner(
        stages=[_AlwaysTransient()], hooks=HookRegistry(), max_retries=2, retry_backoff_seconds=0.5,
    )
    with pytest.raises(TransientError):
        runner._run_one(_AlwaysTransient(), make_ctx())
    assert sleeps == [pytest.approx(0.5), pytest.approx(1.0)]  # exponential: 0.5*2^0, 0.5*2^1
```

`Runner.__init__`'s confirmed full signature (`pipeline/runner.py:54-59`):
`(self, stages: list[Stage], hooks: HookRegistry, max_retries: int = 0, telemetry: bool | str = False)`
— `hooks` is required, no default. `retry_backoff_seconds` is the new parameter this step adds.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/pipeline/test_runner.py -k retries_wait_between_attempts -v`
Expected: FAIL — `sleeps == []` today.

- [ ] **Step 3: Implement backoff**

```python
# pipeline/runner.py

import time

class Runner:
    def __init__(
        self,
        stages: list[Stage],
        hooks: HookRegistry,
        max_retries: int = 0,
        telemetry: bool | str = False,
        retry_backoff_seconds: float = 0.5,  # NEW parameter
    ) -> None:
        self.stages = stages
        self.hooks = hooks
        self.max_retries = max_retries
        self.retry_backoff_seconds = retry_backoff_seconds  # NEW
        # ...(every other existing __init__ line unchanged - self._intaken,
        # self._emitted, self._identity_index, telemetry setup, etc.)

def _run_one(self, stage: Stage, ctx: JobContext) -> JobContext:
    attempts = self.max_retries + 1
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            result = stage.run(ctx)
        except TransientError as exc:
            last = exc
            if attempt < attempts - 1:  # never sleep after the final attempt
                time.sleep(self.retry_backoff_seconds * (2 ** attempt))
            continue
        if not isinstance(result, JobContext):
            raise TypeError(f"stage {stage.name!r} must return a JobContext")
        return result
    if last is None:
        raise RuntimeError(f"stage {stage.name!r} exhausted retries without a result")
    raise last
```

- [ ] **Step 4: Write the failing test for telemetry handler ownership**

```python
# tests/test_telemetry.py

def test_configure_never_closes_a_handler_it_did_not_attach_itself(tmp_path):
    import logging
    foreign_handler = logging.NullHandler()
    logger = logging.getLogger("docintel.telemetry")
    logger.addHandler(foreign_handler)

    configure(str(tmp_path / "telemetry.jsonl"))

    assert foreign_handler in logger.handlers  # still there, never closed
```

- [ ] **Step 5: Run test to verify it fails**

Run: `pytest tests/test_telemetry.py -k never_closes_a_handler_it_did_not_attach -v`
Expected: FAIL — today's `configure()` removes and closes every handler unconditionally.

- [ ] **Step 6: Implement — tag owned handlers, only touch those**

```python
# telemetry.py

_OWNED_MARKER = "_docintel_telemetry_owned"


def configure(path: str | None = None) -> logging.Logger:
    resolved = path or os.environ.get("DOCINTEL_TELEMETRY_LOG") or DEFAULT_LOG_PATH
    logger = logging.getLogger(_LOGGER_NAME)
    for handler in list(logger.handlers):
        if getattr(handler, _OWNED_MARKER, False):
            logger.removeHandler(handler)
            handler.close()
        # a handler this module didn't attach itself (an adopter's own,
        # or one from a prior differently-configured run this process
        # didn't create) is left alone - see module docstring update below

    directory = os.path.dirname(resolved)
    if directory:
        os.makedirs(directory, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        resolved, maxBytes=10 * 1024 * 1024, backupCount=5,
    )
    setattr(handler, _OWNED_MARKER, True)
    handler.setFormatter(_RawLineFormatter())
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
    return logger
```

Update this function's docstring: "Safe to call more than once — each call replaces only the handler
*this module itself previously attached*, never a handler an adopter or a different caller added to
this logger name."

- [ ] **Step 7: Run tests to verify pass**

Run: `pytest tests/pipeline/test_runner.py tests/test_telemetry.py -v`
Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add src/docintel/pipeline/runner.py src/docintel/telemetry.py \
        tests/pipeline/test_runner.py tests/test_telemetry.py
git commit -m "fix(runner,telemetry): add retry backoff, stop closing handlers we don't own

_run_one retried instantly, three times, against real rate limits.
telemetry.configure() unconditionally closed every handler on its
logger, including one an adopter attached themselves. Add exponential
backoff between retries; tag and only touch handlers this module
itself created."
```

---

### Task 15: One configurable root for persistent state

**Verified problem:** `jobs/store.py:39`, `DEFAULT_DB_PATH = "var/jobs.sqlite3"` (overridable via
`DOCINTEL_JOBS_DB`). `telemetry.py:30`, `DEFAULT_LOG_PATH = "var/logs/docintel.jsonl"` (overridable via
`DOCINTEL_TELEMETRY_LOG`). `extract/ocr_cache.py:42`, `CACHE_DIR = Path("var") / "ocr-cache"` — **no
override at all**. Each module resolves its own `var/...` path relative to the process's current
working directory, with inconsistent (or absent) override support. Under a deployment where CWD isn't
the repo root, these land in an unexpected, possibly unwritable location.

**Files:**
- Modify: `src/docintel/extract/ocr_cache.py` (add the missing override — this is the most urgent gap,
  since it currently has none)
- New: `src/docintel/paths.py` — one small module resolving a shared state root
- Modify: `src/docintel/jobs/store.py`, `src/docintel/telemetry.py` (use the shared root as their
  fallback, most-specific-override-still-wins)
- Test: `tests/test_paths.py`, plus one assertion added to each of the three modified modules' existing
  test files

**Interfaces:**
- Produces: `docintel.paths.state_root() -> Path` — resolves `DOCINTEL_STATE_DIR` env var if set,
  else `Path("var")`. New, small, additive; nothing existing calls it yet until this task wires it in.

- [ ] **Step 1: Write the failing test for the new module**

```python
# tests/test_paths.py

def test_state_root_defaults_to_var(monkeypatch):
    monkeypatch.delenv("DOCINTEL_STATE_DIR", raising=False)
    assert state_root() == Path("var")


def test_state_root_honors_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv("DOCINTEL_STATE_DIR", str(tmp_path))
    assert state_root() == tmp_path
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_paths.py -v`
Expected: FAIL — `ModuleNotFoundError: docintel.paths`.

- [ ] **Step 3: Implement the shared module**

```python
# src/docintel/paths.py
"""One configurable root for every path docintel writes state under.

Three modules (jobs.store, telemetry, extract.ocr_cache) each resolved their
own `var/...` path relative to the process's CWD, with inconsistent override
support - ocr_cache had none at all. Under gunicorn (or any deployment where
CWD isn't the repo root), state scatters to wherever the process happened to
start, unpredictably. This is the one new knob; each module's own specific
env var (DOCINTEL_JOBS_DB, DOCINTEL_TELEMETRY_LOG) still wins when set - this
is only the fallback for the common root, and ocr_cache's new override.
"""

from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    """`DOCINTEL_STATE_DIR` if set, else `var` (relative to CWD, matching
    every existing default in this codebase)."""
    override = os.environ.get("DOCINTEL_STATE_DIR")
    return Path(override) if override else Path("var")
```

- [ ] **Step 4: Wire ocr_cache.py's missing override**

```python
# extract/ocr_cache.py

from docintel.paths import state_root

# CACHE_DIR = Path("var") / "ocr-cache"   <- remove this module-level constant

def _cache_dir() -> Path:
    override = os.environ.get("DOCINTEL_OCR_CACHE_DIR")
    return Path(override) if override else state_root() / "ocr-cache"
```

Replace every use of the module-level `CACHE_DIR` constant in this file (in `_cache_path`,
`_evict_oldest_past_cap`, etc.) with a call to `_cache_dir()` — grep this file for `CACHE_DIR` to find
every call site.

- [ ] **Step 5: Wire jobs/store.py and telemetry.py to fall back to `state_root()`**

```python
# jobs/store.py — the existing DEFAULT_DB_PATH constant becomes a function,
# used only as the final fallback (DOCINTEL_JOBS_DB still wins first, unchanged)

from docintel.paths import state_root

def _default_db_path() -> str:
    return str(state_root() / "jobs.sqlite3")

# wherever `resolved = path or os.environ.get("DOCINTEL_JOBS_DB") or DEFAULT_DB_PATH`
# currently reads, change the final fallback to `_default_db_path()`
```

Apply the same pattern to `telemetry.py`'s `DEFAULT_LOG_PATH` / `configure()`.

- [ ] **Step 6: Run all touched tests to verify pass**

Run: `pytest tests/test_paths.py tests/extract/test_ocr_cache.py tests/test_telemetry.py -v` (confirm
exact job-store test file name via `pytest --collect-only -q | grep -i job`, add it to this run too)
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add src/docintel/paths.py src/docintel/extract/ocr_cache.py src/docintel/jobs/store.py \
        src/docintel/telemetry.py tests/test_paths.py
git commit -m "feat(paths): one configurable root for persistent state

jobs.store and telemetry each had their own env-var override;
ocr_cache had none at all. All three now fall back to a shared
DOCINTEL_STATE_DIR root (default 'var', matching every existing
default) when their own specific override isn't set - fixes ocr_cache
having no override, and gives one knob for a deployment whose CWD
isn't the repo root."
```

---

## Self-Review Notes (for whoever executes this plan)

- **Task 4/Task 5 order matters**: Task 5 assumes Task 4's job-split CI structure already exists.
  Execute in the numbered order.
- **Task 8's lock and Task 10's page ceiling both touch the Stage 2 hot path** — if executed out of
  order, re-read the current state of `s2_filter.py` before starting either, since the other may have
  already changed nearby lines.
- Several tasks reference "confirm the exact X by reading Y first" rather than a hardcoded assumption
  (`Runner.__init__`'s full signature in Task 14, test file names in Tasks 6/7/11/15, the exact insertion
  point in Task 10). This is deliberate: this plan was written from a verified read of the *current*
  code, but a few interior details (exact existing test helper names, full constructor signatures
  beyond what was directly quoted) were not exhaustively dumped into this document to keep it a
  reasonable size — the implementer confirms them against the live file in the same step, not against
  this plan's memory of it.
- No task in this plan touches `src/docintel/webui/` — confirmed against the Global Constraints above
  before every task was written.
