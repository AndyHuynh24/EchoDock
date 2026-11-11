# Dock server container.
# Build from server/:  docker build -t dock-server .
# Run:                 docker run -p 8080:8080 -e DOCK_TOKEN=... dock-server
#
# Two stages: "build" installs the locked dependencies with uv; the final image
# only gets the finished virtualenv and the app code, and runs as a non-root user.

# Base image pinned by version and digest, so every build uses the same Python.
ARG PYTHON_IMAGE=python:3.12.16-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

FROM ${PYTHON_IMAGE} AS build
COPY --from=ghcr.io/astral-sh/uv:0.12.19 /uv /bin/uv
# Use the image's Python (pyproject.toml prefers uv's own Python builds for local dev;
# the official Python image can load SQLite extensions too, which sqlite-vec needs).
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_PREFERENCE=only-system UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock .python-version ./
# --frozen: install exactly the versions in uv.lock, fail if it's out of date.
RUN uv sync --frozen --no-install-project --no-dev

FROM ${PYTHON_IMAGE}
RUN groupadd --gid 10001 dock && useradd --uid 10001 --gid dock --no-create-home --shell /usr/sbin/nologin dock
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY dock_server ./dock_server
COPY static ./static
# Saved data (notes, focus log, search library). Mount a volume here to keep it.
RUN mkdir /app/.data && chown dock:dock /app/.data
USER 10001

# Set DOCK_TOKEN (required) and AWS credentials for Bedrock at run time.
# DOCK_PUBLIC_URL turns off the cloudflared tunnel; DOCK_WEBAPP=off skips the S3 phone-app upload.
ENV PATH=/app/.venv/bin:$PATH \
    DOCK_HOST=0.0.0.0 PORT=8080 DOCK_TRACE=log \
    PYTHONUNBUFFERED=1 AWS_DEFAULT_REGION=us-east-1
EXPOSE 8080
CMD ["python", "-m", "dock_server.main"]
