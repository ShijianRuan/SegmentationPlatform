# nnUNet Pipeline

这是仓库中当前唯一已有实际训练实现的管线。平台不会重写这些训练步骤；后续 `nnUNet Adapter` 负责把 Dataset Snapshot 转换为本目录能够消费的数据和配置。

## 入口

| 文件 | 用途 |
| --- | --- |
| `AutoSegmentationFramework.py` | 配置读取和 Action 编排入口 |
| `Action1_ConvertLabeledToTrainData.py` | 训练数据转换 |
| `Action2_PlanAndPreprocess.py` | nnUNet planning 和 preprocessing |
| `Action3_Train.py` | 训练 |
| `Action4_Predict.py` | 推理 |
| `Action5_Evaluation.py` | 评估 |
| `Config_Template.toml`、`Config_*.toml` | 配置模板与已有任务配置 |
| `ModelMap*.toml` | 当前任务级标签映射 |

详细行为见[训练管线参考](../../docs/domains/training/nnunet_pipeline_reference.md)。

## 生成文件

多 GPU 模式会在本目录生成 `gpu*.sh`。这些脚本包含当次任务和机器路径，只是运行产物，不属于源码，已经加入 `.gitignore`。

## 平台边界

- 当前代码仍可独立运行。
- 平台级数据准入由 Dataset Snapshot 决定，不由本目录自行推断。
- 新训练框架应新增 Adapter，不应修改 nnUNet 数据契约来迁就其他框架。
