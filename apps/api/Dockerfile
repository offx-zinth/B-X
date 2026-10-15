# Production API image: multi-stage, non-root, minimal runtime.
FROM python:3.11-slim AS builder
WORKDIR /srv
ENV PIP_NO_CACHE_DIR=1
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

FROM python:3.11-slim
WORKDIR /srv
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH=/usr/local/bin:$PATH
COPY --from=builder /install /usr/local
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./alembic.ini
COPY scripts ./scripts
COPY seed_demo.py ./seed_demo.py
RUN useradd --create-home --uid 10001 xray && chown -R xray:xray /srv
USER xray
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=3).status==200 else 1)"
# 2 workers x 4 threads: matches PgBouncer DEFAULT_POOL_SIZE=20 headroom.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "2"]
