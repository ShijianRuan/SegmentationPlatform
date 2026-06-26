# 分割平台文档入口

> 日期：2026-06-13
> 用途：告诉读者先看什么、各目录放什么，以及哪些文档代表当前设计。

## 1. 先看什么

如果你第一次接触这个项目，按下面顺序阅读：

1. [平台蓝图](architecture/platform_blueprint.md)：先理解平台为什么存在、完整流程是什么、三大实现域怎样协作。
2. [常用词说明](glossary.md)：遇到不熟悉的英文名称或缩写时查阅，不需要提前背诵。
3. [核心数据与操作模型](architecture/platform_data_model.md)：准备实现时，再查看各种记录的字段、创建时机和相互关系。
4. 处理 DICOM、NIfTI、MHD+RAW、纯 RAW 或缺失元数据时阅读[数据导入与规范化契约](architecture/data_ingestion_contract.md)。外部数据集已有复杂图像-标签配对或多标签值映射时，继续阅读[数据集描述契约](architecture/dataset_description_contract.md)。
5. 根据当前工作进入对应实现域：
   - [人工标注与复查](domains/labeling/README.md)
   - [模型训练](domains/training/README.md)
   - [候选标签生成](domains/label_generation/README.md)
6. 准备开发时先阅读[阶段 A 开发执行说明](plans/development_execution_guide.md)，再对照[实施计划](plans/platform_implementation_plan_2026-10-30.md)和[近期任务清单](plans/implementation_backlog.md)。

[架构决策记录](architecture/architecture_decisions.md)解释重要选择的理由，不要求首次通读。[多角色设计审查](architecture/platform_quality_review.md)记录发现过的问题和整改依据，也不属于首次阅读主线。

围绕具体对话产生的问题处理记录放在 `conversations/`。这些文档用于追踪疑问如何被解释、实现或延后；若与架构主文档冲突，仍以 `architecture/` 和对应域契约为准。

### 按角色快速进入

| 你现在要做什么 | 先看哪份文档 |
| --- | --- |
| 理解平台整体设计 | [平台蓝图](architecture/platform_blueprint.md) |
| 导入不同格式或信息不完整的数据 | [数据导入与规范化契约](architecture/data_ingestion_contract.md) |
| 接入复杂外部数据集、CSV 配对或多标签 mask | [数据集描述契约](architecture/dataset_description_contract.md) |
| 正则/CSV 仍表达不了，需要写专用 importer | [专用数据集 Importer 契约](architecture/custom_importer_contract.md) |
| 准备一批病例给标注者 | [标注工作流](domains/labeling/labeling_workflow.md) |
| 直接安装和运行训练前闭环 | [标注闭环实现与运行指南](domains/labeling/labeling_implementation_guide.md) |
| 在 Windows 上实际运行 Mimics 21 | [Mimics Research 21 Windows 工作站操作手册](domains/labeling/mimics_windows_runbook.md) |
| 定义标注工具交换文件 | [病例包契约](domains/labeling/case_package_contract.md) |
| 开发或试用 Mimics 接入 | [Mimics 适配器设计与开发流程](domains/labeling/mimics_adapter_design.md) |
| 在任意 Mimics 项目中使用 nnInteractive | [nnInteractive for Mimics 21](integrations/nninteractive_mimics.md) |
| 接入或修改 nnUNet 训练 | [训练域入口](domains/training/README.md) |
| 运行模型生成候选标签 | [候选标签生成域入口](domains/label_generation/README.md) |
| 查看截至 2026-10-30 的交付安排 | [实施计划](plans/platform_implementation_plan_2026-10-30.md) |
| 确认要写哪些代码、工作量和执行顺序 | [阶段 A 开发执行说明](plans/development_execution_guide.md) |

## 2. 哪份文档说了算

如果两份文档说法不一致，按以下顺序判断当前设计：

| 优先级 | 文档类型 | 作用 |
| ---: | --- | --- |
| 1 | `architecture/platform_blueprint.md` | 当前平台目标、边界和原则 |
| 2 | `architecture/platform_data_model.md`、各域现行契约 | 字段、操作和工具接入的具体规则 |
| 3 | `architecture/architecture_decisions.md` | 记录重要决定及其理由 |
| 4 | `plans/` | 当前执行安排，会随进度调整 |
| 5 | `research/` | 研究综述和实验候选，不自动成为平台能力 |
| 6 | `integrations/` | 可独立运行的工具集成和使用说明 |
| 7 | `references/` | 原始手册和外部资料，不直接定义平台行为 |
| 8 | `archive/` | 历史记录，不作为当前实现依据 |

## 3. 目录结构

```text
docs/
  architecture/       当前平台架构、数据模型和决策
  domains/
    labeling/         人工标注、复查、病例包和 Mimics 适配
    training/         训练数据快照到训练框架和模型记录
    label_generation/ 模型或算法生成候选标签并回流
  plans/              实施计划和近期任务清单
  research/           跨域研究综述和研究源笔记
  integrations/       独立工具集成和使用说明
  references/         实现时需要查阅的外部手册
  conversations/      重要对话记录和问题处理清单
  archive/            初始需求和历史会议记录
```

三大实现域只是为了让代码和文档容易定位，不是三个互相独立的平台：

| 域 | 负责 | 不负责 |
| --- | --- | --- |
| `labeling`（人工标注与复查） | 准备标注任务、人工修正、工具交换、标签导回 | 决定训练编号和哪些标签进入训练 |
| `training`（模型训练） | 固定训练数据、导出训练目录、运行训练和登记模型 | 人工标注流程和候选标签来源管理 |
| `label_generation`（候选标签生成） | 用模型或算法生成候选标签、检查结果并回流 | 把算法输出直接改成已确认真值 |

## 4. 当前实现状态

| 位置 | 当前状态 |
| --- | --- |
| `pipelines/nnunet/` | 已有可复用的转换、预处理、训练、预测和评估管线 |
| `scripts/check_case_package.py` | 已支持病例包 v0.5 的提交前检查 |
| `scripts/hash_package.py` | 可选的目录传输校验值工具 |
| `src/segplatform/` | 已实现病例包、文件式 Registry、Mimics 外部适配、提交 QC、离线工作包分发/提交收集和 Dataset Snapshot |
| `adapters/mimics/` | Python 3.5 正式脚本与 P01/P02/P04/P05/P06 探针已实现；真实 Mimics 21 验收待执行 |
| `adapters/label_generation/` | 只有输入输出边界，尚未实现 |
| 数据导入、登记册和训练数据快照 | 已有 DICOM/NIfTI/可选 MetaImage 的阶段 A 文件式实现，并支持从 Registry 生成 Snapshot request 草稿；纯 RAW 通用入口、数据库和服务化后置 |

计划中提到但仓库尚不存在的脚本必须写明“待实现”，不能让读者误以为已经可以运行。

## 5. 文档维护规则

1. 架构结论只写入 `architecture/` 或对应域的现行契约。
2. 只有实现时仍需查阅的外部手册放入 `references/`；一次性转换产物不进入仓库。
3. 被新设计替代但仍有追溯价值的文档移入 `archive/`，不要继续出现在推荐阅读主线。
4. 同一主题只能有一份主文档；研究源笔记和外部参考必须在入口文档中标清身份。
5. 文件移动、对象改名或状态变化时，必须同步更新 README、交叉引用和实施计划。
6. 外部事实优先引用官方文档、论文和官方仓库；未经核实的内容必须明确标注。
7. 固定英文名称第一次出现时必须同时给出中文解释；缩写第一次出现时必须展开。
8. 蓝图说明“为什么和怎么协作”，数据模型说明“记录什么字段”，域文档说明“具体怎样工作”，不要在三处重复整段定义。
