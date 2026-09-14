# Docker Manager

一个自托管的 Docker 管理平台：**在浏览器里管容器、镜像、网络、卷，包括进容器终端和双向传文件。**

为个人 / 小团队自用而做——单机、无登录、部署即用。

```
浏览器 ──► nginx (127.0.0.1:8088) ──┬──► 静态前端 (Vue 3)
                                    └──► /api /ws ──► FastAPI ──► docker.sock ──► Docker
```

---

## 功能

**容器**
- 列表 / 启停 / 重启 / 暂停 / 恢复 / 删除
- **从镜像一键新建容器运行**（内置 MySQL、Redis、Nginx、PostgreSQL、Ubuntu 预设，不会填也能跑）
- **进入容器终端**（真 PTY，支持 vim/top 等全屏程序，自动跟随窗口尺寸）
- 实时日志（stdout/stderr，可切换、可回溯）
- **双向传文件**：主机 → 容器、容器 → 主机（支持整目录打包传输）
- 提交容器为镜像（commit）
- 端口、环境变量、挂载、重启策略全部可在界面配置

**镜像**
- 列表（含标签与镜像 ID）
- 拉取（**Docker Hub 不可达时自动走镜像源降级**）
- 导出为 tar 文件下载
- 删除

**网络 / 卷**
- 列表 / 创建 / 删除

**终端交互**（已实测）
| 操作 | 行为 |
|------|------|
| 鼠标拖拽 | 选中文本 |
| `Ctrl+C` | 有选中→**复制**（不打断命令）；无选中→发送 SIGINT |
| `Ctrl+V` | 粘贴 |
| 右键 | 粘贴 |
| `Ctrl+Shift+C` | 复制（兼容习惯） |

---

## 快速开始

前置：已装 Docker，且当前用户在 `docker` 组（Linux）或有权限访问 `docker.sock`。

```bash
cd deploy
docker compose up -d --build
```

打开 **http://127.0.0.1:8088**

首次构建需拉取 `python:3.12-slim`、`node:20-alpine`、`nginx:alpine` 基础镜像，视网络 2–10 分钟。

停止 / 卸载：

```bash
docker compose down          # 停止并删除容器
docker compose down --rmi local   # 连同构建的镜像一起删掉
```

> 完整部署说明（配置、升级、备份、安全）见 [`docs/deployment.md`](docs/deployment.md)。

---

## 环境变量

配置在 `deploy/docker-compose.yml`，也可用同目录的 `.env` 覆盖（参考根目录 [`.env.example`](.env.example)）。

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker 守护进程地址 |
| `PORT` | `8088` | 后端容器内监听端口（不对外暴露） |
| `TMP_DIR` | `/tmp/dockermgr` | 文件传输临时目录，启动时自动清空 |
| `IMAGE_MIRRORS` | `docker.m.daocloud.io,docker.1panel.live` | 拉取镜像的降级镜像源，逗号分隔；**留空即关闭降级** |

`IMAGE_MIRRORS` 的工作方式：先用原始镜像名拉取，失败且判定为「Docker Hub 不可达」时，按顺序对每个镜像源重试，成功后**自动打回原始标签**并删掉镜像源临时标签。所以界面里看到的永远是 `mysql:latest`，不是 `docker.m.daocloud.io/library/mysql:latest`。

---

## 接口一览

后端同时提供 `/api/*` HTTP 与 `/ws/*` WebSocket，均由 nginx 反代。

### 健康检查
| 方法 | 路径 |
|------|------|
| GET | `/api/health` |

### 容器（`/api/containers`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/containers` | 列表（含状态、端口、镜像名） |
| POST | `/api/containers` | **创建并运行**容器 |
| GET | `/api/containers/{cid}` | 详情 |
| POST | `/api/containers/{cid}/start` | 启动 |
| POST | `/api/containers/{cid}/stop` | 停止 |
| POST | `/api/containers/{cid}/restart` | 重启 |
| POST | `/api/containers/{cid}/pause` | 暂停 |
| POST | `/api/containers/{cid}/unpause` | 恢复 |
| DELETE | `/api/containers/{cid}` | 删除（可带 `force`） |
| POST | `/api/containers/{cid}/commit` | 提交为镜像 |

`POST /api/containers` 请求体（全部字符串均为「自由文本」，后端负责解析，出错返回 400 并带中文原因）：

```json
{
  "image": "mysql:latest",
  "name": "my-mysql",
  "ports": "3306:3306",
  "env": "MYSQL_ROOT_PASSWORD=secret",
  "volumes": "/data/mysql:/var/lib/mysql",
  "command": "",
  "restart_policy": "unless-stopped",
  "auto_start": true
}
```

支持的填空格式：

| 字段 | 格式 | 示例 |
|------|------|------|
| `ports` | `[IP:]主机端口:容器端口[/协议]`，逗号或换行分隔 | `8080:80`、`127.0.0.1:8080:80`、`53:53/udp`、`80`（随机主机端口） |
| `env` | `KEY=VALUE`，每行一个 | `MYSQL_ROOT_PASSWORD=secret` |
| `volumes` | `/主机路径:/容器路径[:ro]`，也支持命名卷，每行一个 | `/data:/var/lib/mysql`、`myvol:/data` |
| `restart_policy` | `no` / `on-failure` / `always` / `unless-stopped` | `unless-stopped` |

### 镜像（`/api/images`）
| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/images` | 列表 |
| GET | `/api/images/pull/mirrors` | 查询当前配置的镜像源 |
| POST | `/api/images/pull` | 拉取（带镜像源降级） |
| GET | `/api/images/{iid}/save` | **导出为 tar 下载**（流式，不落盘） |
| DELETE | `/api/images/{iid}` | 删除 |

### 网络 / 卷
| 方法 | 路径 |
|------|------|
| GET / POST | `/api/networks`、`/api/volumes` |
| DELETE | `/api/networks/{nid}`、`/api/volumes/{vid}` |

### 文件传输
| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/containers/{cid}/copy` | 主机 → 容器，`multipart/form-data`：`dest`（目标目录）+ `file` |
| GET | `/api/containers/{cid}/copy?path=/` | 容器 → 主机，返回 tar 流 |

### WebSocket
| 路径 | 参数 | 说明 |
|------|------|------|
| `/ws/logs` | `filter`（容器名，**前缀匹配**，优先匹配运行中的容器）、`stream`（`stdout`/`stderr`/`both`，默认 `stdout`；`both` 就是界面上的「全部」）、`tail`（返回最近多少行，默认 `100`） | 实时日志 |
| `/ws/exec` | `container`（容器 ID 或名称）、`cmd`（默认 `/bin/sh`） | 交互式终端 |

`/ws/exec` 协议：**服务端 → 客户端是原始终端字节**；**客户端 → 服务端是 JSON 控制帧**：

```json
{"type": "input",  "data": "ls -la\n"}
{"type": "resize", "cols": 134, "rows": 53}
```

（纯文本帧也兼容，会当作 `input` 处理。）

---

## 项目结构

```
docker-manager/
├── backend/                    # FastAPI 后端
│   ├── app/
│   │   ├── main.py             # 应用入口、路由注册
│   │   ├── config.py           # 环境变量 → 设置
│   │   ├── routers/            # containers / images / networks / volumes / files / ws
│   │   └── services/
│   │       ├── docker.py       # docker-py 客户端封装与数据类型
│   │       ├── files.py        # tar 打包解包、临时目录
│   │       └── run_spec.py     # 「自由文本 → docker-py 参数」解析器
│   ├── tests/                  # 137 个 pytest 用例
│   ├── Dockerfile              # uv 构建
│   └── pyproject.toml
├── frontend/                   # Vue 3 前端
│   ├── src/
│   │   ├── views/              # 容器 / 镜像 / 网络 / 卷 四个页面
│   │   ├── components/         # 终端、日志、文件传输、新建容器对话框
│   │   ├── api/index.ts        # axios 封装
│   │   └── utils/error.ts      # 统一错误提示
│   ├── nginx.conf              # 反代 /api、/ws，SPA history 回退
│   └── Dockerfile              # 多阶段：node 构建 → nginx 托管
├── deploy/
│   └── docker-compose.yml      # backend + frontend 两个服务
├── scripts/
│   ├── e2e_verify.py           # 真实 Docker 端到端验证（18 项）
│   ├── ui_verify.py            # 浏览器逐页检查 + 截图 + 错误捕获
│   └── ui_clipboard_test.py    # 终端复制粘贴回归测试
└── docs/
    ├── deployment.md           # 部署文档
    ├── development.md          # 开发文档
    ├── troubleshooting.md      # 排障手册（真实踩过的坑）
    ├── plans/                  # CDM 计划
    └── epics/docker-manager-v1/  # CDM 需求 / 设计 / 演进日志
```

规模：后端 Python ~1.3k 行，前端 TS/Vue ~3.2k 行。

---

## 开发

### 后端

```bash
cd backend
uv sync --extra dev                 # 创建虚拟环境并装依赖
uv run uvicorn app.main:app --reload --port 8088
```

需要能访问 `docker.sock`。Windows 上通过 Docker Desktop 暴露的命名管道或 TCP 端口访问，设置 `DOCKER_HOST` 即可。

### 前端

```bash
cd frontend
npm install
npm run dev                         # Vite 开发服务器，/api 与 /ws 代理到后端
```

### 测试与验证

```bash
# 验证脚本自己的依赖（playwright、websockets）；缺依赖时脚本会给出中文提示
pip install -r scripts/requirements-verify.txt

# 后端单元测试
cd backend && uv run pytest -q

# 端到端（需要真实 Docker 在跑，会真实创建/删除容器）
python scripts/e2e_verify.py

# 浏览器 UI 检查（截图 + 收集页面报错）
python scripts/ui_verify.py

# 终端复制粘贴回归
python scripts/ui_clipboard_test.py
```

> 更详细的约定（测试写法、mock 注意事项、调试技巧）见 [`docs/development.md`](docs/development.md)。

---

## 设计要点与已知约束

**已做的取舍**
- **不做登录**：设计前提是只监听 `127.0.0.1`，通过 SSH 隧道或个人 VPN 访问。**不要直接暴露到公网。**
- **不做持久化**：没有数据库。所有状态都来自 Docker 本身，重启后不丢任何东西。
- **单机**：通过挂载 `docker.sock` 管理本机 Docker，不支持多节点。
- **导出流式**：镜像导出直接流式转发，不在服务器落盘，所以能导几十 GB 的镜像而不撑爆磁盘。
- **后端不对外暴露**：compose 里 backend 只有 `expose`，唯一入口是 nginx。

**已知限制**
- 只监听 `127.0.0.1`。要换地址改 `deploy/docker-compose.yml` 的 `ports`。
- **删除一律是强制删除**：容器删除与镜像删除都固定带 `force`（`docker rm -f` / `docker rmi -f`），界面上没有「是否强制」开关。因此**运行中的容器会被直接停止并删除**（不必先「停止」），**被容器引用的镜像也会被强删**（那些容器随后成为悬空引用）。确认框里会写明这个后果。
- 文件传输走 tar，超大文件（>1GB）会占用较多内存和带宽。
- 终端默认 shell 是 `/bin/sh`。容器里没有 `/bin/sh`（如 distroless 镜像）时无法进入终端。

---

## 文档索引

| 文档 | 内容 |
|------|------|
| [`docs/usage.md`](docs/usage.md) | **使用手册**：界面怎么用、常见任务怎么做、每个页面逐项说明（第一次用面板先看这个） |
| [`docs/deployment.md`](docs/deployment.md) | 部署、配置、升级、备份、安全加固 |
| [`docs/development.md`](docs/development.md) | 本地开发、代码结构、测试约定 |
| [`docs/troubleshooting.md`](docs/troubleshooting.md) | 已踩过的坑与解决办法 |
| [`docs/epics/docker-manager-v1/`](docs/epics/docker-manager-v1/) | 需求范围、详细设计、演进日志 |
