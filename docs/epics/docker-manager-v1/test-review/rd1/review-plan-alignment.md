# Docker 管理平台 v1 — Phase 4.6 代码审查（Rd1）

## 透镜：计划对齐 + 跨层契约（Plan Alignment & Cross-Layer Contract）

> Epic：`docker-manager-v1`
> 审查范围：`c689f71a52f9cffb89c80efd706149b3d95307ec..81490291321b22d06aec0cfbeff05f06bb7905c2`
> BASE = `c689f71`（Task 1 的父提交）· HEAD = `8149029` · 单分支 `master`（无 `main`，merge-base 不适用）
> 规模实测：**22 个 commit / 63 文件 / +9859 −4**（`git rev-list --count` = 22，与 `README.md:104`「提交数 22」一致）
> 依据文件：`plan.md`（Task 1–12 + Global Constraints + 验证闭环 + 提交节奏）、`spec-review/final/spec.md`（D1–D7、§3–§7）、`scope.md`、`docs/epics/docker-manager-v1/README.md`（仅作线索）
> 本报告的每条发现都带 `file:line` 或 `spec.md:L` / `plan.md:T{n}` 引用。

---

## 0. 审查方法与证据基线

### 0.1 本透镜的工作方式

不靠肉眼扫，全部契约对账都走程序：从 `app.routers.*` 的 `@router` 装饰器 + `app.openapi()` 抽出**后端真实注册的路由**，与前端 `api/index.ts` 及组件内直连 URL 做集合比对；再对**正在运行的部署**（`127.0.0.1:8088`）做只读探测，用真实 HTTP 状态码与 WebSocket 帧验证契约，而不是相信文档。

### 0.2 独立跑过的验证命令与结果

| # | 命令 | 结果 |
|---|------|------|
| 1 | `uv run --frozen --no-sync pytest -q`（cwd=`backend`） | ✅ **66 passed, 2 warnings in 2.69s**；`--collect-only` 亦为 66 → 复现了 `README.md:100` 的「66 passed」 |
| 2 | 路由枚举（`app.openapi()["paths"]` + 逐 router 展开） | ✅ 25 条 HTTP + 2 条 WS，见 §B.1 |
| 3 | 只读 HTTP 探测 6 条 GET（经 nginx） | ✅ 全部 200：`/api/health`、`/api/containers?all=true`、`/api/images`、`/api/networks`、`/api/volumes`、`/api/images/pull/mirrors`；`Server: nginx/1.31.5` |
| 4 | 契约探针（尾斜杠 / 方法不匹配 / 不存在的路径 / Body 形状） | ✅ 见 §B.5，其中 **POST /api/volumes 暴露 🔴 F-01** |
| 5 | WS 只读探测 `/ws/logs`、`/ws/exec` | ✅ 见 §B.2；`/ws/logs` 实收文本帧（nginx access log 行） |
| 6 | `GET /api/images/{id}/save` 流式行为（读 128 KB 即断开） | ✅ 200 / `application/x-tar` / `transfer-encoding: chunked` / 无 `content-length` / **TTFB 0.120s** → D6 真流式，已实测量化 |
| 7 | 线上 bundle 与本地 `dist/` 对账 | ✅ 线上引用 `/assets/index-BGeOqOmG.js`，与本地 `frontend/dist/assets/index-BGeOqOmG.js` 同名；该 bundle 含 HEAD 独有字符串（`浏览器未允许读取剪贴板`、`已复制`、`/images/pull/mirrors`、`/volumes",{name:`）→ **运行中的产物确为 HEAD 源码构建**，本报告所有实测结论可代表被审版本 |
| 8 | `vue-tsc -b --force`（cwd=`frontend`） | ✅ **退出码 0**，前端全量类型检查无错误 |
| 9 | `git ls-files` / `git check-ignore` / `git cat-file -e HEAD:backend/uv.lock` | ✅ 见 §G.1，推翻已知事实 1 |
| 10 | `npm run build`（`vite build` 阶段） | ⛔ 未能跑完：`Error: spawn EPERM`（esbuild 需带管道子进程，被沙箱拒绝）。`vue-tsc` 阶段已先通过 |

### 0.3 审查过程对系统的实际影响（如实披露）

在验证 Body 形状时，为拿到确定性证据发送了 `POST /api/volumes` 的**裸 JSON 字符串**形态，该请求按设计返回 200 并**创建了一个名为 `dm-review-probe-dryrun` 的空数据卷**。随后已 `DELETE /api/volumes/dm-review-probe-dryrun` 并核对卷列表恢复到探针前的 8 个卷（`evidence-kg-neo4j-dev-logs`、`31f020bf…`、`ontology-kg_*`、`evidence-kg-neo4j-dev-data`、`1272bff5…`、`mysql-data`）。除此之外未创建/删除任何容器或镜像。

---

## A. Task-by-Task 对齐矩阵（核心交付物）

判定口径：**✅ 完成** = 计划的 Files/Interfaces/验证要求均满足；**⚠️ 部分** = 主体达成但有可引用缺口；**❌ 缺失**；**➕ 超范围**（相对 plan 但被 spec 容许）。

| Task | 计划要求（引用） | 实际实现（引用） | 判定 | 说明 |
|------|------------------|------------------|------|------|
| **T1** 后端骨架与配置 | `plan.md:T1`（L23–112）：`pyproject.toml`/`app/__init__.py`/`config.py`/`main.py`/`test_health.py`；`get_settings()`；`GET /api/health → {"status":"ok"}`；验证要求 L105 `uv run --directory backend pytest -q` → 1 passed | `backend/pyproject.toml:1-22`、`backend/app/config.py:9-20`、`backend/app/main.py:21-26`、`backend/tests/test_health.py`；实测 `GET /api/health` → 200 `{"status":"ok"}`（经 nginx） | ✅ | commit `1b1e5cb`。`config.py` 在计划三键之外增加 `image_mirrors`（`config.py:15-19`），是后续 R3 修复的落点，属合理扩展。`get_settings()` 返回 dict 而非计划 Interfaces 行写的 `Settings` 类，与计划 Step 3 的代码示例（L79）一致 |
| **T2** Docker 客户端封装 | `plan.md:T2`（L116–189）：`get_docker_client()`／`extract_error(e)`／**`ContainerInfo`/`ImageInfo`/`NetworkInfo`/`VolumeInfo` 四个 dataclass** | `backend/app/services/docker.py:43-55`（客户端 + `extract_error`）；四个 dataclass 定义于 `docker.py:7-37` | ⚠️ | 客户端与 `extract_error` 达标且有单测（`test_docker_service.py`）。**但 4 个 dataclass 中只有 `ContainerInfo` 被引用**（`containers.py:5,76,83`），`ImageInfo`/`NetworkInfo`/`VolumeInfo` 全仓零引用 → 见 **F-12**。`docker.from_env()` 优先于 `get_settings()["docker_host"]`（`docker.py:47-49`），见 **F-16** |
| **T3** 容器 API（CRUD+启停+commit） | `plan.md:T3`（L193–329）：`GET /api/containers?all`、`GET /{id}`、`POST /{id}/start\|stop\|restart\|pause\|unpause`、`DELETE /{id}?force`、`POST /{id}/commit {repo,tag}` | 全部 10 条路由存在（`containers.py:94,154,162,171,180,189,198,207,216`）；实测 `POST /{cid}/commit` 空体 → 422 `loc:["body","repo"]` 证明 embed 形状与前端一致 | ✅ | commit `d68cbb8`。➕ `POST /api/containers`（`containers.py:102`）为计划外新增，但被 `spec.md:83`「容器 CRUD」覆盖，属**计划外、规格内**。`_format_ports`（`containers.py:29-50`）与 `_image_name`（`:53-73`）超出计划的朴素实现且修掉两个真实缺陷（`troubleshooting.md:99-103`、`:89-95`）。**注**：`pause`/`unpause` 前端无入口（**F-02**），`GET /{id}` 前端无调用（**F-12b**） |
| **T4** 镜像 API（save+pull） | `plan.md:T4`（L333–422）：`GET /api/images`、`GET /{iid}/save` → StreamingResponse、`DELETE /{iid}`、`POST /api/images/pull {name,tag}`；约束 L348「spec §4 导出流式 D6」 | `images.py:73,95,104,113`；实测 `/api/images/{id}/save` → 200 chunked、TTFB 0.12s | ✅ | commit `5ed3e8e`。➕ `GET /api/images/pull/mirrors`（`images.py:89`）为计划外；注册顺序在 `/{iid}/save`（`:95`）之前，`/pull/mirrors` 不会被 `/{iid}/save` 吞掉（已实测 200 确认）。➕ 镜像源降级（`images.py:113-181`）为 R3 修复，见 **F-19** |
| **T5** 网络与卷 API | `plan.md:T5`（L426–512）：`GET/POST/DELETE /api/networks`（create `{name,driver}`）、`GET/POST/DELETE /api/volumes`（create **`{name}`**）；验证要求 L451–457 仅含两个 list 断言 | `networks.py:8,24,33`；`volumes.py:8,24,33`。实测：`POST /api/networks {}` → 422 `loc:["body","name"]`（embed ✔ 与前端 `{name,driver}` 一致）；`POST /api/volumes {"name":…}` → 422 `loc:["body"]` | ⚠️ | commit `34ecfce`。**卷创建在界面上必然失败**（**F-01 🔴**）。计划 Step 1 的测试只覆盖 list（`plan.md:451-457`），实现照做了（`test_networks_volumes.py:8-52` 仅 2 个用例）→ create/delete 两侧均无测试，这正是契约断裂得以漏过的原因 |
| **T6** 文件双向拷贝 | `plan.md:T6`（L516–633）：`services/files.py`、`routers/files.py`；Interfaces L527 写 `POST …/copy-to?path=`，但 Step 3 代码（L586-608）实际是 `POST …/copy`（Form `dest`+`file`）与 `GET …/copy?path=`；`main.py` 启动清理临时目录 | `files.py:15-37` + `main.py:12,15-18,33`。实测契约与 Step 3 一致（前端 `FileCopyDrawer.vue:92-93,115` 字段名 `dest`/`file`/`path` 完全对上） | ✅ | commit `e4f5fff`。计划自身在 Interfaces（L527）与 Step 3（L586）之间不一致，实现选了 Step 3。`os.path.basename(file.filename)`（`files.py:18`）修掉了计划示例（`plan.md:589`）的路径穿越隐患。**但**：该 Task 的测试污染仓库工作区并留下已提交的 `backend/a.txt` → **F-09 🟡** |
| **T7** WebSocket 实时日志 | `plan.md:T7`（L637–714）：`/ws/logs?filter=&stream=&tail=`；验证要求 Step 1（L652-662）给出一段**会真实失败**的测试；Step 3 参考实现用 `send_json({"error": "no container"})` | `ws.py:58-124`；`test_ws_logs.py` 存在 | ⚠️ | commit `434d669`。线程化重写（`ws.py:88-111`）是对 `spec.md:113` 与 R1 缺陷的正确修复，且 `test_ws_logs_blocking.py` 起真实 uvicorn 断言（`:111-151`）——这部分质量很高。**但**：（a）计划给的可失败测试被改写成 `try/except: pass` 恒通过（**F-07 🟡**）；（b）错误帧前端不识别，被当日志行渲染（**F-05 🟡**） |
| **T8** WS 交互终端 | `plan.md:T8`（L718–791）：`/ws/exec?container={id}`，`tty=true` + resize（L729 引 spec D5） | `ws.py:127-231`；实测 `container` 参数名一致、客户端 JSON 帧 `{type:input,data}`/`{type:resize,cols,rows}`（`ws.py:204-217`）与前端（`ContainerTerminal.vue:63,86`）逐字对上 | ✅ | commit `eba3904`。实现走了**低层** `api.exec_create`（`ws.py:154-162`）而非计划示例的 `exec_run`（`plan.md:762`），因为只有保留 `exec_id` 才能 resize —— 这是超出计划参考代码的**必要修正**，见 §E 亮点 2。➕ 新增 `cmd` 参数（`ws.py:128`，默认 `/bin/sh`）。🟡 找不到容器时静默 1000 关闭无错误帧（**F-06**） |
| **T9** 前端骨架+路由+API 层 | `plan.md:T9`（L795–869）：Files 列出含 **`frontend/src/views/SettingsView.vue`(占位)**；四路由；`api/` 封装全部端点；验证要求 Step 3（L860-863）`npm run build` 无类型错误 | `router/index.ts:3-29`（4 路由 ✅）、`api/index.ts:57-88`（全部端点 ✅）；**`SettingsView.vue` 不存在** | ⚠️ | commit `4caf6e3`。API 层覆盖完整（见 §B.1）。`SettingsView.vue` 未创建 → **F-13 🟢**；`api/index.test.ts`（L811「可选用 vitest」）未创建，计划标注为可选，不计缺失。验证要求：`vue-tsc -b --force` 退出码 0 ✅；`vite build` 因沙箱未跑完（见 §F.4） |
| **T10** 容器列表页+操作+详情 | `plan.md:T10`（L873–922）：`ContainerLogs.vue`/`ContainerTerminal.vue`/`FileCopyDrawer.vue` 三个组件；Step 1 要求操作列含「启/停/重启/**暂停**/日志/终端/打包/拷贝/删除」 | 三组件齐备（`ContainerLogs.vue`、`ContainerTerminal.vue`、`FileCopyDrawer.vue`）；实测 `/ws/logs`、`/ws/exec` 契约逐字段一致 | ⚠️ | commit `ad1fc1c`。**操作列缺「暂停/恢复」**（`ContainersView.vue:63-100` 只有启动/停止/重启 + 下拉五项），而 `scope.md:24` F1 明确要求「暂停」、`plan.md:206` 明确要求 pause/unpause 端点 → **F-02 🟡**。➕ `RunContainerDialog.vue`（新建容器）为计划外，但被 `spec.md:83`「容器 CRUD」覆盖，且系用户反馈驱动（`README.md:28`） |
| **T11** 镜像页/网络页/卷页 | `plan.md:T11`（L926–961）：三个视图；Step 1 镜像页导出用 **blob 下载**（`plan.md:939-943`） | `ImagesView.vue:170-176` 用 `<a href="/api/images/{id}/save">`；`NetworksView.vue`；`VolumesView.vue`。三文件独立存在 | ⚠️ | commit `7cfa52c`。**已知接受偏差**：计划预审记 Fail（`README.md:76`、`README.md:94`），按约定标 ⚠️，不重新计为新发现（详见 §G.2 的校准说明）。导出方式偏离 `plan.md:939-943` 的 blob 方案，但更贴合 `spec.md:57` D6（浏览器原生下载流式落盘，不把整个 tar 读进 JS 内存）→ 见 §E 亮点 3 |
| **T12** 容器化部署 | `plan.md:T12`（L965–1063）：Files 为 `backend/Dockerfile`、`frontend/Dockerfile`、**`deploy/nginx.conf`**、`deploy/docker-compose.yml`、`.env.example`；约束 L976-977「Dockerfile 用 uv」、L1030-1051 给出**三个服务**（backend/frontend/nginx）；验证要求 Step 5（L1053-1057）`docker compose up -d --build` + `curl /api/health` | `backend/Dockerfile`、`frontend/Dockerfile`、**`frontend/nginx.conf`**（未放 `deploy/`）、`deploy/docker-compose.yml:1-27`（**两个服务**）、`.env.example`。实测经 nginx `GET /api/health` → 200 `{"status":"ok"}` | ⚠️ | commit `50e904d`。四处理由充分的偏差：(1) **nginx.conf 位置**：`plan.md:1005` 的 `COPY ../deploy/nginx.conf` 在 Docker 中非法（超出构建上下文），实现把配置放进 context 内（`frontend/Dockerfile:12`）是正确的修正；(2) **服务数 2 而非 3**：`spec.md:101` 与 `plan.md:1034-1051` 都写三个服务，实际 nginx 与 frontend 合为一个镜像（`frontend/Dockerfile:10-12`），功能等价且 `README.md:194`、`deployment.md:25` 已如实记录为两个服务；(3) **`.env` 覆盖能力与文档不符** → **F-03 🟡**；(4) **无 `.dockerignore`** → **F-10 🟡**。**已知事实 1（uv.lock）在 HEAD 已修复**，见 §G.1 |
| **plan.md「验证闭环」**（L1067–1072） | ① `docker compose up -d` 后 `/api/health` OK ② 页面完成「看容器→看日志→进终端→文件拷进拷出→打包镜像→导出 tar」③ F1–F10 全部经界面触发，不依赖命令行 | ① ✅ 实测经 nginx 200（`Server: nginx/1.31.5`）② ⚠️ 只读部分实测（HTTP 全通、WS logs 实收帧、exec 路由可达、导出实为流式）；写操作链路未逐一实测 ③ ⚠️ F1/F3/F4/F5/F11 有缺口，逐条见下 | ⚠️ | F1 容器管理：列表/启停/重启/删除/筛选 ✅，**暂停 ❌（F-02）**、**详情无界面（F-12b）**；F2 日志 实时+历史(tail)+stdout/stderr 切换 ✅；F3 镜像 列表/删除/拉取 ✅，详情 ❌，且 `README.md:26` 声称的「大小」未返回（**F-12**）；F4 网络 列表/创建/删除 ✅，详情 ❌；F5 卷 列表/删除 ✅，**创建 ❌（F-01）**，使用情况 ❌；F6 打包镜像 ✅；F7 导出 tar ✅；F8 容器化部署 ✅；F9 交互终端 ✅；F10 双向拷贝 ✅；F11 全界面 ✅/⚠️ |
| **plan.md「提交节奏」**（L1074–1076） | 「每个 Task 独立 commit，**Task 内部按 TDD 红->绿增量提交**」 | 12 个 Task commit 各为**单次提交**（`--stat` 实测：`1b1e5cb` 5 files/52 insertions 同时含测试与实现，其余同构） | ⚠️ | 见 **F-15 🟢**。红→绿增量提交未发生；TDD 的"红"阶段在历史中不可考 |

### A.1 三类问题逐条

**(a) 缺失 / 半实现**（全部带引用）

| 编号 | 内容 | 引用 | 严重度 |
|------|------|------|--------|
| A-a1 | 卷创建接口契约断裂，界面「创建卷」必然 422 | `scope.md:28` F5 / `plan.md:T5`(L438) vs `volumes.py:24` + `api/index.ts:86` | 🔴 F-01 |
| A-a2 | 容器「暂停/恢复」后端已实现、前端 API 已封装，但**无任何 UI 入口** | `scope.md:24` F1 / `plan.md:206` vs `ContainersView.vue:63-100,245-253` + `api/index.ts:63-64` | 🟡 F-02 |
| A-a3 | 容器/镜像/网络「详情」无界面路径（`GET /api/containers/{cid}` 无前端调用） | `scope.md:24,26,27` vs `api/index.ts`（无 detail 方法） | 🟢 F-12b |
| A-a4 | 卷「使用情况」未实现 | `scope.md:28` F5 vs `VolumesView.vue:23-62` | 🟢 并入 F-12b |
| A-a5 | `SettingsView.vue` 占位页未创建 | `plan.md:810` | 🟢 F-13 |
| A-a6 | `Task 2` 声明的 4 个数据类型 3 个零引用（含 `ImageInfo.size`），`README.md:26` 的「大小、创建时间」不成立 | `plan.md:124` / `spec.md:70` vs `docker.py:18-37`、`images.py:76-84` | 🟢 F-12 |
| A-a7 | `spec.md:113` 对策中的「断线重连、防抖」未实现（仅做了行数截断） | `spec.md:113` | 🟡 F-11 |
| A-a8 | 计划内测试被弱化为恒通过（`test_ws_logs.py`） | `plan.md:T7`(L652-662) vs `test_ws_logs.py:21-29` | 🟡 F-07 |

**(b) 蔓延（对照 `spec.md` §7「不在范围」，L121–130）**

| 编号 | 结论 |
|------|------|
| B-b1 | ✅ **未发现违规蔓延**。逐条核对：登录/多用户/权限（无）、Compose 可视化编排（无；`docker-compose.yml` 是平台自身部署，非编排功能）、Swarm（无）、监控曲线（无；容器列表只显示 `State`，无 CPU/内存采集）、多宿主机（无，`docker.py:43-50` 单客户端）、镜像导入 `docker load`（界面无，✅ 合规） |
| B-b2 | 🟢 **边界项（判为不违规，但登记）**：`IMAGE_MIRRORS` 镜像源降级（`images.py:113-181`）与 `spec.md:126`「镜像仓库管理（registry）」相邻。判为不违规 —— 它只把仓库域名插到镜像名前（`deployment.md:116` 已说明），无 registry CRUD、无登录凭据管理，属拉取路径的韧性增强，非 registry 管理。**未在 `plan.md` 中，属 ➕ 超计划**（R3 修复，`README.md:27`） |
| B-b3 | 🟢 **边界项**：`deployment.md:194-198` 指导用户用 `docker load -i image.tar` 迁移镜像。`spec.md:129` 把「镜像导入」排除在 v1 之外、`spec.md:16` 规定「不依赖命令行」。判为**文档层面的合规擦边**（未在界面实现该功能，只是迁移建议），但措辞与总体原则相左，建议在文档中标注「v1 未提供界面导入」 |
| B-b4 | 🟢 **边界项**：`RunContainerDialog.vue` 允许创建时配置端口/环境变量/挂载/重启策略。`spec.md:130` 排除的是**已存在容器**的「启动配置编辑」，创建时传参属 `spec.md:83`「容器 CRUD」范畴，判为不违规 |

**(c) 看似对实则错（实现方式与 spec/plan 意图不符）**

| 编号 | 内容 | 引用 |
|------|------|------|
| C-c1 | `volumes.py:24` 单 `Body(...)` 标量 → 非 embed，与 `networks.py:25` 同类接口的双参数 embed 写法不一致，前端按后者写 → 静默 422 | `volumes.py:24` vs `networks.py:25` + `api/index.ts:80,86` → 🔴 F-01 |
| C-c2 | `test_files_api.py:27-28` 把 `get_tmp_dir` mock 成 `Path(".")`，异常路径不清理 → 文件落到仓库 CWD，`backend/a.txt` 因此被提交 | `test_files_api.py:27-28` + `files.py:18-19,25` + `backend/a.txt:1` → 🟡 F-09 |
| C-c3 | `test_ws_logs.py:21-29` 用 `try/except: pass` 包住计划给定的可失败断言 → 路由缺失也通过 | `test_ws_logs.py:21-29` vs `plan.md:659-662` → 🟡 F-07 |
| C-c4 | `e2e_verify.py:210-217` 把「收到任何字符串帧」等同于日志链路成功；结合 C-c5，后端发错误帧时同样 PASS | `e2e_verify.py:210-217` → 🟡 F-08 |
| C-c5 | `ws.py:75` 的 `{"error":"no container"}` 文本帧在前端被当作日志行显示（已实测复现） | `ws.py:75` + `ContainerLogs.vue:100-102` → 🟡 F-05 |
| C-c6 | `nginx.conf:32,43` 用 `$host`（不含端口）→ FastAPI 307 的 `Location` 指向未监听的 80 端口（已实测） | `nginx.conf:32` → 🟡 F-04 |
| C-c7 | `README.md:71` / `deployment.md:83-85` 声称 `.env` 可覆盖配置，实际只有 `IMAGE_MIRRORS` 可覆盖 | `README.md:71` vs `docker-compose.yml:9-14` → 🟡 F-03 |
| C-c8 | `frontend/Dockerfile:6` 的 `COPY . .` 在 `npm ci` 之后执行，会把宿主 Windows 版 `node_modules`（116 MB）覆盖进 Linux 镜像 | `frontend/Dockerfile:5-6` → 🟡 F-10 |
| C-c9 | `docker.py:47-49` 让 `docker.from_env()` 先行，使 `get_settings()["docker_host"]` 基本成为死配置（`from_env()` 自身读同名环境变量且不抛异常） | `docker.py:43-50`、`config.py:12` vs `spec.md:61` D7 → 🟢 F-16 |

---

## B. 跨层契约核查（本透镜独有职责）

### B.1 后端真实注册的路由 ↔ 前端调用（程序化对账）

路由来源：`app.openapi()["paths"]`（HTTP，25 条）+ 逐 router 展开 `router.routes`（WS，2 条）。前端来源：`frontend/src/api/index.ts:57-88` + 组件内直连 URL。

> ⚠️ 方法学备注：FastAPI 0.141.1 的 `app.routes` 对 `include_router` 只保留 `fastapi.routing._IncludedRouter` 占位对象（无 `.path`），直接遍历 `app.routes` 会**静默漏掉全部子路由**。本审查改用 `app.openapi()` + 逐 router 展开，避免了这个陷阱（首次朴素遍历只看到 5 条路由）。

| # | 前端调用（含 file:line） | 后端路由（含 file:line） | 判定 |
|---|--------------------------|--------------------------|------|
| 1 | `api/index.ts:58` `GET /api/containers?all=` | `containers.py:94` `GET /api/containers`（`all: bool = Query(False)`） | ✅ 实测 200 |
| 2 | `api/index.ts:59` `POST /api/containers`（body 8 字段） | `containers.py:102` + `RunRequest`（`containers.py:11-21`） | ✅ 8 字段逐名对应 |
| 3 | `ContainersView.vue:247` `POST /api/containers/{id}/start\|stop\|restart` | `containers.py:162,171,180` | ✅ |
| 4 | `api/index.ts:63-64` `POST /{id}/pause\|unpause` | `containers.py:189,198` | ⚠️ 端点存在，**前端零调用点**（F-02） |
| 5 | `ContainersView.vue:289` `DELETE /api/containers/{id}?force=` | `containers.py:207`（`force: bool = Query(False)`） | ✅ |
| 6 | `ContainersView.vue:272` `POST /{id}/commit` body `{repo,tag}` | `containers.py:216` | ✅ 实测空体 → 422 `loc:["body","repo"]`，证明 embed 形状与前端一致 |
| 7 | 前端无调用 | `containers.py:154` `GET /api/containers/{cid}` | ⚠️ 死端点（F-12b）；实测 200 |
| 8 | `FileCopyDrawer.vue:92-93,97` `POST /api/containers/{cid}/copy`（FormData `dest`+`file`） | `files.py:15-16`（`dest: str = Form(...)`、`file: UploadFile = File(...)`） | ✅ 字段名逐字一致 |
| 9 | `FileCopyDrawer.vue:115` `GET /api/containers/{cid}/copy?path=` | `files.py:31-32`（`path: str = Query("/")`） | ✅ 参数名一致 |
| 10 | `ImagesView.vue:136` `GET /api/images` | `images.py:73` | ✅ 实测 200 |
| 11 | `ImagesView.vue:172` → `api/index.ts:75` `/api/images/{id}/save`（`<a href>`） | `images.py:95` | ✅ 实测 200 / `application/x-tar` / chunked |
| 12 | `ImagesView.vue:186` `DELETE /api/images/{id}?force` | `images.py:104` | ✅ |
| 13 | `ImagesView.vue:157` `POST /api/images/pull` body `{name,tag}` | `images.py:113` | ✅ 两个 `Body` 参数 → 自动 embed，与前端形状一致 |
| 14 | `ImagesView.vue:126` `GET /api/images/pull/mirrors` | `images.py:89` | ✅ 实测 200；注册顺序先于 `/{iid}/save`（`:95`），无被吞风险 |
| 15 | `NetworksView.vue:130,153,171` `GET/POST /api/networks`、`DELETE /api/networks/{id}` | `networks.py:8,24,33` | ✅ 实测 `POST {}` → 422 `loc:["body","name"]`（embed 与前端 `{name,driver}` 一致） |
| 16 | `VolumesView.vue:105,154` `GET /api/volumes`、`DELETE /api/volumes/{name}` | `volumes.py:8,33` | ✅ 实测 200（`volumes.get()` 接受 name，前端传 name 正确） |
| 17 | `VolumesView.vue:127` → `api/index.ts:86` **`POST /api/volumes` body `{name}`** | `volumes.py:24` `name: str = Body(...)`（**非 embed，期望裸 JSON 字符串**） | 🔴 **断裂**：实测 422 `{"loc":["body"],"type":"string_type"}` |
| 18 | `App.vue:82` `GET /api/health`（15s 轮询） | `main.py:24-26` | ✅ 实测 200；`POST /api/health` → 405（正确） |

**结论**：**没有发现**「前端调用了后端不存在的路径」「HTTP 方法不匹配」「`/api` 前缀或尾斜杠不一致」。唯一不一致是 **Body 形状**（#17），且它是**必然失败**的（不是偶发）。

### B.2 WebSocket 契约

| 项 | 前端 | 后端 | 判定 |
|----|------|------|------|
| 路径 | `ContainerLogs.vue:95` `/ws/logs` | `ws.py:58` `/ws/logs` | ✅ |
| 查询参数名 | `filter`（`ContainerLogs.vue:95`） | `filter: str = ""`（`ws.py:59`） | ✅ |
| 查询参数名 | `stream`（`stdout`/`stderr`/`both`） | `stream: str = "stdout"`，判定 `in ("stdout","both")` / `in ("stderr","both")`（`ws.py:83-84`） | ✅ 三值全覆盖 |
| 查询参数名 | `tail`（`ContainerLogs.vue:95`，100/500/2000） | `tail: int = 100`（`ws.py:59`） | ✅ |
| 帧方向/模式 | `ws.onmessage = e => append(e.data as string)`（`ContainerLogs.vue:100-101`） | `await ws.send_text(line.decode(...))`（`ws.py:44`） | ✅ 文本帧，无 `send_bytes`，不涉及二进制模式不匹配 |
| 错误帧 | 无分支处理 | `send_json({"error":"no container"})`（`ws.py:75`） | ⚠️ **F-05**：实测 `/ws/logs?filter=zzz-no-such-container` 收到文本帧 `{"error":"no container"}`，前端会把它渲染成一行日志 |
| 路径 | `ContainerTerminal.vue:197` `/ws/exec` | `ws.py:127` `/ws/exec` | ✅ |
| 查询参数名 | `container`（传 `active.id`，`ContainersView.vue:133`） | `container: str`（`ws.py:128`） | ✅；另 `cmd` 前端不传 → 默认 `/bin/sh` |
| 上行帧 | `{type:'input',data}` / `{type:'resize',cols,rows}`（`ContainerTerminal.vue:63,86`） | `payload.get("type")` / `"input"`→`data` / `"resize"`→`cols,rows`（`ws.py:204-210`） | ✅ 字段名逐字一致 |
| 下行帧 | `term.write(e.data as string)`（`ContainerTerminal.vue:207`） | `await ws.send_text(data.decode("utf-8", errors="replace"))`（`ws.py:184`） | ✅ 原始字节以文本帧承载，前后端一致 |
| 断连语义 | `ws.onclose` → 显示「会话已结束」（`:209-213`） | 异常路径静默 `_close_ws`，**零帧**（`ws.py:220-229`） | ⚠️ **F-06**：实测 `?container=zzz-no-such-container` → 服务端 1000 (OK) 关闭，客户端无从区分「容器不存在」与「shell 退出」 |
| 前缀匹配语义 | 传精确容器名（`active.name`，来自 `_info` 的 `lstrip("/")`） | `_find_container` 用 `c.name.startswith(name)`（`ws.py:18`）**只搜 running 容器** | 🟢 已排除隐患：docker-py 7.2.0 的 `Container.name` 内部已 `lstrip('/')`（`.venv/.../docker/models/containers.py:33-34`），所以 `startswith` 能命中。但前缀匹配本身意味着 `filter=web` 会命中 `web-proxy`，无消歧提示（`plan.md:T7` L678-683 即如此设计，判为**沿用计划**） |

### B.3 前后端数据结构字段

| 结构 | 后端（file:line） | 前端（file:line） | 判定 |
|------|-------------------|-------------------|------|
| 容器行 | `containers.py:83-91` → `id/name/image/state/status/ports/created` | `api/index.ts:3-11` `ContainerRow` 同 7 字段 | ✅ 逐名一致 |
| `ports` 结构 | `containers.py:29-50` 把 docker-py 的 `{'80/tcp': [{'HostIp','HostPort'}]}` 渲染为**字符串** `"127.0.0.1:8088->80/tcp, 443->443/tcp"`（空时 `""`） | `api/index.ts:9` `ports: string`；`ContainersView.vue:213-218` 按 `,` 切分逐行渲染 | ✅ 类型与语义一致；实测线上 `"127.0.0.1:8088->80/tcp"`。这正是 `README.md` 自述曾出现 500/错配的那处，现已修正且单测覆盖（`test_containers_api.py:115-161`） |
| `state` / `status` | `state = attrs["State"]["Status"] or cont.status`；`status = cont.status`（`containers.py:87-88`，注释 `:78-81` 记录 `.state` 不存在） | `api/index.ts:7-8` 双字段；`ContainersView.vue:28,70,79` 用 `state` 驱动圆点与按钮禁用 | ✅ 一致；实测 `"state":"running","status":"running"` |
| `created` 时间 | docker-py `attrs["Created"]`，RFC3339 `"2026-01-01T00:00:00Z"` | `ContainersView.vue:220-226` `new Date(iso)` + 逐位拼 `YYYY-MM-DD HH:mm`，失败回退 `—` | ✅ 一致 |
| 镜像行 | `images.py:76-84` → `id/tags/digest/short_id`（`tags` 为 list 或 `[]`） | `api/index.ts:13-19`（`tags: string[] \| null`，`digest?`、`short_id?` 可选）；`ImagesView.vue:37-43,52-54` | ✅ 一致。⚠️ 后端不返回 `size`/创建时间，而 `README.md:26` 声称镜像列表「含标签、**大小、创建时间**」→ **F-12** 的文档面 |
| 网络行 | `networks.py:12-17` → `id/name/driver/scope` | `api/index.ts:21-26` + `NetworksView.vue:25-47` | ✅ |
| 卷行 | `volumes.py:12-17` → `name/driver/mountpoint` | `api/index.ts:28-32` + `VolumesView.vue:25-43` | ✅（注意卷的「主键」是 `name`，前端删除传 `row.name`，`VolumesView.vue:154` 写对了） |
| 创建容器入参 | `RunRequest`（`containers.py:11-21`）8 字段 | `RunContainerPayload`（`api/index.ts:34-43`）8 字段 | ✅ 逐名一致 |
| 拉取返回 | `{"ok","image","source"}`（`images.py:133,174`） | `PullResult`（`api/index.ts:45-49`）+ `ImagesView.vue:158-160` 用 `source !== 'direct'` 提示镜像源 | ✅ |
| 镜像源查询 | `{"mirrors": [...]}`（`images.py:92`） | `ImagesView.vue:127` `r.data?.mirrors ?? []` | ✅ 实测 `bytes=57` |

### B.4 部署链路自洽性

| 环节 | 证据 | 判定 |
|------|------|------|
| 前端构建产物路径 | `frontend/Dockerfile:7` 产出 `/app/dist` → `:11` `COPY --from=build /app/dist /usr/share/nginx/html` ↔ `frontend/nginx.conf:5` `root /usr/share/nginx/html` + `:6` `index index.html` | ✅ 一致 |
| nginx 配置注入 | `frontend/Dockerfile:12` `COPY nginx.conf /etc/nginx/conf.d/default.conf`；构建上下文 `../frontend`（`docker-compose.yml:20-21`）→ 该文件在 context 内 | ✅ 自洽（`plan.md:1005` 的 `COPY ../deploy/nginx.conf` 在 Docker 中非法，实现已修正） |
| `/api` 反代目标 | `nginx.conf:28-29` `location /api/` → `proxy_pass http://backend:8088`（**无尾斜杠 → 完整 URI 透传**）；`docker-compose.yml:2,10,16-17` 服务名 `backend`、`PORT=8088`、`expose 8088` | ✅ 实测 `/api/health` → 200，`/api/images/pull/mirrors` → 200，链路通 |
| `/ws` 反代目标 | `nginx.conf:38-47` `/ws/` → 同一上游 + `Upgrade`/`Connection: upgrade` + `proxy_http_version 1.1` + `proxy_buffering off` + 3600s 读超时 | ✅ 实测 `/ws/logs` 收到实时文本帧 |
| 对外端口 | `docker-compose.yml:23-25` `127.0.0.1:8088:80` | ✅ 满足 `spec.md:111`（见 §C.1） |
| 后端可达性 | 后端无 `ports`，仅 `expose 8088`（`docker-compose.yml:16-17`）；`backend/Dockerfile:15` `uvicorn --host 0.0.0.0 --port 8088` | ✅ `--host 0.0.0.0` 是**容器网络内**通信所必需，容器未发布端口，不构成 `spec.md:111` 意义上的「后端暴露到 0.0.0.0 公网端口」 |
| socket 挂载 | `docker-compose.yml:6-7` `/var/run/docker.sock:/var/run/docker.sock` + `:9` `DOCKER_HOST=unix:///var/run/docker.sock` | ✅ 与 `spec.md:34` D2、`plan.md:17` 一致 |
| 后端依赖锁 | `backend/Dockerfile:8` `COPY pyproject.toml uv.lock ./` + `:12` `uv sync --frozen --no-install-project` | ✅ 与 `spec.md:60` D7、`plan.md:14` 一致；`backend/uv.lock` **已在版本控制内**（见 §G.1） |
| 前端依赖锁 | `frontend/Dockerfile:4-5` `COPY package.json package-lock.json` + `npm ci` | ✅ 比 `plan.md:999` 的 `npm install` 更可复现 |
| 服务数量 | 实际 2 个（`deploy/docker-compose.yml`）vs `spec.md:101` / `plan.md:1034-1051` 的 3 个 | ⚠️ 功能等价、已文档化（`README.md:194`、`deployment.md:25`）→ 见 T12 |
| `.env` 生效范围 | `docker-compose.yml:14` 用 `${IMAGE_MIRRORS:-…}`；`:9-11` 硬编码 `DOCKER_HOST`/`PORT`/`TMP_DIR` | 🟡 **F-03**：与 `README.md:71`、`deployment.md:83-85` 的「.env 可覆盖」不一致 |
| 运行产物 ↔ 源码 | 线上 `/` 引用 `/assets/index-BGeOqOmG.js` = 本地 `frontend/dist/assets/index-BGeOqOmG.js`；bundle 含 HEAD 独有串（`浏览器未允许读取剪贴板`、`已复制`、`/images/pull/mirrors`、`/volumes",{name:`） | ✅ **运行中的部署确为 HEAD 构建产物**，本次实测结论对得上被审版本 |

### B.5 实时契约探针原始结果（供复核）

```
GET   /api/health                  -> 200  {"status":"ok"}
GET   /api/containers              -> 200  [...]
GET   /api/containers/             -> 307  Location: http://127.0.0.1/api/containers   ← F-04
GET   /api/images/                 -> 307
GET   /api/networks/               -> 307
GET   /api/images/pull             -> 405  {"detail":"Method Not Allowed"}   ← 正确（该路由为 POST）
POST  /api/health                  -> 405  {"detail":"Method Not Allowed"}   ← 正确
GET   /api/container               -> 404  {"detail":"Not Found"}            ← 正确
POST  /api/volumes  {"name":"x"}   -> 422  loc:["body"] string_type          ← 🔴 F-01
POST  /api/volumes  "x"            -> 200  {"ok":true}                       ← 后端期望的形态（探针卷已删除）
POST  /api/networks {"driver":"bridge"} -> 422 loc:["body","name"]           ← embed ✔ 与前端一致
POST  /api/containers/{id}/commit {}    -> 422 loc:["body","repo"]           ← embed ✔ 与前端一致
WS    /ws/logs?filter=<running容器>      -> str 帧：nginx access log 行
WS    /ws/logs?filter=zzz-no-such       -> str 帧：{"error":"no container"}  ← F-05
WS    /ws/exec?container=zzz-no-such    -> 1000 (OK) 关闭，零帧               ← F-06
GET   /api/images/{id}/save             -> 200 application/x-tar, chunked, 无 content-length, TTFB 0.120s
```

---

## C. 生产就绪与安全复核

### C.1 `spec.md` §6 硬性对策落实（L109–117）

| 对策（引用） | 实现（file:line） | 判定 |
|--------------|-------------------|------|
| 「部署强制仅映射 127.0.0.1 访问…docker-compose 绑定 `127.0.0.1:8088`」（`spec.md:111`，同 `plan.md:13`） | `deploy/docker-compose.yml:23-25` `- "127.0.0.1:8088:80"` + 注释 `# Bind only to localhost for security (spec C2)` | ✅ **硬性满足**，实测线上 nginx 仅在 127.0.0.1:8088 |
| 「禁止后端暴露到 0.0.0.0 公网端口」（`spec.md:111`） | 后端服务仅有 `expose: 8088`（`docker-compose.yml:16-17`），无 `ports` | ✅ 满足（`backend/Dockerfile:15` 的 `--host 0.0.0.0` 是容器内监听，未发布） |
| 「文档显式安全提示」（`spec.md:36`、`spec.md:111`） | `README.md:254`「不做登录…**不要直接暴露到公网**」+ `README.md:258`；`docs/deployment.md:135-152` 独立「§5 安全」章节；`docs/troubleshooting.md:241-245` | ✅ 满足，三处文档齐备 |
| socket 挂载最小权限 | `docker-compose.yml:6-7` 只挂 socket 单文件；无 `privileged`、无 `cap_add`、无 `network_mode: host`、无额外挂载 | ✅ 最小必要面。🟢 备注：未做 `read_only: true`／`cap_drop: [ALL]`／非 root 用户运行（`spec.md` 未要求，属可选加固） |
| 「大镜像导出内存」→ StreamingResponse（`spec.md:112`） | `images.py:99` `StreamingResponse(img.save(), media_type="application/x-tar")`；实测 `transfer-encoding: chunked`、无 `content-length`、TTFB **0.120s** | ✅ **真流式已实测量化**（见 §C.4） |
| 「长日志/高并发 WS」→ 消息节流、断线重连、防抖（`spec.md:113`） | 已做：`ContainerLogs.vue:45,75-77` `MAX_LINES=3000` 截断（近似节流）；已做：`ws.py:88-111` 阻塞读线程化 | ⚠️ **部分**：无自动重连（仅手动「重连」按钮 `ContainerLogs.vue:26`、`ContainerTerminal.vue:11`），无防抖 → **F-11 🟡** |
| 「exec 需 TTY / resize」→ `tty=true`、处理 resize（`spec.md:114`） | `ws.py:154-162` `stdin=True, tty=True, stdout=True, stderr=True`；`ws.py:207-217` `api.exec_resize`；前端 `ContainerTerminal.vue:86` 发 resize、`:75-93` `fit()` 含 0 尺寸保护 | ✅ 完整，且有专项回归（`test_ws_exec.py:136-159` 断言 `height=rows/width=cols`） |
| 「docker-py 与 daemon 版本」→ 文档标注兼容范围（`spec.md:115`） | `docs/deployment.md:33` Docker Engine 20.10+；`backend/pyproject.toml:8` `docker>=7.1`、`:3` `requires-python = ">=3.12"` | ✅ 满足 |

### C.2 无持久化原则（`spec.md:38-39` D3、`spec.md:65-75` §3）

- 对 `backend/app/**` 全量正则检索 `sqlite|json.dump|pickle|open(|write_text|write_bytes|.db|sqlalchemy`：**命中仅 3 处，全部合规** —— `files.py:19`（上传中转写临时目录，`spec.md:73` 明确允许）、`files.py:22`（`tarfile.open` 内存 buffer）、`volumes.py:24`（函数名误匹配）。
- `backend/pyproject.toml:5-11` 依赖中**无 ORM、无数据库驱动**。
- `deploy/docker-compose.yml` **无命名卷、无绑定挂载的数据目录**（唯一挂载是 `docker.sock`）→ 平台自身零持久化状态。
- 未发现任何"偷偷落库/写状态文件"的行为。✅ **无违反**。
- 🟢 附带说明：`spec.md:73` 提到临时目录「可用 volume 持久化」，实现**未**采用（`TMP_DIR=/tmp/dockermgr` 留在容器可写层，`docker-compose.yml:11`），这与 `spec.md:49`「启动时清空该目录」的语义更自洽，判为合理选择。

### C.3 临时目录策略（`spec.md:47-50` D4 + architect A1 修订）

| 策略要求 | 实现 | 判定 |
|----------|------|------|
| 「启动时清空该目录」 | `main.py:15-18` `lifespan` → `clear_tmp_dir()`；`services/files.py:12-16` 遍历删除 | ✅ 落实（唯一细节：只删文件不删子目录，当前代码只产生文件，无实际影响 🟢） |
| 「单次下载完成后即删对应文件」 | 拷入成功路径 `files.py:25` `local.unlink(missing_ok=True)` ✅；**拷出与镜像导出根本不落盘**（`files.py:34-35`、`images.py:99` 直接流式），无对象可删 | ✅ 语义满足（且**优于**要求：不落盘则无残留） |
| 「失败残留由启动清兜底」 | 拷入异常路径（`files.py:27-28`）**不删** `local`，依赖下次启动清理 | ✅ 与 spec 表述一致 |
| 「负责模块：`services/files.py`…`main.py` 启动回调触发清空」 | `services/files.py` + `main.py:12,17` | ✅ 与 `spec.md:50` 分工一致 |

🟢 **与 `spec.md:44` 字面流程的偏差**：spec 写「拷出：`get_archive()` 出容器 → **后端临时** → 前端下载」，实现是容器→响应流直连。但 `plan.md:602-608` 给出的参考实现本身就是直连流式，且不落盘更贴合 `spec.md:57` D6 与 `spec.md:112` 的内存对策 → 判为**合理偏差**，非缺陷。

### C.4 `spec.md:56-57` D6「`docker save` 流式导出」是否真流式

- 代码：`images.py:96-101`，`StreamingResponse(img.save(), media_type="application/x-tar")`，**无任何 `.read()`/`BytesIO` 预读**。
- 实测（线上，对一个真实镜像发起导出并在 128 KB 处主动断开）：

```
status 200  content-type application/x-tar
content-length: None   transfer-encoding: chunked   content-disposition: None
time-to-first-byte: 0.120s   first 131072 bytes read, then client aborted
```

→ **是真流式**：无 `Content-Length`（未预先生成完整 tar）、分块传输、首字节 0.12s 到达。✅ **无违反**。

🟢 附注：响应未设置 `Content-Disposition`，浏览器下载文件名完全依赖前端 `<a download>`（`ImagesView.vue:171-175`）。同源场景下可用，但直接访问该 URL 时无文件名。`spec.md` 未要求，登记为可选改进。

### C.5 其他生产就绪观察（`spec.md` 未强制，登记备查）

| 项 | 证据 | 判定 |
|----|------|------|
| 无 `.dockerignore` | 根/`frontend/`/`backend/` 均不存在；`frontend/node_modules` 实测 116.1 MB 在磁盘上、`frontend/dist` 13 个产物在磁盘上 | 🟡 **F-10** |
| nginx 大流量配置 | `nginx.conf:11-13`（3600s 超时）、`:17-18`（`proxy_buffering off` / `proxy_request_buffering off`）、`:22`（`client_max_body_size 0`）、`:44-45`（WS 超时） | ✅ 与 `troubleshooting.md:52,79` 记录一致 |
| SPA history 回退 | `nginx.conf:24-26` `try_files $uri $uri/ /index.html` | ✅ 与 `troubleshooting.md:198-206` 一致 |
| compose 无 `restart:` 策略 | `deploy/docker-compose.yml` 全文无 `restart` | 🟢 宿主重启后平台不自启；`spec.md` 未要求 |
| compose 无 `healthcheck` / `depends_on: condition` | `docker-compose.yml:26-27` 仅 `depends_on: [backend]` | 🟢 后端未就绪时 nginx 会短暂 502；实测当前正常 |
| 容器日志无轮转配置 | 无 `logging:` 段 | 🟢 json-file 默认无限增长，长期运行需注意 |

---

## D. 发现清单

> 严重度：🔴 Critical / 🟡 Important / 🟢 Minor　性质：**HARD VIOLATION**（有可引用依据）／**JUDGEMENT CALL**（需说明推理）

| # | 严重度 | 位置（file:line） | 描述 | 性质 | 依据引用 |
|---|--------|-------------------|------|------|----------|
| **F-01** | 🔴 | `backend/app/routers/volumes.py:24` ↔ `frontend/src/api/index.ts:86`、`frontend/src/views/VolumesView.vue:127` | **「创建数据卷」在界面上必然失败**。后端 `name: str = Body(...)` 是单个标量 Body 参数，FastAPI 不做 embed，要求请求体是**裸 JSON 字符串**；前端发送 `{"name": "..."}`。实测 `POST /api/volumes {"name":"dm-review-probe"}` → **422** `{"loc":["body"],"type":"string_type"}`；发送裸字符串 `"x"` 才 200。同文件族的 `networks.py:24-25` 有两个 Body 参数 → 自动 embed，`{name,driver}` 正常（实测 422 报的是 `missing body.name`，证明形状正确）。**两个同类接口写法不一致，前端跟了 networks 的形状**。该 Task 的测试只有 list 两个断言（`test_networks_volumes.py:8-52`，源自 `plan.md:451-457`），因此漏过 | **HARD VIOLATION** | `scope.md:28` F5「卷管理 列表/**创建**/删除」；`plan.md:T5`(L438)「create `{name}`」；`spec.md:83`「容器 CRUD」（同类接口约定）；实测见 §B.5 |
| **F-02** | 🟡 | `frontend/src/views/ContainersView.vue:63-100,245-253`、`frontend/src/api/index.ts:63-64`、`backend/app/routers/containers.py:189,198` | **容器「暂停/恢复」无任何界面入口**。后端两条端点已实现，前端 axios 方法也已封装，但全仓检索 `pause|unpause` 在前端只出现在 `api/index.ts:63-64` 的定义处，**零调用点**；`act()` 只处理 `'start'|'stop'|'restart'`，下拉菜单 5 项里也没有。计划 T10 Step 1 明确要求操作列含「暂停」 | **HARD VIOLATION** | `scope.md:24` F1「启停/重启/**暂停**」；`plan.md:206`（pause/unpause 端点）；`plan.md:T10`(L886)「操作列：启/停/重启/**暂停**/…」；`scope.md:34` F11「全部动作走界面」 |
| **F-03** | 🟡 | `deploy/docker-compose.yml:9-11,14`、`README.md:71`、`docs/deployment.md:83-85`、`.env.example:3-6` | **`.env` 覆盖能力与文档不符**。文档让用户 `cp ../.env.example .env` 并声称「也可用同目录的 .env 覆盖」，但 compose 里只有 `IMAGE_MIRRORS` 用了 `${IMAGE_MIRRORS:-…}` 插值；`DOCKER_HOST`/`PORT`/`TMP_DIR` 是硬编码字面量。用户按文档改 `.env` 中的 `DOCKER_HOST` 将**完全没有效果**，且不会有任何提示 | **JUDGEMENT CALL**（文档与实现不一致；`spec.md` 未规定 `.env` 机制，但 `deployment.md` 是对外承诺） | `README.md:71`、`docs/deployment.md:83-85`、`.env.example:1-10` vs `deploy/docker-compose.yml:9-14` |
| **F-04** | 🟡 | `frontend/nginx.conf:32`（`/api/`）、`:43`（`/ws/`） | **反代丢了端口号**。`proxy_set_header Host $host` 中的 `$host` 不含端口，FastAPI 默认开启 `redirect_slashes`，其 307 的 `Location` 基于 Host 头生成。实测 `GET /api/containers/` → `307 Location: http://127.0.0.1/api/containers`（**端口 8088 丢失，指向未监听的 80**）。正确写法是 `$http_host`。**影响面有限**：前端自身所有调用都不带尾斜杠（§B.1 全部 200），故正常路径不受影响；受影响的是手工调 API、以及任何将来引入尾斜杠的调用方 | **JUDGEMENT CALL** | `spec.md:96-99` §5（要求 `/api/*` 反代到 backend:8088，隐式要求对外 URL 正确）；实测见 §B.5 |
| **F-05** | 🟡 | `backend/app/routers/ws.py:75` ↔ `frontend/src/components/ContainerLogs.vue:100-102` | **服务端错误帧被当日志行渲染**。后端在找不到匹配容器时 `send_json({"error": "no container"})`（`plan.md:691` 即如此设计），前端 `onmessage` 无条件 `append(e.data)`，因为该帧是**文本帧**（非 Blob），会原样显示成一行日志 `{"error":"no container"}`。用户看到的是"一条诡异日志"而不是"容器不存在"。实测已复现该帧形状。此外 `ws.py:18` 只匹配 running 容器且用 `startswith` 前缀匹配，容器名互为前缀时会静默连到错误的容器 | **JUDGEMENT CALL**（spec 未定义错误帧语义，但两端对同一帧的理解不一致） | `plan.md:T7`(L691)；`spec.md:85`「实时日志…逐行前向」；实测见 §B.5 |
| **F-06** | 🟡 | `backend/app/routers/ws.py:152,220-229` ↔ `frontend/src/components/ContainerTerminal.vue:209-213` | **exec 失败静默关闭**。容器不存在时 `containers.get` 抛异常被 `except Exception` 吞掉（`:220-221` 只 `logger.exception`），随后 `_close_ws` 以 1000 (OK) 关闭，**不发送任何帧**。实测 `ws://…/ws/exec?container=zzz-no-such-container` → `received 1000 (OK)`。前端只显示「会话已结束」，用户无法区分「容器不存在 / 容器没有 /bin/sh / shell 正常退出」 | **JUDGEMENT CALL**（`spec.md:114` 只要求 tty+resize，未定义错误语义） | `spec.md:114`；`plan.md:T8`(L752-780) |
| **F-07** | 🟡 | `backend/tests/test_ws_logs.py:21-29` | **计划给定的可失败测试被弱化为恒通过**。`plan.md:T7` Step 1（L652-662）给的测试体是 `with c.websocket_connect("/ws/logs?filter=&stream=stdout") as ws: ws.send_text("ping")` —— 路由缺失时 `websocket_connect` 会抛异常，测试**会失败**。实现把整个块包进 `try: … except Exception: pass`，于是**任何失败都被吞掉**，该测试对路由存在性、帧格式、错误语义均零断言价值（`66 passed` 里有它一份，但不构成任何证据） | **HARD VIOLATION**（违反 `plan.md:T7` 的验证要求） | `plan.md:T7`(L650-662)「Step 1: 写失败测试」 |
| **F-08** | 🟡 | `scripts/e2e_verify.py:210-217`、`:189-201` | **E2E 断言存在假阴性**。`test_ws_logs` 只判断 `isinstance(msg, str)`，15s 无输出也记 PASS —— 而由上一条（F-05），后端在"找不到容器"时发的**正是**一个 JSON 文本帧，因此**日志链路完全不通也会 PASS**。另 `test_image_remove` 无论 DELETE 成败都 `record(..., True, ...)`。旁证：本机镜像列表残留 `dockermgr-e2e:0476b11a`（正是该脚本 `:152-153` 的命名模式），说明清理路径并未真正生效 —— 与"18/18 全绿"的自述形成对照 | **JUDGEMENT CALL** | `spec.md:113`（对策有效性依赖可信验证）；`README.md:101` 的「18/18」是自我声明 |
| **F-09** | 🟡 | `backend/tests/test_files_api.py:27-28` + `backend/app/services/files.py:18-19,25` + `backend/a.txt:1` | **测试污染仓库工作区，且污染产物已被提交**。该测试把 `get_tmp_dir` monkeypatch 成 `Path(".")`，让上传文件落在**当前工作目录**（即 `backend/`）；又刻意让 `put_archive` 抛异常（`:16-17`），使成功分支的 `local.unlink()`（`files.py:25`）不执行。于是 `a.txt` 留在 `backend/`。核对：`backend/a.txt` 内容为 `hi`，与测试上传的 `io.BytesIO(b"hi")`（`:33`）完全一致，且由 `e4f5fff`（Task 6 提交）带入库。**根因是测试没有指向 `tmp_path`** | **HARD VIOLATION**（生成物入库 + 测试未隔离） | `plan.md:T6`(L516-633) 未要求落盘位置，但仓库整洁性与 `plan.md:1074`「每个 Task 独立 commit」的意图相悖 |
| **F-10** | 🟡 | `frontend/Dockerfile:5-6`（无 `.dockerignore`） | **前端镜像构建会把宿主 `node_modules` 覆盖进镜像**。仓库根/`frontend/`/`backend/` 均无 `.dockerignore`，构建上下文为 `../frontend`（`deploy/docker-compose.yml:20-21`）→ 会把实测 116.1 MB 的 `frontend/node_modules`（含 Windows 平台原生二进制）和 13 个 `frontend/dist` 产物一并送进 context；`:5` `RUN npm ci` 装好 Linux 依赖后，`:6` `COPY . .` 又用宿主目录**覆盖**它。这与 `README.md:33-48`「经验记录 1」强调的"构建应可复现"自相矛盾，也是同类问题（依赖锁）之外尚未清理的一处 | **JUDGEMENT CALL**（`spec.md:60` D7 只要求锁文件复现，未提 `.dockerignore`） | `spec.md:60`；`README.md:33-48`、`docs/development.md:124`（同一"可复现"价值取向） |
| **F-11** | 🟡 | `frontend/src/components/ContainerLogs.vue:111-119`、`frontend/src/components/ContainerTerminal.vue:219-229` | **`spec.md:113` 的三条对策只落实了一条**。spec 对「长日志/高并发 WS」列出的对策是「**消息节流、断线重连、防抖**」。已落实：`MAX_LINES=3000` 截断（`ContainerLogs.vue:45,75-77`，近似节流）。**未落实**：无自动重连（两个组件都只有手动「重连」按钮）、无防抖。WS 断开后界面停在"已断开/会话已结束"，需人工点击；日志流断开会静默丢失后续输出 | **HARD VIOLATION**（`spec.md` §6 对策是逐条列出的硬性要求） | `spec.md:113`；`plan.md:T7`(L637-714) 未细化，属 spec→plan 的传递丢失 |
| **F-12** | 🟢 | `backend/app/services/docker.py:18-37`、`backend/app/routers/networks.py:11-19`、`backend/app/routers/volumes.py:11-18`、`backend/app/routers/images.py:76-84` | **Task 2 声明的 4 个数据类型有 3 个是死代码**，并连带一处文档过度声明。`plan.md:T2`(L124) 的 Produces 要求 `ContainerInfo / ImageInfo / NetworkInfo / VolumeInfo`；全仓 grep 显示只有 `ContainerInfo` 被 import 与实例化（`containers.py:5,76,83`），另外三个**零引用** —— networks/volumes 直接返回 dict（`networks.py:12-17`、`volumes.py:12-17`），images 返回匿名 dict。**连带**：`ImageInfo.size` 字段因此无处产出，`README.md:26` 声称镜像列表「含标签、**大小、创建时间**」不成立（实测 `/api/images` 只有 `id/tags/digest/short_id`）。另 `GET /api/containers/{cid}`（`containers.py:154`，实测 200）无任何前端调用，"容器详情"在界面上不可达 | **JUDGEMENT CALL**🟢 / 详情部分 **HARD VIOLATION** | `plan.md:T2`(L124)、`spec.md:70`（§3 数据模型含 ImageInfo）；`scope.md:24,26,27`（F1/F3/F4 均含「详情」）；`README.md:26` |
| **F-13** | 🟢 | 缺 `frontend/src/views/SettingsView.vue` | 计划文件清单中的 `SettingsView.vue`(占位) 从未创建，`frontend/src/views/` 只有 4 个视图，`router/index.ts:3-29` 只有 4 条路由（无 `/settings`）。无功能影响（`spec.md` 无设置项），仅为计划清单未闭合 | **HARD VIOLATION**（计划 Files 清单未满足） | `plan.md:810` |
| **F-14** | 🟢 | `docs/development.md:158`、`docs/troubleshooting.md:168`、`docs/deployment.md:34` | **文档描述的实现细节与代码不符**。（a）两份文档都写「用 `run_coroutine_threadsafe` 把结果送回事件循环」，实际 `ws.py:34` 用的是 `loop.call_soon_threadsafe` —— 这是排障文档里最该准确的一处（它指导后人"正确做法"）。（b）`deployment.md:34` 断言「带连字符的 `docker-compose` 不支持」，实际 docker-compose v1 支持（只是已 EOL）；且仓库里文件名就叫 `docker-compose.yml` | **JUDGEMENT CALL** | `spec.md:115`（要求文档标注兼容范围，故文档准确性在本 spec 的射程内） |
| **F-15** | 🟢 | 12 个 Task commit（如 `1b1e5cb`、`855bee6` … `50e904d`） | **「提交节奏」要求未遵守**。`plan.md:1076` 要求「每个 Task 独立 commit，Task 内部按 **TDD 红→绿增量提交**」；实测 12 个 Task commit **各只有一次提交**，测试与实现同批入库（`git show --stat 1b1e5cb` = 5 files/52 insertions 同时含 `tests/test_health.py` 与 `app/main.py`）。因此「先跑测试确认失败」（各 Task 的 Step 2）在版本历史上**无从考证**，TDD 只剩测试存在这一可验证痕迹 | **HARD VIOLATION**（流程要求未满足） | `plan.md:1074-1076` |
| **F-16** | 🟢 | `backend/app/services/docker.py:43-50`、`backend/app/config.py:12` | **`config.py` 的 `docker_host` 基本是死配置**。`get_docker_client()` 先试 `docker.from_env()`，仅在其**抛异常**时才回落到 `get_settings()["docker_host"]`。而 `docker.from_env()` 自身就读取同名 `DOCKER_HOST` 环境变量，且缺省时**不会抛异常**（客户端是惰性连接的），所以 `except` 分支几乎不可达。行为上等价（compose 设置了 `DOCKER_HOST`），仅在 Windows 本地开发时 `from_env()` 会走平台默认 endpoint（这正是 `development.md:33-37` 期望的行为）。登记为与 `spec.md:61` D7「config.py 从环境变量读取（DOCKER_HOST、PORT）」的一层绕行 | **JUDGEMENT CALL** | `spec.md:61`（D7）；`plan.md:T2`(L172) 的参考实现是直接用 `get_settings()["docker_host"]` |

**统计：🔴 1 条（F-01）；🟡 9 条（F-02～F-11，其中 F-12 的"详情"子项亦为硬违规）；🟢 5 条（F-12～F-16）。合计 15 条**（F-12 同时含 🟢 与硬违规子项，计入 🟢 一栏）。

---

## E. 亮点

1. **`/ws/logs` 的事件循环冻结被真正解决，而且有能失败的验证**。`ws.py:88-101` 把 `logs(follow=True)` 这个**阻塞生成器**丢到工作线程，用 `loop.call_soon_threadsafe` 回投；`:105-111` 用 `asyncio.wait_for(ws.receive(), 0.5)` 轮询断连而不是阻塞等待。更关键的是 `test_ws_logs_blocking.py:111-151` **起了一个真实 uvicorn**，在流空闲时断言 `/api/health` 3 秒内必须返回 —— 这是全仓唯一一个能真实复现该缺陷（mock 无法复现）的测试。对应 `spec.md:113` 与 `plan.md:T7` 里最难的一块。
2. **exec 走低层 API 保留 `exec_id` 才有 resize**。计划参考实现用 `containers.exec_run()`（`plan.md:762`），拿不到 exec id 也就无法 resize。实现改用 `api.exec_create`（`ws.py:154-162`）+ `api.exec_resize`（`:207-217`），并显式传 `stdin=True`（注释 `:158` 写明"without it the daemon discards all input"）。`test_ws_exec.py:136-159` 断言 `(height, width) == (30, 120)` 校验了 rows/cols 的**映射方向**（这是个容易搞反的地方）。
3. **镜像导出改用浏览器原生下载，比计划更贴合 D6**。`plan.md:939-943` 的参考代码是 `imagesApi.save(id)` 取 blob 再 `URL.createObjectURL` —— 那会把整个 tar **读进浏览器内存**。实现改为 `<a href="/api/images/{id}/save">`（`ImagesView.vue:170-176`），浏览器原生下载流式落盘。这与 `spec.md:57` D6「避免大镜像占内存」的**意图**同向，且实测后端侧确为 chunked 流式。
4. **文件上传做了路径穿越防护**。`files.py:18` 用 `os.path.basename(file.filename)` 再拼临时目录，而 `plan.md:589` 的参考实现是 `tmp / file.filename`（`file.filename` 可含 `../`）。
5. **两个真实线上缺陷修得干净且有文档追溯**。`_format_ports`（`containers.py:29-50`）把 docker-py 的 `{'80/tcp': [{'HostIp','HostPort'}]}` 渲染成人类可读串并做 IPv4/IPv6 去重（`troubleshooting.md:99-103`）；`_image_name`（`:53-73`）对"镜像已删除的悬空引用"做 `tags → Config.Image → 短 ID` 三级兜底，避免整页 500（`troubleshooting.md:89-95`）。两者都有针对性单测（`test_containers_api.py:115-161`）。
6. **mock 形状的纪律被写成团队约定**。`test_containers_api.py:14-21` 的 mock 刻意不提供 `.state`、把 `ports` 写成 dict、把 `tags` 写成 list，与真机一致；`development.md:111-124` 把这六个"真机 vs 想当然"的差异列成表格。这是把一次线上事故转成制度的好做法。
7. **依赖锁与可复现构建**：`frontend/Dockerfile:4-5` 用 `npm ci` + 已提交的 `package-lock.json`（计划写的是 `npm install`）；`backend/Dockerfile:8,12` 用 `uv sync --frozen` + 已入库的 `uv.lock`（见 §G.1）。

---

## F. 存疑 / 未能独立验证项

1. **E2E `18/18`（`README.md:101`）—— 未能独立验证。** `scripts/e2e_verify.py` 会真实创建/启动/删除容器与镜像（`:281-333` 建容器、`:151-163` commit 镜像），超出本次只读审查的边界，我**没有运行它**。旁证：本机镜像列表仍残留 `dockermgr-e2e:0476b11a`，与脚本 `:152-153` 的命名模式一致 → 该脚本确实在本机跑过；但"18/18"这一具体数字未被复现，且其断言质量见 **F-08**。
2. **浏览器逐页验证「0 页面错误 / 0 控制台错误 / 0 失败请求」（`README.md:102`）—— 未能独立验证。** 运行 `.browser-tools\Scripts\python.exe scripts\ui_verify.py` 时，Playwright 启动驱动子进程被沙箱拒绝：`PermissionError: [WinError 5]` 落在 `asyncio\windows_utils.py:63` 的 `CreateFile`（即"带管道的子进程"这一沙箱边界）。本会话审批提示已禁用，无法提权，也未改用其他方式绕过。
3. **终端复制粘贴回归 6/6（`README.md:103`）—— 未能独立验证。** `ui_clipboard_test.py:31` 要求**有头**运行（脚本注释说明 headless 不接系统剪贴板），同样受上一条的沙箱边界阻断。
4. **`npm run build` 完整链路 —— 部分验证。** `vue-tsc -b --force` **退出码 0**（前端全量类型检查无错误，已强制重建 tsbuildinfo），满足 `plan.md:860-863`/`plan.md:913-916`/`plan.md:953-955` 中"无类型错误"这一半要求；`vite build` 阶段因 esbuild 需要 spawn 带管道子进程而失败（`Error: spawn EPERM`，`node_modules/esbuild/lib/main.js:1975`），未跑完。间接证据：本地 `frontend/dist/assets` 与线上 `/assets/` 文件名一致，且 bundle 内含 HEAD 独有字符串 → 存在一次成功的 HEAD 构建产物，但不能证明"当前时刻可重新构建成功"。
5. **`docker compose up -d --build` 全新构建（`plan.md:1053-1057`）—— 未运行。** 本机 docker CLI 因命名管道被沙箱拒绝：`permission denied while trying to connect to the docker API at npipe:////./pipe/dockerDesktopLinuxEngine`。**一个可用的部署确实已在运行**（`127.0.0.1:8088`，`Server: nginx/1.31.5`）并已通过实测，但"全新 clone 后能否构建"这条路径未经我验证（结合 **F-10** 与 §G.1，这条路径的风险仍值得单独验证）。
6. **F9/F10 的写操作端到端（进终端执行命令、文件双向拷贝往返）—— 未做写操作实测。** 仅验证了路由存在与两侧契约逐字段一致（§B.2）。终端我在探针中只做了"连不上时的行为"验证，未在真实容器里执行命令。
7. **OCR 预扫未执行（ocr CLI 未配置 LLM 端点）。** `docs/epics/docker-manager-v1/ocr/` 下**不存在** `ocr-preview.md` / `ocr-preview.json`；`BASE_SHA` 为 `c689f71a52f9cffb89c80efd706149b3d95307ec`（与本次 BASE 一致，说明基线设置正确）。目录下唯一的 `ocr-background.md` 经逐行核对是 `spec-review/final/spec.md` 的**完整副本**（130 行内容一致），不是 OCR 报告，故未采信、也无从逐条验证。据协调者反馈，ocr CLI v1.9.2 因 `resolve LLM endpoint: no valid LLM endpoint configured` 在派发前即失败退出。**本报告无 OCR 输入。**
8. **`spec.md:113`「消息节流」的判定余地**：我按"`MAX_LINES` 截断 ≈ 节流"记为实现了一部分（F-11）。若审阅者认为"节流"特指服务端发送频率控制，则该条应从"部分落实"升级为"三条全未落实"，严重度不变。

---

## G. 三条必须独立核实的已知事实 —— 结论

### G.1 `.gitignore` 忽略 `uv.lock` 导致全新 clone 构建失败 → **在 HEAD 已修复，不再是缺陷**

独立核实链条：

| 证据 | 命令 | 结果 |
|------|------|------|
| `.gitignore` 现状 | 读 `D:\桌面\测试\docker-manager\.gitignore` | **第 5–8 行是一条注释，明确写明 `uv.lock` 是"deliberately COMMITTED, not ignored"**，并解释了原因（`backend/Dockerfile` 的 `COPY pyproject.toml uv.lock ./` + `uv sync --frozen`） |
| 是否被忽略 | `git check-ignore -v backend/uv.lock` | **退出码 1 → 未被忽略** |
| 是否已入库 | `git ls-files uv.lock backend/uv.lock frontend/package-lock.json` | 输出 `backend/uv.lock` 与 `frontend/package-lock.json` |
| HEAD 树内是否存在 | `git cat-file -e 8149029:backend/uv.lock` | 退出码 **0 → 存在于 HEAD 树** |
| 何时入库 | `git log --oneline --diff-filter=A -- backend/uv.lock` | `8149029 docs: add README, deployment, development and troubleshooting guides` |
| `.gitignore` 变更史 | `git log --oneline -- .gitignore` | …, 末次为 `8149029` |

**结论**：`README.md`（Epic 演进日志）`:74` 的「`.gitignore` 忽略 `uv.lock`…**待修复**」**已过期**。修复与撰写该 README 的是**同一个提交 `8149029`** —— 自述写于修复之前（或未同步），导致文档滞后于代码。`backend/Dockerfile:8,12` 与 `.gitignore:5-8` 现在**互相自洽**，全新 clone 的 COPY 步骤不会再失败。

- 严重度：**无需修复**（代码层合规 ✅）。
- 附带问题：Epic 演进日志「未完成项」表需更新 → 已作为 **F-16 同源文档问题**登记为 🟢（引用 `README.md:74`、`.gitignore:5-8`）。
- 归入 **Task 12 矩阵行**：该行"部署链路"各项判定为 ✅，不因本条扣分。

### G.2 `plan.md` Task 11 计划预审 Fail → **已知接受偏差，矩阵标 ⚠️**

- 引用：`README.md:76`「计划预审遗留…`plan.md` Task 11「打包三个独立视图」在预审时记 Fail（3/4），实际实现已覆盖网络与卷两个视图，未拆成三个独立文件」、`README.md:94`「⚠️ 3/4（Task 11 打包三个独立视图，严格记 Fail，可进计划评审）」。
- 本报告按约定在矩阵中标 ⚠️ 并引用，**不重新计为新发现**。
- **一处校准（非新发现，仅为事实核对）**：`frontend/src/views/` 下 `ImagesView.vue`、`NetworksView.vue`、`VolumesView.vue` **三个文件确实各自独立存在**（commit `7cfa52c`）。因此 `README.md:76` 对 Fail 原因的描述（"未拆成三个独立文件"）与该事实不符 —— 若预审原意是"未拆成三个独立 commit"或"提交信息写作 `feat: images/network/volume views`"，建议在 `README.md` 中改写措辞，否则后续读者会得出与代码相反的结论。

### G.3 `README.md:100-102` 的测试声明 → **一真两未验证**

| 声明 | 独立核实 | 结论 |
|------|----------|------|
| 「后端单元测试 66 passed」 | ✅ 我跑了：`uv run --frozen --no-sync pytest -q` → **66 passed, 2 warnings in 2.69s**；`--collect-only` 亦为 66 | **以证据采信**（细节见 F-07：其中 `test_ws_logs.py` 那一条是恒通过的空断言，数量对但证据力不齐） |
| 「端到端（真实 Docker）18/18 passed」 | ⛔ 未运行（脚本会真实创建/删除容器与镜像） | **未能独立验证**；且其断言质量见 **F-08**（存在假阴性，且清理未真正生效有旁证） |
| 「浏览器逐页验证 0 页面错误 / 0 控制台错误 / 0 失败请求」 | ⛔ 未能运行（Playwright 子进程被沙箱拒绝，见 §F.2） | **未能独立验证** |
| 「终端复制粘贴回归 6/6」 | ⛔ 未能运行（需有头，同上） | **未能独立验证** |
| 「提交数 22」 | ✅ `git rev-list --count BASE..HEAD` = 22 | 以证据采信 |
| 「后端 Python ~1.7k 行 / 前端 TS+Vue ~2.1k 行」（`README.md:207`） | 未逐行统计（非判定项） | 存疑，不影响结论 |

---

## H. 结论摘要

- **Task 1–12 判定**（以 §A 表格「判定」列逐行为准，无歧义口径）：

  | 判定 | 数量 | Task |
  |------|------|------|
  | ✅ 完成 | **5** | T1、T3、T4、T6、T8 |
  | ⚠️ 部分 | **7** | T2、T5、T7、T9、T10、T11、T12 |
  | ❌ 缺失 | **0** | — |

  另有两节计划要求未满足：**「验证闭环」⚠️**（F1/F3/F4/F5/F11 有缺口）、**「提交节奏」⚠️**（12 个 Task 各只有 1 个 commit，无红→绿增量提交，F-15）。
  ➕ **超范围但落在 `spec.md` 射程内**的增量：`POST /api/containers` 新建容器（`spec.md:83` 容器 CRUD）、`RunContainerDialog` 及其预设、镜像源降级（`spec.md:84` 拉取镜像）、`GET /api/images/pull/mirrors`。
  ➕ **超范围且 spec 未覆盖**的项：**无**（逐条核对 `spec.md:121-130` §7 见 §A.1(b)）。

- **发现**：🔴 1 · 🟡 9 · 🟢 5（明细见 §D）。
- **跨层契约**：HTTP 路径/方法/前缀/尾斜杠**全部对齐**（§B.1 的 18 项中 16 项 ✅）；WebSocket 参数名、帧格式、文本/二进制模式**全部对齐**（§B.2）；**唯一断裂是 `POST /api/volumes` 的 Body 形状（F-01 🔴，必然失败）**。部署链路自洽，且已证实运行中的产物就是 HEAD 构建（§B.4）。
- **生产就绪**：`spec.md` §6 的硬性对策**逐条落实**（`127.0.0.1:8088` 绑定 ✅、后端不暴露 ✅、安全提示三处 ✅、流式导出经量化实测 ✅、tty+resize ✅）；无持久化**零违反**；临时目录策略符合 D4；D6 是真流式。未落实的是 §6 里 WS 的「断线重连/防抖」（F-11）。
- **最该优先处理的三件事**：F-01（创建卷不可用，🔴）、F-02（暂停/恢复无入口，F11 硬要求）、F-09（测试污染已把垃圾文件提交进仓库）。
