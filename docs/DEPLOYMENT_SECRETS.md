# Deployment Secrets And Variables

NoteAI 的生产密钥目前配置在 GitHub Environment：`production`。

仓库：`iamyusen1314/noteai`

## Production Secrets

以下值以 GitHub Environment Secret 保存，不能写入 Git，也不能在 CI 日志中打印：

- `ADMIN_PASSWORD`
- `AMAP_WEB_KEY`
- `ANTHROPIC_API_KEY`
- `MEITUAN_OPEN_TOKEN`
- `MOONSHOT_API_KEY`

## Production Variables

以下值以 GitHub Environment Variable 保存，可在部署 workflow 中通过 `vars.*` 注入：

- `ADMIN_PORT=8001`
- `ADMIN_USERNAME=noteai_admin`
- `NOTEAI_ENABLE_TEST_BILLING=0`
- `NOTEAI_FACT_SEARCH=1`
- `NOTEAI_FACT_SEARCH_CACHE_TTL=0`
- `NOTEAI_FACT_SEARCH_PROVIDER=auto`
- `NOTEAI_MEITUAN_TRAVEL_ENABLED=1`
- `NOTEAI_MEITUAN_TRAVEL_TIMEOUT=45`
- `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`
- `NOTEAI_USE_V04_COMPOSITE=1`
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
- `NOTEAI_MODEL_ARTIFACT_REQUIRED` 生产必须保持 `1`，防止模型缺失时静默降级。
- `CORS_ORIGINS` 等正式域名确定后再配置，不能长期使用通配策略。
- `MEITUAN_TRAVEL_CLI` 不从本机路径同步到云端；云端镜像需要单独安装或用部署脚本设置可执行路径。
