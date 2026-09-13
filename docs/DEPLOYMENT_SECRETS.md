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
production Compose contract accepts seven database-role inputs plus the
already verified private-storage configuration used only by API and Worker:

| Role | Compose input | Default host path |
|---|---|---|
| API | `NOTEAI_API_ENV_FILE` | `/etc/noteai/api.env` |
| Admin | `NOTEAI_ADMIN_ENV_FILE` | `/etc/noteai/admin.env` |
| Payment | `NOTEAI_PAYMENT_ENV_FILE` | `/etc/noteai/payment.env` |
| AI Dispatcher | `NOTEAI_AI_DISPATCHER_ENV_FILE` | `/etc/noteai/ai-dispatcher.env` |
| AI Worker | `NOTEAI_AI_WORKER_ENV_FILE` | `/etc/noteai/ai-worker.env` |
| XHS Trends | `NOTEAI_XHS_TRENDS_ENV_FILE` | `/etc/noteai/xhs-trends.env` |
| XHS Tracking | `NOTEAI_XHS_TRACKING_ENV_FILE` | `/etc/noteai/xhs-tracking.env` |

The seven database roles must resolve to seven distinct regular files with no
group/world permission bits. The files remain outside Git and images. Do not
source or print them during validation.

The short-lived Item31 canary does not add a database role. It reuses the
`noteai_payment` login through one of two provider-specific `0600` env files:
`/etc/noteai/payment-canary-wechat.env` or
`/etc/noteai/payment-canary-alipay.env`. Each file contains only its provider's
request-signing key, verification trust root and dedicated `DATABASE_URL`.
Never combine the two files or add the WeChat API v3 callback-decryption key or
retained Adapay credentials.

Allowed Secret key names are intentionally role-specific:

- API: `DATABASE_URL`, `ANTHROPIC_API_KEY`, `MOONSHOT_API_KEY`, `NOTEAI_ARK_API_KEY`,
  `AMAP_WEB_KEY`, `BAIDU_MAP_AK`, `TENCENT_MAP_KEY`,
  `SERPAPI_API_KEY`, `BING_SEARCH_API_KEY`, `GOOGLE_API_KEY`,
  `MEITUAN_AI_HUB_TOKEN`, `MEITUAN_OPEN_TOKEN`, `MEITUAN_SIGN_KEY`,
  `MEITUAN_APP_AUTH_TOKEN`, `MEITUAN_OPEN_APP_KEY`,
  `MEITUAN_OPEN_APP_SECRET`, `MEITUAN_OPEN_SIGN`,
  `MEITUAN_OPEN_AES_KEY`, `NOTEAI_CLAUDE_GATEWAY_HMAC_SECRET`,
  `NOTEAI_CLAUDE_GATEWAY_PREVIOUS_HMAC_SECRET`,
  `NOTEAI_MARKET_TIMING_REFRESH_TOKEN`,
  `NOTEAI_AUTHORIZED_TREND_TOKEN`, `AWS_ACCESS_KEY_ID`,
  `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, and the dedicated
  `NOTEAI_AI_API_STORE_ACCESS_KEY_ID`,
  `NOTEAI_AI_API_STORE_SECRET_ACCESS_KEY` and optional
  `NOTEAI_AI_API_STORE_SESSION_TOKEN`; when payment ordering is separately
  enabled, only `NOTEAI_ADAPAY_API_KEY`,
  `NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY` and the role-bound trust root
  `NOTEAI_ADAPAY_PUBLIC_KEY`. The app id, exact QR channel, HTTPS callback
  URL and exact checkout/bill host lists are non-secret configuration used
  by the adapter. For direct ordering the API role may instead hold
  `NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64`,
  `NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64`,
  `NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64` and
  `NOTEAI_ALIPAY_PUBLIC_KEY_B64`.
  Direct transports are live-only. Their non-secret callback configuration must
  equal the canonical `https://noteaipro.com/payments/wechat/callback` and
  `https://api.noteaipro.cn/payments/alipay/callback` endpoints exactly.
- Admin: `DATABASE_URL` and `ADMIN_PASSWORD`.
- Payment: `DATABASE_URL`, `NOTEAI_ADAPAY_API_KEY` and
  `NOTEAI_ADAPAY_MERCHANT_PRIVATE_KEY`, plus the role-bound trust root
  `NOTEAI_ADAPAY_PUBLIC_KEY`. The app id, exact QR channel, HTTPS callback URL
  and exact checkout/bill host lists are non-secret configuration, but still
  belong only in the API and Payment managed files. The direct callback role
  may hold `NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64`,
  `NOTEAI_WECHATPAY_API_V3_KEY` and `NOTEAI_ALIPAY_PUBLIC_KEY_B64`. Merchant
  request-signing private keys remain absent from this continuously running
  callback role.
- Payment canary, WeChat: only `DATABASE_URL`,
  `NOTEAI_WECHATPAY_MERCHANT_PRIVATE_KEY_B64` and
  `NOTEAI_WECHATPAY_PLATFORM_PUBLIC_KEY_B64`.
- Payment canary, Alipay: only `DATABASE_URL`,
  `NOTEAI_ALIPAY_MERCHANT_PRIVATE_KEY_B64` and
  `NOTEAI_ALIPAY_PUBLIC_KEY_B64`.
- AI Dispatcher: only `DATABASE_URL`. Provider and private-storage names are
  prohibited; its dedicated database login is enabled only by the separately
  verified Durable AI runtime task.
- AI Worker: `DATABASE_URL`, the exact Claude/Kimi credential names used by
  the selected processor, and the dedicated
  `NOTEAI_AI_WORKER_STORE_ACCESS_KEY_ID`,
  `NOTEAI_AI_WORKER_STORE_SECRET_ACCESS_KEY` and optional
  `NOTEAI_AI_WORKER_STORE_SESSION_TOKEN`.
- XHS Trends: `DATABASE_URL` and `NOTEAI_XHS_COOKIES_JSON`.
- XHS Tracking: `DATABASE_URL`, `NOTEAI_XHS_COOKIES_JSON`,
  `NOTEAI_XHS_NOTE_ACCESS_JSON` and optional `NOTEAI_XHS_WEB_SSK_JSON`.

These are allowed names, not mandatory values. Provider-specific credentials
must only be present when that separately approved provider path is enabled.
Direct-provider PEM values use the documented `*_B64` names and canonical
standard Base64 of the complete PEM bytes on one unquoted line. This form has
the same meaning through Compose `env_file` and Docker `--env-file`; quotes,
whitespace, escaped `\n` text and bare multi-line PEM blocks are rejected.
Encode only inside the approved Secret materializer and never print or render
the resulting value during validation.
The API and AI Worker storage credentials are deliberately distinct and must
not be reused across roles or as model-artifact credentials.
`NOTEAI_XHS_COOKIES_JSON` supplies the direct-XHS session. Tracking's explicit
pc_v5 path also accepts the original same-note private access context through
`NOTEAI_XHS_NOTE_ACCESS_JSON` and optional existing signing storage through
`NOTEAI_XHS_WEB_SSK_JSON`. These private values are Tracking-only and must never
enter canonical note URLs, image labels, logs or Git. The current verified repair
uses an empty optional signing-state value; it does not manufacture one.
It may exist only in the two distinct `0600` XHS role files; API/Admin files
must reject it. Values are never printed. The old snapshot-upload and
authorized-trend tokens are not accepted by either managed XHS role.
During the one-time role split, the protected host-local legacy `xhs.env`
value, if present, may be read in memory solely to create the final Trends
and Tracking files on the same host. It must not traverse Cloud Shell,
command arguments, logs, API/Admin/Payment/Worker files or Git, and the
legacy file must be deleted after both final files and their role-bound
read-only connections have been independently verified. If the provider
credential is absent while both XHS runtimes remain suspended, the final
files contain only their dedicated `DATABASE_URL`; no placeholder, copied
credential or readiness credit for the provider path is allowed. A real XHS
credential must still be installed and verified through its separate gate
before either runtime or public cutover. This is not permission to duplicate
the credential into any non-XHS role.

The first-launch credential workflow enables `LOGIN` only for
`noteai_admin_runtime`, `noteai_payment`, `noteai_ai_worker`,
`noteai_xhs_trends` and `noteai_xhs_tracking`. The credential-free
`noteai_ai_dispatcher` remains `NOLOGIN` until a separately verified
dispatcher consumer exists. Payment and AI Worker initially receive only
their dedicated `DATABASE_URL`; their separately gated provider and storage
credentials remain absent, and those services remain stopped.

Both production nodes must retain root-owned `0750`
`/usr/local/sbin/noteai-rotate-production-secrets` and
`/usr/local/sbin/noteai-revoke-production-secrets`. They accept only the
non-secret role/confirmation on argv. The protected control DSN and, for
rotation, the new URL-safe password enter as stdin JSON. Rotation atomically
replaces the role file, verifies the new credential in a read-only
transaction and requires the old credential to fail with an authentication
SQLSTATE. Revocation changes the exact role to `NOLOGIN`, quarantines then
deletes the exact role file and likewise requires the old credential to be
rejected. Neither tool starts or restarts a service.

Before any production Compose resolution, validate key names without printing
values:

```bash
python scripts/validate_production_env_files.py \
  --api /etc/noteai/api.env \
  --admin /etc/noteai/admin.env \
  --payment /etc/noteai/payment.env \
  --ai-dispatcher /etc/noteai/ai-dispatcher.env \
  --ai-worker /etc/noteai/ai-worker.env \
  --xhs-trends /etc/noteai/xhs-trends.env \
  --xhs-tracking /etc/noteai/xhs-tracking.env
```

When a provider is approved for the one-attempt canary, append exactly one of
`--payment-canary-wechat /etc/noteai/payment-canary-wechat.env` or
`--payment-canary-alipay /etc/noteai/payment-canary-alipay.env`. Run every
action for one provider on the same designated host with the same named Docker
volume mounted at `/var/lib/noteai/payment-canary-actions`. The image seeds that
directory as `noteai:noteai` mode `0700`; do not remove the volume until the
provider chain has reached a known terminal reconciliation. The canary container
must run with no TTY, closed stdin, no bind mounts, no other volume mounts, a
bounded process timeout, the `payment-canary` image role, and a fresh activation
window of at most one hour. Before a provider request, the volume consumes the
semantic tuple of provider, action, synthetic order, bill date, synthetic user
subject and 1200-fen amount using one `O_EXCL` mode-`0600` record. A different
activation ID cannot replay the same tuple; an admitted, completed, unreadable or
UNKNOWN record remains closed. Validation and Evidence report only key
names/counts, hashes and result state; they never print Secret values or provider
payloads.

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
- 生产 Compose 必须分别使用 API、Admin、Payment、AI Dispatcher、AI
  Worker、Trends 和 Tracking 七个数据库角色 env 文件；禁止回退到共享
  `runtime.env`。Dispatcher 不得挂载私有存储配置。
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
