# CDM Phase 4.6 第三轮（rd3）合并复核报告 — docker-manager-v1

> Epic：`docker-manager-v1`
> 审查对象：**工作区未提交的第二轮修复批次**（提交基线 `HEAD = 8149029`；全部改动为 working-tree 变更 + 未跟踪新文件）
> 审查范围：`git status --short --untracked-files=all` 全量 54 项（28 个已跟踪文件修改 + 26 个未跟踪新文件），**不是抽查**
> 审查方式：**rd3 合并复核者**（只读产品代码；临时探针全部落在仓库外 `D:\桌面\测试\.rd3-probes\`）；另派两路隔离子代理复核前端透镜与脚本/部署透镜
> 模板：`C:\Users\n25893\.dsh\skills\cdm-code-review\code-reviewer.md`（五段结构）
> OCR 预扫：未执行（沿用 rd1/rd2 结论：ocr CLI 未配置 LLM 端点）
> 审查时间：2026-09-14

**证据纪律**：本报告不采信注释、commit message、报告自述或协调者转述。每条判定都附「我实跑的命令 + 真实输出」或「我实际读到的 `文件:行号`」。凡未独立验证者，一律在 §5 明示。

**本轮对产品代码的唯一触碰**：B2 变异测试与 B7 变异测试需要临时改写 `backend/app/routers/ws.py` 与 `backend/app/routers/containers.py`，两者均在**同一命令内**先做 SHA256 备份、跑完立即还原、并校验还原后哈希与改前**逐字节一致**（见 §4.1/§4.3）。审查结束时 `git status --short --untracked-files=all` 与本轮开始时一致。

---

## 1. 审查结论

**Verdict：⚠️ CONDITIONAL PASS（不判 ❌，但需协调者就 3 项做决定后重跑一轮轻量复核）**

| 段 | 结论 | 关键发现 |
|----|:--:|---------|
| Plan alignment | ✅ | 第二轮修复**未越界**：全部落在 rd2 发现范围内 + 协调者文档回写；`spec.md`/`scope.md` 回写与 F12 自洽；无新增范围蔓延。余 1 项（L-01）与 1 项看板计数自相矛盾（RD3-07） |
| Code quality | ⚠️ | 无未关闭 🔴。2 条 🟡：`cont.logs()` 阻塞事件循环（RD3-02，实测 1.52s）、TTY 容器日志被打成「一字符一行」（RD3-03，实测复现）。判别字段三层一致**已闭环** |
| Architecture | ⚠️ | 判别字段三层契约（后端发 / 前端判 / E2E 认）实测一致，设计收口良好；残留 2 项记录在案的取舍（L-11 DNS rebinding、L-12 端口无关放行）**仍未在文档中披露其安全含义** |
| Testing | ⚠️ | 变异测试证实 B2/B7 真能失败（含我自做 3 个变异体）；**但 `staging_dir` fixture 在正常机器上必然报错**（RD3-01，实测 `ValueError: staging_dir did not yield a value`）→ CI 上该文件 6 个用例全 ERROR |
| Production | ⚠️ | 线上栈**已确认是修复后代码**（卷创建 422→200、跨站 403、nginx 307 保留 `:8088`、WS 帧带判别字段），E2E 我独立复跑 **18/18 exit 0** 且**零残留**；但后端镜像仍未重建、线上修复是 `docker cp` 临时态（RD3-09），文档两条排障条目缺失（L-10/L-16 PARTIAL） |

**为什么不是 ✅ APPROVED**：存在 1 条会**在正常机器/CI 上直接打红测试套件**的缺陷（RD3-01），以及 1 条**真实可复现**的事件循环阻塞（RD3-02）与 1 条**真实可复现**的日志渲染缺陷（RD3-03）。
**为什么不是 ❌ NEEDS FIXES**：三项都不是「修复方向错误」，rd2 的 27 条主干修复经独立取证确实成立；RD3-01 与 RD3-03 均为**上一轮遗漏**、RD3-02 是本轮新查出，三者修法明确且都不改变对外契约。

---

## 2. rd2 发现关闭判定表

### 2.0 编号口径说明（先对齐计数）

协调者口径的「rd2 新增 **27 条**发现」= **后端 10 条（N-01…N-10）+ 前端 9 条（N-01…N-09）+ 计划对齐 8 条 🟡（L-02/L-03/L-06/L-07/L-08/L-10/L-11/L-14）**（见 `docs/epics/docker-manager-v1/README.md:20` 与 `test-review/code-review-report.md:284`）。计划对齐透镜另有 9 条 🟢（L-01/L-04/L-05/L-09/L-12/L-13/L-15/L-16/L-17），不在这 27 之内。

本表**逐条覆盖全部 36 条**（10 + 9 + 17），以免口径差异掩盖未关闭项。另复核了 `code-review-report.md:305-307` 记录的 3 条「上轮报告自身错误」更正（R-L1…R-L3）。

### 2.1 后端透镜（`rd2/review-backend.md`）

| 编号 | 级别 | 判定 | 决定性证据 | `文件:行号` |
|:--:|:--:|:--:|---|---|
| **N-01** 批处理回归测试无牙 | 🟡 HARD | ✅ **CLOSED** | **我自做变异**：删掉 `timer.start()` → `1 failed, 4 passed`，`batching: 0 lines delivered in 0 frames`；还原后哈希 `A9CEA43E…F6FF3A` 逐字节一致。正常态：`batching: 600 lines delivered in 19 frames while the stream was still open`。断言确在**流仍开着**时取样（`:188` `stream.produced.wait()` → `:207` `frames_now > 0` / `:212` `len(lines_now) == 600` / `:217` `frames_now*3 < 600`） | `backend/tests/test_ws_logs.py:24-59`（长命流 mock）、`:141-227`（用例本体）；`backend/app/routers/ws.py:187-188` |
| **N-02** 收尾竞态（flusher 关闭时也 flush） | 🟢 | ✅ **CLOSED** | 读码：`while not finished.wait(INTERVAL)` 在 set 后**立即退出、不再 flush**（`:184-185`）；`finally` 先 `finished.set()` → `is_alive()` 守卫下 `join(timeout=0.5)` → 只调一次 `flush()`（`:207-210`）→ 尾部**单一 owner**。且 `flush()` 在 `not pending and not dropped` 时直接 return，不会发空帧（`:158-159`）。活体佐证：`/ws/logs?tail=5` 收到 1 帧（5 行）后 `recv TIMEOUT`，**无空帧**；长命流用例的 `== 600` 精确计数可捕获任何重复行 | `ws.py:150-173,184-185,201-211` |
| **N-03** `0.0.0.0` 在本地白名单 | 🟢 | ✅ **CLOSED** | `LOCAL_ORIGIN_HOSTS = {"localhost","127.0.0.1","::1","[::1]"}`，`0.0.0.0` 已移出；docstring 说明理由；两个方向都被测试锁定：`http://0.0.0.0:8088` vs Host `127.0.0.1:8088` → False；vs Host `0.0.0.0:8088` → True | `backend/app/services/security.py:19-24,32`；`backend/tests/test_security.py:64-79` |
| **N-04** 非 404 故障零帧静默关闭 | 🟢 | ✅ **CLOSED** | 三类分开：`NotFound`→`no such container: X`；`APIError`→404 同类、否则 `docker 守护进程错误：<安全原因>`；`DockerException`→`无法连接 docker 守护进程：…`。**我实测活体**：`created` 态与 `exited` 态容器上 `/ws/exec` 均收到 `{"dockermgr":"error","error":"docker 守护进程错误：409 Client Error … (\"container … is not running\")"}`（非零帧）。异常层级我实测正确：`NotFound ⊂ APIError ⊂ DockerException`，故 except 顺序无法被遮蔽。`_safe_reason` 兜底 `type(e).__name__`，并有 `_UnprintableError` 用例 | `ws.py:37-48,293-313`；`test_endpoints_coverage.py:294-398` |
| **N-05** 丢弃标记行与空行黏连 | 🟢 | ✅ **CLOSED（余一条注释不准，见 RD3-12）** | 标记行现在是 `lines` 的**独立元素**，不再与 `pending` 首元素拼接（`:161-170`） | `ws.py:161-172` |
| **N-06** `clear_tmp_dir` 静默吞错 | 🟢 | ✅ **CLOSED** | `except OSError: logger.warning("failed to clear staging entry %s", p, exc_info=True)`；同时把子目录纳入清理（`shutil.rmtree`） | `backend/app/services/files.py:17-33` |
| **N-07** 修复未部署（线上仍旧构建） | 🟡 HARD | ✅ **CLOSED（残留 RD3-09）** | 我独立实测线上：`POST /api/volumes {"name":…}` → **200**（rd2 时 422）；`Origin: http://evil.example` → **403**；`curl -i /api/containers/` → `location: http://127.0.0.1:8088/api/containers`（端口保留）；`/ws/logs` 失败帧 = `{"dockermgr":"error","error":"no container"}`。真机 E2E 我复跑 **18/18 passed，EXITCODE=0** | 见 §4.4 |
| **N-08** 明文旁路（无 Origin 一律放行） | 🟢 | ✅ **CLOSED（记录为取舍）** | 策略已在模块 docstring 第 1 条明确写出「No Origin → allow」及其理由（非浏览器客户端不是威胁模型），取舍已披露 | `security.py:16-18,56-57` |
| **N-09** 本地来源判定与端口无关 | 🟢 | ⚠️ **PARTIAL（接受为已知取舍）** | `http://127.0.0.1:<任意端口>` 仍放行（语义未变）。docstring 只说「whichever port the browser used to reach it」，**未点出安全含义**（本机任意端口的页面可驱动 WS），也**无测试锁定该放宽**。rd2 建议的「明确写出该放宽及其理由」只做了一半 | `security.py:19-24,58-59` |
| **N-10** `staging_dir` 的 `return` 路径未验证 | 🟢 → **🟡** | ❌ **NOT CLOSED（升级为新发现 RD3-01）** | 未修，且**实测会直接打红**：该 fixture 含 `yield`，故是生成器函数；`mktemp()` 成功时走 `return`，pytest 报 `ValueError: staging_dir did not yield a value`。本沙箱因 `%TEMP%` 被拒而恰好走 `except` 分支，**所以「124 passed」是本沙箱专属结论** | `backend/tests/test_files_api.py:15-38` |

### 2.2 前端透镜（`rd2/review-frontend-deploy.md`）

| 编号 | 级别 | 判定 | 决定性证据 | `文件:行号` |
|:--:|:--:|:--:|---|---|
| **N-01** 退避成功后不复位 | 🟡 | ✅ **CLOSED** | 两个组件都在 `ws.onopen` 内复位：`retryDelay = RETRY_BASE`，且注释与位置均正确（在「连接成功」分支内，不是文件任意处）；`scheduleRetry` 仍为 `Math.min(retryDelay*2, RETRY_MAX)` | `ContainerLogs.vue:204-213,283`；`ContainerTerminal.vue:240-247` |
| **N-02** 预检无超时无取消 | 🟡 HARD | ✅ **CLOSED** | `PREFLIGHT_TIMEOUT = 30000`；`new AbortController()` + `window.setTimeout(… ctrl.abort(), 30000)`；`fetch(url, { signal: ctrl.signal })`；失败路径 `return false`（不抛）；`finally { window.clearTimeout(timer) }`。两个消费方均以 `finally` 清 loading：`ImagesView` 用 `exportingId.value = ''`、`FileCopyDrawer` 用 `downloading.value = false`，故提前 `return false` 不会卡住按钮。超时文案为可读中文而非裸 DOMException | `utils/download.ts:12,50-80`；`ImagesView.vue:181-191`；`FileCopyDrawer.vue:119-128` |
| **N-03** paused 容器仍可进终端 | 🟡 | ✅ **CLOSED** | `canOpenTerminal(row) => row.state === 'running'`，菜单项 `:disabled="!canOpenTerminal(row)"`，并带 `terminalHint` 文案（paused → 「容器已暂停，请先恢复」）。**有意保留** 查看日志/文件拷贝为可用（读日志缓冲与文件系统，不需要进程），理由写在代码注释里——合理，且 `/ws/logs` 对已退出容器实测可用 | `ContainersView.vue:120-134,336-357` |
| **N-04** `{"error":…}` JSON 日志行被吞 | 🟢 | ✅ **CLOSED** | 后端发出带判别字段的帧；前端 `if (frame.dockermgr !== 'error') return null`。**我实跑真值表（机械导入真源码）**：17 个用例中「数据帧被误判为控制帧」= **0**，其中旧帧形 `{"error":"no container"}`、`{"level":"error","error":"ECONNREFUSED","msg":"upstream"}`、`{"error":"boom","msg":"db down"}`、批量行、数组帧、空 error、非字符串 error 全部 → `null` | `utils/ws.ts:34-52`；`ws.py:29,34`。真值表见 §4.5 |
| **N-05** 预检只校验状态行 | 🟢 | ✅ **CLOSED（记录为取舍）** | 修法不是「消除」而是**显式记录**：`download.ts:36-44` 以 `KNOWN LIMIT:` 写明「daemon 在 200 之后才失败仍会到达浏览器为截断 tar」，并解释为何不 drain 一整个 chunk（会破坏流式设计），且说明 chunked 下无法用 `Content-Length` 做完整性校验。取舍已可见、可复现、有理由 | `utils/download.ts:36-44` |
| **N-06** 重连重放 `tail` 刷屏 | 🟢 | ✅ **CLOSED（记录为取舍）** | 行为未变（重连仍是新的 `docker logs --tail=N`），但已：① 代码注释标注 `KNOWN TRADEOFF (N-06)` 并给出为何不缩小 tail 的理由；② **视图内新增边界标记行** `... 连接已断开，正在重连（可能重复最近若干行）...`，让用户能看出重复段的起点 | `ContainerLogs.vue:272-279` |
| **N-07** 注释把 120s 预算归因错 | 🟢 | ✅ **CLOSED** | 新注释归因**准确**：180s 归 `POST /api/containers`（缺失镜像会先拉取）、120s 归 `GET /api/images/{id}/save`，并明说 `commit` 在脚本里仍走默认 30s，故前端 300s 是「安全网而非实测预算」 | `api/index.ts:57-69` |
| **N-08** `${VAR:-default}` 使「留空关闭」失效 | 🟡 HARD | ✅ **CLOSED（但引入文档新缺陷 RD3-05）** | `deploy/docker-compose.yml:18` 已改为单横线 `${IMAGE_MIRRORS-docker.m.daocloud.io,docker.1panel.live}`，注释解释了 `:-` 与 `-` 的差别。**我实测**：`IMAGE_MIRRORS=`（空值）→ `docker compose config` 得 `IMAGE_MIRRORS: ""`（不再回落到默认） | `deploy/docker-compose.yml:13-18`；§4.6 |
| **N-09** 按钮无在途操作保护 | 🟢 | ✅ **CLOSED** | 启动/停止/暂停/恢复/重启五个动作按钮全部加了 `:disabled="isBusy(row) || …"` 在途保护 | `ContainersView.vue:70,79,94,105,111` |

### 2.3 计划对齐透镜（`rd2/review-plan-alignment.md`）— L-01…L-17

| 编号 | 级别 | 判定 | 决定性证据 | `文件:行号` |
|:--:|:--:|:--:|---|---|
| **L-01** `scope.md` 验收标准仍写 F1-F10 | 🟢 | ❌ **NOT CLOSED（接受为已知取舍）** | `scope.md:99` 仍是「F1-F10 各动作均可经界面触发」，未含新增 F12；而 F12 已补入同一文件的 `:35` 与补记 `:37`。低危（F12 已由 §5 澄清段与 README R4 覆盖），但文件内自相矛盾仍在 | `scope.md:35,37,99` |
| **L-02** `deployment.md` compose v1 无证据断言 | 🟡 | ✅ **CLOSED** | 旧的「v1 同样能运行这个文件」已删；新表述为「v1 的 `docker-compose` 已 EOL，**未做兼容性验证**；本文命令与语法一律以 v2 为准」——把无证据断言换成了明示免责。`deploy/docker-compose.yml:1` 确无 `version:` 键（与「未验证」自洽） | `docs/deployment.md:34` |
| **L-03** epic README 看板未同步（C-22 复发） | 🟡 | ✅ **CLOSED** | `README.md:77` 已由「待修复」改为「**已修复（`8149029`）**」；`:80` 记录第二轮关闭 C-15/C-17/C-22；`:106` 已写 **124 passed**；`:21` 新增「修复轮 2」阶段行 | `docs/epics/docker-manager-v1/README.md:20-21,77-81,106` |
| **L-04** 根 README 测试数过期 | 🟢 | ✅ **CLOSED** | 我实测后端 `124 passed`，`README.md:182` 现写「124 个 pytest 用例」 | `README.md:182` |
| **L-05** `requirements-verify.txt` 无文档引用 | 🟢 | ✅ **CLOSED** | 四份文档全部补上引用，我逐一确认命中 | `README.md:235`、`docs/development.md:130`、`docs/deployment.md:243`、`docs/troubleshooting.md:265` |
| **L-06** 错误帧无判别字段 | 🟡 | ✅ **CLOSED** | 三层我**逐层实测**：后端发 `{"dockermgr":"error","error":…}`（活体收到）；前端真源码真值表旧帧形 → `null`（不再吞）；`e2e_verify.py:282` 要求 `obj.get("dockermgr") != "error"` → 否则视作普通文本。后端全仓 grep 确认**只有** `ws.py:34` 一处发错误帧，**旧帧形不再发出** | `ws.py:29,34`；`utils/ws.ts:47-51`；`e2e_verify.py:261-287` |
| **L-07** 5 个语义判定不进退出码 | 🟡 | ✅ **CLOSED** | `record()` 是 `failures` 的**唯一**写入者，`judged=True` 时 `not ok` 即入表；`exit_code()` = `0 if not failures else 1`；5 条语义判定（pageerror / console error / requestfailed / port breaks + 4 条语义 `record`）全部经 `record()` 落表。子代理以真源码 + 桩浏览器跑 8 个场景，4 个信号均能把退出码从 0 翻到 1 | `scripts/ui_verify.py:61,64-68,71-77,251-263` |
| **L-08** run-dialog 端口检查恒为空集 | 🟡 | ✅ **CLOSED** | 旧的 `.c-port` 弹窗查法已删；`note_port_breaks` 现在**只**在容器页调用（`.c-port` 确实只存在于 `ContainersView.vue:49`），并在 docstring 写明「弹窗里没有 chip 元素，查了只会恒空恒过」。替换为真实选择器 `.el-dialog textarea` 可见性判定（`RunContainerDialog.vue:42/56/67` 确有 textarea，端口是第一个），且该项**真能失败**（子代理场景 H：textarea 不可见 → exit 1） | `ui_verify.py:106-117,129,149-156` |
| **L-09** 单行空日志被丢弃 | 🟢 | ⚠️ **NOT CLOSED（接受为已知取舍）** | `appendChunk` 首行 `if (paused.value \|\| !chunk) return` → 空 chunk 仍被丢弃，故「容器只打印一个空行」时视图无输出。影响极低，且丢弃空帧本身是想要的行为 | `ContainerLogs.vue:176-179` |
| **L-10** 跨站守卫与「前置认证反代」冲突未文档化 | 🟡 HARD | ⚠️ **PARTIAL** | `deployment.md:154-162` **已补**：写明守卫规则（Origin 非本地且不等于本次 `Host` → HTTP 403 / WS 1008）、「必须保留客户端 Host」、nginx（`proxy_set_header Host $http_host`，并提示 `$host` 会丢端口）与 Apache（`ProxyPreserveHost On`）样例。❌ **但 rd2 明确要求的 `troubleshooting.md` 条目不存在**：全文件无 `Host`/`403`/`1008`/`http_host` 相关排障条目（`diff` 只动了 2 处，均与本题无关） | `docs/deployment.md:154-162`；`docs/troubleshooting.md`（缺） |
| **L-11** `Origin host == Host` 构成 DNS rebinding 通道 | 🟡 | ⚠️ **NOT CLOSED（接受为已知取舍）** | 该分支仍在（`is_same_site` 末行）。我给的可利用推演：攻击者令 `evil.com` 解析到 `127.0.0.1` → 页面 Origin `http://evil.com:8088` 与 Host `evil.com:8088` 相等 → 放行。**安全含义仍未在 `security.py` docstring 或部署文档中披露**（docstring 只说该分支「covers an operator who deliberately exposes the panel under another hostname」）。协调者已在 `code-review-report.md:303` 记为已知取舍——**接受，但建议补一句风险披露** | `security.py:25-27,60-61` |
| **L-12** 放行任意端口的 127.0.0.1 源 | 🟢 | ⚠️ **NOT CLOSED（接受为已知取舍）** | 与后端 N-09 同一条：语义未变，docstring 提及放宽但未述安全含义，无测试锁定 | `security.py:58-59` |
| **L-13** WS 守卫分散在各 handler 内 | 🟢 | ⚠️ **NOT CLOSED（接受为已知取舍）** | 两处各自内联 6 行（`ws.py:111-116`、`:256-261`），未抽公共依赖/函数。**功能上两处都正确且都在 `accept()` 之前**；但「新增第三个 WS 端点忘了守卫」的风险仍在（HTTP 中间件不覆盖 websocket scope），且 `_send_error_frame` 已抽出、守卫却未抽，风格不一致 | `ws.py:111-116,256-261` |
| **L-14** console warning 判为硬失败 | 🟡 | ✅ **CLOSED** | 警告单独 `record(..., judged=False)`：**仍被收集并打印**（计数 + 明细，`:235-237`），但**不**进 `failures`，不影响退出码。保留信号、移除误判门禁，方向正确。副作用见 RD3-04 | `ui_verify.py:53-54,87-94,235-237,255-259` |
| **L-15** `requestfailed` 可能把导航/取消误判为失败 | 🟢 | ⚠️ **NOT CLOSED（接受为已知取舍，未验证）** | 判定逻辑未加过滤（无 `ERR_ABORTED` 白名单）。因 Playwright 在本沙箱被拒，**我无法实测该误判是否真会发生**——与 rd2 同样留作未验证 | `ui_verify.py:96-99,260-261` |
| **L-16** nginx 修复未部署 + 无排障条目 | 🟢 | ⚠️ **PARTIAL** | ✅ nginx 部分**实测生效**：`curl -i http://127.0.0.1:8088/api/containers/` → `location: http://127.0.0.1:8088/api/containers`（端口保留），且 `nginx.conf:36,48` 两个 location 都是 `$http_host`。❌ **`troubleshooting.md` 的「307 丢端口」条目不存在** | `frontend/nginx.conf:36,48`；`docs/troubleshooting.md`（缺） |
| **L-17** `.dockerignore` 死条目 | 🟢 | ✅ **CLOSED** | `scripts/ui-shots` 已删；现列表无该路径（第 22 行是 `*.log`）。且该条目本就无害（构建上下文是 `../frontend`，`scripts/…` 永远进不去） | `frontend/.dockerignore` |

### 2.4 上一轮报告自身错误的更正（R-L1…R-L3）复核

| 编号 | 判定 | 证据 |
|:--:|:--:|---|
| R-L1（`troubleshooting.md:21` 被误称写「4 轮」） | ✅ 更正成立 | `troubleshooting.md:21` 实为 `## 镜像相关`，与该断言无关 |
| R-L2（计数「21，去重后」应为 20） | ✅ 更正成立 | `code-review-report.md:30` 表内确实 20 条 |
| R-L3（rd2 报告 R-L3） | ✅ 无异议 | 未发现该更正本身引入新错误 |
| — | ⚠️ 新增计数矛盾 | 见 **RD3-07**：`code-review-report.md:284` 写「27 条，其中 **3** 条 HARD」，epic `README.md:20` 写「**4** 条 HARD」，而 §2.4 表内实际标 HARD 的是 **5** 行（N-01后端/N-07后端/N-02前端/N-08部署/L-10） |

### 2.5 判定汇总

| 判定 | 条数 | 编号 |
|:--:|:--:|---|
| ✅ CLOSED | **26** | 后端 N-01…N-08（8）、前端 N-01…N-09（9）、L-02/L-03/L-04/L-05/L-06/L-07/L-08/L-14/L-17（9） |
| ⚠️ PARTIAL | **3** | 后端 N-09、L-10、L-16 |
| ❌ NOT CLOSED | **7**（其中 4 条已在协调者口径中记为「已知取舍」） | 后端 N-10（升级为 RD3-01）、L-01、L-09、L-11、L-12、L-13、L-15 |
| **NEW DEFECT（由修复批次引入）** | **2** | 前端 N-08 的文档副作用 RD3-05；L-14 的副作用 RD3-04 |

> 与协调者口径的差异：协调者把后端 N-09/前端 N-04 等 🟢 项标为「第二轮处理可低成本修项，其余如实记录为已知取舍」（`code-review-report.md:303`）。我**逐条核对后同意多数**，但**不认同把 N-10 留在「已知取舍」**——它不是取舍，是**在正常机器上必然报错**（RD3-01）。

---

## 3. 五段审查

### 3.1 Plan alignment ✅

- **未越界**：第二轮全部改动都能对应到 rd2 发现（判别字段、退避复位、预检超时、paused 禁终端、在途保护、exec 错误分类、端点覆盖、`ui_verify` 门禁真实性、`-` 单横线）或协调者的文档回写（`scope.md` F12、`spec.md` §4/§7 澄清、README/deployment/development/troubleshooting）。
- **回写自洽**：`spec.md:83` 改为「容器 列表/详情 / 创建（从镜像运行）/ 启停 / 暂停 / 删除」，`spec.md:132` 新增澄清段把「从镜像运行容器」明确划入 v1，与 `scope.md:35` 的 F12 行、`scope.md:37` 的补记互不矛盾。**未发现新的范围蔓延**（R4 的 F12 是用户明确提出，已有来历记录）。
- **无「看似实现实则不符 spec 意图」**：我核对了 spec §6 的「消息节流」要求 ↔ `LOG_FLUSH_INTERVAL=0.1` + 有界缓冲；§D6 的流式导出 ↔ `<a href>` 直链 + 预检取消 body（不把 tar 读进内存）。两者意图一致。
- **残留**：L-01（`scope.md:99` 仍 F1-F10）与本文件的新计数矛盾（RD3-07）。

### 3.2 Code quality ⚠️

**做得好的地方（逐条核实，非客套）**
- 判别字段三层收口在 `utils/ws.ts` 一处判定，两个 WS 组件共用；`isRetryableClose` 的 1000/1008 语义与后端 1000/1008 契约闭合（我实测 `isRetryableClose(1000)=false, 1008=false, 1006=true`）。
- `finally` 纪律统一：`files.py` 的暂存文件、两个组件的 loading 标志、`ws.py` 的 `stop/finished/timer/raw` 收尾，都在 `finally` 里且不吞异常语义。
- `_safe_reason` 的设计理由正确且**必要**：`extract_error` 会调 `str(e)`，docker-py 的 `__str__` 会解引用 HTTP response —— 该路径确实可能二次抛异常，兜底 `type(e).__name__` 让「非 404 故障」仍能出可读帧。

**扣分项**
- **RD3-02 🟡**（本轮新查出）：`cont.logs(...)` 是**阻塞调用，跑在事件循环上**（§4.7 实测阻塞 1.525s）。
- **RD3-03 🟡**（本轮新查出）：批处理循环假设「一次迭代 = 一行」，对 TTY 容器不成立（§4.8 实测一字符一行）。
- **RD3-12 🟢**：`ws.py:17-20` 注释称缓冲为「bounded **drop-oldest**」，但实现是 `pending.clear()` **整批丢弃**（含刚 append 的最新行），语义与注释不符；且 `:161-164` 注释声称标记行「never adds a trailing newline that would render as an empty line」，但当 `pending` 首/末元素为空串时 `"\n".join` 仍会产生首/尾空行。
- **RD3-11 🟢**：`test_endpoints_coverage.py` 部分 mock 形状与真实形态不符（见 §3.4）。

### 3.3 Architecture ⚠️

- **判别字段契约落点正确**：生产者单一（`ws.py:34`，全仓 grep 无第二处），消费者三处（前端 parser、E2E sniffer、单测），且**旧帧形不再发出**——这是本轮质量最高的一处跨层改动。
- **Origin 守卫分层合理**：HTTP 走中间件（`main.py` 的 `UNSAFE_METHODS`），WS 走握手前校验（`ws.py:111`/`:256`，均在 `accept()` 之前），GET/HEAD 有意不拦（无副作用），理由写在 `main.py:16-18`。
- **残留架构风险（记录，非本轮新增）**：
  - L-11/L-12 两条 Origin 放宽的安全含义**未在代码或部署文档披露**；L-11 的 DNS rebinding 通道在「只绑 127.0.0.1」的前提下仍可被 `evil.com → 127.0.0.1` 触发（Origin host == Host 分支）。协调者已记取舍，我建议补一行风险披露即可关闭争议。
  - L-13：WS 守卫两处内联复制，未抽公共层；HTTP 中间件**不覆盖** websocket scope，故新增 WS 端点若忘记守卫将无兜底。
  - RD3-09：线上修复是 `docker cp` 临时态，后端镜像未重建（见 §3.5）。
- **编排/性能**：判别字段不引入额外序列化成本；`flush()` 的锁只覆盖缓冲交换、发送在锁外调度，粒度正确。

### 3.4 Testing ⚠️

**正面（实测）**
- 我的 5 次变异注入中 **4 个被杀死**：改 `ws.py` 删 `timer.start()` → FAIL；改 `containers.py` `remove(force=force)→force=False` → FAIL；改 `list(all=all)→all=False` → FAIL；`test_endpoints_coverage.py` 真实覆盖 rd1 点名的端点。**1 个无法构造出确定性变异体**（见下）。
- 端点覆盖从 14 例增至 **29 例**（27 个 `def test_`，含 3 路 parametrize），我实测覆盖 16 个端点；`test_security.py` 24 例、`test_ws_logs.py` 5 例。
- 我复核了容器页断言的真实性：`remove(force=…)` 与 docker-py 7.2.0 签名一致（`Container.remove(**kwargs)` → `remove_container(force=…)`）；`list(all=…)` 一致；`img.save(named=True)` 一致（真实签名 `save(chunk_size=DEFAULT_DATA_CHUNK_SIZE, named=False)`）；`commit(repository=,tag=)` 一致；`get_archive(path)` 一致；`exec_create/exec_start/exec_resize` 调用与真实签名一致（`exec_resize(exec_id, height=, width=)`，`exec_start(exec_id, tty=, socket=)`）。

**扣分项（重要）**
- **RD3-01 🟡 —— `staging_dir` fixture 在正常机器上必然报错**（§4.2 实测 `ValueError: staging_dir did not yield a value`）。含 `yield` 的函数整体变成生成器函数；`mktemp()` 成功时走 `return`，pytest 的 `call_fixture_func` 先 `next(generator)` → `StopIteration` → `ValueError`（`_pytest/fixtures.py:994-1000`）。后果：**任何 `%TEMP%` 可写的机器（CI/同事机）上 `test_files_api.py` 的 6 个用例全部 ERROR**，C-13/C-14 引以为据的「仓库不被污染」也失去回归保护。本沙箱因 `%TEMP%` 被拒而恰好走 `except` 分支，所以「124 passed」**是本沙箱专属结论**。
- **RD3-06 🟡 —— `e2e_verify.py` 的 exec 往返可被 PTY 回显满足**（§3.4 末）：`token = "EXECOK"+hex` 后发 `echo {token}\n`，随后断言 `token in collected`。TTY 会回显输入行，因此**「回显」本身就含 token** —— 一个没执行任何命令的 shell 也能判 PASS。rd1 的 C-11（同类假绿）只修了 `/ws/logs`，`/ws/exec` 的兄弟被漏掉。对照：`test_ws_exec_resize` 断言 `"43 132" in collected` 是**健全**的（该串不可能出现在 `stty size` 的回显里）。
- **RD3-11 🟢 —— mock 形状与真实形态不符/过于宽松**：① `_Cont` 用 `name = "/web"`，而 docker-py 的 `Container.name` 返回 `attrs['Name'].lstrip('/')`（`models/containers.py:29-34`）—— 真实值**从不带前导斜杠**，该 mock 在断言一条不可能发生的输入（幸而 `lstrip` 幂等，未掩盖缺陷）；② `_Api.exec_create/exec_start` 用 `(*args, **kwargs)`，**形状上无法**发现签名漂移（rd2 §4.2 称其为「已核验的形状」，与实际不符——放宽 `**kwargs` 不等于核验签名）；③ 参数顺序错误（如 `exec_resize` 交换 `height`/`width`）这类缺陷，当前 mock 与断言都抓不到。
- **RD3-01 的连带影响**：`test_ws_logs_blocking.py` 那类高风险回归（事件循环冻结）只在**单文件**层面有牙；`/ws/logs` 的 `cont.logs()` 阻塞（RD3-02）**无任何测试覆盖**——我自建的探针是首个能捕获它的用例。

### 3.5 Production ⚠️

**实测通过项**
- 线上栈**确为修复后代码**（这是 rd2 唯一无法验证的事）：卷创建对象体 200、跨站写 403、nginx 307 保留 `:8088`、WS 失败帧带判别字段、SPA 与三页接口可用。
- **我独立复跑真机 E2E：`18/18 passed，EXITCODE=0`**，含 `File copy` 往返、`commit`、`Image export (82966016 bytes, entries=17, manifest=yes)`、`Run container from image`、`WS /ws/logs`（20 行合并 1 帧）、`WS /ws/exec` 往返、PTY resize（`stty size -> '43 132'`）。
- **零残留**：跑完清点 containers=8 / images=8 / volumes=8，`dockermgr-e2e*`、`rd3-*` 命中数均为 0。
- 中文编码：`ws.send_json` 经 starlette 1.6.0 `json.dumps(..., ensure_ascii=False)`（`starlette/websockets.py:174`），线上帧确为 UTF-8 中文（我先前在 pwsh 里看到的乱码是控制台代码页所致，**非产品缺陷**）。
- `.dockerignore` 覆盖 `vite.config.js`（否则会遮蔽 `.ts` 配置）——切中真实构建陷阱。

**扣分项**
- **RD3-09 🟢 —— 线上修复是临时态**：后端镜像因 daemon 拉不到 `ghcr.io/astral-sh/uv` 未重建，代码以 `docker cp` 送入运行容器；`dockermgr-backend` 容器创建时间 `2026-09-11T01:06`（**从未被重建**），而 `dockermgr-frontend` 为 `2026-09-14T02:02`（已重建）。因此一次 `docker compose up -d`（**不带 `--build`**）会从旧镜像重建后端容器，**静默回退 C-01/C-08 等全部后端修复**，且 compose 无 `image:` 固定、无告警。协调者已在 epic `README.md:81` 记录该状态，但**无任何机制阻止回退**。
- **L-10 / L-16 PARTIAL**：两条 rd2 明确要求的排障条目（「反代后写操作全 403 / 终端 1008」、「307 丢端口」）在 `docs/troubleshooting.md` 中不存在。
- **RD3-04 🟡（门禁真实性）**：`ui_verify.py` 对不入判的 warning 仍打印 `[FAIL]`，于是**同一份输出里可以同时出现 `[FAIL]` 与 `UI verification PASSED` + 退出码 0**，直接违背该文件 `:250` 的自述不变量（「a [FAIL] line can never coexist with exit code 0」）与 `:74` 的 docstring（「printed FAIL => non-zero exit」）。任何 grep `[FAIL]` 的 CI/日志扫描器会报假失败。子代理以真源码实测复现该组合（场景 D）。
- **RD3-05 🟡（文档新缺陷）**：`deployment.md:106-108` 的「关闭镜像源」代码块是 compose YAML 列表语法 `- IMAGE_MIRRORS=`，但它在「§4.1 用 `.env` 覆盖 / §4.2 变量说明」语境下会被自然粘进 `deploy/.env`，而 `docker compose` 会**整体拒绝启动**。**我独立实测**：`failed to read …: line 2: key cannot contain a space`，`EXIT=1`；改 `IMAGE_MIRRORS=`（无横线）→ `IMAGE_MIRRORS: ""`，`EXIT=0`。对照 `troubleshooting.md:38-40` 的同一片段有「编辑 `deploy/docker-compose.yml`」明确标注，故那里不算缺陷 —— 说明写清语境即可。
- **RD3-08 🟢**：`README.md:207` 的代码规模自述（后端 ~1.7k / 前端 ~2.1k 行）与实测不符（`backend/app/*.py` 1308 行原文 / 1071 非空；`frontend/src` 3188 行）——与刚修完的 L-04 同族，就在同一文件附近。

---

## 4. 新发现清单

> 编号 RD3-xx；级别 🔴 Critical / 🟡 Important / 🟢 Minor；每条标注 **HARD VIOLATION**（有 plan/spec/项目文档的可引用依据）或 **JUDGEMENT CALL**（无明文依据，需协调者裁决）。

| 编号 | 级别 | 位置 | 问题 | 建议修复 | 性质 |
|:--:|:--:|---|---|---|---|
| **RD3-01** | 🟡 | `backend/tests/test_files_api.py:15-38` | `staging_dir` 同时含 `yield` 与 `return` → 整体是生成器函数；`tmp_path_factory.mktemp()` 成功时 pytest 抛 `ValueError: staging_dir did not yield a value`。**正常机器/CI 上该文件用例全 ERROR**（本沙箱因 `%TEMP%` 被拒才走 `except` 分支而恰好通过） | 统一成单一 `yield` 形态：把两条路径都算出一个目录变量，`try: yield d` 后再按「是否 `mktemp` 产物」决定清理方式（`mktemp` 产物交给 pytest 的 `tmp_path_factory`，自建目录才 `rmtree`）。**并补一条**「正常机器可跑」的断言或 CI 说明，避免再次只在沙箱里变绿 | **HARD**（测试是 plan 的验证载体；且它使「124 passed」成为环境专属结论） |
| **RD3-02** | 🟡 | `backend/app/routers/ws.py:129-135` | `cont.logs(...)` 是**阻塞调用却跑在事件循环上**：docker-py 的 `logs()` 在返回生成器前**立即**发 HTTP 请求（`docker/api/container.py:895 res = self._get(url, params=params, stream=stream)`），并且 `_check_is_tty` 还会额外同步 `inspect_container` 一次（`api/client.py:478-483`）。实测：伪造 `logs()` 阻塞 1.5s 时，`/api/health` 最坏延迟 **1525ms**（基线 min 1ms / max 34ms） | `log_stream = await asyncio.to_thread(lambda: cont.logs(stream=True, follow=True, ...))`；同一处理里 `log_stream.close()`（`finally`）也应一并移出循环 | **HARD**（`docs/development.md:156-160` 明写「阻塞调用会冻死整个事件循环…丢到工作线程里跑」；R1 冻结事故的同类回归） |
| **RD3-03** | 🟡 | `backend/app/routers/ws.py:191-195` | 批处理循环假设「一次迭代 = 一行」。docker-py 对 **TTY 容器**走 `_stream_raw_result(response, chunk_size=1, decode=True)`（`api/client.py:485-490,413-422`）→ `iter_content(1, True)`，**每次迭代约 1 字节**；代码却用 `"\n".join(...)` 拼接，于是**每个字符一行**。实测：TTY 流输入 `'hello world\n'` → 客户端收到 `'h\ne\nl\nl\no\n \nw\no\nr\nl\nd\n'`（渲染 12 行）；非 TTY 路径正常（`'hello world\nsecond line'`） | 与 TTY 无关的稳健做法：**不按迭代边界分行**，改为累积原始文本再按 `\n` 切分（即 `pending` 存字符、`flush` 时 `"".join` 后再 split），或直接判定 `Config.Tty` 后对 TTY 路径走同样的「累积文本 + 按换行切分」逻辑。**注意**：面板自身从不设置 `tty`（`run_spec.py`/`containers.py` 无 `tty`），但面板会列出并流式读取**任何**容器（含用户 `docker run -t` 创建的） | **JUDGEMENT**（spec 未点名 TTY；但 §6 的「逐行前向」意图被违背） |
| **RD3-04** | 🟡 | `scripts/ui_verify.py:64-68` vs `:250`、`:74` | 未入判的 warning 仍以 `[FAIL]` 打印，故「`[FAIL]` 与退出码 0 并存」可实测复现：`[FAIL] 控制台警告（console warning，仅报告不判定） -- 1 条` + `UI verification PASSED` + `main() -> 0`。`:250` 的自述不变量与 `:74` 的 docstring 因此**为假**；grep `[FAIL]` 的 CI/日志扫描器会报假失败 | 让标签诚实：`status = "PASS" if ok else ("FAIL" if judged else "WARN")`（或把 warning 行改为 `[WARN]`），并同步修正 `:250` 注释 | **HARD**（违背文件自身声明的门禁不变量） |
| **RD3-05** | 🟡 | `docs/deployment.md:106-108` | 「关闭镜像源」片段是 YAML 列表语法 `- IMAGE_MIRRORS=`，出现在「用 `.env` 覆盖」章节语境下，粘进 `deploy/.env` 会让 compose **整体拒绝启动**：`failed to read …: line 2: key cannot contain a space`（EXIT=1）；正确写法 `IMAGE_MIRRORS=` 得 `IMAGE_MIRRORS: ""`（EXIT=0） | 去掉行首横线（`.env` 形态），或把代码块语言标成 `yaml` 并在紧邻处写明「以下片段编辑 `deploy/docker-compose.yml`」（`troubleshooting.md:38-40` 已这么做） | **JUDGEMENT**（文档可用性；实测已复现） |
| **RD3-06** | 🟡 | `scripts/e2e_verify.py:357-376` | `test_ws_exec` 的断言可被 **PTY 输入回显**满足：发 `echo EXECOK<hex>` 后断言 `token in collected`，而 TTY 回显的输入行本身就含该 token → 一个什么都不执行的 shell 也能 PASS（rd1 C-11 只修了 `/ws/logs` 的同类假绿）。对照 `test_ws_exec_resize`（`"43 132"`，不可能来自回显）是健全的 | 断言一个**输入里不含**的产物，例如发 `echo EXEC""OK<hex>` 并断言 `EXECOK<hex>`；或先发 `echo $$` 类命令并断言输出中不出现命令行原文 | **JUDGEMENT**（无 spec 明文，但属「测试必须能失败」的门禁原则） |
| **RD3-07** | 🟢 | `test-review/code-review-report.md:284` vs `docs/epics/docker-manager-v1/README.md:20` | 同一批 rd2 发现的 HARD 计数自相矛盾：前者写「27 条，其中 **3** 条 HARD」，后者写「含 **4** 条 HARD」，而 §2.4 表内实际标 HARD 的是 **5** 行（N-01后端/N-07后端/N-02前端/N-08部署/L-10） | 统一为 5（或改为按「按透镜去重后」的口径并给出算式） | **HARD**（C-22/L-03「看板自述与实际不符」同型复发） |
| **RD3-08** | 🟢 | `README.md:207` | 代码规模自述与现实不符（称后端 ~1.7k / 前端 ~2.1k 行；实测 `backend/app/*.py` 1308 原文/1071 非空，`frontend/src` 3188） | 更新数字并写明统计口径（是否含空行/是否含 `tests/`） | **JUDGEMENT** |
| **RD3-09** | 🟢 | 线上栈 / `deploy/docker-compose.yml` | 后端镜像未重建，线上修复是 `docker cp` 临时态：`dockermgr-backend` 容器创建于 `2026-09-11T01:06`（从未重建），`dockermgr-frontend` 为 `2026-09-14T02:02`。一次 **不带 `--build`** 的 `docker compose up -d` 会从旧镜像重建后端容器，**静默回退全部后端修复** | 守护进程恢复后立即 `docker compose up -d --build`；在 epic README「未完成项」保留该行直到重建完成（现已记录于 `README.md:81`，建议再加一句「未重建前**不要**直接 `up -d`」的显式警告） | **JUDGEMENT**（已记录，缺回退防护） |
| **RD3-10** | 🟢 | `docs/troubleshooting.md` | L-10/L-16 要求的两条排障条目缺失（「反代后写操作 403 / 终端 1008」「307 丢端口」） | 在「部署与构建」下补两条：症状 → 病因（Host 被反代改写 / `$host` 丢端口）→ 修法（`proxy_set_header Host $http_host` / `ProxyPreserveHost On`）→ 验证命令 | **HARD**（rd2 明确点名的修复项） |
| **RD3-11** | 🟢 | `backend/tests/test_endpoints_coverage.py:105-120,357+` | mock 形状与真实形态不符或过宽：`_Cont.name = "/web"`（docker-py `Container.name` 从不带前导斜杠，`models/containers.py:29-34`）；`_Api.exec_create/exec_start` 用 `(*args, **kwargs)`，**形状上不可能**发现签名漂移（参数名/顺序/默认值错了也照样 PASS） | ① `name` 改用真实形态 `"web"`（并在需要时显式断言 `lstrip` 行为）；② 给 `exec_create`/`exec_start`/`exec_resize` 写**显式签名**（`def exec_resize(self, exec_id, height=None, width=None)`）并按关键字断言，使 `height`/`width` 交换这类缺陷能被捕获 | **JUDGEMENT** |
| **RD3-12** | 🟢 | `backend/app/routers/ws.py:17-20` vs `:196-198`；`:161-164` | 注释与实现不符：① 注释称缓冲为「bounded **drop-oldest**」，实现却是 `pending.clear()` **整批丢弃**（连刚 append 的最新一行也丢——而前端策略恰恰是保留最新）；② 注释称标记行「never adds a trailing newline that would render as an empty line」，但当 `pending` 首/末元素为空串时 `"\n".join` 仍会产生首/尾空行 | ① 注释改为「drop-all-on-overflow」或实现改为真正的丢最旧（`del pending[:len(pending)//2]` 之类并只计被丢弃部分）；② 修正注释或先过滤空元素再拼接 | **JUDGEMENT** |

**另有 1 条「无新发现但有价值」的观察**：L-13（WS 守卫两处内联）与 L-11/L-12（Origin 放宽未披露）建议合并成一次小改动——抽一个 `guard_ws_origin(ws)` 依赖并在 docstring 里点明放宽的安全含义——即可同时关掉 3 条记录在案的取舍。

---

## 5. 实际运行的命令与真实输出

> 全部探针位于仓库外：`D:\桌面\测试\.rd3-probes\`（`backend\`、`frontend\`、`scripts\`、`compose\`、`fixture\`）。审查前后 `git status --short --untracked-files=all` 均为 54 项。

### 5.0 派生方法说明（前端断言如何做到「机械派生、非手抄」）

本轮的硬性要求是前端逻辑断言必须**机械派生**而非手抄逻辑。我实际采用的方法与边界如下：

| 对象 | 方法 | 是否手抄逻辑 |
|---|---|:--:|
| `frontend/src/utils/ws.ts`（A5 判别字段、`isRetryableClose`、`describeWsError`） | **零派生**：该文件无任何 import，`node` 可直接 `import(pathToFileURL(<真文件>))` 真源码（见 §5.6 首行 `imported from: …`，导出列表由运行时打印）。所有用例都打在这个**真模块**上 | **否**，完全真源码 |
| `frontend/src/utils/download.ts`（A2 预检超时/取消） | **静态核实 + 行号引用**（`:12` 超时值、`:53-58` AbortController、`:62` signal、`:76-80` finally 清定时器），未起 Node 运行；理由是它的失败分支依赖 `showApiError`/DOM（`document.createElement`），真跑需要一并打桩，收益低于成本 | **否**，但属**静态**证据等级（已在 §3.4 与本表如实标注） |
| `frontend/src/components/*.vue`（A1 退避复位、A3 paused 禁终端） | **静态核实 + 行号引用**：读**真文件**并给出 `ContainerLogs.vue:204-213`、`ContainerTerminal.vue:240-247`、`ContainersView.vue:120-134,336-357` 等精确行；**未**做 `@vue/compiler-sfc` 的 `<script setup>` 抽取并执行 | **否**（无手抄），但属**静态**证据等级 |
| `backend/tests/test_files_api.py` 的 `staging_dir`（RD3-01） | **机械抽取**：`(Get-Content <真文件>)[14..37] -join "`n"` 按行号切片后原样写入探针文件，只额外提供 `conftest.py` 覆写 `tmp_path_factory` | **否**，完全真源码片段 |
| 后端变异（B2 / B7） | 备份真文件 → 字符串级替换 → 跑测 → 还原 → **SHA256 校验逐字节一致** | **否** |

> 换言之：**凡本报告给出「实测输出」的前端断言，其输入都是真源码**（`ws.ts` 为直接 import，`.vue` 为精确行号引用 + 未手抄）；凡依赖 `.vue` 运行期行为的结论（A1/A2/A3），证据等级为**静态 + 行号**，我没有把它们写成「已动态验证」。这是刻意保守的标注，而不是省略。

### 5.1 B2 —— 变异验证（决定性手段）

```powershell
# 基线（正常代码）
cd D:\桌面\测试\docker-manager\backend; $env:UV_CACHE_DIR='D:\桌面\测试\.uv-cache'
uv run --frozen pytest tests/test_ws_logs.py -q -s
  batching: 600 lines delivered in 19 frames while the stream was still open
  5 passed, 2 warnings in 2.58s

# 变异体：删除 flusher 线程的 timer.start()（备份 → 改写 → 跑测 → 还原 → 校验哈希）
== BEFORE hash: A9CEA43E0668D86F89C8098031E3D2D74DC6132DBEF1640C3E6E92E442F6FF3A
== occurrences of 'timer.start()': 1
== MUTANT APPLIED
   line 188: pass  # RD3-MUTANT flusher never started
>               assert frames_now > 0, (
E               AssertionError: no frame arrived while the stream was still producing:
                the periodic flush (timer thread) is gone, so everything now waits for
                the stream to end
E               assert 0 > 0
  batching: 0 lines delivered in 0 frames while the stream was still open
  1 failed, 4 passed, 2 warnings in 8.00s
== AFTER hash: A9CEA43E0668D86F89C8098031E3D2D74DC6132DBEF1640C3E6E92E442F6FF3A
== RESTORED byte-identical
```

### 5.2 RD3-01 —— fixture 生成器/return 混用（决定性）

```powershell
# 机械抽取真文件第 15..38 行（不手抄），配一个让 mktemp() 成功的 conftest
$fixtureBlock = (Get-Content ...\test_files_api.py)[14..37] -join "`n"
# conftest.py: 覆写 tmp_path_factory 使其 mktemp() 必定成功（正常机器）
& ...\.venv\Scripts\python.exe -m pytest test_probe_fixture.py -q
  >               raise ValueError(f"{request.fixturename} did not yield a value") from None
  E               ValueError: staging_dir did not yield a value
  ..\..\docker-manager\backend\.venv\Lib\site-packages\_pytest\fixtures.py:1000: ValueError
  ERROR test_probe_fixture.py::test_uses_the_fixture - ValueError: staging_dir ...
  2 warnings, 1 error in 0.19s
```

### 5.3 B7 —— 端点覆盖变异验证
```powershell
== BEFORE hash: 5A016D9CE9289B885018A6BF0ED96EFEC876F346DC036D0EF65409679D67ED9D
##### M-A remove(force=force) -> remove(force=False)  (occurrences=1)
   FAILED tests/test_endpoints_coverage.py::test_container_delete_passes_force
   1 failed, 28 passed, 2 warnings in 0.70s
##### M-B list(all=all) -> list(all=False)  (occurrences=1)
   FAILED tests/test_endpoints_coverage.py::test_containers_list_passes_the_all_flag
   1 failed, 28 passed, 2 warnings in 0.65s
== AFTER hash: 5A016D9CE9289B885018A6BF0ED96EFEC876F346DC036D0EF65409679D67ED9D
== RESTORED byte-identical
```

覆盖率与形状核验：

```powershell
tests/test_endpoints_coverage.py: 27 个 def test_（29 例，3 路 parametrize）
tests/test_security.py:           24 tests collected
三文件合计:                       58 tests collected
docker-py 版本:                   7.2.0
真实签名核对（docker 包源码）:
  containers.list(self, all=False, before=None, filters=None, limit=-1, ...)   models/containers.py:958
  Container.name -> attrs['Name'].lstrip('/')                                  models/containers.py:29-34
  Container.commit(self, repository=None, tag=None, **kwargs)                  models/containers.py:127
  Container.get_archive(self, path, chunk_size=..., encode_stream=False)       models/containers.py:244
  Container.remove(self, **kwargs)                                             models/containers.py:353
  Image.save(self, chunk_size=DEFAULT_DATA_CHUNK_SIZE, named=False)            models/images.py:80
  exec_create(self, container, cmd, stdout=True, ...)                          api/exec_api.py:7
  exec_resize(self, exec_id, height=None, width=None)                          api/exec_api.py:99
  exec_start(self, exec_id, detach=False, tty=False, stream=False, ...)        api/exec_api.py:118
异常层级实测: NotFound ⊂ APIError ⊂ DockerException → except 顺序不可被遮蔽
```

### 5.4 线上栈实测（HTTP + WS）

```text
HTTP 1. GET /api/health -> 200 {"status":"ok"}
HTTP 2. GET /api/containers?all=true -> 200（8 个容器）; GET /api/images -> 200, 8 images
HTTP 3. POST /api/volumes {'name': ...} + Origin: http://127.0.0.1:8088   -> 200 {"ok":true}
        POST /api/volumes + Origin: http://evil.example                   -> 403 cross-site request rejected
        POST /api/volumes + Origin: http://127.0.0.1.evil.example         -> 403 cross-site request rejected
        CLEANUP DELETE /api/volumes/rd3-probe-ab7a1f95 -> 200 {"ok":true}（卷清单回到 8 个）
WS 4. /ws/logs?filter=__rd3_no_such_container__
        recv TEXT '{"dockermgr":"error","error":"no container"}'
WS 5. /ws/exec?container=__rd3_no_such_container__
        recv TEXT '{"dockermgr":"error","error":"no such container: __rd3_no_such_container__"}'
WS 7. /ws/logs?filter=dockermgr-frontend&tail=5&stream=both
        recv TEXT '<5 行真实日志，1 帧>'，随后 recv <TIMEOUT>（无空帧）
WS 8. /ws/logs?filter=x  origin=http://evil.example
        connect failed: InvalidStatus: server rejected WebSocket connection: HTTP 403
```

### 5.5 B5 —— exec 打在不运行容器上（决定性）

```text
POST /api/containers (auto_start=false) -> 200 state="created"
WS /ws/exec on a container in `created` state:
   recv TEXT '{"dockermgr":"error","error":"docker 守护进程错误：409 Client Error for
              http+docker://localhost/v1.55/containers/79b03c29.../exec: Conflict
              (\"container 79b03c29... is not running\")"}'
   recv <closed: received 1000 (OK)>
POST /rd3-b5-2a0cfc86/start -> 200 ; stop -> 200 -> state="exited"
WS /ws/exec on an EXITED container:
   recv TEXT '{"dockermgr":"error","error":"docker 守护进程错误：409 ... is not running"}'
WS /ws/logs on the same EXITED container (C-06 有效性):
   recv TEXT '... [notice] signal 29 (SIGIO) received ... worker process 38 exited with code 0 ... exit'
CLEANUP DELETE /api/containers/rd3-b5-2a0cfc86?force=true -> 200 {"ok":true}
[after] containers 仍为 8 个（无残留）
```

> 中文在 pwsh 控制台显示为乱码（`docker �ػ����̴���`）是**控制台代码页**所致；starlette 1.6.0 `websockets.py:174` 用 `json.dumps(..., ensure_ascii=False)`，线上帧确为 UTF-8 中文。**非产品缺陷**。

### 5.6 A5 —— 判别字段真值表（机械导入真源码）

```powershell
cd D:\桌面\测试\.rd3-probes\frontend; node probe-ws-truth.mjs
imported from: D:/桌面/测试/docker-manager/frontend/src/utils/ws.ts
NEW error frame (control)          -> "no container"
NEW error frame w/ padding         -> "no such container: web"
OLD error frame (must be DATA)     -> null
OLD exec frame (must be DATA)      -> null
json log, error key (structured)   -> null
json log, error + msg              -> null
json log, time + error             -> null
batched log lines                  -> null
batched, last line is json         -> null
discriminator only, no error       -> null
empty error string                 -> null
whitespace error string            -> null
non-string error                   -> null
wrong discriminator value          -> null
array frame                        -> null
trailing content                   -> null
empty frame (single blank line)    -> null
data frames misread as control frames: 0 (expected 0)
--- isRetryableClose ---  1000->false 1005->true 1006->true 1008->false 1011->true
```

### 5.7 RD3-02 —— 事件循环阻塞（决定性）

```text
fixture: 真 uvicorn 服务端 + 伪造容器，其 logs() 阻塞 1500ms（模拟 docker-py 的即时 HTTP 请求）
  baseline /api/health latency: min=1ms max=34ms
  during /ws/logs: 18 health samples, worst=1525ms
  (fake cont.logs() blocked for 1500ms)
E  AssertionError: /api/health took 1.52s while the handler was inside cont.logs():
   the blocking docker-py call runs ON the event loop
```

### 5.8 RD3-03 —— TTY 流被打成一字符一行（决定性）

```text
  TTY stream input : 'hello world\n'
  frame sent to client: 'h\ne\nl\nl\no\n \nw\no\nr\nl\nd\n'
  lines rendered   : 12
  non-TTY frame sent to client: 'hello world\nsecond line'
E  AssertionError: a TTY container's log stream came back with one character per line
1 failed, 1 passed, 2 warnings in 0.59s
```

### 5.9 B8/B10/L-08 —— `ui_verify.py` 门禁（真源码 + 桩浏览器，8 场景）

```text
ui_verify.py sha256 = c911beef…
OK | A. clean baseline                            exit=0 expected=0 fails=0
OK | B. pageerror injected                        exit=1 expected=1 fails=1
OK | C. console error injected                    exit=1 expected=1 fails=1
OK | D. console warning ONLY injected             exit=0 expected=0 fails=1
OK | E. requestfailed injected                    exit=1 expected=1 fails=1
OK | F. mid-token port break in containers chips  exit=1 expected=1 fails=1
OK | G. semantic check fails (0 container rows)   exit=1 expected=1 fails=1
OK | H. L-08 replacement: port textarea missing   exit=1 expected=1 fails=1
scenario D body: console warnings: 1
  [FAIL] 控制台警告（console warning，仅报告不判定） -- 1 条
  UI verification PASSED: 所有判定项均通过
  main() -> 0
```

### 5.10 其余实测命令

```powershell
# 后端全量单测（基线）
cd D:\桌面\测试\docker-manager\backend; $env:UV_CACHE_DIR='D:\桌面\测试\.uv-cache'
uv run --frozen pytest -q            -> 124 passed, 2 warnings in 5.14s

# 前端类型检查
cd D:\桌面\测试\docker-manager\frontend; node .\node_modules\vue-tsc\bin\vue-tsc.js -b --force
                                     -> VUE_TSC_EXITCODE=0（node v24.18.0）

# 真机 E2E（我独立复跑）
& .\backend\.venv\Scripts\python.exe scripts\e2e_verify.py
  -> [PASS] ×18  RESULT: 18/18 passed  EXITCODE=0
     其中：WS /ws/logs -- 收到 20 行真实日志（1 帧）
           Image export -- 82966016 bytes, entries=17, manifest=yes
           WS /ws/exec PTY resize -- stty size -> '43 132'

# E2E 残留清点（跑完）
containers=8  images=8  volumes=8
RESIDUE containers: []   RESIDUE images: []   RESIDUE volumes: []

# nginx 重定向是否保留端口
curl.exe -s -i --max-time 15 "http://127.0.0.1:8088/api/containers/"
  -> HTTP/1.1 307 Temporary Redirect ; Server: nginx/1.31.5
     location: http://127.0.0.1:8088/api/containers

# N-08 / RD3-05 compose 变量语义（我独立复现）
docker compose --env-file .rd3-probes\compose\formA.env -f deploy\docker-compose.yml config
  -> failed to read …formA.env: line 2: key cannot contain a space        EXIT=1
docker compose --env-file .rd3-probes\compose\formB.env -f deploy\docker-compose.yml config
  -> IMAGE_MIRRORS: ""                                                    EXIT=0

# 镜像/容器年龄（RD3-09）
dockermgr-frontend  image='deploy-frontend:latest'  created=2026-09-14T02:02:20Z
dockermgr-backend   image='deploy-backend'          created=2026-09-11T01:06:05Z   ← 从未重建
```

---

## 6. 未能验证项（诚实标注）

| # | 项 | 原因 |
|:--:|------|------|
| 1 | `ui_verify.py` / `ui_clipboard_test.py` 的**真实浏览器**运行 | 沙箱拒绝 Playwright 驱动（`PermissionError [WinError 5]`，asyncio `CreateFile` 管道）。L-07/L-08/L-14 的结论建立在「**未改动的真源码 + 桩浏览器**跑 8 个场景」+ DOM 源码阅读之上，**不是**真实浏览器会话。子代理已用 sha256 证明脚本确实跑到 `sync_playwright()` 才失败 |
| 2 | **RD3-02 在真实链路上的表现** | 我的探针用「伪造 `logs()` 阻塞 1.5s」证明机制；真实 daemon 上 `logs()` 的耗时取决于 `tail` 行数与 daemon 状态，**未测真实耗时量级** |
| 3 | **RD3-03 的实际可达性** | 面板自身从不设置 `tty`（已 grep 确认），我**无法读取宿主机容器的 `Config.Tty`**（daemon 命名管道被沙箱拒绝：`WinError 5`）。故「存在 TTY 容器」是条件，不是已观测事实 |
| 4 | **RD3-09 的镜像构建时间** | 面板 API 不返回镜像 `created`（实测 `created=None`）。我用「后端容器创建于 09-11 且从未重建、前端容器为 09-14」+「线上行为等值于工作区代码」推断 `docker cp` 态，**未能**直接读取镜像层时间戳 |
| 5 | Compose v1 行为、以及部署文档「v1 已 EOL」这一外部断言 | 本机只有 Docker Desktop shim（`docker compose version` → `v5.5.1`），无 v1 可实跑；对外 HTTPS（docs.docker.com）亦不可达 |
| 6 | L-15（`requestfailed` 是否真的把导航/取消误判为失败） | 需真实浏览器会话；与 rd2 同样留作未验证 |
| 7 | 真实 JSON 日志行在**活体**链路上不被误判 | 我抽样的容器在窗口内未产出 `{…}` 行；该结论只在**纯函数层**（真源码真值表）成立。**但**后端—线上—前端三层各自的「形状」都已实测，缺口仅在「真实容器恰好打印这种行」这一情形 |
| 8 | 「修复已提交」 | 全部修复仍是**工作区未提交改动**（基线 `8149029`）。本报告所说「已修」一律指「工作区已含」，**未**验证提交/推送 |
| 9 | N-02 收尾竞态的**确定性变异体** | 我尝试构造「flusher 关闭时也 flush」的变异体，但由于 `flush()` 在缓冲为空时直接 return，重复 flush 不会产生可观测的重复帧/空帧，**无法构造出确定性失败的变异体**。该判定依据是「读码 + 长命流精确计数断言（`== 600`）+ 活体无空帧」三者，标注为**不同于变异验证的证据等级** |

---

## 7. 需协调者决定的事项

1. **RD3-01（必修，最高优先）**：`staging_dir` fixture 改为单一 `yield` 形态。修完请**在 `%TEMP%` 可写的环境下**跑一次 `pytest -q` 以证明不再是沙箱专属绿——否则「124 passed」这一交付证据仍然只在 DSH 沙箱成立。
2. **RD3-02（建议本轮修）**：把 `cont.logs(...)` 移入 `asyncio.to_thread`，并为「`/ws/logs` 建流不阻塞事件循环」补一条回归用例（可复用 `test_ws_logs_blocking.py` 的真 uvicorn + 伪造 `logs()` 阻塞模式）。**注意**：该缺陷**无任何现有测试覆盖**。
3. **RD3-03（需裁决）**：TTY 容器日志渲染一字符一行。是否本轮修取决于「本期是否**承诺**支持 TTY 容器」。若不修，请**在 `docs/troubleshooting.md` 记一条已知限制**（当前无任何记录），并把 §6 第 3 项的未验证状态写进 epic README。
4. **RD3-04（三五行的修）**：`ui_verify.py` 的 warning 行改用 `[WARN]` 标签并修正 `:250` 注释；否则「`[FAIL]` 与 PASSED/exit 0 并存」会长期存在。
5. **RD3-05（一行文档）**：`deployment.md:106-114` 去掉行首横线或标注为 compose YAML 片段。这是本轮修复**自己引入**的文档缺陷，建议同批修掉。
6. **RD3-06（建议修）**：`e2e_verify.py` 的 exec 往返改为断言「输入中不含的产物」。
7. **L-10 / L-16（补齐两条排障条目）+ L-11/L-12/L-13（合并一次小改动）**：抽 `guard_ws_origin()` 并在 docstring 披露 Origin 放宽的安全含义，可一次关掉 3 条记录在案的取舍。
8. **RD3-07（看板计数）**：统一 HARD 计数（3 / 4 / 实际 5）。C-22 与 L-03 都是这一类，**建议在合并提交里一次性对齐**，避免第三次复发。
9. **RD3-09（运维提醒）**：重建后端镜像前，请在 epic README 的「未完成项」显式加一句「**未重建前不要执行不带 `--build` 的 `docker compose up -d`**」，因为那会静默回退全部后端修复。
10. **提交形态**：全部改动仍未提交。建议按「测试修复（RD3-01）/ 后端阻塞与 TTY（RD3-02、RD3-03）/ 门禁与脚本（RD3-04、RD3-06）/ 文档（RD3-05、RD3-07、L-10、L-16）」分 4 个提交落盘，便于下一轮做范围受限的复核。

---

## 8. 亮点（本轮确实做对的）

- **判别字段三层一次改到位**：生产端单点（`ws.py:34`）、旧帧形彻底不再发出（全仓 grep 确认）、前端与 E2E 各自改为「必须带判别字段」，并有**三层各自可失败的证据**（活体帧 / 真值表 / sniffer 单测）。这是本轮最有价值的改动，且我实测「数据帧被误判」计数为 0。
- **B2 的回归用例是真有牙的**：长命流 + `stream.produced` 门控 + 「流仍开着」时取样 + 精确行数断言 + 帧数上界，四个条件组合起来才使删掉计时线程必然失败 —— 我用变异实测确认（600 行 → 0 帧 → FAIL），而 rd2 当时的同名用例在变异下仍全绿。
- **`_safe_reason` 的存在理由是对的**：它防的是「诊断路径自己炸掉 → 退回零帧静默关闭」这一类二级故障，属少见的、真正想到「错误处理器也会失败」的设计。
- **修法选择「显式记录取舍」而非「假装解决」**：N-05（预检只校验状态行）与 N-06（重连重放 tail）都没有被硬修，而是以 `KNOWN LIMIT` / `KNOWN TRADEOFF` + 视图内边界标记的方式把边界讲清楚——这比一个掩盖边界的假修复更有价值。
- **`e2e_verify.py` 的门禁化**：`EXPECTED_CHECKS = 18` + 非零退出码 + 控制帧识别 + 端口断言（`"43 132"`）都是「测试必须能失败」的正确方向，我复跑 18/18 且**零残留**。
