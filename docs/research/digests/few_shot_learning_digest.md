# 小样本学习研究摘要

> 状态说明：这是面向平台架构讨论整理的摘要版，不是原始研究文档；若与 `docs/architecture/platform_blueprint.md` 冲突，以平台蓝图为准。  
> 原始来源：https://uih.feishu.cn/docx/ZdKBdhFSRoXc8TxyVB1cW7pqnSb  
> 本轮处理：删除未逐条核实的论文史、方法表和指标描述，只保留与平台设计有关的使用边界。

## 1. 为什么保留这份文档

全身器官分割会长期遇到小样本问题：有些器官少、有些病种少、有些扫描协议少、有些标签只在少量病例中出现。小样本学习可以作为后期模型能力扩展方向。

但它不应该成为第一阶段平台主线。第一阶段更重要的是把数据、标签、任务和训练快照管理清楚。没有这些基础，小样本算法再复杂，也无法判断训练数据到底是什么、标签是否可信、评估是否泄漏。

## 2. 与当前平台的关系

| 问题 | 当前平台先解决什么 | 小样本方法后续能补什么 |
| --- | --- | --- |
| 某个器官标签少 | 明确标签状态和任务覆盖 | 用更少标签训练或适配 |
| 某类病例少 | 按病例/患者冻结数据拆分 | 研究少样本泛化 |
| 新器官加入 | 通过 anatomy vocabulary 和 task label map 接入 | 研究快速扩展类别 |
| 标注成本高 | 用 draft label 和人工审核减少重复劳动 | 研究更高效的标注策略 |

当前文档主线仍是：

1. `anatomy_vocabulary` 管统一器官名称。
2. `task_label_map` 管训练任务编号。
3. Dataset Snapshot 固定一次训练的数据。
4. nnUNet Adapter 先跑通基线。

小样本方法只能在这些前提成立后进入实验层。

## 3. 第一阶段不要做什么

| 不建议事项 | 原因 |
| --- | --- |
| 一开始就做复杂 few-shot 框架 | 会掩盖数据和标签治理问题 |
| 用少量样例宣称平台泛化能力 | 样本少时评估不稳定 |
| 混用未审核伪标签和人工标签 | 无法判断模型提升来自算法还是标签污染 |
| 让同一患者出现在相近训练/评估任务中 | 容易造成数据泄漏 |
| 用全局统一训练编号接所有任务 | 与 nnUNet 的任务内连续编号要求冲突 |

## 4. 平台架构落点（已确认）

**少样本学习 = training 域下与 nnUNet Adapter 平行的新 Adapter。**

```
训练域/
  adapters/
    nnunet/                      ← 全监督 Adapter（已有，生产级）
    fewshot/                      ← 少样本 Adapter（架构已确认，实现后置）
```

两者共享同一个 Dataset Snapshot 数据契约，各自产出 Model Record。

少数样本方法需要先通过生产级实验协议验证（冻结评估集、多 N 值系统对比、跨扫描协议一致性），通过准入标准后才能从实验层升级为正式 Adapter。

参考：`docs/domains/training/README.md` §3 和 `docs/architecture/platform_blueprint.md` §8.4。

## 5. 后续实验应该怎么设计

如果要评估小样本策略，建议先设计成离线实验，而不是平台核心能力。

```text
select task
        ↓
freeze patient-level split
        ↓
build few-shot Dataset Snapshot
        ↓
train baseline nnUNet Adapter
        ↓
train candidate few-shot method
        ↓
compare on frozen evaluation set
        ↓
record result in Model Registry
```

实验文档必须写清楚：

1. 样本数量按病例、患者还是切片计算。
2. 标签来自 `verified_label` 还是 `accepted_pseudo_label`。
3. 任务 label map 是什么。
4. 评估集是否冻结。
5. 是否使用外部预训练模型或外部数据。

## 5. 对平台设计的启发

小样本学习真正要求平台提前准备的不是某个算法，而是可复用的数据组织：

| 平台能力 | 为什么重要 |
| --- | --- |
| 病例级数据注册 | 防止少样本实验中训练/评估泄漏 |
| 标签来源记录 | 少样本时一个错误标签影响更大 |
| 任务级 label map | 新任务可以复用同一批数据 |
| Dataset Snapshot | 实验必须可复现 |
| Model Registry | 记录每个实验的数据和结果 |

因此，当前架构不需要为小样本算法预留复杂模块，只需要保证数据和标签层是干净的。

## 6. 后续文献核查清单

恢复原始研究条目前，需要逐项确认：

| 核查项 | 要求 |
| --- | --- |
| 论文信息 | 标题、作者、年份、发表位置或 arXiv 编号准确 |
| 方法类别 | 生成、度量、元学习、迁移等归类要来自论文内容 |
| 医学相关性 | 是否真正用于医学图像，尤其是否用于 3D 分割 |
| 数据规模 | few-shot 的 shot、way、case/patient 定义必须清楚 |
| 评估指标 | 指标必须从原文表格引用 |
| 代码许可 | 代码仓库和 license 需要单独检查 |

在这些核查完成前，本文件不引用具体论文结论作为平台设计依据。
