# Tool Adapters

> 日期：2026-06-07  
> 状态：目录骨架已建立；当前只定义落点和边界，不代表所有适配器都已实现。

`adapters/` 是平台里“标注/训练/推理工具适配层”的实际落点。

它存在的目的，是把平台契约和具体工具隔开：

- 平台关心 `Case`、`Image Artifact`、`Label Artifact`、`Dataset Snapshot`
- Adapter 负责把这些对象翻译成具体工具能读写的形式

当前状态：

- `adapters/mimics/`：已建立目录，用于 Mimics 导入导出和标注员说明
- `adapters/nnunet/`：已建立目录，用于说明当前 nnUNet Adapter 的实现边界
- `adapters/fewshot/`：已建立目录，用于少样本训练 Adapter 的实验协议和后续实现
- `adapters/label_generation/`：已建立目录，用于公开算法、内部模型和批量推理输出的适配边界

注意：当前真正可复用的 nnUNet 训练代码仍主要在 `pipelines/nnunet/`。`adapters/` 的角色是把“平台数据如何接到工具”这件事显式化，而不是复制训练核心代码。
