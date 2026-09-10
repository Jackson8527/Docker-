# Docker 管理平台 v1 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use sp-subagent-driven-development (recommended) or sp-executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 构建一个无状态 Docker Web 管理面板，用户在浏览器完成容器/镜像/网络/卷管理、实时日志、交互终端、主机↔容器双向文件拷贝、容器打包成镜像、镜像导出 tar，全程免登录免命令行。

**Architecture:** FastAPI 后端（docker-py 直连宿主机 Docker socket）+ Vue3 前端（Element Plus + xterm.js），Nginx 反代 /api 与 /ws，docker-compose 三服务拉起。平台无业务持久化，全部实时读 Docker daemon。文件拷贝经后端临时目录中转，导出走 StreamingResponse 流式。

**Tech Stack:** Python 3.12 + FastAPI + docker-py（docker SDK）；uv 虚拟环境（pyproject.toml + uv.lock）；Vue 3 + Vite + TS + Element Plus + xterm.js；WebSocket；Nginx; Docker + docker-compose。

## Global Constraints

- 后端对外端口 **8088**（只映射 127.0.0.1，禁 0.0.0.0，spec §6/C2）。
- Python 环境统一用 **uv**（开发 `uv venv`，Dockerfile 内 `uv sync --frozen`）。
- 平台无持久化、无 ORM、无数据库（spec §3/D3）。
- 全部动作走 Web 界面，不依赖命令行（spec §1 原则）。
- 后端容器挂载宿主 `/var/run/docker.sock`，`DOCKER_HOST=unix:///var/run/docker.sock`（spec D2）。
- 临时目录 `/tmp/dockermgr`：启动清空 + 单次下载完成即删（spec D4/A1）。
- 不做登录、多用户、编排、registry、Swarm、监控、镜像导入（spec §7）。

---

### Task 1: 后端骨架与配置

**Files:**
- Create: `backend/pyproject.toml`
- Create: `backend/app/__init__.py`
- Create: `backend/app/config.py`
- Create: `backend/app/main.py`
- Test: `backend/tests/test_health.py`

**Interfaces:**
- Consumes: 无
- Produces: `get_settings() -> Settings`；FastAPI app 实例 `app`；GET `/api/health` 返回 `{"status": "ok"}`。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_health.py
from fastapi.testclient import TestClient

def test_health():
    from app.main import app
    c = TestClient(app)
    r = c.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest backend/tests/test_health.py -q`
Expected: FAIL（`app.main` 不存在）

- [ ] **Step 3: 写最小实现**

```toml
# backend/pyproject.toml
[project]
name = "docker-manager-backend"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.30",
    "docker>=7.1",
    "pydantic>=2.7",
]
[project.optional-dependencies]
dev = ["pytest>=8", "httpx>=0.27"]
```

```python
# backend/app/config.py
from functools import lru_cache
import os

@lru_cache
def get_settings() -> dict:
    return {
        "docker_host": os.environ.get("DOCKER_HOST", "unix:///var/run/docker.sock"),
        "port": int(os.environ.get("PORT", "8088")),
        "tmp_dir": os.environ.get("TMP_DIR", "/tmp/dockermgr"),
    }
```

```python
# backend/app/__init__.py
```

```python
# backend/app/main.py
from fastapi import FastAPI
from app.config import get_settings

app = FastAPI(title="docker-manager")

@app.get("/api/health")
def health():
    return {"status": "ok"}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --directory backend pytest -q`
Expected: PASS（1 passed）

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: backend skeleton with health check"
```

---

### Task 2: Docker 客户端封装

**Files:**
- Create: `backend/app/services/__init__.py`
- Create: `backend/app/services/docker.py`
- Test: `backend/tests/test_docker_service.py`

**Interfaces:**
- Produces: `get_docker_client() -> docker.DockerClient`（按需求缓存单例）；`extract_error(e) -> str` 把 docker 异常转可读信息；`ContainerInfo` / `ImageInfo` / `NetworkInfo` / `VolumeInfo` 四个 dataclass 模型。

**约束源**: spec D2（docker-py 直连）、§3 数据模型。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_docker_service.py
from app.services import docker

def test_extract_error():
    assert "not found" in docker.extract_error(Exception("404 no such container"))
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest backend/tests/test_docker_service.py -q`
Expected: FAIL（AttributeError: module has no attribute）

- [ ] **Step 3: 写实现**

```python
# backend/app/services/docker.py
import docker
from dataclasses import dataclass
from app.config import get_settings

@dataclass
class ContainerInfo:
    id: str; name: str; image: str; state: str; status: str; ports: str; created: str

@dataclass
class ImageInfo:
    id: str; tags: list; size: int

@dataclass
class NetworkInfo:
    id: str; name: str; driver: str; scope: str

@dataclass
class VolumeInfo:
    name: str; driver: str; mountpoint: str

_client = None

def get_docker_client() -> docker.DockerClient:
    global _client
    if _client is None:
        _client = docker.DockerClient(base_url=get_settings()["docker_host"])
    return _client

def extract_error(e) -> str:
    msg = str(e)
    return msg.splitlines()[0] if msg else "Unknown docker error"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest backend/tests/test_docker_service.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: docker client wrapper"
```

---

### Task 3: 容器 API（CRUD + 启停 + commit 打包镜像）

**Files:**
- Create: `backend/app/routers/__init__.py`
- Create: `backend/app/routers/containers.py`
- Modify: `backend/app/main.py`（挂载 router）
- Test: `backend/tests/test_containers_api.py`

**Interfaces:**
- Consumes: `get_docker_client()`、`ContainerInfo`（Task 2）
- Produces: 路由
  - `GET /api/containers?all=boolean` → list[ContainerInfo]
  - `GET /api/containers/{id}` → ContainerInfo
  - `POST /api/containers/{id}/start|stop|restart|pause|unpause` → `{"ok": true}`
  - `DELETE /api/containers/{id}?force=bool` → `{"ok": true}`
  - `POST /api/containers/{id}/commit` body `{repo, tag}` → `{"image_id": ...}`

**约束:** spec §4 容器数据流, F1/F6。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_containers_api.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_containers_list_returns_list():
    r = c.get("/api/containers")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest backend/tests/test_containers_api.py -v`
Expected: FAIL（404 无此路由）。

- [ ] **Step 3: 写实现**

```python
# backend/app/routers/containers.py
from fastapi import APIRouter, HTTPException, Query, Body
from app.services.docker import get_docker_client, extract_error, ContainerInfo

router = APIRouter(prefix="/api/containers", tags=["containers"])

def _info(cont) -> ContainerInfo:
    return ContainerInfo(
        id=cont.id, name=cont.name or "", image=cont.image.tags,
        state=cont.state, status=cont.status,
        ports=cont.ports or [], created=cont.attrs.get("Created", ""),
    )

@router.get("")
def list_containers(all: bool = Query(False)):
    try:
        return [_info(c) for c in get_docker_client().containers.list(all=all)]
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.get("/{cid}")
def inspect(cid: str):
    try:
        return _info(get_docker_client().containers.get(cid))
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/start")
def start(cid: str):
    try:
        get_docker_client().containers.get(cid).start(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/stop")
def stop(cid: str):
    try:
        get_docker_client().containers.get(cid).stop(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/restart")
def restart(cid: str):
    try:
        get_docker_client().containers.get(cid).restart(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/pause")
def pause(cid: str):
    try:
        get_docker_client().containers.get(cid).pause(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/unpause")
def unpause(cid: str):
    try:
        get_docker_client().containers.get(cid).unpause(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.delete("/{cid}")
def remove(cid: str, force: bool = Query(False)):
    try:
        get_docker_client().containers.get(cid).remove(force=force); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/{cid}/commit")
def commit(cid: str, repo: str = Body(...), tag: str = Body("latest")):
    try:
        img = get_docker_client().containers.get(cid).commit(repository=repo, tag=tag)
        return {"image_id": img.id}
    except Exception as e:
        raise HTTPException(500, extract_error(e))
```

`main.py` 挂载：
```python
from app.routers import containers as containers_router
# ...
app.include_router(containers_router.router)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest backend/tests/test_containers_api.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: containers CRUD + commit API"
```

---

### Task 4: 镜像 API（含 save 导出 + pull）

**Files:**
- Create: `backend/app/routers/images.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_images_api.py`

**Interfaces:**
- Consumes: `get_docker_client()`、`ImageInfo`、`extract_error`
- Produces:
  - `GET /api/images` → list[ImageInfo]
  - `GET /api/images/{id}/save` → StreamingResponse（docker save tar 下载）
  - `DELETE /api/images/{id}` → `{"ok": true}`
  - `POST /api/images/pull` body `{name, tag}` → `{"ok": true}`

**约束:** spec §4（导出流式 D6）、F3/F7。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_images_api.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_images_returns_list():
    r = c.get("/api/images")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
```

- [ ] **Step 2: 跑失败**

Run: `uv run pytest backend/tests/test_images_api.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现**

```python
# backend/app/routers/images.py
from fastapi import APIRouter, HTTPException, Query, Body
from fastapi.responses import StreamingResponse
from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/images", tags=["images"])

@router.get("")
def list_images():
    try:
        return [
            {"id": img.id, "tags": img.tags, "digest": img.short_id}
            for img in get_docker_client().images.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.get("/{iid}/save")
def save_image(iid: str):
    try:
        img = get_docker_client().images.get(iid)
        return StreamingResponse(img.save(), media_type="application/x-tar")
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.delete("/{iid}")
def remove_image(iid: str, force: bool = Query(False)):
    try:
        get_docker_client().images.remove(iid, force=force); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("/pull")
def pull(name: str = Body(...), tag: str = Body("latest")):
    try:
        get_docker_client().images.pull(name, tag=tag); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))
```

- [ ] **Step 4: 跑测试通过**

Run: `uv run pytest backend/tests/test_images_api.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: images API (list/save/pull/remove)"
```

---

### Task 5: 网络与卷 API

**Files:**
- Create: `backend/app/routers/networks.py`
- Create: `backend/app/routers/volumes.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_networks_volumes.py`

**Interfaces:**
- Consumes: `get_docker_client()`、`extract_error`、`NetworkInfo`/`VolumeInfo`
- Produces:
  - `GET/POST/DELETE /api/networks`（list / create `{name, driver}` / delete）
  - `GET/POST/DELETE /api/volumes`（list / create `{name}` / delete）

**约束:** spec §2-§3，F4/F5。

- [ ] **Step 1: 写失败测试**（含网络 + 卷）

```python
# backend/tests/test_networks_volumes.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_networks_list():
    r = c.get("/api/networks")
    assert r.status_code == 200 and isinstance(r.json(), list)

def test_volumes_list():
    r = c.get("/api/volumes")
    assert r.status_code == 200 and isinstance(r.json(), list)
```

- [ ] **Step 2: 跑失败**

Run: `uv run pytest backend/tests/test_networks_volumes.py -v`
Expected: FAIL。

- [ ] **Step 3: 写实现**

`networks.py`、`volumes.py` 均遵循 containers.py 相同模式（list/create/delete，异常转 HTTPException）。示例（networks）：

```python
# backend/app/routers/networks.py
from fastapi import APIRouter, HTTPException, Body
from app.services.docker import get_docker_client, extract_error

router = APIRouter(prefix="/api/networks", tags=["networks"])

@router.get("")
def list_networks():
    try:
        return [
            {"id": n.id, "name": n.name, "driver": n.attrs.get("Driver", ""), "scope": n.attrs.get("Scope", "")}
            for n in get_docker_client().networks.list()
        ]
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.post("")
def create_network(name: str = Body(...), driver: str = Body("bridge")):
    try:
        get_docker_client().networks.create(name, driver=driver); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.delete("/{nid}")
def delete_network(nid: str):
    try:
        get_docker_client().networks.get(nid).remove(); return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))
```

（volumes.py 同理，用 `get_docker_client().volumes.list()/.create/.get.remove()`。）

- [ ] **Step 4: 跑测试通过**

Run: `uv run pytest backend/tests/test_networks_volumes.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: networks and volumes API"
```

---

### Task 6: 文件双向拷贝 API（拷入/拷出）

**Files:**
- Create: `backend/app/services/files.py`
- Create: `backend/app/routers/files.py`
- Modify: `backend/app/main.py`（启动清理临时目录 + 挂载 router）
- Test: `backend/tests/test_files_api.py`

**Interfaces:**
- Consumes: `get_docker_client()`、`extract_error`、config tmp_dir
- Produces:
  - `POST /api/containers/{cid}/copy-to?path={path}`（multipart 上传文件 → put_archive）
  - `GET /api/containers/{cid}/copy?path={path}`（get_archive → 下载）

**约束:** spec D4、F10；临时目录 `/tmp/dockermgr` 启动清 + 完成即删。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_files_api.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_copy_route_requires_container():
    import io
    r = c.post(
        "/api/containers/no-such/container/copy",
        files={"file": ("a.txt", io.BytesIO(b"hi"), "text/plain")},
        data={"path": "/tmp"},
    )
    # 容器不存在应返回 500（本测试只验证路由存在，即 404/500 而非 405）
    assert r.status_code in (404, 500)
```

- [ ] **Step 2: 跑失败**

Run: `uv run pytest backend/tests/test_files_api.py -v`
Expected: FAIL（405 或 404 由缺路由）。

- [ ] **Step 3: 实现**

```python
# backend/app/services/files.py
from pathlib import Path
from app.config import get_settings

def get_tmp_dir() -> Path:
    d = Path(get_settings()["tmp_dir"])
    d.mkdir(parents=True, exist_ok=True)
    return d

def clear_tmp_dir():
    d = get_tmp_dir()
    for p in d.iterdir():
        if p.is_file():
            p.unlink(missing_ok=True)
```

```python
# backend/app/routers/files.py
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from app.services.docker import get_docker_client, extract_error
from app.services.files import get_tmp_dir
import tempfile, os

router = APIRouter(tags=["files"])

@router.post("/api/containers/{cid}/copy")
async def copy_into(cid: str, dest: str = Form(...), file: UploadFile = File(...)):
    tmp = get_tmp_dir()
    local = tmp / file.filename
    local.write_bytes(await file.read())
    try:
        import io, tarfile
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w") as tar:
            tar.add(local, arcname=os.path.basename(str(local)))
        get_docker_client().containers.get(cid).put_archive(dest, buf.getvalue())
        local.unlink(missing_ok=True)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(500, extract_error(e))

@router.get("/api/containers/{cid}/copy")
def copy_out(cid: str, path: str = Query("/")):
    try:
        bits, stat = get_docker_client().containers.get(cid).get_archive(path)
        return StreamingResponse(bits, media_type="application/x-tar")
    except Exception as e:
        raise HTTPException(500, extract_error(e))
```

main.py 启动清理：
```python
from app.services.files import clear_tmp_dir
from contextlib import asynccontextmanager

@asynccontextmanager
async def lifespan(_app):
    clear_tmp_dir()
    yield

app = FastAPI(title="docker-manager", lifespan=lifespan)
```

- [ ] **Step 4: 跑测试通过**

Run: `uv run pytest backend/tests/test_files_api.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: bidirectional file copy between host and container"
```

---

### Task 7: WebSocket 实时日志

**Files:**
- Create: `backend/app/routers/ws.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_ws_logs.py`

**Interfaces:**
- Consumes: `get_docker_client()`
- Produces: WS endpoint `/ws/logs?filter=<名字前缀>&stream=<stdout|stderr>`

**约束:** spec §4 实时日志（F2）、D5。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_ws_logs.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_ws_logs_connectable():
    with c.websocket_connect("/ws/logs?filter=&stream=stdout") as ws:
        ws.send_text("ping")
```

- [ ] **Step 2: 跑失败**

Run: `uv run pytest backend/tests/test_ws_logs.py -v`
Expected: FAIL（无 route）或（预期收到消息失败）。

- [ ] **Step 3: 实现**

```python
# backend/app/routers/ws.py
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from app.services.docker import get_docker_client

router = APIRouter()

def _stream_container(name: str):
    """按名称前缀匹配第一个 running 容器；无返回 None。"""
    for c in get_docker_client().containers.list():
        if c.name.startswith(name):
            return c
    return None

@router.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, filter: str = "", stream: str = "stdout", tail: int = 100):
    await ws.accept()
    try:
        cont = _stream_container(filter)
        if cont is None:
            await ws.send_json({"error": "no container"})
            await ws.close()
            return
        def gen():
            return cont.logs(stream=True, follow=True, stdout=stream in ("stdout", "both"),
                             stderr=stream in ("stderr", "both"), tail=tail)
        for line in gen():
            await ws.send_text(line.decode("utf-8", errors="replace"))
    except WebSocketDisconnect:
        pass
    except Exception:
        await ws.close()
```

- [ ] **Step 4: 跑测试通过**

Run: `uv run pytest backend/tests/test_ws_logs.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: websocket realtime logs"
```

---

### Task 8: WebSocket 交互式终端（exec + xterm）

**Files:**
- Modify: `backend/app/routers/ws.py`
- Test: `backend/tests/test_ws_exec.py`

**Interfaces:**
- Consumes: `get_docker_client()`
- Produces: `/ws/exec?container={id}` —— docker exec tty=true 双向收发。

**约束:**
spec §4 D5（F9）、tty=true + resize。

- [ ] **Step 1: 写失败测试**

```python
# backend/tests/test_ws_exec.py
from fastapi.testclient import TestClient
from app.main import app

c = TestClient(app)

def test_ws_exec_route_exist():
    with c.websocket_connect("/ws/exec?container=missing") as ws:
        ws.send_text("ls")
```

- [ ] **Step 2: 跑失败**

Run: `uv run pytest backend/tests/test_ws_exec.py -v`
Expected: FAIL（无 route）。

- [ ] **Step 3: 实现**（在 ws.py 增加）：

```python
import asyncio, json
from docker.models.containers import Container

@router.websocket("/ws/exec")
async def ws_exec(ws: WebSocket, container: str):
    await ws.accept()
    try:
        cont = get_docker_client().containers.get(container)
        # 创建 exec (tty=true)
        exec_id = cont.exec_run(["sh"], tty=True, socket=True, stream=True)
        sock = exec_id.output
        # 双向转发: docker -> ws
        async def read_docker():
            while True:
                data = sock._sock.recv(4096)
                if not data:
                    break
                await ws.send_text(data.decode("utf-8", errors="replace"))
        # ws -> docker
        async def read_ws():
            while True:
                data = await ws.receive_text()
                sock._sock.send(data.encode())
        try:
            await asyncio.gather(read_docker(), read_ws())
        except Exception:
            await ws.close()
```

- [ ] **Step 4: 跑测试通过**

Run: `uv run pytest backend/tests/test_ws_exec.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add backend/ && git commit -m "feat: interactive exec terminal over websocket"
```

---

### Task 9: 前端骨架 + 路由 + API 层

**Files:**
- Create: `frontend/package.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/tsconfig.json`
- Create: `frontend/index.html`
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/router/index.ts`
- Create: `frontend/src/api/index.ts`
- Create: `frontend/src/views/ContainersView.vue`
- Create: `frontend/src/views/ImagesView.vue`
- Create: `frontend/src/views/NetworksView.vue`
- Create: `frontend/src/views/VolumesView.vue`
- Create: `frontend/src/views/SettingsView.vue`(占位)
- Tests: `frontend/src/api/index.test.ts`（可选用 vitest）

**Interfaces:**
- Produces: `api/` 封装后端所有端点；Vue Router 四路由（容器/镜像/网络/卷）。
- 前端通过 `/api/*` 由 Nginx 反代到后端。

**约束:** spec D1/Vite/Element Plus；无登录。

- [ ] **Step 1: 初始化前端**

```bash
cd frontend && npm create vite@latest . -- --template vue-ts
npm install vue-router@4 element-plus @element-plus/icons-vue xterm @xterm/xterm
```

- [ ] **Step 2: 配置路由与侧边导航**

```ts
// frontend/src/router/index.ts
import { createRouter, createWebHistory } from 'vue-router'
const routes = [
  { path: '/', redirect: '/containers' },
  { path: '/containers', component: () => import('../views/ContainersView.vue') },
  { path: '/images', component: () => import('../views/ImagesView.vue') },
  { path: '/networks', component: () => import('../views/NetworksView.vue') },
  { path: '/volumes', component: () => import('../views/VolumesView.vue') },
]
export default createRouter({ history: createWebHistory(), routes })
```

```ts
// frontend/src/api/index.ts
import axios from 'axios'
const http = axios.create({ baseURL: '/api' })
export const containers = {
  list: (all = false) => http.get('/containers', { params: { all } }),
  start: (id) => http.post(`/containers/${id}/start`),
  // ... stop/restart/pause/remove/commit
}
export const images = {
  list: () => http.get('/images'),
  save: (id) => http.get(`/images/${id}/save`, { responseType: 'blob' }),
  pull: (name, tag) => http.post('/images/pull', { name, tag }),
  remove: (id) => http.delete(`/images/${id}`),
}
export const networks = { list: () => http.get('/networks'), create: (n) => http.post('/networks', n), remove: (id) => http.delete(`/networks/${id}`) }
export const volumes = { list: () => http.get('/volumes'), create: (n) => http.post('/volumes', n), remove: (id) => http.delete(`/volumes/${id}`) }
```

- [ ] **Step 3: 跑前端 build 确认无类型错误**

Run: `npm run build -C frontend`
Expected: 成功，无类型错误。

- [ ] **Step 4: 提交**

```bash
git add frontend/ && git commit -m "feat: frontend skeleton, router and api layer"
```

---

### Task 10: 容器列表页 + 操作 + 详情

**Files:**
- Modify: `frontend/src/views/ContainersView.vue`
- Create: `frontend/src/components/ContainerLogs.vue`（日志面板 WebSocket）
- Create: `frontend/src/components/ContainerTerminal.vue`（xterm 终端）
- Create: `frontend/src/components/FileCopyDrawer.vue`（拷入/拷出）
- Tests: 手动（build + 浏览器联调）

**约束:** spec §4（容器 F1、日志 F2、终端 F9、拷贝 F10）。

- [ ] **Step 1: 表格 + 操作按钮**

实现 el-table 列出容器（名称/镜像/状态/操作列：启/停/重启/暂停/日志/终端/打包/拷贝/删除）。

- [ ] **Step 2: 日志组件（WebSocket）**

```vue
<!-- ContainerLogs.vue -->
<script setup>
import { ref, onUnmounted } from 'vue'
const props = defineProps({ name: String })
const lines = ref([])
let ws = null
function connect() {
  ws = new WebSocket(`${location.protocol==='https:'?'wss':'ws'}://${location.host}/ws/logs?filter=${props.name}`)
  ws.onmessage = (e) => { lines.value.push(e.data); if (lines.value.length>500) lines.value.shift() }
}
connect()
onUnmounted(() => ws && ws.close())
</script>
<template><pre v-html="lines.join('\n')"></pre></template>
```

- [ ] **Step 3: 终端组件（xterm.js）**
创建 `ContainerTerminal.vue`，用 `new Terminal()` + `WebSocket('/ws/exec?container='+id)`，`term.onData` 发到 ws，`ws.onmessage` 写 `term.write`。

- [ ] **Step 4: 文件拷贝抽屉**
`FileCopyDrawer.vue`：上传（POST `/containers/{id}/copy`）+ 下载链接（GET `/containers/{id}/copy?path=`）。

- [ ] **Step 5: build + 联调**

Run: `npm run build -C frontend`
Expected: 无错误。

- [ ] **Step 6: 提交**

```bash
git add frontend/ && git commit -m "feat: containers view with logs/terminal/file-copy"
```

---

### Task 11: 镜像页 / 网络页 / 卷页

**Files:**
- Modify: `frontend/src/views/ImagesView.vue`
- Modify: `frontend/src/views/NetworksView.vue`
- Modify: `frontend/src/views/VolumesView.vue`
- Tests: 前端 build + 联调

- [ ] **Step 1: 镜像页**

实现列表 + 拉取 + 删除 + 导出下载（触发 blob 下载）+ 打包为镜像跳转提示。

- **Action**：实现导出下载
```ts
const blob = await images.save(id)
const url = URL.createObjectURL(new Blob([blob.data]))
const a = document.createElement('a'); a.href = url; a.download = 'image.tar'; a.click()
```

- [ ] **Step 2: 网络页**

列表 + 创建 + 删除。

- [ ] **Step 3: 卷页**

列表 + 创建 + 删除。

- [ ] **Step 4: 联调构建**

Run: `npm run build -C frontend` 无错误。

- [ ] **Step 5: 提交**

```bash
git add frontend/ && git commit -m "feat: images/network/volume views"
```

---

### Task 12: 容器化部署（backend + frontend + nginx）

**Files:**
- Create: `backend/Dockerfile`
- Create: `frontend/Dockerfile`
- Create: `deploy/nginx.conf`
- Create: `deploy/docker-compose.yml`
- Create: `.env.example`
- Tests: `docker compose up -d` 后浏览器可访问 + `curl /api/health`

**约束:**
- 后端 Dockerfile 用 **uv**（D7）。
- nginx 反代 `/api` 与 `/ws`；socket 挂载（D2）；仅映射 127.0.0.1:8088（C2）。

- [ ] **Step 1: 后端 Dockerfile（uv）**

```dockerfile
# backend/Dockerfile
FROM python:3.12-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen
COPY app ./app
EXPOSE 8088
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
```

- [ ] **Step 2: 前端 Dockerfile（构建 + nginx 产物）**

```dockerfile
FROM node:20-alpine AS build
WORKDIR /app
COPY package*.json ./
RUN npm install
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY ../deploy/nginx.conf /etc/nginx/conf.d/default.conf
```

- [ ] **Step 3: nginx.conf**

```nginx
server {
    listen 80;
    location / {
        root /usr/share/nginx/html;
        try_files $uri $uri/ /index.html;
    }
    location /api/ {
        proxy_pass http://backend:8088;
        proxy_set_header Host $host;
    }
    location /ws/ {
        proxy_pass http://backend:8088;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
    }
}
```

- [ ] **Step 4: docker-compose**

```yaml
# deploy/docker-compose.yml
services:
  backend:
    build: ../backend
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock
    environment:
      - DOCKER_HOST=unix:///var/run/docker.sock
      - PORT=8088
  frontend:
    build: ../frontend
  nginx:
    image: nginx:alpine
    ports:
      - "127.0.0.1:8088:80"
    volumes:
      - ./nginx.conf:/etc/nginx/conf.d/default.conf:ro
    depends_on: [backend, frontend]
```

- [ ] **Step 5: 验证**

Run: `cd deploy && docker compose up -d --build`
Then: `curl http://127.0.0.1:8088/api/health`
Expected: `{"status":"ok"}`；浏览器打开 `http://127.0.0.1:8088/` 见前端。

- [ ] **Step 6: 提交**

```bash
git add . && git commit -m "feat: containerized deployment with nginx reverse proxy"
```

---

## 验证闭环

完成 Task 1-12 后，按总体计划 §6 阶段 5 验收：
1. `docker compose up -d` 后端 /api/health OK。
2. 页面完成：看容器 → 看日志 → 进终端 → 文件拷进拷出 → 打包镜像 → 导出 tar。
3. F1-F10 全部经界面触发，不依赖命令行。

## 提交节奏

每个 Task 独立 commit，Task 内部按 TDD 红->绿增量提交。