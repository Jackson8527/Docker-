"""Drive the real UI in Chrome and capture screenshots + console errors.

Playwright drives the locally installed Chrome (channel="chrome"), so no
browser download is needed. Output goes to scripts/ui-shots/.

Run with the tool venv:
    .browser-tools\\Scripts\\python.exe scripts\\ui_verify.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8088"
OUT = Path(__file__).resolve().parent / "ui-shots"
OUT.mkdir(exist_ok=True)

console_errors: list[str] = []
page_errors: list[str] = []
failed_requests: list[str] = []


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.on(
            "console",
            lambda m: console_errors.append(f"{m.type}: {m.text}")
            if m.type in ("error", "warning")
            else None,
        )
        page.on("pageerror", lambda e: page_errors.append(str(e)))
        page.on(
            "requestfailed",
            lambda r: failed_requests.append(f"{r.method} {r.url} - {r.failure}"),
        )

        def shot(name: str, full: bool = False) -> None:
            path = OUT / f"{name}.png"
            page.screenshot(path=str(path), full_page=full)
            print(f"  saved {path.name}")

        # ---------------------------------------------------- containers ----
        print("[1] containers page")
        page.goto(f"{BASE}/containers", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot("01-containers")
        rows = page.locator(".el-table__body tr")
        print(f"  container rows: {rows.count()}")
        # Each port mapping should occupy exactly one line.
        ports_seen = page.locator(".c-port").all_inner_texts()
        print(f"  port chips rendered: {ports_seen}")
        broken = [p for p in ports_seen if p.endswith("-") or p.startswith(">")]
        print(f"  mid-token port breaks: {broken if broken else 'none'}")

        # -------------------------------------------------------- images ----
        print("[2] images page")
        page.goto(f"{BASE}/images", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot("02-images")

        # --------------------------------------------- run dialog: empty ----
        print("[3] run dialog (opened from an image row)")
        page.get_by_role("button", name="运行").first.click()
        page.wait_for_timeout(900)
        shot("03-run-dialog-empty")

        # A dialog with no dimming behind it is hard to read.
        overlay = page.eval_on_selector(
            ".el-overlay", "el => getComputedStyle(el).backgroundColor"
        )
        print(f"  modal overlay background: {overlay}")
        # Ports must not break in the middle of a mapping.
        port_lines = page.locator(".c-port").all_inner_texts()

        # Check the preset hint is actually visible.
        hint = page.get_by_text("不会填？点一个常用镜像")
        print(f"  preset hint visible: {hint.is_visible()}")

        # ------------------------------------------- run dialog: preset ----
        print("[4] click the MySQL preset")
        page.get_by_role("button", name="MySQL", exact=True).click()
        page.wait_for_timeout(600)
        shot("04-run-dialog-mysql-preset")

        image_val = page.locator(".el-dialog input").first.input_value()
        ports_val = page.locator(".el-dialog textarea").first.input_value()
        env_val = page.locator(".el-dialog textarea").nth(1).input_value()
        print(f"  image={image_val!r}")
        print(f"  ports={ports_val!r}")
        print(f"  env={env_val!r}")

        filled = bool(image_val) and bool(ports_val) and "MYSQL_ROOT_PASSWORD" in env_val
        print(f"  preset filled the form: {filled}")

        # The 'Select' English placeholder was a visible defect; confirm the
        # restart policy now shows a Chinese hint instead.
        restart_text = page.locator(".el-dialog .el-select").first.inner_text()
        print(f"  restart policy placeholder: {restart_text!r}")

        # ------------------------------------------------- other pages ----
        page.keyboard.press("Escape")
        page.wait_for_timeout(400)

        print("[5] networks / volumes pages")
        page.goto(f"{BASE}/networks", wait_until="networkidle")
        page.wait_for_timeout(900)
        shot("05-networks")

        page.goto(f"{BASE}/volumes", wait_until="networkidle")
        page.wait_for_timeout(900)
        shot("06-volumes")

        # ---------------------------------------------- terminal drawer ----
        print("[6] terminal drawer")
        page.goto(f"{BASE}/containers", wait_until="networkidle")
        page.wait_for_timeout(1000)
        # Pick a running container; a stopped one cannot be exec'd into.
        running_row = page.locator(".el-table__body tr").filter(has_text="running").first
        print(f"  running rows: {page.locator('.el-table__body tr').filter(has_text='running').count()}")
        running_row.locator(".el-dropdown button").first.click()
        page.wait_for_timeout(600)
        # Element Plus keeps a dropdown menu per row in the DOM, so scope the
        # click to the one that is actually open.
        page.locator(".el-dropdown-menu__item:visible", has_text="进入终端").first.click()
        page.wait_for_timeout(3000)
        shot("07-terminal")

        term_text = page.locator(".xterm").first.inner_text()
        print(f"  terminal rendered text: {term_text[:80]!r}")
        page.get_by_role("button", name="重连").first.click()
        page.wait_for_timeout(2000)
        shot("08-terminal-after-reconnect")

        browser.close()

    # ------------------------------------------------------------ report --
    print("\n" + "=" * 70)
    print("UI verification report")
    print("=" * 70)
    print(f"page errors     : {len(page_errors)}")
    for e in page_errors:
        print(f"   !! {e}")
    print(f"console errors  : {len(console_errors)}")
    for e in console_errors[:15]:
        print(f"   -  {e}")
    print(f"failed requests : {len(failed_requests)}")
    for r in failed_requests[:15]:
        print(f"   -  {r}")
    print(f"\nscreenshots in: {OUT}")
    return 1 if page_errors else 0


if __name__ == "__main__":
    sys.exit(main())
