# Docker 管理平台（Docker Manager）总体计划

> 版本：v0.1 · 日期：2026-09-10 · 状态：草案待评审
> 需求已澄清：个人/小团队自用、Python(FastAPI)+Vue、核心管理集、Docker 容器化部署、支持「容器→镜像」「镜像→归档导出」。

---

## 1. 项目概述

一个面向**个人/小团队自用**的轻量 Docker 管理平台，通过 Web 界面管理 Docker 的容器 / 镜像 / 网络 / 卷，并提供日志查看、容器打包成镜像、镜像导出为 tar 归档等能力。

平台自身以 Docker 容器化方式部署：前端 (Vue) + 后端 (FastAPI)，后端通过挂载 Docker Socket 或配置 TCP 端点访问宿主机 Docker Engine API。

### 总体原则
- **所有动作都通过 Web 界面完成**：包括容器操作、日志/终端、文件拷贝、镜像导入导出等，均不依赖用户在命令行手工敲 docker 命令；后端把所有操作封装为 API，前端统一提供操作入口。

### 目标用户
- 在 1~3 台主机上管理自有容器的个人开发者 / 小团队。
- 希望用一个不复杂的 Web 面板替代繁琐的 `docker ps` / `docker logs` 命令操作。

---

## 2. 需求范围（v1 核心管理集）

### P0 必须（v1．0 必须交付）
| 编号 | 功能 | 说明 / 验收要点 |
|------|------|----------------|
| F1 | 容器管理 | 列表、详情、启动/停止/重启/暂停/删除、筛选搜索 |
| F2 | 容器日志 | 实时（滚动）+ 历史日志查看、按行数/跟随输出 |
| F3 | 镜像管理 | 列表、详情、删除、拉取镜像（指定名称/标签） |
| F4 | 网络管理 | 列表、创建/删除自定义网络、查看详情与连接状态 |
| F5 | 卷管理 | 列表、创建/删除、查看使用情况 |
| F6 | 容器打包成镜像 | 对指定容器 commit 为镜像，可命名 tag |
| F7 | 镜像导出归档 | 对指定镜像 docker save 导出为 tar，可下载 |
| F8 | 平台自身容器化部署 | docker-compose 一键拉起（前端+后端+Nginx） |
| F9 | 进入运行中容器 | 对运行中的容器打开**交互式终端**（docker exec -it），前端用 xterm.js 模拟终端实时收发 |
| F10 | 主机↔容器双向文件拷贝 | 通过界面把文件**拷入容器**、把容器内文件**拷回主机**（docker cp），支持选择/上传文件与目录 |

### P1 重要（v1．1 或首轮增强）
- 多宿主机管理（多个 Docker 端点接入）
- 监控：CPU/内存/网络实时曲线
- 镜像导入（docker load）
- 容器参数细节（端口映射/挂载/环境变量）查看与编辑启动配置

### 明确不做（v1 排除项，防蔓延）
- 多用户权限系统 / 审批流（自用场景不需要）
- 可视化编排、Compose 编辑部署
- 镜像仓库管理（registry）
- 集群 / Swarm 编排

---

## 3. 技术方案（架构快照）

| 层 | 选型 | 理由 |
|----|------|------|
| 后端 | Python 3.12 + FastAPI | 你有 OpsKnowBase 的 FastAPI 经验，上手快 |
| Python 环境 | **uv 虚拟环境**（`uv venv` + `pyproject.toml` + `uv.lock`） | 统一依赖管理、体积小、可复现 |
| Docker 访问 | `docker` (docker-py) 官方 SDK | 封装 Docker Engine API，开发效率高 |
| 前端 | Vue 3 + Vite + TypeScript | 组件化、生态成熟 |
| UI 库 | Element Plus | 中后台友好、表格/表单/对话框齐全 |
| 实时日志 | WebSocket（FastAPI + 前端连接） | 日志滚动不轮询 |
| 交互式终端 | docker exec + WebSocket + `xterm.js` | 进入运行中容器，前端模拟终端 |
| 反向代理 | Nginx（同容器编排内） | 统一 80 端口入口，转发 /api 与静态资源 |
| 部署 | Docker + docker-compose | 平台自身容器化，一键拉起 |
| 后端访问 Docker | 挂载 `/var/run/docker.sock` 到后端容器 | 单机自用最简方案 |

### 目录结构（前端）
```
docker-manager/
├─ backend/                 # FastAPI 后端
│  ├─ app/
│  │  ├─ main.py            # 应用入口 / 路由注册 / WS
│  │  ├─ config.py          # 配置（Docker URL、上传/导出目录）
│  │  ├─ routers/
│  │  │  ├─ containers.py   # 容器 CRUD + 启停
│  │  │  ├─ images.py        # 镜像 + commit + save
│  │  │  ├─ networks.py
│  │  │  ├─ volumes.py
│  │  │  ├─ files.py         # 主机↔容器 双向文件拷贝（docker cp）
│  │  │  └─ ws.py           # 日志 + exec 终端 WebSocket
│  │  └─ services/          # docker 封装层（docker-py 调用）
│  ├─ requirements.txt
│  └─ Dockerfile
├─ frontend/                # Vue3
│  ├─ src/                  # 视图、组件、api、store
│  ├─ Dockerfile
│  └─ nginx.conf
├─ deploy/
│  └─ docker-compose.yml    # 一键部署
└─ docs/                    # CDM 文档
```

---

## 4. 后端与 Docker 对接方式

**关键决策（ADR）**：v1 后端通过挂载宿主机 Docker Socket 直接操作本机 Docker。

- 后端容器内 `DOCKER_HOST=unix:///var/run/docker.sock`
- docker-compose 中挂载 `/var/run/docker.sock:/var/run/docker.sock`
- 理由：自用场景主机数少、免鉴权、实现简单；多宿主机留待 P1 用 TCP+TLS 扩展。
- 注意：这使后端容器具有宿主机 Docker 完全权限，仅用于受信任环境；文档中明确写明安全提示。

### 文件拷贝的实现要点
- 平台自身在容器里，故**拷入容器**流程：前端上传文件 → 后端存到临时目录 → `docker cp` 进容器指定路径。
- **拷出容器**流程：`docker cp` 容器内路径到后端临时目录 → 前端下载。
- 临时目录通过 volume 或后端工作目录承载，用后清理；支持目录拷贝（打包 tar）。
- 该能力实现为 docker-py 的 `container.get_archive()` / `container.put_archive()`。

---

## 5. Epic 拆分

将整体拆为 4 个 Epic，按依赖顺序推进：

| Epic | 主题 | 依赖 | 阶段对应 |
|------|------|------|---------|
| E1 | 后端骨架 + Docker 服务封装 + 平台自身容器化 | 无 | Phase 1-3 |
| E2 | 容器 & 日志功能（含打包镜像） | E1 | Phase 4-5 |
| E3 | 镜像 / 网络 / 卷管理（含导出归档） | E1 | Phase 4-5 |
| E4 | 前端应用 + 联调 + 部署验证 | E2、E3 | Phase 6-8 |

每个 Epic 内再拆 User Story 与实施任务（见 §6 详细计划）。

---

## 6. 分阶段实施计划（Roadmap）

### 阶段 1：后端地基（Epic E1）
- 初始化 FastAPI 工程、config、健康检查 `/api/health`
- `services/docker.py` 封装 docker-py 客户端（单例、统一异常处理、模型化返回）
- 实现「平台容器化部署」：backend Dockerfile + docker-compose + 前端骨架 Nginx
- **验收**：`docker compose up` 后台能起，`curl /api/health` 返回 ok

### 阶段 2：容器与日志 API（Epic E2）
- 容器列表/详情/启停/删除 API
- 容器日志 API + WebSocket 实时日志
- 容器 commit 打包成镜像 API
- 交互式终端：docker exec + WebSocket 转发 stdin/stdout（供前端 xterm.js 接入）
- 文件双向拷贝 API：拷入容器（上传→docker cp）、拷出容器（docker cp→下载）
- **验收**：能列出宿主机容器、能对一个容器 commit 生成新镜像、能通过 WebSocket 进入运行中容器执行命令、能经界面把一个文件拷入容器再拷出

### 阶段 3：镜像/网络/卷 API（Epic E3）
- 镜像列表/详情/删除/拉取
- 镜像 save 导出为 tar（文件流下载）
- 网络 / 卷的列表·创建·删除
- **验收**：能导出镜像 tar 并下载；能创建删除自定义网络与卷

### 阶段 4：前端应用（Epic E4）
- 前端骨架 + 路由 + Axios + 登录占位（自用可不做登录）
- 容器管理页（列表+操作+详情）
- 日志面板（WebSocket 实时）+ 交互式终端面板（xterm.js，进入运行中容器）
- **文件拷贝操作入口**（容器详情内：上传文件拷入 / 点选内部文件拷出下载）
- 镜像页（含 commit 为镜像、导出下载/导出）
- 网络页、卷页
- **验收**：打开浏览器完成「看容器→看日志→**进入容器终端**→**文件拷贝进出容器**→打包镜像→导出 tar」完整闭环

### 阶段 5：联调、安全与收尾
- 前后端内网联调、错误提示统一
- WebSocket 断线重连、导出大文件流式可靠
- 安全提示文案、README、验收测试

---

## 7. 关键 API（接口草稿）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | /api/containers | 容器列表（?all=true 含 Stop） |
| GET | /api/containers/{id} | 容器详情 |
| POST | /api/containers/{id}/start · /stop · /restart · /pause · /unpause | 状态操作 |
| DELETE | /api/containers/{id} | 删除（force 参数） |
| GET | /api/containers/{id}/logs?tail=100 | 拉历史日志 |
| WS | /ws/logs?filter=name&stream=stdout | 实时日志流 |
| WS | /ws/exec?container={id} | 交互式终端（docker exec -it，双向收发输入/输出） |
| POST | /api/containers/{id}/copy-to | 把文件/目录拷入容器（docker cp 到指定路径） |
| GET | /api/containers/{id}/copy?path={path} | 把容器内文件/目录拷出供前端下载（docker cp） |
| POST | /api/containers/{id}/commit | 容器打包成镜像 {repo, tag} |
| GET | /api/images | 镜像列表 |
| POST | /api/images/{id}/save | 镜像导出 tar（StreamingResponse） |
| DELETE | /api/images/{id} | 删除镜像 |
| POST | /api/images/pull | 拉取镜像 {name, tag} |
| GET/POST/DELETE | /api/networks | 网络列表/创建/删除 |
| GET/POST/DELETE | /api/volumes | 卷列表/创建/删除 |

---

## 7. 风险与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| Socket 权限导致安全 | 高 | 明确仅自用；文档标注；可配置 backend 端网络访问 |
| 大镜像导出内存 | 中 | 用 StreamingResponse 流式写文件，分批下载 |
| 长日志/高并发 WS | 中 | WS 消息节流、前端防抖、断线重连 |
| exec 终端需 TTY | 中 | docker exec 需分配 tty=true；与 WS 逐字符/块双向转发，处理 resize |
| docker-py 与宿主机 Docker 版本 | 低 | 用稳定版 docker-py，文档标注兼容范围 |

---

## 8. 待办决策（后续与用户确认）
1. 是否需要登录（自用可能不需要，先做占位）。
2. 是否要 Docker WebSocket 部署（前端由 Nginx 分发，需走通长连接）。
3. 后端处理 **8088** 端口映射（已确认）。
4. 确认后进入 CDM Phase 1.7 范围锁定（scope.md）→ v1 首个 Epic 的详细设计与计划。
```