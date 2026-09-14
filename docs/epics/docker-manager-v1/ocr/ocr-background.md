# Docker 管理平台 v1 — 详细设计（spec.md）

> Epic：`docker-manager-v1`
> 阶段：Phase 2 详细设计 · 日期：2026-09-10
> 依赖：`scope.md`（范围锁定）· 状态：草案待设计预审

---

## §1 背景与目标

个人/小团队在 1~3 台主机上管理自有 Docker 的**无状态 Web 面板**。用户打开浏览器，通过界面完成容器/镜像/网络/卷的管理，含实时日志、交互式终端、主机↔容器双向文件拷贝、容器打包成镜像、镜像导出 tar 下载。

**总体原则（对话定案）**：所有动作都通过 Web 界面完成，不依赖命令行；后端所有 docker 操作封装为 API，前端统一提供入口。

**成功标准**：用户在浏览器完成「看容器 → 看日志 → 进入终端 → 文件拷入拷出 → 容器打包镜像 → 镜像导出 tar」完整闭环，全程免登录、免命令行。

---

## §2 设计决策

### D1 技术栈（已确认）
| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | Python 3.12 + FastAPI | 熟悉，开发快 |
| Python 环境 | **uv 虚拟环境**（`uv venv` + `pyproject.toml` + `uv.lock`） | 开发与 Docker 镜像统一用 uv |
| Docker 访问 | `docker` (docker-py) 官方 SDK | 封装 Engine API |
| 前端 | Vue 3 + Vite + TS + Element Plus | 中后台组件齐全 |
| 交互终端 | `xterm.js` | 前端模拟终端 |
| 实时 | WebSocket（FastAPI + 前端） | 日志/终端不轮询 |
| 反向代理 | Nginx | 统一入口，反代 /api 与 /ws |
| 部署 | docker-compose（backend+frontend+nginx） | 一键拉起 |

### D2 后端访问 Docker（架构方案 A）
- 后端容器挂载宿主 `docker.sock`，`DOCKER_HOST=unix:///var/run/docker.sock`。
- 单一 Docker 端点（自用场景）；多主机留 P1（TCP+TLS）。
- ⚠️ 安全：后端容器具宿主机 Docker 完全权限，仅受信任环境，文档显式提示。

### D3 无持久化
平台不落库业务数据，全部实时读 Docker daemon。唯一常量：`config.py`（DOCKER_HOST、临时目录、端口 8088）。

### D4 文件拷贝中转
平台自身在容器内，故 copy 经后端**临时目录中转**：
- 拷入：前端上传 → 后端临时目录 → `put_archive()` 进容器。
- 拷出：`get_archive()` 出容器 → 后端临时 → 前端下载。
- 目录支持打包。

**临时目录策略**（architect A1 修订补充）：
- 位置：后端容器内固定工作目录（如 `/tmp/dockermgr`，可用 volume 持久化）。
- 清理：启动时清空该目录；单次下载完成后即删对应文件；失败残留由启动清兜底。
- 负责模块：`services/files.py`（`copy` 封装目录创建/清理，`main.py` 启动回调触发清空）。

### D5 日志 / 终端走 WebSocket
- 日志：`/ws/logs` 滚动。
- 终端：`/ws/exec` docker exec **tty=true**，双向收发，处理 resize。

### D6 镜像导出流式
`docker save` 调 `StreamingResponse` 流式写文件下载，避免大镜像占内存。

### D7 后端部署清单
- 后端 Dockerfile 内用 **uv 安装依赖**（`uv sync --frozen` 或 `uv pip install`），锁文件复现。
- config.py 从环境变量读取（DOCKER_HOST、PORT）。

---

## §3 数据结构

无业务持久化表。实体全部源自 Docker daemon（**消费**，只读/操作不落册）：

| 实体 | 存储 | 说明 |
|------|------|------|
| 容器 / 镜像 / 网络 / 卷 | Docker daemon | 实时只读 + docker-py 操作 |
| 平台自身配置 | `config.py` / 环境变量 | `backend/app/config.py`：主机、端口、临时目录 |
| 临时文件 | 后端临时工作目录 | 拷贝中转、导出缓冲，启动清 + 下载完成即删（见 D4 策略） |

> 明确：**无新增表**，无数据库服务，无 ORM。

---

## §4 数据流

| 场景 | 数据流 |
|------|--------|
| 容器 CRUD / 启停 / 删除 | HTTP → FastAPI router → docker-py → Docker daemon → 返回模型化 JSON |
| 拉取镜像 | HTTP POST /images/pull → docker-py `pull()`（异步/流进进出） |
| 实时日志 | 前端 WS → `/ws/logs` → docker-py logs(stream=True) → 逐行前向 |
| 交互终端 | 前端 xterm.js → `/ws/exec` → docker exec tty 双向 stdin/stdout |
| 拷入容器 | 前端上传 → 后端临时目录 → `put_archive()` |
| 拷出容器 | `get_archive()` → 后端临时 → 前端下载 |
| 容器打包镜像 | POST commit → docker-py `commit(repo,tag)` |
| 镜像导出 | GET /images/save → `docker save` → StreamingResponse 下载 |

---

## §5 集成与影响

**Nginx 路由**
- `/` → 前端静态资源
- `/api/*` → 反代 backend:8088
- `/ws/*` → 反代 backend WebSocket（配置 `Upgrade` / `Connection` header）

**docker-compose services**：`backend`（挂 socket + 8088）、`frontend`（构建产物给 Nginx）、`nginx`（8088 对外）。

**外部影响**：无外部系统集成，纯对接本机 Docker daemon。

---

## §6 风险与假设

| 风险 | 影响 | 对策 |
|------|------|------|
| socket 高权限 | 高 | 仅受信任环境；文档显式安全提示；**部署强制仅映射 127.0.0.1 访问、禁止后端暴露到 0.0.0.0 公网端口，docker-compose 绑定 `127.0.0.1:8088`** |
| 大镜像导出内存 | 中 | StreamingResponse 流式 |
| 长日志/高并发 WS | 中 | 消息节流、断线重连、防抖 |
| exec 需 TTY / resize | 中 | tty=true、处理 resize |
| docker-py 与 daemon 版本 | 低 | 稳定版 docker-py，文档标注兼容范围 |

**假设**：供使受信任单机环境；浏览器现代（支持 WebSocket）；宿主机有 `/var/run/docker.sock` 可挂载。

---

## §7 不在范围（v1 明确排除）

- 登录、多用户、权限/审批流
- Compose/可视化编排
- 镜像仓库管理（registry）
- Swarm / 集群编排
- 监控 CPU/内存/网络曲线（P1）
- 多宿主机接入（P1）
- 镜像导入 docker load（v1.1）
- 容器参数细节查看/启动配置编辑（v1.1）