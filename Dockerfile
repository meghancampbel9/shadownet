# --- Stage 1: Build frontend ---
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ .
RUN npm run build

# --- Stage 2: Python backend ---
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim
LABEL org.opencontainers.image.source=https://github.com/shadownet-protocol/shadownet-local

ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_NO_DEV=1
ENV PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock ./
# The SDK resolves from the public monorepo git source pinned in uv.lock (needs
# network at build time). TODO: switch to --no-sources once it ships on PyPI.
RUN uv sync --locked --no-install-project

COPY backend/ .
RUN uv sync --locked

# Copy built SPA into /app/static
COPY --from=frontend /build/dist /app/static

RUN mkdir -p /app/data/identity

EXPOSE 8340

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8340"]
