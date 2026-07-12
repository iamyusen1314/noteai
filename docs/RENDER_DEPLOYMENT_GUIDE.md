# NoteAI Render 测试环境部署手册

> 本手册只用于测试环境。开始前必须先完成 checkpoint commit、推送目标分支并确认 GitHub CI 通过。不要把任何密钥写进仓库、截图或聊天记录。

## 1. 将创建什么

| Render 资源 | 名称 | 用途 | 测试方案 |
|---|---|---|---|
| Static Site | `noteai-staging-web` | 用户前端 | 免费 |
| Web Service | `noteai-staging-api` | FastAPI、V0.4、AI 主链路 | Starter + 1GB 临时视频盘 |
| Web Service | `noteai-staging-admin` | 管理后台 | Free，会休眠 |
| Cron Job | `noteai-staging-market-timing` | 每小时更新行业趋势证据 | Starter，按运行时长计费 |
| Cron Job | `noteai-staging-tracking` | 每小时处理到期笔记表现采集 | Starter，按运行时长计费 |
| PostgreSQL | `noteai-staging-db` | 账号、积分、内容、Prompt、趋势与运行状态 | Free，仅限测试 |

不创建 Redis。当前代码没有队列协议或缓存逻辑需要 Redis。

重要限制：Render Free PostgreSQL 只有 1GB、无备份，并在创建 30 天后到期；正式环境必须升级为付费数据库。API 的 1GB 磁盘只存 6 小时内的视频抽帧缓存，不能当永久素材库。挂盘服务部署时会有短暂中断。

## 2. 部署前人工准备

### 2.1 GitHub

1. 确认本次部署准备改动已经单独 checkpoint commit。
2. 确认目标分支已推送到 GitHub。
3. 打开 GitHub `Actions`，确认最新 `CI / test` 为绿色。
4. 记录分支名和 commit SHA，后续回滚只认这两个值。

### 2.2 私有 Amazon S3 模型桶（推荐）

1. 在 AWS S3 创建私有桶，区域建议与 Render 新加坡接近，例如新加坡区域。
2. 保持 `Block all public access` 开启。
3. 在桶内保留以下完整对象路径：

```text
<可选前缀>/model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
<可选前缀>/model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
<可选前缀>/model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
<可选前缀>/model/artifacts/model_v04_composite_train_report.json
```

4. 创建专用 IAM 身份，只授予该前缀的 `s3:GetObject`，不要授予上传、删除或列出其他桶的权限。
5. 准备以下值供 Render Secret 使用，不要写入任何文件：
   `NOTEAI_MODEL_ARTIFACT_S3_BUCKET`、`NOTEAI_MODEL_ARTIFACT_S3_PREFIX`、`AWS_ACCESS_KEY_ID`、`AWS_SECRET_ACCESS_KEY`、`AWS_DEFAULT_REGION`。
6. 如果确认 Render 构建能正确拉取 Git LFS，S3 变量可以暂空；一旦日志出现模型 checksum mismatch，必须配置私有 S3，不能把模型桶改为公开来绕过。

## 3. 在 Render 创建 Blueprint

1. 登录 Render Dashboard。
2. 点击右上角 `New +`。
3. 选择 `Blueprint`。
4. 连接保存 NoteAI 的 GitHub 仓库。
5. 选择已经通过 CI 的目标分支。
6. Blueprint Path 保持 `render.yaml`。
7. 点击预览，不要立即 Apply。
8. 核对预览中恰好有 5 个 service 和 1 个 PostgreSQL，区域为 Singapore。
9. 核对 API 是 Starter 且挂载 1GB `/var/data`；管理端是 Free；数据库是 Free。
10. Render 要求填写 Secret 时，按下一节逐项填写。

## 4. Render 变量填写

### 4.1 前端 `noteai-staging-web`

| 变量名 | 必填 | 用途 |
|---|---:|---|
| `NOTEAI_PUBLIC_API_BASE` | 是 | API 的 HTTPS 根地址，例如该 API 服务的 `onrender.com` 地址，不带末尾 `/` |

### 4.2 API `noteai-staging-api`

| 变量名 | 必填 | 敏感 | 用途 |
|---|---:|---:|---|
| `ANTHROPIC_API_KEY` | 是 | 是 | Claude 多 Agent 主链路 |
| `MOONSHOT_API_KEY` | 是 | 是 | Kimi 图片、OCR、视频理解 |
| `AMAP_WEB_KEY` | 是 | 是 | 餐饮/本地生活事实源 |
| `MEITUAN_AI_HUB_TOKEN` | 酒旅必填 | 是 | `meituan-travel` 酒旅事实源 |
| `CORS_ORIGINS` | 是 | 否 | 前端 HTTPS 完整源地址，不带路径；多个地址用英文逗号分隔 |
| `NOTEAI_MODEL_ARTIFACT_S3_BUCKET` | 推荐 | 否 | 私有模型桶名 |
| `NOTEAI_MODEL_ARTIFACT_S3_PREFIX` | 可选 | 否 | 模型对象前缀，不带开头或末尾 `/` |
| `AWS_ACCESS_KEY_ID` | 使用 S3 时必填 | 是 | 只读模型 IAM 凭据 |
| `AWS_SECRET_ACCESS_KEY` | 使用 S3 时必填 | 是 | 只读模型 IAM 凭据 |
| `AWS_DEFAULT_REGION` | 使用 S3 时必填 | 否 | S3 区域 |
| `NOTEAI_MODEL_ARTIFACT_BASE_URL` | 可选 | 视 URL 而定 | 仅作非 S3 备用下载源 |

生产成本核算还需要按已启用模型配置以下价格变量。测试环境未填写时，系统只能保留操作级固定估算，不能用于真实毛利或对账：

| 变量名 | 必填 | 敏感 | 用途 |
|---|---:|---:|---|
| `NOTEAI_MODEL_PRICE_VERSION` | 商业核算必填 | 否 | 当前采用 `official-2026-07-12` |
| `NOTEAI_BILLING_USD_CNY` | 商业核算必填 | 否 | 已确认固定为 `7.00`，随调用快照保存 |
| `NOTEAI_MODEL_PRICE_<精确模型>_<维度>_PER_1M_<币种>` | 商业核算必填 | 否 | 四个启用模型的普通输入、缓存、输出精确价格；完整键和值见 `model/.env.example` 与 `render.yaml` |

如不同模型价格不同，按 `model/.env.example` 中的精确模型覆盖命名配置。价格、汇率和生效日期必须由产品负责人确认，不得凭经验猜测。

`DATABASE_URL` 由 Blueprint 从 PostgreSQL 自动注入，禁止手工复制连接串。

### 4.3 管理端 `noteai-staging-admin`

| 变量名 | 必填 | 敏感 | 用途 |
|---|---:|---:|---|
| `ADMIN_USERNAME` | 是 | 否 | 测试管理账号名 |
| `ADMIN_PASSWORD` | 是 | 是 | 使用密码管理器生成的独立强密码 |

不要复用 GitHub、邮箱、数据库或 AI 平台密码。

### 4.4 市场时机 Cron

| 变量名 | 必填 | 用途 |
|---|---:|---|
| `NOTEAI_XHS_DOWNLOADER_URL` | 可选 | 已部署并授权的 XHS Downloader sidecar 地址 |

没有 sidecar 时会使用容器内 Playwright。由于平台反自动化机制，首次部署后必须手工触发 Cron 并检查是否取得真实 XHS 证据。系统不会把行业基线伪装成真实趋势；证据不足时 AI 诊断/生成会返回 503，这是有意的质量门禁。

## 5. Apply 前最后检查

1. 所有密钥只出现在 Render 的 Secret 输入框。
2. `DATABASE_URL` 显示为 `fromDatabase`，不是明文。
3. `NOTEAI_MODEL_ARTIFACT_REQUIRED=1`。
4. `NOTEAI_USE_V04_COMPOSITE=1`。
5. `NOTEAI_MARKET_TIMING_REQUIRED=1`。
6. `NOTEAI_XHS_FRESHNESS_REQUIRED=1`。
7. `NOTEAI_ENABLE_CLOUD_MODEL_MUTATION=0`。
8. Auto Deploy 为 `After CI Checks Pass`。
9. 确认 Render 预计费用后再点击 `Apply`。

## 6. 首次部署观察顺序

1. 先看 `noteai-staging-db` 状态为 Available。
2. 打开 API Events，确认 Pre-Deploy 输出 4 个首次迁移或 0 个已存在迁移。
3. API 日志必须出现四个模型 artifact `checked`，并显示 Uvicorn 已监听 Render 的 `PORT`。
4. 打开 API `/health/ready`，必须是 HTTP 200，数据库为 `postgresql`，模型为 `v0.4-composite`。
5. 打开管理端 `/health/ready`，必须是 HTTP 200。
6. 打开 Static Site，确认页面请求指向 HTTPS API，而不是 `127.0.0.1` 或 `:8000`。
7. 任何一步失败都先停止，不要关闭门禁或把 Secret 写死到代码中。

## 7. 首次手工运行 Cron

1. 打开 `noteai-staging-market-timing`。
2. 点击 `Trigger Run` / `Run Now`。
3. 日志必须显示任务正常退出，并且真实 XHS freshness gate 为通过。
4. 再查 API `/health`，`market_timing.ok` 应为 true。
5. 打开 `noteai-staging-tracking`，手工运行一次；没有到期笔记时允许返回 0 条任务，但不能异常退出。

## 8. 本地数据迁移（可选，必须单独批准）

先只做统计，不写 Render：

```bash
python scripts/migrate_sqlite_to_postgres.py
```

真正迁移前必须备份本地 SQLite，并在受控终端临时提供 Render PostgreSQL 外部连接。执行命令需要用户再次确认：

```bash
DATABASE_URL=<Render external PostgreSQL URL> \
python scripts/migrate_sqlite_to_postgres.py \
  --apply \
  --expected-database noteai_staging
```

默认迁移账号、内容、订阅、积分、用量和追踪记录；不迁移用户登录 session。只有明确需要时才加 `--include-user-sessions`。工具不会迁移管理员 token、Cookie、Prompt 历史、趋势缓存或本地视频文件，也不会覆盖目标库已有主键。

## 9. 部署后验收

1. 注册新用户、登录、退出、重新登录。
2. 核对免费/月度积分、充值积分和后台余额一致。
3. 各跑一次截图诊断、手动诊断、视频诊断、爆文生成、两条对话优化。
4. 每次检查扣积分、usage record、模型调用成本与后台统计。
5. 检查 3 个标题对应 3 篇不同正文。
6. 检查 V0.4 分数、质量问题、专家证据和市场时机证据完整。
7. 检查高德餐饮/本地生活事实和美团酒旅事实；缺实体时应要求补充，不能输出占位句。
8. 上传视频后等待 API 重启测试一次，确认 6 小时缓存可恢复。
9. 登录管理端更新一个测试 Prompt，确认 API 10 秒内读取新版本，再执行回滚。
10. 手动触发两个 Cron，检查数据库和后台日志状态同步。

## 10. 回滚

1. Render 服务页面选择最近一个成功 Deploy，执行 Rollback。
2. 代码、`model_registry.json`、模型 manifest 和 S3 前缀必须回滚到同一 release。
3. 数据库迁移采用向前兼容设计；不要手工删除表或降级 schema。
4. 若迁移后业务数据异常，暂停写流量，保留数据库，先导出备份并核对，不执行清库。
5. Free PostgreSQL 无自动备份，测试期有重要数据时必须先手工导出或升级数据库。

## 11. 当前 Staging 稳定参考

以下地址是公开测试入口，不包含任何 Secret：

- 用户前端：`https://noteai-staging-web.onrender.com`
- 用户 API：`https://noteai-staging-api.onrender.com`
- 管理端：`https://noteai-staging-admin.onrender.com`
- 用户 API 就绪检查：`https://noteai-staging-api.onrender.com/health/ready`
- 管理端就绪检查：`https://noteai-staging-admin.onrender.com/health/ready`

当前 Staging 从 `codex/quality-stabilization-real-chain` 分支自动部署，只有 GitHub CI 通过后才会更新。每次交接仍必须在 `.codex/handoffs/current-task.md` 记录并重新核对具体 commit，不能把本节当成版本证明。

### 11.1 市场时机 Cron 运维

- `noteai-staging-market-timing` 每小时第 5 分钟运行；低内存参数由 `render.yaml` 管理。
- 成功日志必须同时显示非零 `homefeed`、`search_result`、`search_recommend`、`hot_search`，并让六个核心行业满足新鲜度门禁。
- 只看到 Build 成功不代表 Cron 运行成功；必须检查最近一次 Run 的退出状态与来源统计。
- 管理端“爬虫管理”会显示 Cookie 的 `verified`、`needs_attention` 或 `needs_relogin`。出现重新登录提示时，由授权人员更新 Cookie 后手工触发一次 Cron 验证。
- Cookie 只能保存在受控运行时配置中，禁止写进仓库、日志、截图或交接文档。

### 11.2 模型与成本验收

- API 启动时必须从私有对象存储取得 V0.4 artifacts，并完成 manifest/SHA256 校验。
- `/health/ready` 必须报告 `v0.4-composite` 和 PostgreSQL 就绪。
- 配置真实模型价格后，用一个最小测试账号分别跑诊断、生成和对话优化；验收要求 Token 数、`actual_model_cost_rmb`、积分账本和管理端汇总一致。
- 未完成上述成本验收前，不得把操作级固定估算当作真实成本或据此上线收费。

官方参考：

- [Render Blueprint](https://render.com/docs/blueprint-spec)
- [Render Health Checks](https://render.com/docs/health-checks)
- [Render Cron Jobs](https://render.com/docs/cronjobs)
- [Render Free Limits](https://render.com/docs/free)
- [Render Persistent Disks](https://render.com/docs/disks)
