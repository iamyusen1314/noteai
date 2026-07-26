# Deployment Secrets And Variables

NoteAI 的生产密钥目前配置在 GitHub Environment：`production`。

仓库：`iamyusen1314/noteai`

当前仓库是 public，用于启用 GitHub Free 下的 branch protection 与 secret scanning。所有生产密钥必须只存在 GitHub Environment、部署平台 Secret 或本地 `.env`，不能进入 Git。

## Production Secrets

以下值以 GitHub Environment Secret 保存，不能写入 Git，也不能在 CI 日志中打印：

- `ADMIN_PASSWORD`
- `AMAP_WEB_KEY`
- `ANTHROPIC_API_KEY`
- `MEITUAN_OPEN_TOKEN`
- `MOONSHOT_API_KEY`
- `NOTEAI_MARKET_TIMING_REFRESH_TOKEN`

说明：NoteAI 运行时接受 `MEITUAN_AI_HUB_TOKEN` 或 `MEITUAN_OPEN_TOKEN`，生产环境只需配置其中一个，无需重复存同一份密钥。官方 `meituan-travel` CLI 1.0.16 实际只读取 `~/.config/meituan-travel/config.json` 的 `key`/`Authorization`；NoteAI 会在每次调用前把上述 Secret 写入权限为 `0600` 的临时配置，并使用权限为 `0700` 的隔离 HOME，调用结束后立即清理。Token 不进入命令参数或应用日志。

## Production Role Env Files

Alibaba Cloud production must not use one shared runtime env file. The
production Compose contract accepts four external inputs:

| Role | Compose input | Default host path |
|---|---|---|
| API | `NOTEAI_API_ENV_FILE` | `/etc/noteai/api.env` |
| Admin | `NOTEAI_ADMIN_ENV_FILE` | `/etc/noteai/admin.env` |
| XHS Trends | `NOTEAI_XHS_TRENDS_ENV_FILE` | `/etc/noteai/xhs-trends.env` |
| XHS Tracking | `NOTEAI_XHS_TRACKING_ENV_FILE` | `/etc/noteai/xhs-tracking.env` |

The four roles must resolve to four distinct regular files with no
group/world permission bits. The files remain outside Git and images. Do not
source or print them during validation.

Allowed Secret key names are intentionally role-specific:

- API: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `MOONSHOT_API_KEY`,
  `AMAP_WEB_KEY`, `BAIDU_MAP_AK`, `TENCENT_MAP_KEY`,
  `SERPAPI_API_KEY`, `BING_SEARCH_API_KEY`, `GOOGLE_API_KEY`,
  `MEITUAN_AI_HUB_TOKEN`, `MEITUAN_OPEN_TOKEN`, `MEITUAN_SIGN_KEY`,
  `MEITUAN_APP_AUTH_TOKEN`, `MEITUAN_OPEN_APP_KEY`,
  `MEITUAN_OPEN_APP_SECRET`, `MEITUAN_OPEN_SIGN`,
  `MEITUAN_OPEN_AES_KEY`, `NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET`,
  `NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET`,
  `NOTEAI_MARKET_TIMING_REFRESH_TOKEN`,
  `NOTEAI_AUTHORIZED_TREND_TOKEN`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, and `AWS_SESSION_TOKEN`.
- Admin: `DATABASE_URL` and `ADMIN_PASSWORD`.
- XHS Trends: `DATABASE_URL` and `NOTEAI_XHS_COOKIES_JSON`.
- XHS Tracking: `DATABASE_URL` and `NOTEAI_XHS_COOKIES_JSON`.

These are allowed names, not mandatory values. Provider-specific credentials
must only be present when that separately approved provider path is enabled.
`NOTEAI_XHS_COOKIES_JSON` is the only implemented direct-XHS session input.
It may exist only in the two distinct `0600` XHS role files; API/Admin files
must reject it. Values are never printed. The old snapshot-upload and
authorized-trend tokens are not accepted by either managed XHS role.

Before any production Compose resolution, validate key names without printing
values:

```bash
python scripts/validate_production_env_files.py \
  --api /etc/noteai/api.env \
  --admin /etc/noteai/admin.env \
  --xhs-trends /etc/noteai/xhs-trends.env \
  --xhs-tracking /etc/noteai/xhs-tracking.env
```

The validator fails on a reused file, duplicate/invalid names, overexposed
file permissions, unknown Secret-like names, and a known Secret name supplied
to the wrong role.

## Production Variables

以下值以 GitHub Environment Variable 保存，可在部署 workflow 中通过 `vars.*` 注入：

- `ADMIN_PORT=8001`
- `ADMIN_USERNAME=noteai_admin`
- `NOTEAI_ENABLE_TEST_BILLING=0`
- `NOTEAI_FACT_SEARCH=1`
- `NOTEAI_FACT_SEARCH_CACHE_TTL=0`
- `NOTEAI_FACT_SEARCH_PROVIDER=auto`
- `NOTEAI_MODEL_PRICE_VERSION=official-2026-07-12`
- `NOTEAI_BILLING_USD_CNY=7.00`
- 四个启用模型的精确 `NOTEAI_MODEL_PRICE_<MODEL>_{INPUT|CACHE_READ|CACHE_WRITE_5M|CACHE_WRITE_1H|OUTPUT}_PER_1M_<CURRENCY>` 变量；完整值见 `model/.env.example` 和 `render.yaml`。Claude 使用 USD，Kimi/Moonshot 使用 RMB。
- `NOTEAI_MEITUAN_TRAVEL_ENABLED=1`
- `NOTEAI_MEITUAN_TRAVEL_TIMEOUT=45`
- `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`
- `NOTEAI_USE_V04_COMPOSITE=1`
- `NOTEAI_API_STARTS_TREND_SCHEDULER=0`
- `NOTEAI_HOT_KEYWORD_FRESH_HOURS=30`
- `NOTEAI_MARKET_TIMING_REQUIRED=1`
- `NOTEAI_MARKET_TIMING_FETCH_TIMEOUT=8`
- `NOTEAI_MARKET_TIMING_REFRESH_URL=<trend-worker-refresh-webhook>`
- `NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL=` (must be empty for managed Trends)
- `NOTEAI_MARKET_TIMING_SNAPSHOT_URL=` (shared-DB production contract)
- `NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES=360`
- `NOTEAI_MARKET_TIMING_MIN_DOMAIN_KEYWORDS=12`
- `NOTEAI_XHS_SCROLL_ROUNDS=10`
- `NOTEAI_XHS_SCROLL_WAIT_SECONDS=1.0`
- `NOTEAI_XHS_CHANNEL_SETTLE_SECONDS=3.0`
- `NOTEAI_XHS_SEARCH_DISCOVERY=1`
- `NOTEAI_XHS_SEARCH_SEEDS_PER_CATEGORY=2`
- `NOTEAI_XHS_SEARCH_SCROLL_ROUNDS=3`
- `NOTEAI_XHS_SEARCH_SETTLE_SECONDS=2.0`
- `PORT=8000`

## Not Configured Yet

- `NOTEAI_MODEL_ARTIFACT_BASE_URL`

该值需要等模型对象存储前缀确定后再配置。当前生产策略是：若部署平台通过 Git LFS 正确拉到 `model/artifacts/`，可以不配置该值；若部署平台不能拉 LFS，则必须把 V0.4 模型文件上传到对象存储并配置该 URL。

## Required Deployment Rule

生产部署 job 必须声明：

```yaml
environment: production
```

否则 GitHub Environment Secrets 不会注入。

## Safety Rules

- `NOTEAI_ENABLE_TEST_BILLING` 必须保持 `0`。
- 只有四个已确认模型、完整 usage/cache 维度和精确模型单价同时满足时，父账单才标记 `actual`。Provider 通用价格只可用于旧估算兼容，不能证明实际毛利。
- `model_usage_records` 只保存模型、Token 维度和价格快照，不保存 Prompt、正文、reasoning 或第三方 request-id。历史父记录不虚构逐模型明细，查询时归为不可复算覆盖缺口。
- `NOTEAI_MODEL_ARTIFACT_REQUIRED` 生产必须保持 `1`，防止模型缺失时静默降级。
- `CORS_ORIGINS` 等正式域名确定后再配置，不能长期使用通配策略。
- `MEITUAN_TRAVEL_CLI` 不从本机路径同步到云端；云端镜像需要单独安装或用部署脚本设置可执行路径。
- Docker 容器启动会先执行 `python -m artifact_loader`；若生产模型缺失或 SHA256 不一致，服务必须启动失败。
- 生产 Compose 必须分别使用 API、Admin 和 XHS env 文件；禁止回退到共享 `runtime.env`。
- 部署前必须运行 `scripts/validate_production_env_files.py`，只输出计数和错误键名，不输出 Secret 值。
- API 容器默认不得启动热词采集器；市场时机证据只由独立
  `xhs-trends` 写入共享 DB。
- Managed Trends 禁止 HTTP snapshot upload。精确 payload、SHA、大小和
  六域计数与本轮业务数据、成功账本在同一事务内写入数据库。
- 生产不依赖授权趋势源。`industry_baseline` 只能在本轮六域真实 XHS
  证据门已经通过后补齐有界 90 词快照，不得使失败运行成功，也不得
  展示成平台官方热搜。
- 生产 `NOTEAI_MARKET_TIMING_REQUIRED` 必须保持 `1`；拿不到当前行业新鲜快照时，AI 诊断/生成应返回 `MARKET_TIMING_EVIDENCE_UNAVAILABLE`，不能静默使用旧数据。
- Dependabot security updates 已启用；依赖更新走 PR 和 `test` 状态检查，不直接进 `main`。
