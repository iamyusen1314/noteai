# NoteAI Git 与部署资产范围

更新时间：2026-06-28

目标：让 Git 仓库成为可上线、可回滚、可审计的 SaaS 交付源；模型和训练资产必须可追踪，但不能把密钥、本地缓存、重复原始数据和实验垃圾提交进仓库。

## 1. 版本库必须包含

- 全栈源码：`model/*.py`、`tools/*.py`、`tests/*.py`、前端 HTML、`Dockerfile`、`docker-compose.yml`、`package*.json`、启动脚本。
- 运行配置模板：`model/.env.example`。真实 `.env`、`model/.env` 永远不能入仓。
- 生产模型路由配置：`model/model_registry.json`。
- 当前生产 V0.4 模型发布三件套：
  - `model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb`
  - `model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb`
  - `model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb`
- 当前生产模型的发布证据：
  - `model/artifacts/model_v04_composite_train_report.json`
  - `model/artifacts/v04_composite_audit.json`
  - `model/artifacts/v04_composite_readiness.json`
  - `model/artifacts/v04_training_data_health.json`
  - `model/artifacts/MODEL_RELEASE_MANIFEST.md`
- 训练工程说明、标注规则、上线检查文档：`docs/`、`quality/*.md`、关键 schema 和 report。

## 2. 必须使用 Git LFS 或云端对象存储

以下文件不能作为普通 Git blob 提交。需要回滚时，靠 `model/model_registry.json` 和发布 manifest 拉取对应版本。

- 模型二进制：`*.lgb`、`*.onnx`、`*.pt`、`*.safetensors`、`*.pkl`、`*.joblib`。
- 训练表和中间特征：`*.parquet`、大体积 `*.jsonl`。
- 原始数据集与同步快照：`model/data/RedNote-Vibe-Dataset/`、`model/data/rednote_vibe_raw/`。
- 封面图片与视觉缓存：`model/data/covers/`、`model/data/covers_v2/`。
- 大规模质量包：`quality/generated_variants/`、大批量 `quality/review_packets/**/*.jsonl`、`quality/labeling_batches/**/*.jsonl`、`quality/*queue*.jsonl`。

当前策略：生产 V0.4 三个 `.lgb` 文件体积很小，但仍按 LFS 规则处理，避免未来模型变大后误伤仓库。

## 3. 永远不能进入 Git

- 密钥与真实环境变量：`.env`、`*.env`、`model/.env`、API Key、Token、OAuth Secret。
- 本地依赖与缓存：`.venv/`、`node_modules/`、`__pycache__/`、`.pytest_cache/`、`.cache/`。
- 本地工具状态：`.claude/`、`.firecrawl/`、临时 `tmp_*`。
- 运行数据库与本地状态：`model/mlflow.db`、`model/mlruns/`、`model/data/*.db`、`model/data/xhs_*.json`。
- 个人授权事实文件：`model/data/authorized_facts.json`。只提交 `authorized_facts.example.json`。
- 备份文件：`*.bak`。

## 4. 模型发布与回滚规则

每一次可上线版本必须由三部分绑定：

1. Git commit：全栈代码、prompt、训练脚本、测试和模型 registry。
2. 模型 manifest：模型文件路径、SHA256、训练 run_id、核心指标、数据来源。
3. 环境配置模板：必要 env 名称存在，真实密钥只在部署平台配置。

回滚时只允许这样做：

1. `git checkout <release_commit>`
2. 按 `model/artifacts/MODEL_RELEASE_MANIFEST.md` 校验或拉取模型文件。
3. 确认 `model/model_registry.json` 指向同一 run_id。
4. 运行后端合同测试和 AI 诊断/生成 smoke test。
5. 再部署。

## 5. 提交前检查

每次提交或推送前至少执行：

```bash
git status --short
git check-ignore -v model/.env .venv node_modules logs tmp_kimi_review_smoke model/mlflow.db
find . -path ./.git -prune -o -type f -size +50M -print
rg -l "(ANTHROPIC|OPENAI|MOONSHOT|KIMI|AMAP|MEITUAN|API_KEY|SECRET|TOKEN|sk-|Bearer)" --glob '!*.env' --glob '!model/.env.example'
.venv/bin/python -m unittest tests.test_api_contracts tests.test_fill_preference_generation_slots tests.test_v04_composite_features
```

如果 `find` 发现超过 50MB 的待提交文件，必须判断它是 LFS 发布物还是仓外训练/数据资产。默认不允许直接普通提交。

## 6. 当前仓库状态

- 本地 Git 仓库已初始化，分支：`main`。
- Git LFS 已安装并通过 `.gitattributes` 配置。
- 真实密钥文件已被 `.gitignore` 阻止。
- 当前尚未配置远程仓库，尚未推送。
- 不建议执行无筛选的 `git add .`。首次提交应按本文件范围逐项 staged。

