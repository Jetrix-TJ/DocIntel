# Web UI Trust Signals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Surface per-field confidence, confidence-modifier warnings (especially `bill_to_mismatch`), a possible-duplicate banner, and a client-side JSON export on the web UI's result screen — all data the pipeline already computes but the screen currently discards.

**Architecture:** All changes are confined to `src/docintel/webui/app.py::_view()` (the pure function that classifies a pipeline record into a template context) and `src/docintel/webui/templates/result.html` / `static/style.css`. No new routes, no new pipeline logic, no new persistence — `_view()` stays a pure function of `(record, filename, runner)` so it's unit-testable without running Flask or the real pipeline.

**Tech Stack:** Flask, Jinja2, Python stdlib (`json`, `urllib.parse`). No new dependencies.

## Global Constraints

- No color-coding confidence by value — only the number is shown, per
  `docs/superpowers/specs/2026-08-04-webui-trust-signals-design.md` ("Scope decisions"): the two
  observed confidence values (0.90, 0.99) are not reliably ordered by correctness, so a
  color/badge would manufacture false trust.
- No new server-side persistence. JSON export must be client-side only (embedded in the page,
  downloaded via a `data:` URI), not a new route or saved file.
- `_view()` remains a pure function — no Flask request/response objects inside it — so every new
  branch is unit-testable by calling `_view()` directly with a hand-built record dict.

---

## Task 1: Per-field confidence column

**Files:**
- Modify: `src/docintel/webui/app.py:130-134` (the `rows` computation inside `_view`)
- Modify: `src/docintel/webui/templates/result.html:25-32` (the field table)
- Test: `tests/webui/test_app.py`

**Interfaces:**
- Produces: `_view()`'s `"rows"` entry changes shape from `(label, value)` to `(label, value,
  confidence)` tuples, where `confidence` is a `float | None`. Task 2 and Task 3 don't touch
  `rows` and don't depend on this change.

- [ ] **Step 1: Write the failing test**

Add to `tests/webui/test_app.py` (after `test_a_clean_document_shows_company_doc_type_and_persona_used`):

```python
def test_a_clean_document_shows_per_field_confidence():
    app = create_app(runner_factory=_real_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    body = resp.data.decode()
    assert "Confidence" in body  # column header
    assert "0.99" in body  # DTSS's total_printed/balance_due land at 0.99
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/webui/test_app.py::test_a_clean_document_shows_per_field_confidence -v`
Expected: FAIL — no "Confidence" header exists yet in `result.html`.

- [ ] **Step 3: Update `_view()`'s `rows` computation**

In `src/docintel/webui/app.py`, inside `_view()`, replace:

```python
    rows = sorted(
        (_label(name), value)
        for name, value in values.items()
        if value is not None and not name.endswith(_PLUMBING_SUFFIXES)
    )
```

with:

```python
    confidence = record.get("confidence") or {}
    rows = sorted(
        (_label(name), value, confidence.get(name))
        for name, value in values.items()
        if value is not None and not name.endswith(_PLUMBING_SUFFIXES)
    )
```

- [ ] **Step 4: Update the field table template**

In `src/docintel/webui/templates/result.html`, replace the table block (lines 25-32):

```html
    <table>
      <thead><tr><th>Field</th><th>Value</th></tr></thead>
      <tbody>
        {% for name, value in rows %}
          <tr><td>{{ name }}</td><td>{{ value }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
```

with:

```html
    <table>
      <thead><tr><th>Field</th><th>Value</th><th>Confidence</th></tr></thead>
      <tbody>
        {% for name, value, confidence in rows %}
          <tr><td>{{ name }}</td><td>{{ value }}</td><td>{{ confidence if confidence is not none else '—' }}</td></tr>
        {% endfor %}
      </tbody>
    </table>
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/webui/test_app.py::test_a_clean_document_shows_per_field_confidence -v`
Expected: PASS

- [ ] **Step 6: Run the full webui test suite to check nothing else broke**

Run: `pytest tests/webui/ -v`
Expected: all pass (existing tests only assert substrings are present, not table shape, so the
extra column shouldn't break them — but confirm).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/webui/app.py src/docintel/webui/templates/result.html tests/webui/test_app.py
git commit -m "feat(webui): show per-field confidence in the result table"
```

---

## Task 2: Confidence-modifier warnings and duplicate banner

**Files:**
- Modify: `src/docintel/webui/app.py` (add `_MODIFIER_COPY`, extend `base` dict in `_view()`)
- Modify: `src/docintel/webui/templates/result.html` (render modifiers + duplicate banner)
- Modify: `src/docintel/webui/static/style.css` (add `.modifiers`/`.modifier-severe`/`.modifier-note`)
- Test: `tests/webui/test_app.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `_view()`'s return dict gains `"modifiers"` — a `list[tuple[str, str]]` of `(raw_tag,
  human_message)` — and `"duplicate_of"` — `str | None`. Task 3 doesn't depend on these.

**Note before Step 3:** the wording for `bill_to_mismatch`'s warning message is a UX/domain
judgment call (how severe to make it sound, what a reviewer needs to know) with no single correct
answer — flagging this so whoever implements it can write it deliberately rather than treat it as
boilerplate.

- [ ] **Step 1: Write the failing tests**

Add to `tests/webui/test_app.py`:

```python
class _DummyRunner:
    stages: list = []


def _base_record(**overrides):
    record = {
        "disposition": "processed",
        "extraction_coverage": {"declared": 1},
        "regen_flag": False,
        "lane": "high",
        "review_flag": False,
        "fields": {"vendor_name": "Acme"},
        "derived": {},
        "confidence": {"vendor_name": 0.99},
        "confidence_modifiers": [],
        "possible_duplicate_of": None,
        "sender_fingerprint": "acme|acme",
        "doc_type": "invoice",
        "extraction_rule_version": 1,
    }
    record.update(overrides)
    return record


def test_view_maps_bill_to_mismatch_to_its_specific_warning():
    from docintel.webui.app import _view

    view = _view(_base_record(confidence_modifiers=["bill_to_mismatch"]), "test.pdf", _DummyRunner())
    tags = dict(view["modifiers"])
    assert "bill_to_mismatch" in tags
    assert "roster" in tags["bill_to_mismatch"].lower()  # names what disagreed, not just the tag


def test_view_falls_back_to_a_humanized_label_for_unknown_modifiers():
    from docintel.webui.app import _view

    view = _view(_base_record(confidence_modifiers=["some_future_tag"]), "test.pdf", _DummyRunner())
    assert view["modifiers"] == [("some_future_tag", "Some Future Tag")]


def test_view_passes_through_possible_duplicate_of():
    from docintel.webui.app import _view

    view = _view(_base_record(possible_duplicate_of="webui-abc123"), "test.pdf", _DummyRunner())
    assert view["duplicate_of"] == "webui-abc123"


```

No corpus document trips `bill_to_mismatch` end-to-end (confirmed in the design doc: no gold
file references it), so template rendering of the warning is covered by the three `_view()` unit
tests above plus one template-rendering check using Flask's `render_template` directly:

```python
def test_result_template_renders_the_severe_modifier_class():
    from docintel.webui.app import create_app

    app = create_app(runner_factory=_real_runner_factory())
    with app.app_context(), app.test_request_context():
        from flask import render_template

        html = render_template(
            "result.html",
            filename="test.pdf",
            classification={"company": "Acme", "doc_type": "invoice", "persona": "acme|acme"},
            coverage_rows=None,
            modifiers=[("bill_to_mismatch", "The printed bill-to party does not match this vendor's known client roster.")],
            duplicate_of=None,
            record_json_url="data:application/json,{}",
            state="extracted",
            status="Needs review",
            lane="low",
            rows=[],
            coverage_summary=None,
        )
    assert "modifier-severe" in html
    assert "roster" in html
```

That's four new tests for this task: three `_view()` unit tests plus this one template-rendering
check.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/webui/test_app.py -k "modifier or duplicate" -v`
Expected: FAIL — `_view()` doesn't return `"modifiers"`/`"duplicate_of"` yet, and
`result.html` has no `modifier-severe` class.

- [ ] **Step 3: Add `_MODIFIER_COPY` and extend `_view()`'s `base` dict**

In `src/docintel/webui/app.py`, near the top-level constants (after `_PLUMBING_SUFFIXES`):

```python
# Human-readable copy for confidence_modifiers tags (s7_gate.py / infer.py). Any
# tag not listed here falls back to a humanized version of the raw tag name, so
# a newly-added modifier doesn't require a template change to be visible.
_MODIFIER_COPY = {
    "bill_to_mismatch": (
        "The printed bill-to party does not match this vendor's known client "
        "roster — confirm this document is actually billed to us before approving payment."
    ),
}
```

In `_view()`, extend the `base` dict (currently `base = {"filename": filename, "classification":
classification, "coverage_rows": None}`) to:

```python
    base = {
        "filename": filename,
        "classification": classification,
        "coverage_rows": None,
        "modifiers": [
            (tag, _MODIFIER_COPY.get(tag, _label(tag)))
            for tag in record.get("confidence_modifiers") or []
        ],
        "duplicate_of": record.get("possible_duplicate_of"),
    }
```

- [ ] **Step 4: Render modifiers and duplicate banner in the template**

In `src/docintel/webui/templates/result.html`, insert after the `</dl>` closing the
`classification` block (after line 9) and before the `{% if state == "no_persona" %}` line:

```html
  {% if modifiers %}
    <ul class="modifiers">
      {% for tag, message in modifiers %}
        <li class="{{ 'modifier-severe' if tag == 'bill_to_mismatch' else 'modifier-note' }}">{{ message }}</li>
      {% endfor %}
    </ul>
  {% endif %}

  {% if duplicate_of %}
    <p class="stop">Possible duplicate of {{ duplicate_of }}.</p>
  {% endif %}
```

- [ ] **Step 5: Add CSS**

In `src/docintel/webui/static/style.css`, append:

```css
.modifiers { list-style: none; padding: 0; margin: 0.8rem 0; }
.modifiers li { padding: 0.5rem 0.8rem; border-radius: 4px; margin-bottom: 0.4rem; }
.modifier-severe { background: #fde2e1; border: 1px solid #f5a9a6; color: #a12822; font-weight: 600; }
.modifier-note { background: #f1f1f1; border: 1px solid #ddd; color: #555; }
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/webui/test_app.py -v`
Expected: all pass, including the four new tests and the existing four-screen tests (their
assertions are substring checks on values already present, unaffected by the new `base` keys).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/webui/app.py src/docintel/webui/templates/result.html src/docintel/webui/static/style.css tests/webui/test_app.py
git commit -m "feat(webui): warn on confidence_modifiers and possible duplicates"
```

---

## Task 3: Client-side JSON export

**Files:**
- Modify: `src/docintel/webui/app.py` (add `record_json_url` to `base`, `import json` and `import urllib.parse`)
- Modify: `src/docintel/webui/templates/result.html` (add the download link)
- Test: `tests/webui/test_app.py`

**Interfaces:**
- Consumes: nothing from Task 1 or Task 2.
- Produces: `_view()`'s return dict gains `"record_json_url"` — a `str`, a full `data:` URI.

- [ ] **Step 1: Write the failing tests**

Add to `tests/webui/test_app.py`:

```python
def test_view_record_json_url_round_trips_the_full_record():
    import urllib.parse

    from docintel.webui.app import _view

    record = _base_record()
    view = _view(record, "test.pdf", _DummyRunner())
    prefix = "data:application/json;charset=utf-8,"
    assert view["record_json_url"].startswith(prefix)
    decoded = urllib.parse.unquote(view["record_json_url"][len(prefix):])
    assert json.loads(decoded) == record


def test_a_clean_document_offers_a_json_download_link():
    app = create_app(runner_factory=_real_runner_factory())
    resp = _upload(app.test_client(), DTSS_PDF)
    body = resp.data.decode()
    assert "Download raw JSON" in body
    assert "data:application/json;charset=utf-8," in body
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/webui/test_app.py -k "json_url or download" -v`
Expected: FAIL — `_view()` has no `"record_json_url"` key yet.

- [ ] **Step 3: Add the import and extend `_view()`'s `base` dict**

In `src/docintel/webui/app.py`, add near the other imports at the top:

```python
import json
import urllib.parse
```

Extend `base` (from Task 2) with one more key:

```python
        "record_json_url": (
            "data:application/json;charset=utf-8,"
            + urllib.parse.quote(json.dumps(record, indent=2))
        ),
```

- [ ] **Step 4: Add the download link to the template**

In `src/docintel/webui/templates/result.html`, replace the final line before `{% endblock %}`
(currently `<p><a href="{{ url_for('upload_form') }}">Process another document</a></p>`) with:

```html
  <p>
    <a download="{{ filename }}.json" href="{{ record_json_url }}">Download raw JSON</a>
    &middot;
    <a href="{{ url_for('upload_form') }}">Process another document</a>
  </p>
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/webui/test_app.py -v`
Expected: all pass.

- [ ] **Step 6: Manually verify the download in a browser**

Run: `docintel serve`, upload a sample PDF (e.g. the DTSS control document), click "Download raw
JSON", confirm the browser saves a `.json` file whose contents are the full record (open it and
check `fields`, `confidence`, `confidence_modifiers` are all present).

- [ ] **Step 7: Commit**

```bash
git add src/docintel/webui/app.py src/docintel/webui/templates/result.html tests/webui/test_app.py
git commit -m "feat(webui): add client-side JSON export, no new persistence"
```

---

## Final check

- [ ] Run the full test suite once more: `pytest tests/ -v` — confirm nothing outside
  `tests/webui/` regressed (the `_PLUMBING_SUFFIXES`/`_label` helpers are unchanged, only
  additive changes were made to `_view()`'s return shape).
- [ ] Run `docintel serve` and manually walk all four result states once (extracted, no-persona,
  collapsed, failed) to confirm the modifiers/duplicate/export additions render correctly and
  don't break the three states that were already working.
