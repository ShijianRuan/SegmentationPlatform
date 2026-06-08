# Label Generation Adapters

> 日期：2026-06-08  
> 状态：目录骨架已建立；当前定义标签生成工具的适配边界。

这个目录用于放置“能产生候选标签的工具”的适配器。

典型来源包括：

- 现有内部模型的离线批量推理
- TotalSegmentator 等公开算法
- 未来的 foundation model 或上下文学习模型

这些工具的输出默认登记为 `candidate_label`。  
只有经过名称映射、空间/几何 QC、标签内容 QC 和任务准入策略后，才可能进入：

- `draft_label`：送到 `labeling` 域给人工修正
- `accepted_pseudo_label`：进入 `training` 域的 Dataset Snapshot
- `rejected_label`：记录报告，不进入闭环

本目录不负责：

- 人工修正流程
- 训练任务编号
- 数据许可裁决
- 正式评估策略
