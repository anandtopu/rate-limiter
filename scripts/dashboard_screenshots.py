import argparse
import importlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

DEFAULT_BASE_URL = "http://127.0.0.1:8001"
DEFAULT_OUTPUT_DIR = Path("docs/assets")
DEFAULT_ADMIN_KEY = "dev-admin-key"


@dataclass(frozen=True)
class ScreenshotTarget:
    name: str
    width: int
    height: int
    path: Path


def normalize_demo_url(base_url: str) -> str:
    normalized = base_url.rstrip("/")
    if normalized.endswith("/demo"):
        return normalized
    return f"{normalized}/demo"


def screenshot_targets(output_dir: Path) -> list[ScreenshotTarget]:
    return [
        ScreenshotTarget(
            name="desktop",
            width=1440,
            height=1200,
            path=output_dir / "demo-dashboard-desktop.png",
        ),
        ScreenshotTarget(
            name="mobile",
            width=390,
            height=1200,
            path=output_dir / "demo-dashboard-mobile.png",
        ),
    ]


def serialize_targets(targets: list[ScreenshotTarget]) -> list[dict[str, Any]]:
    return [
        {
            **asdict(target),
            "path": str(target.path),
        }
        for target in targets
    ]


def load_sync_playwright() -> Any | None:
    try:
        return importlib.import_module("playwright.sync_api").sync_playwright
    except ImportError:
        return None


def prepare_dashboard(page: Any, demo_url: str, admin_key: str, timeout_ms: int) -> None:
    page.goto(demo_url, wait_until="networkidle", timeout=timeout_ms)
    admin_key_input = page.locator("#adminKeyInput")
    if admin_key_input.count() > 0:
        admin_key_input.fill(admin_key)

    report_button = page.locator("#aiResearchReportBtn")
    if report_button.count() > 0:
        report_button.click()
        page.locator("#aiResearchReportOutput").wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_timeout(500)


def capture_dashboard_screenshots(
    *,
    sync_playwright: Any,
    base_url: str,
    output_dir: Path,
    admin_key: str,
    timeout_ms: int,
) -> dict[str, Any]:
    demo_url = normalize_demo_url(base_url)
    targets = screenshot_targets(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        try:
            for target in targets:
                page = browser.new_page(
                    viewport={
                        "width": target.width,
                        "height": target.height,
                    }
                )
                try:
                    prepare_dashboard(page, demo_url, admin_key, timeout_ms)
                    page.screenshot(path=str(target.path), full_page=True)
                finally:
                    page.close()
        finally:
            browser.close()

    return {
        "status": "captured",
        "url": demo_url,
        "screenshots": serialize_targets(targets),
    }


def skipped_result(base_url: str, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "skipped",
        "reason": "playwright_not_installed",
        "install": (
            "Install the optional Playwright package and Chromium browser before refreshing "
            "dashboard screenshots."
        ),
        "url": normalize_demo_url(base_url),
        "screenshots": serialize_targets(screenshot_targets(output_dir)),
    }


def plan_result(base_url: str, output_dir: Path) -> dict[str, Any]:
    return {
        "status": "planned",
        "url": normalize_demo_url(base_url),
        "screenshots": serialize_targets(screenshot_targets(output_dir)),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Refresh demo dashboard screenshots with the AI Research Report panel loaded."
    )
    parser.add_argument(
        "--base-url",
        default=os.environ.get("BASE_URL", DEFAULT_BASE_URL),
        help="Running app base URL or /demo URL.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory where dashboard screenshots are written.",
    )
    parser.add_argument(
        "--admin-key",
        default=os.environ.get("ADMIN_API_KEY", DEFAULT_ADMIN_KEY),
        help="Admin key used to load the protected AI Research Report panel.",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=10_000,
        help="Browser navigation and selector timeout in milliseconds.",
    )
    parser.add_argument(
        "--plan",
        action="store_true",
        help="Print the screenshot targets without launching a browser.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit non-zero when Playwright is not installed.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.plan:
        print(json.dumps(plan_result(args.base_url, args.output_dir), indent=2))
        return 0

    sync_playwright = load_sync_playwright()
    if sync_playwright is None:
        print(json.dumps(skipped_result(args.base_url, args.output_dir), indent=2))
        return 1 if args.strict else 0

    result = capture_dashboard_screenshots(
        sync_playwright=sync_playwright,
        base_url=args.base_url,
        output_dir=args.output_dir,
        admin_key=args.admin_key,
        timeout_ms=args.timeout_ms,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
