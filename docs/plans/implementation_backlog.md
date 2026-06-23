# 分割平台近期任务清单

> 更新日期：2026-06-15
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

### 已实现于 `src/segplatform/`

| 文件 | 当前能力 |
| --- | --- |
| `src/segplatform/imaging.py` | DICOM、NIfTI、可选 MetaImage；图像/标签空间、Mask 读写和轴映射 |
| `src/segplatform/case_packages.py` | Case、Image Artifact、初始 Label Artifact、病例包和初始 Mask 拆分 |
| `src/segplatform/registry.py` | 文件式不可变 Registry |
| `src/segplatform/adapters/mimics/finalize.py` | 提交身份、基础版本、buffer、空标签和空间 QC |
| `src/segplatform/snapshots.py` | 标签准入、split 防泄漏和 Dataset Snapshot |

纯 RAW 通用 sidecar、数据库服务和完整反向引用索引仍后置。当前闭环支持实际所需的 DICOM/NIfTI，MHD/MHA 通过可选 SimpleITK 依赖支持。

### 对象图能力状态

当前命令已经能跑通最小闭环，并补齐了部分非线性对象图能力。仍然不引入 Airflow/Celery 或数据库调度层。

| 能力 | 当前状态 | 说明 |
| --- | --- | --- |
| `sp label merge` | 已实现 | 同一 case/image 下的多个 active Label Artifact 可合并；同器官冲突必须用 `--organ-source organ=label_id` 显式选择 |
| `sp review create-from-finding` | 已实现 | 可从 Snapshot/QC 报告中的 `skipped`、`findings` 或 `results` 生成 follow-up review |
| 批量 `sp label register` | 已实现 | `sp label register-many` 支持 CSV/JSON/YAML 表格批量注册外部标签 |
| 最小 run record | 部分实现 | 新增对象图命令会写入 Registry `_runs/run_*.json`；历史批处理命令尚未全部接入 |
| `adopt unmanaged mask` | 未实现 | Mimics 中临时自建 Mask 仍只警告“不导出”；正式纳管仍需 follow-up 或后续专门命令 |

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

探针和生产工作流代码均已实现。Windows 操作者通过 `probe-run` 在单次 Mimics 会话收集证据，再由 `probe-evaluate` 自动求解并冻结 buffer mapping；未通过时会阻断已有 Mask 注入和结果回收。

### 外部现代 Python

| 文件 | 作用 | 进入条件 |
| --- | --- | --- |
| `src/segplatform/adapters/mimics/doctor.py` | 已实现 | 在 Windows 工作站运行并记录版本/许可/API |
| `src/segplatform/adapters/mimics/prepare.py` | 已实现 | 使用真实病例执行 Gate A |
| `src/segplatform/adapters/mimics/launcher.py` | 已实现 | 确认 Research 21 实际可执行文件和参数 |
| `src/segplatform/adapters/mimics/bridge.py` | 已实现并强制 P05 证据 | 执行 P04/P05 |
| `src/segplatform/adapters/mimics/finalize.py` | 已实现 | 用真实导出验证空间和失败恢复 |

### Mimics Python 3.5.2

| 文件 | 作用 | 进入条件 |
| --- | --- | --- |
| `adapters/mimics/runtime_py35/sp_common.py` | 已实现 | 在 Python 3.5.2 实测 memoryview/NumPy 路径 |
| `adapters/mimics/scripting_library/Start_Labeling.py` | 已实现 | 配置为标注者唯一可见 Scripting Library 入口 |
| `adapters/mimics/runtime_py35/sp_review_console.py` | 已实现 | 在 Mimics 内领取任务、保存 checkpoint、提交当前 review |
| `adapters/mimics/runtime_py35/sp_diagnostics.py` | 已实现 | 运行本机诊断 |
| `adapters/mimics/runtime_py35/sp_open_review.py` | 已实现 | Gate A/B 真实病例验收 |
| `adapters/mimics/runtime_py35/sp_submit_review.py` | 已实现 | Gate B 提交操作验收 |
| `adapters/mimics/probes/sp_probe_suite.py` | 已实现 | 单次 Mimics 会话收集 P01/P02/P04/P05/P06 |
| `src/segplatform/adapters/mimics/probes.py` | 已实现 | 启动探针、自动评估空间映射并生成 verified 配置 |

详细运行步骤见 [Mimics Research 21 Windows 工作站操作手册](../domains/labeling/mimics_windows_runbook.md)。

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
| 标注者操作负担过重 | P1 | 标注者只使用 Mimics 内 **Start Labeling**；准备和收尾由平台后台、管理员批处理或 Console 内部调用 |
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

1. 在 Mimics Research 21.0 Windows 工作站运行 `sp mimics doctor --run-diagnostics`。
2. 对一个三轴尺寸不同的 DICOM Case Package 执行 `probe-run` 和 `probe-evaluate`，冻结该工作站的 buffer mapping。
3. 固定 3 至 5 个已去标识真实病例，执行首次 `prepare/open/submit/finalize`。
4. 验证保存后重开、提交复查、报告阻塞、QC 失败返修和已验证标签再修订。
5. 用两个独立 review 模拟多标注者，不共享 `.mcs`。
6. 创建第一个真实 Dataset Snapshot。
7. Snapshot 验收后才进入 nnUNet Adapter 和小训练。

代码层训练前闭环已经完成；当前剩余工作是 Mimics 21 本机能力验收和真实数据验收，不能用自动测试替代。
