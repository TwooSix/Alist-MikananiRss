FROM python:3.12-alpine3.20

WORKDIR /

RUN apk add --no-cache gcc musl-dev linux-headers rust cargo && \
    pip install --no-cache-dir alist-mikananirss && \
    mkdir /data && \
    apk del gcc musl-dev linux-headers rust cargo && \
    rm -rf /var/cache/apk/*

ENV CONFIG_PATH /config.yaml

CMD ["sh", "-c", "python -m alist_mikananirss --config $CONFIG_PATH"]