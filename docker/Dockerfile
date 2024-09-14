FROM python:3.12-slim

WORKDIR /

RUN pip install alist-mikananirss

RUN mkdir /data

ENV CONFIG_PATH /config.yaml

CMD ["sh", "-c", "python -m alist_mikananirss --config $CONFIG_PATH"]