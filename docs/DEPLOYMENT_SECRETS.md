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
- `NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_TOKEN`

说明：酒旅 `meituan-travel` Skill 运行时读取 `MEITUAN_AI_HUB_TOKEN` 或 `MEITUAN_OPEN_TOKEN` 均可。当前 production 配置的是 `MEITUAN_OPEN_TOKEN`，无需重复存同一份密钥。

## Production Variables

以下值以 GitHub Environment Variable 保存，可在部署 workflow 中通过 `vars.*` 注入：

- `ADMIN_PORT=8001`
- `ADMIN_USERNAME=noteai_admin`
- `NOTEAI_ENABLE_TEST_BILLING=0`
- `NOTEAI_FACT_SEARCH=1`
- `NOTEAI_FACT_SEARCH_CACHE_TTL=0`
- `NOTEAI_FACT_SEARCH_PROVIDER=auto`
- `NOTEAI_BILLING_USD_CNY=<Claude 美元账单折算人民币的内部汇率，例如 6.8>`
- `NOTEAI_MODEL_PRICE_CLAUDE_INPUT_PER_1M_USD=<Claude 输入单价，美元/百万 tokens>`
- `NOTEAI_MODEL_PRICE_CLAUDE_OUTPUT_PER_1M_USD=<Claude 输出单价，美元/百万 tokens>`
- `NOTEAI_MODEL_PRICE_KIMI_INPUT_PER_1M_RMB=<Kimi 输入单价，人民币/百万 tokens>`
- `NOTEAI_MODEL_PRICE_KIMI_OUTPUT_PER_1M_RMB=<Kimi 输出单价，人民币/百万 tokens>`
- `NOTEAI_MEITUAN_TRAVEL_ENABLED=1`
- `NOTEAI_MEITUAN_TRAVEL_TIMEOUT=45`
- `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`
- `NOTEAI_USE_V04_COMPOSITE=1`
- `NOTEAI_API_STARTS_TREND_SCHEDULER=0`
- `NOTEAI_HOT_KEYWORD_FRESH_HOURS=30`
- `NOTEAI_MARKET_TIMING_REQUIRED=1`
- `NOTEAI_MARKET_TIMING_FETCH_TIMEOUT=8`
- `NOTEAI_MARKET_TIMING_REFRESH_URL=<trend-worker-refresh-webhook>`
- `NOTEAI_MARKET_TIMING_SNAPSHOT_PATH=model/data/market_timing_snapshot.json`
- `NOTEAI_MARKET_TIMING_SNAPSHOT_UPLOAD_URL=<object-storage-upload-url-or-empty-if-worker-shares-db>`
- `NOTEAI_MARKET_TIMING_SNAPSHOT_URL=<object-storage-cdn-url-or-empty-if-worker-shares-db>`
- `NOTEAI_MARKET_TIMING_WORKER_INTERVAL_MINUTES=60`
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
- 生产环境必须配置 Claude USD 单价、Kimi RMB 单价和 `NOTEAI_BILLING_USD_CNY` 才能按真实 tokens 自动核算模型成本；未配置时后台会显示真实 tokens，但成本仍以功能估算值计入。
- `NOTEAI_MODEL_ARTIFACT_REQUIRED` 生产必须保持 `1`，防止模型缺失时静默降级。
- `CORS_ORIGINS` 等正式域名确定后再配置，不能长期使用通配策略。
- `MEITUAN_TRAVEL_CLI` 不从本机路径同步到云端；云端镜像需要单独安装或用部署脚本设置可执行路径。
- Docker 容器启动会先执行 `python -m artifact_loader`；若生产模型缺失或 SHA256 不一致，服务必须启动失败。
- API 容器默认不得启动热词采集器；市场时机证据由独立 `noteai-trends-worker`/云端 cron 写入共享 DB 或对象存储快照。
- 生产不依赖授权趋势源；公开抓取不足时，worker 必须生成 `industry_baseline` 行业基线证据包。该来源只能作为辅助参考，不得展示成平台官方热搜。
- 生产 `NOTEAI_MARKET_TIMING_REQUIRED` 必须保持 `1`；拿不到当前行业新鲜快照时，AI 诊断/生成应返回 `MARKET_TIMING_EVIDENCE_UNAVAILABLE`，不能静默使用旧数据。
- Dependabot security updates 已启用；依赖更新走 PR 和 `test` 状态检查，不直接进 `main`。
