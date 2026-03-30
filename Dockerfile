FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

# Node.js(Discord MCP用)
RUN apt-get update && apt-get install -y nodejs npm && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 依存関係を先にインストール（キャッシュ効率UP）
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

CMD ["uv", "run", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]