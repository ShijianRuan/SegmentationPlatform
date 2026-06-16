# 病例包（Case Package）交换契约 v0.5

> 更新日期：2026-06-15
> 状态：第一阶段离线文件交换契约
> 原则：不强制多个序列有主次；每份标签明确绑定自己的 `image_id`

## 1. 病例包解决什么问题

病例包是平台与标注工具之间的一份离线工作目录。它让标注者不需要访问平台数据库或训练目录，也能拿到本次工作所需的：

- 一个或多个图像序列。
- 每个序列需要处理的器官。
- 可选的初始标签。
- 器官名称和标注交换编号。
- 工作进度目录。
- 提交结果和问题报告目录。

病例包不包含 nnUNet 训练任务的整数标签编号。同一份人工标签可以在后续被多个训练任务使用。

标注者的实际操作见[人工标注工作流](labeling_workflow.md)。

## 2. 推荐目录

```text
dataset_package/
  config/
    anatomy_vocabulary.yaml
    review_label_map.yaml
  cases/
    case_001/
      manifest.json
      images/
        img_noncontrast/
          image.nii.gz
          dicom/
        img_arterial/
          image.nii.gz
          dicom/
      labels/
        img_noncontrast/
          draft_label.nii.gz
          masks/
        img_arterial/
          draft_label.nii.gz
          masks/
      working/
        review_case001_001.mcs
        bridge/
        checkpoints/
          review_case001_001/
            latest.json
            20260615T120000Z/
              checkpoint_manifest.json
              buffers/
      submissions/
        review_case001_001/
          submission_manifest.json
          export_manifest.json
          buffers/
            img_noncontrast/
              target_noncontrast_abdomen/
                liver.u8
            img_arterial/
              target_arterial_liver/
                liver.u8
          labels/
            img_noncontrast/
              target_noncontrast_abdomen/
                liver.nii.gz
      reports/
        ingest_report.json
        mimics_open_report.json
        mimics_submit_precheck.json
        review_report.json
      provenance/
        tool_export.json
```

单序列病例也使用 `image_sets` 数组，只包含一个元素。平台不维护另一套“单图像病例”格式。

`working/checkpoints/` 是可选灾备内容。它保存全部受管 Mask 的 gzip 压缩 `.u8.gz` 快照和 manifest，
用于 `.mcs` 损坏时重建，不代表提交，也不进入标签生命周期。

## 3. 三种名称和编号表

| 文件或对象 | 用途 |
| --- | --- |
| `anatomy_vocabulary.yaml` | 统一不同数据集和工具对同一器官的名称 |
| `review_label_map.yaml` | 规定标注交换文件中的稳定整数标签；当前实现从完整器官词表生成，避免逐病例改写共享配置 |
| 任务标签编号表（TaskLabelMap） | 规定训练任务中的整数标签，只存在于训练数据快照和训练导出 |

病例包不绑定某个训练任务。

## 4. 病例清单（`manifest.json`）

```json
{
  "schema_version": "case_package.v0.5",
  "package_id": "pkg_case001",
  "case_id": "case001",
  "leakage_group_id": "subject_pseudo_001",
  "study_id": "study_pseudo_001",
  "patient_id_hash": "hmac-sha256:...",
  "study_instance_uid_hash": "hmac-sha256:...",
  "data_governance": {
    "deidentification_status": "verified",
    "profile": "internal_dicom_profile_v1",
    "profile_version": "1.0"
  },
  "created_at": "2026-06-12T10:00:00+08:00",
  "config_ref": "../../config/",
  "config_sha256": {
    "anatomy_vocabulary.yaml": "TO_BE_FILLED",
    "review_label_map.yaml": "TO_BE_FILLED"
  },
  "image_sets": [
    {
      "image_id": "img_noncontrast",
      "modality": "CT",
      "image_path": "images/img_noncontrast/image.nii.gz",
      "dicom_path": "images/img_noncontrast/dicom",
      "sha256": "TO_BE_FILLED",
      "shape": [512, 512, 300],
      "spacing": [0.8, 0.8, 1.0],
      "origin": [-200.0, -180.0, -300.0],
      "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
      "coordinate_system": "LPS"
    },
    {
      "image_id": "img_arterial",
      "modality": "CT",
      "dicom_path": "images/img_arterial/dicom",
      "sha256": "TO_BE_FILLED",
      "shape": [512, 512, 280],
      "spacing": [0.8, 0.8, 1.0],
      "origin": [-200.0, -180.0, -280.0],
      "direction": [1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0],
      "coordinate_system": "LPS"
    }
  ],
  "review": {
    "review_id": "review_case001_001",
    "tool": "mimics",
    "status": "ready",
    "assignee": "annotator_03",
    "targets": [
      {
        "target_id": "target_noncontrast_abdomen",
        "image_id": "img_noncontrast",
        "organs": ["liver", "kidney_left", "kidney_right"],
        "base_label_id": "label_noncontrast_v1",
        "base_label_sha256": "sha256:..."
      },
      {
        "target_id": "target_arterial_liver",
        "image_id": "img_arterial",
        "organs": ["liver", "hepatic_artery"]
      }
    ]
  }
}
```

平台生成的清单还可包含 `initial_labels`，逐项记录初始 Mask 的 `image_id`、器官、相对路径、文件哈希、`label_id`、生命周期和使用限制。该数组由 `sp package create` 生成，不要求操作者手写。

### 4.1 必须满足的规则

1. `image_sets` 至少包含一个图像序列。
2. 每个 `image_id` 在包内唯一。
3. `review.targets` 至少包含一个目标组。
4. 每个目标组有唯一 `target_id`，并引用已存在的 `image_id`。
5. 目标组的 `organs` 不能为空。
6. `base_label_id` 和 `base_label_sha256` 要么同时存在，要么同时省略。
7. `assignee` 第一阶段可选，多人工作时建议设置。
8. 不同目标组的标签分别绑定自己的图像空间，不能假设多个序列已配准。
9. `target_id` 是最小提交单位；组内器官一起完成或一起进入复查。
10. `data_governance.deidentification_status` 必须是 `verified`。
11. `leakage_group_id` 和 `study_id` 对所有来源必填。
12. `patient_id_hash` 和 `study_instance_uid_hash` 只在来源可靠且已按治理规则伪名化时记录。

去标识声明不能替代导入阶段的 DICOM 标签检查。

### 4.2 哪些文件校验值必须稳定

`manifest.json` 中以下文件要记录校验值：

- 图像。
- 器官名称表。
- 标注交换编号表。
- 基础标签。
- 完成提交的结果。

`checksums.sha256` 只用于复制或归档整个目录时的可选传输检查。工作过程中的 `.mcs`、报告和任务状态会变化，因此不要求整个工作目录始终保持同一个包级校验值。

## 5. 标注任务和目标组状态

第一阶段使用：

- `ready`
- `in_progress`
- `needs_review`
- `completed`
- `blocked`

固定用户动作：

- `save_progress`
- `submit_complete`
- `submit_for_review`
- `report_blocked`

这些动作不需要在每个清单中重复定义。在线锁定、任务领取、“提交中”和“退回”属于后续服务化。

完成提交时同步运行质量检查：

```text
目标组检查通过
-> 目标组 completed
-> 创建 verified_label

目标组检查失败
-> 目标组 in_progress
-> 生成问题报告
```

标注任务状态由所有目标组汇总：

- 所有目标组完成，任务才是 `completed`。
- 任一目标组需要复查，任务显示 `needs_review`。
- 一个目标组失败不会撤销其他已完成目标组。

## 6. 标签输入

每个图像序列可以包含：

```text
labels/{image_id}/source_label.nii.gz
labels/{image_id}/candidate_label.nii.gz
labels/{image_id}/draft_label.nii.gz
labels/{image_id}/masks/{organ}.nii.gz
```

| 状态 | 在病例包中的意义 | 是否自动进入训练 |
| --- | --- | --- |
| `source_label` | 外部数据集自带标签 | 否，由训练数据快照中的规则判断 |
| `candidate_label` | 模型或算法候选标签 | 否，可由训练数据快照中的规则接受 |
| `draft_label` | 人工正在修正或等待复查 | 否 |
| `verified_label` | 完成提交且平台检查通过后创建 | 仍受训练任务和使用限制约束 |
| `rejected_label` | 已明确拒绝 | 否 |

保存 `.mcs` 不改变标签状态。

## 7. 标注工具适配器读取什么

工具适配器读取：

- `manifest.json`
- `image_sets`
- `review.targets`
- 可选初始标签
- 器官名称表
- 标注交换编号表

工具内部可以有“当前活动图像”、当前图层或当前分割等状态，但这些状态不能替代目标组中的 `image_id`。

Mimics 21.0 的实际交换路径由可行性验证决定：

1. 直接文件导入导出稳定时，优先使用直接路径。
2. 只有 Mask 体素数组交换稳定时，才启用外部格式脚本和 `.u8` 文件桥接。
3. 空间关系无法可靠往返时，切换标注工具。

## 8. 提交结果目录

每次提交至少包含：

```text
submissions/{review_id}/submission_manifest.json
submissions/{review_id}/export_manifest.json
submissions/{review_id}/buffers/{image_id}/{target_id}/{organ}.u8
reports/review_report.json
provenance/tool_export.json
```

`export_manifest.json` 中的 buffer `path` 必须相对病例包根目录保存，并声明
`path_base: package_root`。这样 Mimics 工作站生成的完整病例包可以迁移回平台机器，
且平台会拒绝逃逸到病例包目录之外的相对路径。

最小 `submission_manifest.json`：

```json
{
  "schema_version": "review_submission.v1",
  "review_id": "review_case001_001",
  "target_ids": ["target_noncontrast_abdomen"],
  "action": "submit_complete",
  "assignee": "annotator_03",
  "base_labels": {
    "target_noncontrast_abdomen": {
      "label_id": "label_noncontrast_v1",
      "sha256": "sha256:..."
    }
  },
  "organ_outcomes": {
    "target_noncontrast_abdomen": {
      "liver": "present",
      "kidney_left": "present",
      "kidney_right": "confirmed_absent"
    }
  }
}
```

`organ_outcomes` 允许 `present`、`confirmed_absent` 和 `uncertain`。`submit_complete` 不能包含 `uncertain`；空 Mask 只有明确声明 `confirmed_absent` 才能作为完成结果。

如果工具直接导出 NIfTI，可以写入：

```text
submissions/{review_id}/labels/{image_id}/{organ}.nii.gz
```

提交清单必须声明本次提交的 `target_ids`。被声明为完成的目标组必须包含该组全部器官。不同目标组可以分次提交。

单个 Mask 导出只用于调试，或目标组本身只有一个器官。

## 9. 提交检查

| 检查项 | 失败处理 |
| --- | --- |
| 清单格式、配置引用或文件校验值错误 | 阻断 |
| `image_id` 缺失或重复 | 阻断 |
| `target_id` 缺失、重复或没有器官 | 阻断 |
| 标签与目标图像的空间关系无法解释 | 阻断 |
| 未知器官或未知标签值 | 阻断 |
| 完成提交缺少目标组中的 Mask | 阻断该目标组 |
| `review_id`、`target_id`、`assignee` 或基础标签版本不匹配 | 拒绝登记 |
| 标签内容检查失败 | 回到 `in_progress` 并生成问题报告 |

不能仅因为数组大小相同就复制 affine。任何重采样必须创建新的文件记录并保存变换过程。

如果目录中有 `checksums.sha256`，提交前检查会验证其中列出的文件；没有该文件不报错。完成提交后应对提交结果单独记录校验值。

## 10. 多人协作和继续修订

第一阶段不实现在线锁服务：

- 任务清单可以记录 `assignee`。
- 协调者避免把同一目标组同时分给两个人。
- 同一病例的不同目标组可以并行。
- 提交时用 `target_id` 和基础标签校验值阻止旧版本覆盖。
- 第二人复核或继续修订人工确认标签时，创建新标注任务。
- 旧标签记录和旧训练数据快照保持不变。

## 11. 为什么 nnUNet 不直接读取病例包

```mermaid
flowchart LR
    accTitle: 病例包到训练数据的关系
    accDescr: 病例包提交结果先进入资产登记册，再由训练数据快照选择，最后通过 nnUNet 工具适配器导出。

    package["病例包"]
    registry["资产登记册"]
    snapshot["训练数据快照"]
    adapter["nnUNet 工具适配器"]
    nnunet["nnUNet 输入目录"]

    package --> registry
    registry --> snapshot
    snapshot --> adapter
    adapter --> nnunet
```

病例包服务人工标注。nnUNet 工具适配器根据训练数据快照和任务标签编号表，选择具体图像、标签版本和整数编号。

## 12. 仍需实际验证

| 问题 | 验证结果怎样影响实现 |
| --- | --- |
| Mimics 21.0 是否有稳定直接文件路径 | 当前实现仍保留 `.u8` 桥接；实测证明直接路径同样可靠后才可简化 |
| 多图像集上的 Mask 能否稳定绑定和切换 | 决定 Mimics 脚本能否安全自动化 |
| `.mcs` 能否跨机器打开 | 决定它只作为本机进度文件，还是可以作为可移动工作包 |
| 不同序列是否需要配准 | 由具体任务决定，不作为所有病例的默认前提 |
