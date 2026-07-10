# Model Artifact Cloud Strategy

NoteAI 的生产模型必须和代码版本同步回滚。当前 GitHub 仓库已经用 Git LFS 保存 V0.4 三个生产 `.lgb` 文件；正式云端部署时，推荐把模型二进制同时发布到对象存储，并用 SHA256 清单校验。

## 当前发布

- Release: `v0.4-composite`
- Run ID: `20260628T013926Z`
- Git tag: `v0.4-production-baseline-20260628`
- Machine manifest: `model/artifacts/model_release_manifest.v04.json`
- Human manifest: `model/artifacts/MODEL_RELEASE_MANIFEST.md`

## 加载策略

优先级如下：

1. 本地 `model/artifacts/` 已存在且 SHA256 正确，直接加载。
2. 文件缺失或是 Git LFS 指针文件时，优先从配置的私有 S3 桶下载；未配置 S3 时才使用 `NOTEAI_MODEL_ARTIFACT_BASE_URL`。
3. 生产环境配置 `NOTEAI_MODEL_ARTIFACT_REQUIRED=1` 时，缺失或校验失败直接报错，不能静默退回旧模型。

## 推荐对象存储路径

把以下文件上传到同一个对象存储前缀：

```text
model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb
model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb
model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb
model/artifacts/model_v04_composite_train_report.json
```

若对象存储公开前缀为：

```text
https://example-bucket.example.com/noteai/v0.4-composite/20260628T013926Z
```

则生产环境设置：

```text
NOTEAI_MODEL_ARTIFACT_BASE_URL=https://example-bucket.example.com/noteai/v0.4-composite/20260628T013926Z
NOTEAI_MODEL_ARTIFACT_REQUIRED=1
```

商业部署优先使用私有 S3，不要为了模型下载把桶设为公开：

```bash
NOTEAI_MODEL_ARTIFACT_S3_BUCKET=<private-bucket-name>
NOTEAI_MODEL_ARTIFACT_S3_PREFIX=<optional-prefix>
AWS_ACCESS_KEY_ID=<render-secret>
AWS_SECRET_ACCESS_KEY=<render-secret>
AWS_DEFAULT_REGION=<aws-region>
```

S3 IAM 身份只授予目标前缀的 `s3:GetObject`，不授予写入或删除权限。对象 key 需保留清单里的相对路径，例如 `<prefix>/model/artifacts/model_v04_...lgb`。下载完成后仍执行 SHA256 校验；校验失败会中止启动。

下载器会按 manifest 中的相对路径拼接 URL，并写回容器内 `model/artifacts/`。

## 校验命令

本地或 CI 校验当前 LFS 模型是否完整：

```bash
python scripts/fetch_model_artifacts.py --check-only --required
```

云端启动前下载并校验：

```bash
NOTEAI_MODEL_ARTIFACT_BASE_URL=<base-url> \
NOTEAI_MODEL_ARTIFACT_REQUIRED=1 \
python scripts/fetch_model_artifacts.py
```

Docker 镜像启动时会自动执行：

```bash
python -m artifact_loader
```

该命令会读取 `NOTEAI_MODEL_ARTIFACT_BASE_URL` 和 `NOTEAI_MODEL_ARTIFACT_REQUIRED`。生产环境 `NOTEAI_MODEL_ARTIFACT_REQUIRED=1` 时，缺失或校验失败会让容器启动失败；如果对象存储前缀已配置，会先尝试下载并重新校验。

## 回滚规则

回滚必须同时回滚：

- Git commit/tag
- `model/model_registry.json`
- `model/artifacts/model_release_manifest.v04.json`
- `model/artifacts/MODEL_RELEASE_MANIFEST.md`
- 对象存储前缀
- 部署环境变量

不能只回滚代码而让模型指向另一个 release。
