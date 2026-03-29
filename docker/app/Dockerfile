FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --upgrade pip && pip install -r /app/requirements.txt

COPY . /app

RUN mkdir -p /opt/media-seed \
    && if [ -d /app/media ]; then cp -R /app/media/. /opt/media-seed/; fi \
    && chmod +x /app/docker/app/entrypoint.sh

ENTRYPOINT ["/app/docker/app/entrypoint.sh"]
