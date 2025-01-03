FROM ghcr.io/astral-sh/uv:python3.12-alpine

ADD . /

WORKDIR /

RUN apk add --no-cache gcc musl-dev linux-headers rust cargo && \
    uv sync --frozen --no-cache && \
    apk del gcc musl-dev linux-headers rust cargo && \
    uv cache clean && \
    rm -rf \
        /var/cache/apk/* \
        /root/.cache \
        /tmp/*


ENV CONFIG_PATH /config.yaml

CMD ["/bin/sh", "-c", "uv run alist-mikananirss --config $CONFIG_PATH"]