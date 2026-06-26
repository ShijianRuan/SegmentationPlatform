# 人工标注与复查域

> 日期：2026-06-13
> 状态：当前标注域入口。平台总体设计以[平台蓝图](../../architecture/platform_blueprint.md)为准。

## 1. 这个域负责什么

`labeling` 负责“怎样把图像和草稿标签交给标注者，以及怎样把人工结果安全地收回平台”。

它包括：

- 准备标注或复查任务。
- 生成离线病例包。
- 调用 Mimics 或其他标注工具。
- 保存中间进度。
- 提交完成、提交复查和报告阻塞。
- 导回指定器官标签。
- 检查图像与标签是否对齐。
- 创建新的人工确认标签版本。

它不负责：

- 定义 nnUNet 训练编号。
- 决定哪些候选标签进入某次训练。
- 运行模型批量生成候选标签。

## 2. 标注者实际看到什么

标注者只需要处理四类动作：

1. 打开分配给自己的病例。
2. 修正任务指定的器官。
3. 保存进度。
4. 提交完成、提交复查或报告阻塞。

标注者不需要填写标签生命周期、文件校验值、空间矩阵或训练准入结果。平台脚本负责这些机械记录。

## 3. 从哪份文档开始

| 文档 | 用途 |
| --- | --- |
| [标注工作流](labeling_workflow.md) | 了解平台、标注者和工具从准备数据到提交结果的完整步骤 |
| [标注闭环实现与运行指南](labeling_implementation_guide.md) | 安装代码、生成病例包、配置 Mimics、提交收尾和创建 Snapshot |
| [Mimics Research 21 Windows 工作站操作手册](mimics_windows_runbook.md) | 在独立 Windows 机器上安装、运行探针、标注、提交、QC 和回收结果 |
| [病例包契约](case_package_contract.md) | 实现病例包生成、校验、导回或其他标注工具适配器 |
| [Mimics 可行性](mimics_feasibility.md) | 判断 Mimics 21.0 是否适合作为主要标注工具 |
| [Mimics 适配器设计与开发流程](mimics_adapter_design.md) | 明确外部平台代码、Mimics Python 3.5 脚本、安装方式、操作步骤和工作量 |
| [Mimics 技术参考](mimics_reference.md) | 查询格式、脚本参数、Mask buffer、`.mcs` 和 Python 版本边界 |
| [Mimics POC 计划](mimics_poc_plan.md) | 在实际安装和许可环境中逐项验证能力 |
| [Mimics 21.0 API 手册入口](../../references/mimics/README.md) | 查阅本地官方手册转换稿 |

## 4. 数据怎样进入这个域

任意数据集不会直接“变成标注域数据”。它先经过平台导入：

1. 图像登记为图像记录，并保存来源、文件校验值和空间信息。
2. 已有标签登记为标签记录，并按器官保存来源和状态。
3. 外部器官名称映射到平台统一名称。
4. 去标识和空间检查通过后，平台才创建标注任务和病例包。

只有需要人工查看、修正或复查的数据才进入这个域。

## 5. 和其他域怎样协作

- 候选标签生成域可以产出模型草稿，标注域负责人工修正。
- 标注域提交的新标签回到资产登记册。
- 训练域在创建训练数据快照时决定是否采用这些标签。
- 标注域不会把候选标签直接改成“全局可训练”。

## 6. 当前实现位置

| 位置 | 当前用途 |
| --- | --- |
| `src/segplatform/` | 已实现训练前离线闭环的 CLI、Registry、图像几何、Mimics 外部适配和 Snapshot |
| `scripts/check_case_package.py` | 已实现病例包 v0.5、初始标签和 Mimics `.u8` 提交布局检查 |
| `scripts/hash_package.py` | 可选的整个目录传输校验工具 |
| `src/segplatform/adapters/mimics/` | 外部现代 Python 的准备、启动、桥接和收尾代码 |
| `adapters/mimics/` | Mimics Python 3.5.2 运行脚本、能力探针和标注员说明 |
| `docs/domains/labeling/` | 标注流程和病例包契约 |

后续实现与标注闭环有关的代码时，优先从本域和 `adapters/mimics/` 定位，不放入 nnUNet 训练管线。
