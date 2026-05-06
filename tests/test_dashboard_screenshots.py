import json
from pathlib import Path
from uuid import uuid4

from scripts import dashboard_screenshots


def scratch_path() -> Path:
    return Path(".pytest-tmp") / "dashboard-screenshots" / str(uuid4())


def test_normalize_demo_url_accepts_base_or_demo_url():
    assert dashboard_screenshots.normalize_demo_url("http://127.0.0.1:8001") == (
        "http://127.0.0.1:8001/demo"
    )
    assert dashboard_screenshots.normalize_demo_url("http://127.0.0.1:8001/demo") == (
        "http://127.0.0.1:8001/demo"
    )


def test_screenshot_targets_match_checked_in_assets():
    targets = dashboard_screenshots.screenshot_targets(Path("docs/assets"))

    assert [target.name for target in targets] == ["desktop", "mobile"]
    assert targets[0].path == Path("docs/assets/demo-dashboard-desktop.png")
    assert targets[0].width == 1440
    assert targets[1].path == Path("docs/assets/demo-dashboard-mobile.png")
    assert targets[1].width == 390


def test_dashboard_screenshots_main_prints_plan(capsys):
    output_dir = scratch_path()

    exit_code = dashboard_screenshots.main(
        [
            "--plan",
            "--base-url",
            "http://localhost:8001",
            "--output-dir",
            str(output_dir),
        ]
    )

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "planned"
    assert body["url"] == "http://localhost:8001/demo"
    assert body["screenshots"][0]["path"] == str(output_dir / "demo-dashboard-desktop.png")


def test_dashboard_screenshots_main_skips_without_playwright(monkeypatch, capsys):
    output_dir = scratch_path()
    monkeypatch.setattr(dashboard_screenshots, "load_sync_playwright", lambda: None)

    exit_code = dashboard_screenshots.main(["--output-dir", str(output_dir)])

    assert exit_code == 0
    body = json.loads(capsys.readouterr().out)
    assert body["status"] == "skipped"
    assert body["reason"] == "playwright_not_installed"


def test_dashboard_screenshots_main_strict_fails_without_playwright(
    monkeypatch, capsys
):
    output_dir = scratch_path()
    monkeypatch.setattr(dashboard_screenshots, "load_sync_playwright", lambda: None)

    exit_code = dashboard_screenshots.main(["--strict", "--output-dir", str(output_dir)])

    assert exit_code == 1
    assert json.loads(capsys.readouterr().out)["status"] == "skipped"


def test_capture_dashboard_screenshots_uses_report_panel():
    output_dir = Path("docs/assets")
    calls = []

    class FakeLocator:
        def __init__(self, selector):
            self.selector = selector

        def count(self):
            return 1

        def fill(self, value):
            calls.append(("fill", self.selector, value))

        def click(self):
            calls.append(("click", self.selector))

        def wait_for(self, **kwargs):
            calls.append(("wait_for", self.selector, kwargs))

    class FakePage:
        def goto(self, url, **kwargs):
            calls.append(("goto", url, kwargs))

        def locator(self, selector):
            return FakeLocator(selector)

        def wait_for_timeout(self, timeout_ms):
            calls.append(("wait_for_timeout", timeout_ms))

        def screenshot(self, **kwargs):
            calls.append(("screenshot", kwargs))

        def close(self):
            calls.append(("page_close",))

    class FakeBrowser:
        def new_page(self, **kwargs):
            calls.append(("new_page", kwargs))
            return FakePage()

        def close(self):
            calls.append(("browser_close",))

    class FakeChromium:
        def launch(self):
            calls.append(("launch",))
            return FakeBrowser()

    class FakePlaywright:
        chromium = FakeChromium()

    class FakeSyncPlaywright:
        def __enter__(self):
            return FakePlaywright()

        def __exit__(self, exc_type, exc, traceback):
            return False

    result = dashboard_screenshots.capture_dashboard_screenshots(
        sync_playwright=lambda: FakeSyncPlaywright(),
        base_url="http://127.0.0.1:8001",
        output_dir=output_dir,
        admin_key="dev-admin-key",
        timeout_ms=1234,
    )

    assert result["status"] == "captured"
    assert ("fill", "#adminKeyInput", "dev-admin-key") in calls
    assert ("click", "#aiResearchReportBtn") in calls
    screenshot_calls = [call for call in calls if call[0] == "screenshot"]
    assert len(screenshot_calls) == 2
