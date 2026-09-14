# 计划/规格对齐 + 跨层契约 + 文档 透镜 — Phase 4.6 修复后重审（Rd2）

> 审查对象：`D:\桌面\测试\docker-manager`（Windows / pwsh）
> 审查范围：**工作区未提交的修复批次** = `git diff 8149029` + 未跟踪新文件（`git status --short --untracked-files=all`）
> 基线提交：`8149029`（HEAD，`fix` 批次全部未提交）
> 审查方式：**隔离审查**（不继承编码上下文，不采信 README/注释/上一轮报告的自我声明），只读 + 仅写本报告
> 判据：`spec.md` / `scope.md` / `plan.md`（历史归档，仅用于对账）/ epic `README.md`
> 上一轮报告（同为被审对象）：`test-review/code-review-report.md` + `test-review/rd1/*.md`

**环境限制（如实标注，不当作产品缺陷）**：沙箱禁止 Playwright 子进程与 Docker 命名管道，因此**无法**起浏览器跑 `scripts/ui_verify.py`、**无法** `docker build` / `docker compose up`。本报告所有结论要么来自**实跑命令**（见末节），要么明确标注为**静态推断**。

---

## 一、审查结论

**本透镜 Verdict：❌ NEEDS FIXES**（无 🔴；2 🟡 与「提交前必须修」的文档/门禁项有关，其中 L-10 具备可引用文档依据）

| 段 | 结论 | 关键发现 |
|----|:--:|---------|
| Plan alignment | ❌ | C-21 回写**实质成功**、D5 三条**已改正**；但 `deployment.md:34` 新表述把上一轮**未经证实**的兼容性断言写进了产品文档（L-02）；epic 看板「未完成项 / 66 passed」未随批次同步（L-03，C-22 同型复发） |
| Code quality | ❌ | 错误帧协议**无判别字段**，容器打印单行 JSON 日志时会被前端当协议帧吞掉（L-06，本批次新引入）；`ui_verify.py` 新加的 5 个 `record()` 判定**不参与退出码**（L-07）、run-dialog 端口断行检查**恒为空集**（L-08） |
| Architecture | ❌ | 跨站守卫与 `deployment.md:152` 推荐的「前置认证反代」**冲突且未文档化**（L-10，HARD）；`Origin host == Host` 放行分支构成 DNS rebinding 通道（L-11） |
| Testing | ⚠️ | 契约三层对齐良好、E2E 门禁化**真实有效**（L-10/C-10/C-11 已关闭）；唯一判断项是把 console **warning** 判为失败（L-14，JUDGEMENT，已给出生产包级证据） |
| Production | ⚠️ | 本批次的修复**全部未部署**（实测线上仍是修复前行为，见 E-4/E-5），`.dockerignore` 效果量化确认（118.2 MB → 0.16 MB）；`frontend/.dockerignore:22` 存在无效条目（L-17） |

**段间不抵消**：Plan alignment 与 Code quality 段的 🟡 未关闭 → 整体 NEEDS FIXES。

---

## 二、被指派条目 · 关闭判定一览

| 指派条目 | 关闭判定 | 依据（本人实测，非引述） |
|---------|:--:|------|
| **C-21** 回写消除 spec/scope 自相矛盾 | **CLOSED**（余 1 🟢） | `scope.md:35` 新增 F12 行、`:37` 带日期与来历的补记；`spec.md:83` 改为「容器 列表/详情 / 创建（从镜像运行）/ 启停 / 暂停 / 删除」；`spec.md:132` 澄清段；epic `README.md:22` 已是「5 轮修复（R1–R5）」+ `:29` R4 行。模板内 `spec.md:130`（v1.1 排除项）与 `:132` 澄清**已互相自洽**。残留见 L-01 |
| **D5-a** `docs/development.md:158` | **CLOSED** | 现写 `loop.call_soon_threadsafe`，与代码事实一致：`backend/app/routers/ws.py:50`、`:136`、`:160` 三处调用；全文已无 `run_coroutine_threadsafe` |
| **D5-b** `docs/troubleshooting.md:168` | **CLOSED** | 行号未漂移，现写 `loop.call_soon_threadsafe`（回投普通回调），与 `ws.py:50` 一致 |
| **D5-c** `README.md:26` 镜像列表字段 | **CLOSED** | 现写「列表（含标签与镜像 ID）」。对照实现 `backend/app/routers/images.py:76-82`：只有 `id`/`tags`/`digest`/`short_id`，**确无** size/created —— 改后的表述与代码事实一致 |
| **D5-d** `docs/deployment.md:34` docker-compose v1 | **PARTIAL → NEW DEFECT（L-02）** | 由「v1 不支持」改成「v1 同样能运行这个 `docker-compose.yml`」——两版**都没有证据**。事实：`deploy/docker-compose.yml:1` **无 `version:` 键**（HEAD `git show 8149029:deploy/docker-compose.yml` 同样无），而 Docker 官方 compose-file 文档明确「省略 `version` 键即 Version 1 旧格式」，旧格式顶层键就是服务名、不支持 `services:` 段。本机只有 Docker Desktop 的 shim（实测 `Docker Compose version v5.5.1`），**无法**实跑 v1 |
| **契约 1** WS 失败先发 `{"error": ...}` 文本帧再关闭 | **CLOSED** | `/ws/logs`：`ws.py:98-99`（`send_json` → `close`）；`/ws/exec`：`ws.py:226-227`（`send_json` → `return` → `finally` 中 `_close_ws`）。四层对齐：后端 ✅ / 前端 `utils/ws.ts:24-39` + `ContainerLogs.vue:212-218` + `ContainerTerminal.vue:250-257` ✅ / E2E `e2e_verify.py:261-279` ✅ / 单测 `test_ws_logs.py:38-51`（`/ws/logs`，断言在 `try` 之外，`:51`）、`test_endpoints_coverage.py:251-268`（`/ws/exec`）✅。歧义风险见 L-06 |
| **契约 2** `/ws/logs` 单帧含多行（`\n` 分隔） | **CLOSED** | 后端合并：`ws.py:128`（`"\n".join(pending)`，100ms 一帧）；前端按 `\n` 拆：`ContainerLogs.vue:178`（`chunk.split('\n')`，且注释明写「splitting is mandatory」）；E2E 按 `\n` 拆：`e2e_verify.py:286`。**`/ws/exec` 不拆行是对的**（PTY 原始字节，`ContainerTerminal.vue:259` 直接入 xterm），未误伤。单测锁定：`test_ws_logs.py:74-91`，断言 `frame.split("\n") == ["l1","l2","l3"]`（`:91`） |
| **契约 3** `scripts/requirements-verify.txt` 路径一致 | **PARTIAL（脚本层 CLOSED，文档层缺引用）** | 三方脚本提示**完全一致**：`e2e_verify.py:9,12,31`、`ui_verify.py:9,11,27`、`ui_clipboard_test.py:9,24`，且文件本体存在并声明 `playwright>=1.40`（:18）与 `websockets>=12.0`（:22）。**但** `docs/development.md:126-141`、`docs/deployment.md:230-235`、`docs/troubleshooting.md:262-266`、根 `README.md:231-245` 都只说「`python scripts/e2e_verify.py`」，**没有一处**提示安装 `scripts/requirements-verify.txt` → 见 L-05 |
| **C-10** E2E 失败返回非零 | **CLOSED** | `e2e_verify.py:551` `sys.exit(main())`；`main() -> int`（:509）→ `summarize()`（:490-506）：`return 0 if (complete and passed == total) else 1`，且 `total == 0` 与 `total != EXPECTED_CHECKS` 都判 1 |
| **C-11** E2E 断言可假阳性 | **CLOSED** | ① 协议帧被显式识别并判 FAIL（`:261-279` `control_frame_error` + `:312-315`）；② 「收到任意 str 帧即 PASS」已消除，改为必须存在**真实日志行**（`:282-287` 过滤 `"... "` 丢弃提示 + `:320-333` 四分支判定）；③ 端口断言**无条件**执行（`:449-456`，含「ports 为空但显式请求了 ports=80 → FAIL」）；④ 数量恒定断言 `EXPECTED_CHECKS = 18`（`:487`、`:499-502`）—— 我逐条数了 record() 调用：满路径恰为 18（health 1、containers 2、images 1、networks 1、volumes 1、copy 2、commit 1、export 1、run 3、validation 1、logs 1、exec 1、resize 1、cleanup 1 = 18）✅；⑤ 删除镜像改为**重新列表复核**（`:243-248`） |
| **C-12** `ui_verify.py` 判定面 + 参与退出码 | **CLOSED（余 3 项）** | 判定面确实扩大并参与退出码：`ui_verify.py:202-211` 五条 `record` + `:214-216` `return 0 if all(not x for x in (page_errors, console_errors, console_warnings, failed_requests, port_breaks)) else 1`，warning 独立成列（`:206`）、端口断行真实入判（`:210`）。残留：L-07（5 个语义 `record` 不进退出码）、L-08（run-dialog 端口检查恒空）、L-14（warning 门禁判断） |
| **C-20** 脚本依赖声明与可读中文提示 | **CLOSED** | 新文件 `scripts/requirements-verify.txt` 声明 `playwright` + `websockets`，并写明本机 `.browser-tools` venv 无 pip 的安装法（:6-7）；缺依赖提示为中文且给出命令：`e2e_verify.py:31,50-56`（`require_websockets` → 记 FAIL 并附提示）、`ui_verify.py:24-28`、`ui_clipboard_test.py:21-25`（均 `sys.exit(2)`）。残留：文档未引用该文件（契约 3 / L-05） |
| **C-22** 看板自述与实际不符 | **原条目 CLOSED，同型复发 → L-03** | 已核实修正：`README.md:22` 由「4 轮」改为「5 轮（R1–R5）」（对照 `git diff` 旧行）；`:49/:75` 的 `uv.lock` 由「待修复」改为「已修复（8149029）」，我独立复核 `git check-ignore backend/uv.lock` **无命中**、`backend/uv.lock` 已跟踪；`:78` 计划预审描述与实际一致（`ImagesView/NetworksView/VolumesView` 三文件均存在）。**但** `:77` 仍写「待修复」、`:102` 仍写「66 passed」，而修复批次已在工作区完成、测试实测 105 passed → 见 L-03（必须在**同一提交**内同步，否则就是 C-22 形态重现） |
| 上一轮报告自身的准确性 | **有 2 处错误 → 见第五节** | `rd1/review-frontend-deploy.md:190` 把 `docs/troubleshooting.md:21` 报成含「4 轮」，实测该行是 `## 镜像相关`（用户提示的教训复现）；`code-review-report.md:109` 标题「Important（21，去重后）」与表内 20 条、正文「🟡 20」不符 |

---

## 三、发现清单

### Plan alignment

#### L-01 🟢 `scope.md:99` 验收标准仍写「F1-F10」，未覆盖新增 F12 —— JUDGEMENT CALL

- **位置**：`docs/epics/docker-manager-v1/scope.md:99`（AC #3）、对照 `:35`（F12 行）、`:37`（补记）
- **证据**：`scope.md:99` 原文「3. F1-F10 各动作均可经界面触发，不依赖命令行。（总体计划 §2 验收要点）」；表格已在 `:35` 补入 F12，AC 未同步。
- **影响**：读者仍可能认为「从镜像运行容器」不是验收项——这正是 C-21 想根除的读法，只是换了位置。
- **可为作者反驳之处（如实标注）**：`:37` 的补记明写「F1–F11 的原有界定未作改动」，且该行自述来源是「总体计划 §2 验收要点」（未修改的上游文档），因此保留原句**有依据**。故记 🟢 而非 🟡。
- **修复建议（拟改文字）**：`scope.md:99` → 「3. F1–F12 各动作均可经界面触发，不依赖命令行。（F1–F10 出自总体计划 §2 验收要点；F11/F12 为对话定案）」；或仅在 `:37` 补记末尾加一句「§6 AC#3 的 F1–F10 为上游原文引用，F12 的验收见 AC#2 闭环描述」。
- **关闭判定**：PARTIAL（可接受，建议顺手一句）

#### L-02 🟡 `docs/deployment.md:34` 新增的 docker-compose v1 兼容性断言无证据，且与官方格式规则冲突 —— NEW DEFECT / JUDGEMENT CALL

- **位置**：`docs/deployment.md:34`；关联 `deploy/docker-compose.yml:1`（无 `version:` 键）
- **证据链**：
  1. 现文（本批次改入）：「Docker Compose | v2（`docker compose`）。**v1 的 `docker-compose` 同样能运行这个 `docker-compose.yml`**，但 v1 已 EOL，本文命令与语法一律以 v2 为准」。
  2. 改前原文（`git diff 8149029 -- docs/deployment.md`）：写「带连字符的 `docker-compose` 不支持」。**两版都是断言、都没有附带验证记录**。
  3. 事实：`deploy/docker-compose.yml:1` 是 `services:`，**全文没有 `version:`**（HEAD 版本同样没有）；Docker 官方 compose-file 文档：「**Version 1.** This is specified by **omitting a `version` key** at the root of the YAML」，而 v1 是 legacy 格式（顶层键即服务名，不支持 `services:`/`volumes:`/`networks:` 段）。据此，v1 CLI 会把 `services` 当成一个服务名去校验 `backend`/`frontend` 这些「配置项」，典型报错就是 `Unsupported config option for services: 'backend'` 一族（同类报错见 [StackOverflow: Unsupported config option](https://stackoverflow.com/questions/71455439/docker-compose-compose-file-is-invalid-because-unsupported-config-option)、[docker.github.io compose-versioning](https://github.com/docker/docker.github.io-1/blob/master/compose/compose-file/compose-versioning.md)）。
  4. **本机无法定论**：`docker-compose.exe` 实为 Docker Desktop 的 shim，实测 `Docker Compose version v5.5.1`（v2/v5），拿不到真正的 v1 → 该发现是**文档层推断**，不是实跑结论。上一轮 `rd1/review-plan-alignment.md:286`(F-14b) 断言「实际 docker-compose v1 支持」，同样**未给证据**——本批次等于把这个未验证断言**搬进了产品文档**。
- **后果**：只装了 v1 的用户照文档直接 `docker compose` 不存在、`docker-compose up` 又可能直接失败，排查成本高；反过来若 v1 真能跑，这句话也无价值（v1 已 EOL）。
- **修复建议（二选一，任选其一即可关闭）**：
  - 保守改法（推荐，零风险）：`docs/deployment.md:34` → 「Docker Compose | **v2+**（`docker compose`）。本文命令与语法一律以 v2 为准；v1 的 `docker-compose` 已 EOL，**未做兼容性验证**，请勿依赖」。
  - 或补一条验证记录：在 `docs/troubleshooting.md` 增加「用 v1 运行本仓库 compose 文件」条目，附实际输出（并视结果决定是否给 `docker-compose.yml` 加回 `version: "3.9"`）。
- **关闭判定**：NOT CLOSED（需二次改动）

#### L-03 🟡 epic README「未完成项」与「终态验证证据」未随修复批次同步（C-22 形态复发）—— NEW DEFECT

- **位置**：`docs/epics/docker-manager-v1/README.md:77`、`:102`；对照 `:18`（阶段行）、`:75-78`（未完成项表）
- **证据**：
  - `README.md:77`：「Phase 4.6 审查发现（1 🔴 / 20 🟡） | **待修复** | …」——而修复批次已在工作区落地（`git status --short` 显示 29 个修改 + 10 个未跟踪新文件），本报告核实其中 🔴 C-01（`volumes.py:24` 已加 `embed=True`，并有 `test_endpoints_coverage.py:29-45` 回归锁定）与绝大多数 🟡 均已修。
  - `README.md:102`：「后端单元测试 | **66 passed**」——我实跑 `uv run --frozen pytest -q` = **105 passed**；只跑被跟踪的测试文件（`--ignore=tests/test_security.py --ignore=tests/test_endpoints_coverage.py`）= **69 passed**，减去本批次在 `test_files_api.py`/`test_ws_logs.py` 净增的 3 个用例 = 66 → 说明 66 在 HEAD 时**是对的**，是**本批次让它过期**。
  - `:18` 阶段行只到「Phase 4.6 代码审查 ❌ NEEDS FIXES」，没有「修复轮次」与「Rd2 重审」行。
- **后果**：这正是上一轮 C-22 的形态——看板自述与实际不符。若本批次提交时不同步，重审结论与看板会互相矛盾。
- **修复建议（拟改文字，与修复提交同一 commit 落盘）**：
  - `README.md:77` 状态列 → `**Rd2 已修复（未提交批次）**`，说明列 → 「🔴 C-01 与 🟡 主体已修；跨站守卫 / E2E 门禁 / .dockerignore / compose 变量化 / WS 节流与自动重连见 `rd2/` 三份重审报告；未关闭项见各报告」。
  - `README.md:102` → 「后端单元测试 | **105 passed**（Rd2 实测 `uv run --frozen pytest -q`）」。
  - `:18` 之后补两行：「Phase 4.6 修复 | 2026-09-11 | R6 修复批次：C-01…C-21 主体修复，详见 `test-review/rd2/`」「Phase 4.6 重审(Rd2) | 2026-09-11 | 三路隔离透镜重审，Verdict 见 `test-review/rd2/`」。
- **关闭判定**：NOT CLOSED（提交前必须改，属「看板 vs 实际」硬一致性要求）

#### L-04 🟢 根 `README.md:234` 测试数量同样过期 —— NEW DEFECT（低）

- **位置**：`README.md:234`「# 后端单元测试（66 个）」
- **证据**：同上，实测 105 passed（本批次新增 `test_security.py` 22 例 + `test_endpoints_coverage.py` 14 例 + 改造 3 例）；对照 `README.md:196-198` 的 `e2e_verify.py`「18 项」**仍然正确**（`EXPECTED_CHECKS = 18`）。
- **修复建议**：`README.md:234` → 「# 后端单元测试（105 个）」。
- **关闭判定**：NOT CLOSED（一行）

#### L-05 🟢 `scripts/requirements-verify.txt` 未被任何文档引用（契约 3 的文档层缺口）—— NEW DEFECT

- **位置**：`docs/development.md:126-141`、`docs/deployment.md:230-235`、`docs/troubleshooting.md:262-266`、`README.md:231-245`；对照 `scripts/requirements-verify.txt:1-22`
- **证据**：全仓 grep `requirements-verify` 的命中只出现在 `scripts/` 三个脚本与依赖文件自身（以及上一轮审查报告里），**文档零命中**。而 `docs/development.md:137` 恰恰是教人跑 `ui_verify.py` 的那一节，`deployment.md:234` 也是。
- **后果**：换机器克隆后按文档执行 → `ImportError: playwright` → 新加的中文提示会兜住（C-20 已闭），但用户仍需自行发现依赖文件；且 `docs/development.md:137` 的描述「收集页面报错 / 控制台报错 / 失败请求」已落后于脚本（现在还会**判定** console warning 与端口断行并据此退出非零），属同一处的说明漂移。
- **修复建议**：
  - `docs/development.md:137` 之前（同一代码块内）插入一行：`# 首次先装验证依赖：pip install -r scripts/requirements-verify.txt`；
  - `docs/development.md:137` → 「逐页截图 + **判定**页面异常/控制台 error+warning/失败请求/端口断行，任一非空即退出码 1」；
  - `deployment.md:232-235` 与 `troubleshooting.md:264-266` 同样补一行安装提示。
- **关闭判定**：PARTIAL（脚本层已闭，文档层未闭）

---

### Code quality

#### L-06 🟡 错误帧协议没有判别字段：容器打印单行 JSON 日志时会被当成协议帧丢弃 —— NEW DEFECT / JUDGEMENT CALL

- **位置**：后端 `backend/app/routers/ws.py:98`（`send_json({"error": "no container"})`）、`:226`（`{"error": f"no such container: {container}"}`）；前端 `frontend/src/utils/ws.ts:24-39`（整帧 parse 成含非空 `error` 字符串的对象即判定为协议帧）、`ContainerLogs.vue:212-219`（判定后 **return**，不再当日志渲染）；E2E `scripts/e2e_verify.py:261-279`
- **证据**：`utils/ws.ts:27` 的判定是「整帧 trim 后以 `{` 开头、以 `}` 结尾 + JSON 对象 + `error` 为非空字符串」。后端每 100ms 把窗口内的行用 `\n` 拼成一帧（`ws.py:128`）。**当某窗口内恰好只有一行、且该行本身就是这种 JSON 时**（结构化日志很常见，如 `{"error":"upstream timeout","level":"error"}`），前端 `parseServerErrorFrame` 返回非 null → `ContainerLogs.vue:217` 弹「无法获取日志」并 `return`，**真实日志行被吞掉**；E2E 同样会把它判为「服务端控制帧报错」→ 整项 FAIL，即使通道完全正常。
- **对照**：旧行为是把协议帧当日志行渲染（C-19a），本批次翻转成「JSON 日志被当协议帧」——同一个歧义的另一面。代码注释（`utils/ws.ts:16-20`）只论证了「批多行的帧不会 parse 成 JSON」，**遗漏了单行帧**这一分支。
- **触发条件（不夸大）**：需要该 100ms 窗口内**只有**这一行且它就是该形状；高频日志容器不会被误判。因此记 🟡 而非 🔴。
- **修复建议（任选，推荐 A）**：
  - **A. 加判别字段（三层一次改完）**：后端 `ws.py:98` → `await ws.send_json({"error": "no container", "dockermgr": "error"})`，`:226` 同理；前端 `utils/ws.ts:37` 改为同时要求 `parsed.dockermgr === 'error'`；E2E `e2e_verify.py:277` 同条件。日志里出现 `{"error":…}` 就不再误判。
  - **B. 用关闭码替代文本帧**：错误帧只作为「人有可读原因」的补充，前端仅在**从未收到过数据帧**时才把 JSON 帧当协议帧（状态机更复杂，不如 A）。
  - 任何改法都要同步 `backend/tests/test_ws_logs.py:38-51`、`test_endpoints_coverage.py:251-268` 与 `utils/ws.ts` 头部（`:10-23`）的协议说明。
- **关闭判定**：NOT CLOSED（本批次新引入）

#### L-07 🟡 `ui_verify.py` 新加的 5 个语义判定打印 FAIL 但不影响退出码 —— NEW DEFECT

- **位置**：`scripts/ui_verify.py:87`、`:115`、`:132`、`:139`、`:172`（`record(...)`）；对照 `:214-216`（退出码只看 5 个 browser 列表）
- **证据**：`record()`（`:42-43`）只 `print`，不写回任何集合；`main()` 的返回值是 `all(not x for x in (page_errors, console_errors, console_warnings, failed_requests, port_breaks))`。于是「容器列表渲染出行 0 行」「运行弹窗不显示预设提示」「MySQL 预设没填满表单」「重启策略显示英文 Select」「终端抽屉没渲染出内容」这 5 类**会出现 `[FAIL]` 行却仍以 0 退出**——门禁自述（`:6-7` “Exits 1 when anything the browser reported is a defect”）虽只承诺 browser 层，但脚本输出与退出码不一致是上一轮 C-11 的同型假绿。
- **修复建议**：`record()` 内把失败写入一个全局 `failures: list[str]`，`:214` 改为 `return 0 if (not failures and all(not x for x in (...))) else 1`（约 3 行改动）。
- **关闭判定**：NOT CLOSED

#### L-08 🟡 `ui_verify.py` 的 run-dialog 端口断行检查恒为空集（永远 PASS）—— NEW DEFECT

- **位置**：`scripts/ui_verify.py:108-110`（`note_port_breaks(page.locator(".c-port").all_inner_texts(), "run-dialog")`）与注释 `:108-109`「Ports must not break in the middle of a mapping (**here and in the dialog itself**)」
- **证据**：
  1. 步骤 [3] 之前 `:93` 已 `page.goto(f"{BASE}/images")`，此时页面上没有容器列表；
  2. 全仓 `.c-port` **只存在于** `frontend/src/views/ContainersView.vue:49`（元素）与 `:371`（样式）；
  3. 且运行弹窗用的是 textarea 输入端口（`frontend/src/components/RunContainerDialog.vue:39-48`，`el-form-item label="端口映射"`），文件内**没有任何** `c-port` 类名 → 该 locator 恒返回 `[]` → `broken` 恒为 `[]` → `port_breaks` 不会被它写入。
- **后果**：与注释宣称的覆盖面不符，属「看起来在查、实际查不到」的假阳性检查（C-11/C-12 的同型）。
- **修复建议（任选）**：
  - 若确实要查弹窗内端口渲染：给对话框里的端口预览元素加 `class="c-port"`，并把调用改为 `page.locator(".el-dialog .c-port").all_inner_texts()`；
  - 若弹窗本来就只有 textarea、不存在断行风险：删掉 `:108-110` 两行并改注释，只保留 `:89` 容器页那一处（那处是真实有效的）。
- **关闭判定**：NOT CLOSED

#### L-09 🟢 单行空日志会被前端丢弃（`chunk` 空串守卫误伤）—— JUDGEMENT CALL（极低）

- **位置**：`ContainerLogs.vue:176-179`（`appendChunk`：`if (paused.value || !chunk) return`）；后端 `ws.py:124-136`（`pending == [""]` 时 `chunk = ""` 仍会发送）
- **证据**：后端 `flush()` 只在 `not pending and not counter["dropped"]` 时提前返回；若窗口内只有一条空行，`"\n".join([""]) == ""` 会被发出去，前端 `!chunk` 直接 return → 该空行丢失。而 `:126-132` 的注释明确宣称「keeping genuinely empty lines, otherwise blank lines in a batch shift the output」——批内空行确实保住了（`"a\n\nb".split('\n')` = 3 段），只有「整帧就是空行」这一种情况不符注释。
- **修复建议**：后端 `flush()` 里 `if chunk == "": pending.clear(); return`（不发送空帧），或前端改为 `if (paused.value || chunk === null || chunk === undefined) return`。
- **关闭判定**：PARTIAL（可延后，纯显示层）

---

### Architecture

#### L-10 🟡 新增跨站守卫与 `docs/deployment.md:152` 推荐的「前置认证反代」冲突，且该约束未文档化 —— HARD VIOLATION

- **位置**：`backend/app/services/security.py:21-22`、`backend/app/main.py:30-44`、`backend/app/routers/ws.py:85-90`、`:205-210`；对照 `docs/deployment.md:152`、`:129`、`README.md:253-254`
- **证据（逻辑推演 + 可引用依据）**：
  - 守卫放行条件只有三种（`security.py:14-23` 自述）：无 `Origin` → 放行；`Origin` host ∈ `{localhost,127.0.0.1,::1,0.0.0.0}` → 放行；**`Origin` host == 请求 `Host`** → 放行；否则 403（HTTP 写操作）/ 1008（WS）。
  - `docs/deployment.md:152` 明确推荐「必须自己在前置加一层带认证和 HTTPS 的反向代理」，`spec.md:99` 也把 `/api`、`/ws` 定义在 nginx 反代之后。
  - 若该前置代理**改写了 Host**（Apache `ProxyPreserveHost Off` 为默认、或显式 `proxy_set_header Host $proxy_host`），FastAPI 看到的 `Host` 是上游名（如 `127.0.0.1:8088` / `backend:8088`），而浏览器 `Origin` 是 `https://panel.example.com` → 两者不等 → **所有 POST/PUT/DELETE 全部 403、`/ws/*` 全部 1008**，界面表现为「操作全失败 / 终端连不上」，而文档对此**零提示**（本仓库自己的 `frontend/nginx.conf:36,48` 恰好用 `$http_host` 保住了 Host，所以只在**外部前置代理**场景踩雷）。
- **修复建议**：
  1. 文档：`docs/deployment.md §5 安全` 增一条「前置反代必须保留客户端 Host」并给出可复制的 `proxy_set_header Host $http_host;`（或 Apache `ProxyPreserveHost On`）；`docs/troubleshooting.md` 增条目「后置反代后所有写操作 403 / 终端 1008：检查 Host 是否被改写」。
  2. 代码（可选，更稳）：`security.py` 在 `is_same_site` 里接受 `X-Forwarded-Host`（仅当请求来自受信代理段时），或提供 `DM_ALLOWED_ORIGINS` 环境变量白名单。
- **关闭判定**：NOT CLOSED（文档必须补；代码改法可选）

#### L-11 🟡 `Origin host == Host` 放行分支构成 DNS rebinding 通道 —— JUDGEMENT CALL

- **位置**：`backend/app/services/security.py:21-22`（`return request_host is not None and origin_host == request_host`）
- **证据**：攻击者页面位于 `http://evil.example`；若 `evil.example` 的 DNS 被重绑定到 `127.0.0.1`，浏览器发出的 `Origin` 与 `Host` **同时**变成 `evil.example` → 该分支放行 → 恶意页可直接驱动 `docker.sock`（=宿主 root）。这正是「用 Host 与 Origin 互相比对来保护 loopback 服务」的已知缺口；`spec.md:111` 的「仅绑 127.0.0.1」对策**挡不住浏览器作为中介**（这一点 `security.py:3-8` 的模块注释自己也承认）。
- **缓解因素（如实标注）**：Chrome 近版的 Local Network Access / PNA 预检对「公网源 → 私网」有额外限制，且默认部署下该分支**并非必需**（面板只从 `127.0.0.1:8088` 访问，前两个条件已覆盖）。属 JUDGEMENT，不是硬违规。
- **修复建议（任选）**：
  - 默认关闭该分支：仅当设置了 `DM_TRUSTED_HOSTS`（或 `DM_ALLOW_SAME_HOST_ORIGIN=1`）时才启用「同 host 放行」，并在文档说明「暴露到非 loopback 主机名时必须显式配置」；
  - 或改为「`Origin` host 必须命中 `DM_ALLOWED_ORIGINS` 白名单（默认只含 loopback）」。
- **关闭判定**：PARTIAL（需作者判断取舍；若接受现状，请在 `security.py` 模块注释里显式写下这条已知风险与缓解依赖）

#### L-12 🟢 守卫放行「任意端口的 127.0.0.1 源」—— JUDGEMENT CALL（记录）

- **位置**：`security.py:28`（`LOCAL_ORIGIN_HOSTS` 含 `0.0.0.0`）、`:54-55`
- **证据**：`is_same_site("http://127.0.0.1:9999", "127.0.0.1:8088")` → `True`（只看 host、不看 port）。本机任意其他 Web 服务（例如本地 dev server、其他面板）的页面同样可驱动本面板，只要它监听在 loopback 上。注释 `:19-20` 明说是刻意取舍（「whichever port the browser used」），故仅记录。
- **修复建议**：如需收紧，把 `LOCAL_ORIGIN_HOSTS` 的判断改为「host ∈ loopback 且 port ∈ {8088}（可配）」。
- **关闭判定**：PARTIAL（作者取舍）

#### L-13 🟢 WS 跨站守卫分散在各 handler 内，无集中层 —— JUDGEMENT CALL

- **位置**：`main.py:30-44`（HTTP 用中间件集中）+ `ws.py:85-90`、`:205-210`（两处 WS 各自内联）
- **证据**：`@app.middleware("http")` 不覆盖 WebSocket，所以每个 WS 端点都必须自己记得调用 `is_same_site`；目前 2/2 端点都调了（正确），但这是**靠纪律**而非靠结构，新增第三个 WS 端点极易漏。
- **修复建议**：抽 `async def guarded_ws(ws, handler)` 装饰器/依赖，或至少在 `ws.py` 顶部写一行「新增 WS 端点必须调用 is_same_site」的契约注释。
- **关闭判定**：PARTIAL

---

### Testing

#### L-14 🟡 把 console **warning** 判为硬失败，门禁可能长期为红（但**不是**恒定红）—— JUDGEMENT CALL（附生产包级证据）

- **位置**：`scripts/ui_verify.py:53`（收集 warning）、`:206`（判定）、`:214-216`（入退出码）
- **我做的实证（不需要浏览器）**：线上部署的前端产物 `http://127.0.0.1:8088/assets/index-BGeOqOmG.js` 与本地 `frontend/dist/assets/index-BGeOqOmG.js` **SHA256 完全一致**（`F23794B417FECD23D641914ECC8F830B6203A8800ABB5C38339DEE36FB992C9F`，1,255,966 B）→ 我分析的就是用户实际会加载的那份产物。
  - 结论 1（排除最常见的「恒定红」）：Vue esm-bundler 的 feature-flag 告警（`not explicitly defined` / `__VUE_PROD_HYDRATION_MISMATCH_DETAILS__`）**不在产物里**（计数 0/0），`Vue warn`、`Failed to resolve component`、`Missing required prop` 也都为 0，`NODE_ENV`/`production` 字面量均不出现 → 这是**真正的生产构建**，Vue/Element Plus 的 dev 告警已被摇掉，**页面加载时不会固定冒出告警**。
  - 结论 2（残余风险是真实的）：产物里仍有 3 处**活着的** `console.warn` —— ① Element Plus `debugWarn`（`frontend/node_modules/element-plus/es/utils/error.mjs` 里函数体是**裸块**、`console.warn` 无条件保留，非 dev 门控）；② 包装 Vue `warnHandler` 的 `console.warn(...t)`（`ElTreeSelect` 相关）；③ axios `transitional`/`spelling` 的弃用告警（`deprecated since v`）。这些只在「组件被误用 / 传了弃用选项 / Vue 自己告警」时触发——**它们与产品缺陷无关，却会让整条 UI 门禁变红**。
  - 另有 Chromium 侧 `warning` 级消息（网络/第三方策略类）同样无法与真实缺陷区分；本机**无法**实跑确认当前是否有告警（见未验证项）。
- **我的判断**：warning **值得收集并打印**（`:189-191` 已做），但**不宜与 pageerror/console error 同权判失败**。理由是它无法区分「产品坏了」与「第三方库在抱怨」，一旦触发就是长期红灯，会让团队开始无视门禁（比没有门禁更糟）。
- **修复建议**：
  1. 最小改法：`:206` 的 `record("无控制台警告…")` 保留为**输出项**，但从 `:214-216` 的 `all(...)` 里移除；docstring `:6-7` 同步为「console warning 仅报告不判定」。
  2. 或者保留硬判但加**基线白名单**：`WARN_ALLOW = ("Feature flag", "[ElementPlus]", "Third-party cookie")`，仅当出现白名单外的 warning 才失败（推荐这条：既守住「新告警必须解释」的纪律，又不因第三方噪声红灯）。
  3. 若坚持现行严格口径，则必须把「跑之前先人工确认 0 warning」写进 `docs/development.md:137`，否则后续没人知道绿灯意味着什么。
- **关闭判定**：PARTIAL（需作者定策略；当前口径**可运行**但会长期漂红）

#### L-15 🟢 `requestfailed` 判定可能把「导航/取消」误判为失败 —— JUDGEMENT CALL（未验证）

- **位置**：`scripts/ui_verify.py:62-65`（`requestfailed` 收集）、`:208`（判定）
- **证据**：Chromium 对「页面导航时被取消的 XHR」会以 `net::ERR_ABORTED` 触发 `requestfailed`。脚本在 `:93`、`:147`、`:151`、`:157` 连续 `page.goto` 且每页都有 axios 加载请求，存在竞态。**我无法实跑验证**（Playwright 被沙箱拒绝），故只作为风险记录，不断言必然发生。
- **修复建议**：收集时过滤 `net::ERR_ABORTED`（或仅对 `net::ERR_FAILED`/5xx 类失败判失败）；若实跑确无此现象，可维持现状并在注释里写明已排除。
- **关闭判定**：PARTIAL（可选）

---

### Production

#### L-16 🟢 nginx `$http_host` 修复未部署、且无排障条目 —— NEW DEFECT（文档侧）

- **位置**：`frontend/nginx.conf:36`（`/api/`，注释块 `:32-35`）、`:48`（`/ws/`，注释 `:47`）；对照 `docs/troubleshooting.md:198-206`（只有 SPA 回退条目）
- **证据（本轮实测）**：线上仍是修复前行为——`curl.exe -s -o NUL -D - http://127.0.0.1:8088/api/containers/` → `HTTP/1.1 307 Temporary Redirect` + `location: http://127.0.0.1/api/containers`（**端口被吃掉**，指向未监听的 80）。这与 `nginx.conf:32-35` 的新注释所述症状完全一致，反证**线上产物 = HEAD 构建、本批次未部署**。
- **修复建议**：在 `docs/troubleshooting.md` 增一条「所有接口 307 跳到 80 端口 / 尾斜杠路径 404：nginx 用 `$host` 丢了端口，改 `$http_host`」——这是本轮修复里**唯一**一个「症状已复现、根因已定位、修复已写好」的坑，值得进排障手册（现有手册的自我定位就是「记录实际踩过的坑」）。
- **关闭判定**：PARTIAL

#### L-17 🟢 `frontend/.dockerignore:22` 列了 `scripts/ui-shots`，该路径在 frontend 构建上下文里不存在 —— NEW DEFECT（无害）

- **位置**：`frontend/.dockerignore:22`（`scripts/ui-shots`）
- **证据**：`frontend/.dockerignore` 的 `:3-6` 注释说明构建上下文是 `../frontend`（`deploy/docker-compose.yml:23` 亦为 `context: ../frontend`）；截图目录实际在**仓库根**的 `scripts/ui-shots/`（截图文件确在 `scripts\ui-shots\*.png` 下）。故该条为死条目。
- **修复建议**：删除 `:22`，或把截图输出改到上下文内（不建议）——删掉即可，属清理。
- **关闭判定**：PARTIAL（无关紧要）

---

## 四、五个「冻结契约」的全层对账小结

| 契约 | 后端 | 前端 | E2E | 文档/单测 | 结论 |
|------|:--:|:--:|:--:|:--:|:--:|
| ① 失败先发 `{"error": ...}` 文本帧再关闭 | ✅ `ws.py:98-99`（logs，accept 后发）/ `:226-227`（exec，`return` 后 finally 关闭） | ✅ `utils/ws.ts:24-39` 解析；`ContainerLogs.vue:212-218` / `ContainerTerminal.vue:250-257` 各自消费；1000/1008 不做无谓重连（`ws.ts:54-56`） | ✅ `e2e_verify.py:261-279` 识别为控制帧并判 FAIL（`:312-315`、`:358-362`、`:391-395`） | ✅ 单测 `test_ws_logs.py:31-43`、`test_endpoints_coverage.py:251-268` | **一致**（歧义见 L-06） |
| ② `/ws/logs` 单帧多行（`\n`） | ✅ `ws.py:128` 合并、`:21` 100ms 窗口、`:152-154` 有界丢弃 | ✅ `ContainerLogs.vue:178` 拆行；终端**不拆**（PTY 原始流，正确） | ✅ `e2e_verify.py:286` 拆行 + `:287` 过滤 `"... "` 丢弃提示 | ✅ `test_ws_logs.py:74-91`（拆行断言 `:91`） | **一致** |
| ③ E2E 依赖文件路径 | — | — | ✅ 三脚本一致 + `requirements-verify.txt` 声明 playwright/websockets + 中文缺失提示 | ⚠️ 四份文档（development/deployment/troubleshooting/README）**均未引用** | **脚本一致，文档缺引用**（L-05） |
| 附：WS 重连/节流语义 | ✅ `ws.py:21-22,124-144`（flush 线程 + 有界缓冲） | ✅ 指数退避 1s→30s（`ContainerLogs.vue:243-296`、`ContainerTerminal.vue:294-317`），1000/1008 不重试，手动重连重置退避 | — | ⚠️ `spec.md:113` 的「节流/断线重连/防抖」已落地，但**无单测覆盖退避逻辑**（仅 E2E 间接） | **一致，测试偏薄（🟢，非本透镜主责）** |

---

## 五、上一轮报告自身的错误（报告亦为被审对象）

> 特别说明：上一轮 `code-review-report.md` 的**主结论**（C-01…C-22 的存在性与严重度、五个分歧裁决）经我独立复核**未发现实质性错误**，绝大多数事实项我都用命令复现了（见第六节 E-1…E-8）。下列两处为可确证的**局部错误**，不足以推翻结论，但应记录以免被后续引用放大。

**R-L1（🟢，事实错误）** `rd1/review-frontend-deploy.md:190` 写「`docs/troubleshooting.md:21` 亦写『4 轮』」——**不成立**。
实测 `docs/troubleshooting.md:21` 是 `## 镜像相关`（该文件第 21 行内容为二级标题，全文没有「4 轮」字样；含「4 轮」的只有 epic `README.md` 的旧第 21 行）。这正是用户提到的「把不存在的行号/内容当缺陷」教训的复现。
**影响面**：该错误**未**被汇总报告继承——`code-review-report.md:140` 只引用了 `README.md:21`（那处是对的），故未污染 C-22 的结论；但 rd1 透镜报告作为原始证据存档，建议在原文加一行更正批注。

**R-L2（🟢，计数不一致）** `code-review-report.md:109` 标题写「### 🟡 Important（**21**，去重后）」，同一节表格实为 **20 条**（C-02…C-21），而正文 `:28` 与 epic `README.md:18/:77` 都写 **20** → 标题应为 20。

**R-L3（🟢，不构成缺陷，预先排除）** `spec-review/final/spec.md:83` 仍写旧文「容器 CRUD / 启停 / 删除」。这是**设计会审归档件**（epic `README.md:12` 载明「会议关闭、spec 归档至 `spec-review/final/`」），按归档不改的约定**不应修改**，也不构成 spec 自相矛盾复发——工作副本 `spec.md:83/132` 已自洽。**请勿把归档件记为未关闭项。**

---

## 六、我实际运行的命令与真实输出（可核对）

| # | 命令 | 真实结果 |
|:--:|------|---------|
| E-1 | `git log --oneline -12` / `git status --short --untracked-files=all` / `git diff --stat 8149029` | HEAD = `8149029`；工作区 29 改 + 10 未跟踪（含 `backend/app/services/security.py`、`frontend/src/utils/{ws,download}.ts`、`scripts/requirements-verify.txt`、两个新测试文件）；`29 files changed, 1180 insertions(+), 181 deletions(-)` |
| E-2 | `cd backend; $env:UV_CACHE_DIR='D:\桌面\测试\.uv-cache'; uv run --frozen pytest -q` | **`105 passed, 2 warnings in 2.78s`**（2 条 warning 来自 fastapi/starlette 的 DeprecationWarning，与本次改动无关） |
| E-3 | 同上 + `--ignore=tests/test_security.py --ignore=tests/test_endpoints_coverage.py` | **`69 passed`** → 反推 HEAD 为 66，与 epic/根 README 的「66」在 HEAD 时自洽，故「66」是**被本批次弄过期**的 |
| E-4 | `curl.exe -s -o NUL -D - http://127.0.0.1:8088/api/containers/` | `HTTP/1.1 307 Temporary Redirect` + **`location: http://127.0.0.1/api/containers`**（端口丢失）→ 线上 nginx 仍是修复前版本 |
| E-5 | `Invoke-WebRequest http://127.0.0.1:8088/assets/index-BGeOqOmG.js` → SHA256 对比 `frontend/dist/assets/index-BGeOqOmG.js` | 双方均为 `F23794B4…B992C9F`，**逐字节相同**（1,255,966 B）→ 线上前端是生产构建且与本地构建一致 |
| E-6 | 同上产物文本检索：`not explicitly defined` / `__VUE_PROD_HYDRATION_MISMATCH_DETAILS__` / `Vue warn` / `Failed to resolve component` / `Missing required prop` = **0**；`console.warn` = **3 处**（Element Plus `debugWarn`、Vue warnHandler 包装、axios 弃用告警） | 支撑 L-14 的「非恒定红、但存在第三方噪声红灯风险」结论 |
| E-7 | `Get-Content frontend/node_modules/element-plus/es/utils/error.mjs` | `function debugWarn(scope, message) { { … console.warn(error) } }` —— 函数体是**裸块**，`console.warn` 未做 dev 门控 → 生产包里是活的 |
| E-8 | `docker compose -f deploy/docker-compose.yml config` | 通过；输出显示四个变量全部按默认值展开（`DOCKER_HOST: unix:///var/run/docker.sock`、`PORT: "8088"`、`TMP_DIR: /tmp/dockermgr`、`IMAGE_MIRRORS: docker.m.daocloud.io,docker.1panel.live`）→ 与 `.env.example:3-10`、`docs/deployment.md:89-94` 三方一致（C-09 关闭的实证） |
| E-9 | `git check-ignore backend/uv.lock`（无命中）+ `Test-Path backend/a.txt`（absent）+ `git status` 显示 `D  backend/a.txt` | C-22 的 uv.lock 行、C-13 的 `a.txt` 清理**均已落实** |
| E-10 | 构建上下文量化：按各自 `.dockerignore` 规则排除后求和 | `frontend` **26 文件 / 0.16 MB**（对比上一轮实测 118.2 MB）；`backend` 19 文件 / 0.22 MB → C-16 修复**有效**（静态计算，`docker build` 未实跑） |
| E-11 | `docker-compose version` / `docker compose version` | 两者都指向 Docker Desktop 的 shim，均报 `Docker Compose version v5.5.1` → **本机不存在 Compose v1**，L-02 无法实跑定论 |
| E-12 | grep 全仓 `.c-port` / 读 `RunContainerDialog.vue` | `.c-port` 仅存在于 `ContainersView.vue:49,371`；弹窗端口是 textarea（`RunContainerDialog.vue:39-48`）→ L-08 的「恒空集」判定成立 |
| E-13 | 读 `docs/troubleshooting.md:21` | 内容是 `## 镜像相关`，无「4 轮」→ R-L1 成立 |

**副作用披露**：本透镜**未创建/删除任何容器、镜像、网络或卷**；未修改任何产品代码或文档；除本报告外仅新建目录 `test-review/rd2/`。所有 HTTP 探测均为 GET 只读（`/api/health`、`/favicon.ico`、`/`、`/api/containers/`、`/assets/…`）。

---

## 七、未能独立验证（诚实标注）

1. **`scripts/ui_verify.py` / `ui_clipboard_test.py` 未实跑**：沙箱禁止 Playwright 子进程（上一轮为 `PermissionError [WinError 5]`，本会话审批提示禁用，我**未尝试提权**，也未绕道其他方式）。**旁证**：同轮另两路隔离审查者在其报告中各自记录了同一限制（`rd2/review-backend.md:22`、`rd2/review-frontend-deploy.md:443`，均为 `WinError 5` / 命名管道拒绝），三路独立撞同一堵墙，可排除「我这一路环境异常」。因此 **L-14 的「当前是否真有 warning」、L-15 的 `ERR_ABORTED` 是否发生、以及「0 控制台错误 / 0 失败请求」的历史自述**均未获独立验证；我给出的证据只到「生产包里有哪些活的 `console.warn` 调用点」这一层。
2. **`scripts/e2e_verify.py` 未实跑**：它会真实创建/删除容器与镜像，且需要后端处于可创建容器的状态——按既往约定不在被审机器上执行。C-10/C-11 的关闭判定基于**读码 + 逐条数 record()（恰 18）**，不是运行结果。
3. **`docker build` / `docker compose up` 未实跑**（Docker 命名管道被沙箱禁止）→ L-17 与 `.dockerignore` 效果（E-10）是**静态计算**，不是构建实测；`deploy/docker-compose.yml` 的变量化只验证到 `docker compose config` 层。
4. **Compose v1 行为无法实测定论**（E-11）→ L-02 是文档层推断 + 官方格式规则佐证，不是复现实验。
5. **本批次修复全部未部署**：线上后端/前端/nginx 仍是 `8149029` 的构建（E-4/E-5 为证）。因此「修复在真实环境生效」这件事**本轮任何人都无法验证**，必须重建后复跑 E-4 与 `ui_verify`/`e2e_verify` 才能关闭 L-10/L-14/L-16。
6. `libc`/多平台无关的 `frontend/dist` 是否与镜像内构建产物逐字一致**未验证**（只能证明线上产物 == 本地 dist）。

---

## 八、建议修复顺序（本透镜视角）

1. **L-06（🟡，本批次新引入、会吞日志）**：错误帧加 `dockermgr: "error"` 判别字段，三层同步 + 两个单测 —— 改动小、后果明确。
2. **L-03 + L-04（🟡/🟢，看板一致性）**：修复提交**同一 commit** 内更新 epic `README.md:77/:102` 与根 `README.md:234`，并补「修复轮 / Rd2」阶段行 —— 否则 C-22 形态立即复发。
3. **L-10（🟡，HARD）**：`docs/deployment.md §5` 与 `troubleshooting.md` 补「前置反代必须保留 Host」的要求与配置样例（可复制粘贴）。
4. **L-07 + L-08（🟡，门禁真实性）**：`ui_verify.py` 让 5 个语义 `record` 参与退出码；删掉或修好 run-dialog 的端口断行检查。约 5 行改动。
5. **L-14（🟡，门禁策略）**：给 console warning 加白名单（或降级为仅报告），并把口径写进 `docs/development.md:137`。
6. **L-02 + L-05 + L-16 + L-04（文档一批）**：`deployment.md:34` 改为「v1 未验证」；四份文档补 `scripts/requirements-verify.txt` 安装提示；`troubleshooting.md` 增「307 丢端口」与「反代后 403/1008」两条。
7. **L-01 / L-09 / L-11 / L-12 / L-13 / L-15 / L-17（🟢）**：随手清理或在注释中显式记录取舍。

> 本透镜的全部 🟡 关闭后，建议**重建镜像并复跑** `e2e_verify.py`（应得 18/18 且退出码 0）与 `ui_verify.py`（先确认 warning 口径），再据实回填 epic `README.md` 的「终态验证证据」——那才是「修复批次在真实环境生效」的唯一证据。
