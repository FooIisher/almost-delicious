FROM ghcr.io/astral-sh/uv:0.13.7 AS uv
FROM python:3.12-slim AS builder
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src/ src/
RUN uv sync --frozen --no-dev --no-editable

FROM python:3.12-slim AS runtime
RUN useradd --uid 10001 --create-home app && mkdir -p /cache/huggingface /var/lib/almost-delicious && chown -R app:app /cache /var/lib/almost-delicious
COPY --from=builder /app/.venv /app/.venv
ENV PATH=/app/.venv/bin:$PATH APP_HOST=0.0.0.0 APP_PORT=8003 OUTPUT_DIR=/var/lib/almost-delicious HF_HOME=/cache/huggingface
USER app
EXPOSE 8003
CMD ["almost-delicious"]
