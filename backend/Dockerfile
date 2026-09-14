# Backend build with uv (spec D7)
#
# 为什么不用 `FROM ghcr.io/astral-sh/uv:latest`：受限网络下 ghcr.io 可能不可达。
# 实测（2026-09-11）：Docker 守护进程拉 `ghcr.io/token?...astral-sh/uv...` 时
# TLS 握手超时，导致 `docker compose up -d --build` 的后端部分整体失败；而同一
# 守护进程访问 PyPI 完全正常（pypi.org / files.pythonhosted.org / 清华 / 阿里
# 镜像均 200）。改为从 PyPI 安装 uv：少一个外部依赖域，且版本被显式钉住
# （原来 `:latest` 意味着同一条命令在不同时间可能装到不同版本的 uv）。
#
# 若连 PyPI 也不通/慢，构建时覆盖索引即可（用 `=` 传参，不影响已有镜像）：
#   docker compose -f deploy/docker-compose.yml build \
#     --build-arg PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple backend
FROM python:3.12-slim

ARG UV_VERSION=0.12.0
ARG PIP_INDEX_URL=https://pypi.org/simple
RUN pip install --no-cache-dir --index-url "${PIP_INDEX_URL}" "uv==${UV_VERSION}"

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app

# Use locked deps via uv for reproducibility (spec D7)
RUN uv sync --frozen --no-install-project

EXPOSE 8088
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]
