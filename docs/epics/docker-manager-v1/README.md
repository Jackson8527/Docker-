# docker-manager-v1 — Epic 演进日志

> Epic: `docker-manager-v1`（Docker 管理平台 · 核心管理集）

## 演进记录

| 阶段 | 日期 | 说明 |
|------|------|------|
| Phase 1 需求澄清 | 2026-09-10 | 澄清：个人/小团队自用、FastAPI+Vue、核心管理集、Docker 部署；补充进容器终端、双向文件拷贝、全操作走界面 |
| Phase 1 范围锁定 | 2026-09-10 | 产出 `scope.md`；定案：端口 8088、不做登录、Python 用 uv 虚拟环境、后端含 Docker 镜像均统一用 uv |
| Phase 2 详细设计 | 2026-09-10 | 产出 `spec.md`（七段）；设计确认：单机 socket + docker-py、无持久化、WS 日志/终端、流式导出、后端统一 uv |
| 设计会审 | 2026-09-10 | self + architect 两份审查 + 交叉比对，采纳 C1（临时目录策略）+ C2（socket 安全对策），会议关闭、spec 归档至 spec-review/final/ |
| Phase 3 计划 | 2026-09-10 | 生成 `plan.md`（Task 1-12，TDD 红→绿→commit） |
| Phase 4 编码实现 | 2026-09-10 | Task 1-12 全部完成，12 次提交，单元测试 66 passed |
| Phase 4.4 自证 | 2026-09-10 | E2E 脚本 18/18 通过；**由 E2E 发现 2 个真实缺陷**（见下） |
| Phase 4.5 浏览器 E2E | 2026-09-10 | Playwright + 本机 Chrome 逐页验证，0 页面错误 / 0 控制台错误 / 0 失败请求 |
| Phase 6 知识沉淀 | 2026-09-11 | 补齐 `README.md` + `docs/deployment.md` + `docs/development.md` + `docs/troubleshooting.md` |
| Phase 4.6 代码审查 | 2026-09-11 | 三路隔离子代理（后端 / 前端+部署 / 计划对齐+跨层契约）+ 协调者交叉比对，全量 diff 五段式审查。**Verdict：❌ NEEDS FIXES** — 1 Critical / 20 Important / 约 31 Minor（去重后）。OCR 预扫未执行（ocr CLI 未配置 LLM 端点）。见 `test-review/code-review-report.md` |
| Phase 4.6 修复轮 | 2026-09-11 | 21 条（1 🔴 / 20 🟡）逐条修复并自证：后端单测 66 → **124 passed**；**变异测试**证明新断言真会失败；真机 E2E **18/18、退出码 0**；部署后契约探测 **4/9 → 10/10**（卷创建 422→200、跨站写 422→403、nginx 重定向补回 `:8088`、WS 失败帧带上判别字段）。修复批次为**工作区未提交改动**（基线 `8149029`） |
| Phase 4.6 重审（rd2） | 2026-09-11 | 同一模板三路隔离重审：**19/21 关闭**（C-15/C-17/C-22 判 PARTIAL），并新增 27 条发现（含 **5 条 HARD**，其中 **2 条由修复批次自己引入**：错误帧无判别字段、下载预检无超时）→ 触发第二轮修复。见 `test-review/rd2/` |
| Phase 4.6 修复轮 2 | 2026-09-11 | 第二轮修复（判别字段三层一致、长命流批处理回归、exec 错误分类、下载预检超时、paused 禁终端、端点覆盖 14→29 例、`ui_verify` 门禁真实性）+ 部署验证 |
| Phase 4.6 合并复核（rd3） | 2026-09-11 | 独立只读复核 **36 条**：**26 CLOSED / 3 PARTIAL / 7 NOT CLOSED**；新增 12 条发现（含 2 条 HARD）→ **Verdict ⚠️ CONDITIONAL PASS**。见 `test-review/rd3/review-consolidated.md` |
| Phase 4.6 修复轮 3 | 2026-09-11 | 关闭 RD3-01（`staging_dir` 反模式：**正常机器/CI 上该测试文件 6 例全 ERROR**，已用正常机器等价机复现+AST 锁）、RD3-02（`cont.logs()` 建立流阻塞事件循环，实测冻结 **1503ms → 1.6~25ms**）、RD3-04（`ui_verify` 输出标记与退出码一致）、RD3-06（E2E exec 断言不再被 PTY 回显满足）、RD3-11（mock 按 docker-py 7.2.0 真实签名）、RD3-12（真·drop-oldest）；文档侧 RD3-03/05/07/08/10 已修。**RD3-03 记为已知限制** |

## 交付后的缺陷修复轮次

编码完成后由真机使用与浏览器验证驱动了 5 轮修复（R1–R5），均已合入：

| 轮次 | 日期 | 触发 | 缺陷与修复 |
|------|------|------|-----------|
| R1 | 2026-09-10 | E2E 自证 | ① `Container` 无 `.state` 属性导致容器列表 500；② `/ws/logs` 阻塞事件循环冻死整个服务；③ `/ws/exec` 丢弃输入（`stdin` 默认 `False`）；④ PTY 从不 resize，停留 80×24 导致终端显示错乱 |
| R2 | 2026-09-10 | 用户反馈「页面不好看 / 终端显示有问题」 | UI 整体重设计；端口按行解析（修 `127.0.0.1:17474-` 断行）与 IPv4/IPv6 去重 |
| R3 | 2026-09-10 | 用户报告 `mysql` 拉取 500 | Docker Hub 不可达 → 应用级镜像源降级；配 nginx 3600s 超时（修 60s 504）与 `client_max_body_size 0`（修 >1MB 413）；axios 拉取改为不超时 |
| R4 | 2026-09-10 | 用户指出「没有用镜像运行容器的操作」 | 新增「从镜像运行容器」链路：`run_spec.py` 自由文本解析器 + `POST /api/containers` + 运行对话框 + 常用镜像预设 |
| R5 | 2026-09-11 | 用户问「终端里不能复制粘贴？」 | 复制与粘贴**均失效**：xterm 的 `preventDefault` 消费按键 → 浏览器原生 `copy`/`paste` 事件从不触发。改为 `attachCustomKeyEventHandler` 显式接管；**中途引入重复粘贴缺陷并被测试捕获后修正**（见下） |

## 经验记录（值得回看的判断失误）

**1. `.gitignore` 把构建必需的文件挡在了版本控制外**

`.gitignore` 第 5 行写了 `uv.lock`，但 `backend/Dockerfile` 里是：

```dockerfile
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project
```

本机上构建能成功，是因为 build context 是**本地目录**，`uv.lock` 就在磁盘上（183 KB，未跟踪）。但**全新 `git clone` 之后构建会在 COPY 这一步直接失败**。

对照之下 `frontend/package-lock.json` 是**被跟踪**的——前后端处理不一致。

→ **教训**：`.gitignore` 判断依据应当是「这个文件是不是构建/运行必需」，而不是「它看起来像不像生成物」。`uv.lock` 官方建议就是应当提交，正是它保证了 `--frozen` 的可复现性。

> 状态：**已修复（`8149029`）** —— `.gitignore:5-8` 改为显式「uv.lock 是刻意提交」的注释说明，`backend/uv.lock` 已入库；本表的「未完成项」此前未回改（Phase 4.6 审查发现 C-22）。

**2. 用「看起来像」的猜测替代了实测**

前端 digest 列最初直接把 `img.short_id` 当 digest 返回。在**本机**它恰好是对的（本机 Docker 用 containerd 镜像存储，镜像 ID 就等于 manifest digest，`docker images --digests` 可证），但换台机器就错。最终改为读真实的 `attrs["RepoDigests"]`，并删掉冗余的 digest 列。
→ **教训**：巧合正确不是正确，要区分「本机成立」和「普遍成立」。

**3. 为修一个 bug 引入另一个 bug，靠测试兜住**

终端复制粘贴的首次修复中，我让按键处理器返回 `false` 并在其中**手动**执行粘贴。但返回 `false` 本身就已经让浏览器发出了原生 `paste` 事件，于是文本被发送两次（屏幕出现 `echo Xecho X`）。
→ **教训**：这个重复不是靠读代码发现的，是靠**看截图**发现的。测试断言了「不重复」，才把它固定下来。

**4. 假阴性比没有测试更危险**

一度用 headless Chrome 验证剪贴板，得到「粘贴全失败」的结论——而真实原因是 headless 不接系统剪贴板。同样，用 `window.getSelection()` 判断 xterm 选区永远为空（xterm 是内部选区实现）。
→ **教训**：验证工具本身也要验证。改有头运行、改看 `.xterm-selection div` 之后，结论才可信。

**5. mock 必须还原真机形状**

测试 mock 里给 `Container` 加了 `.state`、把 `ports` 写成 list，测试全绿而线上 500。
→ **教训**：mock 照着「真机是什么样」写，不是照着「我觉得它应该什么样」写。这条已写入 `docs/development.md`。

## 未完成项

| 项 | 状态 | 说明 |
|----|------|------|
| `.gitignore` 忽略 `uv.lock` 导致全新 clone 构建失败 | **已修复（`8149029`）** | 上文「经验记录 1」描述的缺陷已在本 diff 内修掉：`.gitignore:5-8` 改为「uv.lock 刻意提交」的说明注释，`backend/uv.lock`（887 行）已入库，`git check-ignore backend/uv.lock` 无命中。**注意：本表此前误标「待修复」，与同 commit 的 `.gitignore` 自相矛盾**（审查发现 C-22）。 |
| Phase 4.6 代码审查（`cdm-code-review`） | **已执行（2026-09-11）** | 三路隔离子代理 + 协调者交叉比对，全量 diff 五段式审查。判定 **❌ NEEDS FIXES**，见 `test-review/code-review-report.md`。 |
| Phase 4.6 审查发现（1 🔴 / 20 🟡） | **已修复（工作区未提交）** | 唯一 Critical「界面创建数据卷必然 422」已修并在**真实环境实测**（`POST /api/volumes` 对象体 `422 → 200`）。三路重审判定 **19/21 关闭**；rd2 判 PARTIAL 的 C-15（端点覆盖，66→124 passed）、C-17（下载预检加 30s 超时 + 取消）、C-22（本表同步）已在第二轮修复中关闭。完整清单与证据见 `test-review/code-review-report.md` §2。 |
| 后端镜像重建（原 E-1） | **已解决** | 原问题：Docker 守护进程拉 `ghcr.io/astral-sh/uv:latest` 的 token 端点 TLS 握手超时 → `up -d --build` 后端部分失败，只能用 `docker cp` 临时把代码送进容器（容器与镜像不一致）。**修法（用户选 A）**：`backend/Dockerfile` 改为从 **PyPI** 安装 uv 并钉版本（`ARG UV_VERSION=0.12.0`，索引可用 `--build-arg PIP_INDEX_URL` 覆盖），彻底去掉 ghcr.io 依赖；`docs/deployment.md` / `docs/troubleshooting.md` 补上前置条件与覆盖方法。**验证**：重建成功、容器已从新镜像重建、容器内 `ws.py`/`security.py`/`main.py` 哈希与工作区源码**逐一 MATCH**，契约探测 10/10、真容器日志 4/4、真机 E2E 18/18 退出码 0。 |
| 计划预审遗留 | 已知 | `plan.md` Task 11「打包三个独立视图」在预审时记 Fail（3/4）。**审查核实：`ImagesView.vue`/`NetworksView.vue`/`VolumesView.vue` 三个文件实际均已独立存在**（commit `7cfa52c`），本表此前对 Fail 原因的描述与事实不符。 |

## 设计会审记录（原始 append 日志）

> 由 review.py 脚本追加，保留原始事件记录。

| # | 日期 | 阶段 | 说明 |
|---|------|------|------|
| 2 | 2026-09-10 | Rd1-Self | 自审完成 |
| 2 | 2026-09-10 | Rd1-Review (architect) | 架构师透镜审查提交 |
| 2 | 2026-09-10 | Rd1-CrossRef | 交叉比对完成 |
| 2 | 2026-09-10 | Rd1-Revision | 采纳 C1+C2：D4 补临时目录清理策略、§6 补 socket 安全对策 |
| 2 | 2026-09-10 | Close | Conference closed. Final design archived |

## 计划预审记录

| 日期 | 阶段 | 结果 |
|------|------|------|
| 2026-09-10 | Prescan-Plan | ⚠️ 3/4（Task 11 打包三个独立视图，严格记 Fail，可进计划评审） |

## 终态验证证据

| 项 | 结果 |
|----|------|
| 后端单元测试 | **137 passed**（Phase 4.6 第三轮修复后实测；编码完成时为 66）。**注意**：此数此前写作 124，而那是「沙箱专属绿」——`test_files_api.py` 的 fixture 在正常机器上会抛 `ValueError: staging_dir did not yield a value`（RD3-01），已在第三轮修复，并用「正常机器等价机」复现+修复验证、AST 结构锁 + 两种 `%TEMP%` 模式双向复跑 |
| 端到端（真实 Docker） | **18/18 passed，退出码 0**（修复轮在修好后的真实部署上复跑；该脚本此前永不返回非零退出码，已修） |
| 部署后契约探测 | **10/10 passed**（卷创建对象体、跨站守卫 403、nginx 重定向保留 `:8088`、WS 失败帧判别字段、health/list/SPA） |
| 浏览器逐页验证 | 0 页面错误 / 0 控制台错误 / 0 失败请求 —— **本行为 Phase 4.5 的历史自述**；修复轮因沙箱禁止 Playwright 未能复跑，但 `scripts/ui_verify.py` 的判定面与退出码已在修复轮加固 |
| 终端复制粘贴回归 | 6/6 passed（同上：Phase 4.5 历史自述，修复轮未复跑） |
| 提交数 | 22 |
| 代码规模 | 后端 Python ~1.7k 行 / 前端 TS+Vue ~2.1k 行 |
