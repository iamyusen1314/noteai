FROM python:3.11-slim

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8

# 系统依赖（OpenCV 需要）
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# 依赖先复制（利用 Docker 缓存）
COPY model/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /ms-playwright \
    && python -m playwright install --with-deps chromium
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# 复制代码
COPY model/ ./model/
COPY scripts/docker_entrypoint.sh scripts/render_start_api.sh scripts/render_start_admin.sh \
    scripts/render_predeploy.py scripts/render_run_market_timing.sh scripts/render_run_crawler.sh \
    scripts/migrate_sqlite_to_postgres.py scripts/migrate_managed_prompts_v04.py ./scripts/
COPY NoteAI_Pro_Demo_Framer.html ./NoteAI_Pro_Demo_Framer.html

WORKDIR /app/model

# 数据目录（持久化挂载点）
RUN mkdir -p data
RUN groupadd --system noteai \
    && useradd --system --gid noteai --home-dir /app --shell /usr/sbin/nologin noteai \
    && chmod +x /app/scripts/docker_entrypoint.sh /app/scripts/render_start_api.sh /app/scripts/render_start_admin.sh \
        /app/scripts/render_predeploy.py /app/scripts/render_run_market_timing.sh /app/scripts/render_run_crawler.sh \
        /app/scripts/migrate_sqlite_to_postgres.py /app/scripts/migrate_managed_prompts_v04.py \
    && chown -R noteai:noteai /app /ms-playwright

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD curl --fail --silent "http://127.0.0.1:${PORT:-8000}/health/live" || exit 1

USER noteai

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["/app/scripts/render_start_api.sh"]
