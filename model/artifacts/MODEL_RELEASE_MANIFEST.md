# V0.4 生产模型发布清单

更新时间：2026-06-28

发布标识：`v0.4-composite / 20260628T013926Z`

当前 registry：`model/model_registry.json`

## 生产模型文件

| 角色 | 文件 | 大小 | SHA256 |
| --- | --- | --- | --- |
| 分数回归 | `model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb` | 456K | `c708c76eef9e017e73bcb63794592baed100d2af73cc53dedbb471cb792cbde4` |
| 可发布分类 | `model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb` | 434K | `5d6e5d5bab5bee321c486d96bb8670605138444ca56cd2589cbbd57c14d80f10` |
| 偏好排序 | `model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb` | 443K | `1f3d0b12a6b32d89044480ab5f3add47076f6148d00ea87135fee2d5bfb7bb7b` |

## 发布证据文件

| 文件 | SHA256 |
| --- | --- |
| `model/artifacts/model_v04_composite_train_report.json` | `b7f6bdf0eb24af8ed48108d0188571a2f8034908a7db8bad7054b503215a7adc` |
| `model/artifacts/v04_composite_audit.json` | `b2d10f6092f5ef36aa197fa8452f422f1a792b21618534523380f70b454785d3` |
| `model/artifacts/v04_composite_readiness.json` | `7473bc72ba2667e7f8a4a0021a7404dd2f4b097d0c49c68d2795cb75beea3e36` |
| `model/artifacts/v04_training_data_health.json` | `82f9b8644c221c3d6794fb3e00bd78a5068d3e83d8044a6f32163645c921e309` |
| `model/model_registry.json` | `af5fa89fcb2c2c49fbbdf5c0e7f7490c77bee3f25e659e626702a11a056ab5e6` |

## 核心指标

来自 `model/artifacts/model_v04_composite_train_report.json` 和 `model/model_registry.json`：

- 特征数：124
- Golden rows：6694
- Preference pairs：24850
- Golden regression MAE：5.4971
- Golden regression Spearman：0.7814
- Publishable classifier AUC：0.8857
- Preference ranker AUC：0.9989
- 当前状态：`production`

## 校验命令

```bash
shasum -a 256 \
  model/artifacts/model_v04_composite_regressor_experimental_20260628T013926Z.lgb \
  model/artifacts/model_v04_composite_ready_classifier_experimental_20260628T013926Z.lgb \
  model/artifacts/model_v04_composite_ranker_experimental_20260628T013926Z.lgb \
  model/artifacts/model_v04_composite_train_report.json \
  model/artifacts/v04_composite_audit.json \
  model/artifacts/v04_composite_readiness.json \
  model/artifacts/v04_training_data_health.json \
  model/model_registry.json
```

部署前必须确认输出与本清单一致。若任一 SHA256 不一致，不能把该版本作为生产模型发布。

## 仓库策略

- 这三个生产 `.lgb` 文件允许进入 Git LFS。
- 历史实验 `.lgb`、MLflow 本地 run、原始 RedNote 数据集、训练中间表不进入普通 Git。
- 下一次模型发布必须新增或更新本文件，并同步 `model/model_registry.json`。
