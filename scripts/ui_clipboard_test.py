"""Regression test for terminal copy/paste.

The app wires clipboard handling itself (attachCustomKeyEventHandler + the
async Clipboard API) rather than relying on the browser's native copy/paste
events, so this is fully verifiable in automation.

Runs HEADED: headless Chrome does not bridge the system clipboard.

    .browser-tools\\Scripts\\python.exe scripts\\ui_clipboard_test.py
"""
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "http://127.0.0.1:8088"
OUT = Path(__file__).resolve().parent / "ui-shots"
OUT.mkdir(exist_ok=True)

MARKER = "COPYPASTE_4271"


def main() -> int:
    results: list[tuple[str, bool, str]] = []

    def rec(name, ok, detail=""):
        results.append((name, ok, detail))
        print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=False)
        ctx = browser.new_context(
            viewport={"width": 1440, "height": 900},
            permissions=["clipboard-read", "clipboard-write"],
        )
        page = ctx.new_page()

        def clip() -> str:
            return page.evaluate("() => navigator.clipboard.readText()")

        def setclip(t: str) -> None:
            page.evaluate("x => navigator.clipboard.writeText(x)", t)

        # ---------------------------------------------------- open terminal --
        page.goto(f"{BASE}/containers", wait_until="networkidle")
        page.wait_for_timeout(1200)
        row = page.locator(".el-table__body tr").filter(has_text="running").first
        row.locator(".el-dropdown button").first.click()
        page.wait_for_timeout(600)
        page.locator(".el-dropdown-menu__item:visible", has_text="进入终端").first.click()
        page.wait_for_timeout(3500)

        xterm = page.locator(".xterm").first
        box = xterm.bounding_box()
        if not box:
            rec("terminal opened", False, "no xterm element")
            browser.close()
            return 1

        # Several lines, so there is plenty to select across.
        page.mouse.click(box["x"] + 40, box["y"] + 12)
        page.wait_for_timeout(300)
        page.keyboard.type(f"for i in 1 2 3 4 5; do echo {MARKER}_$i; done")
        page.keyboard.press("Enter")
        page.wait_for_timeout(1500)
        print(f"screen: {xterm.inner_text()[:130]!r}")

        def select_lines():
            """Drag across the first few output lines."""
            page.mouse.move(box["x"] + 8, box["y"] + 10)
            page.mouse.down()
            page.mouse.move(box["x"] + 420, box["y"] + 45, steps=18)
            page.mouse.up()
            page.wait_for_timeout(400)

        # ------------------------------------------------------------ copy ---
        setclip("SENTINEL_BEFORE_COPY")
        select_lines()
        n_sel = page.locator(".xterm-selection div").count()
        rec("鼠标拖拽可选中文本", n_sel > 0, f"{n_sel} 个选区元素")

        screen_before = xterm.inner_text()
        sigint_before = screen_before.count("^C")

        page.keyboard.press("Control+c")
        page.wait_for_timeout(900)
        got = clip()
        rec("Ctrl+C 复制选中文本", MARKER in got, f"剪贴板={got[:40]!r}")

        screen_after = xterm.inner_text()
        sigint_after = screen_after.count("^C")
        rec(
            "复制时不再把 SIGINT(^C) 发给 shell",
            sigint_after == sigint_before,
            f"^C 次数 {sigint_before} -> {sigint_after}",
        )
        page.screenshot(path=str(OUT / "11-clipboard-copied.png"))

        # ------------------------------- Ctrl+C with no selection = SIGINT ---
        page.mouse.click(box["x"] + 40, box["y"] + 12)  # clears the selection
        page.wait_for_timeout(400)
        page.keyboard.press("Control+c")
        page.wait_for_timeout(800)
        sigint_final = xterm.inner_text().count("^C")
        rec(
            "无选区时 Ctrl+C 仍是中断信号",
            sigint_final > sigint_after,
            f"^C 次数 {sigint_after} -> {sigint_final}",
        )

        # ----------------------------------------------------------- paste ---
        setclip(f"echo PASTED_{MARKER}")
        page.mouse.click(box["x"] + 40, box["y"] + 12)
        page.wait_for_timeout(300)
        page.keyboard.press("Control+v")
        page.wait_for_timeout(1500)
        rec("Ctrl+V 粘贴", f"PASTED_{MARKER}" in xterm.inner_text(),
            f"尾部={xterm.inner_text()[-60:]!r}")
        page.screenshot(path=str(OUT / "12-clipboard-pasted.png"))

        # ----------------------------------------------------- right-click ---
        setclip(f"echo RC_{MARKER}")
        page.mouse.click(box["x"] + 40, box["y"] + 12)
        page.wait_for_timeout(300)
        page.mouse.click(box["x"] + 200, box["y"] + 12, button="right")
        page.wait_for_timeout(1500)
        rec("右键粘贴", f"RC_{MARKER}" in xterm.inner_text(),
            f"尾部={xterm.inner_text()[-60:]!r}")
        page.screenshot(path=str(OUT / "13-clipboard-rightclick.png"))

        browser.close()

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"RESULT: {passed}/{len(results)} passed")
    for n, ok, d in results:
        if not ok:
            print(f"  FAILED: {n} -- {d}")
    print("=" * 70)
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(main())
