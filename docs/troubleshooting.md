# 排障手册

这里记录的都是**实际遇到过并已解决**的问题，不是设想出来的。

---

## 快速定位

```bash
cd deploy
docker compose ps                    # 两个容器是否都 Up
docker compose logs --tail=50 backend
docker compose logs --tail=50 frontend
curl -s http://127.0.0.1:8088/api/health     # 期望 {"status":"ok"}
```

浏览器按 F12 看 Network 和 Console：**后端报错看 Network 的响应体，前端白屏看 Console。**

---

## 镜像相关

### 拉取镜像失败 / 一直转圈

**症状**：点「拉取」后长时间无响应或报错，`docker pull` 也超时。

**原因**：国内网络下 `registry-1.docker.io` 经常不可达。可以用 `curl` 确认：

```bash
curl -s -o /dev/null -w "%{http_code} %{time_total}s\n" --max-time 10 https://registry-1.docker.io/v2/
# 不可达时输出：000 8.000s
```

**已内置的处理**：后端会自动降级到 `IMAGE_MIRRORS` 配置的镜像源，成功后打回原始标签。可在界面「镜像」页看到当前配置的镜像源。

**换镜像源**：编辑 `deploy/docker-compose.yml`：

```yaml
- IMAGE_MIRRORS=docker.m.daocloud.io,docker.1panel.live
```

改完 `docker compose up -d`（改环境变量不需要 `--build`）。

**注意**：`docker info` 里的 `Registry Mirrors` 是 **daemon 级**配置，和这里的**应用级**降级是两回事。两者可以同时为空而应用仍能工作。

### 拉取大镜像时页面报 504

**症状**：拉 `mysql:latest`（1.3GB）时，页面在**正好 60 秒**时报网关超时。

**原因**：nginx 默认 `proxy_read_timeout 60s`，而拉取可能要几分钟。

**已修复**：`frontend/nginx.conf` 里已把 `/api/` 和 `/ws/` 的超时改成 3600s，并且关掉 `proxy_buffering`。

如果你改过 nginx 配置又遇到这个问题，检查这几行是否还在：

```nginx
proxy_connect_timeout 60s;
proxy_send_timeout    3600s;
proxy_read_timeout    3600s;
proxy_buffering       off;
```

### 导出镜像时中断 / 转圈不动

同上，属于长连接。另外确认后端用的是流式响应——导出**不在服务器落盘**，所以几十 GB 的镜像也能导。

如果前端仍然中断，检查 `frontend/src/api/index.ts` 里导出用的是不是 `NO_TIMEOUT`（`{ timeout: 0 }`）。axios 默认 30 秒超时会先于后端断开。

---

## 文件传输

### 上传稍大的文件报 413

**症状**：拷贝超过 1MB 的文件到容器，报 `413 Request Entity Too Large`。

**原因**：nginx 默认 `client_max_body_size 1m`。

**已修复**：`nginx.conf` 里设为 `client_max_body_size 0`（不限制）。

### 拷贝目录失败

拷贝目标路径必须以 `/` 结尾，且目标目录要存在。容器里没有 `tar` 命令时也会失败（后端用 `tar` 流传输）——`alpine` 默认有 `tar`，`distroless` 类镜像没有。

---

## 容器列表

### 页面报 500，日志里 `No such image: sha256:...`

**症状**：容器列表整页 500，后端日志出现 `ImageNotFound: No such image: sha256:ca1f...`。

**原因**：容器的镜像被删了（悬空引用）。**重建 `dockermgr-backend` 自己时必然触发**——旧容器还在，它引用的旧镜像已经被新构建覆盖。

**已修复**：`_image_name()` 依次尝试 `cont.image.tags` → `attrs["Config"]["Image"]` → 短镜像 ID，不再直接抛异常。

如果又出现，说明有别的地方直接用了 `cont.image.tags`，要加同样的兜底。

### 端口列显示成 `127.0.0.1:17474-` / `>7474/tcp` 这种断开的片段

**原因**：端口列表按分隔符整体切分，把一个端口号从中间切断了。

**已修复**：改成逐行解析，并且对 IPv4/IPv6 重复绑定去重。

---

## 终端

### 终端显示乱码 / 排版错乱 / 看不清

**根因**：PTY 尺寸没同步。xterm 按实际像素算出行列数，但容器里的 PTY 一直是默认 **80×24**，两者对不上就会错位。

**判断方法**：在容器终端里执行

```bash
stty size
```

正常应输出类似 `53 134`（行 列），要和终端状态栏显示的尺寸**一致**。

**已修复**：前端 `fit()` 之后会发 `{"type":"resize","cols":N,"rows":N}`，后端调 `exec_resize`。

如果又不对了，检查：
1. `fit()` 是否因为容器尺寸为 0 而提前返回（抽屉动画未结束时 `clientWidth` 是 0，代码里特意做了保护）；
2. `ResizeObserver` 是否正常触发；
3. 后端 `exec_resize` 是否收到消息。

### Ctrl+C 复制不了、Ctrl+V 粘贴不了

**根因**：xterm 自己**不实现**剪贴板快捷键，只依赖浏览器原生 `copy`/`paste` 事件；而它的默认键盘处理会用 `preventDefault` 把这些键**消费掉**，消费掉按键**恰好会阻止浏览器发出原生事件**——于是彻底失效。

**已修复**：`ContainerTerminal.vue` 里用 `attachCustomKeyEventHandler` 显式接管：

- `Ctrl+C`：有选中 → 复制并吞掉按键（**不再同时发 `\x03` 打断你的命令**）；无选中 → 保留 SIGINT
- `Ctrl+V`：返回 `false` 让浏览器发出原生 `paste` 事件，交给 xterm 自己处理
- 右键：粘贴

> **改这里时特别注意**：`Ctrl+V` **不要**自己再手动粘贴一遍。返回 `false` 本身就会让原生 `paste` 事件触发，再手动粘一次会导致**文本被发送两次**（屏幕上会看到 `echo Xecho X`）。这个坑踩过。

验证：

```bash
python scripts/ui_clipboard_test.py
```

必须**有头**运行（headless Chrome 不接系统剪贴板，会假失败）。

### 终端连不上 / 输入没反应

依次检查：

1. 容器里有没有 `/bin/sh`？distroless 类镜像没有，进不去是正常的。
2. 容器是 `running` 吗？已停止的容器无法 exec。
3. nginx 的 `/ws/` 是否配了 WebSocket 升级头：

```nginx
proxy_http_version 1.1;
proxy_set_header Upgrade    $http_upgrade;
proxy_set_header Connection "upgrade";
```

4. 后端建 exec 时 `stdin=True` 有没有传？**`stdin` 默认是 `False`**，忘了传就会「连上了但打什么都石沉大海」。

### 日志页面卡住 / 整个服务无响应

**根因**：`container.logs(follow=True)` 是**阻塞生成器**，直接在 async 函数里迭代会冻死事件循环——影响的是整个服务，不只是这个连接。

**已修复**：放到工作线程里跑，用 `run_coroutine_threadsafe` 把数据送回事件循环。

---

## 部署与构建

### `docker compose up --build` 看起来卡住

**正常现象**。前端 `vite build` 比较吃资源，低配机器上这一步可能超过 5 分钟，加上拉基础镜像，首次整体 2–10 分钟很正常。

想确认没死：另开一个终端看

```bash
docker compose logs -f frontend
```

### 构建时拉基础镜像失败

`python:3.12-slim`、`node:20-alpine`、`nginx:alpine`、`ghcr.io/astral-sh/uv` 都要从网上拉。构建阶段的镜像源由 **Docker daemon** 决定，和应用内的 `IMAGE_MIRRORS` 无关。

配置 daemon 级镜像源（`/etc/docker/daemon.json`）：

```json
{
  "registry-mirrors": ["https://docker.m.daocloud.io"]
}
```

改完 `sudo systemctl restart docker`。

### 前端刷新页面报 404

SPA 路由需要 history 回退。确认 `nginx.conf` 里有：

```nginx
location / {
    try_files $uri $uri/ /index.html;
}
```

### 页面能开但所有接口都失败

说明 nginx 起来了但反代不通。检查：

```bash
docker compose exec frontend wget -qO- http://backend:8088/api/health
```

不通就是两个容器不在同一网络，或 backend 没起来。

**注意**：`deploy/docker-compose.yml` 里 backend 用的是 `expose` 而不是 `ports`，这是**故意的**——后端不对外暴露，唯一入口是 nginx。

---

## 权限

### `Permission denied` 访问 docker.sock

```bash
sudo usermod -aG docker $USER
newgrp docker      # 或重新登录
```

确认：

```bash
docker info > /dev/null && echo "OK"
```

### 改了 `ports` 后局域网还是访问不了

检查防火墙，并确认绑定地址确实改成了 `0.0.0.0`。

> **强烈建议不要这么做。** 这个平台没有登录，能访问页面就等于能完全控制宿主机 Docker。远程访问请用 SSH 隧道：
>
> ```bash
> ssh -L 8088:127.0.0.1:8088 user@server
> ```

---

## 还是不行？

收集这些信息：

```bash
cd deploy
docker compose ps
docker compose logs --tail=100 backend > /tmp/dm-backend.log
docker compose logs --tail=100 frontend > /tmp/dm-frontend.log
docker version
docker info | head -30
```

再跑一遍自动化验证，它会明确指出是哪一层出问题：

```bash
python scripts/e2e_verify.py     # 后端 + Docker 层
python scripts/ui_verify.py      # 浏览器层（含页面报错）
```
