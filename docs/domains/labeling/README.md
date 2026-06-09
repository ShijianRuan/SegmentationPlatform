# 标注域文档入口

> 日期：2026-06-07  
> 状态：标注域导航；平台总体设计以 `docs/architecture/platform_blueprint.md` 为准。

## 1. 这个域管什么

`labeling` 是“人工和工具如何把标签生产出来并安全导回平台”的实现域。

它覆盖的不是狭义的人工勾画，而是整条标注侧链路：

- Case Package 导出与导回
- 标注工具适配
- 草稿标签 review
- 人工保存后的 `verified_label`
- 几何校验、label 校验、来源记录

因此这里不用 `annotation_pipeline` 命名，而用 `labeling`。它比单纯的 annotation 更能容纳“人工标注 + 伪标签修订 + 标签交换契约”这一整块。

## 2. 关键文档

| 文档 | 当前用途 |
| --- | --- |
| `docs/domains/labeling/case_package_contract.md` | 标注工具和平台之间的离线文件交换契约 |
| `docs/domains/labeling/mimics_feasibility.md` | Mimics 是否适合作为第一阶段人工标注/修正工具 |
| `docs/domains/labeling/mimics_poc_plan.md` | Mimics POC 的执行草案 |
| `docs/domains/labeling/mimics_research_notes.md` | Mimics 外部资料整理，供调研追溯 |

## 3. 和其他域的边界

- 和 `training` 的边界：标注域负责产出可注册的标签，不负责定义任务级训练 label id。
- 和 `label_generation` 的边界：候选标签可以进入标注域做人工修正，但候选标签是否被接受、如何抽检，属于标签生成域和主蓝图中的准入策略。

## 4. 数据集接入标准

任意来源的数据集不能直接等同于 `labeling` 域。它应先经过平台 ingest/import，登记为 Image Artifact 和 Label Artifact。只有当它需要人工 review、修正或工具交换时，才进入标注域。

最低接入标准：

1. 图像能登记为 Image Artifact，并记录 shape、spacing、origin/direction 或 affine、hash、来源。
2. 标签能登记为 Label Artifact；如果是多器官标签，应能按 segment 记录器官、来源和状态。
3. 外部器官名称能映射到 `anatomy_vocabulary`。
4. 如果要进入 review 工具，必须能生成 Case Package，并携带 `review_label_map.yaml`。
5. 导回后必须通过几何、label id 和 provenance 校验。

这保证了后续 Web UI 里“导入数据集”“生成 review 任务”“提交标注结果”都是平台动作，而不是临时脚本拼接。

## 5. 当前实现落点

当前仓库里，这个域的代码还没有独立成模块，但它已经有明确落点：

- 平台侧通用脚本在 `scripts/`
- 标注工具适配脚本后续应和工具一起组织，例如 `adapters/mimics/`
- 与训练框架无关的文件契约、几何校验、mask 拆分/合并，应优先归在这个域

这意味着你后面找“和标注闭环有关的实现”，优先看这个域，而不是去 `pipelines/nnunet/` 里翻。
