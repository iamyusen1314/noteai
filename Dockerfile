# Immutable multi-arch index; linux/amd64 child at release audit time:
# sha256:3d0f05455dea2c82e2f76e7e2543964c30f6b7d673fc1a83286736d44fe4c41c
FROM node:20-bookworm-slim@sha256:2cf067cfed83d5ea958367df9f966191a942351a2df77d6f0193e162b5febfc0 AS meituan-travel-cli

ARG MEITUAN_TRAVEL_CLI_VERSION=1.0.16
ARG MEITUAN_TRAVEL_CLI_INTEGRITY=sha512-mYwkdd2jzFPKPacMM7CL3aAbfWqxkCh6q1kVi9YhgJoDPw22vAp1JFQrWuWJKzJiBBoYuXnMxzyC8i+f6mXzrA==
ARG MEITUAN_TRAVEL_CLI_BUNDLE_SHA256=8a0527bb6e8b9074cf0221756f35bca989945e8436e4841596a7b7bf79ae06d8

WORKDIR /tmp/meituan-travel-cli
RUN set -eux; \
    npm pack "@meituan-travel/travel-cli@${MEITUAN_TRAVEL_CLI_VERSION}" --ignore-scripts --json > pack.json; \
    node -e 'const fs=require("fs"); const item=JSON.parse(fs.readFileSync(process.argv[1],"utf8"))[0]; if(item.integrity!==process.argv[2]) throw new Error("integrity mismatch")' pack.json "${MEITUAN_TRAVEL_CLI_INTEGRITY}"; \
    tarball="$(node -e 'const fs=require("fs"); process.stdout.write(JSON.parse(fs.readFileSync(process.argv[1],"utf8"))[0].filename)' pack.json)"; \
    npm install --global --omit=dev --ignore-scripts "./${tarball}"; \
    test "$(node -p 'require("/usr/local/lib/node_modules/@meituan-travel/travel-cli/package.json").version')" = "${MEITUAN_TRAVEL_CLI_VERSION}"; \
    echo "${MEITUAN_TRAVEL_CLI_BUNDLE_SHA256}  /usr/local/lib/node_modules/@meituan-travel/travel-cli/mttravel-bundle.cjs" | sha256sum -c -; \
    npm cache clean --force; \
    rm -rf /tmp/meituan-travel-cli

# Immutable multi-arch index; linux/amd64 child at release audit time:
# sha256:28255a3ace7eb4c48bc1b57b90af29e1bc82b4fd6c60614a8e3dce61b87ff941
FROM python:3.11-slim-bookworm@sha256:b18992999dbe963a45a8a4da40ac2b1975be1a776d939d098c647482bcad5cba

ARG NOTEAI_OCI_REVISION=development
ARG NOTEAI_OCI_SOURCE=https://github.com/iamyusen1314/noteai
ARG NOTEAI_OCI_VERSION=development
ARG NOTEAI_OCI_CREATED=1970-01-01T00:00:00Z

LABEL org.opencontainers.image.revision="${NOTEAI_OCI_REVISION}" \
      org.opencontainers.image.source="${NOTEAI_OCI_SOURCE}" \
      org.opencontainers.image.version="${NOTEAI_OCI_VERSION}" \
      org.opencontainers.image.created="${NOTEAI_OCI_CREATED}"

WORKDIR /app

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8 \
    MEITUAN_TRAVEL_CLI=/usr/local/bin/mttravel

# 系统依赖（OpenCV 需要）；健康检查使用 Python 标准库，不保留 curl。
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 libglib2.0-0 libsm6 libxext6 libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Official Meituan Travel CLI runtime only; npm and its cache stay in the build stage.
COPY --from=meituan-travel-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=meituan-travel-cli /usr/local/lib/node_modules/@meituan-travel/travel-cli /usr/local/lib/node_modules/@meituan-travel/travel-cli
RUN ln -s /usr/local/lib/node_modules/@meituan-travel/travel-cli/mttravel-bundle.cjs /usr/local/bin/mttravel \
    && test -x /usr/local/bin/mttravel \
    && node -e 'const pkg=require("/usr/local/lib/node_modules/@meituan-travel/travel-cli/package.json"); if(pkg.version!=="1.0.16") process.exit(1)'

# 依赖先复制（利用 Docker 缓存）
COPY model/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt
RUN mkdir -p /ms-playwright \
    && python -m playwright install --with-deps chromium
RUN apt-get purge -y xvfb xserver-common \
    && python -c 'from playwright.sync_api import sync_playwright; runtime = sync_playwright().start(); browser = runtime.chromium.launch(headless=True, args=["--no-sandbox"]); page = browser.new_page(); page.goto("about:blank"); browser.close(); runtime.stop()' \
    && python -m pip uninstall -y setuptools wheel \
    && python -m pip check \
    && python -c 'import importlib.util; assert importlib.util.find_spec("setuptools") is None; assert importlib.util.find_spec("wheel") is None' \
    && rm -rf /root/.cache /var/lib/apt/lists/* /var/cache/apt/*
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
    CMD ["python", "-c", "import http.client, os, sys; connection = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('PORT', '8000')), timeout=5); connection.request('GET', '/health/live'); response = connection.getresponse(); sys.exit(0 if 200 <= response.status < 300 else 1)"]

USER noteai

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["/app/scripts/render_start_api.sh"]
