# 标签生成域文档入口

> 日期：2026-06-07  
> 状态：标签生成域导航；平台总体设计以 `docs/architecture/platform_blueprint.md` 为准。

## 1. 为什么不用 `pseudo_labeling`

这个域如果叫 `pseudo_labeling`，会让人以为它只是在做一件事：生成伪标签。

但现有设计里，它实际负责的是更完整的一段链路：

- 用内部模型或公开算法生成候选标签
- 做 label mapping、空间校验和质量筛选
- 决定候选结果进入 `draft_label`、`accepted_pseudo_label` 还是 `rejected_label`
- 把结果回流到标注域或训练域

所以这里最终命名为 `label_generation`。这个名字既保留“生成”这个起点，也容纳后续的治理和回流。

## 2. 关键文档

| 文档 | 当前用途 |
| --- | --- |
| `docs/domains/label_generation/cads_reference.md` | CADS 对大规模候选标签建设和全身分割数据组织的启发 |
| `docs/domains/label_generation/cads_fact_check.md` | CADS 相关事实核查记录 |
| `docs/architecture/platform_blueprint.md` | 定义候选标签状态、训练准入和回流关系 |

## 3. 和其他域的边界

- 和 `labeling` 的边界：`label_generation` 产出候选标签和准入判断，`labeling` 负责人工修订和导回。
- 和 `training` 的边界：训练域消费已经被允许进入任务快照的标签，但不负责定义候选标签的抽检和接受策略。

## 4. 当前实现落点

当前仓库还没有这个域的独立代码目录，但后续凡是下面这些实现，都应优先归到这一域：

- 公开算法适配
- 批量推理生成候选标签
- 伪标签质量报告
- `candidate_label -> draft_label / accepted_pseudo_label` 的规则脚本

这样以后你想找“伪标签到底在哪里实现”，不会再被迫在标注和训练之间来回猜。
