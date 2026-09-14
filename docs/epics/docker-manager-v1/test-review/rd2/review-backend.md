# CDM Phase 4.6 修复后重审 — 后端透镜（rd2 / review-backend）

> Epic：`docker-manager-v1`
> 审查对象：**工作区未提交的修复批次**（提交基线 `8149029`，`git diff` + 未跟踪新文件）
> 审查者透镜：**后端**（`backend/**`，含部署配置中与后端契约相关的部分）
> 审查时间：2026-09-11
> 审查方式：**隔离子代理独立审查**——不参与编码、不继承编码上下文；**不采信注释/commit message/报告自述**，全部结论以实跑 + 变异测试（mutation testing）+ `文件:行号` 为证据
> OCR 预扫：未执行（沿用 rd1 结论：ocr CLI 未配置 LLM 端点）

---

## 0. 审查方法与实跑证据总表

| 项 | 命令 / 手段 | 真实结果 |
|----|------|------|
| 后端全量单测 | `cd backend; $env:UV_CACHE_DIR='D:\桌面\测试\.uv-cache'; uv run --frozen pytest -q` | **105 passed, 2 warnings in 2.75s**（rd1 为 66 → 新增 39 个用例）✅ |
| 仓库污染复核 | 跑测后 `git status --short --untracked-files=all -- backend` + `Get-ChildItem -Recurse -Filter a.txt` | 无 `a.txt`、无 `_staging` 残留；`D backend/a.txt` 已暂存删除 ✅ |
| docker-py 语义核验 | 读 `backend/.venv/Lib/site-packages/docker/models/images.py:80-120` | docker-py **7.2.0**，`save(chunk_size, named=False)`；`named=True` → `img = self.tags[0] if self.tags else self.id` ✅ |
| **变异测试（决定性手段）** | 注入 9 个变异体，逐个跑相关测试 | 见 §0.1——**8 个被杀、1 个存活（即新发现 N-01）** |
| 真实 WS 服务端探测 | 起 uvicorn（随机端口）+ `websockets` 真客户端，按 `Origin` 逐项打 `/ws/logs` | 见 §0.2 ✅ |
| 线上栈契约探测 | HTTP 到 `http://127.0.0.1:8088`（沙箱可用） | 见 §0.3——**线上仍是修复前构建** ⚠️ |
| E2E / `docker` CLI / Playwright | `docker version`、Playwright | ❌ **环境限制**：沙箱禁 Docker Desktop 命名管道（`permission denied npipe` / `WinError 5`）、Playwright `WinError 5`。**不作为产品缺陷记录** |

### 0.1 变异测试结果（证明「测试真的能失败」）

| # | 变异体（注入的缺陷） | 相关测试结果 | 判定 |
|:--:|------|------|:--:|
| M1 | `volumes.py` 去掉 `embed=True` | `test_volume_create_accepts_object_body` **FAILED** `assert 422 == 200`，body `{"type":"string_type","loc":["body"],"input":{"name":"app-data"}}` | **被杀死** ✅ |
| M2 | `images.py` 去掉 `named=True` | `test_image_save_streams_and_keeps_the_name` **FAILED**（`named=False drops repository:tag`） | **被杀死** ✅ |
| M3 | `_find_container` 只遍历 running（`(False,)`） | `test_ws_logs_streams_a_stopped_container` **FAILED** | **被杀死** ✅ |
| M4 | `/ws/exec` 删掉 `NotFound` 错误帧 | `test_ws_exec_reports_missing_container` **FAILED** | **被杀死** ✅ |
| M5 | `security.py` 令 `is_same_site` 恒真 | `test_security.py` + 端点覆盖 **7 failed** | **被杀死** ✅ |
| M6 | `main.py` 禁用 HTTP 中间件（`if False and ...`） | `test_cross_site_write_is_rejected` **FAILED**（证明中间件是承载守卫） | **被杀死** ✅ |
| M7 | `/ws/logs` 删掉 `{"error":"no container"}` 帧 | `test_ws_logs_reports_missing_container` **FAILED**（`WebSocketDisconnect`） | **被杀死** ✅ |
| M8 | `ws.py` 删掉 `ws_logs` 的 Origin 守卫 | `test_ws_handshake_from_a_foreign_page_is_rejected` **FAILED**（`DID NOT RAISE WebSocketDisconnect`） | **被杀死** ✅ |
| M9 | `ws.py` 删掉**计时器线程**（`timer.start()` → `pass`） | **17 passed** —— 全部既有测试仍通过 | ☠️ **存活 → 新发现 N-01** |
| M10 | `ws.py` 把 `except docker.errors.NotFound` 放宽为 `except Exception` | **17 passed** | ☠️ 存活 → 新发现 N-04 |

> 独立计量实验（证明 `M9` 不是「变异体无效果」而是「测试无牙」）：自建探针（长命流 600 行、间隔 3ms、统计合并前后帧数）
> - **正常代码**：`lines_sent=600 frames=19` ✅ 真批处理
> - **去掉计时器线程**：`lines_sent=600 frames=1` ❌ 只剩收尾那一次 flush
> - 而**既有 17 个测试在两种情况下都通过** → `test_ws_logs_batches_lines_into_one_frame` 无法分辨二者。

### 0.2 真实 WS 握手探测（uvicorn 真服务端 + 真 `websockets` 客户端）

| 客户端 `Origin` | 服务端实际行为 |
|------|------|
| **无 Origin**（服务端脚本/wscat） | `CONNECTED`，随后 1000（放行，策略文档已声明） |
| `http://evil.example` | **`InvalidStatus: server rejected WebSocket connection: HTTP 403`** ✅ |
| `http://127.0.0.1:<port>`（面板自身） | 放行（走到 docker 调用，本沙箱因 npipe 失败 → 属环境限制） |
| `http://localhost:<port>` | 放行 ✅ |
| `null` | **403** ✅（`file://`/沙箱 iframe 被挡） |
| `http://127.0.0.1.evil.example` | **403** ✅（前缀仿冒被挡） |
| `http://127.0.0.1:9999`（**端口不同**） | **放行** ⚠️ → 新发现 N-03 |

### 0.3 线上栈探测（`http://127.0.0.1:8088`）——⚠️ **线上是修复前的构建**

| 探针 | 结果 | 含义 |
|------|------|------|
| `GET /api/health` | `{"status":"ok"}` | nginx→backend 链路可用 |
| `POST /api/volumes {"name":"rd2-probe-…"}`（**前端真实形状**） | **422** `{"type":"string_type","loc":["body"],"input":{"name":"rd2-probe-05aeb41a"}}` | 线上仍按 **裸字符串** 解析 → **C-01 的代码路径在线上依然存活** |
| `POST /api/volumes "rd2-probe-…"`（裸 JSON 字符串） | **200 `{"ok":true}`** | 决定性证据：线上是 **pre-fix** 构建（已立刻 `DELETE`，200） |
| `POST /api/volumes` + `Origin: http://evil.example` | **422**（**非** 403） | 线上**没有**跨站中间件 → C-08 的 HTTP 守卫未上线 |
| `POST /api/volumes` + `Origin: http://127.0.0.1:8088` | **422**（非 403） | 同上 |
| `GET /api/volumes` + 外部 Origin | 200 | 与「读不设防」的设计一致 |
| 卷计数 | 前 8 / 后 8，无 `probe` 残留 | **审查副作用已复原** ✅ |
| `GET /openapi.json` | 444 B `text/html`（SPA 回退） | nginx 只代理 `/api`、`/ws`，无法从线上核对 schema |

> **这不是源码缺陷，而是交付/部署缺口**：`deploy/docker-compose.yml` 的 backend 是 `build:` 且无 bind-mount（无热重载），线上镜像仍是旧构建。**只要不重建重启，唯一的 🔴 Critical 在用户面前依然是「点创建卷就报错」**。记为 N-06。

### 0.4 审查副作用披露（全部已复原）

- 变异测试**改动了 6 个产品文件**（`volumes.py`/`images.py`/`ws.py`/`security.py`/`main.py`/`files.py`），**每个变异体跑完立刻还原**；全部还原后用 `Get-FileHash` 与备份逐一比对 **完全一致**，并 `ast.parse` 确认语法。
- 中途一次误操作：为撤销 M6 我执行了 `git checkout -- app/main.py`，**把未提交的中间件修复打回了 HEAD**（`main.py` 一度丢失 `cross_site_guard`）。已按原 diff 逐字重建，并以 `git diff --stat` 复核恢复无误：
  `backend/app/main.py | 25 +++++++++++-`、`6 files changed, 149 insertions(+), 19 deletions(-)` —— 与动手前捕获的输出**逐字一致**。**已复原**，但如实披露。
- 临时探针文件（`_mutate_ws.py`/`_ws_probe.py`/`_enc_probe.py`/`test_zz_*.py`/`probe_batching.py`）**已全部删除**（`Get-ChildItem` 复查为空）。
- 线上探针创建并立即删除了 1 个卷 `rd2-probe-05aeb41a`（卷数 8→8，无残留）。
- 未修改任何产品代码的**最终状态**：`git status --short --untracked-files=all -- backend` 与审查开始时**完全一致**。

---

## 1. Plan alignment（对照 spec/scope）

**Verdict: ⚠️（无未关闭 🔴/🟡；1 条 🟢 文档回写）**

本轮修复批次基本不触碰 scope/spec 的功能清单，而是修缺陷与补测试，故 plan alignment 面无新增缺口。逐条核对：

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟢 | `docs/epics/docker-manager-v1/README.md:102` | **C-22 的残留**：`README.md:75`「未完成项」的过期表述**已改对**（「已修复（8149029）」✅），但同一份看板的自述仍然不准——见 §1.1 的四点逐条核对。 | **HARD** | 看板自述与实测不符（无 spec 条款，属文档一致性） |

### 1.1 C-22 逐点核对（实测）

| README 位置 | README 说法 | 实测 | 判定 |
|------|------|------|:--:|
| `:75` | `.gitignore` 忽略 `uv.lock` → **已修复（`8149029`）** | `git ls-files backend/uv.lock` 有跟踪、`git check-ignore` 无命中 | ✅ **已改对**（C-22 主项关闭） |
| `:77` | 「Phase 4.6 审查发现（1 🔴 / 20 🟡）」= **待修复** | 修复批次已在工作区落地（本报告逐条验证） | ⚠️ **仍写「待修复」**，且未说明「工作区已修、未提交、重审进行中」 |
| `:78` | 「**审查核实**：三个视图文件实际均已独立存在（commit `7cfa52c`）」 | 该句**在 `git diff` 里是本轮新增**（`git diff` 显示 README +12/-…）；即 README 把「审查者自己的核实」写成既有事实——表述可接受，但它是**本批次新写的** | 🟢 表述可接受 |
| `:102` | 「后端单元测试 = **66 passed**」 | **实测 105 passed** | ⚠️ **未同步**（终态验证证据表还留着旧数） |
| `:23` | Phase 4.6 一行仍为旧结论「❌ NEEDS FIXES」（对应 `:18`） | 与本轮「修复后重审」应有的状态不一致 | 🟢 建议在重审结论确定后一并更新 |

**修复建议（文档回写，一行改动量级）**：
1. `README.md:77` 改为「**源码已修复（工作区未提交，待 `rd2` 重审确认）**」，并列出本报告 §3 的关闭判定摘要；
2. `README.md:102` 的「66 passed」→「105 passed」；
3. 待重审结论落地后再在 `:18`/`:23` 追加「Phase 4.6 重审」一行。

**亮点（Plan alignment）**
- 修复批次**没有偷范围**：改动集中在 rd1 明确指出的缺陷点与配套测试，未引入新的端点/配置项/依赖（`git diff --stat` 可见 `backend/app` 仅 6 文件、+149/-19）。
- 所有修复都在**既有契约内**完成，未改动冻结的 WS 错误帧契约（仍是「文本帧内含 `{"error": "..."}` 对象」），并以 `frontend/src/utils/ws.ts` 在客户端侧对齐。

---

## 2. Code quality

**Verdict: ⚠️（无未关闭 🔴/🟡；3 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟢 | `backend/app/routers/ws.py:157-160`（配合 `:138-141`） | **N-02 收尾竞态（可重复帧）**：`pump` 的 `finally` 执行 `finished.set()` → `flush()`，而 `flusher` 线程的循环是 `while not finished.is_set(): finished.wait(0.1); flush()`。`finished.wait()` 的返回有两条路径（超时返回 False / 被 set 返回 True），**两条都会继续执行 `flush()`**。因此在「pump 进入 finally 的同一瞬间 flusher 恰好超时」时，两个线程都可能通过 `if not pending …` 检查，把**同一批行发两次**；即使不重复，也可能在线程退出后再发一帧空 `chunk`。窗口极窄、后果是多一行日志，故 🟢。 | JUDGEMENT | 无明文依据（读码 + 时序分析） |
| 🟢 | `backend/app/routers/ws.py:128-133` | **N-05 丢弃标记可能与日志行黏连**：`chunk = f"... N lines dropped ...\n" + chunk`，而 `chunk = "\n".join(pending)`。若 buffered 的首行是空串（容器输出空行时 `line.decode().rstrip("\n")` 可为 `""`），标记行会与首个空行合并，显示上少一次换行。纯显示瑕疵。 | JUDGEMENT | 无明文依据 |
| 🟢 | `backend/app/services/files.py:26-28` | **N-06 `clear_tmp_dir` 静默吞错**：`except OSError: pass` 使「临时目录里删不掉的残留」在启动时**无任何日志**。属「启动不得因残留而失败」的合理取舍，但排障时会丢现场（项目本身也没有 logging 配置，rd1 §5 已记同类问题）。 | JUDGEMENT | `spec.md:49` |

**亮点（Code quality）**
- `files.py` 的重构质量高：把 3 步阻塞操作**整体**抽成纯阻塞函数 `_stage_and_push`，`finally` 里 `local.unlink(missing_ok=True)` 用 `missing_ok` 把「成功路径已删」与「失败路径未建」两种情形统一处理，**成功/失败两条路径都无残留**（`test_files_api.py:71,100` 双向断言）。
- `ws.py:124-136` 的 `flush()` 用 `with lock:` **只包住状态变更**，把 `_send_from_thread(...)` 放到锁**外**——避免持锁调用事件循环调度，是对的方向（否则 flusher 线程会与 pump 线程在调度上互相阻塞）。
- `except docker.errors.NotFound` 用**精确异常类**而不是 `except Exception`（`ws.py:223`），语义正确；`is_same_site` 用**等值比较**而非 `startswith`，前缀仿冒被实测挡住。
- `services/security.py` 的模块 docstring 把**威胁模型**（浏览器中介、同源策略不覆盖 WebSocket）与**策略四条**写清楚，是本次新增代码里最有价值的一段注释——它解释了「为什么 localhost 绑定不够」。

---

## 3. Architecture

**Verdict: ⚠️（无未关闭 🔴/🟡；1 条 🟢）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟢 | `backend/app/services/security.py:28` | **N-03 `0.0.0.0` 在 localhost 白名单里，与 spec 的绑定要求不自洽**：`LOCAL_ORIGIN_HOSTS = {"localhost","127.0.0.1","::1","[::1]","0.0.0.0"}`。`spec.md:111` 要求「仅映射 `127.0.0.1:8088`、禁止后端暴露 0.0.0.0」，而 `deploy/docker-compose.yml` 的 backend 只 `expose: 8088`（未 publish）→ 正常情况下**不可能**出现 `Origin: http://0.0.0.0:8088`。把它放进白名单是**把「不该发生的部署形态」当合法来源**，属纵深防御上的自相矛盾（当前不可利用，故 🟢）。 | JUDGEMENT | `spec.md:111`、`deploy/docker-compose.yml:16-17` |

**亮点（Architecture）**
- **Origin 守卫的落点正确**：HTTP 侧用 `@app.middleware("http")` 覆盖**全部** `POST/PUT/PATCH/DELETE`，而不是逐路由挂依赖——新增写端点自动受保护，不存在「漏挂」风险（M6 证明它是承载守卫）。
- **WS 侧守卫在 `accept()` 之前**（`ws.py:85-90`、`:205-210`），符合要求；实测外部 Origin 在**握手阶段**就被 `HTTP 403` 拒绝（§0.2），浏览器拿不到已建立的连接。
- 保留 HTTP 中间件与路由内检查**双重** WS 守卫（中间件 403 + 路由 1008）属**有意冗余**，方向正确：前者覆盖 `/ws/exec` 这类「路由内忘了检查」的新端点，后者在中间件被移除时兜底。
- 前端 `isRetryableClose` 把 `1000`/`1008` 明确判为**不可重试**（`frontend/src/utils/ws.ts`），与后端「1008 = 跨站拒绝、重试必然同样失败」的语义闭合——两侧对同一契约的理解一致，是跨层契约对账的好例子。

---

## 4. Testing

**Verdict: ❌（1 条新 🟡 = N-01；其余关闭）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | `backend/tests/test_ws_logs.py:74-91` | **N-01 批处理回归测试无牙（同义反复的新变体）**：`test_ws_logs_batches_lines_into_one_frame` 用 `_Stream([b"l1\n", b"l2\n", b"l3\n"])` —— 这个 mock 流**立刻结束**，于是 `pump` 的 `finally` 里那句 `flush()` 一次性把 3 行发完，测试断言 `frame.split("\n") == ["l1","l2","l3"]` **必然成立**，与「批处理/计时器线程」毫无关系。**决定性证据**：删掉**整个计时器线程**（`timer.start()` → `pass`）后，`pytest tests/test_ws_logs.py tests/test_endpoints_coverage.py` 仍 **17 passed**；而独立探针显示同样代码把 600 行压成 **1 帧**（正常为 19 帧）。即：**C-02 的核心机制（计时线程驱动的周期 flush）没有任何回归测试保护**，而它恰好是 rd1 没见过的、最容易写错的部分。 | **HARD** | `spec.md:113`（「消息节流」明文对策）；`plan.md:T7`（该 Task 验证要求） |
| 🟢 | `backend/tests/test_endpoints_coverage.py:251-268` | **N-04 对「非 404 故障」的诊断不精确，且无测试区分**：`ws.py:221-227` 把 `docker.errors.NotFound` 一律翻成 `no such container: <name>`，且前端 `describeWsError` 对匹配 `no container` 的文案追加「容器可能已被删除或改名，请刷新列表后重试」。若 daemon 在 `containers.get` 时抛 `NotFound` 之外的错误（连接断开等）→ 走 `except Exception` → 只记日志、静默关闭，用户看到「已断开」而无原因。**把 `except docker.errors.NotFound` 放宽为 `except Exception` 后 17 个测试仍全绿**（M10），说明「错误分类」这一行为无测试锁定。 | JUDGEMENT | 无明文依据 |
| 🟢 | `backend/tests/test_files_api.py:15-38` | **staging fixture 的非标准 `return` 路径未经覆盖**：`staging_dir` 在 `tmp_path_factory` 成功时用 `return`（而非 `yield`）。**实测本沙箱下 `tmp_path_factory.mktemp()` 必抛 `PermissionError: [WinError 5] …\pytest-of-25893`**（`OSError` 子类），故实际**只走 `except` 分支**——`return` 路径在本机与 CI 都可能执行，但从未被验证。属可延后项。 | JUDGEMENT | 无明文依据（实测见 §0） |

### 4.1 上一轮测试类发现的逐条关闭判定

| rd1 编号 | 位置 | 本轮实测证据 | 判定 |
|:--:|------|------|:--:|
| **C-13** | `test_files_api.py` + `backend/a.txt` | ① `git ls-files backend/a.txt` **空**；② 文件已 `D` 暂存删除、磁盘上 `Test-Path` = `False`；③ 改用 `tmp_path_factory`（`test_files_api.py:16-38`）并**双向断言**无残留（`:71`、`:100`）；④ 连跑 3 次全量测试后 `git status` 仍无新增未跟踪文件、无 `a.txt`、无 `_staging` 残留 | ✅ **CLOSED** |
| **C-14** | `test_ws_logs.py` 假绿 | `assert msg.get("error") == "no container"` 已移到 `with` 块**之后**（`:49-51`），全文件**无任何 `try/except`**；M7 证明删掉错误帧该用例立刻 FAILED（不再是恒真） | ✅ **CLOSED** |
| **C-15** | 14 端点零单测 | 新增 `test_endpoints_coverage.py`（324 行、14 用例），把 `volume/network create`、`pause/unpause`、**F6 commit**（成功+失败）、**F7 save 流式导出**（成功+失败，并断言 `named=True`）、**F10 拷出**（成功+失败）、`/ws/exec` 错误帧、跨站守卫 4 例全部纳入；全量 **66 → 105 passed**。**仍未直接覆盖**（需真 daemon，本环境不可跑）：`list (containers/images)`、`start/stop/restart`、`DELETE container`、`GET container detail`、`DELETE image`、`pull`/`pull/mirrors`、`networks/volumes delete` | ⚠️ **PARTIAL（大幅改善，非违规）** |

> C-15 的 PARTIAL 判定理由：rd1 已明确记为 **JUDGEMENT**（`plan.md:T3-T6` 只要求「路由存在」级测试），而本轮补齐的恰是**三条主线能力（F6/F7/F10）+ 守卫**，风险敞口最大处已覆盖；余下未覆盖项的失败模式与已覆盖项同型（`except Exception → 500`），边际收益递减。

### 4.2 新增测试的「能否失败」逐项核验（无同义反复残留）

- 逐文件扫描 `backend/tests/` 全部 10 个测试文件：**无 `try/except Exception: pass` 包裹断言**、**无 `assert True`**、**无 `pytest.skip`**、**无 `xfail`**。
- **mock 形状核验（对照 docker-py 7.2.0 实测签名）**：
  - `Image.save(self, chunk_size=2097152, named=False)` ↔ `test_endpoints_coverage.py:166` `def save(self, named=False)` ✅ 一致；
  - `Container.commit(**kwargs)` → 实现传 `repository=`/`tag=`（`test_endpoints_coverage.py:136` 断言 `{"repository":"myimg","tag":"v1"}`）✅；
  - `containers.get(cid)` 抛 `docker.errors.NotFound`（真类）✅（`:257` 用真异常类构造，不是自造 `Exception`）；
  - `containers.list(all=...)` 带 `all` 关键字 ✅（`test_ws_logs.py:27`）；
  - `client.api.exec_create/exec_start` 未在此批新增 mock（沿用 rd1 已核验的形状）。
- **`test_security.py` 的边界完备性**：`local:8088` / `127.0.0.1:8088` / `[::1]:8088` / `http://[::1]` / `127.0.0.1.evil.example` / `null` / `not a url` / 空串 / 纯空白 逐项有断言，且含**前缀仿冒**与**大小写归属**等真实绕过尝试 ✅。

**亮点（Testing）**
- **变异测试视角看，本轮 8/10 个注入缺陷被既有测试杀死了**——这是本套测试从「能跑」到「能守」的实质跃迁，尤其 M1/M2/M3/M4/M7/M8 六个都直接锚定 rd1 的具体发现。
- `test_files_api.py` 的两个用例**成对**（失败路径断言「残留为空」、成功路径断言「解密出的 tar 内容正确且残留为空」），把「清理」这个最容易漏的语义钉死在两条路径上。
- `test_ws_logs_blocking.py`（rd1 亮点）被保留并调整（`git diff` 有改动），维持了「真机级事件循环阻塞回归」这条最有价值的用例。
- 用例命名即断言意图（`test_cross_site_write_is_rejected`、`test_reads_are_deliberately_not_guarded`），后者甚至把「GET 是有意不设防的**设计决定**」写成测试，防止后人误「修」。

---

## 5. Production

**Verdict: ❌（1 条 🟡 = N-07 部署缺口；其余关闭）**

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|:--:|------|
| 🟡 | 线上 `http://127.0.0.1:8088`（构建来源 `deploy/docker-compose.yml:2-4`） | **N-07 线上栈仍是修复前构建 → 唯一的 🔴 Critical 在用户面前依然存活**（半新发现：rd1 记的是「C-01 存在」，本轮记的是「C-01 的修复未生效」）。实测：前端真实形状 `{"name":…}` → **422**；裸字符串 → **200**（这正是 pre-fix 契约）；外部 Origin 的写请求 → **422 而非 403**（证明跨站中间件未上线）。compose 的 backend 是 `build:`、无 bind-mount、uvicorn 无 `--reload` → **不重建重启就不会生效**。 | **HARD** | `spec.md:111`（安全对策）、rd1 C-01/C-08；实测见 §0.3 |
| 🟢 | `backend/Dockerfile:2,8-12` | rd1 的 🟢 未修（`uv:latest` 未固定；`COPY app ./app` 在 `RUN uv sync` 之前 → 改源码即废依赖缓存）。**不属本批次范围**，仅记录。 | JUDGEMENT | `spec.md:60`（D7 只约束依赖） |

### 5.1 C-04（异步阻塞）关闭判定：CLOSED

| 检查项 | 证据 | 结论 |
|------|------|:--:|
| 是否把**全部**阻塞步骤搬出事件循环 | `files.py:16-23` 新增 `_stage_and_push`，把 `local.write_bytes(data)` + `tarfile` 打包 + `put_archive()` **三步**一起搬进 worker 线程；处理器内在 `await asyncio.to_thread(...)` 之前**只剩** `to_thread` 调用本身（`await file.read()` 是异步 I/O，不阻塞循环） | ✅ |
| 参数传递安全性 | `await asyncio.to_thread(_stage_and_push, cid, dest, local, data)` —— 全位置参数，不会触发 `to_thread` 的关键字透传陷阱 | ✅ |
| 失败路径清理 | `finally: local.unlink(missing_ok=True)`（`files.py:29-31`） | ✅ |
| 成功路径清理 | 同上（`finally` 对两条路径生效） | ✅ |
| 测试覆盖 | `test_copy_into_failure_is_reported_and_leaves_no_temp_file`（断言 500 + `list(staging_dir.iterdir()) == []`）、`test_copy_into_success_pushes_a_tar_and_cleans_up`（断言 tar 内 `["hello.txt"]` 与内容 + 残留为空） | ✅ |
| `File(filename=None)` 健壮性 | `file.filename or "upload.bin"`（`files.py:19`） | ✅ 顺带修好 |

> 唯一**未变**的是 rd1 另一条 🟢（内存三份拷贝：`await file.read()` 的 bytes → `BytesIO` 的 tar → `put_archive` 的请求体）。本轮**未声称**修它，rd1 也判 🟢（`spec.md:49` 兜底），故不重复开条目。

### 5.2 附：`clear_tmp_dir` 的正确性与副作用

- `get_tmp_dir()` 自带 `d.mkdir(parents=True, exist_ok=True)`（`files.py:9`），`clear_tmp_dir` 先调它（`:19`）→ **不存在「目录不存在导致 `iterdir()` 抛错」** ✅
- 新增 `shutil.rmtree(p, ignore_errors=True)` 处理子目录（`:23`），配合 `except OSError: pass` 保证**启动不会被残留阻断**；`unlink(missing_ok=True)` 处理文件 ✅
- 该函数在 `lifespan` 启动时执行（`main.py:16-18`）→ 即使 `files.py` 的 `finally` 因进程被 kill 而未执行，也能在下次启动清干净，**两层兜底成立** ✅

---

## 6. 发现清单汇总（含关闭判定）

### 6.1 上轮发现（后端相关）逐条关闭判定

| 编号 | 严重度 | 位置 | 关闭判定 | 关键证据 |
|:--:|:--:|------|:--:|------|
| **C-01** | 🔴 | `volumes.py:24` | ✅ **CLOSED**（源码） / ⚠️ **线上未生效（N-07）** | `embed=True` 已在位（`:24`）；测试进程 200；M1 证明测试有牙；**线上实测仍 422** |
| **C-02** | 🟡 | `ws.py` 批量/背压 | ✅ **CLOSED**（机制生效） / ⚠️ 回归测试无牙（**N-01**） | 600 行 → **19 帧**（每秒 ≤10 帧）；尾部不丢（`finally: flush()`）；flusher 线程退出正常；M9 存活暴露测试缺口 |
| **C-04** | 🟡 | `files.py:16-31` | ✅ **CLOSED** | §5.1 六项全过；双路径清理有断言 |
| **C-06** | 🟡 | `ws.py:25-36` | ✅ **CLOSED** | 两轮 `list(all=False/True)` 且 running 优先；`test_ws_logs_streams_a_stopped_container` 断言 `list_all == [False, True]`；M3 证明有牙 |
| **C-07** | 🟡 | `images.py:103` | ✅ **CLOSED** | `img.save(named=True)`；docker-py 7.2.0 源码 `named=True → img = self.tags[0] if self.tags else img`；M2 证明有牙 |
| **C-08** | 🟡 | `security.py` + `main.py` 中间件 + `ws.py` 守卫 | ✅ **CLOSED（含 3 条新 🟢：N-03 + 明文旁路 + 端口无关）** | 真服务端探测：`evil.example`/`null`/`127.0.0.1.evil.example` 全部 **403**；本地与无 Origin 放行；M5/M6/M8 全部杀死；WS 守卫确在 `accept()` **之前** |
| **C-13** | 🟡 | `test_files_api.py` + `a.txt` | ✅ **CLOSED** | `a.txt` 不再被跟踪、磁盘无残留、3 次跑测后仓库树干净 |
| **C-14** | 🟡 | `test_ws_logs.py` | ✅ **CLOSED** | 断言移出 `try`，全文件无 `try/except`；M7 证明可失败 |
| **C-15** | 🟡 | `backend/tests/` | ⚠️ **PARTIAL** | 66→105 passed，三条主线（F6/F7/F10）已覆盖；余 9 个端点仍未直接覆盖（rd1 判 JUDGEMENT） |
| **C-19** | 🟡 | `ws.py:98-100,226` | ✅ **CLOSED** | 两个端点都在关闭前发**文本帧** `{"error": …}`；`ws_logs` 走 `send_json` + `close()`，`ws_exec` 走 `send_json` + `return`→`finally` 收尾；前端 `parseServerErrorFrame` 严格校验（须整帧为 JSON 对象且有非空 `error` 字符串）；M4/M7 有牙 |
| **C-22** | 🟢 | `docs/.../README.md` | ⚠️ **PARTIAL** | `:75` 已改对 ✅；但 `:77` 仍写「待修复」、`:102` 仍写「66 passed」（实测 105） |

### 6.2 新发现

| 编号 | 严重度 | 位置 | 描述 | 性质 | 修复建议 |
|:--:|:--:|------|------|:--:|------|
| **N-01** | 🟡 | `backend/tests/test_ws_logs.py:74-91` | **批处理回归测试同义反复**：3 行 mock 流立刻结束，断言由收尾 `flush()` 满足，与计时线程无关。删掉整个 flusher 后 17 个测试仍全绿（600 行 → 1 帧）。C-02 的核心机制无回归保护。 | **HARD** | 新增用例：① mock 一个**长命**流（如 200 行、行间 `sleep(2ms)`），在**流未结束**时断言「已收到 >3 帧且每帧 >1 行」（即合并真发生）；② 断言「单帧内含多行」不足以证明批处理，必须断言**帧数远小于行数**；③ 可再加一条「空闲容器不丢尾部」——流结束后不再有新行，断言末行仍到达。**注意** `_send_from_thread` 是模块级函数，测试可直接 monkeypatch 它计数（本报告 §0.1 的探针即此手法，已验证能区分两种实现）。 |
| **N-02** | 🟢 | `backend/app/routers/ws.py:157-160` + `:138-141` | 收尾竞态：`flusher` 的 `finished.wait()` 两条返回路径都继续执行 `flush()` → 与 `finally` 的 `flush()` 可能重复发送同一批行（或发空帧）。窗口极窄。 | JUDGEMENT | 把 flusher 改为「只在自己成功取到数据时发送」：`if finished.wait(INTERVAL): return` 之后才 `flush()`；或让 `flush()` 返回「本次是否真的发了内容」，收尾时用 `if not flushed: flush()` 的原子形式（在锁内判定并置位）。 |
| **N-03** | 🟢 | `backend/app/services/security.py:28` | `0.0.0.0` 在 localhost 白名单里，与 `spec.md:111`「禁止后端暴露 0.0.0.0」及 compose 的仅 `expose` 不自洽（不可利用）。 | JUDGEMENT | 删掉 `"0.0.0.0"`；若确实要支持「以 0.0.0.0 访问」，应改由 `is_same_site` 的「Origin host == Host」同源分支覆盖，而不是把 0.0.0.0 当**本地**来源。 |
| **N-04** | 🟢 | `backend/app/routers/ws.py:221-227` | 仅 `docker.errors.NotFound` 有专门文案；其他 daemon 故障 → 静默关闭 + 前端「已断开」无原因；且前端对匹配 `no container` 的文案追加「容器可能已被删除」的**具体归因**，误判时会把用户引向错误方向。放宽 `except` 后测试仍全绿（无覆盖）。 | JUDGEMENT | ① 区分处理：`except docker.errors.APIError as e` → `if e.response.status_code == 404: "no such container: X" else: "docker 守护进程错误：<首行>"`；② 为「非 404 故障也发错误帧」加一条测试。 |
| **N-05** | 🟢 | `backend/app/routers/ws.py:128-133` | 丢弃标记行与首个空日志行可能黏连（少一次换行）。 | JUDGEMENT | 先 `chunk = "\n".join(pending)`；若 `counter` 有值，改为 `chunk = marker + "\n" + chunk`（marker 自带 `\n` 时避免与空行首元素合并），或对空行做 `"\u200b"` 之外的显式占位处理。 |
| **N-06** | 🟢 | `backend/app/services/files.py:26-28` | `except OSError: pass` 静默吞错，启动清理失败无日志（项目亦无 logging 配置）。 | JUDGEMENT | 至少 `logger.warning("could not remove staging entry %s", p, exc_info=True)`，让「删不掉的残留」在日志里留痕。 |
| **N-07** | 🟡 | 线上栈（`deploy/docker-compose.yml:2-4`） | **修复未部署**：线上仍是 pre-fix 构建，C-01（🔴）对用户仍可见、C-08 中间件未生效。 | **HARD** | 重审通过后**必须重建并重启**：`docker compose -f deploy/docker-compose.yml up -d --build backend frontend`；并在 `docs/deployment.md` 补一句「升级后需 `--build`，源码改动不会自动生效」。**不要把「源码已修」当成「用户可用」。** |
| **N-08** | 🟢 | `backend/app/services/security.py:14-23` | 明文旁路：**无 `Origin` 头的非浏览器客户端一律放行**（`is_same_site(None, …) is True`，§0.2 实测 `wscat`/脚本可连）。这是**有意设计**（文档已声明，且本机任意进程本就能直取 `docker.sock`，守卫只针对浏览器中介），从安全角度看不可辩护为漏洞，但必须知道它不是认证。 | JUDGEMENT | 无需改码。若未来把面板当作多用户/生产系统，应改为随机 token（Cookie/URL 注入）+ 白名单，而不是继续依赖 Origin 存在性。 |
| **N-09** | 🟢 | `backend/app/services/security.py:19-20,54-55` | 本地来源判定**与端口无关**：`http://127.0.0.1:9999` 与 `http://localhost:5173` 都被放行（§0.2 实测 `127.0.0.1:9999` → 放行）。这是为「Vite dev 5173 / UI 8088 互访」刻意放宽的取舍，但违反了标准 same-origin 的端口语义。 | JUDGEMENT | 若接受取舍：在 `security.py` docstring 里**明确写出**该放宽及其理由（现在只写了「whichever port」而未点出安全含义）。若要收紧：对「`Origin` 端口 ≠ 面板端口 ≠ 允许的 dev 端口」的来源拒绝，并把 dev 端口做配置项。 |
| **N-10** | 🟢 | `backend/tests/test_files_api.py:26-31` | `staging_dir` 的 `return` 路径（`tmp_path_factory` 成功时）**从未被验证**；本沙箱下必定走 `except OSError` 分支（实测 `PermissionError`）。 | JUDGEMENT | 要么统一为 `yield` 版本（`try: d = mktemp(...); except OSError: d = fallback`；`yield d; finally: 清理`），要么保留现写法但在 docstring 里点明「`return` 路径在 CI 生效，本机只走 fallback」。 |

---

## 7. 存疑 / 未能验证项

1. **线上构建的版本无法精确定位**：本沙箱禁 Docker 命名管道 → 无法 `docker inspect dockermgr-backend` 看镜像 ID/创建时间、无法比对镜像内文件、无法 `docker exec` 读容器内 `nginx.conf`。N-07 的「pre-fix 构建」是**由契约行为反推**（裸字符串 200 / 对象体 422 / 无 403 守卫），证据强度高但非直接读取。
2. **E2E（`scripts/e2e_verify.py` 18 项）、`ui_verify.py`、`ui_clipboard_test.py`、`docker build`/`compose up` 均未复跑**（`permission denied npipe` / `WinError 5`，且本会话审批已禁用 → 不升级重试）。因此「真机 105 passed 之外的行为」只有间接证据。
3. **`test_ws_logs_blocking.py` 未独立复跑其真机语义**：该用例需起真实 uvicorn + 空闲 6 秒内 `/api/health` < 3s；在本环境它作为普通用例在 105 passed 中通过，但「事件循环真的没被冻结」这一点未单独计时复核（rd1 已把它列为亮点）。
4. **未验证前端实际交互**（前端透镜职责）：`ContainerLogs.vue`/`ContainerTerminal.vue` 的自动重连、退避、`parseServerErrorFrame` 与后端的**端到端**联调未做（Playwright 不可用）。我只做了**契约两侧对齐**的静态核对。
5. **N-02 的重复发送未能在实机复现**（时间窗口为微秒级，需确定性调度注入）；结论是**读码 + 时序分析**，非实测复现。如实标注为 JUDGEMENT。
6. **N-01 的「长命流」用例未写入仓库**（审查者不得改产品代码，探针已删除）。修复建议里给出了可直接落地的写法，其可分辨性已由本报告 §0.1 的探针证明（正常 19 帧 vs 无计时器 1 帧）。

---

## 8. 五段结论

| 段 | 结论 | 关键发现 |
|----|:--:|---------|
| Plan alignment | ⚠️ | 无未关闭 🔴/🟡。修复未偷范围、未改冻结契约；C-22 **PARTIAL**（README `:77` 仍写「待修复」、`:102` 仍写「66 passed」，实测 105） |
| Code quality | ⚠️ | 无未关闭 🔴/🟡。修复本身质量高（`_stage_and_push` 抽取干净、`finally` 统一清理、锁粒度正确、`except NotFound` 精确）；2 条 🟢（N-02 收尾竞态、N-05 标记行黏连） |
| Architecture | ⚠️ | 无未关闭 🔴/🟡。Origin 守卫落点正确（HTTP 中间件全覆盖 + WS 握手前校验 + 双重冗余）、前端重试语义与后端 1000/1008 契约闭合；1 条 🟢（N-03 `0.0.0.0` 白名单不自洽） |
| Testing | ❌ | **N-01 🟡**：批处理回归测试同义反复，删掉整个计时器线程后 17 个测试仍全绿（600 行→1 帧），C-02 核心机制无回归保护。**正面**：变异测试 8/10 注入缺陷被杀；C-13/C-14 确认关闭且仓库不再被污染（66→105 passed） |
| Production | ❌ | **N-07 🟡**：线上仍是修复前构建，C-01（🔴）对用户仍可见、C-08 未生效 → 需 `--build` 重建重启。C-04 确认 CLOSED（阻塞步骤全部搬出事件循环 + 双路径清理） |

**后端透镜总判定：❌ NEEDS FIXES**（未关闭 🔴 0 / 🟡 2 = N-01、N-07 / 🟢 8）

> 两条 🟡 都不是「源码写错」，而是「**修好了但证明不了 / 修好了但没生效**」：
> - **N-07** 是交付闭环缺口 —— 一行 `--build` 的事，但不做等于本轮最重要的 🔴 修复归零；
> - **N-01** 是验证闭环缺口 —— 修复正确（已由探针证明 600→19 帧），但**没有任何测试能阻止它被改回去**，而它正是 rd1 未审视、最易写错的计时线程。
>
> 建议修复顺序：**N-07（重建部署，立即）→ N-01（补长命流批处理用例）→ C-15 剩余端点（可延后）→ C-22 文档回写 → N-02/N-03/N-04/N-05/N-06/N-08/N-09/N-10（记录）**。
