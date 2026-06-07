# 研究材料说明

> 日期：2026-06-06  
> 状态：跨域研究入口；区分原始研究材料和面向架构讨论的摘要版。

## 1. 用途

这个目录保存跨域研究材料，例如 TTA、持续学习、交互式学习、小样本学习、上下文学习等。

这些内容可能同时影响 `training`、`label_generation`、`labeling`，但不直接决定当前平台架构。当前架构主线仍是：

1. 统一器官名称。
2. 任务级 label map。
3. Dataset Snapshot。
4. nnUNet Adapter 先跑通。
5. 后续再扩展其他训练方法。

为避免“摘要版冒充原文”的混淆，这里现在分成两层：

- `docs/research/originals/`：从旧仓库路径恢复的原始研究材料，保留原始写法，不视为已核实事实。
- `docs/research/digests/`：面向当前平台架构讨论整理的摘要版，只保留与平台设计直接相关的判断边界。

## 2. 阅读建议

| 位置 | 阅读目的 |
| --- | --- |
| `docs/research/digests/` | 先看摘要版，快速理解这些方向对平台设计的影响边界 |
| `docs/research/originals/` | 再看原始材料，追溯完整调研内容和原始表述 |

如果这些研究材料与 `docs/architecture/platform_blueprint.md` 的当前架构冲突，以平台蓝图为准。
