# Render exposes NOTEAI_RUNTIME_TARGET as a non-secret build argument. Compose
# selects named stages directly. No credentials may be passed through this ARG.
ARG NOTEAI_RUNTIME_TARGET=api-runtime

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
# sha256:00af38ae2ed311628970782e8a2d7f014d8909dbc63cb97bc0a158187f4db045
FROM python:3.11.15-slim-trixie@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93 AS runtime-common

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
    PIP_DEFAULT_TIMEOUT=120 \
    PIP_RETRIES=8 \
    MEITUAN_TRAVEL_CLI=/usr/local/bin/mttravel

# API/shared runtime keeps only the non-browser native dependency required by
# LightGBM. The worker stage lets Playwright install its own Chromium runtime.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Official Meituan Travel CLI runtime only; npm and its cache stay in the build stage.
COPY --from=meituan-travel-cli /usr/local/bin/node /usr/local/bin/node
COPY --from=meituan-travel-cli /usr/local/lib/node_modules/@meituan-travel/travel-cli /usr/local/lib/node_modules/@meituan-travel/travel-cli
RUN ln -s /usr/local/lib/node_modules/@meituan-travel/travel-cli/mttravel-bundle.cjs /usr/local/bin/mttravel \
    && test -x /usr/local/bin/mttravel \
    && node -e 'const pkg=require("/usr/local/lib/node_modules/@meituan-travel/travel-cli/package.json"); if(pkg.version!=="1.0.16") process.exit(1)'

# Install only API dependencies in the shared layer. Browser capability is
# added solely by worker-runtime below.
COPY model/requirements.txt model/requirements-api.txt model/requirements-worker.txt ./
RUN pip install --no-cache-dir -r requirements-api.txt \
    && python -m pip uninstall -y setuptools wheel \
    && python -m pip check \
    && python -c 'import importlib.util; assert importlib.util.find_spec("setuptools") is None; assert importlib.util.find_spec("wheel") is None' \
    && rm -rf /root/.cache /var/lib/apt/lists/* /var/cache/apt/*

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
    && chown -R noteai:noteai /app

ENV PORT=8000
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=3 \
    CMD ["python", "-c", "import http.client, os, sys; connection = http.client.HTTPConnection('127.0.0.1', int(os.environ.get('PORT', '8000')), timeout=5); connection.request('GET', '/health/live'); response = connection.getresponse(); sys.exit(0 if 200 <= response.status < 300 else 1)"]

# Public API runtime: no browser package, browser binary, or explicit graphics
# stack. The root-owned marker cannot be replaced by runtime ENV.
FROM runtime-common AS api-runtime

LABEL com.noteai.runtime.role="api"
ENV NOTEAI_RUNTIME_ROLE=api
RUN printf '%s\n' api > /etc/noteai-runtime-role \
    && chmod 0444 /etc/noteai-runtime-role

USER noteai

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["/app/scripts/render_start_api.sh"]

FROM runtime-common AS worker-runtime

# Worker/admin runtime: browser support is isolated here. Chromium is verified
# headlessly during a future authorized build; no provider or network target is
# contacted by the smoke test.
LABEL com.noteai.runtime.role="worker"
ENV NOTEAI_RUNTIME_ROLE=worker \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN pip install --no-cache-dir -r requirements-worker.txt \
    && mkdir -p /ms-playwright \
    && python -m playwright install --with-deps chromium \
    && apt-get purge -y xvfb xserver-common \
    && python -c 'from playwright.sync_api import sync_playwright; runtime = sync_playwright().start(); browser = runtime.chromium.launch(headless=True, args=["--no-sandbox"]); page = browser.new_page(); page.goto("about:blank"); browser.close(); runtime.stop()' \
    && python -m pip uninstall -y setuptools wheel \
    && python -m pip check \
    && python -c 'import importlib.util; assert importlib.util.find_spec("setuptools") is None; assert importlib.util.find_spec("wheel") is None' \
    && printf '%s\n' worker > /etc/noteai-runtime-role \
    && chmod 0444 /etc/noteai-runtime-role \
    && chown -R noteai:noteai /ms-playwright \
    && rm -rf /root/.cache /var/lib/apt/lists/* /var/cache/apt/*

USER noteai

ENTRYPOINT ["/app/scripts/docker_entrypoint.sh"]
CMD ["/bin/false"]

# Render builds the selected internal stage through this non-secret argument.
# The default remains the API-safe runtime for ordinary Docker builds.
FROM ${NOTEAI_RUNTIME_TARGET} AS noteai-runtime
