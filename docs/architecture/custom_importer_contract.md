# 专用数据集 Importer 契约

> 状态：阶段 A 的 L4 复杂数据集接入规范  
> 目的：当 `scan` 和 `dataset_description.yaml` 表达不了真实数据集结构时，约束专用 importer 的输入、输出、错误报告和验收方式。

## 1. 什么时候才写专用 importer

不要把专用 importer 当成默认路径。优先级必须是：

1. `sp ingest scan`：标准 DICOM 或简单文件型图像。
2. `sp ingest plan dataset_description.yaml ...`：图像、标签和 label map 可用正则或 CSV 描述。
3. L3 预整理脚本：先把混乱目录整理成 `images.csv`、`labels.csv` 或 `dataset_description.yaml`。
4. L4 专用 importer：只有前面三种表达不了时才写。

典型 L4 场景：

- 一个病例由多个 sidecar 共同决定图像、期相、标签和排除规则；
- 标签文件名混乱，需要读取 README、JSON、CSV 和目录上下文才能确认器官语义；
- 公开数据集打包方式特殊，需要解压、重命名或跨目录关联多个文件；
- 医院批次 CSV 不完整，需要结合 DICOM UID、检查日期、序列描述和人工修订表才能配对；
- 同一标签文件中存在多个 label value，但 label map 按批次或子目录变化。

L4 importer 的职责是把数据集特有知识翻译成平台已知输入。它不能绕过病例包、Registry、几何校验或标签生命周期。

## 2. 标准输出目录

每个专用 importer 应输出一个可审计目录：

```text
import_runs/{dataset_id}_{run_id}/
  requests/
    case_001.yaml
    case_002.yaml
  reports/
    import_summary.json
    import_issues.csv
    importer_manifest.json
  derived/                 # 可选：去标识、重命名、解压或格式转换结果
  logs/                    # 可选：外部工具日志
```

必需规则：

- `requests/` 中只放 `case_package_request.v1`。
- `reports/import_summary.json` 是机器可读总览。
- `reports/import_issues.csv` 记录所有未进入 request 或需要人工确认的问题。
- `reports/importer_manifest.json` 记录 importer 版本、输入根目录、配置、运行参数和代码版本。
- `derived/` 中的文件必须可由原始数据和 manifest 重新生成；不要把它当成唯一真相来源。

## 3. Importer Manifest

`importer_manifest.json` 建议字段：

```json
{
  "schema_version": "custom_importer_manifest.v1",
  "dataset_id": "hospital_ct_2026q2",
  "run_id": "20260622_001",
  "created_at": "2026-06-22T10:00:00Z",
  "importer_name": "hospital_ct_importer",
  "importer_version": "0.1.0",
  "code_revision": "git:abcdef0",
  "source_root": "/data/raw/hospital_ct",
  "output_root": "/data/import_runs/hospital_ct_2026q2_20260622_001",
  "config_path": "/data/importer_configs/hospital_ct.yaml",
  "request_schema_version": "case_package_request.v1",
  "platform_commit": "git:abcdef0",
  "notes": "Combines DICOM UID table and manually curated phase map."
}
```

`code_revision` 和 `platform_commit` 不要求阶段 A 自动填充，但手工填也比缺失好。目标是未来能回答“这批 request 是由哪个脚本、哪份配置、哪份原始数据生成的”。

## 4. 错误报告规范

`import_issues.csv` 必须使用稳定列名，方便人工筛选和后续自动统计：

```csv
severity,code,case_hint,image_hint,label_hint,path,message,required_action,disposition,evidence
error,missing_label_map,case_021,img_ct,label_021,labels/case_021.nii.gz,"label values [3,4] are undocumented","confirm value to organ mapping",quarantined,README has no entry
warning,no_initial_label,case_105,img_ct,,images/case_105.nii.gz,"no matching label found","create review without initial label",request_without_label,matched by image table
error,geometry_mismatch,case_220,img_ct,liver,labels/case_220_liver.nii.gz,"affine differs from image by 12 mm","manual geometry review",quarantined,nibabel affine check
```

字段含义：

| 字段 | 含义 |
| --- | --- |
| `severity` | `error`、`warning` 或 `info` |
| `code` | 稳定问题代码，不写自由文本 |
| `case_hint` | 原始数据中的病例线索，可为空 |
| `image_hint` | 相关 image 或序列线索，可为空 |
| `label_hint` | 相关 label 或器官线索，可为空 |
| `path` | 相对 `source_root` 或 `derived/` 的路径 |
| `message` | 给人看的具体说明 |
| `required_action` | 谁需要做什么确认或修复 |
| `disposition` | `quarantined`、`request_without_label`、`request_created`、`ignored` |
| `evidence` | 支撑判断的来源，例如 CSV 行号、UID、README 条目、几何检查 |

建议的 `code`：

| code | 典型含义 | 默认处理 |
| --- | --- | --- |
| `unreadable_file` | 文件损坏或格式无法读取 | `quarantined` |
| `unsupported_format` | 格式暂不支持且无法安全转换 | `quarantined` |
| `ambiguous_case_group` | 无法确定属于哪个病例或检查 | `quarantined` |
| `ambiguous_image_role` | 无法确定哪个图像应进入标注 | `quarantined` |
| `missing_pairing_key` | 图像和标签缺少配对依据 | `quarantined` |
| `duplicate_pairing_key` | 多个图像或标签匹配同一 key | `quarantined` |
| `missing_label_map` | 多标签值没有权威器官映射 | `quarantined` |
| `unknown_organ_name` | 器官名无法归一到 Anatomy Vocabulary | `quarantined` |
| `geometry_mismatch` | header、affine、spacing、origin 或 direction 不一致 | `quarantined` |
| `shape_only_match` | 只能证明 shape 相同，不能证明空间一致 | `quarantined` |
| `no_initial_label` | 图像可进入标注，但没有初始标签 | `request_without_label` |
| `deidentification_uncertain` | 脱敏状态无法由现有证据证明 | `quarantined` 或降级治理状态 |

原则：凡是影响配对、器官语义、空间一致性和脱敏状态的问题，默认不进入 request。只有“无初始标签但仍可人工标注”这类问题，才允许 `request_without_label`。

## 5. Summary JSON

`import_summary.json` 用于批量验收和快速判断是否能进入 `package create-many`：

```json
{
  "schema_version": "custom_importer_summary.v1",
  "dataset_id": "hospital_ct_2026q2",
  "run_id": "20260622_001",
  "created_at": "2026-06-22T10:05:00Z",
  "status": "passed_with_warnings",
  "request_count": 128,
  "case_count": 128,
  "image_set_count": 143,
  "initial_label_count": 97,
  "issue_counts": {
    "error": 0,
    "warning": 31,
    "info": 0
  },
  "requests_dir": "requests",
  "issues_csv": "reports/import_issues.csv",
  "manifest": "reports/importer_manifest.json",
  "next_command": "sp package create-many requests dataset_package --registry registry --continue-on-error"
}
```

`status` 取值：

- `passed`：无 error 和 warning。
- `passed_with_warnings`：无 error，但有不阻断的问题，例如无初始标签。
- `blocked`：存在 error；不能整体进入 `package create-many`。

如果存在 `error`，importer 仍可输出已确定的 request，但必须把不确定病例留在 issues 中。不要为了“跑完”而创建猜测性 request。

## 6. Request 生成要求

专用 importer 输出的 request 必须满足：

- `schema_version: case_package_request.v1`。
- `case_id`、`study_id`、`image_id`、`target_id` 稳定、可重复生成。
- `leakage_group_id` 按患者或最保守可证明主体生成，不能按文件名随意分组。
- `image_sets[].source` 指向原始或可重建派生文件。
- `image_sets[].source_layout` 写清匹配依据，例如 CSV 行号、UID、正则命名组或 sidecar key。
- `initial_labels[]` 只登记有明确器官语义和空间证据的标签。
- 多标签文件必须使用 `label_map`，逐器官文件必须使用 `organ`。
- `lifecycle_status` 不得把伪标签伪装成 `source_label`；算法输出应保留 `candidate_label` 或对应来源字段。
- 无法确认的病例不写入 request，进入 `import_issues.csv`。

## 7. 验收清单

专用 importer 完成后，至少检查：

| 检查项 | 通过标准 |
| --- | --- |
| 可重复性 | 同一输入和配置重复运行，request 文件名、ID、数量和 hash 稳定 |
| 问题清单 | `import_issues.csv` 存在；所有 error 都有 `required_action` 和 `disposition` |
| Summary | `import_summary.json` 存在；`status`、数量统计和 issue_counts 与输出一致 |
| Manifest | `importer_manifest.json` 记录 importer、配置、输入根和输出根 |
| 词表校验 | 所有 `organ` 和 `label_map` key 能通过 Anatomy Vocabulary |
| 配对证据 | 每个初始标签能追溯到明确 image-label 配对依据 |
| 空间证据 | 不接受仅 shape 相同；必须有 header/affine/DICOM 几何证据，最终仍由 `package create` 校验 |
| 治理信息 | `source_type`、`import_batch`、`data_governance` 不为空且符合该批数据事实 |
| 病例包创建 | `sp package create-many requests ... --continue-on-error` 能创建确定病例；失败项不能被忽略 |
| 抽样人工复核 | 至少抽查若干病例的图像、标签、器官映射和目标器官范围 |

推荐验收命令：

```bash
python examples/importers/custom_importer_template.py SOURCE_ROOT import_runs/run_001 --dry-run

sp package create-many import_runs/run_001/requests dataset_package \
  --registry registry \
  --continue-on-error

find dataset_package -name manifest.json -maxdepth 3 -print
```

实际 importer 应替换模板脚本。模板只定义输出形态和报告规范。

## 8. 失败时怎么处理

- `blocked`：先解决 `severity=error` 的问题，不进入病例包。
- `passed_with_warnings`：可以进入病例包，但 warning 必须可解释，例如“没有初始标签，后续人工标注”。
- 单病例失败：保留该病例在 `import_issues.csv`，其余确定病例继续进入 request。
- CSV 不完整：优先补 CSV 或人工修订表，不要在 importer 里写隐式猜测规则。
- 器官语义不明：不要导入标签；可创建无初始标签的人工标注任务。
- 空间关系不明：不要导入标签；必要时只导入图像，标签隔离待复核。

## 9. 不允许的做法

- 在 importer 中直接写 Registry。
- 在 importer 中直接创建 Label Artifact。
- 只因为文件名包含器官词就自动当成可靠标签，除非数据集说明确认命名约定。
- 只因为 shape 相同就认为图像和标签对齐。
- 把无法确认的伪标签写成 `source_label`。
- 为了减少 issues 数量而静默丢弃异常文件。
- 让后续 Mimics、training 或 snapshot 代码理解某个数据集的特殊目录结构。
