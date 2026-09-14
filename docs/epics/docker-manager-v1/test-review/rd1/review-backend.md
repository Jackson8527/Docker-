# CDM Phase 4.6 正式代码审查 — 后端透镜（review-backend）

> Epic：`docker-manager-v1`
> 审查范围：`c689f71a52f9cffb89c80efd706149b3d95307ec..81490291321b22d06aec0cfbeff05f06bb7905c2`（21 个编码 commit、63 文件、+9859/-4）
> 审查者透镜：**后端**（`backend/**`、`.gitignore`、部署配置中与后端契约相关的部分）；前端 Vue/TS 归另一透镜，仅当契约问题出在后端一侧时报告。
> 审查时间：2026-09-11
> 审查方式：子代理独立审查（未参与编码，不采信 README/注释/commit message 的自我声明，全部结论以代码 + 实测为证据）
> OCR 预扫：**未纳入（后台未完成）**——`docs/epics/docker-manager-v1/ocr/` 下仅存在 `BASE_SHA` 与 `ocr-background.md`，写报告前两次检查均无 `ocr-preview.md/.json`。

## 0. 审查方法与实跑证据

| 项 | 命令 | 结果 |
|----|------|------|
| 后端单测 | `cd backend; uv run --frozen pytest -q`（`UV_CACHE_DIR` 指向工作区内，因沙箱禁止写 `%LOCALAPPDATA%\uv\cache`） | **66 passed, 2 warnings in 2.55s** ✅ |
| 锁文件一致性 | `uv lock --check` | **exit 0**（`pyproject.toml` 与 `uv.lock` 一致，`--frozen` 可解）✅ |
| 全量 diff 阅读 | `git diff BASE..HEAD`（后端全部文件逐行读完，非抽查） | ✅ |
| docker-py 真实形状核验 | 直接阅读 `backend/.venv/Lib/site-packages/docker/**`（docker-py **7.2.0**，与 `uv.lock:195-196` 一致） | ✅（见 §4.T4、§6） |
| E2E / `docker build` | `docker version` | ❌ **无法执行**：本沙箱访问 `npipe:////./pipe/dockerDesktopLinuxEngine` 被拒（permission denied），无 daemon、无已部署栈 |

> 说明：凡引用 `docker/...` 的行号，均指本机 venv 内安装的 docker-py 7.2.0 源码（`backend/.venv/Lib/site-packages/docker/`），不属于被审 diff，仅作为「真机形状」的判据。

---

## 1. Plan alignment（对照 spec/plan）

**Verdict: ❌（存在未关闭的 🟡 2 条；另有 7 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | `backend/app/routers/ws.py:88-101`（配合 `frontend/src/components/ContainerLogs.vue:99-101`） | **spec §6 对「长日志/高并发 WS」的三项对策中「消息节流」整体缺失**：后端每收到一行日志就 `loop.call_soon_threadsafe` → `asyncio.ensure_future(_safe_send(...))`（`ws.py:32-46`），无节流/批量/背压，客户端消费慢或无消费时发送任务与帧缓冲无上限；前端每条消息直接 `append()` 并 `await nextTick()` 触发一次渲染。刷屏容器（`while true; do echo x; done`）下会放大内存与延迟。「断线重连」前端已实现（`ContainerLogs.vue:102-140`），「防抖」无。 | **HARD** | `spec.md:113`（风险表对策：消息节流、断线重连、防抖） |
| 🟡 | `backend/app/routers/images.py:95-101` | **镜像导出未保留仓库名/标签**：`img.save()` 默认 `named=False`，docker-py 文档明确「tarball 不保留 repository/tag 信息」（docker-py `models/images.py:80-90`）→ 导出的 tar 在**另一台机器** `docker load` 后成为 `<none>:<none>`，需手工重打标签，与 F7「导出归档」的复用意图不符。本机验证发现不了：E2E 只断言 tar 里有 `manifest.json`（`scripts/e2e_verify.py:180-184`），且本机 Docker 用 containerd 镜像存储时镜像 ID 恰等于 manifest digest（与 epic README「经验记录 2 · 巧合正确」同型失误）。修法：`img.save(named=True)`。 | JUDGEMENT | `spec.md:90`（§4 导出流）、`scope.md:30`（F7）、`plan.md:T4`（plan 示例同样未加 `named=True`） |
| 🟢 | `backend/app/routers/files.py:31-37` | **拷出路径偏离 spec D4 的中转设计**：spec 规定「`get_archive()` → 后端临时目录 → 前端下载」且「单次下载完成后即删对应文件」；实现改为把 daemon 的 tar 流直接 `StreamingResponse` 给客户端，临时目录与「完成即删」在拷出路径上不存在（**实现更省盘、也更优**，但 spec 文字未同步修订，`spec.md:73` 仍把「导出缓冲」列为临时目录用途）。 | **HARD** | `spec.md:44`、`spec.md:49`、`spec.md:73` |
| 🟢 | `backend/app/routers/networks.py`（无 `GET /api/networks/{nid}`） | scope F4 要求网络管理含**详情**；实现只有 list/create/delete，plan T5 的 Interfaces 也只列了这三个 → **计划本身欠范围**，不能只记在执行侧。 | **HARD** | `scope.md:27`、`plan.md:T5`（Interfaces 437-438） |
| 🟢 | `backend/app/routers/volumes.py:8-20` | scope F5 要求卷管理含**使用情况**；实现只返回 `name/driver/mountpoint`，无 size/引用容器数等使用信息，plan T5 同样未列 → 计划欠范围。 | **HARD** | `scope.md:28`、`plan.md:T5` |
| 🟢 | `backend/app/services/run_spec.py`（整文件 161 行）+ `routers/containers.py:11-21,102-151` + `tests/test_run_container.py`（284 行）+ 前端对话框/预设 | **蔓延**：plan Task 3 的接口清单只有 list/detail/start/stop/restart/pause/unpause/delete/commit，**没有「从镜像创建容器」**；整条 R4 链路（自由文本解析器 + `POST /api/containers` + 前端对话框/常用镜像预设）超出 plan。**但** spec §4 数据流表写了「容器 CRUD」，且 epic README 记录 R4 为用户主动要求 → 记为蔓延，不判违规；建议回写 plan/spec（`spec.md:130` 仍把「启动配置编辑」列为 v1.1）。 | JUDGEMENT | `plan.md:T3`（Interfaces 204-208）、`spec.md:83`（部分背书）、`spec.md:130` |
| 🟢 | `backend/app/config.py:6,15-19` + `routers/images.py:12-70,89-92` + `.env.example` + `deploy/docker-compose.yml:14` | **蔓延**：spec D3 明确「唯一常量：`config.py`（DOCKER_HOST、临时目录、端口 8088）」，实现新增第 4 个配置项 `IMAGE_MIRRORS` 与约 70 行镜像源降级/重打标签策略（R3 的真实环境修复，动机成立）。副作用需写进设计：镜像来源变成第三方镜像源后仍被静默重打为官方名（`images.py:161-174`），UI 只显示 `mysql:latest`，用户无法区分。 | **HARD** | `spec.md:39`（D3）、`spec.md:125`（§7 排除 registry） |
| 🟢 | `deploy/docker-compose.yml:1-27`、`frontend/Dockerfile`、`frontend/nginx.conf` | **与 spec §5/plan T12 不一致（属合理偏离）**：spec/plan 要求三服务（backend / frontend / nginx，`deploy/nginx.conf`），实现把 nginx 并进 frontend 镜像成二服务。功能等价，且修掉了 plan 片段里 `COPY ../deploy/nginx.conf`（构建上下文之外，照抄必失败）——建议把 spec §5 改为二服务并说明理由。 | JUDGEMENT | `spec.md:101`、`plan.md:T12`（Step 2 第 1005 行） |
| 🟢 | `backend/a.txt:1` | 仓库内杂物文件（2 字节，内容 `hi`），无任何代码引用；由 `tests/test_files_api.py:27-28` 把临时目录指到 CWD 后写入、并被提交进 `e4f5fff`（蔓延）。根因与修复见 §4.T2。 | JUDGEMENT | 无明文依据（证据：`git log --all -- backend/a.txt` → `e4f5fff`） |
| 🟢 | `docs/epics/docker-manager-v1/README.md:74`（另 `:35-48`） | **文档与代码不一致**：README「未完成项」仍把 `.gitignore` 忽略 `uv.lock` 记为「**待修复**」，但该问题在 HEAD 已修复（见 §5.1 独立核实）。同一提交 `8149029` 里既修了问题又保留了「待修复」的说法。 | JUDGEMENT | 无 spec/plan 依据；证据见 §5.1 |

**亮点（Plan alignment）**
- 12 个 Task 的对外接口基本逐条落地，路由前缀/方法/参数与 plan 的 Interfaces 段一致（含 `POST /{cid}/commit` 的 `repo`+`tag` Body 形状、`/api/images/{iid}/save`、`/api/containers/{cid}/copy` 的 `dest`+`file` multipart）。
- `spec.md:111` 的安全对策被**逐字**执行：compose 只把 nginx 绑到 `127.0.0.1:8088`（`docker-compose.yml:23-25`），backend 仅 `expose: 8088` 不发布宿主端口（`:16-17`）。
- 全局约束「无持久化、无 ORM、无数据库」「无登录」在代码中确实成立（后端无任何存储层，`main.py` 无 auth 依赖）。

---

## 2. Code quality

**Verdict: ⚠️（无 🔴/🟡；7 条 🟢，均为可延后的小项）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟢 | `backend/app/routers/files.py:17-28` | **拷入的错误边界与内存放大**：① `local.write_bytes(await file.read())`（:19）在 `try` **之外**，写盘失败（磁盘满/权限）会以 FastAPI 通用 500 + 堆栈返回，前端拿不到中文原因，且此时上传内容已读进内存；② `local.unlink()` 不在 `finally`（:25），任何异常都留下残留文件；③ 同一份数据在内存里存在三份（`await file.read()` 的 bytes → `io.BytesIO` 里的 tar → docker-py `_put(data=...)` 的请求体，`put_archive` 只接受 bytes，见 docker-py `api/container.py:970-992`），1GB 上传约 2-3GB RSS（README 已知限制有提及，nginx 侧 `client_max_body_size 0` 无上限）；④ 临时文件名只取 `basename`（:18），同名并发上传会互相覆盖（spec 的单用户前提下降级为可接受）。 | JUDGEMENT | `spec.md:49`（失败残留由启动清兜底，故③④不判违规） |
| 🟢 | `backend/app/routers/containers.py:82-88` + `services/docker.py:12-13` | **`state` 与 `status` 恒等，模型字段冗余、兜底分支不可达**：docker-py 的 `Container.status` 定义就是 `attrs["State"]["Status"]`（`docker/models/containers.py:61-67`），因此 `state_obj.get("Status","") or cont.status` 的后半段永远不生效，两个字段在 API 响应里始终相同（前端 `ContainerRow` 也同时声明了二者）。反过来说：`state_obj.get(...)` 只在 `State` 是 dict 时成立，若改用 docker-py 的 `sparse=True`（list 响应里 `State` 是字符串）就会 `AttributeError` → 整个容器列表 500；直接复用 `cont.status` 才是形状无关的写法。 | JUDGEMENT | 无明文依据（docker-py `containers.py:61-67` 实测） |
| 🟢 | `backend/app/config.py:6` / `.env.example:7` / `deploy/docker-compose.yml:14` | **DRY**：镜像源默认值 `docker.m.daocloud.io,docker.1panel.live` 三处硬编码，改一处必漏两处；建议 compose/`.env.example` 只留占位，默认值单一来源于 `config.py`。 | JUDGEMENT | 无明文依据 |
| 🟢 | `backend/app/services/docker.py:43-50` | **近乎死代码的兜底 + 无锁单例**：`docker.from_env()` 本身就读取进程环境里的 `DOCKER_HOST`（与 `get_settings()["docker_host"]` 同源），且它在构造时即会 `version()` 急连接；失败后用同一个地址再建一个 client 只是把「急切失败」变成「懒失败」，排查信息还更差。`_client` 全局赋值无锁，并发首调理论上可建出两个 client（实际无害）。 | JUDGEMENT | `plan.md:T2`（plan 原写法是直接用 `base_url`，实现改为 from_env 优先） |
| 🟢 | `backend/app/routers/containers.py:154-159,207-213`；`networks.py:33-39`；`volumes.py:32-38`；`images.py:104-110` | **not-found 一律 500**：容器/镜像/网络/卷不存在时全部走 `except Exception → HTTPException(500, ...)`，DELETE 一个不存在的资源也返回 500（REST 语义应 404）。测试把 500 固化为预期（`tests/test_files_api.py:35`）。前端只展示 `detail`，影响仅限于语义与可观测性。 | JUDGEMENT | `plan.md:T3:T5`（plan 示例即如此） |
| 🟢 | `backend/app/routers/images.py:113-124` | **`name` 里带 tag 时静默拉错 tag**：端点默认 `tag="latest"`，而 docker-py 的 `pull` 先解析 `repository` 里的 tag、再用 `tag = tag or image_tag or 'latest'`（docker-py `api/image.py:395-396`）→ `POST /api/images/pull {"name":"mysql:8"}` 实际拉的是 `mysql:latest`，响应还回显 `mysql:8:latest`（`_canonical` 会保留 `:8`，`images.py:52-57`）。前端会把 `mysql:8` 拆成 name+tag（`ImagesView.vue:146-153`）故 UI 路径不受影响，仅直连 API 时误导。建议：同时给 `name` 与 `tag` 时以 `tag` 为准并显式剥离 `name` 中的 tag。 | JUDGEMENT | 无明文依据（docker-py `api/image.py:395-396` 实测） |
| 🟢 | `backend/app/routers/ws.py:59,83-86,208-209` | **入参校验缺失/单帧异常终止会话**：① `/ws/logs` 的 `stream` 未校验，非法值会让 `stdout`/`stderr` 同时为 False，静默返回空流（用户看到「暂无日志」而非错误）；② `/ws/exec` 的 `int(payload.get("cols") or 0)` 遇到非数字会抛 `ValueError`，被外层 `except Exception` 收尾 → **一帧坏消息直接关掉整个终端会话**（缩进层级把它排除在 `try/except` 之外即可）。 | JUDGEMENT | 无明文依据 |

**亮点（Code quality）**
- 错误信息统一走 `extract_error()` 且只取首行（`services/docker.py:53-55`），并把 docker 的英文错误翻译成可操作的中文（`containers.py:124-144` 的 404/409 分支），是本 diff 里质量最高的一段错误处理。
- 纯函数被刻意抽成可测单元且边界完备：`services/run_spec.py` 的四个解析器覆盖了空值、超范围、非法协议、Windows 盘符、命名卷等（`tests/test_run_container.py:24-149`）。
- `_format_ports` 处理了 docker-py「一个端口同时给出 IPv4 `0.0.0.0` 与 IPv6 `::` 两条绑定」的真实形状并去重（`containers.py:29-50`），`_image_name` 处理了「容器指向已被删除的镜像」的悬空引用（`containers.py:53-73`）——两处都有对应用例。

---

## 3. Architecture

**Verdict: ❌（1 条未关闭 🟡；3 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | `backend/app/routers/ws.py:127-231`（`/ws/exec`）、`ws.py:58-124`（`/ws/logs`）、`backend/app/routers/containers.py:162-204` | **跨站 WebSocket 劫持（CSWSH）与跨站简单请求副作用，spec §6 的对策对此无效**：两个 WS 端点均不校验 `Origin`/`Referer`，HTTP 端点无 CSRF 防护。浏览器**不会**用 CORS 阻止 WebSocket 握手，也不会阻止「简单请求」（`POST /api/containers/{id}/stop|restart|pause|unpause` 无 body、无自定义头，可直接被跨站发出，仅响应不可读）。因此：用户在面板运行期间访问任意恶意网页 → 该页可 `new WebSocket("ws://127.0.0.1:8088/ws/exec?container=<被管理的容器>")` 拿到**交互式 shell**，再 `exec` 进 `dockermgr-backend` 自身容器（它挂着 `docker.sock`）即等于宿主机 root。spec §6 的对策是「仅映射 127.0.0.1 + 文档提示」——那只挡住网络层，挡不住浏览器中介。建议（成本很低）：校验 `Origin` 白名单（`127.0.0.1:8088`/`localhost:8088`）+ 启动时生成随机 token 由 nginx 注入 Cookie/URL。**判为 🟡 而非 🔴 的理由**：epic 明确接受「无登录 + 本机自用」的威胁模型（`spec.md:36`、`docs/deployment.md:137`），且需诱导用户访问恶意页面；若后续把它当生产系统用，应升级为 🔴。 | JUDGEMENT | `spec.md:111`、`spec.md:36`（对策已按字面实现，但覆盖不到这一类） |
| 🟢 | `backend/app/routers/images.py:12-70`、`routers/containers.py:29-73` | **分层**：约定的方向是 `routers/` 只做 HTTP 编排 → `services/` 封装 docker-py 与领域逻辑。按此口径，`images.py` 里的注册表策略（不可达判定、Hub 引用判定、镜像源重打标签，约 70 行）与 `containers.py` 里的模型映射（`_format_ports`/`_image_name`）都属于领域逻辑，落在 router 层。**减责说明**：plan T3/T5 的示例代码本身就把 docker-py 调用写在 router 里，T5 甚至明文写「遵循 containers.py 相同模式」，因此这是计划确立的模式，而 R3 新增的镜像源策略是把它推过头的那一步。 | JUDGEMENT | `plan.md:T3`（Step 3 示例）、`plan.md:T5`（「均遵循 containers.py 相同模式」） |
| 🟢 | `backend/app/routers/containers.py:94-99` + `services/docker.py`（`cont.image`） | **`GET /api/containers` 每次 2N+1 次 daemon 往返**：docker-py 的 `containers.list()` 默认 `sparse=False`，会对**每个**容器再 `get()` 一次（docker-py `models/containers.py:1015-1024`）＝ 1+N 次；`_image_name` 又对每个容器访问 `cont.image`，触发 `client.images.get()` ＝ 再 +N 次（docker-py `containers.py:36-44`）。N=30 时约 61 次往返/次列表刷新。修法：优先读 `cont.attrs["Config"]["Image"]`（0 次额外调用），仅在为空时回退到 `.image`。个人自用规模下不致命，故 🟢。 | JUDGEMENT | 无明文依据（docker-py 源码实测） |
| 🟢 | `backend/app/routers/ws.py:100-101,188-189`；`Dockerfile:15`（无 `--workers`） | **并发上限未定义**：uvicorn 单进程单事件循环（compose 未设 workers），每个 WS 连接各占 1 个守护线程（日志 1 个、终端 1 个），无连接数/线程数上限。与 §1.P1（无背压）同根因：日志刷屏 + 多标签页会把「单循环」推成瓶颈。 | JUDGEMENT | `spec.md:113` |

**亮点（Architecture）**
- 事件循环纪律在 R1 后被认真处理：`/ws/logs` 把阻塞的 docker-py 生成器搬到工作线程并用 `loop.call_soon_threadsafe` 回投（`ws.py:79-101`），`/ws/exec` 的 socket 读也在线程里、超时 0.2s 保证可中断（`ws.py:166-189`），而不是用 `asyncio.sleep` 轮询假装异步。
- 除 `copy_into` 外，**所有** HTTP 处理器都是同步 `def`（FastAPI 自动丢线程池），只有需要 `await file.read()` 的那一个写成 `async def` —— 说明作者理解这条规则（另见 §5.R1，那一个正是唯一失守点）。
- 流式导出确实流式：`img.save()` → `_stream_raw_result` 2MB 分块（docker-py `api/image.py:38-39`），`StreamingResponse` 对同步生成器走线程池，不占内存、不占事件循环（`spec.md:112` 的内存风险对策成立）。
- 请求发出即校验（`save_image` 在 `try` 内调用 `img.save()`，错误能在响应头前转成 500）、导出与拷出都在错误路径上保持 4xx/5xx 语义。

---

## 4. Testing

**Verdict: ❌（2 条未关闭 🟡；2 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | `backend/tests/`（全目录） | **端点层覆盖缺口：14 个端点零单测**——`POST /{cid}/start|stop|restart|pause|unpause`（5）、`DELETE /api/containers/{cid}`、`POST /{cid}/commit`（**F6 主线**）、`GET /api/containers/{cid}`、`GET /api/images/{iid}/save`（**F7 主线，且是流式**）、`DELETE /api/images/{iid}`、`GET /api/containers/{cid}/copy`（**拷出，F10 的一半**）、`GET /api/images/pull/mirrors`、网络与卷的 create/delete（4）。现有 66 个用例里，端点级测试只覆盖 health、容器 list/create、images list/pull、networks/volumes list 与一个 copy 的失败路径；其余体量来自解析器/格式化纯函数的单元测试。E2E 脚本（`scripts/e2e_verify.py`）覆盖了 commit/save，但需真机且在本环境无法复跑（§0）。**减责说明**：plan 每个 Task 的 Step 1 只要求「路由存在」级别的测试，故不判硬违规。 | JUDGEMENT | `plan.md:T3`/`T4`/`T7`（Step 1 示例测试） |
| 🟡 | `backend/tests/test_files_api.py:26-28`（产物 `backend/a.txt:1`） | **测试污染仓库工作目录，并把产物提交进了版本库**：用例把 `get_tmp_dir` monkeypatch 成 `Path(".")`，于是 `files.py:19` 把上传内容写到 **pytest 的 CWD（= `backend/`）**；又因为该用例里 `put_archive` 必抛（:16-17），`files.py:25` 的 `unlink` 永不执行 → **每次跑测试都会在仓库里留下 `backend/a.txt`**。文件已被提交进 `e4f5fff`（内容 `hi` 与该用例上传的 `b"hi"` 一致），`git status` 因此长期「干净地」藏着一个不该存在的跟踪文件。修法：用 pytest 的 `tmp_path` fixture，并在断言前/后清理。 | JUDGEMENT | 无明文依据；证据：`git log --all -- backend/a.txt` → `e4f5fff`；`backend/a.txt` 内容 = 测试上传内容 |
| 🟢 | `backend/tests/test_ws_logs.py:22-29` | **断言被 `except Exception: pass` 整体吞掉**：`ws.receive_json()` 与 `msg.get("error") == "no container"` 的断言位于 `try` 内，任何异常（含断言失败之外的一切）都被 pass，用例实际上只证明「路由可达」。这是本套测试里唯一有「假绿」风险的写法（plan T7 的示例测试同样如此）。 | JUDGEMENT | `plan.md:T7`（Step 1 示例） |
| 🟢 | `backend/tests/test_containers_api.py:14-35`、`test_ws_exec.py:17-33` | **mock 形状核验：结论是「对的」，但覆盖不到 sparse 形状**。逐条对照 docker-py 7.2.0 实测：`Container` 确实**没有** `.state`（`models/containers.py:61-67` 只有 `status`），`.image.tags` 是 list，`.ports` 是 `{container_port: [bindings]}` dict，`SocketIO` 包装器无 `settimeout/setblocking`（`Dockerfile`-side 代码用 `_sock`，`ws.py:23-29`）；且 mock 用 dict 形状的 `attrs["State"]` 是**正确**的——`containers.list()` 默认 `sparse=False` 会对每个容器 inspect（`models/containers.py:1015-1024`），真实对象就是 inspect 形状。遗留缺口：没有任何用例覆盖 `sparse=True` 的形状（那会让 `containers.py:82-88` 抛 AttributeError，见 §2.Q2）。 | JUDGEMENT | 无明文依据（docker-py 源码实测） |

**实跑结果**
- `cd backend && uv run --frozen pytest -q` → **66 passed, 2 warnings in 2.55s**（与 README/`docs/epics/docker-manager-v1/README.md:100` 的「66 passed」一致，非自我声明的采信，是本次实测）。
- 唯一环境妥协：沙箱禁止写 `%LOCALAPPDATA%\uv\cache`，需 `UV_CACHE_DIR` 指向工作区内；不影响 `--frozen` 语义（`uv lock --check` 也 exit 0）。
- **跑不起来的部分**：`scripts/e2e_verify.py`、`scripts/ui_verify.py`、`scripts/ui_clipboard_test.py`、`docker build` / `docker compose up` —— 本沙箱连接 Docker Desktop 命名管道被拒（permission denied），无 daemon、无 8088 上的已部署栈。因此「18/18 E2E」「浏览器 0 报错」只能视为**编码者提供的证据**，本次未能独立复核（见 §6）。

**亮点（Testing）**
- **专门为事件循环阻塞写了真机级回归测试**（`tests/test_ws_logs_blocking.py`）：起真实 uvicorn、真实 WebSocket、「空闲 6 秒期间 `/api/health` 必须 <3s 返回」，并明确注释「mocked in-memory generator 无法复现该缺陷」。这是本套测试里最有价值的一个用例，直击历史事故。
- 测试断言偏向**行为**而非冒烟：`test_exec_create_uses_stdin_true`（防「终端丢弃输入」回归）、`test_exec_resize_is_forwarded_to_pty`（断言 `height=rows/width=cols` 顺序）、`test_containers_list_survives_dangling_image_reference`、`test_format_ports_collapses_ipv4_ipv6_duplicates`、pull 的「只有网络失败才走镜像源」等，每条都锚定一个真实缺陷。
- `test_ws_exec.py` 用真实 `socket.socketpair()` 打通「WS → docker socket → WS」双向数据路径，而不是 mock 掉整条链路。

---

## 5. Production

**Verdict: ❌（1 条未关闭 🟡；3 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | `backend/app/routers/files.py:16-25` | **`async def` 处理器里做同步阻塞 I/O —— R1 事故的同类残留，且是唯一一处**。`copy_into` 是 `async def`，但内部：`local.write_bytes(...)`（:19）同步写盘、`tarfile` 打包（:21-23）同步 CPU、`get_docker_client().containers.get(cid).put_archive(...)`（:24）同步阻塞直到**整个 tar 上传到 daemon 完成**。期间 uvicorn 的**唯一**事件循环被冻结：所有 HTTP 请求（含 `/api/health`）与所有 WebSocket 连接的收发（日志、终端）一起卡住，nginx 侧表现为 499/504；上传 1GB 级文件（nginx `client_max_body_size 0`，`frontend/nginx.conf:22`）可冻结数十秒到数分钟，与 `ws.py:59-68` 注释里记录的历史事故是同一机制（区别仅在于「有界」，因此判 🟡 而非 🔴；若按生产标准应升级）。修法（任选其一）：整段用 `await asyncio.to_thread(_blocking_part)` 包住；或把处理器改回同步 `def`（FastAPI 自动走线程池，`UploadFile.file` 可直接同步读）。 | **HARD** | `backend/app/routers/ws.py:59-68`（项目自身明文写下的「async 处理器内不得阻塞事件循环」规则）、`spec.md:113`（高并发 WS 风险） |
| 🟢 | `backend/Dockerfile:2,8-12` | ① `FROM ghcr.io/astral-sh/uv:latest` **未固定版本**，与 spec D7 强调的「锁文件复现」精神不符（依赖锁住了，构建工具没锁），也是供应链风险点；② `COPY app ./app`（:9）排在 `RUN uv sync`（:12）之前，导致**任何源码改动都会让依赖安装层缓存失效**，重建即重装全部依赖（`docs/deployment.md` 的「前端可单独重建省时间」在 backend 上不成立）。 | JUDGEMENT | `spec.md:60`（D7 只约束依赖、未约束基镜像，故非硬违规） |
| 🟢 | `deploy/docker-compose.yml:1-27` | 两个 service 都没有 `restart:` 策略与 `healthcheck`：宿主机重启 / docker 重启后面板不会自动拉起；`depends_on: backend` 不等后端就绪，nginx 起后到后端起前会有短暂 502（`proxy_read_timeout 3600s` 不覆盖连接失败）。spec §5/§6 未要求，属部署健壮性建议。 | JUDGEMENT | `spec.md:101` |
| 🟢 | `backend/app/services/files.py:12-16` | `clear_tmp_dir()` 只删文件（`if p.is_file()`），不删子目录，与 spec「启动时**清空**该目录」在最坏情况下不完全一致（当前代码不会在临时目录下建子目录，风险极低）；另外全项目没有 logging 配置，`logger.exception`/`logger.debug`（`ws.py:12,96,115,186,217,221`）依赖 Python last-resort handler 才能出到 stderr，`logger.debug` 实际不可见——排障时容易丢失现场。 | JUDGEMENT | `spec.md:49` |

### 5.1 必须独立核实的已知事实 1：`.gitignore` 忽略 `uv.lock` → 全新 clone 构建失败

**结论：在 HEAD 上已修复，不构成未决缺陷（严重度：无 / 已关闭）**；但文档仍写「待修复」（`docs/epics/docker-manager-v1/README.md:74`，见 §1 最后一行 🟢）。

独立核实证据（全部为本机实测，非采信自述）：

| 检查 | 命令 | 结果 |
|------|------|------|
| `.gitignore` 是否仍忽略 | `git check-ignore -v backend/uv.lock` | **exit 1 = 未被忽略**；`.gitignore:5-8` 已把 `uv.lock` 一行换成「刻意提交」的注释说明 |
| 是否被 git 跟踪 | `git ls-files backend/uv.lock` | `backend/uv.lock`（**已跟踪**，183,446 字节） |
| 与 Dockerfile 的 COPY 是否对得上 | `backend/Dockerfile:8` | `COPY pyproject.toml uv.lock ./` → 文件在版本库内，全新 clone 的构建上下文里存在 ✅ |
| 修复发生在哪个提交 | `git log -S'uv.lock' -- .gitignore`、`git log -- backend/uv.lock` | 均在 **`8149029`**（即本范围的最后一个 commit，同时也提交了 README/文档） |
| 锁文件与 `pyproject.toml` 是否一致（`--frozen` 能否成功） | `uv lock --check` / `uv run --frozen pytest -q` | **exit 0** / 66 passed —— `uv.lock` 已包含 `python-multipart` 等全部依赖（`uv.lock:213-231`），R1-R5 期间新增的依赖没有漏锁 ✅ |

> 观察：修复与「未完成项」文档写在同一个提交里，二者互相矛盾——说明该表是手工维护且未在修复后回改。建议把「未完成项」清空或标注「已于 8149029 修复」。

### 5.2 已知事实 2：plan Task 11 计划预审 Fail（「打包三个独立视图」未拆成三个文件）

**记录项，非新发现，且我同意作者的处理**：`plan.md:T11` 把镜像/网络/卷三页放在同一个 Task，预审严格记 Fail（`docs/epics/docker-manager-v1/README.md:94`），实现最终落在**三个独立视图文件**（`frontend/src/views/ImagesView.vue` / `NetworksView.vue` / `VolumesView.vue` 均存在且均为 A 状态新增）。属「计划粒度与预审口径」差异，功能无缺口，作为记录接受。

### 5.3 已知事实 3：R1-R5 五轮修复本身的正确性（本次逐条复核）

| 轮次 | 修复内容 | 复核结论 |
|------|---------|---------|
| R1-① | 容器列表 500：`Container` 无 `.state` | ✅ **正确**。docker-py 7.2.0 `models/containers.py:28-67` 只有 `name`/`image`/`labels`/`status`/`health`/`ports`，**无 `state`**；`containers.py:82-88` 改用 `attrs["State"]["Status"]` 是对的（`containers.list()` 默认 inspect 形状）。见 §2.Q2 的残留冗余。 |
| R1-② | `/ws/logs` 阻塞事件循环 | ✅ **正确且是本次 diff 里最关键的修复**：把阻塞生成器搬到线程 + `call_soon_threadsafe` 回投 + `receive()` 0.5s 有界等待 + 收尾 `log_stream.close()` 解除线程阻塞（`ws.py:70-124`），并有真机级回归测试。 |
| R1-③ | `/ws/exec` 丢弃输入 | ✅ **正确**。`exec_create(..., stdin=True, tty=True)`（`ws.py:154-162`）确为必需；用例断言 `kwargs["stdin"] is True`。 |
| R1-④ | PTY 从不 resize | ✅ **正确**。改用低层 `api.exec_create`/`exec_start` 以保留 `exec_id`，`exec_resize(exec_id, height=rows, width=cols)` 与 docker-py 签名一致（`api/exec_api.py:99`），参数顺序在测试中被钉住。 |
| R2 | 端口按行解析 + IPv4/IPv6 去重 | ✅ **正确**，`_format_ports` + `_append_unique`（`containers.py:24-50`）有三条针对性用例。 |
| R3 | 镜像源降级 + nginx 超时/体积 | ✅ **功能正确**（首次直连失败→仅在判定为「不可达」时走镜像源→重打标签→删临时标签，8 条用例覆盖；`frontend/nginx.conf:11-22` 配了 3600s 与 `client_max_body_size 0`）。设计侧的两点保留见 §1（蔓延/静默重打标签）与 §2.Q6（name 内含 tag 时拉错 tag）。 |
| R4 | 从镜像运行容器 | ✅ 实现与测试质量良好（见 §4 亮点），但属 plan 外蔓延（§1.P5）。 |
| R5 | 终端复制粘贴 | 前端范畴，不在本透镜。 |

**亮点（Production）**
- 部署配置与 spec §6 的安全对策逐字一致，且 `docs/deployment.md:137-152` 明确写出「等价于宿主机 root / 只绑 127.0.0.1 / 用 SSH 隧道 / 绝不暴露公网」，是诚实的文档（配套风险见 §3.A1）。
- 导出与拷出均不落盘：镜像导出走 daemon 流 → `StreamingResponse`；nginx 侧 `proxy_buffering off` / `proxy_request_buffering off`（`frontend/nginx.conf:17-18`），大镜像不会撑爆磁盘或内存。
- 临时目录策略按 spec 落地：`main.py:15-18` 的 lifespan 启动清空 + `files.py:25` 拷入完成即删（拷出路径未用到临时目录，见 §1.P3）。
- `docker-py`/Engine 兼容范围有文档（`docs/deployment.md:33`「Docker Engine 20.10+」），满足 `spec.md:115` 的对策。

---

## 6. 存疑 / 未能验证项

1. **OCR 预扫未纳入**：`docs/epics/docker-manager-v1/ocr/` 只有 `BASE_SHA`（= `c689f71…`，与本审查 BASE 一致）与 `ocr-background.md`（= spec 副本，5952 B），写报告前两次检查都没有 `ocr-preview.md/.json` → 本报告**无 OCR 交叉验证段**。
2. **E2E / 部署验证未能独立复核**：本沙箱连不上 Docker daemon（`npipe` permission denied），`scripts/e2e_verify.py`（18 项）、`ui_verify.py`、`ui_clipboard_test.py`、`docker build`、`docker compose up` 均无法执行。「真机可用」这一结论本次**只有间接证据**支持：单测通过 + 代码里对真实 docker-py 形状的适配正确（我逐条核对了 `.state`、`ports`、`SocketIO`、`exec_resize`、`list()` 的 inspect 形状）+ 脚本本身是真的（真 HTTP/WS、真 tar 解析、`stty size` 断言）。
3. **`scripts/e2e_verify.py:214-217` 的软断言**：`/ws/logs` 在 15s 内没有输出时记为 PASS（「容器安静是合理的」）。这意味着 E2E 的 18 项里有一项在安静容器上不构成证据；`test_ws_logs_blocking.py` 用 `filter=web` 的 mock 覆盖了同一路径，弥补了一部分。
4. **前端是否轮询容器列表**未核实（前端归另一透镜）：若 `ContainersView` 定时刷新，则 §3.A3 的 2N+1 次 daemon 往返会被放大。
5. **未验证的运行期行为**：`docker.from_env()` 在容器内（Linux + `DOCKER_HOST=unix://…`）是否会因 `~/.docker/config.json` 缺失而走兜底分支、`uv run` 在容器启动时是否触发网络同步、daemon 重启后缓存的单例 client 是否需要重建——都需要真机确认（本环境无法验证）。
6. `backend/app/routers/images.py` 的镜像源降级属第三方镜像信任降级（镜像来源被静默重打为官方名），本次只做了代码层判定，**未做供应链层面的尽调**。

---

## 7. 汇总

| 段 | Verdict | 🔴 | 🟡 | 🟢 | 关键结论 |
|----|:--:|:--:|:--:|:--:|------|
| 1. Plan alignment | ❌ | 0 | 2 | 7 | spec §6「消息节流」对策缺失（HARD）；导出 tar 未保留标签（tar 到异机 load 后变 `<none>`）；拷出偏离 D4 中转设计；scope F4/F5 各缺一项（plan 亦欠范围）；R4「从镜像运行容器」与 `IMAGE_MIRRORS` 两处蔓延（后者违反 D3「唯一常量」）；epic README 的「待修复」与代码不符。已知接受：Task 11 三视图粒度（§5.2）。 |
| 2. Code quality | ⚠️ | 0 | 0 | 7 | 无阻断项。`state`≡`status` 冗余且对 sparse 形状会炸；`copy_into` 的 try 边界/内存放大/同名并发；镜像源默认值三处重复；not-found 一律 500；`name` 内含 tag 时静默拉错 tag；WS 入参未校验/单帧异常即断会话。 |
| 3. Architecture | ❌ | 0 | 1 | 3 | 跨站 WebSocket 劫持 + 跨站简单请求副作用（spec §6 的 127.0.0.1 对策挡不住浏览器中介，可经 backend 容器拿到宿主机 root）；镜像源策略与模型映射落在 router 层（plan 自身确立的模式，R3 推过头）；容器列表 2N+1 次 daemon 往返；并发上限未定义。 |
| 4. Testing | ❌ | 0 | 2 | 2 | 实跑 **66 passed**；14 个端点零单测（含 F6/F7 主线）；`test_files_api` 把文件写进仓库工作目录并把 `backend/a.txt` 提交进库；`test_ws_logs` 断言被 `except: pass` 吞掉。**mock 形状核验结论：与 docker-py 7.2.0 一致，不存在 README 所述的「加 `.state` / `ports` 写成 list」问题**（唯一缺口是没有 sparse 形状的用例）。 |
| 5. Production | ❌ | 0 | 1 | 3 | `copy_into` 是唯一仍在事件循环里做同步阻塞 I/O 的处理器（R1 事故同类残留，HARD）；Dockerfile 基镜像 `uv:latest` 未固定 + 源码改动即废掉依赖缓存层；compose 无 restart/healthcheck；`clear_tmp_dir` 只删文件、无 logging 配置。**已知事实 1 独立核实：`uv.lock` 已在 `8149029` 随 `.gitignore` 一并修复，非未决缺陷**（README 未回改）。R1-R5 逐条复核：修复本身正确。 |

**后端透镜总判定：NEEDS FIXES**（🔴 0 / 🟡 6 / 🟢 22）。优先修复顺序建议：
1. `files.py:16-25` 的 async 阻塞（§5.R1，一行改动量级，消除唯一的事件循环冻结点）；
2. `/ws/*` 与写操作的 Origin/CSRF 防护（§3.A1，成本低、收益最大）；
3. WS 消息节流/背压（§1.P1，spec 明文对策）；
4. 导出改 `named=True`（§1.P2，一行）；
5. `test_files_api` 改用 `tmp_path` 并删除 `backend/a.txt`（§4.T2）；
6. 回写文档：epic README「未完成项」、spec §5 二服务、D4 拷出路径、plan T5 的 F4/F5 缺项。
