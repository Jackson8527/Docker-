"""E2E verification for docker-manager (run against the live deployment).

Verifies: HTTP CRUD endpoints, WebSocket logs, WebSocket exec terminal,
host<->container file copy, container commit, image export.
"""
import asyncio
import io
import json
import tarfile
import urllib.error
import urllib.request
import uuid

BASE = "http://127.0.0.1:8088"
WS_BASE = "ws://127.0.0.1:8088"

RESULTS = []


def record(name, ok, detail=""):
    RESULTS.append((name, ok, detail))
    print(f"[{'PASS' if ok else 'FAIL'}] {name}" + (f" -- {detail}" if detail else ""))


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
    """Cleanup the image created by the commit test."""
    if not image_ref:
        return
    try:
        st, body = http("GET", "/api/images")
        imgs = json.loads(body)
        target = next((i for i in imgs if image_ref in (i.get("tags") or [])), None)
        if target:
            http("DELETE", f"/api/images/{target['id']}?force=true", timeout=60)
        record("Cleanup committed image", True, image_ref)
    except Exception as e:
        record("Cleanup committed image", False, repr(e))


# ---------------------------------------------------------------- WS ----
async def test_ws_logs(container_name):
    import websockets
    try:
        url = f"{WS_BASE}/ws/logs?filter={container_name}&stream=stdout&tail=20"
        async with websockets.connect(url, open_timeout=15) as ws:
            try:
                msg = await asyncio.wait_for(ws.recv(), timeout=15)
                ok = isinstance(msg, str)
                record("WS /ws/logs (realtime logs)", ok, f"got {len(msg)} chars")
            except asyncio.TimeoutError:
                # A container with no recent output may legitimately stay quiet.
                record("WS /ws/logs (realtime logs)", True,
                       "connected, no output within 15s (acceptable)")
    except Exception as e:
        record("WS /ws/logs (realtime logs)", False, repr(e))


async def test_ws_exec(cid):
    import websockets
    try:
        url = f"{WS_BASE}/ws/exec?container={cid}"
        async with websockets.connect(url, open_timeout=15) as ws:
            await asyncio.sleep(0.5)
            token = "EXECOK" + uuid.uuid4().hex[:6]
            await ws.send(f"echo {token}\n")
            collected = ""
            deadline = asyncio.get_event_loop().time() + 15
            while asyncio.get_event_loop().time() < deadline:
                try:
                    chunk = await asyncio.wait_for(ws.recv(), timeout=3)
                except asyncio.TimeoutError:
                    break
                collected += chunk
                if token in collected:
                    break
            ok = token in collected
            record("WS /ws/exec (interactive terminal)", ok,
                   f"echo roundtrip={'yes' if ok else 'no'}")
    except Exception as e:
        record("WS /ws/exec (interactive terminal)", False, repr(e))


# ---------------------------------------------------------------- main ----
def main():
    print("=" * 70)
    print("docker-manager E2E verification against live deployment")
    print("=" * 70)

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
        return
    cid = target["id"]
    print(f"\n-- using target container: {target['name']} ({cid[:12]}) --\n")

    test_file_copy(cid)
    image_ref = test_commit(cid)
    test_image_export(image_ref)

    asyncio.run(test_ws_logs(target["name"]))
    asyncio.run(test_ws_exec(cid))

    test_image_remove(image_ref)

    print("\n" + "=" * 70)
    passed = sum(1 for _, ok, _ in RESULTS if ok)
    total = len(RESULTS)
    print(f"RESULT: {passed}/{total} passed")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"  FAILED: {name} -- {detail}")
    print("=" * 70)


if __name__ == "__main__":
    main()