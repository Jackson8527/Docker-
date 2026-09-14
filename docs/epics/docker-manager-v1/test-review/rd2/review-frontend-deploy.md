# 修复后重审报告（前端 + 部署透镜）— docker-manager-v1（Rd2）

> 审查对象：`docker-manager` 工作区**未提交的修复批次**，提交基线 `8149029`（`HEAD` = `8149029`，全部改动是 working tree 变更）
> 审查范围（本透镜）：`frontend/**`、`deploy/**`、`docs/deployment.md`、`scripts/e2e_verify.py`（仅用于 C-18 预算核对）
> 透镜：前端（`frontend/src/**`）+ 部署（`frontend/nginx.conf`、`frontend/.dockerignore`、`deploy/docker-compose.yml`）
> 依据：`docs/epics/docker-manager-v1/spec.md`、`scope.md`、`test-review/code-review-report.md`（C-xx 编号来源）、`rd1/review-frontend-deploy.md`
> 审查日期：2026-09-11
> 审查方式：**只读独立核实**（未修改任何产品代码）；不采信代码注释与自述，每条结论附命令 + 真实输出或 `文件:行号`
> 工具链实测：`vue-tsc -b --force` 退出码 **0**；`docker compose config`（无需 daemon）；`curl`/`node` 对运行中的 `127.0.0.1:8088` 探针
> 环境限制（**不是产品缺陷**）：沙箱禁止 Docker Desktop 命名管道（`docker version` → `permission denied ... npipe:////./pipe/dockerDesktopLinuxEngine`）与 Playwright → **无法重建镜像、无法起真实浏览器**。因此凡「配置已改但运行镜像仍是旧的」之处，本报告一律标注为「静态核实 + 旧镜像实测基线」，不声称做过镜像内验证。

---

## 审查结论

**Verdict**：⚠️ **NEEDS FIXES（1 🟡 需修 + 3 🟡/🟢 新缺陷登记）**

上一轮本透镜的 7 条待关闭发现中：**4 条 CLOSED、2 条 PARTIAL、1 条 NOT CLOSED（新发现域）**。
本批次没有引入 🔴，且**修复方向全部正确**；未关闭项的共性是「**修了主干、漏了边界**」，其中最需要修的是 C-02 的退避计数复位与 C-09 的「留空关闭镜像源」承诺。

---

## 五段审查

| 段 | 结论 | 关键发现 |
|----|:--:|---------|
| Plan alignment | ⚠️ | C-05（暂停/恢复入口）**真接上了**、C-06 后端已覆盖停止容器；但 `spec.md:113` 的「防抖」仍无独立实现（以 100ms/16ms 批量 flush 等价覆盖，判定可接受）；C-02 只算部分关闭 |
| Code quality | ⚠️ | 重连状态机的定时器/`disposed` 纪律**逐条核实无泄漏**；扣分在退避不复位（N-01）、预检无超时无取消（N-02）、错误帧判定过窄导致的误判面（N-04） |
| Architecture | ✅ | 前端零内存流式下载/直链复用设计成立；`utils/ws.ts` 把协议判定收口到一处（好设计）；`isRetryableClose` 的 1000/1008 判定经实测证明**准确**（见下） |
| Testing | ⚠️ | `e2e_verify.py` 新增 `EXPECTED_CHECKS=18` 与退出码是**实质增强**；但它对 `create`/`commit` 的 180s/120s 预算**未覆盖导出端点**（前端那句注释引用它作为依据，属**弱引用**） |
| Production | ⚠️ | C-16 构建上下文实测 **118.2 MB → 0.2 MB**，且**逐文件核对无任何误排除**；C-09 四变量与文档**逐项一致**且 `.env` 实测生效，但**「留空关闭降级」这条文档承诺实测不成立** |

---

## 一、上一轮发现的独立核实（逐条）

### C-03 · nginx `Host $host` → `$http_host` — 判定：**CLOSED（附带一个未做的推荐加固）**

**代码现状**（两处都已改）：

- `frontend/nginx.conf:36` — `location /api/` 内 `proxy_set_header Host $http_host;`（`nginx.conf:32-35` 是解释注释）
- `frontend/nginx.conf:48` — `location /ws/` 内 `proxy_set_header Host $http_host;`

**旧镜像实测基线**（必须先说清：**运行中的 `dockermgr-frontend` 是旧镜像，仓库里这条改动尚未生效**）：

```
$ curl.exe -s -i --max-time 15 "http://127.0.0.1:8088/api/containers/"
HTTP/1.1 307 Temporary Redirect
Server: nginx/1.31.5
location: http://127.0.0.1/api/containers        <-- 端口丢失，指向未监听的 80

$ curl.exe -s -o NUL -w "port80_status=%{http_code}\n" --max-time 5 http://127.0.0.1/api/health
port80_status=000                                 <-- 80 端口确实没有任何东西在听

$ node -e "fetch('http://127.0.0.1:8088/api/containers/',{redirect:'manual'})..."
live container-api preflight (redirect:manual): status=307 location=http://127.0.0.1/api/containers
```

即：**旧缺陷 100% 可复现**，且后果是硬失败（跳到一个没有任何监听的端口，`000`），不是「可能有问题」。

**新配置是否真能修掉 —— 静态推演 + 依据**：

| 变量 | nginx 定义 | 本项目 `Host: 127.0.0.1:8088` 时的值 |
|------|-----------|-----------------------------------|
| `$host` | 「request line 里的 host，**或** Host 请求头字段里的 host，**或** 与请求匹配的 server_name」——**端口在其中被剥离** | `127.0.0.1` |
| `$http_host` | 「`Host` **请求头字段的原样内容**」 | `127.0.0.1:8088` |

后端 FastAPI（`redirect_slashes` 默认开启）用重建的 `request.url` 拼 `Location`，而 `request.url` 取自 **Host 头**。于是：

- 旧：上游 Host = `127.0.0.1` → `Location: http://127.0.0.1/api/containers`（实测吻合）
- 新：上游 Host = `127.0.0.1:8088` → `Location: http://127.0.0.1:8088/api/containers` ✅

**`proxy_redirect` 是否需要？—— 不需要。** `proxy_redirect` 的默认值就是 `default`，语义为 `proxy_redirect <proxy_pass 的值> <Host 头的值>`；本例 `proxy_pass` 无 URI 部分，因此默认规则只有在 `Location` 恰好等于 `http://backend:8088` 时才改写。加了 `$http_host` 以后 `Location` 已经是客户端可达的绝对 URL，**再加 `proxy_redirect` 反而会把正确的 URL 改坏**。

**更正确的写法（推荐，但不是关闭条件）**：`$http_host` 是客户端可控值，HTTP/1.0 或畸形请求下**可能为空**（upstream 收到空 `Host:` 头 → uvicorn 400）。更稳的是 server 级定义一次：

```nginx
map $http_host $forwarded_host {
    ""      $host:$server_port;
    default $http_host;
}
# 三处 proxy_set_header Host 全部改用 $forwarded_host
```

**为什么判 CLOSED 而不是 PARTIAL**：修复方向、依据、失效面都已核实清楚，且**旧行为有实测证据**。唯一缺口是「镜像内验证」——它被沙箱的 docker 管道权限挡住，属于**验证手段缺失**，不是修复不成立。修改后**必须重建前端镜像**才生效（`docker compose up -d --build frontend`），文档/交付说明里应写明这一点。

---

### C-05 · 暂停/恢复 UI 入口 — 判定：**CLOSED**

| 核对项 | 结果 | 证据 |
|--------|------|------|
| 是否真接上 `pause`/`unpause` | ✅ | `frontend/src/views/ContainersView.vue:88-105`（模板两个按钮）→ `act('pause'|'unpause', row)` → `ContainersView.vue:282` `await containersApi[type](row.id)` → `frontend/src/api/index.ts:72-73` → 后端 `backend/app/routers/containers.py:189-204` |
| 类型是否允许 | ✅ | `ContainersView.vue:269` `type ContainerAction = 'start'|'stop'|'restart'|'pause'|'unpause'`；`Record<ContainerAction,string>`（`:272-278`）保证穷尽（`vue-tsc` 退出码 0） |
| 状态判断（running→暂停 / paused→恢复） | ✅ | `:89` `v-if="row.state === 'running'"`；`:98` `v-else-if="row.state === 'paused'"`。后端 `state` 取自 `attrs["State"]["Status"]`（`containers.py:82-87`），Docker 的取值就是 `running` / `paused`；`styles/main.css:290-293` 早有 `.dm-dot.is-paused` 配色，三者一致 |
| 会不会出死按钮 | ✅ 无死按钮 | 两个分支由同一个 `v-if/v-else-if` 承担，**任一时刻最多一个可见**；`paused` 之外的 `exited/created/restarting/dead` **两个都不显示**（不存在「点了必然 500」的按钮） |
| 失败是否有反馈 | ✅ | `:285-287` `catch (err) { fail(err) }`，`fail`（`:251-254`）取 `response.data.detail` 弹 ElMessage |
| 成功反馈 | ✅ | `:283` `ElMessage.success(\`${row.name} 已${ACTION_DONE[type]}\`)`，`ACTION_DONE.pause='暂停'` / `.unpause='恢复'`（`:276-277`） |
| 列表是否刷新 | ✅ | `:284` `load()`（虽未 `await`，与既有 `start/stop/restart` 行为一致） |

**新增：操作列宽度与交互影响（问题二的一部分）**

- 列宽 `270 → 326`（`:63`）；`.dm-row-actions` 是 `flex-wrap: nowrap`（`styles/main.css:304-308`），因此宽度必须够。粗算最宽情形（`running`）＝ 启动 44 + 停止 44 + 暂停 44 + 重启 44 + ⋯下拉 30 + 4×4 gap ≈ **254 px** < 326 px，**不会溢出**（`exited/paused` 情形按钮更少）。
- ⚠️ **但 `/ws/exec` 对 paused 容器没有防护**（见「问题二」N-03）：paused 容器的对话框里「进入终端」仍可点，Docker 的 `exec_create` 对冻结容器会**永久阻塞**（线程卡在 `asyncio.to_thread`，`exec_start` 永不返回，终端停在「连接中…」）。

---

### C-02 · 消息节流 / 断线重连 / 防抖（前端半）— 判定：**PARTIAL**（三件事都做了，退避状态机缺一步）

`spec.md:113` 原文：`| 长日志/高并发 WS | 中 | 消息节流、断线重连、防抖 |`。

#### (1) 三项是否真的实现

| 要求 | 日志侧 `ContainerLogs.vue` | 终端侧 `ContainerTerminal.vue` | 结论 |
|------|--------------------------|---------------------------|------|
| 消息节流 | ✅ 100ms 批量 flush（`:68` `FLUSH_INTERVAL=100`、`:145-148` `scheduleFlush`、`:151-167` `flush` 一次响应式写入）；DOM 上限 `MAX_LINES=3000`（`:62`）+ 缓冲上限 `MAX_BUFFER=5000`（`:65`） | ✅ 16ms（约一帧）合并 PTY 字节（`:46` `WRITE_FLUSH_INTERVAL=16`、`:376-387`） | ✅ 实现 |
| 断线重连 | ✅ 自动重连 + 退避 + 倒计时（`:222-235` `onclose`→`scheduleRetry`、`:243-273`、`:275-287`） | ✅ 同构（`:261-287`、`:294-317`） | ✅ 实现 |
| 防抖 | ⚠️ **无独立 debounce**（全前端仅两处 `setTimeout`，都是节流式批量；`frontend/package.json` 无 lodash） | 同 | ⚠️ **判断项** |

**关于「防抖」的判定（JUDGEMENT CALL）**：`spec.md:113` 是风险对策表里的一句话，没有定义「防抖」作用在哪个交互上。本批次实际存在的最接近需求是「连点『重连』不应产生并发连接」，而代码里 `reconnect()`（`:310-319`）**每次先 `stopRetry()` + `dropSocket()`（先摘 handler 再 close）再建新连接**，天然不会并发；`select` 的 `@change="reconnect"` 也走同一路径。因此我判定：**以 100ms/16ms 批量 flush（节流）+ 先拆后连的幂等 `reconnect()` 覆盖了该条对策的意图**，不构成需要修复的缺失。若评审坚持逐字对齐，最小补法是在 `reconnect()` 入口加 150ms 尾沿去抖。

#### (2) 重连状态机逐点审查（本批次新代码的重点）

| 审查点 | 结论 | 证据 |
|--------|------|------|
| 指数退避是否真封顶 | ✅ 真封顶 | `:271` `retryDelay = Math.min(retryDelay * 2, RETRY_MAX)`，`RETRY_MAX=30000`（`:71`）。**实测**（`evidence/probe-retry.mjs`，逻辑逐字转写自源码）：drop#1 1s → #2 2s → #3 4s → #4 8s → #5 16s → #6 **30s（不再增长）** |
| 退避计数是否在成功后复位 | ❌ **没有** | `retryDelay` 只在 `reconnect()`（`:313`）被复位；`ws.onopen`（`:204-208`）**没有**复位。实测：连续 6 次失败后 `retryDelay=30s`，随后**健康连接 1 小时**再掉线，显示的等待仍是 **30s**（期望 1s）→ 见 **N-01** |
| 手动「断开」后是否真不再重连 | ✅ 是 | `closeStream()`（`:322-328`）= `userClosed=true` + `stopRetry()` + `dropSocket()`；`scheduleRetry`（`:244`）与 `tickRetry`（`:276-279`）都以 `userClosed` 早退；实测「断开后连跑 3 秒 tick：`tickTimer=undefined retryIn=0 connects=0`」 |
| 组件卸载后是否真不再重连 | ✅ 是 | `onUnmounted`（`:344-354`）顺序正确：**先 `disposed=true`** → `stopRetry()` → `clearTimeout(flushTimer)` → `dropSocket()` → 清空 `pending`；实测「卸载后连跑 2 秒 tick：`connects=0`」 |
| 是否有定时器泄漏 | ✅ 无 | 两个定时器都有单一来源 `tickTimer` / `flushTimer`，`scheduleRetry` 用 `if (tickTimer === undefined)` 守卫（`:272`），`scheduleFlush` 同理（`:146`）；`stopRetry`（`:289-296`）与 `flush`（`:152`）都置回 `undefined` |
| 是否有 socket 泄漏 | ✅ 无 | `dropSocket`（`:298-307`）**先摘 4 个 handler 再 close**，避免「自己触发的 onclose 又排一次重连」；`connect()`（`:201`）只在 `tickRetry` → `stopRetry()` 之后或初次挂载时调用，不会覆盖未清理的 socket |
| `disposed` 是否覆盖所有异步回调 | ✅ 覆盖 | `ws.onopen/onmessage/onclose` 首行都查（`:205`、`:210`、`:223`）；`flush` 查（`:153`）；`scrollToBottom` 的 `nextTick().then` 里通过 `bodyEl.value` 可能为 `undefined` 隐式失效（`:170-173`，不抛错）；`tickRetry` 查（`:276`）。**唯一未加 `disposed` 的点是 `scheduleRetry` 里对 `pushLine` 的调用**，但它被 `:244` 的 `disposed` 早退挡住 → 等价安全 |
| 重连是否会把 `tail` 重放导致大量重复行 | ⚠️ **会，但已知且有界** | 后端 `ws.py:103-109` 每次连接都用同一个 `tail`（默认 200，可选 2000）重新 `logs(tail=...)`；前端只在**重连时插一行提示**（`:267` `'... 连接已断开，正在重连（可能重复最近若干行）...'`）。有界性来自 `MAX_BUFFER`/`MAX_LINES`，**不会 OOM**，但抖动网络下日志区确实会被 tail 刷屏 → 见 **N-06** |
| 1000/1008 不重连的判定是否正确 | ✅ **正确，且经实测证明** | 我先在活体探针里看到 close code **1005**，一度怀疑「正常结束也会无限重连」；随后用 `evidence/probe-close-codes.mjs` 消歧：**客户端自己 close → 1005**；**服务端 `_close_ws()`（Starlette `WebSocket.close()` 默认 `code=1000`）→ 1000**（`/ws/logs` 错误帧路径与 `/ws/exec` 路径均实测 1000）。`utils/ws.ts:54-56` 的 `code !== 1000 && code !== 1008` 恰好命中，**未误判** |
| 100ms/16ms flush 会否丢行或乱序 | ✅ 不会 | 日志：`pending` 是**字符串数组**，`flush` 用 `lines.value.concat(batch)` 整批追加（`:162`），丢弃只发生在**最前面** `next.slice(next.length - MAX_LINES)`（`:163`）→ 保新弃旧、保序。终端：`writeBuf` 是**单个字符串**追加（`:378` `writeBuf += data`），跨帧拆开的转义序列天然不会错位（`:367-375` 的注释属实） |
| 缓冲上限丢弃策略会否丢**最新**行 | ✅ 不会 | `:135-141` `pending.splice(0, overflow)` 删的是**最旧**的 `overflow` 行，并往**尾部**补一行截断标记 → 最新行永远保留。唯一副作用：标记行本身计入 `MAX_BUFFER`，极端情况可产生 2 行连续标记（无害） |

**C-02 判定依据**：主干三项都落地，定时器/泄漏/`disposed`/丢弃策略**逐条核实无误**，唯一的算法缺口是「成功后不复位退避」（N-01）——按标准指数退避定义属**漏了一半**，故 PARTIAL 而非 CLOSED。

---

### C-17 · 下载「假成功」— 判定：**PARTIAL**（旧症状关闭，新增 2 个边界缺陷）

**方案核对**（`frontend/src/utils/download.ts:29-61` + `FileCopyDrawer.vue:113-128` + `ImagesView.vue:179-193`）：

| 审查点 | 结论 | 证据 |
|--------|------|------|
| 预检 `fetch` 是否真能看到 500 | ✅ **实测看到** | 活体：`GET /api/images/<不存在>/save` → `HTTP/1.1 500` + `Content-Type: application/json` + `{"detail":"404 Client Error ... No such image: ..."}`；`GET /api/containers/<不存在>/copy?path=...` → `HTTP/1.1 500` + `{"detail":"404 Client Error ... No such container: deadbeef..."}`。前端 `readErrorDetail`（`:64-78`）能从这个 JSON 取出 `detail` |
| 失败分支是否真的不提示成功 | ✅ **是** | `startDownload` 三条失败路径（网络异常 `:33-37`、`!res.ok` `:39-43`）**都 `return false`**；两个调用点都是 `if (await startDownload(...)) ElMessage.success(...)`（`FileCopyDrawer.vue:122-124`、`ImagesView.vue:186-188`）→ 失败时**不会**出现「已开始下载/已开始导出」 |
| 预检是否可能破坏大文件下载 | ⚠️ **不会破坏，但代价真实** | ① 预检期间 Node 收到 **10043 KiB / 300ms** 后才 abort（`evidence/probe-preflight-cost.mjs`，首个 chunk 也在 152ms 后到达）——说明**后端确实为预检启动了一次完整导出**，这正是 `download.ts:18-23` 注释承认的成本；② 预检**不复用**这次流（`res.body.cancel()` 后重新走 `<a>`），所以下载的是**第二次**导出，内容完整；③ 但「取头即取消」意味着浏览器侧丢弃量只有 TCP/socket 缓冲（几 KB~几十 KB），代码注释里「一点都不会缓冲」的表述**偏乐观** |
| `cancel()` 是否真能中断 `StreamingResponse` | ⚠️ 部分（判据不足，见下） | 实测 `res.body.cancel()` **resolve 且未抛**（`:48-51` 的 `try/catch` 是必要的，因为 Firefox/Safari 在某些时机 `cancel()` 会 reject）。但能否**立即**让服务端停止写 tar 取决于 Starlette 版本与 ASGI `spec_version` 分支：本机 `starlette 1.6.0` 的 `StreamingResponse.__call__` 在 `spec_version < (2,4)` 时走 `create_collapsing_task_group()` + `listen_for_disconnect()`，只有该分支才会**主动取消** `stream_response` 任务；`>= (2,4)` 分支仅在 `OSError`/`ClientDisconnect` 时结束。本机 uvicorn 0.52.4，`spec_version` 未实测 → **无法断言服务端一定立即停写**（见「未验证项」） |
| 是否引入内存/连接泄漏 | 🟢 未发现 | 每次点击新增 **2 次** 流式请求（预检 1 + 直链 1）。预检的 `requests.Response`（docker-py 的 tar 流）唯一强引用链是 `response → data → body_iterator → async_generator → async_generator_athrow`，客户端断开后由 GC 回收并触发 `requests.Response.__del__ → close()`。属**依赖 GC 时机**（不是显式 release），在同时导出多个大镜像时，被杀掉的导出可能仍占着 docker daemon 的一条流式连接与最多一个 64 KiB 读缓冲。**实测 3 并发预检全部即时 cancel 成功、无报错**（`evidence/probe-download.mjs` C 组） |
| 是否引入新缺陷 | ❌ **是，2 条** | 预检**无超时、无取消**（N-02）；预检**只校验状态行**，daemon 在 200 之后才失败的导出仍会被判成功（N-05） |

**「预检能否避免 500 也提示成功」的精确结论**：对**本轮审查指出的两类 500（路径不存在 / 镜像已删）成立**——这类错误在 docker-py 侧是 **eager** 的，我读了源码验证：`Image.save()`（→ `get_image()` → `self._get(url, stream=True)`）与 `ContainerApiMixin.get_archive()`（→ `self._get(..., stream=True)` + `_raise_for_status(res)`）**都在返回 generator 之前就把 HTTP 状态检查完了**，因此 500 一定发生在 `StreamingResponse` 构造之前，预检的状态码判据**是可靠的**。反之，daemon 在 200 之后才失败的情况预检看不到（N-05）。

---

### C-18 · 长操作超时（`LONG_OP_TIMEOUT`）— 判定：**CLOSED（含 1 条注释/预算口径 JUDGEMENT）**

| 审查点 | 结论 | 证据 |
|--------|------|------|
| `create`/`commit` 是否用上 `LONG_OP_TIMEOUT` | ✅ | `frontend/src/api/index.ts:64` `const LONG_OP_TIMEOUT = { timeout: 300000 }`；`:68` `create(..., LONG_OP_TIMEOUT)`；`:75-76` `commit(..., LONG_OP_TIMEOUT)` |
| 是否与 `scripts/e2e_verify.py` 的真实预算一致 | ✅ 覆盖（300s > 180s/120s） | E2E 实测预算：`scripts/e2e_verify.py:436` `timeout=180`（`POST /api/containers`）、`:190` `timeout=120`（`POST /{cid}/commit`） |
| `NO_TIMEOUT` 是否仍只用于 pull | ✅ 是 | 全文件仅 `api/index.ts:82` 一处 `NO_TIMEOUT` 引用（`imagesApi.pull`）。`api/index.ts:53-54` 的注释「that one call opts out」属实 |
| 全局 30s 是否仍作用于其余调用 | ✅ | `:51` `axios.create({ baseURL: '/api', timeout: 30000 })`；`start/stop/restart/pause/unpause/remove/list` 均未覆盖 |
| 注释所引依据是否严谨 | ⚠️ JUDGEMENT | `api/index.ts:59-61` 写「e2e allows 180s for POST /api/containers and **120s for POST /{id}/commit**」——`180` 属实，但 **e2e 并没有对 `commit` 给 120s**：`:190` 的 `timeout=120` 是 **`POST /api/images/pull`**，`commit` 走的是默认 `http(..., timeout=30)`（`:59`）。即那两个数字**真实但归因错位**，且**导出端点 `/images/{id}/save` 的 120s 预算（`:212`）根本没有被前端任何超时覆盖**（前端走裸 `<a>`/`fetch`，无 axios 超时）。结论不变（修法正确），但注释与「预算一致性」叙事需要修正 → 见 **N-07** |

---

### C-09 · compose 改 `${VAR:-default}` 与部署文档一致性 — 判定：**CLOSED（＋1 条 🟡 新发现的口径缺陷）**

**逐项对照**（`deploy/docker-compose.yml:11-16` ↔ `docs/deployment.md:89-94`）：

| 变量 | compose 名字与默认值 | 文档 §4.2 名字与默认值 | 一致？ |
|------|---------------------|----------------------|:--:|
| `DOCKER_HOST` | `:11` `${DOCKER_HOST:-unix:///var/run/docker.sock}` | `deployment.md:91` `unix:///var/run/docker.sock` | ✅ |
| `PORT` | `:12` `${PORT:-8088}` | `deployment.md:92` `8088` | ✅ |
| `TMP_DIR` | `:13` `${TMP_DIR:-/tmp/dockermgr}` | `deployment.md:93` `/tmp/dockermgr` | ✅ |
| `IMAGE_MIRRORS` | `:16` `${IMAGE_MIRRORS:-docker.m.daocloud.io,docker.1panel.live}` | `deployment.md:94` `docker.m.daocloud.io,docker.1panel.live` | ✅ |

**四个变量全部改成了变量替换**（改动前只有 `IMAGE_MIRRORS` 一个），`docs/deployment.md` 与 `README.md:71-78`、`.env.example` 的承诺**在名字与默认值上 100% 对得上**。

**`.env` 放置位置与写法是否真能生效 —— 实测（`docker compose config` 不需要 daemon，是本轮最有力的证据）**：

```
$ docker compose -f deploy/docker-compose.yml config          # 无 .env
      DOCKER_HOST: unix:///var/run/docker.sock
      IMAGE_MIRRORS: docker.m.daocloud.io,docker.1panel.live
      PORT: "8088"
      TMP_DIR: /tmp/dockermgr

$ # 写入 deploy/.env:  DOCKER_HOST=tcp://10.0.0.9:2375 / PORT=9099 / TMP_DIR=/tmp/custom-tmp
$ docker compose -f deploy/docker-compose.yml config
      DOCKER_HOST: tcp://10.0.0.9:2375
      PORT: "9099"
      TMP_DIR: /tmp/custom-tmp

$ # 写入 仓库根/.env: PORT=7777
$ docker compose -f deploy/docker-compose.yml config
      PORT: "8088"          <-- 根目录 .env 被忽略（符合 compose 规范：.env 取「项目目录」= compose 文件所在目录）
$ # 写入 deploy/.env: PORT=7777
      PORT: "7777"          <-- 生效
```

→ **`docs/deployment.md:80-85` 教的 `cd docker-manager/deploy && cp ../.env.example .env` 是正确写法，实测三个变量都会被 `.env` 覆盖。** 唯一与文档冲突的是 `IMAGE_MIRRORS` 的**留空语义**（见下）。

**🟡 新发现（N-08）**：`docs/deployment.md:104-108` 明确承诺「想关闭降级：`- IMAGE_MIRRORS=`」，但 `${IMAGE_MIRRORS:-…}` 的 `:-` 语义是 **「未设置**或**为空」都用默认值**，因此**留空关闭是不成立的**：

```
$ # deploy/.env 内容: IMAGE_MIRRORS=
$ docker compose -f deploy/docker-compose.yml config | Select-String IMAGE_MIRRORS
      IMAGE_MIRRORS: docker.m.daocloud.io,docker.1panel.live     <-- 降级仍然开着
$ # 换成真实值
$ # deploy/.env: IMAGE_MIRRORS=harbor.example.com
      IMAGE_MIRRORS: harbor.example.com                          <-- 覆盖生效
```

改法：把 `:16` 的 `:-` 换成 `-`（`${IMAGE_MIRRORS-docker.m.daocloud.io,docker.1panel.live}`），**只在未设置时**用默认值，留空即真正的「关闭降级」。其余三个变量（`DOCKER_HOST`/`PORT`/`TMP_DIR`）留空无意义，保持 `:-` 正确。

---

### C-16 · `.dockerignore` 与构建上下文 — 判定：**CLOSED**

**上下文压缩效果（实测，按 `.dockerignore` 规则逐条重算）**：

| 构建上下文 | 压缩前 | 压缩后 | 保留文件数 |
|-----------|-------|-------|:--:|
| `frontend/`（`deploy/docker-compose.yml:22-23` `context: ../frontend`） | **118.2 MB**（`node_modules` 116.1 + `dist` 1.9 + 其余） | **0.2 MB（167,068 B）** | 26 |
| `backend/`（`context: ../backend`） | 45.4 MB（`.venv` 44.9） | **0.215 MB** | 19 |

上一轮实测的 118.2 MB 与本次一致，`.dockerignore` 确实把上下文压到 0.2 MB 量级。

**有没有误排除构建必需文件 —— 逐文件核对保留清单**：

```
保留（frontend）：Dockerfile, .dockerignore, index.html, nginx.conf,
  package.json, package-lock.json, tsconfig.json, tsconfig.node.json,
  vite.config.ts, src/{App.vue,env.d.ts,main.ts,api/index.ts,router/index.ts,
  styles/main.css,utils/{ws.ts,download.ts,error.ts},components/×4,views/×4}
```

- ✅ `frontend/Dockerfile:4` 需要的 `package.json` + `package-lock.json` 都在 → `npm ci` 可跑
- ✅ `Dockerfile:6-7` 的 `COPY . .` + `npm run build` 需要的 `src/`、`index.html`、`tsconfig*.json`、`vite.config.ts` 都在（`tsc -b` 的 project references 需要 `tsconfig.node.json`，也在）
- ✅ `Dockerfile:12` 的 `COPY nginx.conf ...` 在
- ✅ 后端 `Dockerfile:8-9` 的 `COPY pyproject.toml uv.lock ./` + `COPY app ./app` **全部**在执行列表中（`uv.lock` 183,446 B 在；`app/` 下 13 个文件全在，含新增的 `services/security.py`）
- ✅ **`public/` 在本项目不存在**（无 favicon，`index.html:5` 的引用本就是悬空 URL），所以「没保留 public」不是误排除

**与 `Dockerfile` 的 `COPY`/`npm ci` 顺序是否自洽（关键项）**：

- ✅ **自洽**。`Dockerfile:4-6` 的顺序是 `COPY package*.json` → `RUN npm ci` → `COPY . .`。**排除 `node_modules` 正是这个顺序的前提**：不排除时 `COPY . .` 会用宿主的 Windows `node_modules`（含 `@esbuild/win32-x64`、`@rollup/rollup-win32-*`）覆盖镜像内刚装好的 Linux 依赖 → 构建产物含错平台二进制且不可复现。排除后镜像内**只剩 `npm ci` 装出的 Linux 依赖**，语义正确。
- ✅ `backend/.dockerignore` 对后端属**纯粹收益**：`backend/Dockerfile` 只 `COPY` 两个文件 + 一个目录，从不 `COPY . .`，即使没有 `.dockerignore` 也不会有覆盖问题；本轮补上主要收益是上下文 45.4 MB → 0.2 MB。

**`tsconfig.tsbuildinfo` / `vite.config.js` 被排除是否有副作用**：

- ✅ 无副作用，**且是必要的**。`package.json:8` 的 `build` 是 `vue-tsc -b && vite build`；若 `vite.config.js` 被打进镜像，Vite 的配置查找顺序里 **`.js` 优先于 `.ts`** → 镜像内会用宿主的旧编译产物而非 `vite.config.ts`。`.dockerignore:11-15` 把 `vite.config.js/.d.ts` 与 `*.tsbuildinfo` 排除，`vue-tsc -b` 会在镜像内**重新生成**（增量失效只会导致全量重编，不会失败）。
- 注：`.dockerignore:20-22` 的 `.browser-tools` / `.npm-cache` / `scripts/ui-shots` 在 `frontend/` 下**不存在**（实测 absent），属无害冗余条目。

---

## 二、修复批次引入的新缺陷

### N-01 🟡 重连退避计数在成功后不复位（`ContainerLogs` / `ContainerTerminal`）

- **位置**：`frontend/src/components/ContainerLogs.vue:204-208`（`ws.onopen` 缺复位）、`:271`（只增不减）、`:313`（仅手动重连复位）；`frontend/src/components/ContainerTerminal.vue:240-246`、`:301`、`:346` 同构
- **证据（实测）**：`evidence/probe-retry.mjs`（状态机逐字转写自源码）

  ```
  === S1: repeated transport failures (1006) ===
    drop #1: shown = 1s   drop #2: 2s   drop #3: 4s
    drop #4: 8s           drop #5: 16s  drop #6: 30s   <- 封顶正确
  === S2: successful connection, then a later drop ===
    retryDelay after 6 failures (capped) = 30s
    next drop after 1h healthy: shown = 30s   (expected 1s if backoff resets on success)
  === S3: manual 「重连」 resets the backoff ===
    after manual reconnect: shown = 1s
  ```
- **影响**：一次短暂网络抖动（连续 5 次失败）就会把退避永久钉在 30s。此后**即使流了一小时都很健康**，下一次掉线用户仍要等 30 秒，且**只能靠点「重连」按钮**回到 1s——这正是「断线重连」体验的退化点。
- **性质**：JUDGEMENT CALL（`spec.md:113` 只说「断线重连」，未写退避算法），但按指数退避的标准定义，「成功后复位」是该算法的组成部分；本轮修复自称实现了退避、实测封顶正确，故属**修了一半**。
- **修复建议**：在 `ws.onopen` 内加一行 `retryDelay = RETRY_BASE`（两个组件各一行）。
- **关闭判定**：**PARTIAL**（C-02 的未关闭项）

### N-02 🟡 下载预检既无超时也无取消，最坏情况按钮永久 loading

- **位置**：`frontend/src/utils/download.ts:30-43`（`res = await fetch(url)`，无 `AbortSignal`）；消费点 `FileCopyDrawer.vue:118-127`（`downloading.value = true` / `finally` 复位）、`ImagesView.vue:181-192`（`exportingId`）
- **证据**：全文件无 `AbortController`/`AbortSignal`/超时（`download.ts` 79 行通读）；对比 `api/index.ts:51` 的 axios 全局 `timeout: 30000`——**只有这个新加的下载路径没有超时**。
- **影响**：后端卡住（daemon 无响应、`get_archive` 挂住）时，`fetch` 既不 resolve 也不 reject → `downloading`/`exportingId` 永远为真 → 按钮**永久 loading**，用户既不知道该等多久，也无法在页面上区分「正在下载」与「已卡死」。
- **性质**：HARD VIOLATION（本批次新引入的路径缺少项目其他地方一致具备的超时保护；`spec.md:13` 要求动作对用户可见且可理解）。
- **修复建议**：

  ```ts
  const PREFLIGHT_TIMEOUT = 10000   // 与 axios 30s 不同：预检只等响应头，10s 足够
  const ctrl = new AbortController()
  const timer = window.setTimeout(() => ctrl.abort(), PREFLIGHT_TIMEOUT)
  try { res = await fetch(url, { signal: ctrl.signal }) }
  catch (err) { /* 超时也走这里 */ showApiError(err, '下载失败'); return false }
  finally { window.clearTimeout(timer) }
  ```
  超时后仍可提示「预检超时，已改为直接下载」并把控制权交给 `<a>`，比无限 loading 好。
- **关闭判定**：**NEW DEFECT**

### N-03 🟡 paused 容器的「查看日志 / 进入终端」未防护（后端 `exec_create` 会永久阻塞）

- **位置**：`frontend/src/views/ContainersView.vue:109-119`（下拉菜单 `logs`/`terminal` 无 `row.state` 判断，paused 行仍可出现）；后端 `backend/app/routers/ws.py:229-239`（`api.exec_create` → `exec_start` 无超时）
- **证据**：本轮**新增了暂停能力**，但下拉菜单未随之加状态门；`ws.py:239` `output = await asyncio.to_thread(api.exec_start, ...)` 包在 `to_thread` 里，Docker 对 `paused`（cgroup freezer 冻结）容器的 `exec_start` 会一直等容器恢复——线程永久占用，前端 `ContainerTerminal.vue:231-238` 停在「连接中…」，`scheduleRetry` 也不会触发（socket 没关）。
- **影响**：用户点了「暂停 → 进入终端」后得到一个**看似卡死**的终端画布，且后台多一个卡住的线程；这是本轮新功能与既有菜单的组合缺陷（属「新功能引入的新交互路径」）。
- **性质**：JUDGEMENT CALL（无 spec 明文），但后果明确且用户可见。
- **修复建议**：① 前端在 `row.state !== 'running'` 时禁用「进入终端」（与「停止」按钮同样式），或在 `ContainerTerminal` 内对被暂停容器给出明确提示；② 后端给 `exec_create`/`exec_start` 加 `asyncio.wait_for(..., timeout=10)`，超时后走 `{"error": "容器已暂停，无法打开终端"}` 错误帧（**与冻结契约兼容**：仍是文本帧内 `{"error": "..."}`）。
- **关闭判定**：**NEW DEFECT**

### N-04 🟢 `parseServerErrorFrame` 的判定规则会把「恰好是 `{"error":"..."}` 的日志行」误判为控制帧

- **位置**：`frontend/src/utils/ws.ts:24-39`（判据：`trim` 后以 `{` 开头、以 `}` 结尾、`JSON.parse` 得非数组对象、`error` 是非空字符串）
- **证据（实测，`evidence/probe-ws.mjs`）**：

  ```
  batch of lines                     -> null      （多行批次不解析为 JSON，安全）
  json log line, no error key        -> null      （无 error 键，安全）
  json log line WITH error key       -> "connection reset by peer"   <-- 误判
  real error frame                   -> "no container"
  error frame w/ padding             -> "no such container: web"
  array frame                        -> null
  empty error / null error / non-string error -> null
  multi-line log ending with }       -> null      （"a\n{\"x\":1}" 整体解析失败，安全）
  ```

  即判据**只在「整帧恰好是一个带非空字符串 `error` 的 JSON 对象」时命中**；「错误帧+后续日志」的混合帧**不会**被误判（整体 parse 失败），这点比预想的好。补充一组**真实世界 JSON 日志**的对抗用例（`evidence/probe-ws-extra` 的运行输出）：

  ```
  {"error":"boom","msg":"db down"}                                 -> "boom"
  {"level":"error","error":"ECONNREFUSED","msg":"upstream"}        -> "ECONNREFUSED"   <-- 极常见的结构化错误日志
  {"time":"2026-09-11T00:00:00Z","error":"x"}                      -> "x"
  {"error":{"code":500}}                                           -> null              （非字符串 error，安全）
  "  {\"error\":\"x\"}  "                                          -> "x"               （trim 后仍命中）
  {"error":"x"} trailing                                           -> null              （整帧非纯 JSON，安全）
  ```
- **真实风险评估**：低-中。① 纯文本日志（uvicorn/nginx/大多数应用）不可能命中；② **JSON 结构化日志的容器**只要某行含**字符串** `error` 字段（`{"level":"error","error":"...","msg":"..."}` 是 Go/Node/结构化 Python 应用的默认错误日志形状）就会**被静默吞掉**，界面上弹一条红色「无法获取日志」→ 用户会以为 WS 坏了，实际只是那行被判成了控制帧；③ 相比「每行 JSON 都误判」，命中面已被 `trim` 后的整帧形状限制住，且非字符串 `error` 与「有尾随内容」的帧都安全。
- **更好的判据（推荐按顺序采纳）**：
  1. **前端状态判据（零后端改动，强烈推荐）**：后端契约保证错误帧是**连接建立后、任何数据之前的唯一一帧**（`ws.py:98-99` 发完即 `return`），因此加一个 `let sawData = false`，在 `appendChunk` 成功后置真，`onmessage` 里 **只在 `!sawData` 时才做错误帧判定**。这会把误判面从「任意时刻」压缩到「收到首帧数据之前」，**几乎不可能误伤真实日志**。
  2. **协议判据（更彻底，代价是后端改动 + 契约变更）**：把「不能服务」的语义搬到**关闭帧**上——`await ws.close(code=1011, reason="no container")`，前端读 `ev.reason`（浏览器原生支持，`CloseEvent.reason`），控制信息与数据**结构性分离**，`parseServerErrorFrame` 可以整个删掉。注意：本环境实测服务端 close 能正确送达 code（1000 与 1008 均实测到），故该方案在本机可行。
  3. 最弱方案是在文本帧上加前缀（如 `{"dm_ctrl":1,"error":...}`），能降低但不能消除误判（用户日志仍可能构造出该形状）。
- **性质**：JUDGEMENT CALL（冻结契约要求「WS 错误帧 = 文本帧内含 `{"error": "..."}` 对象」，本实现**恰好正确执行了该契约**）。因此**不要求改后端契约**；建议采纳方案 1。
- **关闭判定**：**NEW DEFECT（🟢 / 建议采纳方案 1）**

### N-05 🟢 预检只校验状态行：daemon 在 200 之后才失败的导出仍会显示「已开始导出」

- **位置**：`frontend/src/utils/download.ts:39-43`（判据只有 `res.ok`）
- **证据**：实测 `res.body.cancel()` 在 **headers 到达时即可 resolve**（`evidence/probe-download.mjs`：`headers after 129ms, status=200` → `cancel() resolved after 3ms`），此时 tar 才刚开始传输。因此预检**没有读任何正文字节**，无法覆盖「状态行 200 + 正文中途 500/断流」的情况。
- **影响**：本轮指出的两类 500（路径不存在/镜像已删）**在 docker-py 侧是 eager 的**（我读了 `Image.save → get_image → _get(stream=True)` 与 `ContainerApiMixin.get_archive → _get(stream=True) + _raise_for_status`，均在返回 generator 前完成状态检查），所以这两类**确实被预检拦住了**；但 daemon 在流中途出错（大层导出时 I/O 错误、磁盘满）时，浏览器仍会拿到一个截断的 `.tar`，界面**不会**报错。相比修复前的「所有错误都假成功」，这是**大幅改善**，属残留边界而非回归。
- **性质**：JUDGEMENT CALL（无 spec 要求；`spec.md:57` 的流式导出目标与「预检读正文」相冲突）
- **修复建议**：可选加固——预检里 `await reader.read()` **读一个 chunk**（有 `AbortController` 超时保护）再 cancel，就能同时确认首字节已到；或干脆接受该边界，在 UI 上把提示从「已开始导出」改成「已开始导出（下载中断时请重试）」。注意 `Content-Length` 在流式响应里不可用（实测 `Transfer-Encoding: chunked`），**不能**靠它校验完整性。
- **关闭判定**：**NEW DEFECT（🟢 / 可延后）**

### N-06 🟢 重连必定重放 `tail`，抖动网络下日志区被重复行刷屏

- **位置**：`ContainerLogs.vue:267`（仅插一行提示）、`:202`（重连沿用同一 `tail`）；后端 `backend/app/routers/ws.py:103-109`（每次连接重新 `tail=N`）
- **证据**：后端每次连接都以同一 `tail` 重放；`tail` 可选 100/500/**2000**（`ContainerLogs.vue:11-13`）。连续抖动时按 N-01 最多 30s 一次重连，每次最多灌 2000 行 → 由 `MAX_LINES=3000` 与 `MAX_BUFFER=5000` 保证**内存有界**，但**可读性无界**。
- **性质**：JUDGEMENT CALL（现有实现明确用提示行承认了该行为，且无 OOM 风险）
- **修复建议**：① 重连时把 `tail` 降为一个小值（如首次 200、重连 20）——后端参数已支持，纯前端一行；② 或后端在重连连接上支持 `since=<最后一行的 ts>`（需契约扩展，代价大）；③ 至少让提示行只在**同一个自动重连序列的第一次**出现（现在每次掉线都会插一行）。
- **关闭判定**：**NEW DEFECT（🟢 / 可延后）**

### N-07 🟢 C-18 的注释把 E2E 超时预算归因错了（`commit` 的 120s 实为 `pull`）

- **位置**：`frontend/src/api/index.ts:59-61`
- **证据**：`scripts/e2e_verify.py:190` 的 `timeout=120` 属于 **`POST /api/images/pull`**；`commit` 调用（同函数内）走默认 `timeout=30`（`:59`）；而 `timeout=180` 确实属于 `POST /api/containers`（`:436`）。另 `:212` 给 `GET /api/images/{id}/save` 的 `timeout=120` **没有任何对应的前端超时**（前端走裸 `<a>` / `fetch`）。
- **影响**：无功能影响，但该注释是「预算一致性」论证的唯一依据；按注释复核的人会得到错误结论（正如上一轮 C-18 的发现本身就是因为这个错位）。
- **修复建议**：改成准确表述，例如「E2E 对 `POST /api/containers` 给 180s、对镜像导出给 120s；`commit` 在 E2E 里仍是默认 30s（其真实耗时随文件系统大小增长，300s 为安全网）」。
- **关闭判定**：**NEW DEFECT（🟢）**

### N-08 🟡 `${VAR:-default}` 让「留空关闭镜像源」这条文档承诺失效

（证据与修法见上文 C-09 段落）→ **性质：HARD VIOLATION**（`docs/deployment.md:104-108` 是明文承诺，实现与文档冲突）→ **关闭判定：NEW DEFECT / C-09 的残留项**

### N-09 🟢 `ContainersView` 新增按钮没有在途操作保护（双击可能撞 500）

- **位置**：`frontend/src/views/ContainersView.vue:88-107`（暂停/恢复/重启按钮均无 `:loading`、无 per-row 在途标记）；`act()`（`:280-288`）无重入守卫
- **证据**：全文件无 `busy`/`pending` 之类状态（`Select-String` 无命中）；`load()` 在 `act` 之后**不 await**（`:284`），所以 `row.state` 在操作完成前不会更新。**实测 Docker 语义**：`docker pause` 之后立刻 `docker stop` 会因容器处于 paused 而失败（daemon 返回错误 → 前端 `fail()` 弹 500）。「启动」按钮在这段窗口内对 paused 行**不会**被禁用（`:70` 只判 `state === 'running'`），而 Docker 对 paused 容器 `start` 会报错。
- **影响**：偶发的「点了没反应/报错红条」。属既有模式（`start/stop/restart` 本就没有在途保护），但本轮把操作数从 3 个加到 4 个，暴露面变大。
- **性质**：JUDGEMENT CALL
- **修复建议**：加一个 `const busy = ref('')` 存 `row.id`（或 `${row.id}:${type}`），`act()` 入口守卫 + 出口复位，并把所有操作按钮 `:disabled="busy === row.id || <原条件>"`。顺带能修掉「暂停/恢复按钮没有 loading 态」的观感问题。
- **关闭判定**：**NEW DEFECT（🟢）**

### 全量新增代码的总体核查（无发现，作为正面结论记录）

- **`vue-tsc -b --force` 退出码 0**（真实退出码，非推断）→ 新增的 `utils/ws.ts`、`utils/download.ts`、`ACTION_DONE` 记录、两个组件的联合类型均类型安全，无未使用变量/参数（`tsconfig.json` 开了 `strict`/`noUnusedLocals`/`noUnusedParameters`）。
- **`disposed`/定时器纪律**：两个组件的 4 个定时器（`flushTimer`/`writeTimer`/`tickTimer`×2）与 2 个 socket 的建立/销毁路径**逐条对齐**，无悬挂回调（详见 C-02 表）。
- **协议判定收口**：`utils/ws.ts` 把「什么算错误帧」「什么码该重连」「怎么向用户解释」三件事集中到一处，两个 WS 组件共用，避免了双份实现漂移——这是本轮**最好的设计决策**。
- **`isRetryableClose` 是实测正确的**（不是纸面正确）：我最初从活体探针看到的 1005 差点导向「无限重连」的误判，用 `evidence/probe-close-codes.mjs` 消歧后确认**服务端 close 一律是 1000**（客户端自己 close 才是 1005），因此 `1000 → 不重连` 的分支既可达又正确。
- **`README`/`spec`/`scope` 本轮无回写遗漏**：`spec.md` 的 diff 只动了 6 行，`scope.md` 动了 3 行（属其它透镜的范围，本报告不裁决）。

---

## 三、关闭判定一览

| 编号 | 上一轮发现 | 严重度（本轮） | 关闭判定 | 一句话理由 |
|:--:|------|:--:|:--:|------|
| C-03 | nginx `Host $host` 丢端口 | 🟡 | **CLOSED** | 两处都改 `$http_host`；旧行为实测复现（307 → 未监听的 80）；`proxy_redirect` 不需要；**需重建镜像才生效** |
| C-05 | 暂停/恢复无 UI 入口 | — | **CLOSED** | 按钮→`act`→api→后端链路完整；`running/paused` 分支正确；无死按钮；有成功/失败反馈 |
| C-02 | 节流/重连/防抖三项 | 🟡 | **PARTIAL** | 三项都落地、定时器与丢弃策略无缺陷；但**退避成功后不复位**（N-01），只算半个标准指数退避 |
| C-17 | 下载假成功 | 🟡 | **PARTIAL** | 两类 500 实测被预检拦住、失败分支确不提示成功；但引入**预检无超时/无取消**（N-02）与「200 后中途失败仍假成功」（N-05） |
| C-18 | 超时与 E2E 预算矛盾 | — | **CLOSED** | `create`/`commit` 用 300s ≥ E2E 的 180s/120s；`NO_TIMEOUT` 仍只给 pull（全文件仅 1 处引用）；仅注释归因需修正（N-07） |
| C-09 | `.env` 4 变量只有 1 个生效 | 🟡 | **CLOSED（+1 残留）** | 四变量名字/默认值与 `deployment.md` §4.2 逐项一致，`docker compose config` 实测 `.env` 三个变量都生效；但「留空关闭镜像源」被 `:-` 破坏（N-08） |
| C-16 | 无 `.dockerignore`，上下文 118.2 MB | — | **CLOSED** | 上下文 **118.2 → 0.2 MB**（后端 45.4 → 0.215 MB）；保留清单逐文件核对**无任何误排除**；与 `Dockerfile` 的 `npm ci` 顺序自洽（排除 `node_modules` 正是其前提） |

---

## 四、发现清单汇总

| 编号 | 严重度 | 位置 | 描述 | 性质 | 关闭判定 |
|:--:|:--:|------|------|:--:|:--:|
| N-01 | 🟡 | `ContainerLogs.vue:204-208,271,313`；`ContainerTerminal.vue:240-246,301,346` | 退避计数成功后不复位，一次抖动把重连延迟永久钉在 30s | JUDGEMENT | PARTIAL（C-02） |
| N-02 | 🟡 | `utils/download.ts:30-43`；`FileCopyDrawer.vue:118-127`；`ImagesView.vue:181-192` | 预检无超时无取消 → 后端卡住时按钮永久 loading | HARD | NEW |
| N-03 | 🟡 | `ContainersView.vue:109-119`；`backend/app/routers/ws.py:229-239` | paused 容器仍可「进入终端」，`exec_create` 永久阻塞 | JUDGEMENT | NEW |
| N-04 | 🟢 | `utils/ws.ts:24-39` | `{"error":"..."}` 形状的 JSON 日志行被判为控制帧而被吞 | JUDGEMENT（契约本身要求如此） | NEW |
| N-05 | 🟢 | `utils/download.ts:39-43` | 预检只校验状态行，200 之后的中途失败仍显示「已开始导出」 | JUDGEMENT | NEW |
| N-06 | 🟢 | `ContainerLogs.vue:202,267`；`ws.py:103-109` | 重连重放 `tail`（最多 2000 行）导致重复行刷屏（内存有界、可读性无界） | JUDGEMENT | NEW |
| N-07 | 🟢 | `api/index.ts:59-61` | 注释把 E2E 的 120s 归因给 `commit`（实为 `pull`），导出端点无前端超时 | JUDGEMENT | NEW |
| N-08 | 🟡 | `deploy/docker-compose.yml:16` ↔ `docs/deployment.md:104-108` | `${VAR:-default}` 使「留空关闭镜像源」失效（实测仍用默认镜像源） | HARD | NEW（C-09 残留） |
| N-09 | 🟢 | `ContainersView.vue:88-107,280-288` | 新增按钮无在途保护，双击可撞 daemon 500（paused→stop） | JUDGEMENT | NEW |

**计数**：🔴 0 · 🟡 4（N-01 计入 C-02 未关闭项、N-02、N-03、N-08）· 🟢 5（N-04/05/06/07/09）

---

## 五、亮点

1. **`utils/ws.ts` 的三合一收口是本轮最好的设计**：协议判定、重连决策、用户措辞集中一处，两个 WS 组件共用；`isRetryableClose` 的 1000/1008 判定**经活体探针消歧后证明正确**（服务端 close 实测 1000，客户端自己 close 才是 1005——这是一个很容易被误读成「无限重连」的陷阱，实现躲过了）。
2. **`dropSocket()` 先摘 4 个 handler 再 close**（`ContainerLogs.vue:298-307`、`ContainerTerminal.vue:328-337`）：避免了「自己触发的 `onclose` 再排一次重连」这个经典自激 bug，注释说「Detach first」且代码确实如此。
3. **终端缓冲用的是单个字符串而不是数组**（`ContainerTerminal.vue:73,376-387`）：跨帧拆开的转义序列天然不会错位，比「按帧 push 再 join」更稳，注释里的理由（ordering cannot be lost）是**真的**。
4. **C-16 的 `.dockerignore` 写得很懂 Dockerfile**：不只是压体积，还专门排除 `vite.config.js`（防 `.js` 遮蔽 `.ts`）——这条只有踩过 `vue-tsc -b` 产物污染的人才写得出来，且实测排除清单零误伤。
5. **`download.ts` 把「为什么必须预检、为什么下载仍走直链、代价是什么」写在 docstring 里**，包括主动承认「每次下载多付一次被中止的导出」——这是把设计取舍留给后来者的正确做法；我实测到的那次多付出（300ms 内 10 MB）正好印证了它的诚实。
6. **`e2e_verify.py` 的修复方向对**：`EXPECTED_CHECKS=18` + `sys.exit(main())` + 「收到帧但没有真实日志行 → FAIL」+「删除后用重新 list 证明 tag 真的没了」，把上一轮点出的三类假绿通道都堵上了。

---

## 六、未验证项（明确没做的事）

| # | 项 | 原因与影响 |
|:--:|------|------|
| 1 | **nginx `$http_host` 在镜像内的真实效果** | 运行中的 `dockermgr-frontend` 是**旧镜像**（`Server: nginx/1.31.5`，307 实测仍见端口丢失）；`docker`/`docker compose exec` 被沙箱以命名管道权限拒绝（`permission denied ... npipe:////./pipe/dockerDesktopLinuxEngine`），审批已禁用 → **无法重建镜像**。C-03 的「新配置正确」是**静态推演 + 旧行为实测**的合成结论，**不是**镜像内实测。需要一次 `docker compose up -d --build frontend` 后复跑 `curl -i http://127.0.0.1:8088/api/containers/` 才能收尾（期望 `location: http://127.0.0.1:8088/api/containers`） |
| 2 | `res.body.cancel()` 是否让**服务端立即**停写 | 需要 `starlette` 在 `spec_version < (2,4)` 分支下主动 cancel `stream_response` 任务；本机 `starlette 1.6.0` 存在该分支，但 **uvicorn 0.52.4 上报的 `spec_version` 未实测** → 只能确认「客户端 cancel 成功、不抛错」与「后端确实被启动了两次导出」，**不能**断言「取消时 daemon 立刻停手」 |
| 3 | 预检造成的真实浪费量 | `probe-preflight-cost.mjs` 的 10 MB/300ms 是**我的 Node 主动读满 300ms** 的结果，不是浏览器行为；浏览器在 headers 到达（约 130–180ms）后立即 cancel，实际丢弃量只有 TCP/socket 缓冲。**两个数都不是「浪费量」的准确值**，只能作为「导出确实被启动」的证据 |
| 4 | 浏览器侧渲染/交互验证 | Playwright 被沙箱拒绝（`WinError 5` / 命名管道），**无法**验证：重连提示的视觉表现、326px 列宽在真实字体下的换行、暂停/恢复按钮的 loading 观感、`el-alert` 在深色抽屉里的对比度。N-09 的「双击撞 500」是按 **Docker 语义 + 代码无守卫** 推定的，**未在真机复现** |
| 5 | `docker compose build` 实跑 | 无 daemon 权限 → C-16 的「上下文 0.2 MB、无误排除」是**按规则重算 + 逐文件核对**的静态结论；末段 `docker build` 是否成功、镜像内 `dist/` 大小均未实测 |
| 6 | `.env` 留空语义在**其他 compose 版本**下的行为 | 我在本机 `Docker Compose version v5.5.1`（`docker compose config`）实测 `IMAGE_MIRRORS=` 仍取默认值。不同版本对「空值是否算未设置」的处理可能不同 → N-08 的修法（`:-` → `-`）在语义上更正确，但**建议在目标机器上复验一次** |
| 7 | `commit` 的真实耗时是否可能超过 300s | 未在真机用大文件系统复现；`LONG_OP_TIMEOUT=300000` 是**安全网**而非实测阈值。若某镜像的 commit 真会 >5 分钟，用户在 300s 后仍会看到超时（而后端在继续） |

---

## 七、证据文件（可复跑）

均在 `docs/epics/docker-manager-v1/test-review/rd2/evidence/`：

| 文件 | 用途 | 运行方式 |
|------|------|---------|
| `probe-ws.mjs` | `parseServerErrorFrame` / `isRetryableClose` / `describeWsError` 的真值表（N-04 的证据） | `node --experimental-strip-types evidence/probe-ws.mjs`（需把 `ws.ts` 放在同目录，见 `ws.snapshot.ts`） |
| `probe-ws-extra.mjs` | 对抗用例：真实世界 JSON 日志行是否会被误判为控制帧；`isRetryableClose(1005/1000/1006)` | `node --experimental-strip-types evidence/probe-ws-extra.mjs` |
| `probe-retry.mjs` | 重连状态机逐字转写 + 4 个场景（N-01 的证据） | `node evidence/probe-retry.mjs` |
| `probe-download.mjs` | 预检 fetch 的 200/500/断网/307 行为（C-17 的证据） | `node evidence/probe-download.mjs`（需 8088 在跑） |
| `probe-preflight-cost.mjs` | 预检确实触发一次真实导出（C-17 代价的证据） | `node evidence/probe-preflight-cost.mjs` |
| `probe-ws-live.mjs` | 活体 WS 协议帧（错误帧形状、帧计数） | `node evidence/probe-ws-live.mjs` |
| `probe-close-codes.mjs` | 消歧 1005（客户端 close）vs 1000（服务端 close） | `node evidence/probe-close-codes.mjs` |
| `ws.snapshot.ts` | 被审 `utils/ws.ts` 的快照（供 `probe-ws.mjs` 导入） | — |

> 说明：这些探针脚本是我在 `D:\桌面\测试\_rd2_probe\` 下临时编写并运行后**归档到本目录**的副本，**未修改任何产品代码**（`git status` 对照确认工作区改动面与本轮审查开始时完全一致）。
