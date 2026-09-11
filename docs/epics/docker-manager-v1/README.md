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

## 交付后的缺陷修复轮次

编码完成后由真机使用与浏览器验证驱动了 4 轮修复，均已合入：

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

> 状态：**已定位，待修复**（见「未完成项」）。

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
| `.gitignore` 忽略 `uv.lock` 导致全新 clone 构建失败 | **待修复** | 详见上文「经验记录 1」。本机可构建，换机器/全新 clone 会失败。 |
| Phase 4.6 代码审查（`cdm-code-review`） | **未执行** | Epic 全部编码已完成后未派发审查者子代理做五段式正式审查。缺陷修复轮次起到了部分作用，但不等于正式审查。 |
| 计划预审遗留 | 已知 | `plan.md` Task 11「打包三个独立视图」在预审时记 Fail（3/4），实际实现已覆盖网络与卷两个视图，未拆成三个独立文件。 |

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
| 后端单元测试 | 66 passed |
| 端到端（真实 Docker） | 18/18 passed |
| 浏览器逐页验证 | 0 页面错误 / 0 控制台错误 / 0 失败请求 |
| 终端复制粘贴回归 | 6/6 passed（含「不发送 SIGINT」与「不重复粘贴」断言） |
| 提交数 | 22 |
| 代码规模 | 后端 Python ~1.7k 行 / 前端 TS+Vue ~2.1k 行 |
