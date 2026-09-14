# 代码审查报告 — docker-manager-v1

> 审查时间：2026-09-11
> 审查范围：`c689f71a52f9cffb89c80efd706149b3d95307ec..81490291321b22d06aec0cfbeff05f06bb7905c2`（21 个编码 commit、63 文件、+9859/-4）
> 审查方式：**三路隔离子代理（多透镜）+ 协调者交叉比对**——后端透镜 / 前端+部署透镜 / 计划对齐+跨层契约透镜，均不继承编码上下文，不采信 README、注释、commit message 的自我声明
> OCR 预扫：**未执行**——ocr CLI v1.9.2 已安装，但 `resolve LLM endpoint: no valid LLM endpoint configured`（`OCR_LLM_URL`/`OCR_LLM_TOKEN`/`OCR_LLM_MODEL`、`~/.opencodereview/config.json`、`ANTHROPIC_*` 均未配置），按 skill「增强非门禁」规则跳过；五段审查不依赖该输入
> BASE_SHA 解析（写死规则）：仓库**单分支 master、无 main**，`git merge-base main HEAD` 不可用（会得到空 diff → 漏审全部改动），故显式取 `c689f71`（Task 1 的父提交）。本次已补落 `docs/epics/docker-manager-v1/ocr/BASE_SHA`，供后续审查复用
> 透镜报告（原始，含逐条证据）：`test-review/rd1/review-backend.md` · `review-frontend-deploy.md` · `review-plan-alignment.md`

---

## 审查结论

**Verdict：❌ NEEDS FIXES** ← 这是 **第一轮（rd1）的原始判定**，作为历史记录保留。

五段各自独立结论，**段间不抵消**。任一段存在未关闭的 🔴/🟡 → 整体即 NEEDS FIXES（第一轮据此判定）。

---

> ## 终态判定（第三轮修复后，2026-09-11）：**✅ APPROVED（附 1 项环境阻塞）**
>
> - 第一轮 21 条（1 🔴 / 20 🟡）**全部修复**；rd2 重审：19/21 关闭 + 新增 27 条（5 HARD，含 2 条修复批次自己引入的）；rd3 合并复核 36 条：**26 CLOSED / 3 PARTIAL / 7 NOT CLOSED**（后 6 条是记录在案的已知取舍，1 条升级为 RD3-01 后已修）。
> - rd3 新增 12 条**全部处置**：必修 2 条（RD3-01 正常机器上测试文件全 ERROR、RD3-02 事件循环冻结 1503ms）+ 4 条已修并有变异反证（RD3-04/06/11/12）+ 5 条文档/记录类已修 + RD3-03 记为已知限制（写入排障手册）。
> - **最终门禁（协调者自跑）**：`uv run --frozen pytest -q` → **137 passed**（两种 `%TEMP%` 模式一致）；`vue-tsc -b --force` → exit 0；AST 反模式扫描 → **hits=0**；真机 `e2e_verify.py` → **18/18 exit 0**；部署后契约探测 → **10/10 exit 0**。
> - ~~**唯一未闭合项是环境的**：Docker 守护进程拉不到 `ghcr.io/astral-sh/uv`，后端镜像无法重建 → 线上修复靠 `docker cp` 生效，容器与镜像不一致。~~ **已解决**：`backend/Dockerfile` 改为从 PyPI 装 uv（去掉 ghcr.io 依赖），`up -d --build` 成功、容器已从新镜像重建、容器内代码哈希与工作区源码**逐一 MATCH**；连同 RD3-09 一起关闭。证据见 §2.5「E-1 关闭证据」。
> - 全部修复仍是**工作区未提交改动**（基线 `8149029`）；是否提交、如何拆分由用户决定。

| 段 | 结论 | 关键发现 |
|----|:--:|---------|
| Plan alignment | ❌ | 1 🔴（卷创建界面必失败）+ 5 🟡：WS 三对策缺失、暂停/恢复零 UI 入口、停止容器看不了日志、导出丢 tag、R4 蔓延；Task 1–12 中 7 个 ⚠️ |
| Code quality | ❌ | 3 🟡：假成功反馈（裸 `<a href>` 无失败通道）、超时策略自相矛盾、WS 错误帧语义 |
| Architecture | ❌ | 3 🟡：跨站 WS 劫持/无 CSRF（socket=宿主 root）、nginx `Host $host` 丢端口 → 307 指向 80、构建上下文无 `.dockerignore`（118.2 MB） |
| Testing | ❌ | 7 🟡：E2E 永不返回非零、E2E/UI 断言可假阳性、`test_ws_logs` 恒通过空断言、测试污染仓库并误提交 `backend/a.txt`、14 端点零单测、脚本换机必挂 |
| Production | ❌ | 2 🟡：`copy_into` async 内同步阻塞 I/O（唯一残留冻结点）、`.env` 文档承诺 4 变量实际 1 个 |

> 分段计数按**主要归属段**计（个别发现跨段，例如 C-01 同时属 Plan alignment 与 Testing）。

**发现计数（协调者去重后）**：🔴 1 · 🟡 20 · 🟢 约 31

> 各透镜自报原始计数：R1 后端 `0/6/22`、R2 前端+部署 `0/13/25`、R3 计划对齐 `1/9/5`。🟡 原始合计 29 条，跨透镜重复 8 条（WS 节流 3→1、暂停恢复 2→1、R4 蔓延 2→1、`.env` 2→1、`a.txt` 2→1、`.dockerignore` 2→1、WS 错误帧 3→1），去重后 **20 条**。🟢 原始合计 52 条，协调者按标题去重后约 31 条（**未逐条复核全部 Minor**，明细以 `rd1/` 三份透镜报告为准）。

---

## 跨透镜交叉比对与仲裁

三路独立审查，**9 条发现被两个以上透镜独立命中**（置信度最高）：

| 发现 | 命中透镜 | 结论 |
|------|---------|------|
| WS「节流 / 断线重连 / 防抖」整体缺失（`spec.md:113` 明文对策） | R1 + R2 + R3 | **三路一致**，HARD VIOLATION |
| 暂停/恢复有后端接口+前端 API 方法但零 UI 入口 | R2 + R3 | HARD VIOLATION（`scope.md:24` F1 含「暂停」） |
| 「从镜像运行容器」超出 plan T1–12 | R1 + R2 + R3 | **裁决见下（分歧）** |
| `.env` 文档承诺 4 变量、实际只 1 个生效 | R2 + R3 | HARD VIOLATION（文档与实现不符） |
| 测试把临时目录指到 CWD → `backend/a.txt` 被提交 | R1 + R3 | HARD VIOLATION |
| 缺 `.dockerignore` → 上下文 118.2 MB | R2 + R3 | 一致 |
| WS 错误帧被当日志行渲染 | R2 + R3 | 一致 |
| epic README「uv.lock 待修复」已过期 | R1 + R2 + R3 + 协调者 | 三路 + 协调者一致，**实证已修复** |
| R1–R5 修复轮次本身是否引入新缺陷 | R1 + R2 | 一致：修复本身正确，仅 `copy_into` 是同类残留 |

### 分歧裁决 1：`test_ws_logs.py` 空断言的严重度（R1 记 🟢 vs R3 记 🟡）

**裁决：升级为 🟡 HARD VIOLATION（采纳 R3）。** 协调者亲自读码取证：`backend/tests/test_ws_logs.py:22-29` 的 `assert msg.get("error") == "no container"`（:26）位于 `try` 内，`:27-29` 是 `except Exception: pass` —— **断言失败抛出的 `AssertionError` 本身就是 `Exception`，会被这个 `except` 吞掉**，因此该用例在任何情况下都会通过（恒真式）。依据 `plan.md:T7`（该 Task 的验证要求）→ 有可引用依据，属硬违规。R1 已把它记在自己报告的段 4（🟢），但其汇总文字同时承认「这是本套测试里唯一有『假绿』风险的写法」——二者矛盾，以升级后的判定为准。

### 分歧裁决 2：「从镜像运行容器」是否构成范围蔓延（R1/R2 记 HARD 蔓延 vs R3 判不违规）

**裁决：判为 🟡 JUDGEMENT CALL（需回写文档），不判硬违规。** 分歧根源是 **spec 自身矛盾**：

- 支持「在范围内」：`spec.md:83`（§4 数据流表）写明「容器 **CRUD** / 启停 / 删除」——Create 属 CRUD。
- 支持「超范围」：`scope.md:24`（F1 明细）只列「列表/详情/启停/重启/暂停/删除/筛选」，**无创建**；`spec.md:130` 把「容器参数细节查看/启动配置编辑」归 **v1.1**；`plan.md:T3` 的 Interfaces 清单无创建端点。

三条依据互相冲突，故不构成「可引用依据一致」的硬违规。补充事实：该功能由用户主动要求（`README.md:29` 记录 R4 触发原因），依 ETHOS #3「用户主权」，**不应回滚**，正确处置是回写 `spec.md` §4/§7 与 `scope.md` F1，把「从镜像运行容器」正式纳入 v1 范围。

### 分歧裁决 3：拷出路径与 spec D4 的偏差

R1 报「`copy_out` 偏离 D4 中转设计」，R3 报「D4 临时目录策略**符合**」。**两者不矛盾、均成立**：R3 核查的是 D4 的**生命周期规则**（启动清空 `app/main.py:15-18`、拷入成功即删 `files.py:25`），全部落实；R1 指的是 **D4 字面流程**（「`get_archive()` → 后端临时 → 前端下载」）在拷出路径上根本没有临时文件——实现是容器→响应流直连。该直连更贴合 `spec.md:57`（D6 流式）与 `spec.md:112`（大文件内存对策），且 `plan.md` 的参考实现本身就是直连。**裁决：记为文档漂移（🟢），非缺陷**，建议回写 `spec.md:44/73` 的 D4 描述。

### 分歧裁决 4：安全合规的层次差异

R3 核查 `spec.md:111` 的硬性对策（绑定 `127.0.0.1:8088`、禁止后端暴露 0.0.0.0）→ **全部落实，判合规**；R1 报「跨站 WS 劫持 + 无 CSRF」→ 属实。**裁决：两者层次不同、均保留**——前者是对照 spec 明文要求（合规），后者是 spec 未覆盖但后果极重的安全判断（Docker socket = 宿主 root），保留 🟡 JUDGEMENT CALL。

---

## 协调者独立复核证据（不采信子代理结论）

下列结论为协调者**亲自跑出**的证据，与子代理报告一致：

| 复核项 | 我执行的命令 / 读取 | 结果 |
|--------|-------------------|------|
| 🔴 卷创建界面必失败 | `POST /api/volumes {"name":"coord-dryrun"}`（前端真实形状） | **422** `{"type":"string_type","loc":["body"],"msg":"Input should be a valid string"}` |
| 同上，证明「非 embed」（决定性实验） | `POST /api/volumes '"coord-probe-tmp"'`（裸 JSON 字符串） | **200** → 证明后端 `Body(...)` 非 embed；探针卷已 DELETE |
| 同上，对照组 | `POST /api/networks {"name":…,"driver":…}` | **200** → networks 双 Body 参数自动 embed，前端形状正确，只有 volumes 断 |
| nginx 丢端口 | `GET /api/containers/`（禁止自动重定向） | **307** `Location: http://127.0.0.1/api/containers` —— `:8088` 被 `proxy_set_header Host $host`（`frontend/nginx.conf:32,43`）吃掉，指向未监听的 80 |
| 导出丢 tag | docker-py 7.2.0 `inspect.signature(Image.save)` + docstring | `(self, chunk_size=2097152, named=False)`；*"If False (default), the tarball will not retain repository and tag information"* → `images.py:99` 的 `img.save()` 不带 `named=True` |
| 无 Origin/CSRF 防护 | `git grep -ni "origin\|csrf\|cors" -- backend/app` | **零命中** |
| WS 无节流/背压 | `git grep -n "throttle\|Queue(\|sleep" -- backend/app/routers/ws.py` | **零命中** |
| 停止容器看不了日志 | 读 `ws.py:15-20` | `_find_container` 只遍历 `containers.list()`（默认 `all=False` = 仅 running），docstring 自述 "first **running** container" |
| 构建上下文体积 | `frontend/` 全量文件求和 | **118.2 MB**（与 R2 实测一致；无任何 `.dockerignore`） |
| E2E 无法当门禁 | `git grep -n "sys.exit" -- scripts` | 只有 `ui_verify.py:157`、`ui_clipboard_test.py:144`；`e2e_verify.py` 的 `main()`（:351）以 `:396 main()` 结尾，**无退出码** |
| `ui_verify` 判定面 | 读 `ui_verify.py:146-153` | 控制台错误/失败请求仅 `print`，`return 1 if page_errors else 0` |
| 超时策略矛盾 | 读 `api/index.ts:51,55,73` | 全局 `timeout: 30000`；`NO_TIMEOUT` 仅用于 `pull`（:73），create/commit 受 30s 约束 |
| `.env` 覆盖面 | 读 `deploy/docker-compose.yml:8-14` | 仅 `IMAGE_MIRRORS` 用 `${…:-…}`，`DOCKER_HOST`/`PORT`/`TMP_DIR` 硬编码 |
| `backend/a.txt` 误提交 | `git ls-files` + 读 `test_files_api.py:26-28` | 被跟踪，2 字节内容 `hi`；测试把 `get_tmp_dir` 指到 `Path(".")` 且写在 `try` 之外，每次跑测试都落盘 |
| `test_ws_logs` 恒通过 | 读 `test_ws_logs.py:22-29` | `assert` 在 `try` 内 + `except Exception: pass` → 断言失败自身被吞，恒真 |
| uv.lock 事实 | `git ls-files backend/uv.lock` / `git log --diff-filter=A` | 已跟踪（183,446 B）；首次入库 = **`8149029`**（即修 `.gitignore` 的同一 commit）→ R1 自述的「待修复」已过期 |
| 编码/乱码假象排除 | `docs/plans/…-plan.md` 首字节 | `E7 AE A1` = 合法 UTF-8（无 BOM）→ 控制台显示乱码**不是**文件缺陷，不予记录 |

**审查副作用披露（已复原）**：协调者探针创建并删除了卷 `coord-probe-tmp`、网络 `coord-net-dryrun`；复核后卷总数为 **8**，无 `*probe*/*dryrun*/*review*` 残留。R3 报告披露其探针创建并删除了空卷 `dm-review-probe-dryrun`，同样已复原。除上述外未创建/删除任何容器或镜像；未修改任何被测代码（`git status` 仅新增 `test-review/` 与 `ocr/` 文档目录）。

---

## 发现清单

### 🔴 Critical（1）

| ID | 位置 | 描述 | 性质 | 依据 |
|:--:|------|------|:--:|------|
| C-01 | `backend/app/routers/volumes.py:24` ↔ `frontend/src/api/index.ts:86`、`views/VolumesView.vue:127` | **「创建数据卷」在界面上必然失败**：后端 `def create_volume(name: str = Body(...))` 是单标量 Body 且未 `embed=True`，要求请求体是**裸 JSON 字符串**；前端发的是 `{"name": …}` 对象 → 实测 **422**。用户点「创建卷」只会看到一个校验错误，功能 100% 不可用。同族 `networks.py:25` 有两个 Body 参数故自动 embed，前端跟了 networks 的形状，**只有卷这一条断**（已用对照实验证明）。修法：`name: str = Body(..., embed=True)`，或把前端改为发裸字符串（推荐前者，与 networks 一致） | **HARD** | `scope.md:28`（F5 含「创建」）、`plan.md:T5` |

### 🟡 Important（20，去重后；原写 21 与本节表内 20 条不符，已按 R-L2 更正）

| ID | 位置 | 描述 | 性质 | 依据 | 命中透镜 |
|:--:|------|------|:--:|------|:--:|
| C-02 | `routers/ws.py:88-101`、`components/ContainerLogs.vue:103-108`、`ContainerTerminal.vue:209-216` | `spec.md` §6 风险对策要求「**消息节流、断线重连、防抖**」，实现**三条全部缺失**：后端每行日志一个 `ensure_future` 无背压；前端只有手动「重连」按钮，无自动重连/退避/节流（日志批量下发只做了「截断」） | **HARD** | `spec.md:113` | R1+R2+R3 |
| C-03 | `frontend/nginx.conf:32,43` | `proxy_set_header Host $host` **丢掉端口**：实测所有尾斜杠请求返回 `307 Location: http://127.0.0.1/api/…`（指向未监听的 80）→ 任何触发 FastAPI 尾斜杠规范化的路径在浏览器里都会 404/连接失败。应改用 `$http_host` | JUDGEMENT | 实测 307 | R3 |
| C-04 | `backend/app/routers/files.py:16-29` | `async def copy_into` 内做**同步阻塞 I/O**：`local.write_bytes()`（:19）、`tarfile` 打包（:21-23）、`put_archive()`（:24，阻塞至整个 tar 上传完成）。期间 uvicorn 唯一事件循环被冻结，**所有** HTTP + WS 一起卡死（与 R1 历史事故同机制，区别是「有界」）。上传 1GB（nginx `client_max_body_size 0`）可冻结数十秒～数分钟。修法：`await asyncio.to_thread(...)` 包住，或改回同步 `def`（FastAPI 自动走线程池） | **HARD** | `routers/ws.py:59-68`（项目自身写下的异步规则）、`spec.md:113` | R1 |
| C-05 | `views/ContainersView.vue:63-100,245-253`、`api/index.ts:63-64` | **暂停/恢复零 UI 入口**：后端 `containers.py:189-201` 已实现、前端 API 层已封装，但没有任何组件调用（`git grep` 全仓无调用点）→ 功能实际不可达 | **HARD** | `scope.md:24`（F1 含「暂停」）、`plan.md:206` | R2+R3 |
| C-06 | `routers/ws.py:15-20`、`components/ContainerLogs.vue:95` | **停止/退出的容器看不了日志**：`_find_container` 只遍历运行中容器（`containers.list()` 默认 `all=False`），而「最需要看历史日志」的正是刚崩掉的容器 | **HARD** | `scope.md:25`（F2「实时 + **历史**」） | R2 |
| C-07 | `routers/images.py:95-101` | 导出 tar **丢失镜像名与 tag**：`img.save()` 未传 `named=True`（docker-py 默认 `named=False`，docstring 明示不保留 repository/tag）→ 异机 `docker load` 得到 `<none>:<none>`，F7「导出归档」意图落空。本机 Docker 的镜像 ID 恰等于 digest，因此在开发机上发现不了（与 epic README「经验记录 2」同型的巧合正确） | JUDGEMENT | `scope.md:30` F7、`spec.md:90` | R1 |
| C-08 | `routers/ws.py:127-231`（`/ws/exec`）、`containers.py:162-204` 等写操作 | **跨站 WebSocket 劫持 + 无 CSRF 防护**：全仓 `backend/app` 无任何 `Origin` 校验/CSRF 令牌，WS 握手不受同源策略保护 → 用户只要访问一个恶意页面，该页面即可连上 `ws://127.0.0.1:8088/ws/exec` 拿到容器 shell，再 exec 进挂了 `docker.sock` 的 backend 容器 = **宿主机 root**。spec §6 的「绑定 127.0.0.1」对策**挡不住浏览器作为中介**（请求确实来自 127.0.0.1） | JUDGEMENT | `spec.md:111`（对策不足）、`spec.md:36`（socket 全权限） | R1 |
| C-09 | `deploy/docker-compose.yml:8-14` vs `docs/deployment.md:80-94`、`README.md:71-78`、`.env.example:3-6` | **文档承诺 4 个变量可经 `.env` 覆盖，实际只有 `IMAGE_MIRRORS` 一个生效**（其余三个在 compose 里硬编码），用户照文档改 `.env` 完全无效且无任何提示 | **HARD** | `docs/deployment.md:80-94`、`README.md:71-78` | R2+R3 |
| C-10 | `scripts/e2e_verify.py:351,395-396` | **E2E 永远返回 0**：`main()` 只 `print`，从不 `sys.exit(非零)` → 失败也无法当门禁接入（对比 `ui_verify.py:157`、`ui_clipboard_test.py:144` 写法正确） | **HARD** | `plan.md:1067-1072`（验证闭环意图） | R2 |
| C-11 | `scripts/e2e_verify.py:210-217,189-201,321-323` | **断言可假阳性**：WS 日志项只要收到**任意 str 帧**即 PASS，而「找不到容器」发的正是文本帧 → **链路全断也 PASS**；`test_image_remove` 无条件记 `True`；`if info.get("ports"): record(...)` 条件断言导致「18 项」可静默变成 17 项（本机残留镜像 `dockermgr-e2e:0476b11a` 即旁证） | JUDGEMENT | 同上 | R2+R3 |
| C-12 | `scripts/ui_verify.py:146-153` | **UI 校验脚本判定面过窄**：`return 1 if page_errors else 0` —— 控制台错误、失败请求、端口断行只 `print` 不判定，「0 控制台错误 / 0 失败请求」的结论完全靠人眼看输出 | JUDGEMENT | 同上 | R2 |
| C-13 | `backend/tests/test_files_api.py:26-28` + `services/files.py:18-19,25` + `backend/a.txt` | **测试污染仓库并已误提交**：mock 把 `get_tmp_dir` 指到 `Path(".")`，写盘又在 `try` 之外 → 每次跑测试都在 `backend/` 落一个 `a.txt`；该文件已被 `e4f5fff` 提交进库（2 字节，内容 `hi` 与测试上传体一致）。应改用 pytest `tmp_path`，并 `git rm backend/a.txt` | **HARD** | 实测 `git ls-files` | R1+R3 |
| C-14 | `backend/tests/test_ws_logs.py:22-29` | **恒通过的假绿用例**：`assert` 位于 `try` 内 + `except Exception: pass` → 断言失败抛的 `AssertionError` 被同一 `except` 吞掉，用例只证明「路由可达」 | **HARD** | `plan.md:T7`（验证要求） | R3（协调者升级，R1 记 🟢） |
| C-15 | `backend/tests/`（全目录） | **14 个端点零单测**，含 F6（commit 打包）、F7（save 流式导出）、F10（拷出）三条主线能力；plan 各 Task 只要求「路由存在」级测试，故非硬违规，但交付前风险敞口明确 | JUDGEMENT | `plan.md:T3-T6`（验证要求偏弱） | R1 |
| C-16 | `frontend/Dockerfile:5-6`（全仓无 `.dockerignore`） | `COPY . .` 排在 `npm ci` 之后，且无 `.dockerignore` → 把**宿主的 Windows 版 `node_modules`（116.1 MB）+ `dist/`** 覆盖进 Linux 镜像；构建上下文实测 **118.2 MB**，构建慢且不可复现（与 README 自述的可复现构建目标冲突） | JUDGEMENT | `spec.md:60`（D7 复现精神） | R2+R3 |
| C-17 | `components/FileCopyDrawer.vue:109-119`、`views/ImagesView.vue:170-176` | **假成功反馈**：拷出与镜像导出走裸 `<a href>`，没有失败通道——路径不存在或后端 500 时，界面仍提示「已开始下载/导出」，用户拿到的是错误页或空文件 | JUDGEMENT | — | R2 |
| C-18 | `api/index.ts:51,59,66` vs `scripts/e2e_verify.py:156,308` | **超时策略内部矛盾**：全局 30s，`NO_TIMEOUT` 只给 pull；而 E2E 给同一批调用 120s/180s → 真机上「创建容器/commit 大镜像」超过 30s 会在前端显示失败而后端仍在跑，重试还会撞 409（create 不幂等） | JUDGEMENT | — | R2 |
| C-19 | `routers/ws.py:75,152,220-229` ↔ `components/ContainerLogs.vue:100-102`、`ContainerTerminal.vue:209-213` | **错误帧语义缺陷**：① 后端 `{"error":"no container"}` 文本帧被前端当**日志行**渲染，界面出现一行裸 JSON，随后只显示「已断开」，没有任何可读原因；② `/ws/exec` 找不到容器时**静默以 1000(OK) 关闭、零帧**，用户无法区分「容器不存在」与「shell 正常退出」 | JUDGEMENT | — | R2+R3 |
| C-20 | `scripts/ui_verify.py:7`、`ui_clipboard_test.py:9,31,47`、`.gitignore:42`、`e2e_verify.py:206,252` | **验证脚本不可移植**：playwright 在 `frontend/package.json` 与 `backend/pyproject.toml` **均未声明**（本机靠 `.browser-tools` venv，而该目录被 `.gitignore` 忽略）；`websockets` 只是 `uvicorn[standard]` 的传递依赖，换解释器即静默 FAIL；脚本还隐含要求「有头浏览器 + 存在 running 容器 + 本机已有镜像」 | JUDGEMENT | `spec.md:117`（假设现代浏览器等前提应写明） | R2 |
| C-21 | `components/RunContainerDialog.vue`、`routers/containers.py:102-151`、`services/run_spec.py`、`api/index.ts:59` | **范围蔓延（待回写文档）**：整条「从镜像运行容器」链路（自由文本解析器 161 行 + `POST /api/containers` + 运行对话框 342 行 + 5 个预设）在 `plan.md` T1–T12 中**无对应任务**。裁决理由见上文「分歧裁决 2」：`spec.md:83`（CRUD）与 `spec.md:130`/`scope.md:24` 互相冲突，且该功能由用户主动要求 → 不回滚，**回写 `spec.md` §4/§7 与 `scope.md` F1** | JUDGEMENT | `spec.md:83` vs `spec.md:130`、`scope.md:24`、`plan.md:T3` | R1+R2+R3 |

### 🟢 Minor（约 31，去重后；完整明细见 `rd1/` 三份透镜报告）

高频/值得优先处理的几类：

| 位置 | 描述 | 命中透镜 |
|------|------|:--:|
| `docs/epics/docker-manager-v1/README.md:74` | **C-22** 「未完成项」仍写 `.gitignore` 忽略 `uv.lock` = **待修复**，但该问题在**同一 commit `8149029`** 已修（`.gitignore:5-8` 改为「刻意提交」注释 + `backend/uv.lock` 887 行入库）→ 看板自相矛盾。另 `README.md:21` 写「4 轮修复」而下表实为 R1–R5 五轮（**本次审查已在 README 中改正这两处**） | R1+R2+R3+协调者 |
| `backend/Dockerfile:2,8-12` | 基镜像 `ghcr.io/astral-sh/uv:latest` **未固定版本**（依赖锁住了、构建工具没锁，供应链风险）；`COPY app ./app`（:9）排在 `RUN uv sync`（:12）之前 → **任何源码改动都让依赖层缓存失效**，重建即重装全部依赖 | R1 |
| `views/SettingsView.vue`（不存在） | `plan.md:810` 文件清单要求创建占位页，实际未创建、无 `/settings` 路由（无功能影响） | R2+R3 |
| `services/docker.py:18-37`、`images.py:76-84` | Task 2 声明的 4 个数据类型有 3 个（`ImageInfo`/`NetworkInfo`/`VolumeInfo`）**零引用死代码**；连带 `README.md:26` 声称镜像列表含「大小、创建时间」不成立（接口只返回 id/tags/digest/short_id） | R2+R3 |
| `scope.md:27,28` vs 实现 | 网络/卷「详情」、卷「使用情况」未实现（plan T5 的 Interfaces 亦只列 list/create/delete → **计划本身欠范围**，不能只记在执行侧） | R1+R2+R3 |
| `docs/development.md:158`、`troubleshooting.md:168` | 文档写 `run_coroutine_threadsafe`，代码实际是 `call_soon_threadsafe`（`ws.py:34`）—— 排障文档里最该准确的一处 | R3 |
| `frontend/vite.config.ts` + `tsconfig.node.json` | `vue-tsc -b` 会把 `vite.config.ts` 编译出 `vite.config.js` 落在源码目录，而 Vite 配置查找 **`.js` 优先于 `.ts`** → 改完 `.ts` 直接 `npm run dev`（README 推荐命令）读到旧副本，表现为「改动没生效」（`.gitignore:19-21` 说明作者已知产物但未解决遮蔽） | R2 |
| `utils/error.ts` vs `ContainersView/NetworksView/VolumesView` | 错误提示三处重复实现（只有 `ImagesView`/`RunContainerDialog` 用了 `showApiError`），与 `docs/development.md:83` 的自定约定相悖 | R2 |
| `main.ts:11-13` | 全局注册全部 Element Plus 图标 → 主 chunk 1.26 MB（实测未压缩） | R2 |
| `routers/containers.py:82-88` | `state` 与 `status` 恒等（docker-py 的 `status` 定义就是 `attrs["State"]["Status"]`），且一旦改用 `sparse=True` 形状会 `AttributeError` → 整个列表 500；`containers.py:94-99` 每次列表刷新还有 2N+1 次 daemon 往返 | R1 |
| `frontend/nginx.conf:22` + `files.py:19` | 上传无任何上限（`client_max_body_size 0` + 全量读进内存 + compose 无内存限制），且同一份数据在内存里存在 3 份 | R1+R2 |
| `deploy/docker-compose.yml` | 无 `restart:`、无 `healthcheck`、无 `logging:` 轮转；`clear_tmp_dir()` 只删文件不删子目录 | R1+R2+R3 |
| `frontend/index.html:5` | `/favicon.ico` 不存在，被 `try_files` 静默回退成 `200 text/html`（444 字节 index.html） | R2 |
| `docs/deployment.md:194-198` | 指导用户 `docker load -i`，与 `spec.md:16`「不依赖命令行」原则相左（未在界面实现导入，属文档措辞擦边） | R3 |
| `1b1e5cb`…`50e904d` | **提交节奏未遵守**：`plan.md:1076` 要求「Task 内部按 TDD 红→绿增量提交」，实测 12 个 Task commit 各只有一次提交（测试与实现同批入库），TDD 的「红」阶段在历史上不可考 | R3 |
| `services/docker.py:47` | `docker.from_env()` 先行使 `config.py` 的 `docker_host` 成为近乎不可达的死配置 | R1+R3 |

**正向确认（三路一致，非发现）**：

- `spec.md:111` 的硬性安全对策**全部落实**：`docker-compose.yml:23-25` 绑 `127.0.0.1:8088:80`、后端仅 `expose` 不 publish、安全提示在 `README.md:254`/`deployment.md:135-152`/`troubleshooting.md:241-245` 三处齐备。
- **无持久化零违反**（无 DB/ORM/状态文件，compose 无数据卷）；D4 临时目录生命周期（启动清空 + 拷入成功即删）落实。
- **D6 是真流式（量化实测）**：`GET /api/images/{id}/save` → `transfer-encoding: chunked`、无 `content-length`、TTFB 0.120s。
- **mock 形状核验结论：正确**。逐条对照 docker-py 7.2.0 源码：`Container` 确实**没有** `.state`（只有 `status`）、`ports` 是 dict、`image.tags` 是 list、`SocketIO` 无 `settimeout`；mock 用 dict 形状的 `attrs["State"]` 也是对的（`containers.list()` 默认 `sparse=False`）。**唯一缺口**：无用例覆盖 `sparse=True` 形状。
- **R1–R5 五轮缺陷修复逐条复核：修复本身均正确**（`.state`→`attrs["State"]["Status"]`、`stdin=True` 必需、`exec_resize(height=rows,width=cols)` 与 docker-py 签名一致、镜像源降级仅在注册表不可达时触发且成功后回打原名、终端按键接管不产生重复粘贴）。唯一同类残留是 C-04。
- **契约对账**：25 HTTP + 2 WS 端点与前端调用**逐项对齐**（路径/方法/`/api` 前缀/尾斜杠/参数名/字段名），唯一断裂是 C-01 的 Body 形状；线上运行产物已证明就是 HEAD 构建（线上 `/assets/index-BGeOqOmG.js` 与本地 `dist/` 同名且含 HEAD 独有串）。

---

## Task 1–12 对齐矩阵（R3 透镜，协调者复核）

| Task | 判定 | 缺口 |
|------|:--:|------|
| T1 后端骨架与配置 | ✅ | — |
| T2 Docker 客户端封装 | ⚠️ | 4 个数据类型 3 个零引用；`docker_host` 死配置 |
| T3 容器 API | ✅ | — |
| T4 镜像 API | ✅ | — |
| T5 网络与卷 API | ⚠️ | **卷创建界面必失败（C-01 🔴）**；网络/卷「详情」「使用情况」缺（计划自身欠范围） |
| T6 文件双向拷贝 API | ✅ | — |
| T7 WebSocket 实时日志 | ⚠️ | 验证测试被 `except: pass` 吞成恒通过（C-14） |
| T8 WebSocket 交互终端 | ✅ | — |
| T9 前端骨架 + 路由 + API 层 | ⚠️ | `SettingsView.vue` 未创建 |
| T10 容器列表页 + 操作 + 详情 | ⚠️ | 暂停/恢复零入口（C-05）；容器详情接口无前端入口 |
| T11 镜像/网络/卷视图 | ⚠️ | 计划预审已记 Fail（三视图粒度）；卷创建不可用（C-01） |
| T12 容器化部署 | ⚠️ | 缺 `.dockerignore`（C-16）；`.env` 覆盖面与文档不符（C-09）；`uv:latest` 未固定 |
| 「验证闭环」节 | ⚠️ | F1/F3/F4/F5/F11 有缺口；E2E 无法当门禁（C-10/11） |
| 「提交节奏」节 | ⚠️ | TDD 红→绿增量提交未发生 |

---

## 亮点

- **WS 阻塞修复是本 diff 里质量最高的一处**：docker-py 的 `logs(follow=True)` 阻塞生成器被转移到工作线程 + `call_soon_threadsafe` 回推 + 0.5s 可断连 `receive`，并用 30 行注释把「为什么不能直接在 async 里迭代」写在代码里——这是把踩过的坑变成了团队资产。
- **三处资源清理成对且无死角**（xterm/WS/定时器/监听器 + `disposed` 兜住异步尾部 + 抽屉动画期 `clientWidth=0` 防护）。
- **前端类型纪律好**：全仓仅 1 处 `any`（官方 shim），`vue-tsc -b --force` 实测退出码 0。
- **镜像导出选直链而非 blob**（`<a href>`），前端零内存占用，与 D6 流式意图一致；实测 chunked + TTFB 0.12s。
- **`IMAGE_MIRRORS` 三层默认值兜底**（config → compose → `.env`），且降级只在注册表不可达时触发、成功后回打官方名。
- **排障文档六条坑均能在代码中找到对应修改**（`.state`、事件循环、`stdin`、resize、镜像源、剪贴板）。

---

## 未能独立验证（诚实标注）

1. **E2E 18/18 与「浏览器 0 错误」未获独立验证**：`e2e_verify.py` 会真实增删容器/镜像；Playwright 子进程被沙箱以 `PermissionError [WinError 5]` 拒绝（会话审批禁用，未升级重试）；`vite build` 因 esbuild `spawn EPERM` 未跑完。**但 `66 passed` 已由 R1 与 R3 各自独立实测复现**（`uv run --frozen pytest -q` → 66 passed）。
2. **容器内 nginx.conf 未能逐字比对**（`docker exec` 被 docker npipe 权限拒绝）：3600s 超时与 `client_max_body_size 0` 仅有间接证据（`/api`、`/ws`、SPA 回退、静态 MIME 实测正常）。
3. **`docker build` 与全新 clone 构建未能实跑**（沙箱限制）→ C-16 的「不可复现」是静态分析结论，非实测复现。
4. 停止容器看日志的表现按两侧代码推定（本机无非 running 容器可测）。

---

## 建议修复顺序

1. **C-01（🔴，一行）** `volumes.py:24` 加 `embed=True` —— 唯一一个「功能直接不可用」的缺陷。
2. **C-04 + C-08（一行 + 少量）** `copy_into` 改 `asyncio.to_thread`；`/ws/*` 与写操作加 Origin 校验 —— 成本最低、后果最重的两项（事件循环冻结 / 宿主机 root 暴露）。
3. **C-13 + C-14（测试假绿）** `test_files_api` 改 `tmp_path` 并 `git rm backend/a.txt`；`test_ws_logs` 把 `assert` 移出 `try`。
4. **C-02 + C-07 + C-03（各一行）** WS 节流/自动重连；`img.save(named=True)`；nginx 改 `$http_host`。
5. **C-05 + C-06 + C-09** 补暂停/恢复入口、停止容器日志、修 `.env` 文档与实现的落差。
6. **C-10 + C-11 + C-12** 让验证脚本真正能当门禁（退出码 + 强断言）。
7. **文档回写一批**：C-21（spec §4/§7 + scope F1）、D4 拷出描述、spec §5 二服务、`README.md:74`「未完成项」、`README.md:21` 轮次计数、`development.md:158` 的 `run_coroutine_threadsafe`。

> 修复后需 **re-review**（同一模板，BASE 不变、HEAD 更新到修复 commit），确认 🔴/🟡 全部关闭后方可进 Phase 5 测试。

---
---

# 第二轮：修复 + 重审（2026-09-11）

> 修复批次 = **工作区未提交改动**（基线 `8149029`）：28 个已跟踪文件 + 12 个新文件（+1180/−180）。
> 重审方式：**同一模板、三路隔离重审**，报告见 `test-review/rd2/review-backend.md` · `review-frontend-deploy.md` · `review-plan-alignment.md`（前端+部署透镜另附 8 个可复跑探针在 `rd2/evidence/`）。
> 修复纪律：按 `sp-receiving-code-review` 执行——**先核实再实现**，不表演式认同；阻塞项 → 简单项 → 复杂项；每条以「能失败的验证」收尾，不接受注释与自述当证据。

## 2.1 修复内容

| 组 | 修复 |
|---|---|
| 后端 | **C-01** `volumes.py:24` 加 `embed=True`；**C-02** `ws.py` 批量 flush（100ms 计时线程 + 2000 行有界丢旧）；**C-04** `files.py` 写盘/打包/推送三步整体进 `asyncio.to_thread` + `finally` 清理；**C-06** `_find_container` 两轮 `list(all=False/True)`；**C-07** `images.py:103` `named=True`；**C-08** 新增 `services/security.py` + `main.py` 跨站中间件 + 两个 WS 守卫（`accept()` 之前）；**C-19** 两端点先发文本帧 `{"error": …}` 再关；`clear_tmp_dir` 同时清目录 |
| 后端测试 | **C-13** `test_files_api` 改用工作区外临时目录 + `git rm backend/a.txt`；**C-14** 断言移出 `try/except`；**C-15** 新增 `test_endpoints_coverage.py`（14 例）+ `test_security.py`（22 例，含 `Origin: null` 与前缀仿冒）；`test_ws_logs_blocking` 的 mock 补上真实签名 `list(all=…)` |
| 前端 | **C-05** 暂停/恢复入口（running→暂停 / paused→恢复）；**C-02** 日志 100ms 批量渲染 + 5000 行有界缓冲（丢最旧并提示）+ 指数退避自动重连；终端 16ms 合并写 xterm；**C-17** 下载预检 + 真实失败通道；**C-18** `LONG_OP_TIMEOUT`(300s) 用于 `create`/`commit`；新增 `utils/ws.ts`、`utils/download.ts` |
| 部署 | **C-03** nginx `proxy_set_header Host $http_host`（`/api`、`/ws` 两处）；**C-09** compose 四变量 `${VAR:-default}`；**C-16** 新增 `frontend/.dockerignore`、`backend/.dockerignore` |
| 脚本 | **C-10** `sys.exit(main())` + `EXPECTED_CHECKS=18`（少一项即失败）；**C-11** 控制帧判 FAIL、必须收到真实日志行、端口断言无条件、删除后重新列表复核；**C-12** 五类判定共同决定退出码；**C-20** 新增 `scripts/requirements-verify.txt` + 缺依赖中文提示 |
| 文档 | **C-21** `scope.md` 补 F12（带日期与来历）+ `spec.md` §4/§7 澄清；**D5** `call_soon_threadsafe`、镜像列表字段、compose v1 表述；epic README 轮次计数 |

## 2.2 修复批次自证证据（本轮实测，非自述）

| 证据 | 结果 |
|---|---|
| `uv run --frozen pytest -q` | **105 passed**（修复前 66） |
| `vue-tsc -b --force` | **exit 0**（协调者独立复跑；前端透镜另用「塞入类型错误 → exit 2」反证过该 0 非空跑） |
| `py_compile` 三个验证脚本 | **exit 0** |
| 变异：去掉 `embed=True` | 契约用例 **FAILED**（`422 == 200`） |
| 变异：把 `"no container"` 改错 | 断言用例 **FAILED**（证明 C-14 的断言真的会失败） |
| 变异：删掉日志计时线程 | **17 passed（存活）** ← 这正是 rd2 的 **N-01**：批处理回归测试当时是同义反复 |
| 真机 `scripts/e2e_verify.py` | **18/18 passed，EXITCODE=0**（`收到 20 行真实日志（20 帧）`、`端口 61081->80/tcp`、`tag gone`） |
| `docker compose --env-file` 实测 | `IMAGE_MIRRORS` 未设→默认源；**设为空→保持空**（文档承诺的「留空关闭降级」）；设值→生效 |
| 探针：600 行日志 | **19 帧**（非 600）→ 节流机制真实生效 |

## 2.3 重审关闭判定（19/21 关闭）

| 编号 | 判定 | 决定性证据（摘要） |
|---|---|---|
| C-01 🔴 | ✅ CLOSED（源码） | `embed=True` 在位；变异体杀死契约用例 |
| C-02 🟡 | ✅ CLOSED（机制）／测试无牙 → N-01 | 探针 600 行 → 19 帧；尾部不丢 |
| C-03 🟡 | ✅ CLOSED | 两处都改；旧行为实测复现（307 → `http://127.0.0.1/api/containers` → 80 端口 `000`）；`proxy_redirect` 经核实不需要 |
| C-04 🟡 | ✅ CLOSED | 三步阻塞整体进线程；成功/失败双路径清理均有断言 |
| C-05 ⚪ | ✅ CLOSED | 按钮→api→后端链路完整，无死按钮，有成功/失败反馈 |
| C-06 🟡 | ✅ CLOSED | 两轮 list、running 优先；测试断言 `[False, True]`；变异杀死 |
| C-07 🟡 | ✅ CLOSED | 读 docker-py 7.2.0 源码确认 `named=True → tags[0]`；变异杀死 |
| C-08 🟡 | ✅ CLOSED | 真 uvicorn + 真客户端：`evil.example`/`null`/`127.0.0.1.evil.example` → **403**；守卫确在 `accept()` 前；3 个变异体全杀 |
| C-09 🟡 | ✅ CLOSED（余 1 项 → N-08） | 四变量与文档逐项一致；`docker compose config` 实测 `.env` 生效（根目录 `.env` 被忽略、`deploy/.env` 生效） |
| C-10 🟡 | ✅ CLOSED | `sys.exit(main())` + 三种失败条件；反证实验（BASE 指死端口）→ **0/6、退出码 1** |
| C-11 🟡 | ✅ CLOSED | 控制帧 FAIL / 必须有真实日志行 / 端口无条件 / 删除后复核；探针逐项验证 |
| C-12 🟡 | ✅ CLOSED（余 3 → L-07/L-08/L-14） | 五类判定入退出码；端口断行真入判（原「收集了却不用」已修） |
| C-13 🟡 | ✅ CLOSED | `a.txt` 已 `git rm`（`D backend/a.txt`）、磁盘无残留；跑测 3 次仓库树干净 |
| C-14 🟡 | ✅ CLOSED | 断言在 `try` 之外；变异杀死 |
| C-15 🟡 | ⚠️ PARTIAL | 66→105 passed，F6/F7/F10 主线已覆盖；余 ~9 端点（第二轮补） |
| C-17 🟡 | ⚠️ PARTIAL → 见 N-02/N-05 | 两类 500 **实测**被预检拦住、失败确不提示成功；但预检无超时 → 第二轮修 |
| C-18 ⚪ | ✅ CLOSED | 300s ≥ E2E 的 180s/120s；`NO_TIMEOUT` 仅 pull 一处 |
| C-19 🟡 | ✅ CLOSED | 两端点先发文本帧；前端严格校验整帧；E2E 同步识别 |
| C-20 🟡 | ✅ CLOSED | 依赖文件 + 三脚本中文提示 + `sys.exit(2)` |
| C-21 🟡 | ✅ CLOSED | F12 + §4/§7 澄清 + 轮次计数；跨层契约① ② 四层对齐 |
| C-22 🟢 | ⚠️ PARTIAL | `uv.lock` 与「5 轮」已改对；`:77` 仍「待修复」、`:102` 仍「66 passed」（实测 105）→ L-03 |
| C-16 ⚪ | ✅ CLOSED | 构建上下文 **118.2 MB → 0.2 MB**（后端 45.4 → 0.215），逐文件核对零误排除 |

> ⚪ = 上一轮未编号或按 🟢 记录的条目。**段间不抵消**：后端透镜自身仍判 NEEDS FIXES（差在「修好了但证明不了」）。

## 2.4 重审新发现（27 条，其中 5 条 HARD；**2 条由修复批次自己引入**）

| 编号 | 级别 | 位置 | 问题 | 处置 |
|---|:--:|---|---|---|
| **N-01**(后端) | 🟡 HARD | `tests/test_ws_logs.py:74-91` | 批处理回归测试**同义反复**：mock 流立刻结束，断言由收尾 flush 满足；删掉计时线程仍全绿 → C-02 核心机制无保护 | 第二轮：改长命流 + 断言帧数远小于行数 + 变异验证 |
| **N-07**(后端) | 🟡 HARD | 线上栈 | **修复未部署**：实测对象体 422 / 裸字符串 200 / 外部 Origin 422(非 403) ⇒ pre-fix 构建，**C-01 对用户仍是活的** | 用户已批准 `compose up -d --build` 并复跑验证 |
| **N-02**(前端) | 🟡 HARD | `utils/download.ts:30-43` | 下载预检无超时、无 `AbortController` → 后端卡住时按钮**永久 loading** | 第二轮：加超时 + 取消 + `finally` 清 loading |
| **N-08**(部署) | 🟡 HARD | `docker-compose.yml:16` | `${IMAGE_MIRRORS:-…}` 的 `:-` 把**空值当未设置** → 文档承诺的「留空关闭降级」实测失效 | **已修**（改 `${IMAGE_MIRRORS-…}`）+ 已实测三态 |
| **L-10** | 🟡 HARD | `security.py` ↔ `deployment.md:152` | 新跨站守卫与文档推荐的「前置认证反代」冲突：反代改写 Host 时 → 写操作全 403、WS 全 1008，文档零提示 | **已修**：`deployment.md` 补「必须保留 Host」+ nginx/Apache 样例 |
| **L-06** | 🟡 | `utils/ws.ts` + `ws.py` + `e2e_verify.py` | 错误帧无判别字段 → 容器打印单行 `{"error":…}` 结构化日志会被当协议帧吞掉（E2E 同误判） | 第二轮：改带判别字段 `{"dockermgr":"error",…}`，三层同步（契约由协调者冻结） |
| N-01(前端) | 🟡 | `ContainerLogs/Terminal.vue` | 退避成功后**不复位** → 一次抖动把重连延迟永久钉在 30s | 第二轮修 |
| N-03(前端) | 🟡 | `ContainersView.vue:109-119` | paused 容器仍可「进入终端」→ Docker `exec_create` 对冻结容器**永久阻塞**（暂停功能带出的新路径） | 第二轮修 |
| L-03 | 🟡 | epic README `:77`/`:102` | 看板自述未随批次同步（C-22 同型复发） | 协调者随修复同批更新 |
| L-02 | 🟡 | `deployment.md:34` | 新表述把「v1 也能跑本文件」这个**未经证实**的兼容性断言写进了产品文档（文件无 `version:`，官方规则下 v1 语义不同） | **已修**：改为「v1 已 EOL，未做兼容性验证，一律以 v2 为准」 |
| L-07 | 🟡 | `ui_verify.py:202-216` | 新加的 5 个语义判定打印 FAIL 但**不进退出码** | 第二轮修 |
| L-08 | 🟡 | `ui_verify.py:108-110` | run-dialog 端口断行检查**恒为空集**（`.c-port` 只存在于列表页）→ 永远 PASS 却宣称覆盖弹窗 | 第二轮修（改真实选择器或删掉假检查） |
| L-14 | 🟡 | `ui_verify.py` | console **warning** 也判失败；而 Element Plus 的 `debugWarn` 无 dev 门控 → 第三方抱怨即判红整条门禁 | 协调者裁决：warning 统计并打印但**不**决定退出码（C-12 只要求 error/失败请求入判，故这是**回归到发现原文**而非弱化） |
| L-05 | 🟢 | 四份文档 | `scripts/requirements-verify.txt` 脚本层一致但**文档零引用** | **已修**：README / development / deployment / troubleshooting 各补一行 |
| L-17 | 🟢 | `frontend/.dockerignore:22` | 死条目 `scripts/ui-shots`（该路径不在前端上下文里） | **已修**：删除 |
| 其余 N-02/03/04/05/06/09/10(后端)、N-04/05/06/07/09(前端)、L-11/12/13/15/16 | 🟢 | — | 收尾竞态、`0.0.0.0` 白名单、非 NotFound 静默关闭、标记行黏连、fixture 分支未验证、端口无关放行、`sawData` 守卫、重连重放 tail、注释归因、DNS rebinding 分支、`ERR_ABORTED`、nginx 修复未部署与排障手册缺条目 | 第二轮处理可低成本修项，其余在报告与本报告中如实记录为已知取舍 |

**上一轮报告自身的错误（被审对象也要被审）**：
- **R-L1（事实错误）**：`rd1/review-frontend-deploy.md:190` 称 `docs/troubleshooting.md:21` 也写「4 轮」——实测该行是 `## 镜像相关`，全 docs 只有 epic README 一处。该错误**未**被本报告继承（本报告 `:140` 引的是 `README.md:21`，那处正确）。
- **R-L2（计数不符）**：本报告 `:109` 标题写「Important（21，去重后）」而表内 20 条、正文 20 —— 已更正为 20。

## 2.5 部署验证：修复在真实环境生效（含前后对照）

第二轮修复落地后按用户批准重建并重启线上栈，用**同一支探测器**在**同一台机器**上取前后对照（探测器：`D:\桌面\测试\.rd3-probes\post_deploy_verify.py`，只读 + 自清理，创建的数据卷当场删除）：

| 探测项 | 修复前（旧镜像） | 修复后 | 对应发现 |
|---|---|---|---|
| 对象体建卷 `POST /api/volumes` | **FAIL** `422` `{"type":"string_type","loc":["body"]}` | **PASS** `200 {"ok":true}` | C-01（🔴） |
| 外部 Origin 写操作 | **FAIL** `422`（无守卫） | **PASS** `403 cross-site request rejected (Origin not allowed)` | C-08 |
| 本机 Origin 写操作 | — | **PASS** `200`（随后自清理） | C-08 不误伤 |
| nginx 重定向 Location | **FAIL** `http://127.0.0.1/api/containers`（丢端口 → 指向 80） | **PASS** `http://127.0.0.1:8088/api/containers` | C-03 |
| WS 失败帧 | **FAIL** `{'error': 'no container'}`（旧帧形） | **PASS** `{'dockermgr': 'error', 'error': 'no container'}` | C-19 / L-06 |
| `/api/health`、`/api/containers`、SPA 首页 | PASS | **PASS**（8 个容器） | — |
| **合计** | **4/9 passed, exit 1** | **10/10 passed, exit 0** | |

**真机 E2E（修好后的部署上复跑）**：`scripts/e2e_verify.py` → **18/18 passed，EXITCODE=0**。其中两条现场证据值得单列：

- `WS /ws/logs (realtime logs) -- 收到 20 行真实日志（1 帧）` —— **20 行合并进 1 帧**，即 C-02 的消息节流在真实链路上生效；而修复前的断言只要收到**任意**字符串帧就算通过，链路全断也能 PASS（C-11）。
- `Cleanup committed image -- delete HTTP 200, tag gone: dockermgr-e2e:2acfcfe6` —— 删除被真正复核（旧版无条件记 `True`）。

跑后清点：无 `e2e` 残留容器/镜像/卷；运行中容器 8、卷 8，与跑前一致；容器内上一轮遗留的 `/tmp/e2e.txt` 已删除；上一轮 E2E 遗留的镜像 `dockermgr-e2e:0476b11a`（331 MB）与三个 `pytest-cache-files-*` 空目录（沙箱/ACL 拒删，已用 `takeown`+`icacls /reset` 清除）均已清理。

### 部署侧新发现（环境，非代码缺陷）

**E-1 🟡 后端镜像无法重建**：`docker compose -f deploy/docker-compose.yml up -d --build` 的**前端部分成功**（镜像重建 + 容器重建），**后端部分失败**：

```
ERROR: failed to authorize: failed to fetch anonymous token:
Get "https://ghcr.io/token?scope=repository%3Aastral-sh%2Fuv%3Apull&service=ghcr.io": net/http: TLS handshake timeout
```

定位（协调者实测，排除"网络整体不通"）：

| 探测点 | 结果 |
|---|---|
| 宿主机 `curl https://ghcr.io/v2/` | `401`，1.05s（通） |
| 宿主机 `curl https://ghcr.io/token?...` | `200`，1.23s（通） |
| 宿主机 `curl https://registry-1.docker.io/v2/` | `000`，20s 超时（**不通**） |
| Docker 守护进程（BuildKit）解析 `ghcr.io/astral-sh/uv` 元数据 | **TLS 握手超时**（守护进程出口网络与宿主机不同） |
| 守护进程解析 `python:3.12-slim` / `node:20-alpine` / `nginx:alpine` | 0.0–0.1s（**本地已有元数据缓存**，非真拉取） |

即：宿主机网络正常，**守护进程的出口被挡**；能"通过"的基础镜像全是缓存命中，而 `ghcr.io/astral-sh/uv` 从未缓存过，所以必然失败。**影响**：`docs/deployment.md` 承诺的 `docker compose up -d --build` 在本机当前网络下不可用（这是**首次构建/换机**才会暴露的问题，因为旧镜像还在）。

**本次的止损做法**：前端上线新镜像；后端用 `docker cp backend/app/. dockermgr-backend:/app/app/` + `docker restart` 把修复后的代码送进运行中的容器（**不改依赖**，`security.py` 只用标准库，故安全）。因此：

- 线上**行为**已是修复后的（上表 10/10 与 E2E 18/18 都是在**修复后**的容器上取的）；
- 但 **`deploy-backend:latest` 镜像本身仍是旧的**，容器与镜像已不一致；`docker compose up -d`（不重建）会把容器还原成旧代码。

**E-1 处置（已实施，用户选 A）**：`backend/Dockerfile` 改为**从 PyPI 安装 uv**并钉住版本（`ARG UV_VERSION=0.12.0`；索引可用 `--build-arg PIP_INDEX_URL=…` 覆盖），把 ghcr.io 从构建链路中彻底去掉；`docs/deployment.md` 与 `docs/troubleshooting.md` 补上前置条件与覆盖方法。

**E-1 关闭证据（协调者实测）**：

| 步骤 | 结果 |
|---|---|
| 探明守护进程出口 | 容器内访问 `pypi.org/simple/uv/`、`files.pythonhosted.org`、清华与阿里镜像均 **200**；`ghcr.io/v2/` 返回 `401`（可达，但 token 端点此前超时）→ 改用 PyPI 是对症的 |
| `docker compose up -d --build` | **exit 0**，后端镜像重建成功（此前在第一步 `FROM ghcr.io/...` 即失败） |
| 容器状态 | `dockermgr-backend` **已重建**（`Up Less than a second`，创建时间刷新）——不再是 `docker cp` 临时态 |
| 镜像内 uv | `uv 0.12.0 (x86_64-unknown-linux-gnu)`；`uv run python -c "import app.main"` → `app import OK` |
| **代码一致性** | 容器内 `/app/app/routers/ws.py`、`/app/app/services/security.py`、`/app/app/main.py` 的 SHA256 与工作区源码**逐一 MATCH** → 一次不带 `--build` 的 `docker compose up -d` 不会再静默回退修复 |
| 复验 | 契约探测 **10/10**、真容器日志 **4/4**、真机 E2E **18/18 exit 0** |

> 因此 **RD3-09（后端镜像未重建、容器与镜像不一致）随之关闭**，本轮唯一的环境阻塞项清零。

---
---

# 第三轮：合并复核（rd3，2026-09-11）

复核者：独立子代理，**只读**（唯一触碰是 B2/B7 变异测试的临时改写，同一命令内备份→改写→跑测→还原，SHA256 校验还原后**逐字节一致**：`ws.py = A9CEA43E…F6FF3A`、`containers.py = 5A016D9C…D67ED9D`）。报告：`test-review/rd3/review-consolidated.md`（382 行）。

## Verdict：⚠️ CONDITIONAL PASS

- **不判 ❌**：rd2 的 27 条主干修复经**独立取证确实成立** —— 复核者自做 **3 个变异体全部被杀**、真机 E2E **18/18 退出码 0 且零残留**、线上栈实测已是修复后代码、`vue-tsc` exit 0。
- **不判 ✅**：存在 1 条会在**正常机器/CI 上直接打红测试套件**的缺陷（RD3-01）、1 条**实测可复现**的事件循环阻塞（RD3-02）、1 条**实测可复现**的日志渲染缺陷（RD3-03），以及 2 条门禁/文档真实性缺陷（RD3-04、RD3-05）。

## 3.1 rd2 发现关闭判定（复核者逐条覆盖 36 条，非仅口径内 27 条）

| 判定 | 条数 | 明细 |
|---|:--:|---|
| ✅ CLOSED | **26** | 后端 N-01…N-08；前端 N-01…N-09 **全部**；L-02/03/04/05/06/07/08/14/17 |
| ⚠️ PARTIAL | **3** | 后端 N-09、L-10、L-16 |
| ❌ NOT CLOSED | **7** | 后端 **N-10（升级为 RD3-01）**、L-01、L-09、L-11、L-12、L-13、L-15（后 6 条协调者已记为已知取舍，复核者同意多数） |

**点名易假绿项，复核者逐一自跑取证**（不采信注释与自述）：

| 项 | 独立证据 |
|---|---|
| **B2** 长命流批处理 | 自做变异删 `timer.start()` → `batching: 0 lines delivered in 0 frames` / `1 failed, 4 passed`；基线 `600 lines delivered in 19 frames while the stream was still open`（与审查者探针 19 帧**独立吻合**）；断言确在流仍开着时取样（`:188 produced.wait` → `:207/:212/:217`） |
| **B1** 判别字段三层 | 全仓 grep 确认**只有** `ws.py:34` 发错误帧（旧帧形彻底不再发出）；前端**直接 import 真源码**真值表 17 例中「数据帧被误判」= **0**；活体帧 `{"dockermgr":"error","error":"no container"}` |
| **B3** 收尾单次 flush | `while not finished.wait()` 关闭时**不** flush；`finished.set()` → `is_alive()` 守卫 join → 单次 `flush()`（单一 owner）；活体 `tail=5` 收 1 帧后超时（**无空帧**）。诚实降级：空缓冲时 `flush()` 直接 return，**无法构造确定性变异体** → 证据等级 = 读码 + 精确计数断言 + 活体 |
| **B5** exec 错误分类 | 活体在 `created` 态与 `exited` 态容器上均收到**可读 409 帧**（非零帧静默关闭），随后自清理、零残留 |
| **B7** 端点覆盖 | 自做 2 个变异（`remove(force=force)→False`、`list(all=all)→False`）**均被杀**；29 例覆盖 16 端点；docker-py **7.2.0** 真实签名逐条核对一致（`list(all=)`/`remove(**kwargs)`/`commit(repository=,tag=)`/`save(chunk_size,named=)`/`get_archive(path)`/`exec_create/exec_start/exec_resize`） |
| **B8/B10** 门禁真实性 | 8 场景动态验证：4 个信号（pageerror / console error / requestfailed / 端口断行）都能把退出码 0→1；`record()` 是 `failures` 唯一写入者 |
| **A1/A2/A3/A5** 前端 | A1 两组件均在 `ws.onopen` 内复位退避；A2 `PREFLIGHT_TIMEOUT`+`AbortController`+`finally` 清定时器，两消费方均清 loading；A3 仅 `running` 放行终端；A5 真值表 0 泄漏。（`.vue` 部分为**精确行号静态核实**，未做动态执行，复核者已按对象标注证据等级） |
| **N-07** 部署 | 线上实测 422→**200**、外部 Origin→**403**、307 Location 保留 `:8088`、WS 帧带判别字段 |

## 3.2 rd3 新发现 12 条与处置

| 编号 | 级别 | 位置 | 问题（复核者实测） | 性质 | 处置 |
|:--:|:--:|---|---|:--:|---|
| **RD3-01** | 🟡 | `backend/tests/test_files_api.py:15-38` | `staging_dir` 是「含 `yield` 的函数里在 `yield` 前 `return`」→ 实测 `ValueError: staging_dir did not yield a value`（`_pytest/fixtures.py:1000`）。**任何 `%TEMP%` 可写的机器（你的开发机/CI）上该文件 6 个用例全部 ERROR**；本沙箱因 `%TEMP%` 被拒恰好走 `except` 分支 → **`124 passed` 是沙箱专属结论** | **HARD** | 第三轮必修 + **两种 `%TEMP%` 模式双向复跑** |
| **RD3-02** | 🟡 | `backend/app/routers/ws.py:129-135` | `cont.logs(...)` 及其**流迭代都阻塞在事件循环上**（docker-py `api/container.py:895` 立即发 `_get`，另加 `_check_is_tty` 同步 inspect）。实测伪造阻塞 1.5s → `/api/health` 最坏 **1525ms**（基线 min 1ms / max 34ms）。**零测试覆盖** | **HARD** | 第三轮修（移出事件循环）+ 补能失败的回归测试 + 变异反证 |
| **RD3-03** | 🟡 | `ws.py:191-195` | 批处理假设「一次迭代=一行」，但 TTY 容器走 `_stream_raw_result(chunk_size=1)` → 实测 `'hello world\n'` 变 `'h\ne\nl\nl\no\n \nw\no\nr\nl\nd\n'`（**一字符一行**）。面板自身不设 tty，但会流式读取任何容器 | JUDGEMENT | **决定：记为已知限制**（`docs/troubleshooting.md` 新增条目，含根因/影响范围/规避）。理由：修它要给日志流换「按字节透传」协议，而前端按 `\n` 切分 —— 属跨层契约变更，改动面大于收益 |
| **RD3-04** | 🟡 | `scripts/ui_verify.py:64-68` vs `:250`/`:74` | 未入判 warning 仍打印 `[FAIL]` → 实测同一次运行出现 `[FAIL]` + `UI verification PASSED` + 退出码 0，使 `:250` 自述不变量**为假**，grep `[FAIL]` 的扫描器报假失败 | **HARD** | 第三轮修（输出标记与退出码语义严格一致） |
| **RD3-05** | 🟡 | `docs/deployment.md:106-108` | 「关闭镜像源」片段写成 YAML 列表 `- IMAGE_MIRRORS=`，粘进 `deploy/.env` 使 compose **整体拒绝启动**（实测 `line 2: key cannot contain a space`，EXIT=1）。**由本轮 N-08 修复自己引入** | JUDGEMENT | **已修**（改为 `.env` 的「键=值」写法 + 说明单横线 `${VAR-…}` 的必要性）；协调者独立复验：无横线 → `exit 0` / `IMAGE_MIRRORS: ""`；有横线 → `exit 1`；根目录 `.env` 被忽略、`deploy/.env` 生效 |
| **RD3-06** | 🟡 | `scripts/e2e_verify.py:357-376` | `test_ws_exec` 断言 `token in collected` 可被 **PTY 输入回显**满足（脚本发 `echo <token>`）→ **不执行任何命令也能 PASS**。C-11 只修了 `/ws/logs` 的同类假绿，exec 兄弟被漏 | JUDGEMENT | 第三轮修 + 「命令未执行则失败」反证 |
| **RD3-07** | 🟢 | 本报告 `:284` / epic `README.md:20` | HARD 计数自相矛盾（写 3 条 / 4 条，§2.4 表内实为 5 行标 HARD） | **HARD**（C-22/L-03 同型复发） | **已修**：两处统一为 **5 条** |
| **RD3-08** | 🟢 | `README.md:207` | 代码规模自述与现实不符（1.7k/2.1k vs 实测 `backend/app` 1300 行、`frontend/src` 3168 行） | JUDGEMENT | **已修**（改为 ~1.3k / ~3.2k，行数为协调者本人含空行统计） |
| **RD3-09** | 🟢 | 线上栈 / compose | 后端镜像未重建，线上修复是 `docker cp` 临时态：`dockermgr-backend` 容器创建于 `2026-09-11T01:06`（**从未重建**）vs 前端 `2026-09-14T02:02`。**一次不带 `--build` 的 `docker compose up -d` 会静默回退全部后端修复** | JUDGEMENT | **已记录**：§2.5 + epic README「未完成项」新增行 + 本条；这是本轮唯一"修复在线上，但不在镜像里"的状态 |
| **RD3-10** | 🟢 | `docs/troubleshooting.md` | L-10/L-16 明确要求的两条排障条目缺失（反代 403/1008、307 丢端口） | **HARD** | **已修**：新增「写操作全报 403 / 终端连不上」（含反代保留 Host 的 nginx/Apache 写法 + **安全含义澄清**）与「登录/刷新后跳到 80 端口」（含 `curl -sI` 自测） |
| **RD3-11** | 🟢 | `test_endpoints_coverage.py:105-120,357+` | mock 形状失真/过宽：`_Cont.name="/web"`（真实 `Container.name` **从不带前导斜杠**）；`exec_create/exec_start` 用 `(*args,**kwargs)` → **形状上不可能**发现签名漂移（rd2 称其「已核验的形状」不实） | JUDGEMENT | 第三轮修（按 7.2.0 真实签名收口 + 补 `attrs["Name"]=="/web"` 用例） |
| **RD3-12** | 🟢 | `ws.py:17-20` vs `:196-198`；`:161-164` | 注释与实现不符：称「bounded **drop-oldest**」实为 `pending.clear()` **整批丢弃**（含最新行）；称标记行「never adds a trailing newline」但 `"\n".join` 仍可产生首/尾空行 | JUDGEMENT | 第三轮修：改成**真正的 drop-oldest**（`deque(maxlen=…)`）并让注释与实现一致 |

## 3.3 协调者裁决与不做的事（如实记录）

1. **L-11/L-12/L-13（同源分支、Origin 放宽的含义）**：采用 rd3 建议中的**披露**部分（已写入 `docs/troubleshooting.md` 的「安全含义」段：跨站守卫**不是**认证，不能替代访问控制）。**不采用**「抽 `guard_ws_origin()` 共用函数」：两个 WS 处理器的守卫只有 6 行重复、各自有独立的日志与文案，抽函数属于对**安全关键代码**的纯整形改动，收益（少 6 行）小于回归风险；两条路径均已各自有测试覆盖。**记为已知取舍。**
2. **L-01/L-09/L-15（空帧、同源分支取舍、`ERR_ABORTED`）**：维持「已知取舍」，理由见 rd2 与本报告 §2.4；rd3 复核同意多数。
3. **RD3-03（TTY 容器）**：承诺范围**不含** TTY 容器的日志渲染（面板自己创建的容器不设 TTY），记为已知限制并写进排障手册。
4. **不 commit**：全部修复仍是工作区改动（用户未要求提交）。rd3 建议的「分 4 个提交落盘」留给用户决定。

## 3.4 第三轮修复与验证（含 `%TEMP%` 双向复跑）

> 本节在修复批次落地后回填。**RD3-01 已证伪了「124 passed」的普适性**：该数字只在 `%TEMP%` 被拒的沙箱里成立，因此本轮所有测试结论都必须**同时给出两种 `%TEMP%` 模式**的结果，否则不算验证。

## 3.4 第三轮修复与验证（证据均由协调者独立复跑确认）

| 编号 | 修复 | 决定性证据 |
|---|---|---|
| **RD3-01** | `test_files_api.py` 改为**唯一代码路径**：`tests/_staging/<uuid>`（已 gitignore）+ 默认 mode 的 `mkdir` + `finally` 清理，不再依赖 `%TEMP%`；新增 3 条用例，含**AST 结构锁**（静态拦截「yield 前 return 值」，永久钉死这类只在部分机器暴露的反模式） | 子代理用「正常机器等价机」（conftest 覆盖 `tmp_path_factory` 使其必然成功）复现：修复前 **`ValueError: staging_dir did not yield a value` + 2 errors**、修复后 **5 passed**。协调者独立 AST 扫描：修前 `hits=1`（全项目仅此一处）→ **修后 `hits=0`**。两种 `%TEMP%` 模式各 **137 passed**、`_staging` 无残留 |
| **RD3-02** | `ws.py` 新增 `_open_log_stream()`：**建立流与迭代行整条都在生产者线程**，async 侧只管发送与生命周期；建立失败经 `failure` 通道回到接收循环，**先发错误帧再关闭**（故意不设 `stop`，否则帧发不出去） | 子代理纠正了复核者的判断（迭代**本来**已在 worker 线程，真正占循环的是 `cont.logs()` 建立）并在旧代码上跑出新回归 **FAIL：`/api/health took 1.50s while cont.logs() was parked for 1.5s`**（独立复现 1525ms）；修复后 6 次连跑 **1.58–25.09ms**（阈值 500ms，与坏值 1503ms 双向分离 3×/20×）。**协调者真守护进程复核**见下 |
| **RD3-12** | pending 改**真·drop-oldest**（`del pending[:excess]` + 精确丢弃计数）；两处不实注释按「注释服从正确行为」修正（空行只可能来自容器真实输出，**刻意保留**——过滤它才是真的丢输出） | 变异 M2（恢复 `pending.clear()`）→ 40 行**全丢**、43 行计数 40≠38，两条参数化用例全挂；修复后 `['... 38 lines dropped ...', 'line-38'…'line-42']`（保留最新 5 行且顺序正确） |
| **RD3-06** | E2E exec 断言改为 `echo $((6位+6位))`：**和恒为 7 位、不可能出现在回显文本里**，且要求独立成行；另用 shell 注释行单独证明「回显通道是活的」 | 反证矩阵：旧断言对「只回显不执行」的桩 **PASS（假绿）**、新断言对同一桩 **FAIL**、对真执行的桩 PASS。协调者复跑真机 **18/18 exit 0**（`执行结果行 1455513=yes（末行 '#'）`） |
| **RD3-04** | `ui_verify.py` 非判定项改打印 `[warn]`/`[note]`，**`[FAIL]` 与退出码语义严格一致**；判定面逐字未动 | 8 场景离线桩全过；pre-fix 快照在「仅 warning」场景复现 `[FAIL] lines=1 + exit 0`（自违不变量），修后 `[warn] + exit 0 + 零 [FAIL]` |
| **RD3-11** | mock 按 docker-py **7.2.0** 真实签名重写（`exec_create/exec_start/exec_resize`）；明确「去前导 `/`」服务的是 `Container.name`（`attrs["Name"]` 从不被读）→ 真实形态与未 strip 形态各有用例 | 变异：关键字漂移 `stdin=True→stdin_=True` 在**旧** mock 下 GREEN（测不出）、**新** mock 下 RED；两处 name 变异均 RED |
| **RD3-03** | **记为已知限制**（不改代码）：写入 `docs/troubleshooting.md` | 面板自己创建的容器不设 TTY；修它需给日志流换成「按字节透传」协议，而前端按 `\n` 切分 → 跨层契约变更，改动面大于收益 |
| RD3-05/07/08/10 | **已修**（文档侧，协调者） | RD3-05 用 compose 实测三态（无横线 exit 0 + `IMAGE_MIRRORS: ""`、有横线 **exit 1**）；RD3-07 计数统一为 5；RD3-08 改为实测 1.3k/3.2k；RD3-10 新增两条排障条目 |
| RD3-09 | **已记录**（§2.5 + epic README「未完成项」） | 后端镜像未重建、容器与镜像不一致；不带 `--build` 的 `docker compose up -d` 会静默回退后端修复 |

**协调者对 RD3-02 的真实守护进程复核**（补子代理自述的「无真机验证」缺口）：把第三轮代码送进运行容器重启后，用**真容器**探针实测 **4/4** —— 真容器日志帧（20 行/1 帧）、非 TTY 容器单字符行 **0/20**、不存在容器的错误帧带判别字段、**日志流打开期间 `/api/health` 最坏 33.3ms**（`[33.3, 18.5, 18.0, 18.5, 3.4, 3.8]`）。

**最终门禁数据（协调者自跑）**：`uv run --frozen pytest -q` → **137 passed**；`vue-tsc -b --force` → exit 0；AST 反模式扫描 → **hits=0**；`scripts/e2e_verify.py` → **18/18 exit 0**；部署后契约探测 → **10/10 exit 0**。

**环境事实（解释「124 passed」为何曾是沙箱专属）**：本沙箱下 pytest 的 `TempPathFactory` 用 `mode=0o700` 建目录，而 0o700 目录连 `os.scandir` 都被拒（子代理 mode 对照实验：`0o700` 列目录与删除均 `WinError 5`，`0o755/0o777/0o500` 均正常）→ `tmp_path_factory.mktemp()` 必然抛 `OSError`，旧 fixture 因此**永远**走 `except` 分支。正常机器上它会走 `return` → 该文件 6 个用例全 ERROR。**修复后不再依赖 `%TEMP%`，两种模式结果一致。**

**残留清理**：上一轮 E2E 镜像（331 MB）、`pytest-cache-files-*`、子代理本轮产生的 5 个 0o700 目录（含仓库根 `docker-manager\.t2`）与两个 `%TEMP%` 探针目录均已清除；`git status` 权限警告**归零**。
