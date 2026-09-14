# 代码审查报告（前端 + 部署透镜）— docker-manager-v1

> 审查范围：`c689f71a52f9cffb89c80efd706149b3d95307ec..81490291321b22d06aec0cfbeff05f06bb7905c2`（21 个编码 commit / 63 文件 / +9859 行）
> 透镜：前端（`frontend/**`）+ 部署（`deploy/**`、`scripts/**`、根目录文档、`.env.example`、`.gitignore`）
> 依据文件：`spec.md`（全文 130 行）、`plan.md`（全文 1076 行）、`scope.md`、`docs/*.md`、`.env.example`、`deploy/docker-compose.yml`
> 审查日期：2026-09-11
> 审查方式：全量 diff 审查（非抽查）；不接受编码者自我声明，结论以代码 + 实测为准
> OCR 预扫：**未执行（ocr CLI 未配置 LLM 端点）** — 见文末「OCR 预扫」段

## 审查方法与证据等级

| 证据类型 | 具体动作 |
|---------|---------|
| 静态全量 | 逐文件读完 `frontend/**`（19 个源文件）、`deploy/**`、`scripts/**`、根 README、`docs/deployment.md`、`docs/development.md`、`docs/troubleshooting.md`、epic `README.md` |
| 契约核对 | 读后端 `routers/{containers,images,volumes,files,ws}.py`、`config.py`、`services/docker.py`，逐条比对前端调用路径/方法/payload 形状/错误帧 |
| 实测（只读） | 对**正在运行的部署**（127.0.0.1:8088）做 HTTP/WS 探针：`/api/health`、`/`、`/images`、`/favicon.ico`、`/assets/index-*.js`、`/ws/logs`（真实日志行）、`/ws/exec`（拿到 shell 提示符）；线上 bundle 内含 R5 的 `attachCustomKeyEventHandler`/`hasSelection`（证明部署的即被审代码） |
| 实测（工具链） | `vue-tsc -b` 通过（前端 TS strict 无错）；`pytest --collect-only` = 66（核对 README 的「66 个」属实）；multipart 中文文件名解码探针 = 正确（无乱码） |
| 被沙箱阻断 | Playwright 浏览器脚本无法执行（`asyncio.create_subprocess_exec` → `PermissionError [WinError 5]`，即命名管道限制）；`docker exec` 读容器内 nginx.conf 被拒（docker npipe 权限）。本会话审批已禁用，未做升级重试 → 相关结论标注为「按代码推定」 |

---

## 段 1 · Plan alignment — Verdict：⚠️

对照 `spec.md` / `plan.md` / `scope.md` 逐条核，**功能闭环（看容器→看日志→进终端→双向拷贝→打包镜像→导出 tar）全部落地且环节齐全**，但存在 1 条用户驱动的功能蔓延、1 条 spec 硬性范围内的缺失（暂停/恢复无界面入口）、以及若干部分实现。

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|------|------|
| 🟡 | `frontend/src/views/ContainersView.vue:86-97`（下拉菜单仅 logs/terminal/copy/commit/remove） | **暂停 / 恢复无界面入口**。`containersApi.pause/unpause` 在 `frontend/src/api/index.ts:63-64` 定义后**无任何视图调用**（全仓 grep 仅此定义处命中），CSS 里却已有 `.dm-dot.is-paused`（`styles/main.css:290`）。plan 要求操作列含「暂停」、AC 要求 F1–F10 各动作可经界面触发，README 也宣称有该功能 → 三处宣称与实现不符 | **A 缺失** / HARD VIOLATION | `plan.md:886`；`scope.md:96`（AC3）；`README.md:17` |
| 🟡 | `frontend/src/components/ContainerLogs.vue:103-108`；`frontend/src/components/ContainerTerminal.vue:209-216` | **断线重连 / 消息节流未落地**：两处 WS 都只有手动「重连」按钮，`onclose` 仅把状态置为 closed，无自动重连、无指数退避、无消息批量/防抖。日志侧仅以 `MAX_LINES=3000` 截断代替节流（`:45`、`:75-77`） | **A 缺失**（部分实现） / JUDGEMENT | `spec.md:113`（风险表对策「消息节流、断线重连、防抖」） |
| 🟡 | `frontend/src/components/ContainerLogs.vue:95` + `backend/app/routers/ws.py:15-20` | **停止中的容器看不了日志**：`/ws/logs` 的 `filter` 只在前端传容器名，后端 `_find_container` 用 `containers.list()`（仅 running）做前缀匹配，停止的容器必然匹配不到 → 「历史日志」（F2 要求「实时(WS)+**历史**」）在最需要它的场景（容器挂了想看为什么）不可用 | **A 缺失** / JUDGEMENT（F2 措辞可宽可严） | `scope.md:25`（F2）；`spec.md:85` |
| 🟢 | `frontend/src/api/index.ts`（无 `get`）；`frontend/src/views/ImagesView.vue:35-72` | 三处「详情/使用情况」缺口：① 容器详情接口 `GET /api/containers/{cid}` 存在但前端无入口（api 层未暴露 `get`，列表字段与详情几乎等价，影响小）；② 镜像列表无「大小/创建时间」（接口也不返回，见 §5 G6）；③ 卷无「使用情况」。plan Task 2/4/5 均未要求，属 scope↔plan 落差 | **A 缺失** / JUDGEMENT | `scope.md:26`（F3 列表/详情）；`scope.md:28`（F5 使用情况）；`scope.md:96`；`spec.md:13` |
| 🟢 | `frontend/src/views/SettingsView.vue`（**文件不存在**） | plan 明确列出要创建 `SettingsView.vue`(占位)，实际未创建、也未挂路由（`router/index.ts:3-29` 只有四路由 + 重定向）。占位文件无功能影响 | **A 缺失** / HARD VIOLATION | `plan.md:810` |
| 🟡 | `frontend/src/components/RunContainerDialog.vue:1-342`；`frontend/src/api/index.ts:59`；`backend/app/routers/containers.py:102-151`；`backend/app/services/run_spec.py` | **「从镜像创建并运行容器」整条链路（含 5 个常用预设）超出 spec/plan 范围**：plan Task 1–12 无任何一条要求 `POST /api/containers`；spec §7 明确把「容器参数细节查看/**启动配置编辑**」划入 v1.1（不在范围），scope 亦列为 P1。触发来源是用户口头要求（epic README R4 记录），属**经授权的蔓延**，但仍应作为范围偏差登记并补文档/验收口径 | **B 蔓延** / HARD VIOLATION | `spec.md:130`（§7 不在范围）；`scope.md:37`（P1「容器参数细节/启动配置编辑（v1.0 后）」） |
| 🟢 | `deploy/docker-compose.yml:12-14`；`backend/app/routers/images.py:89-92,113-181`；`frontend/src/views/ImagesView.vue:17-21,104-108` | 应用级镜像源降级（`IMAGE_MIRRORS` + `GET /api/images/pull/mirrors` + 前端提示 + `.env.example` 新项）plan 无此任务。**不触碰** §7「镜像仓库管理（registry）」禁令——它是拉取兜底而非仓库管理；代价是多了一个对外接口与一层配置面 | **B 蔓延** / JUDGEMENT | `spec.md:126`（§7 registry 不在范围）；`plan.md:333-422`（Task 4 无此要求） |
| 🟢 | `frontend/src/styles/main.css:1-362`（R2 整体重设计） | UI 全面重设计（侧边栏/页头/设计 token）属范围外视觉工作，无语义功能蔓延；CSS 体量 362 行，是本 epic 最大单文件之一 | **B 蔓延** / JUDGEMENT | `plan.md:926-961`（Task 11 只要求三个页面功能） |
| 🟢 | `deploy/docker-compose.yml:1-27`；`frontend/Dockerfile:10-12` | **服务拓扑与 spec/plan 的显式描述不符**：spec §5 写「docker-compose services：`backend`（挂 socket + 8088）、`frontend`（构建产物给 Nginx）、`nginx`（8088 对外）」、plan 要求 `deploy/nginx.conf`；实际是 **2 个服务**，nginx 内嵌进 frontend 镜像，nginx.conf 放在 `frontend/nginx.conf`，`deploy/` 下只有 compose。行为等价（已实测反代可用），无功能回归，代价是「改 nginx 配置要重建前端镜像」+ 文档/仓库布局与 spec 不符 | **C 看似对实则错（结构）** / JUDGEMENT | `spec.md:101`（§5）；`plan.md:970`、`plan.md:1008`（Task 12 Step 3） |
| 🟢 | `frontend/src/api/index.ts:75`；`frontend/src/views/ImagesView.vue:170-176` | 镜像导出**实现方式与 plan 示例不同但更好**：plan 给的是 axios blob + `URL.createObjectURL`（前端吃内存），实现改为 `<a href="/api/images/{id}/save">` 直链下载（流式不占前端内存，与 spec D6 的流式意图一致）。注意 `imagesApi.save` 从未存在，后续勿误判为「缺失」 | **C 记录项** / JUDGEMENT | `plan.md:938-943`；`spec.md:56-57`（D6 流式） |

---

## 段 2 · Code quality — Verdict：⚠️

整体质量偏高：TS 严格模式无 `any` 滥用、组件分层清晰、卸载清理完整；问题集中在**错误反馈的完整性与一致性**。

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|------|------|
| 🟡 | `frontend/src/components/ContainerLogs.vue:100-102`（+ `backend/app/routers/ws.py:75`） | **控制帧被当日志渲染**：后端在找不到容器时先发 `{"error": "no container"}` 再关连接，前端 `onmessage` 无条件下 `append(e.data)` → 用户日志区里出现**一行原始 JSON**，随后状态变「已断开」，**看不到任何可读原因**（无法区分「容器没在跑」「名字不匹配」「网络断了」）。终端侧同理：`ContainerTerminal.vue:209-213` 只写「[会话已结束]」 | JUDGEMENT（前后端契约在前端侧未闭合） | `spec.md:13`（动作全部可见、统一入口）；`ws.py:75-77` |
| 🟡 | `frontend/src/components/FileCopyDrawer.vue:109-119`；`frontend/src/views/ImagesView.vue:170-176` | **假成功反馈**：拷出下载与导出都只用 `<a href>` 触发，没有可观测的失败通道 — 路径不存在/接口 500/nginx 拒绝时，用户仍看到绿色「已开始下载 / 已开始导出」。既没有 axios 的 catch，也没有 fetch+blob+错误分支 | JUDGEMENT | `spec.md:13`；`spec.md:44`（D4 拷出流程） |
| 🟢 | `frontend/src/views/ContainersView.vue:228-231`、`NetworksView.vue:122-125`、`VolumesView.vue:97-100` | **错误提示两头做（DRY）**：只有 `ImagesView`/`RunContainerDialog` 用了 `utils/error.ts:13` 的 `showApiError`（长错误自动弹窗）；其余三个视图各写一份 `fail()`，把多行错误（例如 commit 失败、镜像被引用）压成截断 toast。与项目自定约定相悖 | JUDGEMENT（引用项目自定约定） | `docs/development.md:83`（「后端错误统一走 showApiError，不要各写各的 ElMessage.error」） |
| 🟢 | `frontend/src/components/FileCopyDrawer.vue:89-107` | 绕过 api 层：直接 `import axios from 'axios'` + 硬编码 `/api/containers/${cid}/copy`，并再抄一份错误提取逻辑；同文件的下载又用裸 href 拼路径（`:115`）。api 层不是唯一出口 | JUDGEMENT | `docs/development.md:82`（「所有后端类型定义集中在 api/index.ts」） |
| 🟢 | `frontend/src/components/ContainerLogs.vue:67-77` | `if (part === '') continue` 丢弃空行 → 日志的段落结构丢失；注释声称「保留尾部不完整行」，但代码没有做跨 chunk 的行缓冲（当前后端按行下发才没暴露，属于隐式契约） | JUDGEMENT | `ws.py:88-96`（逐行下发） |
| 🟢 | `frontend/src/components/ContainerLogs.vue:121-128` | `a.click()` 之后立刻 `URL.revokeObjectURL(a.href)`，部分浏览器可能取消下载（常规做法是延迟回收）；同屏其他下载点用直链所以不受影响 | JUDGEMENT | — |
| 🟢 | `frontend/src/main.ts:11-13` | 全局注册**全部** Element Plus 图标（`Object.entries(Icons)`，数百个组件），换来的主 chunk 1.26 MB（实测 `dist/assets/index-BGeOqOmG.js`，未压缩） | JUDGEMENT | — |
| 🟢 | `frontend/src/views/ContainersView.vue:213-218` | 「契约即展示字符串」：后端 `_format_ports` 已用 `", "` 拼好人类可读端口（`backend/app/routers/containers.py:29-50`），前端再 `split(',')` 反解析 → 跨端重复解析逻辑，后端一改格式前端静默失效 | JUDGEMENT | `containers.py:50` |
| 🟢 | `frontend/src/views/VolumesView.vue:138-145` | 「复制路径」只有 `navigator.clipboard` 一条路，失败只提示「浏览器不允许访问剪贴板」；`ContainerTerminal.vue:119-135` 已经有 `execCommand` 兜底，这里没有（非 127.0.0.1/https 访问时必然失败） | JUDGEMENT | — |

**边界与资源检查结论（无发现项，作为正面结论记录）**

- **内存泄漏**：三处长生命周期资源都做了卸载清理 —— `App.vue:100-102`（`clearInterval`）、`ContainerLogs.vue:135-142`（置 `disposed`、置空 handler、`ws.close()`）、`ContainerTerminal.vue:275-288`（移除 capture 监听、`observer.disconnect()`、`term.dispose()`、置空引用）。`ContainerTerminal.vue:75-78` 用 `disposed` 兜住 `fit()` 的异步尾部（含 rAF 回调），未发现悬挂回调。
- **TS 类型安全**：全仓仅 1 处 `any`，在官方 shim `src/env.d.ts:5`（`DefineComponent<{}, {}, any>`）；`tsconfig.json:14-17` 开了 `strict`/`noUnusedLocals`/`noUnusedParameters`；**实测 `vue-tsc -b` 通过**。
- **中文/二进制文件名**：用 Starlette 1.6.0 + python-multipart 走真实 multipart（模拟 Chrome 发原始 UTF-8 filename）实测解码正确（`file.filename` 码点与 `中文文件.txt` 完全一致），`os.path.basename` 路径也正常 → **无乱码问题**（本项为实测排除，不是推测）。
- **空列表 / 超长日志**：四个视图都有 `#empty` 插槽（如 `ContainersView.vue:102-110` 还带「显示全部容器」引导）；日志有 3000 行上限与暂停/清屏/下载。

---

## 段 3 · Architecture — Verdict：⚠️

结构判断：**API 层收口基本成立、组件/视图划分合理、构建产物与反代链路实测可用**；两个需要决策的点是超时策略与配置产物遮蔽。

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|------|------|
| 🟡 | `frontend/src/api/index.ts:51,59,66` vs `scripts/e2e_verify.py:156,308` | **超时策略内部不一致，会造成「假失败」**：全局 `timeout: 30000`，`NO_TIMEOUT` 只给了 pull（`:73`）。但项目自己的 E2E 给 `POST /containers`（创建容器）**180s**、`commit` **120s**。大镜像首次 run（解压层）或大文件系统 commit 超过 30s 时，前端先报超时 → 用户看到失败，而后端仍在继续；创建类调用不幂等，用户重试会遇到 409（名字/端口占用，见 `containers.py:140-143`） | JUDGEMENT | `api/index.ts:51`；`e2e_verify.py:308`（timeout=180）；`e2e_verify.py:156`（timeout=120） |
| 🟢 | `frontend/vite.config.ts:1-13`；`frontend/tsconfig.node.json:3`（`composite` 且无 `outDir`/`noEmit`） | **配置产物遮蔽源码配置**：`npm run build` 先跑 `vue-tsc -b`，会把 `vite.config.ts` 编译出 `vite.config.js`+`.d.ts` 落在源码目录；而 Vite 的配置查找顺序里 **`.js` 优先于 `.ts`**（我实测的报错信息即为 `failed to load config from ...vite.config.js`）。因此改完 `vite.config.ts` 直接 `npm run dev`（README:228 推荐的开发命令，不经过 vue-tsc）会读到旧副本，表现为「改动没生效」 | JUDGEMENT | `package.json:8`（`vue-tsc -b && vite build`）；`.gitignore:19-21`（作者已知这些产物，已忽略但未解决遮蔽） |
| 🟢 | `frontend/src/router/index.ts:3-29` | 无 404 兜底路由（`/:pathMatch(.*)*`）：访问未知路径时外壳渲染、内容区空白，且 `App.vue:31-32` 仍显示默认标题，用户不知道发生了什么 | JUDGEMENT | — |
| 🟢 | `frontend/src/App.vue:45,89-94` | 「刷新」用递增 `:key="`${route.fullPath}#${reloadKey}`"` 强制 remount 视图来重新取数：实现简单有效，但会把正在看的抽屉/终端/日志一起销毁（用户点「刷新」等于丢上下文）。属设计取舍，记录备查 | JUDGEMENT | — |

**架构正面结论（逐项核实）**

- **API 层**：`api/index.ts` 集中了 4 组端点 + 全部 TS 类型，`baseURL='/api'`，并对 pull 单独放开超时；例外见 §2 的 3 处绕过（FileCopyDrawer 裸 axios、2 处裸 href）。
- **Nginx 反代 WebSocket**：`frontend/nginx.conf:38-47` 同时具备 `proxy_http_version 1.1` + `Upgrade $http_upgrade` + `Connection "upgrade"` + 独立 3600s 读/写超时 + `proxy_buffering off` —— 正确。
- **超时/体积配置**（README 自述的两个真机坑）：`nginx.conf:12-13` 读/写超时 3600s（修 60s→504）、`:22` `client_max_body_size 0`（修 >1MB→413）、`:17-18` 关掉响应/请求缓冲（配合流式导出与直传上传）—— 与 `docs/troubleshooting.md:46-79` 的修复说明一致。
- **构建与产物**：Vite `base` 用默认 `/`，与 nginx `root` 托管方式一致；静态资源实测 `/assets/index-BGeOqOmG.js` 返回 200 且 MIME 为 `application/javascript`；`/images` 命中 `try_files ... /index.html` 回退（实测 200 text/html），`createWebHistory` 的刷新 404 问题已解决。
- **WebSocket 生命周期**：URL 统一由 `wsUrl()` 生成（`ContainerTerminal.vue:47-50`、`ContainerLogs.vue:62-65`），走同源 host 由 nginx 反代，无硬编码 8088/后端域名 —— 这点比很多同类实现干净；重连是手动按钮触发并显式清理旧 socket（`ContainerTerminal.vue:219-229`）。
- **状态管理**：无 Vuex/Pinia，全部组件局部 `ref`；对一个无持久化的面板是合适的选择。

---

## 段 4 · Testing — Verdict：⚠️

`scripts/**` 的三个脚本**有真机价值**（断言的是行为而不是「没报错」，`stty size`、tar `manifest.json`、marker 往返、`.xterm-selection div`、SIGINT 计数都是好断言），但存在**假阴性通道 / 门禁失效 / 环境依赖未声明**三类问题。

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|------|------|
| 🟡 | `scripts/e2e_verify.py:395-396`（`if __name__ == "__main__": main()`，`main()` 无返回值） | **E2E 脚本永不返回非零退出码**：失败项只打印 `FAILED:` 摘要，进程仍 exit 0。任何「跑一遍看是否通过」的自动化都在这里失效（对比 `ui_clipboard_test.py:140` 正确返回 `0 if passed == len(results) else 1`）。epic README 用 `18/18 passed` 当终态证据，人眼读没问题，但机器无法复核 | JUDGEMENT | `e2e_verify.py:385-392`；对照 `ui_clipboard_test.py:140` |
| 🟡 | `scripts/e2e_verify.py:211-217` | **WS 日志断言可假阴性**：15s 内**一条消息都没收到**也记 PASS（理由「容器可能确实没输出」）。于是「WS 通了但完全不推日志」与「正常」不可区分 —— 这恰好是 R1 修过的 `logs(follow=True)` 阻塞型缺陷的表现形态。建议断言一个**已知会产日志的动作**（例如先 `echo` 一条再收） | JUDGEMENT | `e2e_verify.py:213-217`（`record(..., True, "connected, no output within 15s (acceptable)")`） |
| 🟡 | `scripts/ui_verify.py:153`（`return 1 if page_errors else 0`） | **UI 校验脚本的判定面太窄**：`console_errors`（`:28-33`）、`failed_requests`（`:35-38`）、以及端口断行检查 `broken`（`:55-56`）**只 print 不判定**。因此「0 控制台错误 / 0 失败请求」这类结论是**肉眼读输出**得到的，脚本本身不拦任何回归。同时 `restart_text`、`filled`、`hint.is_visible()`（`:80,95-101`）等检查同样只打印，返回值恒为 `True`/字符串，无法作为断言 | JUDGEMENT | `ui_verify.py:46-153` |
| 🟡 | `scripts/ui_verify.py:7,23-25`；`scripts/ui_clipboard_test.py:9,31`；`.gitignore:42` | **换机器/换环境直接跑挂，且依赖未声明**：① 脚本要求 `.browser-tools\Scripts\python.exe` —— 该 venv 被 `.gitignore:42` 忽略，全仓**没有任何地方声明 playwright 依赖**（`git ls-files` 无 requirements/环境文件），文档只说「用本机已装 Chrome」（`docs/development.md:141`）没说怎么装 playwright；② `ui_clipboard_test.py:31` 必须 `headless=False`（有头）→ 无显示环境（CI/远程）必挂；③ 两个脚本都硬依赖「页面里存在含 `running` 的表格行」与「至少一个镜像」（`ui_verify.py:66,121-123`、`ui_clipboard_test.py:47-51`），空主机上会以 Playwright 超时崩掉而不是给出可读前提不满足提示 | JUDGEMENT | `.gitignore:42`；`ui_verify.py:7`；`ui_clipboard_test.py:9,31,47` |
| 🟢 | `scripts/e2e_verify.py:206,252`（`import websockets` 写在函数内） | **隐式依赖 `websockets`**：`backend/pyproject.toml` 未声明（只作为 `uvicorn[standard]` 的传递依赖存在）。实测本机：backend venv 有、`.browser-tools` venv **没有** → 若按文档口径混用解释器，WS 两项会静默 FAIL。好在 import 在函数内且被 `except` 包住，表现为 FAIL 而非崩溃 | JUDGEMENT | `backend/pyproject.toml:5-17` |
| 🟢 | `scripts/e2e_verify.py:321-323` | **条件断言导致项数漂移**：`if info.get("ports"): record(...)` —— 端口为空时该断言整条消失，宣称的「18 项」会变成 17 项而无人察觉（`:292-294` 的 image 选择也依赖本机已有镜像，注释里首选 nginx:alpine/alpine/python，缺失时退化为 `tags[0]`，可能选到 distroless 镜像） | JUDGEMENT | `e2e_verify.py:288-294,321-323` |
| 🟢 | `frontend/package.json:6-10`；全仓无 `*.test.ts`/`*.spec.ts` | **前端零单元测试**：无 test 脚本、无 vitest 依赖、无测试文件。plan 把 vitest 标为「可选」，故**不构成硬违规**；风险评级：中低——风险最高的前端逻辑（按键接管/剪贴板/fit 尺寸）已有 `ui_clipboard_test.py` 6 项行为断言覆盖，未覆盖的是纯函数（`showApiError` 的分支、`splitPorts`、预设生成与表单重置）与路由/空态，这些改坏只能靠人眼看截图 | JUDGEMENT | `plan.md:811`（「Tests: `frontend/src/api/index.test.ts`（可选用 vitest）」） |

**脚本的正面证据（可重复性与断言强度）**

- 可重复运行：E2E 用 `uuid` 生成容器名/标签/marker（`e2e_verify.py:122,153,283`），跑完有 `finally` 清理（`:326-333`）与镜像清理（`:383`），重复跑不冲突。
- 断言的是行为不是「没报错」：`stty size` 必须回 `43 132`（`:250-275`）、`docker save` 结果必须能被 `tarfile` 打开且含 `manifest.json`（`:180-184`）、拷入拷出用同一 marker 做字节级往返（`:136-147`）、非法端口必须返回 **400 而非 500**（`:336-347`）。
- 假阴性教训已被正确吸收：剪贴板测试用 `.xterm-selection div` 计数而不是 `window.getSelection()`（`ui_clipboard_test.py:79-80`），并断言「Ctrl+C 复制时不产生新的 `^C`」（`:83-96`）与「无选区时 Ctrl+C 仍是中断」（`:100-109`）——把 R5 的两个边界行为固定下来了。`docs/development.md:143-146` 把这三条教训写进了文档。

---

## 段 5 · Production — Verdict：⚠️

真机可用性**实测通过**；spec §6 的硬性安全约束（仅绑 127.0.0.1、后端不暴露）**合规**；扣分项是构建可复现性（无 `.dockerignore`）与配置项「文档承诺可改、实际写死」。

| 严重度 | file:line | 描述 | 性质 | 依据引用 |
|:--:|------|------|------|------|
| ✅ | `deploy/docker-compose.yml:23-25`（`"127.0.0.1:8088:80"`）、`:16-17`（`expose: 8088`，**无 `ports`**） | **spec §6 硬性要求合规**：docker-compose 绑定 `127.0.0.1:8088`、后端仅 `expose` 不发布端口、无 `0.0.0.0` 映射。实测：宿主上仅这一个入口可用，`/api/*` 经 nginx 反代可达 | HARD VIOLATION（**不成立**，已核实合规） | `spec.md:111`（「部署强制仅映射 127.0.0.1 访问、禁止后端暴露到 0.0.0.0 公网端口，docker-compose 绑定 `127.0.0.1:8088`」）；`plan.md:13`（Global Constraints） |
| 🟡 | `frontend/Dockerfile:5-6`；全仓**无 `.dockerignore`**（`git ls-files` 与文件系统均无命中） | **构建上下文不可控**：实测 `frontend/` 目录 **118.2 MB**（含 `node_modules/` 与 `dist/`），`COPY package*.json` + `npm ci` 之后紧接 `COPY . .`，会把**宿主的 node_modules 合并覆盖进 Linux 构建镜像**——宿主的平台相关二进制（`@esbuild/win32-x64`、`@rollup/rollup-win32-*`）被打进镜像，锁文件漂移被静默掩盖，构建变慢且不可复现。全新 clone（无 node_modules）不受影响，所以「全新 clone 能否构建」这一项是通的，但开发者本机构建与 CI/他人构建结果可能不一致 | JUDGEMENT | `frontend/Dockerfile:5-6`；`deploy/docker-compose.yml:20-21`（context=../frontend） |
| 🟡 | `deploy/docker-compose.yml:8-14` vs `docs/deployment.md:80-94` / `README.md:71-78` / `.env.example:3-6` | **文档承诺 4 个变量可用 `.env` 覆盖，实际只有 1 个生效**：compose 里只有 `IMAGE_MIRRORS=${IMAGE_MIRRORS:-...}` 用了变量替换；`DOCKER_HOST`（`:9`）、`PORT`（`:10`）、`TMP_DIR`（`:11`）是硬编码字面量，写进 `deploy/.env` 后**不生效**（部署文档 §4.1 还专门教用户 `cp ../.env.example .env`） | JUDGEMENT（文档与实现不一致） | `deploy/docker-compose.yml:9-11`；`docs/deployment.md:80-94`；`README.md:71-78`；`.env.example:3-6` |
| 🟢 | `docs/epics/docker-manager-v1/README.md:74` | 「未完成项」表仍写「`.gitignore` 忽略 `uv.lock` 导致全新 clone 构建失败 — **待修复**」，但**同一次提交（8149029）已修复**：`.gitignore:5-8` 改为显式「deliberately COMMITTED」说明、`backend/uv.lock`（887 行）已入库，`git check-ignore backend/uv.lock` 无命中。看板未同步，读者会得出错误结论（本次审查任务书即引用了这条旧结论） | HARD VIOLATION（可程序化核实为**已修复**） | `.gitignore:5-8`；`git ls-files --error-unmatch backend/uv.lock` 成功；`git log --diff-filter=A -- backend/uv.lock` = 8149029 |
| 🟢 | `README.md:26`、`README.md:21` vs `frontend/src/views/ImagesView.vue:35-72`、`frontend/src/api/index.ts:13-19`、`frontend/src/components/FileCopyDrawer.vue:12-19`、`backend/app/routers/files.py:16-26` | **功能文档夸大**：① README 称镜像列表「含标签、**大小、创建时间**」——UI 只有「标签/镜像 ID/操作」三列，接口也不返回 size/created（`images.py:73-84` 只给 id/tags/digest/short_id）；② README 称文件拷贝「支持**整目录**打包传输」——拷出（`get_archive(path)`）成立，拷入只支持单文件（`el-upload :limit="1"` + 单 member tar），无目录上传入口 | JUDGEMENT | `README.md:21,26`；`spec.md:45`（D4「目录支持打包」） |
| 🟢 | `docs/troubleshooting.md:67`；`docs/development.md:84` | **排障指引与代码不符**：两处都说「导出镜像要用 `NO_TIMEOUT`（`{timeout: 0}`），否则 axios 30s 会先断开」；但导出根本不走 axios —— 它是 `<a href="/api/images/{id}/save">` 直链（`api/index.ts:75`、`ImagesView.vue:170-176`），`NO_TIMEOUT` 实际只作用于 pull（`:73`）。照此指引排查导出中断会白费工夫 | JUDGEMENT | `docs/troubleshooting.md:63-67`；`api/index.ts:53-55,73-75` |
| 🟢 | `frontend/index.html:5` | `/favicon.ico` 不存在（无 `frontend/public/`、`git ls-files` 无 favicon）。**实测**：`GET /favicon.ico` 被 `try_files` 回退成 `200 text/html`（444 字节 = index.html），浏览器标签页无图标；这类「静默回退」也不会被任何断言捕获 | HARD VIOLATION（实测） | `index.html:5`；实测记录 |
| 🟢 | `frontend/nginx.conf:22` + `backend/app/routers/files.py:19` | **上传无任何上限**：nginx `client_max_body_size 0`（为修 413）+ 后端 `local.write_bytes(await file.read())`（整个文件读进内存）+ compose 未设内存限制 → 单次超大上传可把 backend 容器打爆。因仅 127.0.0.1 可达、且属受信任自用场景，风险低但不能算零（本机多用户/被当作跳板时成立） | JUDGEMENT | `spec.md:111`（受信任本机前提）；`README.md:263`（自述 >1GB 会占较多内存） |
| 🟢 | `deploy/docker-compose.yml:19-27` | 两个服务都没有 `restart:` 策略，也没有 healthcheck（宿主重启后需手动 `up`；nginx 先于后端就绪时首页可用但接口短暂 502）。非 spec 要求，记录备查 | JUDGEMENT | — |

**真机可用性实测记录（本次审查独立执行，只读）**

| 探针 | 结果 |
|------|------|
| `GET /api/health`（经 nginx） | `200 {"status":"ok"}` |
| `GET /`、`/index.html` | `200 text/html` (444 B) |
| `GET /images`（SPA 深链路） | `200 text/html` → history 回退生效 |
| `GET /assets/index-BGeOqOmG.js` | `200 application/javascript` (1,255,966 B) → 静态产物 MIME 正确 |
| `GET /favicon.ico` | `200 text/html`（回退，非 404，见上表） |
| `WS /ws/logs?filter=dockermgr-frontend&stream=stdout&tail=5` | 收到**真实日志行**（nginx access log），证明 `/ws/` 升级与后端线程化读取链路上线可用 |
| `WS /ws/exec?container=<cid>` | 收到 shell 提示符帧 `/ # \x1b[6n`，证明 exec/tty 链路可用 |

**部署可复现性（全新 clone）结论**：**基本成立**。`frontend/package-lock.json` 已跟踪 + `Dockerfile:4-5` 用 `npm ci`（而非 `npm install`）；`backend/uv.lock` 已跟踪 + `uv sync --frozen --no-install-project`；`.env.example` 提供了 `IMAGE_MIRRORS` 的默认兜底，`config.py:6,15-19` 也有代码级默认值（`DEFAULT_IMAGE_MIRRORS`），`docker-compose.yml:14` 还有 `:-` 兜底 —— **三层默认值齐备，无「必须手工配 .env 才能起」的硬依赖**。唯一可复现性缺口见上表第 2 行（缺 `.dockerignore`）。

---

## 必须独立核实的已知事实 — 结论

| # | 已知事实 | 我的独立核实结果 | 严重度 / file:line |
|:--:|------|------|------|
| 1 | README「未完成项」自述：`.gitignore` 忽略 `uv.lock`，导致全新 `git clone` 构建失败；前后端处理不一致 | **该问题在本审查范围内已被修复，且修复就在被审 diff 的最后一个 commit**。核实链：`.gitignore:5-8` 现为注释「uv.lock is deliberately COMMITTED, not ignored」，原 `uv.lock` 忽略行已在 diff 中删除（`-uv.lock`）；`git ls-files --error-unmatch backend/uv.lock` 返回成功；`git log --diff-filter=A -- backend/uv.lock` = `8149029`（本范围 commit）；`git check-ignore -v backend/uv.lock` 无输出。**对前端/整体部署链路的影响面：0** —— `backend/Dockerfile:7-11` 的 `COPY pyproject.toml uv.lock ./` + `uv sync --frozen` 在全新 clone 上可满足；前端链路本就一致（`package-lock.json` 跟踪 + `npm ci`）。**残留问题不是代码而是文档**：`docs/epics/docker-manager-v1/README.md:74` 仍标「待修复」，与同 commit 的 `.gitignore` 自相矛盾（见 §5 第 4 行） | 🟢（文档未同步） / `docs/epics/docker-manager-v1/README.md:74`、`.gitignore:5-8`、`backend/uv.lock` |
| 2 | plan Task 11 计划预审记 Fail（「打包三个独立视图」未拆成三个独立文件） | **确认属实，作为记录项**：`ImagesView.vue`/`NetworksView.vue`/`VolumesView.vue` 三个文件确实存在且各自独立（三份独立文件已交付），但预审判定针对的是「打包」这一动作的拆分口径。功能覆盖完整，无行为影响 | 🟢（记录项，非新发现） / `plan.md:926-961`；`docs/epics/docker-manager-v1/README.md:76,94` |
| 3 | R1–R5 五轮修复中 R2/R3/R4/R5 落在我的范围 | 逐轮核实（详见下表），**五轮修复本身都真实生效**；其中 R4 触发范围偏差（§1 B 蔓延）、R2/R3/R5 的实现正确且副作用可控 | 见下表 |

**R2–R5 修复正确性与副作用核查**

| 轮次 | 修复内容 | 我的核查结论 |
|:--:|------|------|
| R2 | UI 重设计 + 端口按行解析 | 正确。后端 `_format_ports`（`containers.py:29-50`）逐绑定渲染 + `_append_unique` 去重 IPv4/IPv6 重复；前端 `splitPorts` + `.c-port{white-space:nowrap}`（`ContainersView.vue:213-218,336-339`）保证「一段映射不换行」。**副作用**：契约变成「后端拼好字符串、前端再拆」的隐式耦合（§2 判定 🟢 D8） |
| R3 | 镜像源降级 + nginx 超时 | 正确。`images.py:130-174` 先直连、仅在「注册表不可达」标记命中时才走镜像源（`_UNREACHABLE_MARKERS`，且非 Hub 引用直接 502 并给出中文原因），成功后 `img.tag(canonical, tag)` 回打原名并删除临时标签 —— 与 README:80 的自述一致；nginx `:12-13` 3600s、`:22` `client_max_body_size 0` 已实测存在于仓库配置。**副作用**：新增对外接口 `/api/images/pull/mirrors` 与配置面（§1 B2）；`.env` 覆盖口径与文档不符（§5 G3） |
| R4 | 从镜像运行容器 + 预设 | 实现正确（`containers.py:102-151` 对 404/409 做了可读映射，`run_spec.py` 纯函数解析）。**副作用**：落在 spec §7 明确划出 v1.1 的范围（§1 B1，HARD），且该路径的前端超时仍是 30s（§3 E1），与本项目 E2E 的 180s 口径不一致 |
| R5 | 终端复制粘贴（`attachCustomKeyEventHandler` 接管） | 逻辑正确且副作用已被照顾：Ctrl+C 有选区→`copySelection()`+`return false`（既不向 shell 发 `\x03`，又放行浏览器原生 copy 事件作为剪贴板 API 被禁时的兜底，`ContainerTerminal.vue:164-176`）；无选区→`return !ev.shiftKey`（保留 SIGINT，Ctrl+Shift+C 静默）；Ctrl+V→`return false` 交给 xterm 原生 paste（**明确不再手动 paste**，避免 R5 中途踩过的「发送两次」，`:178-187`）；右键→`preventDefault`+`term.paste()`（`:149-154`）。清理路径完整（`:264,277` 成对增删 capture 监听）。**唯一残留**：`copySelection()` 未 await 且失败分支只能提示「复制失败，请手动选中」，属可接受降级 |

---

## OCR 预扫

**未执行（ocr CLI 未配置 LLM 端点）**。经协调者确认：ocr CLI v1.9.2 已安装，但运行时报 `resolve LLM endpoint: no valid LLM endpoint configured` —— `OCR_LLM_URL` / `OCR_LLM_TOKEN` / `OCR_LLM_MODEL`、`~/.opencodereview/config.json`、`ANTHROPIC_*` 均未配置，预扫在派发阶段即失败退出，因此 `docs/epics/docker-manager-v1/ocr/ocr-preview.md` 与 `.json` **确定不会产出**（目录下仅有 `BASE_SHA` 43 B，值 `c689f71a52f9cffb89c80efd706149b3d95307ec`，与本次审查 BASE 一致；以及 `ocr-background.md` 5952 B）。

本报告因此不含「OCR 预扫」验证表，也无法对 ocr 发现做「属实/误报/升级」的逐条判定 —— 这是**输入缺失**，不是本段审查未做：五段审查（Plan alignment / Code quality / Architecture / Testing / Production）已按全量 diff 独立完成，结论不依赖 ocr 预扫。若日后补齐 LLM 端点并产出 `ocr-preview.md/.json`，可按 Base SHA 一致性并入本报告的发现清单按同等级处理。

---

## 亮点

1. **WS 阻塞问题被真正修对**：`backend/app/routers/ws.py:88-124` 把 `logs(follow=True)` 的阻塞迭代放进工作线程、用 `call_soon_threadsafe` 回推事件循环，主协程用 `asyncio.wait_for(ws.receive(), timeout=0.5)` 保持可断连 —— 这是「不冻死整个服务」的正确解法，且 `docs/development.md:154-158` 把根因写进了开发文档。
2. **前端卸载清理无死角**：三处长生命周期资源的清理都成对（`App.vue:100-102`、`ContainerLogs.vue:135-142`、`ContainerTerminal.vue:275-288`），`disposed` 标志还兜住了异步尾部；`ContainerTerminal.vue:75-78` 对「抽屉动画期 clientWidth=0 时 fit 出垃圾行列数」做了显式防护并用 ResizeObserver 补位 —— 这是真机上会被忽略的坑。
3. **TS 类型纪律**：全仓仅官方 shim 一处 `any`，`strict`+`noUnusedLocals` 全开且 `vue-tsc -b` 实测通过；类型集中在 `api/index.ts`，组件不自己拼后端类型。
4. **契约细节处理到位**：镜像导出用直链而非 blob（前端零内存占用，与 spec D6 流式意图一致）；terminal 与 logs 的 WS URL 都从 `location` 派生（无硬编码端口，开发代理/生产反代两种拓扑都能用）；exec 协议在 README:158-165 写明了「服务端原始字节 / 客户端 JSON 控制帧」并保留纯文本帧兼容。
5. **排障文档是真踩过的坑**（不是想象出来的）：`docs/troubleshooting.md` 里 nginx 60s→504、`client_max_body_size`→413、`Container` 无 `.state`、`SocketIO` 无 `settimeout`、`exec_create` 的 `stdin` 默认 False、`window.getSelection()` 对 xterm 永远为空 —— 六条都能在代码/diff 里找到对应修改，属于高价值的知识沉淀。
6. **单文件即可验证的默认值兜底**：`IMAGE_MIRRORS` 有「代码默认（`config.py:6`）+ compose `:-` 兜底（`docker-compose.yml:14`）+ `.env.example` 示例」三层，缺 `.env` 也能起。

---

## 存疑 / 未能验证项

| # | 项 | 原因与影响 |
|:--:|------|------|
| 1 | 浏览器侧脚本（`ui_verify.py` / `ui_clipboard_test.py`）本次**未实际执行** | Playwright 需要 `asyncio.create_subprocess_exec` 拉起 node driver，被本会话沙箱以命名管道限制拒绝（`PermissionError [WinError 5]`）；本会话审批已禁用且我为子代理，无法升级权限。因此 §4 中「断言强度/假阴性通道」的结论来自**逐行读码 + 与已修正的假阴性教训对照**，不是执行结果。建议由有权限的会话补跑一次并核对退出码（e2e 的退出码问题见 §4 F1） |
| 2 | 容器内 nginx.conf 是否与仓库 `frontend/nginx.conf` 完全一致 | `docker exec dockermgr-frontend cat ...` 被 docker npipe 权限拒绝。间接证据：线上 `/ws/` 与 `/api/` 均可用、SPA 回退可用、静态 MIME 正确，说明关键指令在位；但 `proxy_read_timeout 3600s` / `client_max_body_size 0` 无法逐字比对（未跑过长耗时拉取或 >1MB 上传） |
| 3 | 「停止中的容器点『查看日志』」的真实表现 | 本机当前**没有非 running 容器**（`?all=true` 实测 `not running: []`），无法做端到端复现。结论基于两侧代码：`ws.py:17-20` 只在 `containers.list()`（running）中匹配 → 必然找不到；`ContainerLogs.vue:100-102` 会把 `{"error": "no container"}` 当日志行渲染。建议造一个已停止容器复核 |
| 4 | `docker compose up -d --build` 在**本机带 node_modules 的上下文**下是否真的会构建失败 | 无 docker 管道权限，且不宜为此重建用户正在运行的两个容器。§5 G2 的结论按「已确定的事实」（无 `.dockerignore`、上下文 118.2 MB、`COPY . .` 在 `npm ci` 之后）表述，未断言必然失败，只断言**不可复现 + 会合并宿主平台二进制** |
| 5 | 「建容器/commit 超过 30s」的具体阈值 | 未在真机上用大镜像制造 >30s 的 `docker run` 来复现前端超时。结论依据是**项目自身 E2E 给这两个调用 120s/180s** 这一内部矛盾（`e2e_verify.py:156,308` vs `api/index.ts:51`） |
| 6 | `docs/epics/docker-manager-v1/README.md:102` 的「0 页面错误 / 0 控制台错误 / 0 失败请求」 | 该结论依赖 Playwright 执行（见第 1 项），本次无法复核。另外该断言本身在脚本里不是门禁（§4 F3），属「人眼读输出」级证据 |
| 7 | epic README 的轮次计数 | `docs/epics/docker-manager-v1/README.md:21` 写「4 轮修复」，下表实际是 R1–R5 五轮（`:25-29`）；`docs/troubleshooting.md:21` 亦写「4 轮」。文档内部不一致（🟢 级，未单列发现行） |

---

## 结论汇总

| 段 | Verdict | 关键结论 |
|----|:--:|---------|
| 1 Plan alignment | ⚠️ | 闭环功能全覆盖；1 条 HARD 范围蔓延（从镜像运行容器，落在 spec §7 明确排除项）、1 条 spec 硬性范围内的缺失（暂停/恢复无界面入口）、2 条部分缺失（断线重连、停止容器日志） |
| 2 Code quality | ⚠️ | TS 严格、清理完整、边界处理（中文文件名实测无碍）；扣分在两处**错误反馈不完整**（WS 控制帧被当日志渲染、下载类假成功提示）与错误提示三处重复实现 |
| 3 Architecture | ⚠️ | 反代/超时/体积/静态产物/WS 链路实测全部可用；需决策：创建/commit 的 30s 超时偏短、`vue-tsc -b` 产出的 `vite.config.js` 遮蔽 `.ts` 配置 |
| 4 Testing | ⚠️ | 断言有真机价值（stty/tar/manifest/selection/SIGINT）；但 E2E 脚本无退出码、WS 日志可假阳性、UI 脚本判定面过窄、浏览器脚本环境依赖未声明且换机器会跑挂、前端零单测 |
| 5 Production | ⚠️ | spec §6 的 127.0.0.1 绑定与后端不暴露**合规**（HARD 要求满足）；真机实测可用；缺 `.dockerignore` 与「文档承诺可改、实际写死的 3 个环境变量」是主要扣分项；`uv.lock` 未完成项**已修复**（看板未同步） |

**计数**：🔴 0 · 🟡 13 · 🟢 25（另含 1 条 HARD 合规确认、1 条已修复确认、1 条记录项；段 1 的 C2 与段 5 的首行不计入严重度计数）
