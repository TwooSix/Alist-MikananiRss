# syntax=docker/dockerfile:1.7
FROM python:3.11-alpine AS builder

ENV UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/openlist-ani/.venv \
    PATH="/opt/openlist-ani/.venv/bin:$PATH"

WORKDIR /opt/openlist-ani

COPY --from=ghcr.io/astral-sh/uv:0.9.17 /uv /uvx /bin/
COPY pyproject.toml uv.lock README.md ./

# feedparser's only source-only dependency is packaged by Alpine. Copy its
# pure-Python module into the isolated environment, while keeping builds
# disabled for every package resolved by uv.
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    apk add --no-cache py3-sgmllib3k && \
    uv sync --frozen --no-dev --no-install-project --no-build \
        --no-install-package sgmllib3k && \
    cp /usr/lib/python3*/site-packages/sgmllib.py \
        /opt/openlist-ani/.venv/lib/python3.11/site-packages/ && \
    cp -R /usr/lib/python3*/site-packages/sgmllib3k-*.dist-info \
        /opt/openlist-ani/.venv/lib/python3.11/site-packages/ && \
    apk del py3-sgmllib3k

COPY src/ ./src
COPY docker/entrypoint.sh /entrypoint.sh
RUN --mount=type=cache,target=/root/.cache/uv,sharing=locked \
    uv build --wheel --out-dir /tmp/dist && \
    uv pip install --python /opt/openlist-ani/.venv/bin/python \
        --no-build /tmp/dist/*.whl && \
    rm -rf /tmp/dist
RUN chmod +x /entrypoint.sh

FROM python:3.11-alpine AS runtime

ENV PATH="/opt/openlist-ani/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1

COPY --from=builder --chmod=0555 /opt/openlist-ani/.venv /opt/openlist-ani/.venv
COPY --from=builder --chmod=0555 /entrypoint.sh /entrypoint.sh

RUN apk add --no-cache nodejs npm ripgrep && \
    npm install -g --ignore-scripts @earendil-works/pi-coding-agent@0.82.1 && \
    npm cache clean --force && \
    addgroup -S -g 1000 openlistani && \
    adduser -S -D -H -u 1000 -G openlistani openlistani && \
    mkdir -p /data /logs /skills && \
    touch /config.toml && \
    chown openlistani:openlistani /config.toml /data /logs /skills

ENV CONFIG_PATH=/config.toml
ENV ENABLE_ASSISTANT=false
ENV PI_SKIP_VERSION_CHECK=1

USER openlistani
WORKDIR /

CMD ["/entrypoint.sh"]
