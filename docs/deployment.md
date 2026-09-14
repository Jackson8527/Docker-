# 部署文档

面向自托管场景的完整部署说明。

---

## 1. 部署架构

```
                 ┌─────────────────────────────────────────────┐
  浏览器 ──────► │  dockermgr-frontend  (nginx)                │
  127.0.0.1:8088 │    ├── /         → Vue 3 静态文件            │
                 │    ├── /api/*    → 反代到 backend            │
                 │    └── /ws/*     → 反代到 backend (WS 升级)   │
                 └───────────────┬─────────────────────────────┘
                                 │ 容器内网络（不发布端口）
                 ┌───────────────▼─────────────────────────────┐
                 │  dockermgr-backend  (FastAPI + uvicorn)      │
                 │    └── /var/run/docker.sock  ← 挂载宿主机     │
                 └───────────────┬─────────────────────────────┘
                                 ▼
                          Docker 守护进程
```

两个容器，后端**不发布端口**，宿主机上只有一个入口 `127.0.0.1:8088`。

---

## 2. 前置条件

| 项 | 要求 |
|----|------|
| Docker Engine | 20.10+ |
| Docker Compose | v2（`docker compose`）。v1 的 `docker-compose` 已 EOL，**未做兼容性验证**；本文命令与语法一律以 v2 为准 |
| 权限 | 当前用户能访问 `docker.sock`（在 `docker` 组内，或 root） |
| 磁盘 | ≥ 2 GB（基础镜像 + 构建缓存）；若要拉大镜像另算 |
| 网络 | 能访问 Docker Hub 或已配置镜像源 |

确认：

```bash
docker version
docker compose version
docker info | grep -i "server version"
```

---

## 3. 快速部署

```bash
cd docker-manager/deploy
docker compose up -d --build
```

首次构建会依次拉取 `ghcr.io/astral-sh/uv`、`python:3.12-slim`、`node:20-alpine`、`nginx:alpine` 并编译前端。视网络情况 **2–10 分钟**。

> **注意**：前端构建（`vite build`）比较吃资源，低配机器上这一阶段可能超过 5 分钟。命令看起来「卡住」是正常的。

查看状态与日志：

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
```

看到两个容器都是 `Up` 后，浏览器打开：

```
http://127.0.0.1:8088
```

---

## 4. 配置

### 4.1 用 `.env` 覆盖

在 `deploy/` 目录下创建 `.env`（compose 会自动读取）：

```bash
cd docker-manager/deploy
cp ../.env.example .env
```

### 4.2 变量说明

| 变量 | 默认 | 说明 |
|------|------|------|
| `DOCKER_HOST` | `unix:///var/run/docker.sock` | Docker 守护进程地址 |
| `PORT` | `8088` | 后端容器内监听端口，无需改动 |
| `TMP_DIR` | `/tmp/dockermgr` | 文件传输临时目录，容器启动时清空 |
| `IMAGE_MIRRORS` | `docker.m.daocloud.io,docker.1panel.live` | 镜像拉取降级源 |

**关于 `IMAGE_MIRRORS`**

国内环境下 `registry-1.docker.io` 经常不可达。后端策略是：

1. 先用原始镜像名拉取；
2. 失败且判定为「仓库不可达」时，按顺序对每个镜像源重试；
3. 成功后**自动打回原始标签**（`mysql:latest`），并删掉临时标签。

所以拉完之后 `docker images` 里看到的仍是正常名字。

镜像源用环境变量配置，写进 **`deploy/.env`**（与 `docker-compose.yml` 同目录；**根目录的 `.env` 不会被 compose 读取**）。注意 `.env` 是「键=值」格式，**不要写 YAML 的列表横线**——写成 `- IMAGE_MIRRORS=` 会让 compose 直接拒绝启动（`key cannot contain a space`）。

想关闭降级（留空即保持空值，后端判定为「无镜像源」）：

```bash
IMAGE_MIRRORS=
```

想换成自己的私有仓库：

```bash
IMAGE_MIRRORS=harbor.example.com,mirror.aliyuncs.com
```

> 这里必须用单横线形式 `${IMAGE_MIRRORS-…}`（`docker-compose.yml` 已是此写法）：若用 `${IMAGE_MIRRORS:-…}`，compose 会把「留空」当成「未设置」而套回默认镜像源，上面这种「留空关闭降级」就会失效。

> 私有仓库需带完整路径前缀（如 `harbor.example.com/library`），后端只做「把仓库域名插到镜像名前」这一件事。

**关于构建时的外网依赖**

`backend/Dockerfile` 用 **PyPI** 安装 uv（不再 `FROM ghcr.io/astral-sh/uv`）。原因：受限网络下 ghcr.io 的 token 端点可能 TLS 握手超时，会让整个 `up -d --build` 在第一步就失败，而 PyPI 通常可达。构建阶段的外网访问由 **Docker 守护进程**决定，和应用内的 `IMAGE_MIRRORS` 无关。

- 正常网络：`docker compose -f deploy/docker-compose.yml up -d --build` 直接可用。
- PyPI 慢或不通：覆盖索引即可（注意用 `=` 传参）：
  ```bash
  docker compose -f deploy/docker-compose.yml build \
    --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple backend
  ```
- uv 版本钉在 `backend/Dockerfile` 的 `ARG UV_VERSION`（当前 `0.12.0`）。

### 4.3 换监听地址 / 端口

编辑 `deploy/docker-compose.yml`：

```yaml
  frontend:
    ports:
      - "127.0.0.1:8088:80"     # ← 改这里
```

- 换端口：`"127.0.0.1:9090:80"`
- 允许局域网访问：`"0.0.0.0:8088:80"` ← **危险，务必先读第 5 节**

改完 `docker compose up -d` 即可（无需重新构建）。

---

## 5. 安全

**这个平台没有登录，任何能访问到页面的人都能完全控制你的 Docker——等价于宿主机 root。**

因此：

- 默认只绑定 `127.0.0.1`，**只能本机访问**。
- 后端挂载了 `docker.sock`，这是设计使然（管理 Docker 必须如此），但也意味着容器逃逸等于宿主机沦陷。

**远程访问的推荐做法——SSH 隧道**，不要改 `ports`：

```bash
ssh -L 8088:127.0.0.1:8088 user@your-server
```

然后在本机浏览器打开 `http://127.0.0.1:8088`。

**绝对不要**直接把端口暴露到公网。如果确实需要，必须自己在前置加一层带认证和 HTTPS 的反向代理。

> **自建反向代理的前提**：后端带着**跨站请求守卫**（`backend/app/services/security.py`）。浏览器发来的 `POST/PUT/PATCH/DELETE` 与 `/ws/*` 握手，若 `Origin` 的 host 既不是 `localhost`/`127.0.0.1`/`::1`，也不等于**这次请求的 `Host`**，就会被 **HTTP 403 / WS 1008** 拒绝（不带 `Origin` 的非浏览器客户端不受影响，例如 curl 与验证脚本）。
>
> 所以自己加反代时**必须保留客户端的 Host 头**：
>
> ```nginx
> proxy_set_header Host $http_host;   # 用 $http_host，$host 会丢掉端口号
> ```
>
> Apache 的 `ProxyPreserveHost` 默认为 `Off`，需显式 `ProxyPreserveHost On`，否则所有写操作都会被 403。若确实要用另一个域名访问，请把该域名加入守卫（`security.py` 的判定），不要绕成「只要不带 Origin 就放行」。

---

## 6. 升级

```bash
cd docker-manager
git pull
cd deploy
docker compose up -d --build
```

只改了前端时，可以只重建前端以省时间：

```bash
docker compose up -d --build frontend
```

数据不会被影响——平台本身不持久化任何状态，所有信息都实时来自 Docker。

---

## 7. 备份与迁移

平台**没有自己的数据**，所以「备份」指的是备份你用它管理的容器数据：

```bash
# 备份具名卷
docker run --rm -v myvolume:/data -v $(pwd):/backup alpine \
  tar czf /backup/myvolume.tar.gz -C /data .

# 恢复
docker run --rm -v myvolume:/data -v $(pwd):/backup alpine \
  tar xzf /backup/myvolume.tar.gz -C /data
```

迁移到新机器：

1. 新机器装好 Docker；
2. 拷贝 `docker-manager` 目录（或 `git clone`）；
3. `cd deploy && docker compose up -d --build`；
4. 用界面重新创建容器，或在旧机器导出镜像（界面「导出」按钮）再在新机器导入：

```bash
docker load -i image.tar
```

---

## 8. 卸载

```bash
cd deploy
docker compose down                 # 停容器，保留镜像
docker compose down --rmi local     # 连构建的镜像一起删
docker compose down -v              # 连匿名卷一起删
```

平台不会删除你用它管理的其他容器/镜像/卷，需要的话在界面里手动清。

---

## 9. 部署后验证

```bash
# 1. 后端健康检查（经由 nginx，验证反代链路）
curl -s http://127.0.0.1:8088/api/health
# 期望：{"status":"ok"}

# 2. 容器列表能取到数据
curl -s http://127.0.0.1:8088/api/containers | head -c 200

# 3. 后端确实连上了 Docker
docker compose exec backend uv run python -c \
  "import docker; print(docker.from_env().version()['Version'])"
```

自动化验证（需要真实 Docker）：

```bash
pip install -r scripts/requirements-verify.txt   # 验证脚本自己的依赖（playwright、websockets）
python scripts/e2e_verify.py        # 18 项端到端，含创建/删除真实容器
python scripts/ui_verify.py         # 浏览器逐页截图 + 报错收集
```

`e2e_verify.py` 覆盖：健康检查、容器增删启停、端口可读性、镜像列表、网络与卷、文件双向传输、commit、镜像导出、从镜像运行容器、错误参数返回 400、WS 日志、WS 终端输入回显、**PTY 尺寸联动**（`stty size`）、以及清理。

---

## 10. 常见问题

见 [`troubleshooting.md`](troubleshooting.md)，里面记录了实际踩到的坑，包括：

- Docker Hub 不可达导致拉取失败
- 拉大镜像时 nginx 60 秒超时（504）
- 上传超过 1MB 的文件报 413
- 容器列表 500
- 终端显示乱码 / 无法复制粘贴
