"""`docintel serve` through the real CLI - argument wiring only.

`create_app()` itself is already thoroughly tested end-to-end
(`tests/webui/test_app.py`, `tests/webui/test_review.py`). What had zero
coverage was `_cmd_serve`'s own wiring: does `--port` actually reach
`app.run`, does `--no-browser` actually suppress the browser open, and does
it open the right URL when it doesn't. `app.run(...)` itself is stubbed in
every test here - the real one blocks forever serving requests, which is
exactly what must never happen inside a test.
"""

from __future__ import annotations

import docintel.webui.app as webui_app
from docintel.cli import main


class _StubFlaskApp:
    def __init__(self) -> None:
        self.run_calls: list[dict] = []

    def run(self, **kwargs):
        self.run_calls.append(kwargs)


def test_serve_passes_the_requested_port_to_app_run(monkeypatch):
    stub_app = _StubFlaskApp()
    monkeypatch.setattr(webui_app, "create_app", lambda: stub_app)
    monkeypatch.setattr("webbrowser.open", lambda url: None)

    exit_code = main(["serve", "--port", "5959", "--no-browser"])

    assert exit_code == 0
    assert stub_app.run_calls == [{"host": "127.0.0.1", "port": 5959, "debug": False}]


def test_serve_defaults_to_port_5000(monkeypatch):
    stub_app = _StubFlaskApp()
    monkeypatch.setattr(webui_app, "create_app", lambda: stub_app)
    monkeypatch.setattr("webbrowser.open", lambda url: None)

    main(["serve", "--no-browser"])

    assert stub_app.run_calls[0]["port"] == 5000


def test_serve_no_browser_suppresses_the_browser_open(monkeypatch):
    stub_app = _StubFlaskApp()
    opened: list[str] = []
    monkeypatch.setattr(webui_app, "create_app", lambda: stub_app)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    main(["serve", "--no-browser"])

    assert opened == []


def test_serve_without_no_browser_opens_the_right_url(monkeypatch):
    stub_app = _StubFlaskApp()
    opened: list[str] = []
    monkeypatch.setattr(webui_app, "create_app", lambda: stub_app)
    monkeypatch.setattr("webbrowser.open", lambda url: opened.append(url))

    main(["serve", "--port", "5959"])

    assert opened == ["http://127.0.0.1:5959/"]
