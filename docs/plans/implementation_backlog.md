# 分割平台近期任务清单

> 日期：2026-06-13
> 近期目标：用 3 至 5 个病例跑通第一次手动闭环
> 总体日期和验收标准见[实施计划](platform_implementation_plan_2026-10-30.md)。
> 代码结构、工作量和依赖顺序见[阶段 A 开发执行说明](development_execution_guide.md)。

## 1. 近期只做什么

近期目标只有一条流程：

```text
准备病例包
-> 人工保存或提交
-> 检查提交结果
-> 登记人工确认标签
-> 创建最小训练数据快照
-> 运行一次 nnUNet 小训练和推理
-> 登记候选标签
-> 生成下一轮人工草稿
```

近期不做：

- 完整 Web 界面。
- 常驻流程调度服务。
- 复杂任务队列。
- MONAI 工具适配器。
- 通用少样本工具适配器。
- 自动主动学习。
- 完整多人审批。

## 2. 七个闭环检查点

| 检查点 | 目标 | 完成标准 |
| --- | --- | --- |
| B0 | 选好样例 | 3 至 5 个已完成去标识检查的病例，覆盖无标签、草稿、部分标签和空间边界差异 |
| B1 | 生成病例包 | 每个病例都有图像集、目标组、基础标签版本和去标识声明 |
| B2 | 导入标注工具 | Mimics 21.0 或备用工具能打开多个图像集和初始 mask |
| B3 | 导出标注结果 | 能导出单个或多个完整目标组，并通过空间检查 |
| B4 | 登记提交结果 | 只有明确提交且检查通过的目标组创建人工确认标签 |
| B5 | nnUNet 小训练 | 用最小训练数据快照完成一次导出、训练和推理 |
| B6 | 第二轮草稿 | 新模型输出登记为候选标签，并进入下一轮人工任务 |

首次闭环为了减少变量，B5 可以只使用人工确认标签。闭环稳定后，外部来源标签和候选标签仍可按训练数据快照规则进入训练。

## 3. 通用脚本

### 已存在

| 文件 | 当前能力 |
| --- | --- |
| `scripts/check_case_package.py` | 检查病例包 v0.5 的必需文件、目标组、去标识声明、配置引用和文件校验值 |
| `scripts/hash_package.py` | 复制或归档整个目录时生成可选校验值 |

### 待实现

| 文件 | 输入 | 输出 |
| --- | --- | --- |
| `src/segplatform/ingest/scan.py` | DICOM、NIfTI、MHD+RAW 或 RAW 来源 | 只读扫描报告 |
| `src/segplatform/ingest/import_cases.py` | 扫描报告和确认映射 | Case、Image Artifact |
| `src/segplatform/labeling/package_case.py` | 已登记图像、可选标签、器官和任务配置 | 病例包 |
| `src/segplatform/labeling/mask_conversion.py` | 多标签文件或逐器官 mask、标签映射 | 拆分或合并结果 |
| `src/segplatform/qc/geometry.py` | 图像和标签记录 | 空间检查报告 |

顶层 `scripts/` 如需保留命令兼容，只提供薄入口；核心逻辑进入可测试的 `src/segplatform/`。这些能力与具体标注软件无关，应先于 Mimics 自动化完成。

## 4. Mimics 工具适配器

> 首次闭环不必等 Mimics：先用 ITK-SNAP 或 3D Slicer 完成人工修正，Mimics 验证并行进行（见[实施计划](platform_implementation_plan_2026-10-30.md) M3）。

### 先做工作站诊断和能力探针

按照[Mimics 适配器设计与开发流程](../domains/labeling/mimics_adapter_design.md)和[Mimics POC 计划](../domains/labeling/mimics_poc_plan.md)验证：

1. DICOM 多序列分组。
2. 每个目标组绑定正确图像集。
3. Mask 体素数组轴顺序。
4. 图像索引到物理坐标的关系。
5. 导入初始 mask。
6. 修改一个器官并保存。
7. 关闭后重新打开继续。
8. 导出单个 mask 和完整目标组。
9. 导出结果通过空间检查。

每一步都记录是否需要不可控的人工操作。

探针是完成 POC 所需的实验代码，不等待全部验证结束。生产工作流代码必须在 Gate A 通过后开始。

### 外部现代 Python

| 文件 | 作用 | 进入条件 |
| --- | --- | --- |
| `src/segplatform/adapters/mimics/doctor.py` | 检查工作站、启动诊断脚本并生成环境报告 | 立即实现 |
| `src/segplatform/adapters/mimics/prepare.py` | 检查病例包并生成 runtime manifest | Gate A |
| `src/segplatform/adapters/mimics/launcher.py` | 传参启动 Mimics 和打开任务脚本 | Gate A |
| `src/segplatform/adapters/mimics/bridge.py` | 医学标签与逐器官布尔缓冲区互转 | P04/P05 路径成立 |
| `src/segplatform/adapters/mimics/finalize.py` | 转换提交、执行 QC 并生成提交清单 | Gate A |

### Mimics Python 3.5.2

| 文件 | 作用 | 进入条件 |
| --- | --- | --- |
| `adapters/mimics/runtime_py35/sp_common.py` | 兼容层、manifest、日志和错误处理 | 立即实现最小版 |
| `adapters/mimics/runtime_py35/sp_diagnostics.py` | 检查版本、许可和关键 API | 立即实现 |
| `adapters/mimics/runtime_py35/sp_open_review.py` | 导入或打开任务、绑定 image set、创建 Mask 和 metadata | Gate A |
| `adapters/mimics/runtime_py35/sp_submit_review.py` | 选择完成/复查/阻塞并导出任务 Mask | Gate A |
| `adapters/mimics/probes/p01_*.py` 至 `p06_*.py` | 验证分组、绑定、buffer、空间往返和选择性导出 | POC 期间 |

当前这些脚本均待实现。

## 5. nnUNet 小闭环

实施顺序：

1. 从通过检查的人工提交结果创建最小标签记录。
2. 手写或用薄脚本创建最小训练数据快照。
3. 固定病例划分和任务标签编号。
4. 检查缺失标签、空类别，以及 train/test 病例的患者级（leakage_group）不相交。
5. 导出现有 nnUNet 管线需要的目录。
6. 运行小规模训练或快速训练。
7. 对样例病例推理。
8. 创建最小模型记录。

目标是验证数据路径，不是追求模型指标。

## 6. 候选标签回流

待实现：

| 文件 | 作用 |
| --- | --- |
| `adapters/label_generation/run_batch_inference.py` | 对病例列表运行模型并创建候选标签生成批次 |
| `adapters/label_generation/route_candidates.py` | 根据质量报告把结果送复查、保留候选或拒绝 |
| `adapters/label_generation/candidate_to_draft.py` | 把候选标签准备成下一轮人工草稿 |

要求：

- 一个病例失败不影响其他成功病例。
- 重跑不覆盖已成功输出。
- 每个候选标签保存模型、参数和质量报告。
- 本步骤不写训练准入结论。

## 7. 当前最高风险

| 风险 | 优先级 | 处理方式 |
| --- | --- | --- |
| Mimics 图像索引到物理坐标无法解释 | P0 | 不复制头信息绕过；停止该路径并换导出方式或工具 |
| Mask 绑定错误图像集 | P0 | 导入和导出按目标组切换并验证图像标识 |
| 多标签文件与 Mimics 多 Mask 映射错误 | P0 | 使用同一份 `review_label_map.yaml` |
| 候选标签误当人工真值 | P0 | 保持候选状态，训练采用结果只写入训练数据快照 |
| 多位标注者覆盖彼此结果 | P0 | 检查任务、目标组、标注者和基础标签校验值 |
| 标注者操作负担过重 | P1 | 第一阶段允许平台操作者运行前后脚本，稳定后再封装启动器 |
| Windows 与服务器路径不同 | P1 | 清单优先使用相对路径 |
| 过早扩展训练框架 | P2 | 先完成 nnUNet 小闭环 |

## 8. 开始 POC 前仍需确认

1. Mimics Research 21.0 的 edition、许可模块和 Python scripting 权限。
2. 第一批 3 至 5 个样例病例的位置和可用范围。
3. DICOM、NIfTI、MHD+RAW、RAW+sidecar 和不完整几何样例能否覆盖最小导入矩阵。
4. 训练服务器能否直接访问病例包输出，还是需要手动传输。
5. 第一轮小训练选择哪个 v500 任务。
6. 哪些数据或算法来源明确禁止作为候选训练标签。

## 9. 紧接着要做的工作

按顺序：

1. 固定 3 至 5 个闭环病例和最小异构导入样例。
2. 建立 `pyproject.toml`、`src/segplatform/`、统一 CLI 和测试骨架。
3. 实现 Schema 运行时校验、单文件摘要和稳定文件组摘要。
4. 实现 NIfTI、MHD+RAW 扫描，再实现 DICOM 分组和 RAW+sidecar。
5. 实现最小文件型 Registry 和几何 QC。
6. 实现病例包生成、mask 拆分合并，并复用已有 `check_case_package.py`。
7. 实现 Mimics doctor 和能力探针，按 Gate A 决定是否继续生产脚本。
8. 创建最小 Dataset Snapshot，随后接入 nnUNet。

完成前六步后，即使最终不用 Mimics，数据入口、Registry、QC 和病例包仍可复用于其他标注工具。
