# Dock server container.
# Build from server/:  docker build -t dock-server .
FROM debian:bookworm-slim
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_INSTALL_DIR=/python
COPY pyproject.toml uv.lock .python-version ./
RUN uv sync --frozen --no-install-project
COPY dock_server ./dock_server
COPY static ./static
COPY evals ./evals

# Set DOCK_PUBLIC_URL to the service's HTTPS address (disables the tunnel), plus
# DOCK_TOKEN and AWS credentials for Bedrock.
ENV DOCK_HOST=0.0.0.0 PORT=8080 DOCK_TRACE=log PYTHONUNBUFFERED=1 AWS_DEFAULT_REGION=us-east-1
EXPOSE 8080
CMD ["/app/.venv/bin/python", "-m", "dock_server.main"]
