# CADS 伪标签技术文档核实记录

> 核实日期：2026-06-06  
> 核实范围：`docs/domains/label_generation/cads_reference.md`  
> 状态：参考核查记录；主平台设计以 `docs/architecture/platform_blueprint.md` 为准。

## 1. 总体结论

`cads_reference.md` 可以作为伪标签方法参考，但不应作为平台架构主文档。CADS 对本项目最有价值的启发是：大规模全身 CT 标签可以通过多来源数据整合、伪标签生成、自动质量控制和公开工具链组合出来；但平台不能直接照搬 CADS 的标签准入策略，仍需要自己的 label policy。

## 2. 已核实的关键事实

| 内容 | 核实结果 | 来源 |
| --- | --- | --- |
| CADS 论文编号为 arXiv:2507.22953 | 已核实 | arXiv |
| CADS 声称包含 22,022 个 CT volumes | 已核实 | arXiv 摘要、Hugging Face |
| CADS 声称覆盖 167 个解剖结构 | 已核实 | arXiv 摘要、Hugging Face |
| CADS 声称相比既有集合有 18 倍扫描量、60% 更多解剖目标 | 已核实 | arXiv 摘要 |
| CADS 数据页说明数据来自公开数据和项目新增数据，并要求用户遵守各数据集许可 | 已核实 | Hugging Face |
| CADS 数据页提到 pseudo-labeling 和 unsupervised quality control | 已核实 | Hugging Face |

## 3. 需要谨慎的内容

| 内容 | 处理建议 |
| --- | --- |
| 具体 Dice、NSD 或单结构指标 | 只有在逐表核对论文 PDF 后再写入；避免把单器官指标写成总体指标 |
| “可直接作为金标准” | 改成“可作为候选伪标签或 accepted pseudo 的来源，是否训练由平台策略决定” |
| 数据许可 | 不能只看 CADS 汇总页，仍需检查各子数据集许可 |
| 质量控制细节 | 可借鉴思路，不代表适合本项目每个器官 |

## 4. 对平台的启发

1. 伪标签不应只来自自训模型，也可以来自公开算法、公开模型或公开数据资源。
2. 伪标签进入训练前应有质量证据，例如自动 QC、抽检或任务级准入规则。
3. 标签来源必须保留，否则后续模型评估和数据治理会失真。
4. 大规模全身任务适合拆成区域/器官任务逐步建设，再考虑合并或统一模型。

## 5. 来源

- [CADS arXiv paper](https://arxiv.org/abs/2507.22953)
- [CADS Hugging Face dataset page](https://huggingface.co/datasets/mrmrx/CADS-dataset)
