# 开发文档

面向要改这个项目的人（包括未来的自己）。

---

## 1. 环境准备

### 后端

```bash
cd backend
uv sync --extra dev
uv run uvicorn app.main:app --reload --port 8088
```

需要 Python 3.12+（`pyproject.toml` 里 `requires-python = ">=3.12"`）。依赖用 `uv` 管理，`uv.lock` 已提交，改动依赖后记得 `uv lock`。

### 前端

```bash
cd frontend
npm install
npm run dev
```

Vite 开发服务器默认 5173，`vite.config.ts` 里把 `/api` 和 `/ws` 代理到后端 8088。

> **Windows 注意**：在 PowerShell 里要用 `npm.cmd` 而不是 `npm`，否则可能命中执行策略限制。

### 连不上 Docker 时

后端依赖 Docker 守护进程。Windows 上通过 Docker Desktop 时，把 `DOCKER_HOST` 指向暴露出来的地址（命名管道或 TCP）：

```powershell
$env:DOCKER_HOST = "npipe:////./pipe/docker_engine"
```

---

## 2. 后端结构

```
app/
├── main.py          FastAPI 实例、路由注册、启动时清理临时目录
├── config.py        环境变量 → dict（lru_cache 缓存）
├── routers/         只做 HTTP 层：解析请求、调 docker、转成响应
│   ├── containers.py  容器增删改查 + 新建运行 + commit
│   ├── images.py      镜像列表/拉取/导出/删除（含镜像源降级）
│   ├── networks.py    网络
│   ├── volumes.py     卷
│   ├── files.py       双向文件传输
│   └── ws.py          /ws/logs 与 /ws/exec
└── services/        业务逻辑，不感知 HTTP
    ├── docker.py      客户端单例、数据类型、错误抽取
    ├── files.py       tar 打包/解包、临时目录管理
    └── run_spec.py    自由文本 → docker-py 参数
```

**分层约定**：`routers` 只做转换，不写业务规则；`services` 不 import FastAPI。`run_spec.py` 是纯函数模块，没有 IO，因此最好测。

**错误处理**：`extract_error(e)` 负责把 docker-py 抛出的异常转成给用户看的中文消息。新接口抛错时统一用它，不要直接 `str(e)`。

---

## 3. 前端结构

```
src/
├── views/            四个页面：容器 / 镜像 / 网络 / 卷
├── components/
│   ├── ContainerTerminal.vue   xterm 终端（含剪贴板处理）
│   ├── ContainerLogs.vue       实时日志
│   ├── FileCopyDrawer.vue      双向传文件
│   └── RunContainerDialog.vue  新建容器（含预设）
├── api/index.ts      axios 封装 + 全部 TypeScript 类型
├── utils/error.ts    showApiError()：长错误用弹窗，短错误用 toast
└── router/index.ts
```

**约定**：
- 所有后端类型定义集中在 `api/index.ts`，组件不自己拼类型。
- 后端错误统一走 `showApiError(err, title)`，不要各写各的 `ElMessage.error`。
- 长耗时请求的超时按用途分两档，都在 `api/index.ts` 里：**拉取镜像**用 `NO_TIMEOUT`（`{ timeout: 0 }`，拉多久都等，`:55,87`）；**创建容器与打包镜像（commit）**用 `LONG_OP_TIMEOUT`（`{ timeout: 300000 }`，300 秒兜底，避免守护进程卡住时界面永远转圈，`:69,73,80-81`）。其余接口保持默认 30 秒。
- **导出镜像不走 axios**：它是 `imagesApi.saveUrl()` 拼出地址后交给 `utils/download.ts` 的 `startDownload()`——先做 30 秒 `fetch` 预检，再走裸 `<a href>` 让浏览器下载（所以既不受 axios 超时约束，也没有超时选项可配）。新增「流式下载」类功能时照这条链路走，不要再想办法塞进 axios。

---

## 4. 测试

### 后端单元测试（137 个）

```bash
cd backend
uv run pytest -q
```

**两条必须遵守的约定——违反了测试就会「假通过」：**

**① monkeypatch 的目标是 router 模块，不是 service 模块**

```python
# 对
import app.routers.containers as containers_mod
monkeypatch.setattr(containers_mod, "get_docker_client", lambda: _Client())

# 错——router 里已经 import 了引用，改 service 模块不生效
import app.services.docker as docker_mod
monkeypatch.setattr(docker_mod, "get_docker_client", lambda: _Client())
```

**② mock 必须还原 docker-py 的真实形状**

这一条是用真机 bug 换来的：

| docker-py 真实行为 | 曾经写错的 mock | 后果 |
|---|---|---|
| `Container` **没有** `.state` 属性（状态在 `attrs["State"]["Status"]`） | 给 mock 加了 `.state` | 测试全绿，上线后容器列表 500 |
| `image.tags` 是 **list** | 写成字符串 | 掩盖了标签解析问题 |
| `ports` 是 **dict**：`{"80/tcp": [{"HostIp":..., "HostPort":...}]}` | 写成 list | 端口渲染逻辑测不到 |
| `SocketIO` **没有** `settimeout()` | 调了它 | 终端一连上就断 |
| `Image.attrs["RepoDigests"]` 是 **list** | 写成字符串 | digest 解析出错 |
| `exec_create` 的 `stdin` 默认是 `False` | 想当然以为默认开 | 终端吞掉所有输入 |

结论：**mock 要照着真机行为写，不能照着「我觉得它应该长啥样」写。** 拿不准就 `docker run` 一个真容器打一下 `print(type(x), dir(x))`。

### 端到端

```bash
# 先装验证脚本自己的依赖（playwright、websockets）；缺依赖时脚本会给中文提示
pip install -r scripts/requirements-verify.txt
python scripts/e2e_verify.py     # 18 项，需要真实 Docker
```

会真实创建/启动/删除容器，跑完自动清理。**不要在生产机器上跑。**

### 浏览器验证

```bash
python scripts/ui_verify.py          # 逐页截图 + 收集页面报错 / 控制台报错 / 失败请求
python scripts/ui_clipboard_test.py  # 终端复制粘贴回归
```

用 Playwright 驱动**本机已装的 Chrome**（`channel="chrome"`），不需要下载 Chromium。截图输出在 `scripts/ui-shots/`。

> **两个已踩过的坑**：
> 1. `ui_clipboard_test.py` 必须**有头**运行。headless Chrome 不接系统剪贴板，会得到假阴性。
> 2. 判断 xterm 是否选中文本，**不能**看 `window.getSelection()`——xterm 的选区是内部实现，DOM 选择永远为空。要看 `.xterm-selection div` 的数量。
> 3. Playwright 合成按键到不了 Chrome 浏览器层的剪贴板加速键处理，所以**不能**用 `keyboard.press` 判断「原生 copy/paste 事件是否触发」。要验证剪贴板逻辑，得测自己写的代码路径。

---

## 5. WebSocket 两个坑

`/ws/logs` 和 `/ws/exec` 是全项目最容易写错的地方。

**① 阻塞调用会冻死整个事件循环**

`container.logs(follow=True)` 是**阻塞生成器**。直接在 async 函数里迭代，整个服务会卡死（不只是这个连接）。

正确做法：丢到工作线程里跑，用 `loop.call_soon_threadsafe` 把结果送回事件循环。（是 `call_soon_threadsafe` 而非 `run_coroutine_threadsafe`——回投的是一个普通回调，不是协程。）

**② 交互式终端必须显式开 stdin + tty**

```python
exec_id = client.api.exec_create(
    cid, cmd, stdin=True, tty=True,     # ← 两个都要，stdin 默认是 False
)
sock = client.api.exec_start(exec_id, socket=True, tty=True)
sock._sock.settimeout(0.2)              # ← 是 _sock，SocketIO 本身没有 settimeout
```

**③ PTY 尺寸必须回传**

终端连上后如果不调 `exec_resize`，PTY 会一直是默认的 80×24，而 xterm 按实际像素渲染——**这就是当初「终端显示乱码」的根因**。前端 `fit()` 之后要发 `{"type":"resize","cols":N,"rows":N}`。

用 `stty size` 可以在容器里验证是否生效。

---

## 6. 加一个新接口的步骤

1. 在 `routers/` 对应文件加路由；
2. 业务逻辑放 `services/`，保持 router 只做转换；
3. 错误用 `extract_error(e)`；
4. 在 `backend/tests/` 加测试，mock 按第 4 节的两条约定写；
5. `frontend/src/api/index.ts` 加类型和调用；
6. 页面接上，错误走 `showApiError`；
7. 跑 `uv run pytest -q` + `npm run build`（`vue-tsc` 会做类型检查）。

---

## 7. 一些实现细节备忘

- **镜像 ID 与 digest 的关系**：本机 Docker 用的是 containerd 镜像存储（`docker info` 显示 `driver-type io.containerd.snapshotter.v1`），此时**镜像 ID 就等于 manifest digest**，所以 `docker images --digests` 里 ID 和 DIGEST 两列一样。换到非 containerd 的机器上就不成立，所以后端读的是真实的 `attrs["RepoDigests"]`，没有硬编码。
- **端口去重**：docker-py 对同一端口会同时给出 IPv4 `0.0.0.0` 和 IPv6 `::` 两条绑定，渲染出来一模一样，看起来像重复。`_append_unique` 负责去重。
- **镜像名兜底**：容器引用的镜像被删掉后（悬空引用），`cont.image.tags` 会抛 `ImageNotFound`。`_image_name()` 依次尝试 `tags` → `attrs["Config"]["Image"]` → 短 ID。
- **自由文本解析器**：`run_spec.py` 里所有 `parse_*` 函数失败时抛 `ValueError` 且消息直接面向用户（中文），router 捕获后返回 400。Windows 路径（`C:\data:/data`）做了盘符重组，别改坏。

---

## 8. 提交规范

提交信息用 `feat:` / `fix:` / `chore:` / `docs:` 前缀，**正文说明「为什么」而不是「改了什么」**——diff 已经说明改了什么了。

改完记得：
- 跑后端测试和 `npm run build`
- 涉及界面/交互的，跑一遍浏览器验证并**亲眼看一下截图**
