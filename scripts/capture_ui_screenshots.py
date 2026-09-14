"""Capture the Docker Manager Web panel as manual screenshots (READ-ONLY).

What this script is for
-----------------------
It drives the *running* panel (nginx + backend + real Docker daemon on
http://127.0.0.1:8088) with Playwright against the locally installed Chrome
(`channel="chrome"`, so nothing is downloaded) and writes one PNG per screen
into `docs/images/`, named `NN-<english-slug>.png`, for the user manual to
reference.

Read-only contract (do not weaken it)
-------------------------------------
* NO container / image / network / volume is created, started, stopped,
  restarted, deleted, pulled, committed or exported.
* The run-container wizard is filled from a preset and screenshotted, but its
  submit button is NEVER clicked (`shot_run_dialog`).
* The delete confirmation is never opened; anything opened by accident is
  dismissed with Escape.
* The one deliberate failure (10-error-toast) is a GET to the file-copy
  download endpoint with a path that does not exist, i.e. a read that the
  backend answers with 500. It changes nothing inside Docker.
* The only process-level action is `docker exec /bin/sh` for the terminal
  screenshot (05), which the task explicitly asks for; the session is closed
  again (「断开」) and the drawer unmounted before the script moves on.

How the shots stay honest
-------------------------
Waiting is always "wait for the real element to show up" (bounded polling),
never a bare sleep; every screenshot is preceded and followed by an assertion
that the page actually has content (table rows > 0, target element visible with
non-empty text, log lines rendered, xterm prompt printed), so a skeleton screen
or an empty table can never end up in the manual. A shot that still fails its
assertion after `ATTEMPTS` attempts is reported as FAILED, not silently kept.

Exit code
---------
0 = every attempted screenshot was captured and satisfied its assertions
    (SKIPPED entries - see below - do not turn the run red, they are reported),
1 = at least one attempted screenshot failed, or the Docker resource counts
    changed between the start and the end of the run,
2 = the environment itself is unusable (panel unreachable / playwright missing).

Browser diagnostics (pageerror, console error, requestfailed, downloads) are
collected and printed in full, but they never decide whether a screenshot
counted as successful - they are reported for a human to judge.

Known skip
----------
`02-container-detail.png` is intentionally not produced: this product has no
container-detail drawer/dialog. The backend exposes `GET /containers/{cid}`
(backend/app/routers/containers.py:154) but no view or component consumes it -
`grep -r 详情 frontend/src frontend/dist` returns nothing, and the only
per-container surfaces are the 查看日志 / 进入终端 / 文件拷贝 drawers and the
打包为镜像 dialog in ContainersView.vue.

Idempotent: re-running overwrites the same file names. Nothing outside
`docs/images/` is written.

Usage
-----
    D:\\桌面\\测试\\docker-manager\\backend\\.venv\\Scripts\\python.exe ^
        scripts\\capture_ui_screenshots.py
"""
from __future__ import annotations

import re
import subprocess
import sys
import time
from pathlib import Path

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright
except ImportError as exc:  # pragma: no cover - depends on the interpreter
    print(f"缺少依赖 playwright，无法驱动浏览器截图：{exc}")
    print("请使用 backend\\.venv\\Scripts\\python.exe 运行本脚本（其中已装 playwright）。")
    sys.exit(2)

BASE = "http://127.0.0.1:8088"
ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "images"

# The report is Chinese; a redirected pipe would otherwise encode it with the
# console code page and turn the log into mojibake for whoever reads it.
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:  # pragma: no cover - older/odd interpreters
    pass

VIEWPORT = {"width": 1440, "height": 900}
ATTEMPTS = 2

# Containers used for the drawer screenshots. Both are already running and are
# never touched beyond "look at the logs" / "open a shell" / "read a path".
# The log figure is taken from mysql-db rather than from the panel's own nginx
# container: `dockermgr-frontend`'s stdout would show the capture browser's own
# HeadlessChrome request lines (and whoever else is driving the panel), which is
# confusing inside a manual. mysql-db prints a clean, realistic startup log.
CONTAINER_LOGS = "mysql-db"             # real startup log on stdout
CONTAINER_EXEC = "mysql-db"             # /bin/sh exists -> a real shell prompt
BAD_COPY_PATH = "/dsh-no-such-path"     # never exists -> backend answers 500

# ----------------------------------------------------------------- reporting --

# name -> (status, detail). status is 'ok' | 'failed' | 'skipped'.
SHOTS: list[tuple[str, str, str]] = []
SIZES: dict[str, int] = {}
DIAG = {
    "pageerror": [],
    "console_error": [],
    "console_warning": [],
    "requestfailed": [],
    "download": [],
}


class ShotFailed(Exception):
    """A screenshot could not be taken, or its content assertion did not hold."""


def log(msg: str = "") -> None:
    print(msg, flush=True)


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ShotFailed(message)


def poll(page, fn, timeout_ms: int = 25000, interval_ms: int = 250):
    """Call `fn()` until it returns something truthy; `None` on timeout.

    This is the script's only waiting primitive: it waits for a *real* element
    or value to appear (the task's waiting policy), with a bounded deadline so a
    genuinely broken page fails instead of hanging forever.
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while True:
        try:
            value = fn()
        except PlaywrightError:
            value = None
        if value:
            return value
        if time.monotonic() >= deadline:
            return None
        page.wait_for_timeout(interval_ms)


# ------------------------------------------------------------------- helpers --

def goto(page, path: str) -> None:
    """Navigate and wait for the app shell, not for `networkidle`.

    `networkidle` is deliberately avoided: while a log/terminal drawer holds a
    websocket open the network never goes idle and the navigation would time
    out. Waiting for the real shell element (App.vue:43) is both faster and
    more honest.
    """
    page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=30000)
    page.wait_for_selector(".dm-content", state="visible", timeout=20000)


def wait_rows(page, minimum: int = 1, timeout_ms: int = 25000) -> int:
    """Wait until the page table has at least `minimum` body rows."""
    count = poll(page, lambda: page.locator(".el-table__body tr").count(), timeout_ms)
    return count or 0


def wait_loading_gone(page, timeout_ms: int = 15000) -> None:
    """Wait until Element Plus' `v-loading` mask is gone.

    Rows can already be in the DOM while the mask still covers the table, and a
    screenshot taken in that window shows a spinner over the content - exactly
    the "blank/skeleton" the manual must not contain. Asserting on the mask
    turns that into a retryable failure instead of a lucky guess.
    """
    gone = poll(
        page,
        lambda: page.locator(".el-loading-mask:visible").count() == 0 and True or None,
        timeout_ms,
    )
    require(bool(gone), "表格仍处于加载遮罩（.el-loading-mask）状态，拒绝拍摄骨架屏")


def wait_settled(page, selector: str, timeout_ms: int = 6000) -> None:
    """Wait until an animated panel has come to rest.

    Dialog and drawer entrance animations (fade / slide) run for ~300ms after
    the element is already "visible"; shooting during one produces a half-faded
    or half-slid panel whose PNG size even varies run to run. Stability is
    decided by the element's own box not moving between two polls, plus the
    overlay being fully opaque - both real DOM facts, not a sleep.
    """
    last: tuple | None = None

    def box_key():
        box = page.locator(selector).first.bounding_box()
        if box is None:
            return None
        return (round(box["x"]), round(box["y"]), round(box["width"]), round(box["height"]))

    def stable():
        nonlocal last
        key = box_key()
        if key is None:
            return None
        same = key == last
        last = key
        return True if same else None

    def overlay_opaque():
        if not page.locator(".el-overlay").count():
            return True
        return page.eval_on_selector(
            ".el-overlay", "el => getComputedStyle(el).opacity"
        ) == "1" or None

    poll(page, stable, timeout_ms)
    poll(page, overlay_opaque, timeout_ms)


def headers(page) -> list[str]:
    return [
        t.strip()
        for t in page.locator(".el-table__header th").all_inner_texts()
        if t.strip()
    ]


def container_row(page, name: str):
    row = page.locator(".el-table__body tr").filter(has_text=name).first
    row.wait_for(state="visible", timeout=20000)
    return row


def open_row_menu(page, name: str) -> None:
    """Click the ⋯ button of one container row (ContainersView.vue:116)."""
    # Element Plus keeps a dropdown menu per row in the DOM, so every menu
    # lookup below is scoped with `:visible` (same trick as ui_verify.py:234).
    container_row(page, name).locator(".el-dropdown button").first.click()
    page.locator(".el-dropdown-menu__item:visible").first.wait_for(
        state="visible", timeout=10000
    )


def click_menu_item(page, text: str) -> None:
    item = page.locator(".el-dropdown-menu__item:visible", has_text=text).first
    item.wait_for(state="visible", timeout=10000)
    if "is-disabled" in (item.get_attribute("class") or ""):
        raise ShotFailed(f"菜单项「{text}」当前为禁用状态，无法打开")
    item.click()


def wait_drawer(page, title_part: str, timeout_ms: int = 15000) -> str:
    """Wait for a drawer whose header carries `title_part`; return its header text."""
    def header_text():
        el = page.locator(".el-drawer__header:visible")
        if not el.count():
            return None
        text = el.first.inner_text().strip()
        return text if title_part in text else None

    text = poll(page, header_text, timeout_ms)
    require(bool(text), f"抽屉「{title_part}」未在规定时间内出现")
    return text or ""


def reset_ui(page) -> None:
    """Best-effort cleanup between attempts.

    Only Escape and the drawer's own × button are used. No confirmation dialog
    is ever confirmed here - clicking a stray 「删除」by accident is exactly the
    failure mode this script must not have.
    """
    for _ in range(2):
        try:
            page.keyboard.press("Escape")
        except PlaywrightError:
            break
        page.wait_for_timeout(200)
    for _ in range(3):
        btn = page.locator(".el-drawer__close-btn:visible")
        if btn.count() == 0:
            break
        try:
            btn.first.click()
        except PlaywrightError:
            break
        page.wait_for_timeout(300)
    # An error alert (ElMessageBox) only ever has 知道了; nothing else is clicked.
    ack = page.locator(".el-message-box__btns button:visible", has_text="知道了")
    if ack.count():
        ack.first.click()
        page.wait_for_timeout(300)


def shoot(page, name: str, slug: str) -> None:
    path = OUT / f"{name}-{slug}.png"
    page.screenshot(path=str(path), full_page=False)
    size = path.stat().st_size if path.exists() else 0
    require(size > 0, f"截图文件为空：{path.name}")
    SIZES[path.name] = size


# ---------------------------------------------------------------------- shots --
# Every selector/button label below is taken from the product source; the
# citing comment next to it is the proof that the wording was read, not guessed.

def shot_containers(page) -> str:
    """01-containers.png - container list, left nav and table columns."""
    goto(page, "/containers")
    rows = wait_rows(page)
    require(rows > 0, f"容器列表没有渲染出任何行（rows={rows}）")
    wait_loading_gone(page)
    nav = [t.strip() for t in page.locator(".dm-nav-item").all_inner_texts()]
    require(len(nav) == 4, f"左侧导航项数异常：{nav}")           # App.vue:60-65
    require(all(k in " ".join(nav) for k in ("容器", "镜像", "网络", "卷")), f"导航文案异常：{nav}")
    head = headers(page)
    for expected in ("状态", "名称", "镜像", "端口", "操作"):     # ContainersView.vue:26-63
        require(expected in head, f"表头缺少「{expected}」：{head}")
    title = page.locator(".dm-page-title").first.inner_text().strip()  # ContainersView.vue:5
    require("容器" in title, f"页面标题异常：{title!r}")
    health = page.locator(".dm-health").first.inner_text().strip()     # App.vue:35
    shoot(page, "01", "containers")
    require(page.locator(".el-table__body tr").count() > 0, "截图后表格行消失")
    return f"{rows} 行；导航={nav}；表头={head}；标题={title!r}；服务状态={health!r}"


def shot_run_dialog(page) -> str:
    """03-run-dialog.png - the run wizard with the input fields visible."""
    goto(page, "/containers")
    new_btn = page.get_by_role("button", name="新建容器")        # ContainersView.vue:19
    new_btn.wait_for(state="visible", timeout=15000)
    new_btn.click()
    page.locator(".el-dialog:visible").first.wait_for(state="visible", timeout=10000)
    title = page.locator(".el-dialog__title:visible").first.inner_text().strip()
    require("创建并运行容器" in title, f"运行向导标题异常：{title!r}")  # RunContainerDialog.vue:4

    # Fill demo values from the MySQL preset (RunContainerDialog.vue:158) so the
    # screenshot shows a fully populated form. The preset only writes into the
    # component's local form - it makes no API call.
    page.get_by_role("button", name="MySQL", exact=True).click()
    image_field = page.get_by_placeholder("mysql:latest")        # RunContainerDialog.vue:32
    poll(page, lambda: image_field.input_value().strip() or None, 10000)
    name_field = page.get_by_placeholder("选填，留空自动生成，例如 mysql-db")  # :36
    ports_field = page.get_by_placeholder("3306:3306")           # :45
    env_field = page.locator(".el-dialog textarea").nth(1)       # :59 (2nd textarea = env)
    volumes_field = page.locator(".el-dialog textarea").nth(2)   # :70 (3rd = volumes)

    values = {
        "镜像": image_field.input_value().strip(),
        "容器名": name_field.input_value().strip(),
        "端口映射": ports_field.input_value().strip(),
        "环境变量": env_field.input_value().strip(),
        "目录挂载": volumes_field.input_value().strip(),
    }
    for label, value in values.items():
        require(bool(value), f"运行向导的「{label}」输入项为空，无法证明输入项可见")
    require("3306:3306" in values["端口映射"], f"端口映射内容异常：{values['端口映射']!r}")
    require("MYSQL_ROOT_PASSWORD" in values["环境变量"], "环境变量未被预设填好")
    submit = page.get_by_role("button", name=re.compile("创建并启动|仅创建"))  # :106
    submit.wait_for(state="visible", timeout=5000)

    wait_settled(page, ".el-dialog:visible")
    shoot(page, "03", "run-dialog")
    # Safety: the submit button was only ever looked at, never clicked - the
    # dialog must therefore still be open, and no container may have appeared.
    require(page.locator(".el-dialog:visible").count() > 0, "运行向导在未提交的情况下关闭了")
    reset_ui(page)
    poll(page, lambda: page.locator(".el-dialog:visible").count() == 0 and True or None, 8000)
    return "镜像=%s 容器名=%s 端口=%s（仅填表，未提交）" % (
        values["镜像"], values["容器名"], values["端口映射"],
    )


def shot_logs(page) -> str:
    """04-logs.png - the log drawer with real log lines rendered."""
    goto(page, "/containers")
    open_row_menu(page, CONTAINER_LOGS)
    click_menu_item(page, "查看日志")                            # ContainersView.vue:119
    head = wait_drawer(page, "容器日志")                         # ContainersView.vue:162
    line_count = poll(page, lambda: page.locator(".log-line").count(), 30000)  # ContainerLogs.vue:48
    require(bool(line_count), f"日志抽屉里没有出现任何日志行（title={head!r}）")
    state = page.locator(".log-state").first.inner_text().strip()  # ContainerLogs.vue:15
    first = page.locator(".log-line").first.inner_text().strip()
    wait_settled(page, ".el-drawer:visible")
    shoot(page, "04", "logs")
    require(page.locator(".log-line").count() > 0, "截图后日志行消失")
    # Close the stream, then the drawer: no websocket is left dangling.
    # Teardown failures are reported but must not undo a good screenshot.
    try:
        page.get_by_role("button", name="断开").first.click(timeout=5000)  # ContainerLogs.vue:29
    except PlaywrightError as exc:
        log(f"  (日志抽屉的「断开」按钮未能点击：{exc})")
    reset_ui(page)
    return f"{line_count} 行；状态={state!r}；首行={first[:70]!r}"


def shot_terminal(page) -> str:
    """05-terminal.png - an interactive shell inside a container."""
    goto(page, "/containers")
    open_row_menu(page, CONTAINER_EXEC)
    click_menu_item(page, "进入终端")                            # ContainersView.vue:133
    head = wait_drawer(page, "交互终端")                         # ContainersView.vue:173
    def connected_state():
        el = page.locator(".term-state-text")
        if not el.count():
            return None
        text = el.first.inner_text().strip()
        return text if "已连接" in text else None

    state = poll(page, connected_state, 30000)                   # ContainerTerminal.vue:6
    require(bool(state), f"终端未能连上：{page.locator('.term-state-text').first.inner_text()!r}")

    def prompt_text():
        """The xterm screen text, but only once a shell prompt has been drawn."""
        el = page.locator(".xterm-rows")
        if not el.count():
            return None
        text = el.first.inner_text()
        return text if re.search(r"[#$%>]", text) else None

    text = poll(page, prompt_text, 20000)
    if not text:
        # The shell was connected but printed nothing yet: nudge it once with a
        # bare Enter (no command is executed, nothing in the container changes).
        page.locator(".xterm").first.click()
        page.keyboard.press("Enter")
        text = poll(page, prompt_text, 15000)
    require(bool(text), "终端已连接但没有出现 shell 提示符")
    wait_settled(page, ".el-drawer:visible")
    shoot(page, "05", "terminal")
    require(page.locator(".xterm").count() > 0, "截图后终端消失")
    # Detach the session, then close the drawer (both are needed: 断开 stops the
    # stream, unmounting the drawer releases the socket for good). Teardown
    # failures are reported but must not undo a good screenshot.
    try:
        page.get_by_role("button", name="断开").first.click(timeout=5000)  # ContainerTerminal.vue:13
    except PlaywrightError as exc:
        log(f"  (终端抽屉的「断开」按钮未能点击：{exc})")
    reset_ui(page)
    left = poll(page, lambda: page.locator(".xterm").count() == 0 and True or None, 8000)
    require(bool(left), "终端抽屉关闭后 xterm 仍然存在，会话可能悬挂")
    return f"{head!r}；状态={state!r}；终端文本={text.strip()[:60]!r}"


def shot_file_copy(page) -> str:
    """06-file-copy.png - the file copy drawer (both directions)."""
    goto(page, "/containers")
    open_row_menu(page, CONTAINER_EXEC)
    click_menu_item(page, "文件拷贝")                            # ContainersView.vue:135
    head = wait_drawer(page, "文件拷贝")                         # ContainersView.vue:183
    upload = page.get_by_text("从本机拷入容器")                  # FileCopyDrawer.vue:7
    upload.wait_for(state="visible", timeout=10000)
    download = page.get_by_text("从容器拷出到本机")              # FileCopyDrawer.vue:47
    require(download.is_visible(), "文件拷贝抽屉缺少「从容器拷出到本机」区块")
    drop = page.locator(".el-upload-dragger")                    # FileCopyDrawer.vue:12-22
    require(drop.count() > 0 and drop.first.is_visible(), "上传拖拽区未渲染")
    dest = page.get_by_placeholder("/tmp").input_value()         # FileCopyDrawer.vue:26
    src = page.get_by_placeholder("/app/logs").input_value()     # FileCopyDrawer.vue:55
    wait_settled(page, ".el-drawer:visible")
    shoot(page, "06", "file-copy")
    require(page.get_by_text("从本机拷入容器").is_visible(), "截图后抽屉内容消失")
    reset_ui(page)
    return f"{head!r}；默认目标目录={dest!r}；默认源路径={src!r}"


def shot_error_toast(page) -> str:
    """10-error-toast.png - a real, recoverable error prompt.

    Triggered by asking the copy drawer to download a path that does not exist.
    That is a GET (`FileCopyDrawer.vue:118`), the backend answers 500 and
    `showApiError` (utils/error.ts:13) surfaces it. Nothing is created or
    deleted - the request only reads (and fails).
    """
    goto(page, "/containers")
    open_row_menu(page, CONTAINER_EXEC)
    click_menu_item(page, "文件拷贝")
    wait_drawer(page, "文件拷贝")
    page.get_by_placeholder("/app/logs").fill(BAD_COPY_PATH)     # FileCopyDrawer.vue:55
    page.get_by_role("button", name="下载").first.click()        # FileCopyDrawer.vue:58-60

    # >140 characters of backend detail opens an ElMessageBox alert instead of a
    # toast (utils/error.ts:26); accept either shape and report which one it was.
    alert = page.locator(".el-message-box:visible")
    toast = page.locator(".el-message--error:visible")
    kind = poll(page, lambda: "alert" if alert.count() else ("toast" if toast.count() else None), 20000)
    require(bool(kind), "故意触发的非法路径没有产生任何错误提示")
    box = alert.first if kind == "alert" else toast.first
    text = box.inner_text().strip()
    require(bool(text), "错误提示没有文本内容")
    wait_settled(page, ".el-message-box:visible")
    shoot(page, "10", "error-toast")
    require(bool(box.inner_text().strip()), "截图后错误提示消失")
    reset_ui(page)
    return f"{kind}；文本={text.replace(chr(10), ' / ')[:120]!r}"


def shot_simple(page, path: str, name: str, slug: str, expect: tuple[str, ...]) -> str:
    """07/08/09 - images / networks / volumes list pages."""
    goto(page, path)
    rows = wait_rows(page)
    require(rows > 0, f"{path} 没有渲染出任何行（rows={rows}）")
    wait_loading_gone(page)
    head = headers(page)
    for expected in expect:
        require(expected in head, f"{path} 表头缺少「{expected}」：{head}")
    title = page.locator(".dm-page-title").first.inner_text().strip()
    shoot(page, name, slug)
    require(page.locator(".el-table__body tr").count() > 0, "截图后表格行消失")
    return f"{rows} 行；标题={title!r}；表头={head}"


def shot_images(page) -> str:
    return shot_simple(page, "/images", "07", "images",
                       ("标签", "镜像 ID", "操作"))            # ImagesView.vue:35-58


def shot_networks(page) -> str:
    return shot_simple(page, "/networks", "08", "networks",
                       ("名称", "驱动", "范围", "操作"))        # NetworksView.vue:25-49


def shot_volumes(page) -> str:
    return shot_simple(page, "/volumes", "09", "volumes",
                       ("名称", "驱动", "挂载点", "操作"))      # VolumesView.vue:25-45


# `02-container-detail.png` has no implementation on purpose: the product has
# no container-detail surface. Recorded as SKIPPED in the report instead of
# being faked from an unrelated dialog.
SHOT_TABLE = [
    ("01", "containers", shot_containers),
    ("02", "container-detail", None),
    ("03", "run-dialog", shot_run_dialog),
    ("04", "logs", shot_logs),
    ("05", "terminal", shot_terminal),
    ("06", "file-copy", shot_file_copy),
    ("07", "images", shot_images),
    ("08", "networks", shot_networks),
    ("09", "volumes", shot_volumes),
    ("10", "error-toast", shot_error_toast),
]

SKIP_REASON = {
    "02": "产品没有容器详情抽屉/弹窗（frontend/src 与 frontend/dist 中均无「详情」字样；"
          "后端 GET /containers/{cid} 无前端调用方），不伪造该图",
}


# ------------------------------------------------------------------ docker io --

def docker_counts() -> dict:
    """Best-effort resource counts, used as the zero-side-effect evidence.

    Returns None per key when the docker CLI cannot be reached - that is
    reported, never treated as a failure.
    """
    cmds = {
        "containers": ["docker", "ps", "-a", "-q"],
        "images": ["docker", "images", "-q"],
        "volumes": ["docker", "volume", "ls", "-q"],
        "networks": ["docker", "network", "ls", "-q"],
    }
    counts: dict = {}
    for key, cmd in cmds.items():
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            counts[key] = len([ln for ln in res.stdout.splitlines() if ln.strip()])
        except Exception:  # pragma: no cover - environment dependent
            counts[key] = None
    return counts


def docker_container_names() -> str:
    try:
        res = subprocess.run(
            ["docker", "ps", "-a", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=30,
        )
        return "|".join(sorted(n.strip() for n in res.stdout.splitlines() if n.strip()))
    except Exception:  # pragma: no cover
        return "<unavailable>"


# ------------------------------------------------------------------------ main --

def check_panel() -> None:
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(f"{BASE}/api/health", timeout=10) as resp:
            body = resp.read().decode("utf-8", "replace")
    except (urllib.error.URLError, OSError) as exc:
        log(f"面板不可达：{BASE}/api/health -> {exc}")
        log("请先启动面板（nginx + backend）后重试。")
        sys.exit(2)
    log(f"面板健康检查：{body.strip()}")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    log(f"输出目录：{OUT}")
    check_panel()

    before_counts = docker_counts()
    before_names = docker_container_names()
    log(f"开工前 Docker 资源计数：{before_counts}")

    with sync_playwright() as p:
        browser = p.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            viewport=VIEWPORT, device_scale_factor=1, accept_downloads=True
        )
        page = context.new_page()
        page.set_default_timeout(15000)

        def on_console(msg):
            if msg.type == "error":
                DIAG["console_error"].append(f"{msg.type}: {msg.text}")
            elif msg.type == "warning":
                DIAG["console_warning"].append(f"{msg.type}: {msg.text}")

        page.on("console", on_console)
        page.on("pageerror", lambda e: DIAG["pageerror"].append(str(e)))
        page.on(
            "requestfailed",
            lambda r: DIAG["requestfailed"].append(f"{r.method} {r.url} - {r.failure}"),
        )
        page.on("download", lambda d: DIAG["download"].append(d.suggested_filename))

        try:
            for name, slug, fn in SHOT_TABLE:
                target = f"{name}-{slug}.png"
                if fn is None:
                    SHOTS.append((target, "skipped", SKIP_REASON.get(name, "无可用的界面入口")))
                    log(f"[skip] {target} -- {SKIP_REASON.get(name, '')}")
                    continue

                log(f"[shot] {target}")
                error = "未执行"
                for attempt in range(1, ATTEMPTS + 1):
                    reset_ui(page)
                    try:
                        detail = fn(page)
                        SHOTS.append((target, "ok", detail))
                        log(f"  [ok] {target} ({SIZES.get(target, 0)} bytes) -- {detail}")
                        error = ""
                        break
                    except Exception as exc:  # noqa: BLE001 - reported verbatim
                        error = f"{type(exc).__name__}: {exc}"
                        log(f"  [attempt {attempt}/{ATTEMPTS} failed] {error}")
                        if attempt == ATTEMPTS:
                            SHOTS.append((target, "failed", error))
                if error:
                    log(f"  [FAIL] {target} -- {error}")
        finally:
            context.close()
            browser.close()

    after_counts = docker_counts()
    after_names = docker_container_names()
    log(f"收工后 Docker 资源计数：{after_counts}")

    # ------------------------------------------------------------- report ----
    ok = [s for s in SHOTS if s[1] == "ok"]
    failed = [s for s in SHOTS if s[1] == "failed"]
    skipped = [s for s in SHOTS if s[1] == "skipped"]

    log("\n" + "=" * 72)
    log("Docker Manager UI 截图报告")
    log("=" * 72)
    for target, status, detail in SHOTS:
        mark = {"ok": "OK     ", "failed": "FAILED ", "skipped": "SKIPPED"}[status]
        size = f"{SIZES.get(target, 0):>7} bytes" if status == "ok" else " " * 13
        log(f"{mark} {target:<24} {size}  {detail}")

    log("\nDocker 资源计数（开工前 -> 收工后）")
    for key in ("containers", "images", "volumes", "networks"):
        log(f"  {key:<11}: {before_counts.get(key)} -> {after_counts.get(key)}")
    log(f"  容器名集合一致: {before_names == after_names}")
    counts_changed = before_counts != after_counts or before_names != after_names

    log("\n浏览器诊断（仅报告，不参与截图成败判定）")
    log(f"  pageerror      : {len(DIAG['pageerror'])}")
    for item in DIAG["pageerror"]:
        log(f"     !! {item}")
    log(f"  console error  : {len(DIAG['console_error'])}")
    for item in DIAG["console_error"]:
        log(f"     -  {item}")
    log(f"  console warning: {len(DIAG['console_warning'])}")
    for item in DIAG["console_warning"]:
        log(f"     -  {item}")
    log(f"  requestfailed  : {len(DIAG['requestfailed'])}")
    for item in DIAG["requestfailed"]:
        log(f"     -  {item}")
    log(f"  download 事件  : {len(DIAG['download'])}")
    for item in DIAG["download"]:
        log(f"     -  {item}")

    log("\n" + "=" * 72)
    log(f"成功 {len(ok)} 张 / 失败 {len(failed)} 张 / 跳过 {len(skipped)} 张")
    if failed:
        log("失败清单：")
        for target, _, detail in failed:
            log(f"  !! {target} -- {detail}")
    if skipped:
        log("跳过清单（不计入失败）：")
        for target, _, detail in skipped:
            log(f"  -- {target} -- {detail}")
    if counts_changed:
        log("!! Docker 资源计数发生变化，违反只读约束，请立即人工核查")
        log("=" * 72)
        return 1
    log("=" * 72)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
