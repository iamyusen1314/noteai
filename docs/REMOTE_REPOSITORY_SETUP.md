# NoteAI Remote Repository Setup

本文档记录 NoteAI 第一次上传远程 Git 仓库的标准流程。目标是让代码、模型清单、当前 V0.4 生产模型和部署脚本可回滚，同时避免泄露密钥、误传原始训练大数据或把大模型文件错误塞进普通 Git 历史。

## 当前本地基线

- Branch: `main`
- Initial source baseline commit: `906432d chore: initialize deployable NoteAI repository`
- Remote: `https://github.com/iamyusen1314/noteai`
- Release tag: `v0.4-production-baseline-20260628`
- Git LFS: enabled
- Scope doc: `docs/GIT_DEPLOYMENT_SCOPE.md`
- Model manifest: `model/artifacts/MODEL_RELEASE_MANIFEST.md`

## 远程仓库要求

1. 仓库必须是私有仓库，至少在正式商业上线前保持私有。
2. 远程平台必须支持 Git LFS，或另外配置模型对象存储。
3. 远程仓库名称建议为 `noteai` 或 `noteai-saas`。
4. 不要在远程仓库网页端手动上传 `.env`、训练原始数据、MLflow 本地运行目录或临时质量生成队列。
5. 云端部署密钥只放在部署平台的 Secret/Environment Variables 中，不放进 Git。

## 推荐推送流程

先在 GitHub/Gitee/GitLab 创建空的私有仓库，不要初始化 README、license 或 `.gitignore`，避免第一次 push 出现无关历史。

然后在项目根目录执行：

```bash
scripts/push_remote.sh <remote-url>
```

示例：

```bash
scripts/push_remote.sh git@github.com:OWNER/noteai.git
```

脚本会执行：

- 校验当前分支是 `main`
- 校验工作区干净
- 初始化本地 Git LFS
- 配置或更新 `origin`
- 推送 `main`
- 推送 tags
- 推送 LFS 对象

## 推送后必须核验

远程仓库页面需要确认：

- 可以看到 `main` 分支最新提交
- 可以看到 tag `v0.4-production-baseline-20260628`
- `.env` 没有出现
- `model/.env` 没有出现
- `.venv/`、`node_modules/`、`model/mlruns/`、`model/mlflow.db` 没有出现
- V0.4 三个 `.lgb` 文件在远程以 LFS 文件存在
- `model/model_registry.json` 指向当前 V0.4 release
- `model/artifacts/MODEL_RELEASE_MANIFEST.md` 中的 SHA256 与本地一致

## 克隆验收

第一次远程 push 完成后，建议在临时目录做一次干净克隆验收：

```bash
git clone <remote-url> /tmp/noteai-clone-check
cd /tmp/noteai-clone-check
git lfs pull
git status --short
python3 -m py_compile model/api.py model/v04_composite_features.py model/train_v04_composite.py
```

若部署机不允许直接从 Git LFS 拉模型，则需要把 `MODEL_RELEASE_MANIFEST.md` 里的三个模型文件同步到对象存储，并让部署环境通过模型 registry 或启动脚本下载到 `model/artifacts/`。

## 回滚规则

每一次上线必须同时记录：

- Git commit
- Git tag
- `model/model_registry.json`
- `model/artifacts/MODEL_RELEASE_MANIFEST.md`
- 部署平台环境变量版本

生产回滚时，不只回滚代码，也必须回滚模型 registry 和对应模型文件。AI 诊断、爆文生成、评分和多 agent 质量链路必须使用同一个模型 release，不能代码回滚而模型仍指向新版本。
