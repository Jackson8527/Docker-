"""E2E verification for docker-manager (run against the live deployment).

Verifies: HTTP CRUD endpoints, WebSocket logs, WebSocket exec terminal,
host<->container file copy, container commit, image export.

This script is a gate: it exits 1 when any check failed, 0 only when all of
them passed.

Dependencies are declared in scripts/requirements-verify.txt (do not rely on
whatever happens to be installed transitively):

    pip install -r scripts/requirements-verify.txt
    python scripts/e2e_verify.py
"""
import asyncio
import io
import json
import random
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8088"
WS_BASE = "ws://127.0.0.1:8088"

# How long a websocket check waits for real traffic before it fails.
WS_WAIT_SECONDS = 20

DEPENDENCY_HINT = "缺少验证依赖。请先安装：pip install -r scripts/requirements-verify.txt"

# websockets is a declared dependency, not an accident of uvicorn[standard].
try:
    import websockets
except ImportError as _exc:  # pragma: no cover - depends on the interpreter
    websockets = None
    _WEBSOCKETS_IMPORT_ERROR = repr(_exc)
else:
    _WEBSOCKETS_IMPORT_ERROR = None

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


def require_websockets(name):
    """Return the websockets module, or record a readable FAIL and return None."""
    if websockets is not None:
        return websockets
    record(name, False,
           f"缺少依赖 websockets（{_WEBSOCKETS_IMPORT_ERROR}）-> {DEPENDENCY_HINT}")
    return None


def http(method, path, data=None, headers=None, timeout=30):
    url = BASE + path
    body = None
    hdrs = headers or {}
    if data is not None:
        if isinstance(data, (bytes, bytearray)):
            body = bytes(data)
        else:
            body = json.dumps(data).encode()
            hdrs.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=hdrs, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.status, r.read()


# ---------------------------------------------------------------- HTTP ----
def test_health():
    try:
        st, body = http("GET", "/api/health")
        ok = st == 200 and json.loads(body).get("status") == "ok"
        record("HTTP /api/health", ok, body.decode()[:80])
    except Exception as e:
        record("HTTP /api/health", False, repr(e))


def test_containers():
    try:
        st, body = http("GET", "/api/containers?all=true")
        data = json.loads(body)
        ok = st == 200 and isinstance(data, list) and len(data) > 0
        names = [c["name"] for c in data][:4]
        record("HTTP /api/containers", ok, f"{len(data)} containers e.g. {names}")

        # Ports must be rendered for humans, not dumped as a dict repr.
        with_ports = [c for c in data if c.get("ports")]
        raw = [c for c in with_ports if "{" in c["ports"] or "'" in c["ports"]]
        record("Container ports are human-readable", not raw,
               (with_ports[0]["ports"] if with_ports else "no published ports"))
        return data
    except Exception as e:
        record("HTTP /api/containers", False, repr(e))
        return []


def test_images():
    try:
        st, body = http("GET", "/api/images")
        data = json.loads(body)
        ok = st == 200 and isinstance(data, list) and len(data) > 0
        record("HTTP /api/images", ok, f"{len(data)} images")
        return data
    except Exception as e:
        record("HTTP /api/images", False, repr(e))
        return []


def test_networks():
    try:
        st, body = http("GET", "/api/networks")
        data = json.loads(body)
        ok = st == 200 and isinstance(data, list)
        record("HTTP /api/networks", ok, f"{len(data)} networks")
    except Exception as e:
        record("HTTP /api/networks", False, repr(e))


def test_volumes():
    try:
        st, body = http("GET", "/api/volumes")
        data = json.loads(body)
        ok = st == 200 and isinstance(data, list)
        record("HTTP /api/volumes", ok, f"{len(data)} volumes")
    except Exception as e:
        record("HTTP /api/volumes", False, repr(e))


# ------------------------------------------------------------ file copy ----
def multipart(fields, files):
    """Build a multipart/form-data body manually (urllib has no helper)."""
    boundary = "----dockermgr" + uuid.uuid4().hex
    buf = io.BytesIO()
    for k, v in fields.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(f'Content-Disposition: form-data; name="{k}"\r\n\r\n'.encode())
        buf.write(str(v).encode() + b"\r\n")
    for k, (fname, content) in files.items():
        buf.write(f"--{boundary}\r\n".encode())
        buf.write(
            f'Content-Disposition: form-data; name="{k}"; filename="{fname}"\r\n'.encode()
        )
        buf.write(b"Content-Type: application/octet-stream\r\n\r\n")
        buf.write(content + b"\r\n")
    buf.write(f"--{boundary}--\r\n".encode())
    return buf.getvalue(), f"multipart/form-data; boundary={boundary}"


def test_file_copy(cid):
    marker = ("dockermgr-e2e-" + uuid.uuid4().hex[:8]).encode()

    # --- copy INTO the container ---
    body, ctype = multipart({"dest": "/tmp"}, {"file": ("e2e.txt", marker)})
    try:
        st, resp = http("POST", f"/api/containers/{cid}/copy", data=body,
                        headers={"Content-Type": ctype})
        ok = st == 200 and json.loads(resp).get("ok") is True
        record("File copy INTO container", ok, resp.decode()[:100])
    except Exception as e:
        record("File copy INTO container", False, repr(e))
        return

    # --- copy OUT of the container, and verify the bytes survived ---
    try:
        st, resp = http("GET", f"/api/containers/{cid}/copy?path=/tmp/e2e.txt")
        got = b""
        if st == 200:
            with tarfile.open(fileobj=io.BytesIO(resp), mode="r") as tar:
                member = tar.getmembers()[0]
                got = tar.extractfile(member).read()
        ok = st == 200 and marker in got
        record("File copy OUT of container (roundtrip)", ok,
               f"marker roundtrip={'yes' if marker in got else 'no'}")
    except Exception as e:
        record("File copy OUT of container (roundtrip)", False, repr(e))


# ------------------------------------------------------- commit / export ----
def test_commit(cid):
    repo = "dockermgr-e2e"
    tag = uuid.uuid4().hex[:8]
    try:
        st, body = http("POST", f"/api/containers/{cid}/commit",
                        data={"repo": repo, "tag": tag}, timeout=120)
        data = json.loads(body)
        ok = st == 200 and "image_id" in data
        record("Container commit -> image", ok, str(data)[:100])
        return f"{repo}:{tag}"
    except Exception as e:
        record("Container commit -> image", False, repr(e))
        return None


def test_image_export(image_ref):
    if not image_ref:
        record("Image export (save tar)", False, "skipped: no image from commit")
        return
    try:
        # find the image id for the committed tag
        st, body = http("GET", "/api/images")
        imgs = json.loads(body)
        target = next((i for i in imgs if image_ref in (i.get("tags") or [])), None)
        if not target:
            record("Image export (save tar)", False, f"image {image_ref} not found")
            return
        st, blob = http("GET", f"/api/images/{target['id']}/save", timeout=120)
        # a docker save tarball must be a readable tar with manifest.json
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r") as tar:
            names = tar.getnames()
        ok = st == 200 and "manifest.json" in names and len(blob) > 1000
        record("Image export (save tar)", ok,
               f"{len(blob)} bytes, entries={len(names)}, manifest={'yes' if 'manifest.json' in names else 'no'}")
    except Exception as e:
        record("Image export (save tar)", False, repr(e))


def test_image_remove(image_ref):
    """Delete the image created by the commit test and prove it is gone."""
    if not image_ref:
        record("Cleanup committed image", False, "skipped: commit produced no image")
        return
    try:
        st, body = http("GET", "/api/images")
        imgs = json.loads(body)
        target = next((i for i in imgs if image_ref in (i.get("tags") or [])), None)
        if not target:
            record("Cleanup committed image", False, f"image {image_ref} not found")
            return

        st, body = http("DELETE", f"/api/images/{target['id']}?force=true", timeout=60)
        detail = body.decode(errors="replace")[:80]
        if st != 200:
            record("Cleanup committed image", False, f"DELETE -> HTTP {st}: {detail}")
            return
        delete_status = st

        # A 200 is not proof: re-list and require the tag to be gone.
        st, body = http("GET", "/api/images")
        still = [i for i in json.loads(body) if image_ref in (i.get("tags") or [])]
        record("Cleanup committed image", not still,
               f"delete HTTP {delete_status}, tag "
               f"{'still present' if still else 'gone'}: {image_ref}")
    except Exception as e:
        record("Cleanup committed image", False, repr(e))


# ---------------------------------------------------------------- WS ----
LOGS_TEST = "WS /ws/logs (realtime logs)"

# The backend's drop notice is not container output, so it must not be able to
# satisfy the "at least one real log line" assertion on its own.
DROP_NOTICE_PREFIX = "... "


def control_frame_error(msg):
    """Return the reason if a text frame is a `{"dockermgr": "error", ...}` frame.

    The backend reports "cannot serve this socket" as a JSON text frame before
    closing, so a frame is not evidence of a working channel until it has been
    shown NOT to be one of these.

    The `dockermgr == "error"` discriminator is what distinguishes a protocol
    frame from a container that happens to log a single JSON line like
    {"error": "upstream timeout"}: only the former may fail this check, and a
    real log line must never be swallowed as a protocol frame.
    """
    if not isinstance(msg, str):
        return None
    text = msg.strip()
    if not text.startswith("{"):
        return None
    try:
        obj = json.loads(text)
    except ValueError:
        return None
    if not isinstance(obj, dict) or obj.get("dockermgr") != "error":
        return None
    reason = obj.get("error")
    if not isinstance(reason, str) or not reason.strip():
        return "（服务端失败帧缺少可读原因）"
    return reason


def log_lines_in_frame(msg):
    """Real log lines inside one frame (frames may carry many `\\n`-joined lines)."""
    if not isinstance(msg, str):
        return []
    lines = msg.split("\n")
    return [ln for ln in lines if ln.strip() and not ln.startswith(DROP_NOTICE_PREFIX)]


# A PTY stream carries cursor/erase sequences around the text a human sees.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\x1b[()][A-Z0-9]")


def visible_lines(text):
    """Terminal bytes -> the lines a human would actually read.

    Comparing against these instead of the raw stream is what lets a check tell
    an executed *result* apart from the PTY's echo of the typed line: the echo
    of `echo $((1+2))` is a line of its own only once the escape codes and the
    `\\r` padding are gone.
    """
    stripped = _ANSI_RE.sub("", text).replace("\r\n", "\n").replace("\r", "\n")
    return [line.strip() for line in stripped.split("\n") if line.strip()]


async def drain_frames(ws, needles, timeout):
    """Collect frames until a needle is visible, or the deadline expires.

    Returns `(visible_text, control_frame_error_or_None)`. One collector for all
    websocket checks keeps the "did the server tell us why it gave up" test in a
    single place, so a new check cannot forget it.
    """
    text = ""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            chunk = await asyncio.wait_for(ws.recv(), timeout=3)
        except asyncio.TimeoutError:
            break
        reason = control_frame_error(chunk)
        if reason is not None:
            return text, reason
        text += chunk
        if any(needle in text for needle in needles):
            break
    return text, None


async def test_ws_logs(container_name):
    ws_mod = require_websockets(LOGS_TEST)
    if ws_mod is None:
        return
    try:
        url = f"{WS_BASE}/ws/logs?filter={container_name}&stream=both&tail=20"
        async with ws_mod.connect(url, open_timeout=15) as ws:
            frames = 0
            lines: list[str] = []
            closed = None
            deadline = time.monotonic() + WS_WAIT_SECONDS
            while time.monotonic() < deadline:
                try:
                    msg = await asyncio.wait_for(
                        ws.recv(), timeout=max(0.1, deadline - time.monotonic())
                    )
                except asyncio.TimeoutError:
                    break
                except Exception as e:  # closed by the server or the network
                    closed = repr(e)
                    break

                reason = control_frame_error(msg)
                if reason is not None:
                    record(LOGS_TEST, False, f"服务端控制帧报错：{reason}")
                    return

                frames += 1
                lines.extend(log_lines_in_frame(msg))

            if lines:
                record(LOGS_TEST, True,
                       f"收到 {len(lines)} 行真实日志（{frames} 帧），"
                       f"例：{lines[0][:60]!r}")
            elif frames:
                record(LOGS_TEST, False,
                       f"收到 {frames} 帧但没有任何真实日志行"
                       f"（容器 {container_name} 无输出或帧内容非法）")
            elif closed:
                record(LOGS_TEST, False,
                       f"连接被对方关闭且未收到任何日志行：{closed}")
            else:
                record(LOGS_TEST, False,
                       f"{WS_WAIT_SECONDS}s 内未收到任何日志行（容器 {container_name}）")
    except Exception as e:
        record(LOGS_TEST, False, repr(e))


async def test_ws_exec(cid):
    """The terminal must deliver *execution output*, not just a PTY echo.

    RD3-06: the old check sent `echo <token>` and asserted the token came back.
    A PTY echoes the line it is fed, so that assertion was satisfied with the
    command never running - measured live by putting the token in a shell
    *comment* (zero output) and watching it arrive anyway
    (.rd3-probes/exec-echo-probe.txt). The check could not have failed even on a
    completely dead shell.

    The marker is now a value only the shell can produce, and the echo channel
    is proved separately so the two can never be confused:

      1. a comment line is echoed but prints nothing, so its text can only come
         back through the echo - if it does, the stream really is echoing and
         step 2 is being tested against the channel that caused the false green;
      2. `echo $((a+b))` must print the sum as a line of its own. Both operands
         are 6-digit, so the sum is always 7 digits and therefore cannot occur
         anywhere inside the echoed command text (whose digit runs are 6 long) -
         the echoed line simply does not contain it.
    """
    ws_mod = require_websockets("WS /ws/exec (interactive terminal)")
    if ws_mod is None:
        return
    name = "WS /ws/exec (interactive terminal)"
    try:
        a = random.randint(500000, 899999)
        b = random.randint(500000, 899999)
        total = str(a + b)
        command = f"echo $(({a}+{b}))"
        # Belt and braces: if the sum ever leaked into the command text, the
        # echo alone could produce it and the whole check would be forgeable.
        assert total not in command, "exec marker is forgeable by the PTY echo"
        echo_marker = "EXECECHO" + uuid.uuid4().hex[:6]

        url = f"{WS_BASE}/ws/exec?container={cid}"
        async with ws_mod.connect(url, open_timeout=15) as ws:
            await asyncio.sleep(0.5)
            # Announce the terminal size first, exactly like the browser does.
            await ws.send(json.dumps({"type": "resize", "cols": 100, "rows": 30}))
            await asyncio.sleep(0.3)

            # 1. echo channel: a shell comment produces no output at all.
            await ws.send(json.dumps({"type": "input", "data": f"# {echo_marker}\n"}))
            echoed, reason = await drain_frames(ws, [echo_marker], 8)
            if reason is not None:
                record(name, False, f"服务端控制帧报错：{reason}")
                return
            echo_seen = any(echo_marker in line for line in visible_lines(echoed))

            # 2. execution channel: only the shell can compute the sum.
            await ws.send(json.dumps({"type": "input", "data": command + "\n"}))
            output, reason = await drain_frames(ws, [total], 15)
            if reason is not None:
                record(name, False, f"服务端控制帧报错：{reason}")
                return
            lines = visible_lines(output)
            executed = total in lines
            tail = lines[-1][:40] if lines else "<无输出>"
            record(name, echo_seen and executed,
                   f"echo 通道={'live' if echo_seen else 'missing'}，"
                   f"执行结果行 {total}={'yes' if executed else 'no'}"
                   f"（末行 {tail!r}）")
    except Exception as e:
        record(name, False, repr(e))


async def test_ws_exec_resize(cid):
    """The PTY must accept a resize; an 80x24 PTY garbles a wide terminal."""
    import websockets
    try:
        url = f"{WS_BASE}/ws/exec?container={cid}"
        async with websockets.connect(url, open_timeout=15) as ws:
            await asyncio.sleep(0.4)
            await ws.send(json.dumps({"type": "resize", "cols": 132, "rows": 43}))
            await asyncio.sleep(0.4)
            # `stty size` prints "<rows> <cols>" as the kernel sees it.
            await ws.send(json.dumps({"type": "input", "data": "stty size\n"}))
            collected = ""
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                try:
                    chunk = await asyncio.wait_for(ws.recv(), timeout=3)
                except asyncio.TimeoutError:
                    break
                reason = control_frame_error(chunk)
                if reason is not None:
                    record("WS /ws/exec PTY resize", False,
                           f"服务端控制帧报错：{reason}")
                    return
                collected += chunk
                if "43 132" in collected:
                    break
            ok = "43 132" in collected
            record("WS /ws/exec PTY resize", ok,
                   f"stty size -> {'43 132' if ok else collected[-60:]!r}")
    except Exception as e:
        record("WS /ws/exec PTY resize", False, repr(e))


# ---------------------------------------------------------- run container ----


def test_run_container():
    """Create, verify and clean up a container built from a local image."""
    name = "dockermgr-e2e-run-" + uuid.uuid4().hex[:6]
    cid = None
    try:
        st, body = http("GET", "/api/images")
        tags = [t for img in json.loads(body) for t in (img.get("tags") or [])]
        image = next(
            (t for t in ("nginx:alpine", "alpine:latest", "python:3.12-slim") if t in tags),
            tags[0] if tags else None,
        )
        if not image:
            record("Run container from image", False, "no local image available")
            return

        # A bare '80' publishes the container port on a random host port.
        st, body = http(
            "POST",
            "/api/containers",
            {
                "image": image,
                "name": name,
                "ports": "80",
                "env": "E2E_MARKER=1",
                "restart_policy": "no",
                "auto_start": True,
            },
            timeout=180,
        )
        created = json.loads(body)
        cid = created["id"]
        ok = st == 200 and created["name"] == name
        record("Run container from image", ok,
               f"{image} -> {created['name']} ({created['state']})")

        st, body = http("GET", f"/api/containers/{cid}")
        info = json.loads(body)
        record("Created container is running", info.get("state") == "running",
               f"state={info.get('state')}")

        # Asserted unconditionally: a conditional assert would silently drop
        # this check from the total instead of failing loudly.
        ports = (info.get("ports") or "").strip()
        if ports:
            record("Created container published its port", "->" in ports, ports)
        else:
            record("Created container published its port", False,
                   "ports 为空，但创建时显式请求了 ports=80：端口映射未生效")
    except Exception as e:
        record("Run container from image", False, repr(e))
    finally:
        if cid:
            for method, path in (("POST", f"/api/containers/{cid}/stop"),
                                 ("DELETE", f"/api/containers/{cid}")):
                try:
                    http(method, path, timeout=60)
                except Exception:
                    pass


def test_run_container_validation():
    """Bad form input must be a readable 400, not a 500."""
    try:
        try:
            http("POST", "/api/containers", {"image": "alpine", "ports": "not-a-port"})
            record("Create container rejects bad ports", False, "expected HTTP 400")
        except urllib.error.HTTPError as e:
            detail = json.loads(e.read()).get("detail", "")
            record("Create container rejects bad ports", e.code == 400,
                   f"HTTP {e.code}: {str(detail)[:50]}")
    except Exception as e:
        record("Create container rejects bad ports", False, repr(e))


# ---------------------------------------------------------------- main ----
# The full suite is expected to report exactly this many checks. A smaller
# count means a check silently disappeared (the C-11 defect), which must fail
# the run just like a red check does.
EXPECTED_CHECKS = 18


def summarize() -> int:
    """Print the report and return the process exit code."""
    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"RESULT: {passed}/{total} passed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name} -- {detail}")
    complete = total == EXPECTED_CHECKS
    if not complete:
        print(f"  FAILED: 检查项数量 {total} != 预期 {EXPECTED_CHECKS}"
              "（有检查被静默跳过）")
    if total == 0:
        print("  FAILED: 没有任何检查被执行")
    print("=" * 70)
    return 0 if (complete and passed == total) else 1


def main() -> int:
    print("=" * 70)
    print("docker-manager E2E verification against live deployment")
    print("=" * 70)
    if websockets is None:
        print(f"!! {DEPENDENCY_HINT}（WebSocket 相关检查会直接判 FAIL）")

    test_health()
    containers = test_containers()
    test_images()
    test_networks()
    test_volumes()

    # pick our own backend container as the test subject
    target = next((c for c in containers if c["name"] == "dockermgr-backend"), None)
    if not target:
        target = containers[0] if containers else None
    if not target:
        print("!! no container available for interactive tests")
        record("Interactive tests need a container", False,
               "no container available for interactive tests")
        return summarize()
    cid = target["id"]
    print(f"\n-- using target container: {target['name']} ({cid[:12]}) --\n")

    test_file_copy(cid)
    image_ref = test_commit(cid)
    test_image_export(image_ref)

    test_run_container()
    test_run_container_validation()

    asyncio.run(test_ws_logs(target["name"]))
    asyncio.run(test_ws_exec(cid))
    asyncio.run(test_ws_exec_resize(cid))

    test_image_remove(image_ref)

    return summarize()


if __name__ == "__main__":
    sys.exit(main())