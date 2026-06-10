# 平台操作模型

> 日期：2026-06-10  
> 状态：架构补充文档；回答“平台搭好后，操作者如何不关心底层代码也能走完整流程”。  
> 主设计仍以 `docs/architecture/platform_blueprint.md` 为准。

## 1. 结论

当前架构已经具备服务化的基础，但还缺一个明确的操作层设计。

三大实现域解决的是代码和责任边界；真正让标注者、训练者、评估者不关心底层细节的，是更上层的 **Platform Workflow Layer**：

```mermaid
flowchart TB
    accTitle: Platform Operational Layers
    accDescr: The platform hides domain adapters behind workflow actions that operators can run without knowing implementation details.

    user["操作者<br/>标注者 / 训练者 / 评估者"]
    workflow["Platform Workflow Layer<br/>任务向导 / Orchestrator / Web UI"]
    registry["Data Registry<br/>统一资产目录"]
    labeling["labeling<br/>Case Package + Review Adapter"]
    training["training<br/>Dataset Snapshot + Training Adapter"]
    generation["label_generation<br/>Candidate Generation + Routing"]
    tools["工具层<br/>Mimics / nnUNet / TotalSegmentator / 其他框架"]

    user --> workflow
    workflow --> registry
    workflow --> labeling
    workflow --> training
    workflow --> generation
    labeling --> tools
    training --> tools
    generation --> tools
    labeling --> registry
    training --> registry
    generation --> registry
```

因此平台后续服务化时，不应该让用户直接操作脚本、目录或 YAML。用户看到的是少量稳定动作：

| 用户角色 | 平台动作 | 用户不应关心 |
| --- | --- | --- |
| 标注者 | 打开待 review 病例、修正、保存、提交 | mask 拆分、label id、hash、几何头修复、Mimics 内部脚本 |
| 训练者 | 选择任务、选择数据范围、生成 Snapshot、启动训练 | nnUNet 目录结构、label id 转换、哪些标签状态能训练 |
| 评估者 | 选择模型、选择评估集、查看指标和失败病例 | 模型权重路径、推理临时目录、评估脚本参数 |
| 平台管理员 | 配置数据源、任务规则、Adapter、准入策略 | 单个病例的手工路径 |

标注者不应该看到或维护 `candidate_label`、`verified_label`、admission decision、hash、affine 这类底层字段。训练者也不应该逐个挑 mask 文件。状态机和策略判断留给平台，用户只执行角色相关动作。

这意味着当前架构还需要补齐几类对象的设计形式：Data Registry、TaskDefinition、Dataset Snapshot、Model Record、Workflow Action。

## 2. 操作内化目标

平台内化不是把所有脚本藏起来，而是把底层规则固化为可复用动作。

### 2.1 第一阶段

第一阶段可以是命令行和文件包，但必须已经模拟未来 Web UI 的动作边界。

例如未来 Web UI 的“生成标注任务”按钮，在第一阶段对应：

```bash
python scripts/package_case.py ...
python scripts/check_case_package.py ...
python scripts/hash_package.py ...
```

但用户文档不应要求标注者理解这些脚本。标注者只需要知道：

1. 打开哪个病例包。
2. 修正哪些结构。
3. 保存并导出。
4. 把导出包交回平台。

### 2.2 服务化阶段

服务化后，Orchestrator 和 Web UI 只编排 Workflow Action，不直接写业务规则。

```text
Create Review Task
  -> select Image Artifact
  -> select candidate/draft label
  -> build Case Package
  -> run preflight QC
  -> open Tool Adapter

Create Training Snapshot
  -> select task
  -> query eligible labels
  -> resolve and freeze label_policy
  -> freeze split
  -> export through training adapter

Run Batch Inference
  -> select Model Record
  -> select Image Artifact set
  -> run inference adapter
  -> register candidate labels
  -> attach QC evidence and optional review route
```

## 3. Data Registry 设计

Data Registry 是平台的资产目录。它不是一开始必须做成数据库，但它的记录结构要先设计清楚。

### 3.1 它负责什么

| 功能 | 说明 |
| --- | --- |
| 资产登记 | 登记 Case、Image Artifact、Label Artifact、Model Record；第一阶段用 `generator metadata` 追踪外部算法来源 |
| 去重和一致性 | 用 hash、shape、spacing、origin、direction、affine 识别重复或不一致 |
| 来源追溯 | 记录数据集来源、人工来源、模型来源、导入批次、工具版本 |
| 标签状态维护 | 记录标签生命周期状态、每个结构的来源、QC 证据和训练准入决策 |
| 使用限制传播 | 记录并传递 `usage_constraints`，防止 license 和用途限制在回流链中丢失 |
| 查询 | 支持按任务、器官、状态、来源、扫描范围查找可用数据 |
| 版本和审计 | 记录谁在什么时候导入、修改、接受、拒绝、用于训练；Label Artifact 追加版本，不覆盖旧文件 |
| 导出 | 为 Case Package、Dataset Snapshot、评估集和批量推理提供稳定输入 |

### 3.2 最小实现形式

第一阶段可以先用文件系统加 manifest：

```text
registry/
  schemas/
    manifest_schema_v1.yaml
  cases/
    case_001.json
  generators/
    totalsegmentator_v2.yaml
  images/
    image_001.json
  labels/
    label_001.json
  models/
    model_001.json
  qc_reports/
    qc_001.json
  task_definitions/
    CT5_Liver.yaml
  snapshots/
    snap_CT5_Liver_001.yaml
```

后续再迁移到 SQLite/PostgreSQL。只要字段稳定，存储后端可以换。

### 3.3 Case 防泄漏字段示例

第一阶段不需要单独建立 Patient 表。Case 是一次检查或一次影像研究；为了防止同一患者不同检查跨 split 泄漏，Case manifest 必须保留 `patient_id_hash` 或 `leakage_group_id`。没有可靠患者 ID 时，导入器也要尽量从原始 subject id、study id 或稳定 hash 生成保守的 `leakage_group_id`。

```json
{
  "schema_version": "case_manifest.v1",
  "case_id": "case_001",
  "patient_id_hash": "sha256:...",
  "leakage_group_id": "hash_subject_001",
  "study_date": "2026-06-01",
  "modality": "CT",
  "body_region": "abdomen"
}
```

### 3.4 Image Artifact 示例

```json
{
  "schema_version": "image_artifact.v1",
  "image_id": "img_001",
  "case_id": "case_001",
  "modality": "CT",
  "path": "images/case_001/ct.nii.gz",
  "hash": "sha256:...",
  "shape": [512, 512, 300],
  "spacing": [0.8, 0.8, 1.0],
  "origin": [0.0, 0.0, 0.0],
  "direction": [1, 0, 0, 0, 1, 0, 0, 0, 1],
  "geometry_contract": {
    "space": "image_native",
    "orientation_checked": true,
    "resampled_from": null
  },
  "source": {
    "type": "imported_dataset",
    "name": "internal_abdomen_set",
    "import_batch": "2026-06-15"
  },
  "usage_constraints": {
    "model_training": "allowed",
    "commercial_use": "unknown",
    "redistribution": "forbidden",
    "derivative_model_release": "unknown"
  }
}
```

### 3.5 Label Artifact 示例

Label Artifact 可以是单个多标签文件，也可以是一组逐器官 mask。关键不是文件形式，而是每个结构的状态要能追溯。

```json
{
  "schema_version": "label_artifact.v1",
  "label_id": "lbl_001",
  "case_id": "case_001",
  "image_id": "img_001",
  "path": "labels/case_001/label.nii.gz",
  "format": "multilabel_nifti",
  "hash": "sha256:...",
  "geometry_ref": "img_001",
  "artifact_lifecycle": "active",
  "parent_label_id": null,
  "segments": [
    {
      "organ": "liver",
      "value": 2,
      "lifecycle_status": "verified_label",
      "source": "manual_review",
      "review_tool": "Mimics",
      "qc_report": "qc_001"
    },
    {
      "organ": "kidney_left",
      "value": 3,
      "lifecycle_status": "candidate_label",
      "source": "TotalSegmentator",
      "qc_report": "qc_002",
      "admission_decisions": [
        {
          "task_id": "CT_Kidney",
          "policy_id": "CT_Kidney_v1",
          "result": "accepted",
          "decided_at_snapshot": "snap_CT_Kidney_001"
        }
      ]
    }
  ],
  "usage_constraints": {
    "model_training": "allowed_with_policy",
    "commercial_use": "needs_review",
    "redistribution": "forbidden",
    "derivative_model_release": "unknown"
  }
}
```

这回答了一个关键问题：**不需要为每个器官都单独保存一个庞大的状态文件**。可以一个 Label Artifact 里按 segment 记录生命周期状态、来源、QC 和准入决策。腹部数据集中肝来自人工、肾来自算法，是允许的；训练准入时按 segment 级证据和 Snapshot policy 过滤。

Artifact 层不承担训练准入状态。segment 的 `lifecycle_status` 只描述标签来源和生命周期，例如 liver 是 `verified_label`、kidney_left 是 `candidate_label`。某个 candidate 是否能训练由 `admission_decisions` 和 Snapshot 内冻结的 `resolved_label_policy` 判断。如果 UI 需要显示整体状态，可以显示派生摘要 `mixed_segments`；真正进入训练时仍按 segment 过滤。

物理文件支持两种形式：

| 格式 | segment 如何定位 | 适用场景 |
| --- | --- | --- |
| 单个多标签 NIfTI | `value` 指向多标签整数值 | nnUNet 导出、全身合并展示 |
| 逐器官 mask 组 | `path` 指向每个器官二值 mask | Mimics/人工 review、逐器官编辑 |

标签修改采用追加版本：人工修正、QC 修复、状态提升都创建新的 `label_id` 或 `version`，并记录 `parent_label_id`。旧 artifact 保留，可标记为 `superseded`，但不能覆盖写。Snapshot 引用具体 `label_id/version/hash`，所以旧 Snapshot 不会因为标签修正而变化。

### 3.6 TaskDefinition 示例

TaskDefinition 是训练任务模板，不是一次训练事实。它维护默认任务规则；真正用于复现的是 Snapshot 内冻结后的 resolved copy。

```yaml
schema_version: task_definition.v1
task_id: CT5_Liver
modality: CT
target_anatomy:
  - gallbladder
  - liver
task_label_map:
  background: 0
  gallbladder: 1
  liver: 2
default_label_policy:
  policy_id: CT5_Liver_v1
  allow_lifecycle_status: [verified_label, source_label, candidate_label]
  candidate_label_requires:
    trusted_generators: [TotalSegmentator:v2]
    qc:
      geometry: pass
      min_confidence: 0.85
preprocess_profile:
  name: default_ct_abdomen
```

## 4. Dataset Snapshot 设计

Dataset Snapshot 是一次训练视图的冻结结果。它不等于原始数据拷贝，也不等于 nnUNet 导出目录。默认语义是 immutable manifest：冻结 case/image/label segment 的引用、版本、hash、split、resolved `label_policy`、准入决策、usage constraints 和预处理意图。

### 4.1 它负责什么

| 功能 | 说明 |
| --- | --- |
| 固定任务 | 记录 task_id、目标器官、TaskLabelMap |
| 固定样本 | 记录纳入哪些 case/image/label segment |
| 固定 split | 记录 train/val/test 或 fold 划分 |
| 固定准入策略 | 记录从 TaskDefinition 解析出的 resolved `label_policy` 和准入决策 |
| 固定输入版本 | 记录每个 image/label 的 hash 和 registry id |
| 固定使用限制 | 记录输入链路继承而来的 `usage_constraints` |
| 固定导出意图 | 记录希望导出给哪个 Adapter，例如 nnUNet |
| 固定预处理配置引用 | 记录 spacing、patch size、低分辨率 coarse 任务等配置的来源 |

### 4.2 它不负责什么

Snapshot 不应亲自执行 resample、crop、normalization 或 nnUNet preprocess。

更合理的边界是：

1. Snapshot 记录任务需要的预处理意图和配置引用。
2. Adapter 根据 Snapshot 导出训练框架需要的目录。
3. 训练框架或 Adapter 执行实际 resample/preprocess。
4. 执行结果和实际参数写回 Model Record 或 Export Record。

这样 coarse 任务可以表达为：

```yaml
snapshot_id: snap_ct_coarse_001
task_id: CT_All_Coarse
task_label_map: task_label_maps/CT_All_Coarse.yaml
preprocess_profile:
  name: coarse_low_resolution
  target_spacing: [3.0, 3.0, 3.0]
  interpolation:
    image: linear
    label: nearest
adapter_target:
  type: nnunet
  export_profile: low_resolution_coarse
```

Snapshot 关心的是“这次训练视图承诺用低分辨率 coarse 配置”；真正 resample 在 nnUNet Adapter 或 nnUNet preprocessing 中执行。

### 4.3 Snapshot 示例

```yaml
snapshot_id: snap_CT5_Liver_20260720_001
schema_version: dataset_snapshot.v1
task_id: CT5_Liver
created_by: trainer_a
created_at: "2026-07-20T10:00:00+08:00"

resolved_label_policy:
  source_policy: task_definitions/CT5_Liver.yaml#label_policy
  policy_id: CT5_Liver_v1
  allow_lifecycle_status:
    - verified_label
    - source_label
    - candidate_label
  source_label_requires:
    trusted_datasets: [BTCV:v1, AMOS:v2]
  candidate_label_requires:
    trusted_generators:
      - TotalSegmentator:v2
    qc:
      geometry: pass
      min_confidence: 0.85

task_label_map:
  background: 0
  gallbladder: 1
  liver: 2

split_policy:
  split_scope: snapshot
  leakage_key: leakage_group_id
  source_split_plan: split_abdomen_v1

cases:
  train:
    - case_id: case_001
      image_id: img_001
      segments:
        - organ: liver
          label_id: lbl_001
          segment_status: verified_label
        - organ: gallbladder
          label_id: lbl_001
          segment_status: candidate_label
          admission_decision:
            result: accepted
            policy_id: CT5_Liver_v1
  val:
    - case_id: case_010
      image_id: img_010
      segments:
        - organ: liver
          label_id: lbl_010
          segment_status: verified_label

usage_constraints:
  model_training: allowed_with_policy
  commercial_use: needs_review
  redistribution: forbidden
```

Snapshot 创建后不可修改。如果某个 Label Artifact 在 Snapshot 创建后被修正，Registry 会新增 `label_id/hash`；旧 Snapshot 继续引用旧标签。如果 TaskDefinition 的默认 `label_policy` 之后改变，旧 Snapshot 也不受影响。要使用修正后的标签或新策略，必须创建新 Snapshot。导出的 nnUNet 目录、低分辨率缓存或 NIfTI 副本只是 materialized export，不是 Snapshot 的真相来源。

Split 默认存储在 Snapshot 内，也可以引用全局 `SplitPlan`。即使引用全局计划，Snapshot 也要记录当时解析出来的 case 列表和 leakage key。不同任务可以有不同 split；若一个模型使用 A 任务训练后在 B 任务评估，评估动作必须用 Model Record 的训练 Snapshot 和 B 的评估 Snapshot 做 `leakage_group_id` 交集检查，交集非空则判为泄漏或要求显式豁免。

FewShot Adapter 共享 Snapshot 数据契约，但第一阶段不把 few-shot episode 写进主 Snapshot schema。实验时使用 sidecar `fewshot_protocol.yaml`：

```yaml
fewshot_protocol:
  shot_unit: case
  repeats: 5
  split_roles:
    support_pool: train
    query: val
    final_test: test
  shots_per_anatomy:
    liver: [1, 3, 5, 10]
  seed: 20260610
```

FewShot 的 support/query episode 必须随 Model Record 保存，不能在训练脚本里临时随机生成后丢失。后续如果 FewShot 成为正式能力，再决定是否把 protocol 升级为 Snapshot schema 的一部分。

## 5. Model Record 设计

Model Record 是训练结果的登记表。它让评估者和下一轮 label_generation 能知道模型从哪里来、能用于什么、不能用于什么。平台自己训练出的模型在 label_generation 中直接以 Model Record 作为来源。

### 5.1 它负责什么

| 功能 | 说明 |
| --- | --- |
| 训练追溯 | 记录 Snapshot、训练框架、代码版本、配置 |
| 权重登记 | 记录模型权重、fold、ensemble、checkpoint |
| 指标登记 | 记录 Dice、Surface Dice、失败病例、评估集 |
| 使用边界 | 记录适用模态、器官、扫描范围、禁止用途和继承的 usage constraints |
| 回流入口 | 作为 label_generation 批量推理的输入模型 |

### 5.2 示例

```yaml
model_id: model_CT5_Liver_001
schema_version: model_record.v1
task_id: CT5_Liver
framework: nnUNet
adapter: adapters/nnunet
snapshot_id: snap_CT5_Liver_20260720_001
code_version: git:abc123
config:
  nnunet_dataset_id: Dataset501
  folds: [0, 1, 2, 3, 4]
weights:
  path: models/model_CT5_Liver_001/
metrics:
  validation:
    dice_mean: 0.91
    surface_dice_mean: 0.86
usage:
  allowed_for_candidate_generation: true
  allowed_for_formal_evaluation: false
usage_constraints:
  model_training: allowed_with_policy
  commercial_use: needs_review
  redistribution: forbidden
  derivative_model_release: unknown
limitations:
  - "只验证过 CT 腹部任务"
```

### 5.3 generator metadata

`generator metadata` 是第一阶段对外部标签生成来源的轻量记录。它不是必须先做成数据库表；可以是 `generators/*.yaml`，也可以内嵌在 Label Artifact 的 `source.generator` 字段。它记录外部算法、公开工具、规则脚本或 Docker/CLI 工作流的来源。

```yaml
schema_version: generator_metadata.v1
generator_id: totalsegmentator_v2
type: external_algorithm
name: TotalSegmentator
version: "v2.x"
runtime:
  kind: cli
  command_template: "TotalSegmentator -i {image} -o {output}"
license:
  status: needs_review
usage_constraints:
  model_training: needs_policy
  commercial_use: needs_review
  redistribution: forbidden
  derivative_model_release: unknown
inputs:
  modality: CT
outputs:
  label_mapping: mappings/totalsegmentator_to_anatomy.yaml
provenance_required:
  parameters: true
  runtime_log: true
  qc_report: true
```

label_generation 不允许“无来源生成”。即使只是调用公开算法，也要在输出 Label Artifact 的 `source.generator` 中记录对应 metadata。后续服务化时，这个 metadata 可以升级为正式来源管理模块。

## 6. Adapter 标准

Adapter 的标准不是“所有工具都长得一样”，而是“对平台暴露同样的输入输出契约”。

### 6.1 labeling Adapter 标准

任意来源数据集或标注工具要进入 labeling 域，最低标准是能转成：

1. Image Artifact。
2. Label Artifact 或空标签入口。
3. anatomy vocabulary 映射。
4. review label map 映射。
5. provenance。
6. geometry/QC 报告。

因此，一个任意来源数据集不是“直接统一到 labeling 域”，而是先经过 **ingest/import**，登记为平台 Artifact，再按需要生成 Case Package 给 labeling 域 review。

### 6.2 training Adapter 标准

不同于 nnUNet 的训练框架可以加入 training 域。标准是：

1. 输入必须是 Dataset Snapshot。
2. 不能直接读取散落原始文件绕过 Registry。
3. 必须声明自己如何解释 TaskLabelMap。
4. 必须记录实际预处理、训练配置和代码版本。
5. 必须产出 Model Record。

如果某个算法不是训练框架，而只是用现成模型推理生成标签，它更可能属于 `label_generation`，不是 `training`。

### 6.3 label_generation Adapter 标准

label_generation 可以自定义接入已有算法，也可以替换伪标签生成策略。标准是：

1. 输入是 Image Artifact 集合和 `generator metadata` 或 Model Record。
2. 输出必须登记为 `candidate_label`，不能直接伪装成 `verified_label`。
3. 必须提供 label mapping。
4. 必须提供 QC 报告。
5. 可以提供 admission evidence 或送审建议，但最终是否进入训练由 Snapshot 的 `resolved_label_policy` 决定。

平台训练得到的模型用 Model Record 作为来源；外部算法用 `generator metadata` 作为来源，不能绕过来源记录直接写 Label Artifact，也不能直接生成全局可训练标签。

## 7. QC 在哪里发生

QC 不是单个域独占，而是每个关键边界上的 gate。

| 位置 | 触发时机 | 主要 QC | 执行者 | 失败后 |
| --- | --- | --- | --- | --- |
| 数据导入 Registry | 新数据进入平台 | 文件可读、hash、空间元数据、label value 合法 | 自动脚本；异常由平台管理员处理 | 生成 QC Report，修复后重新导入或创建新 `label_id/hash` |
| Case Package 生成前 | 发给标注者前 | 包完整性、配置 hash、草稿标签几何 | 自动脚本 | 阻断导出，修复 package 后重跑 |
| Review 导回 | 标注者提交后 | shape、spacing、origin、direction、label id、空标签 | 自动脚本；异常由标注者或管理员裁决 | 不覆盖旧标签，修复后提交新 `label_id/hash` |
| Snapshot 创建 | 训练前 | 生命周期状态、来源、QC 证据、usage constraints、扫描范围、任务 label map、split 泄漏 | 平台自动检查；训练者选择策略 | Snapshot 创建失败，调整策略或数据后重建 |
| 训练导出 | Adapter materialize 数据时 | 导出 mask label id、缺失标签策略、ignore/exclude 策略、空类别、label 连续性 | training Adapter | 导出失败，不启动训练 |
| 批量推理后 | candidate 生成后 | 几何、内容、置信度/规则、异常体积 | 自动脚本；低置信进入人工 review | 进入 `draft_label` / `rejected_label` / 重新推理 |
| 评估前 | 评估集冻结前 | 评估标签状态、来源、是否泄漏 | 自动脚本；评估者确认策略 | 阻断正式评估或要求显式豁免 |

目标是让人工只处理“医学判断”和“异常裁决”，不要人工做 hash、路径、label id、几何头这类机械检查。

QC Report 是追加记录，不是标签状态本身。失败标签修复后应生成新 `label_id/hash`，并重新运行对应 QC 脚本；平台不应修改旧 QC Report。

空间一致性是平台级 gate。Label Artifact 的 `geometry_ref` 必须指向 Image Artifact；导入、review 导回、推理回流、Snapshot 创建、训练导出都要验证 shape、spacing、origin、direction 和 affine。shape 相同但 affine 或方向不一致时，默认阻断，不允许静默进入训练。

## 8. 缺失标签在哪里区分

“缺失标签不等于器官不存在”主要在两个地方生效：

1. **数据导入/登记时**：Registry 要记录某个器官是 `uncovered`、`missing_label`、还是 `confirmed_absent`。
2. **Dataset Snapshot 创建时**：训练导出必须按这些状态决定某个 voxel 是否能作为背景学习。

训练导出时不能简单说“没有 liver 标签，所以 liver 是背景”。更稳的逻辑是：

| 状态 | Snapshot 处理 |
| --- | --- |
| `uncovered` | 该器官不参与这个 case 的训练监督 |
| `missing_label` | 不当作背景；该结构在该 case 中不提供监督 |
| `confirmed_absent` | 可作为阴性信息进入任务，前提是任务支持 |
| 有可准入标签 | 按 TaskLabelMap 写入训练 mask |

nnUNet Adapter 第一阶段采用保守规则：如果某 case 缺失当前任务的目标器官标签，则该 case 不进入该多类任务的 `labelsTr`；如果是逐器官任务，则只排除该 case 对该器官的监督。不要在标准 nnUNet 导出里把 `missing_label` 写成背景。只有当 Adapter 明确实现 ignore mask / partial-label loss，并在 Model Record 中记录 trainer、ignore label 值和 loss 行为时，才允许用 loss mask 方式处理。

## 9. 状态维护会不会太重

如果要求每个器官、每个文件、每次操作都手工维护状态，确实会臃肿。

推荐做法是：

1. 平台自动生成大多数状态。
2. 人只在少数节点做确认。
3. 生命周期状态按 segment 记录，但 UI 聚合展示。
4. 训练准入不是手工状态，而是 Snapshot 创建时的 policy 结果。

例如：

| 场景 | 平台如何记录 |
| --- | --- |
| 外部数据集导入 | 默认 `source_label`，来源为 dataset import |
| 模型推理输出 | 默认 `candidate_label`，来源为 Model Record 或 `generator metadata` |
| 生成给人修的草稿 | 平台从 candidate 转成 `draft_label` |
| 标注者保存并提交 | 第一阶段自动登记为 `verified_label` |
| 规则认为高质量伪标签可用 | 保持 `candidate_label`，追加 QC evidence 或 admission decision |
| QC 明确失败 | 自动登记为 `rejected_label` |

BTCV、AMOS 等公认公开数据集可以保持 `source_label` 状态，并由 Snapshot 的 `resolved_label_policy` 显式允许进入训练；不需要为了训练而伪装成 `verified_label`。模型或算法输出保持 `candidate_label`，即使某个任务接受它训练，也只是该任务下的 admission decision。

腹部数据集中肝来自人工、肾来自算法时，平台只需要在同一个 Label Artifact 的 segments 里分别记录：

```yaml
segments:
  liver:
    lifecycle_status: verified_label
    source: manual_review
  kidney_left:
    lifecycle_status: candidate_label
    source: TotalSegmentator
    admission_decisions:
      - task_id: CT_Kidney
        policy_id: CT_Kidney_v1
        result: accepted
```

训练者在 UI 里不需要逐条编辑这些状态，只需要选择任务策略：

```yaml
resolved_label_policy:
  allow_lifecycle_status: [verified_label, source_label, candidate_label]
  candidate_label_requires:
    trusted_generators: [TotalSegmentator:v2]
    qc:
      geometry: pass
      min_confidence: 0.85
```

## 10. validate 命令和最小 walkthrough

第一阶段即使是文件包和离线脚本，也要有统一 `validate` 入口。它不替代业务流程，但负责在训练、导入 Mimics、生成 Snapshot 之前阻断结构性错误。

```bash
sp validate vocabulary anatomy_vocabulary.yaml
sp validate registry registry/
sp validate task-map task_label_maps/CT5_Liver.yaml
sp validate snapshot snapshots/snap_CT5_Liver_001.yaml
sp validate export nnunet_exports/CT5_Liver_001/
```

最低检查项：

| 对象 | 检查 |
| --- | --- |
| Vocabulary | 器官 key 唯一、aliases 不冲突、parent 存在、laterality 合法、global id 不重复 |
| TaskLabelMap | label 从 0 开始、整数连续、无重复、器官都在 Vocabulary 中 |
| Registry | manifest 有 `schema_version`、id/hash 可解析、usage constraints 不缺失 |
| Label Artifact | `geometry_ref` 存在、shape/spacing/origin/direction/affine 与 Image Artifact 一致 |
| Snapshot | split 无 leakage、resolved policy 已冻结、candidate 准入有 QC evidence |
| nnUNet export | 类别不全空、导出 label 值合法、dataset.json 与 TaskLabelMap 一致 |

最小可用 walkthrough 应该长这样：

```text
导入肝胆 CT 数据
  -> validate registry
  -> 生成 review package
  -> 标注者打开、修正、提交
  -> 导回并 validate geometry
  -> 创建 CT5_Liver Snapshot
  -> validate snapshot
  -> nnUNet Adapter materialize export
  -> validate export
  -> 启动训练
  -> 写入 Model Record
  -> 批量推理生成 candidate_label
  -> candidate 回流为下一轮 Snapshot 的可选输入
```

这个 walkthrough 后续可以展开成命令文档；架构层只固定动作边界。

## 11. combine map 的含义

`combine_map` 不是训练 label map。它用于把多个模型输出合成一个全身展示或导出结果。

典型场景：

1. 现有 v500 可能由多个局部模型组成，例如肺、肝胆、椎体、粗分割等。
2. 每个模型训练时的 label id 都从 1 开始，彼此会重复。
3. 如果要把多个模型输出放进同一个全身 mask，就需要一个全局展示编号。

例子：

```yaml
task_label_map:
  task_id: CT5_Liver
  labels:
    background: 0
    gallbladder: 1
    liver: 2

combine_map:
  map_id: CT_Combine
  source: anatomy_vocabulary.global_label_id
  labels:
    liver: 37
    gallbladder: 38
```

训练时 liver 可以是 2；全身合并展示时 liver 可以是 37。这不是冲突，因为两者服务不同目的。

长期维护上，`combine_map` 不应手工给所有器官编号。Anatomy Vocabulary 应维护稳定 `global_label_id`；`combine_map` 默认只声明包含哪些器官。现有 v500 编号可以作为 legacy override 保留，以兼容历史输出。

体素冲突不由 `combine_map` 解决，而由 `combine_policy` 或后处理逻辑解决：

```yaml
combine_policy:
  conflict_strategy: priority_then_confidence
  priority:
    gallbladder: 90
    liver: 80
  tie_breaker: higher_probability
  on_unresolved_conflict: mark_conflict_and_keep_empty
  log_conflict_voxels: true
```

默认不允许静默覆盖。多个模型在同一体素给出不同结构时，必须按优先级、概率图或任务规则决定；无法决定时记录 conflict mask 或 QC Report。

## 12. Mimics 拿到软件和 license 后做什么

拿到 Mimics 后，不要先写完整 Adapter。先做 8 个验证。

### 12.1 验证 Mimics 本身功能

| 验证 | 要回答的问题 |
| --- | --- |
| 图像导入 | DICOM 和 NIfTI 哪个稳定？方向和 spacing 是否正确？ |
| 草稿显示 | 多标签 NIfTI 能否稳定显示为可编辑结构？如果不能，逐器官 mask 是否可行？ |
| 人工编辑 | 标注者能否自然修正、保存、撤销、查看 3D/2D？ |
| 标签导出 | 能导出单个多标签 NIfTI，还是只能导出逐器官 mask？ |
| 空间往返 | 导出标签和原图 shape 是否一致？affine/spacing 是否可解释？ |

### 12.2 验证脚本联动能力

| 验证 | 要回答的问题 |
| --- | --- |
| Python 脚本入口 | license 是否允许运行 Python scripting？ |
| 批量创建 mask | 脚本能否根据平台 mask 文件创建 Mimics Mask？ |
| 命名和颜色 | 脚本能否自动设置 mask 名称和颜色？ |
| 读取 mask buffer | 脚本能否把 Mimics mask 转成数组或导出文件？ |
| 无 GUI 批量 | 是否能减少人工导入导出，还是必须人工点选？ |

### 12.3 为什么必要时拆成逐器官 mask

拆成逐器官 mask 是为了降低工具解释风险。

单个多标签 NIfTI 依赖工具正确理解 label id、颜色、名称和多类别编辑。很多标注工具内部更自然的对象是“一个器官一个 mask”。拆开后：

1. 每个 mask 名称就是器官 key。
2. 人工更容易隐藏、显示、编辑某个器官。
3. 导出后更容易判断哪个器官出错。
4. 平台可以用 `review_label_map.yaml` 再合并回多标签文件。

这不是平台最终必须永远使用的格式，而是 POC 阶段更稳的交换策略。

## 13. 仍待讨论问题的影响

| 问题 | 影响哪一步 | 如果不解决会怎样 |
| --- | --- | --- |
| 扫描范围如何记录 | Registry 导入、Snapshot 创建 | 可能把扫描范围外器官误当背景训练 |
| 具体 license 裁决 | 数据导入、Model Record、模型发布 | usage constraints 必须记录和传播，但每个来源是否允许商业训练/发布仍要逐项确认 |
| 正式评估准入 | 评估集冻结、Model Record 指标 | 内部迭代指标和正式验收指标可能混在一起 |
| candidate admission 阈值 | Snapshot 创建 | 高质量候选标签能训练，但不同器官和生成器的阈值还要实验沉淀 |
| Mimics 是否主工具 | labeling Adapter | 影响自动化程度和标注员工作方式 |

这些问题不阻塞第一阶段文件闭环，但会影响 8-10 月的平台加固和验收标准。
