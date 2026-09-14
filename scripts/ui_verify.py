"""Drive the real UI in Chrome and capture screenshots + console errors.

Playwright drives the locally installed Chrome (channel="chrome"), so no
browser download is needed. Output goes to scripts/ui-shots/.

Exit code policy
----------------
The exit code is decided by four browser-reported classes plus every semantic
check this script makes:

    pageerror / console error / requestfailed / mid-token port break
    + each `record(...)` semantic assertion below (e.g. "no container rows")

Exit 1 when any of them is non-empty, 0 otherwise.

The printed marker and the exit code are ONE contract, not two. `[FAIL]` is
reserved for checks that actually decide the exit code, so a scanner that greps
for `[FAIL]` and the process status can never disagree. A check that is reported
but not judged - the console warnings below - prints `[warn]` (something is
there) or `[note]` (nothing to see) and never turns the gate red.

That was RD3-04: `record()` printed `[FAIL]` for non-judged checks too, so the
warning-only run showed `[FAIL] 控制台警告...` on the same screen as
`UI verification PASSED` and exit code 0, while the invariant documented further
down claimed that could not happen.

console **warning** is deliberately NOT a failure criterion - it is collected
and printed, nothing more. Rationale (measured on the production bundle, see
test-review/rd2/review-plan-alignment.md §L-14): the shipped bundle contains
three live `console.warn` call sites - Element Plus' `debugWarn` (a bare block,
so it is NOT stripped in production builds), a wrapped Vue `warnHandler`, and
axios' deprecation warnings. Any complaint from those libraries - a deprecated
option, a third-party cookie policy message - would turn the whole gate red
even though nothing about the product is broken. A gate that is permanently red
for reasons nobody can act on stops being a gate. Warnings still get printed
with a count, so a new one is visible in the report and can be judged by a
human.

Dependencies are declared in scripts/requirements-verify.txt:

    pip install -r scripts/requirements-verify.txt
    python scripts/ui_verify.py

On this machine the .browser-tools venv already has them (it is uv-managed and
therefore has no pip of its own):

    .browser-tools\\Scripts\\python.exe scripts\\ui_verify.py
"""
import sys
from pathlib import Path

try:
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - depends on the interpreter
    print("缺少依赖 playwright，无法驱动浏览器做 UI 验证。")
    print(f"  原始错误：{exc}")
    print("请先安装验证依赖：pip install -r scripts/requirements-verify.txt")
    sys.exit(2)

BASE = "http://127.0.0.1:8088"
OUT = Path(__file__).resolve().parent / "ui-shots"
OUT.mkdir(exist_ok=True)

console_errors: list[str] = []
console_warnings: list[str] = []
page_errors: list[str] = []
failed_requests: list[str] = []
# Port chips that wrapped in the middle of a mapping, e.g. "8080->" / ">80/tcp".
port_breaks: list[str] = []
# Semantic checks that failed AND therefore decide the exit code. Only a judged
# failure is ever appended here, and only a judged failure ever prints [FAIL],
# so the console output and the exit code can never disagree.
failures: list[str] = []


def record(name: str, ok: bool, detail: str = "", judged: bool = True) -> None:
    """Print one check and, unless `judged=False`, let it decide the exit code.

    The marker is the contract: `[PASS]`/`[FAIL]` belong to judged checks only.
    A non-judged check reports with `[note]` (clean) or `[warn]` (worth a human
    look) - printing `[FAIL]` for it would put a failure marker in the output of
    a run that exits 0 (RD3-04).
    """
    suffix = f" -- {detail}" if detail else ""
    if not judged:
        print(f"[{'note' if ok else 'warn'}] {name}{suffix}")
        return
    print(f"[{'PASS' if ok else 'FAIL'}] {name}{suffix}")
    if not ok:
        failures.append(f"{name} -- {detail}" if detail else name)


def exit_code() -> int:
    """0 only when nothing was judged a failure.

    Kept as a function so the "printed FAIL => non-zero exit" rule is checkable
    without launching a browser.
    """
    return 0 if not failures else 1


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(viewport={"width": 1440, "height": 900})

        page.on(
            "console",
            lambda m: console_warnings.append(f"{m.type}: {m.text}")
            if m.type == "warning"
            else (
                console_errors.append(f"{m.type}: {m.text}")
                if m.type == "error"
                else None
            ),
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

        def note_port_breaks(chips: list[str], where: str) -> None:
            """A port mapping must not be broken across two lines.

            Only the containers page renders port chips (`.c-port` lives in
            ContainersView.vue); the run dialog has no chip element at all, so
            calling this for the dialog could only ever return an empty list and
            pass unconditionally.
            """
            broken = [c for c in chips if c.endswith("-") or c.startswith(">")]
            print(f"  port chips rendered ({where}): {chips}")
            print(f"  mid-token port breaks ({where}): {broken if broken else 'none'}")
            port_breaks.extend(f"{where}: {b}" for b in broken)

        # ---------------------------------------------------- containers ----
        print("[1] containers page")
        page.goto(f"{BASE}/containers", wait_until="networkidle")
        page.wait_for_timeout(1200)
        shot("01-containers")
        rows = page.locator(".el-table__body tr")
        row_count = rows.count()
        print(f"  container rows: {row_count}")
        record("容器列表渲染出行", row_count > 0, f"{row_count} 行")
        # Each port mapping should occupy exactly one line.
        note_port_breaks(page.locator(".c-port").all_inner_texts(), "containers")

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

        # The dialog's port field is a plain textarea (RunContainerDialog.vue:39)
        # - there is no port-chip element here, so a `.c-port` lookup inside the
        # dialog would always return [] and always pass. Check the element that
        # actually exists instead: the port textarea must be rendered (it is the
        # first textarea in the dialog, the one [4] reads the preset from).
        port_field = page.locator(".el-dialog textarea").first
        record("运行弹窗的端口输入框已渲染", port_field.is_visible(),
               f"visible={port_field.is_visible()}")

        # Check the preset hint is actually visible.
        hint = page.get_by_text("不会填？点一个常用镜像")
        print(f"  preset hint visible: {hint.is_visible()}")
        record("运行弹窗显示预设提示", hint.is_visible())

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
        record("MySQL 预设填满运行表单", filled,
               f"image={image_val!r} ports={ports_val!r}")

        # The 'Select' English placeholder was a visible defect; confirm the
        # restart policy now shows a Chinese hint instead.
        restart_text = page.locator(".el-dialog .el-select").first.inner_text()
        print(f"  restart policy placeholder: {restart_text!r}")
        record("重启策略提示为中文（无英文 Select 占位）",
               "Select" not in restart_text, restart_text.strip()[:40])

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
        record("终端抽屉渲染出内容", bool(term_text.strip()), repr(term_text[:40]))
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
    print(f"console warnings: {len(console_warnings)}")
    for w in console_warnings[:15]:
        print(f"   -  {w}")
    print(f"failed requests : {len(failed_requests)}")
    for r in failed_requests[:15]:
        print(f"   -  {r}")
    print(f"port breaks     : {len(port_breaks)}")
    for b in port_breaks[:15]:
        print(f"   -  {b}")
    print(f"\nscreenshots in: {OUT}")

    # Everything the browser reported is judged, not merely printed: a green
    # screenshot run with console errors is not a pass.
    #
    # The first four records feed `failures` through record(), exactly like the
    # semantic checks above: a [FAIL] line can never coexist with exit code 0.
    record("无页面 JS 异常（pageerror）", not page_errors,
           f"{len(page_errors)} 个")
    record("无控制台错误（console error）", not console_errors,
           f"{len(console_errors)} 条")
    # Reported but NOT judged - see the module docstring for why: the three
    # live console.warn sites in the production bundle are third-party library
    # complaints, not product defects. `judged=False` also switches the marker
    # to [warn]/[note], which is what keeps "[FAIL] <=> exit 1" true.
    record("控制台警告（console warning，仅报告不判定）", not console_warnings,
           f"{len(console_warnings)} 条", judged=False)
    record("无失败请求（requestfailed）", not failed_requests,
           f"{len(failed_requests)} 个")
    record("端口映射未被断行", not port_breaks,
           f"{len(port_breaks)} 处")

    print("=" * 70)
    if failures:
        print(f"UI verification FAILED: {len(failures)} 项判定为失败")
        for f in failures:
            print(f"   !! {f}")
    else:
        print("UI verification PASSED: 所有判定项均通过")
    return exit_code()


if __name__ == "__main__":
    sys.exit(main())
