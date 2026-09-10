# Backend build with uv (spec D7)
FROM ghcr.io/astral-sh/uv:latest AS uv
FROM python:3.12-slim

COPY --from=uv /uv /uvx /bin/

WORKDIR /app
COPY pyproject.toml uv.lock ./
COPY app ./app

# Use locked deps via uv for reproducibility (spec D7)
RUN uv sync --frozen --no-install-project

EXPOSE 8088
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8088"]