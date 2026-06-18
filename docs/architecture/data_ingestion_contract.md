# 数据导入与规范化契约

> 状态：阶段 A 的数据入口设计
> 目的：说明不同目录层级、文件格式和元数据完整度怎样进入统一平台

## 1. 这份契约解决什么问题

平台不能假设所有数据都是“一个患者、一个检查、一个 NIfTI 文件、完整空间信息”。真实来源可能是：

- 一个目录中混有多个患者、检查和 DICOM 序列；
- 一个检查中有平扫、动脉期、静脉期等多个序列；
- 单个 `.nii` 或 `.nii.gz` 文件；
- `.mhd` 头文件和一个或多个 `.raw` 数据文件；
- 只有 `.raw`，尺寸、像素类型和字节序来自额外说明；
- 图像可读取，但患者、检查、模态、spacing、origin 或 direction 不完整；
- 图像和标签已经按数组对齐，但无法证明完整物理坐标。

本契约只定义“怎样如实登记和判断能否使用”，不要求导入时把所有来源强制转换成同一种文件格式。

## 2. 三层必须分开

| 层 | 含义 | 是否允许改变原文件 |
| --- | --- | --- |
| 来源数据 | 收到的原始目录、文件或文件组 | 否 |
| 已登记图像 | 平台能够读取、校验并赋予 `image_id` 的一个三维体素网格 | 否 |
| 派生图像 | 为标注、训练或推理进行格式转换、重定向、裁剪或重采样后的新图像 | 创建新记录，不覆盖上游 |

阶段 A 不新增独立的 `Source Artifact` 实体。来源目录层级、读取器、导入批次和原始相对路径保存在 `Image Artifact.source` 中，减少第一阶段对象数量。

一条必须坚持的规则是：

> 一个独立三维体素网格对应一个 Image Artifact。

因此：

- 一个 DICOM 序列通常对应一个 Image Artifact；
- 同一检查的平扫和动脉期是两个 Image Artifact；
- PET 和 CT 是两个 Image Artifact；
- 一个 4D NIfTI 在进入当前三维分割流程前要拆成多个三维 Image Artifact；
- 不同序列没有默认主次关系，标注任务直接选择目标 `image_id`。

## 3. 来源层级怎样映射

### 3.1 DICOM

导入器先扫描文件，再按 DICOM 元数据形成候选层级：

```text
来源目录
-> Patient/Subject 候选组
-> Study 候选组
-> Series 候选组
-> 实例排序和三维体积检查
-> 每个可用 Series 创建一个 Image Artifact
```

平台不能直接信任目录名，也不能只按文件扩展名分组。导入报告必须保存：

- 实际发现的患者、检查和序列数量；
- 无法读取、重复、缺片、尺寸不一致或排序不确定的文件；
- 每个序列采用的分组键和排序依据；
- DICOM 标识是否已去标识；
- 序列到平台 `case_id`、`study_id` 和 `image_id` 的映射。

如果一个目录中含多个患者或检查，导入器应拆成多个 Case；不能把整个目录默认为一个病例。

### 3.2 NIfTI

每个三维 `.nii` 或 `.nii.gz` 文件通常创建一个 Image Artifact。导入器读取：

- shape 和像素类型；
- qform、sform 和 affine 的可用性；
- spacing、origin、direction 和坐标约定；
- 头信息冲突、退化 affine 或非有限值。

文件名不能自动当作患者身份。患者、检查和序列关系来自数据集清单、路径映射或显式导入参数；无法获得时使用平台生成标识，并如实降低防泄漏分组可信度。

阶段 A 的 `sp ingest scan` 已能发现三维 NIfTI 文件。默认启发式是：同一父目录下的文件归为同一个 Case；根目录下的顶层文件各自成为独立 Case。这个规则只适合基础整理后的文件型数据集，不能替代数据集级清单。若一个目录层级同时混有图像、标签和多时间点，必须改写生成的请求文件，或后续使用显式 `dataset_description.yaml` 导入器。

### 3.3 MetaImage

`.mha` 是单文件，可按文件计算校验值。

`.mhd` 和它引用的 `.raw`、`.zraw` 等数据文件是一个不可拆分的文件组：

- `path` 指向 `.mhd`；
- `companion_paths` 保存被引用的数据文件；
- `hash_scope` 使用 `bundle_manifest`；
- 校验值覆盖头文件、数据文件和稳定的相对路径清单。

只复制 `.mhd` 而漏掉 `.raw` 的记录必须判定为不可读取。

阶段 A 的 `sp ingest scan` 会发现 `.mha/.mhd`。`.mhd` 的伴随数据文件参与文件组 hash；单独出现的 `.raw` 不会被猜测解析，除非未来提供明确 sidecar。

### 3.4 纯 RAW

纯 `.raw` 没有自描述头信息。只有同时提供以下读取参数时才能创建可读取的 Image Artifact：

- 三维尺寸；
- 像素类型；
- 字节序；
- 数据排列顺序；
- 文件偏移量（如果不是 0）。

spacing、origin 和 direction 可以未知，但尺寸、像素类型和字节序不能靠猜测。缺少这些最低解码参数时，数据只能进入隔离区等待补充，不能进入标注或训练。

### 3.5 来源数据自带标签

来源标签也可能是多标签 NIfTI、MHD+RAW、纯 RAW 或逐器官 mask。导入原则与图像一致：

- 每个 Label Artifact 必须绑定一个明确的 `image_id`；
- 同一标签文件不能跨两个未配准的图像序列；
- MHD+RAW 和逐器官 mask 目录按文件组计算摘要；
- 纯 RAW 标签也必须有尺寸、像素类型、字节序和标签值说明；
- 图像与标签只能证明数组同形时，记录 `index_space` 对齐，不能声称物理空间一致；
- 来源标签的器官名称和整数值必须通过显式映射进入平台统一名称。

平台不要求在登记前把所有来源标签先转换成 NIfTI。具体标注或训练工具不支持来源格式时，由适配器创建或导出工具所需表示，并记录真实转换参数。

## 4. 文件和文件组怎样登记

`Image Artifact` 使用下面的最小存储表达：

| 字段 | 含义 |
| --- | --- |
| `format` | `dicom_series`、`nifti`、`metaimage`、`raw_binary` 或 `other` |
| `path` | 主入口；可以是文件，也可以是 DICOM 目录 |
| `companion_paths` | MHD 对应 RAW、sidecar 等伴随文件 |
| `hash` | 文件或稳定文件组清单的 SHA-256 |
| `hash_scope` | `file` 或 `bundle_manifest` |
| `pixel_type` | 实际读取后的像素类型 |
| `source` | 数据集、导入批次、来源层级、读取器和读取参数 |

`bundle_manifest` 的摘要算法在代码实现前必须固定，至少包含：

1. 以 `/` 分隔的相对路径；
2. 每个文件的 SHA-256；
3. 稳定排序；
4. 不包含绝对路径和修改时间。

这样 Windows 标注机和 Linux 训练服务器可以得到相同摘要。

## 5. 空间信息不完整时怎样表达

不得为了通过 Schema 而伪造 spacing、origin 或 direction。平台使用三种 `geometry_status`：

| 状态 | 已知内容 | 含义 |
| --- | --- | --- |
| `complete` | shape、spacing、origin、direction | 可以进行完整物理空间检查 |
| `partial` | shape，加上部分可信空间字段 | 可以读取，但部分物理空间操作受限 |
| `index_only` | shape 和数组顺序可确认 | 只能证明数组索引空间，不能声称物理坐标正确 |

每个空间字段还要记录证据来源：

- `header`：来自 NIfTI 或 MetaImage 头；
- `dicom`：来自 DICOM 序列；
- `sidecar`：来自可信数据集清单；
- `inferred`：由确定性规则推导；
- `assumed`：人为指定的假设值；
- `unknown`：无法获得。

`assumed` 不是错误，但必须进入使用限制和运行记录，不能伪装成原始元数据。

## 6. 信息不完整不等于一律不可用

平台分别判断标注、训练和正式评估能否使用，不能只设置一个笼统的“有效/无效”状态。

| 数据情况 | 标注 | 训练 | 正式评估 |
| --- | --- | --- | --- |
| 完整物理空间 | 允许 | 允许 | 允许 |
| shape 确定，图像和标签数组严格同形，但物理坐标不完整 | 可在索引空间标注，必须提示限制 | 可按任务策略允许并冻结假设 | 默认阻止跨来源空间比较 |
| spacing 缺失，但任务明确接受统一假设 spacing | 使用派生图像 | 使用派生图像并记录 `assumed` | 不能把物理距离指标当作可信结果 |
| origin 或 direction 缺失，图像和标签来自同一数组 | 可进行同数组编辑 | 可用于不依赖真实物理位置的训练 | 物理表面距离指标受限 |
| shape 或像素解码参数未知 | 阻止 | 阻止 | 阻止 |
| 患者关联未知 | 可标注 | 可全部放入训练集 | 不能声称患者级独立评估 |

这些结论写入 `Image Artifact.usability`：

```json
{
  "annotation": "allowed_with_assumptions",
  "training": "allowed_with_assumptions",
  "evaluation": "blocked",
  "reasons": [
    "direction is unavailable; image and label are only verified in index space"
  ]
}
```

具体任务仍可设置更严格规则，但不能放宽底层“无法解码”或“无法证明独立评估”的阻断结论。

## 7. 患者和检查信息缺失时怎样处理

`case_id` 和 `study_id` 是平台标识，不要求直接来自 DICOM。来源没有检查标识时，平台可以生成 `study_id`。

防泄漏信息必须同时记录：

| 字段 | 作用 |
| --- | --- |
| `leakage_group_id` | 当前认为应当一起划分的数据组 |
| `leakage_group_basis` | 分组依据，例如患者伪名、来源 subject、study、case 或未知批次 |
| `leakage_group_confidence` | `high`、`medium` 或 `low` |

建议取值：

- 有稳定患者伪名：`patient_pseudonym` + `high`；
- 数据集提供可靠 subject id：`source_subject` + `medium/high`；
- 只有检查级关系：`study` + `low`；
- 完全无法关联：`import_batch_unknown` + `low`。

低可信度数据仍可标注，也可全部用于训练；但不能与同一来源的其他病例随机拆成正式训练/测试并宣称患者无泄漏。

## 8. 是否统一转换成 NIfTI

阶段 A 采用“保留来源，按需派生”，不采用“导入即全部覆盖成 NIfTI”。

```text
原始 DICOM / NIfTI / MHD+RAW / RAW
-> 读取和登记
-> 判断目标工具是否能直接使用
-> 必要时创建派生 NIfTI
-> 标注、训练或推理使用明确的 image_id
```

格式转换只要产生了新的文件，就创建新的 Image Artifact，并记录：

- `derived_from_image_id`；
- 转换工具和版本；
- 是否只改变容器格式；
- 是否重定向、裁剪或重采样；
- 新文件的实测空间信息和校验值。

只复制头信息、手工改 affine 或假设两个数组对齐，不构成有效空间转换。

## 9. 导入命令的目标边界

阶段 A 的目标接口：

```bash
sp ingest scan /data/source --output reports/source_scan.json
sp ingest build-requests reports/source_scan.json package_requests/ --organs liver spleen --import-batch batch_001
sp package create-many package_requests/ dataset_package/ --registry registry/
sp registry rebuild-index registry/
```

`scan` 只发现和报告，不写正式记录。`build-requests` 根据人工确认或规则化参数生成可审阅的 Case Package 请求；`package create-many` 才创建 Case Package 和 Registry 记录。这样可以避免批量扫描时错误分组直接污染登记册。

当前扫描覆盖 DICOM Series、三维 NIfTI、MetaImage。DICOM 按元数据分组；NIfTI 和 MetaImage 按文件发现，并使用路径启发式生成低可信度防泄漏分组。扫描报告中的 `status=importable` 只说明平台能读取和登记，不等于所有标注工具都能直接打开。以 Mimics 21 为标注工具时，第一次打开仍要求 DICOM 或已准备好的 `.mcs`；NIfTI/MHD 需要先转换成 Mimics 可接受的表示，或改用支持这些格式的标注工具。

导入器至少要产出：

- 导入报告；
- Case 记录；
- Image Artifact 记录；
- 文件或文件组校验值；
- 无法导入项和原因；
- 需要人工确认的分组或元数据假设。

## 10. 阶段 A 必测样例

开始写导入代码前要准备下面的最小样例矩阵：

| 编号 | 样例 | 必须验证 |
| --- | --- | --- |
| I01 | 单患者单序列 DICOM | 正确排序和完整几何 |
| I02 | 单患者多序列 DICOM | 创建多个 Image Artifact，无默认主次 |
| I03 | 同目录多患者或多检查 DICOM | 正确拆分 Case |
| I04 | 正常 NIfTI | 读取 shape、像素类型和 affine |
| I05 | qform/sform 冲突或退化 NIfTI | 进入警告或阻断，不静默修复 |
| I06 | MHD+RAW | 文件组校验和伴随文件完整性 |
| I07 | 纯 RAW+sidecar | 按显式参数解码 |
| I08 | 缺少 spacing/direction 但数组可读 | 创建 `partial` 或 `index_only` 记录 |
| I09 | 图像与标签同形但只有索引空间 | 限制正式评估，保留标注/训练选择 |
| I10 | 无可靠患者关联 | 标记低可信度防泄漏分组 |

没有这些样例，只实现“能读取一个 `.nii.gz`”不能证明数据入口成立。

## 11. 与病例包和训练快照的关系

- 数据导入契约决定来源怎样成为 Case 和 Image Artifact。
- 来源自带标签按相同原则成为 Label Artifact。
- 病例包只接收已经登记、且满足目标标注工具要求的图像和标签。
- 如果原始格式不适合标注工具，病例包引用派生图像，不修改原始记录。
- 病例包 v0.5 当前要求工具可用的 DICOM 或带 spacing 的图像表示；`index_only` 来源必须先创建带显式假设的派生图像，无法建立可控工具空间时则阻止发包。
- 训练数据快照冻结最终使用的 `image_id`、标签版本、几何假设和防泄漏信息。
- nnUNet 工具适配器不负责猜测来源目录结构，只消费已登记并通过准入的图像和标签。若 nnUNet 需要 spacing，而来源只有索引空间，必须先选择或创建记录了假设 spacing 的派生图像。

因此，异构格式的复杂性收敛在导入层，不泄漏到每个标注工具和训练框架中。
