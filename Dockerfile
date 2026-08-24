FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

COPY pyproject.toml README.md ./
COPY app ./app

RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 iamllm \
    && mkdir -p /data \
    && chown -R iamllm:iamllm /data

USER iamllm

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=20s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os, urllib.request; urllib.request.urlopen(f\"http://127.0.0.1:{os.getenv('PORT', '8000')}/health\", timeout=3).read()"]

CMD ["python", "-m", "app.server"]
