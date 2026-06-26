# 数据集描述契约

> 状态：阶段 A 的复杂数据集导入入口  
> 目的：把数据集特有的目录结构、图像-标签配对和 label value 映射，在 `package create` 之前消化成标准 Case Package Request。

## 1. 为什么需要这一层

`sp ingest scan` 适合回答“有哪些图像文件可读”。它不应该承担所有数据集语义，尤其不应该猜：

- 哪个 NIfTI 是图像，哪个 NIfTI 是标签；
- 一个标签文件中的 `1`、`2`、`3` 分别代表哪个器官；
- 文件名中的 `liver`、`spleen` 是否可靠对应平台器官词表；
- 分开的图像目录和标签目录怎样配对；
- 哪些序列应该进入本次标注任务。

这些是数据集特有知识，必须在 `package create` 之前显式表达。阶段 A 用 `dataset_description.v1` 承接这件事：

```text
外部数据集
-> dataset_description.yaml
-> sp ingest plan
-> case_package_request.v1
-> sp package create-many
```

`dataset_description` 本身不直接写 Registry，也不生成正式 Image/Label Artifact。它只生成可审阅的病例包请求。若只想先登记图像资产，应使用 `sp ingest scan -> sp ingest register`；若要把数据集特有的图像-标签配对和 label map 一起消化，则使用本契约生成 request，再由 `sp package create-many` 做几何校验、病例包创建和标签登记。

## 2. 数据集接入分级

不要追求一个万能自动 parser。真实医学数据集的差异来自采集系统、脱敏方式、公开数据集发布习惯、标注工具和研究者自定义脚本。平台要做的是把差异分层消化，而不是猜。

| 等级 | 适用情况 | 入口 | 结果 |
| --- | --- | --- | --- |
| L0：标准 DICOM | 有可靠 DICOM Study/Series 元数据 | `sp ingest scan` | 自动分组并生成草稿请求 |
| L1：简单文件型图像 | NIfTI/MHD/MHA 图像文件规则简单，标签暂不导入 | `sp ingest scan` + 审阅 request | 图像进入 request，标签后补 |
| L2：声明式数据集 | 图像、标签和 label map 可用正则或 CSV 明确描述 | `sp ingest plan dataset_description.yaml ...` | 生成带 `initial_labels` 的 request |
| L3：预整理脚本 | 原始结构混乱，但可以被整理成 L2 所需 CSV 或目录 | 自写短脚本输出 `dataset_description.yaml` 或 `images.csv/labels.csv` | 再走 L2 |
| L4：专用 importer | 需要读取私有元数据、多个 sidecar、特殊压缩包或复杂规则 | 按[专用数据集 Importer 契约](custom_importer_contract.md)自写 adapter | 输出标准 request、summary 和 issues，再走 `package create-many` |
| L5：人工隔离 | 无法确定图像-标签配对、器官语义或空间关系 | 不入库，写入问题清单 | 人工确认或放弃该批数据 |

核心规则：

- L0-L2 是平台内置路径。
- L3-L4 是“把混乱数据翻译成平台已知输入”的桥，不是长期绕过平台。
- L5 不是失败，而是防止错误数据静默进入训练集。

## 3. 支持的两种表达方式

### 3.1 正则发现

适合目录规则稳定的数据集，例如 TotalSegmentator、MSD。

```yaml
schema_version: dataset_description.v1
dataset_id: totalseg_like
root: /data/totalseg
defaults:
  organs: [liver, spleen]
  modality: CT
  import_batch: totalseg_202606
  assignee: annotator_01
discovery:
  images:
    - regex: (?P<case>[^/]+)/ct\.nii\.gz
      case_id: case_{case}
      study_id: study_{case}
      image_id: img_{case}
      format: nifti
  labels:
    - regex: (?P<case>[^/]+)/segmentations/(?P<organ>liver|spleen)\.nii\.gz
      type: per_organ
      image_id: img_{case}
      organ: "{organ}"
      lifecycle_status: source_label
```

规则说明：

- `regex` 匹配相对 `root` 的路径。
- `(?P<case>...)` 是推荐的病例分组键。
- `case_id`、`study_id`、`image_id` 是模板，引用正则命名组。
- `type: per_organ` 表示一个文件对应一个器官，`organ` 必须能归一到 Anatomy Vocabulary。

### 3.2 多标签文件

适合 MSD 这类 `imagesTr/` 和 `labelsTr/` 分离的数据集。

```yaml
schema_version: dataset_description.v1
dataset_id: msd_liver_like
root: /data/msd_liver
defaults:
  organs: [liver, spleen]
  modality: CT
  import_batch: msd_202606
discovery:
  images:
    - regex: imagesTr/(?P<case>[^/]+)\.nii\.gz
      case_id: case_{case}
      study_id: study_{case}
      image_id: img_{case}
      format: nifti
  labels:
    - regex: labelsTr/(?P<case>[^/]+)\.nii\.gz
      type: multilabel
      image_id: img_{case}
      label_map:
        liver: 1
        spleen: 2
      lifecycle_status: source_label
```

同一个多标签数据集如果换成 `1=spleen, 2=liver`，只改 `label_map`，不改平台代码。

### 3.3 CSV 配对

适合图像和标签完全分开放，或配对关系来自外部表格的数据集。

```yaml
schema_version: dataset_description.v1
dataset_id: hospital_batch_a
root: /data/hospital_batch_a
defaults:
  organs: [liver, spleen]
  modality: CT
  import_batch: hospital_a_202606
tables:
  images: images.csv
  labels: labels.csv
```

`images.csv` 最小列：

```csv
case_id,study_id,image_id,path,format,modality,target_organs
case_001,study_001,img_ct,images/case_001.nii.gz,nifti,CT,"liver,spleen"
```

`labels.csv` 最小列二选一：

```csv
case_id,image_id,path,organ,lifecycle_status
case_001,img_ct,labels/case_001_liver.nii.gz,liver,source_label
```

或：

```csv
case_id,image_id,path,label_map,lifecycle_status
case_001,img_ct,labels/case_001.nii.gz,"{""liver"": 1, ""spleen"": 2}",source_label
```

## 4. 不能适配时怎么办

遇到新数据集时，按下面顺序处理。

1. **先做数据画像**：列出文件类型、目录层级、病例数、图像文件数量、标签文件数量、是否有 README、CSV、JSON、label definition 或论文说明。
2. **判断 label 语义来源**：如果没有地方说明 `value -> organ` 或 `filename -> organ`，该标签不能作为 `source_label` 自动导入。
3. **判断 image-label 配对依据**：可以来自同名、正则命名组、CSV、DICOM UID、sidecar JSON 或人工表格。没有配对依据时不能导入标签。
4. **判断空间依据**：图像和标签必须能通过 header/affine/DICOM 几何证明一致；只有 shape 相同不够。
5. **优先写 CSV 而不是写代码**：只要能整理出 `images.csv` 和 `labels.csv`，就不需要专用 importer。
6. **CSV 也表达不了再写 adapter**：adapter 只负责读取这个数据集的奇怪结构，输出 `dataset_description.yaml`、CSV 或标准 request；若直接输出 request，必须同时输出 importer manifest、summary 和 issues。
7. **仍不确定就隔离**：生成 `dataset_issues.csv`，记录 case、文件、问题、需要谁确认；不要让 `package create` 静默猜。

推荐的 L3 预整理产物：

```text
prepared_dataset/
  dataset_description.yaml
  images.csv
  labels.csv
  raw/                 # 原始文件只读保留
  derived/             # 必要的格式转换或重命名结果
  issues.csv           # 无法自动处理的病例
```

`issues.csv` 建议包含：

```csv
case_hint,path,problem,required_action
case_021,labels/case_021.nii.gz,unknown_label_values,confirm label_map
case_105,images/case_105.nii.gz,no_matching_label,decide missing_label or no initial label
case_220,labels/case_220_liver.nii.gz,affine_mismatch,manual geometry review
```

只有 `issues.csv` 中的问题被解决后，相关病例才进入 `case_package_request.v1`。

L4 专用 importer 需要更严格的交付包，不只是一个临时脚本。标准输出、错误代码、`import_summary.json`、`importer_manifest.json` 和验收清单见[专用数据集 Importer 契约](custom_importer_contract.md)。可复制模板位于 `examples/importers/custom_importer_template.py`。

## 5. 命令

```bash
sp ingest plan dataset_description.yaml package_requests/
sp package create-many package_requests/ dataset_package/ --registry registry/
```

输出仍是 `case_package_request.v1`。因此后续病例包创建、几何校验、初始标签拆分、Registry 登记和 Mimics 准备流程都不需要知道原始数据集来自 TotalSegmentator、MSD 还是医院批次。

## 6. 当前边界

- `dataset_description` 只做确定性发现，不做模糊匹配。
- 路径正则必须精确，匹配不到就不会生成请求。
- 标签语义必须来自 `organ` 或 `label_map`，不能从像素值自动推断。
- 所有图像和标签仍要在 `package create` 阶段做几何一致性校验。
- 当前实现不直接读取 DICOM 表格；DICOM 批次优先使用 `sp ingest scan`。
- 专用 importer 不属于平台核心路径；它只能把特殊数据集翻译成标准 request 和报告，不能直接写 Registry 或跳过病例包校验。

## 7. 设计取舍

这比“scan 全自动”复杂一点，但复杂度放在正确的位置：

- `scan`：发现可读图像，适合 DICOM 和简单文件型数据；
- `dataset_description`：表达数据集特有规则；
- `package create`：只消费标准请求，执行校验和登记。

这样可以覆盖常见数据集差异，同时避免每个数据集写一套直接拼病例包 YAML 的脚本。
