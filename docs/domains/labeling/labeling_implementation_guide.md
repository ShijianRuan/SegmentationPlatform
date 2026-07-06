# 训练前标注闭环实现与运行指南

> 版本：v0.1  
> 日期：2026-06-15  
> 适用范围：离线阶段 A，结束于不可变 Dataset Snapshot，不包含 nnUNet 导出和训练  
> Mimics：以 Mimics Research 21.0 API 为实现依据，真实工作站 Gate A/B/C 仍需执行

## 1. 已经实现到哪里

当前代码已经可以在外部现代 Python 环境中完成：

1. 扫描来源目录，发现 DICOM Series、三维 NIfTI 和可选 MetaImage，并生成可审阅的导入清单。
2. 检查 DICOM、NIfTI 和可选 MetaImage 图像的格式、哈希与三维空间。
3. 从扫描清单批量生成病例包请求，或从单个请求文件创建 Case Package v0.5。
4. 批量创建病例包，避免逐病例手工运行 `package create`。
5. 把 Case、Image Artifact、初始 Label Artifact 和 Review Task 写入文件式 Registry。
6. 把已有逐器官或多标签文件拆成逐器官 NIfTI。
7. 为 Mimics 21 生成运行清单和逐器官 `.u8` 体素缓冲区。
8. 启动 Mimics，并在 Mimics 内创建、绑定、恢复和导出受平台管理的 Mask。
9. 区分保存进度、提交完成、提交复查和报告阻塞。
10. 在外部环境回收 Mask，执行身份、基础版本、哈希、shape、轴映射、空 Mask 和空间检查。
11. 追加创建 `verified_label` 或 `draft_label`，不覆盖旧版本。
12. 从 Registry 选择明确标签版本，检查患者级 split 泄漏，创建不可变 Dataset Snapshot。
13. 为文件式 Registry 维护标签查询索引，避免快照创建时反复全量扫描标签目录。

没有宣称已经完成的部分：

- 当前机器不是 Mimics 21 Windows 工作站，因此 P01-P14 尚未产生真实证据。
- `buffer_mapping.status=verified` 必须来自 P05 实测，不能照抄示例值。
- 未校准时可以创建空 Mask 从零标注，但不能导入已有 Mask，也不能把导出缓冲区转换为正式标签。
- RAW 图像没有可靠 sidecar 时仍然阻断；MetaImage 需要安装可选依赖，`.mhd` 按头文件和伴随数据文件形成文件组校验。
- 本阶段没有 Web UI、在线锁、权限系统或多人实时协同。批量入口是命令行扫描、请求生成和批量创建，不是在线任务队列。
- 阶段 A 仍采用“一个 `.mcs` 一个 review/case 工作空间”。多病例塞进同一 `.mcs` 暂不作为默认路径。

## 2. 端到端流程走查

下面沿完整的标注链路走一遍，每一步说明做什么、产出什么、怎么验证。涉及三个角色：平台操作者（运行命令）、标注者（只在 Mimics 内操作）、平台脚本（自动执行）。

### 阶段 1：平台准备环境验收

**谁做**：平台操作者，在标准 Mimics 21 构建上执行。标注者机器不安装平台 Python，也不创建本机配置。

**目标**：确认这台机器能可靠地导入平台 DICOM、操作 Mask 并原样导出。

**步骤**：

1. 安装 Mimics Research 21.0，确认许可含 Scripting 模块。在 `File → Preferences → Scripting` 中配置 Python 3.5.2。
2. 在平台准备机上把 `adapters/mimics/scripting_library/` 设为 Scripting Library；`runtime_py35/` 是内部实现目录。
3. 创建 `config/mimics_workstation.yaml`，记录 Mimics 路径和工作目录。
4. 运行环境诊断：
   ```powershell
   sp mimics doctor --config C:\SegmentationPlatform\config\mimics_workstation.yaml
   ```
   **产出**：`mimics_doctor_report.json` — 确认 Python 版本、Mimics 版本、关键 API 是否存在。
5. 运行能力探针：
   ```powershell
   sp mimics probe-run D:\cases\pkg_probe --config C:\SegmentationPlatform\config\mimics_workstation.local.yaml
   ```
   **产出**：P01–P06 证据 JSON — 证明 DICOM 导入、Mask 创建/绑定、buffer 导出和空间往返全部可执行。
6. 验证几何映射：
   ```powershell
   sp mimics probe-evaluate D:\cases\pkg_probe D:\cases\pkg_probe\reports\mimics_probe\mimics_probe_evidence.json --config ... --output-config mimics_workstation.verified.yaml
   ```
   **产出**：`mimics_workstation.verified.yaml`，其中 `buffer_mapping.status=verified`。轴排列和翻转值来自体模实际测量，不是手工猜测。

**验证方式**：检查 `buffer_mapping.status` 是否为 `verified`；不是 verified 时不允许注入初始标签和回收提交。平台应把同一 Mimics 版本、构建和已验证导入路径视为一个兼容性 profile，按 profile 准备工作包。标注者不填写 profile，但工作包会在打开时检查 Mimics 版本。

---

### 阶段 2A：登记图像资产

**谁做**：平台操作者或后台脚本；可在确定标注任务之前执行。

**目标**：把可读取的 Case 和 Image Artifact 先写入 Registry，但不创建病例包、不创建 Review Task。

```bash
sp ingest scan /data/source --output /data/reports/source_scan.json

sp ingest register /data/reports/source_scan.json \
  --registry /data/platform_registry \
  --import-batch batch_20260616 \
  --source-type hospital_inventory \
  --source-name hospital_ct_batch_001
```

这条路径适合“先盘点和登记图像，稍后再决定标注哪些器官”。登记后的 Image Artifact 指向原始数据路径并冻结 hash、来源布局和空间信息；它不复制图像，也不保证 Mimics 能直接打开。来源根目录必须稳定、只读、可被后续平台步骤访问。

**验证方式**：

- Registry 中出现 `cases/{case_id}.json` 和 `images/{image_id}.json`
- Registry 中没有新增 `reviews/`
- `Image Artifact.source.import_batch` 与本次批次一致
- `Image Artifact.usability` 能被后续 Snapshot 检查使用

### 阶段 2B：创建标注病例包

**谁做**：平台操作者，每批标注任务执行一次。

**目标**：把原始数据整理成标注者可以直接使用的离线工作目录，并创建 Review Task。若图像已通过阶段 2A 登记，病例包仍负责复制/派生标注工具所需文件和生成任务现场。

推荐批量入口：

```bash
sp ingest plan /data/source /data/package_requests \
  --organs-file /data/config/whole_body_organs.txt \
  --import-batch batch_20260616 \
  --workers 8

sp package create-many /data/package_requests /data/dataset_package \
  --registry /data/platform_registry \
  --continue-on-error \
  --copy-mode hardlink
```

`sp ingest plan` 是推荐统一入口。输入是目录时，它会先生成 `source_scan.json` 再生成可审阅 request；输入是已有 scan JSON 时，只生成 request；输入是 `dataset_description.v1` 时，走描述文件路径。中间的请求文件允许人工批量检查和修改，比如只保留静脉期、补充初始标签或调整目标器官。扫描报告不保存原始 PatientID，只保存哈希、相对路径和导入可用性。

`--organs` 不是实施者必须手写上百个参数。大任务使用 `--organs-file`，支持 YAML/JSON 的 `organs` 数组或一行一个器官的 TXT。`assignee` 不建议在建包阶段定死；可先留空，分发时仅作为中央筛选或记录提示。

注意：`package create-many --registry` 仍会登记 Case 和 Image Artifact，这是为了兼容“一步创建标注工作包”的路径。但从架构上，Registry 中的图像资产不应依赖病例包存在；只想登记图像时使用阶段 2A。

复杂外部数据集不要强行依赖 `scan`。若标签和图像混放、标签目录独立、一个文件含多个标签值，或配对关系来自 CSV，使用数据集描述入口：

```bash
sp ingest plan /data/dataset_description.yaml /data/package_requests

sp package create-many /data/package_requests /data/dataset_package \
  --registry /data/platform_registry \
  --continue-on-error
```

`dataset_description.yaml` 负责显式写清图像 pattern、标签 pattern、CSV 配对、`organ` 或 `label_map`。这样 TotalSegmentator、MSD Liver 和医院 CSV 批次都能先收敛成同一种 `case_package_request.v1`，再进入病例包创建。

如果正则和 CSV 仍表达不了，不要继续扩大 `scan`。按[数据集描述契约](../../architecture/dataset_description_contract.md)的 L0-L5 分级处理：先尝试预整理成 `images.csv/labels.csv`，仍不行再按[专用数据集 Importer 契约](../../architecture/custom_importer_contract.md)写 L4 importer，输出标准 request、`import_summary.json`、`import_issues.csv` 和 `importer_manifest.json`；无法确认配对、器官语义或空间关系的病例进入 issues，不进入病例包。

`scan` 的边界要分清：

- DICOM：按 Study/Series 元数据分组，一个 Series 生成一个 `image_set`。
- NIfTI/MHD/MHA：按文件发现，同一父目录默认归为一个 Case；顶层文件各自成为独立 Case。
- RAW：没有明确 sidecar 时只报告为不可直接导入。
- 复杂数据集：不要让 scan 猜标签语义；使用 `sp ingest plan dataset_description.yaml ...` 将“哪些文件是标签、标签值对应哪个器官、哪些序列应进入标注”显式写进数据集描述。

病例包可以登记 NIfTI/MHD。若标注工具选择 Mimics，非 DICOM 图像需要在外部 Python 中读取，并派生成 Mimics 已支持的导入表示。首选去标识 DICOM Series；BMP/TIFF 切片导入可作为降级路径；RAW 只能作为单独 POC 路径，因为 API 文档有 `force_raw_import` 入口但没有完整 RAW header 参数契约。任何非 DICOM 路径都必须用 P03 验证维度、灰度、spacing 和方向。不要依赖 Mimics Python 3.5 直接把 NIfTI/MHD 数组写成 `ImageData`。

单例调试入口仍然可用：

```bash
sp package create examples/labeling/case_package_request.yaml /data/dataset_package --registry /data/platform_registry
```

**病例包创建做的事**：

- 从来源区读取图像 → DICOM 按患者/检查/序列分组，文件型图像按路径启发式分组 → 为每个三维体素网格创建 `image_id`
- 复制、硬链接或符号链接图像到 `images/{image_id}/`，记录去标识检查结果和文件哈希
- 如有初始候选标签，拆为逐器官 NIfTI 放入 `labels/{image_id}/masks/`
- 生成 `manifest.json`（image_sets、器官列表、标注目标组、base label 版本）
- 在 Registry 中创建或补充 Case、Image Artifact、Label Artifact、Review Task 记录

**产出物目录**：

```text
/data/dataset_package/
  config/
    anatomy_vocabulary.yaml          # 器官名称统一词表
    review_label_map.yaml            # 标注工具中的标签编号
  cases/case_001/
    manifest.json                     # ← 核心：这份病例要标什么
    images/
      img_noncontrast/image.nii.gz    # 一个序列 = 一个 image_id
      img_arterial/image.nii.gz
    labels/
      img_noncontrast/masks/          # 逐器官初始标签（可选）
    working/                          # 空，标注过程中产生
    submissions/                      # 空，提交时产生
    reports/                          # 空，问题报告
```

**验证方式**：

```bash
sp package validate /data/dataset_package/cases/case_001
```

检查项：DICOM 序列是否单一、初始 Mask 与图像 affine 是否一致、器官名是否在词表中、文件复制后哈希是否变化、去标识检查是否有风险记录；只有显式开启 `strict_deidentification` 时，去标识风险才阻断建包。

---

### 阶段 3：为 Mimics 准备任务队列

**谁做**：平台操作者或后台脚本。

**目标**：把病例包预生成为可移动、无需 Registry 的 Mimics 工作包。这个阶段不要求标注者参与。

```bash
sp mimics prepare-many /data/dataset_package/cases \
  --config mimics_workstation.verified.yaml \
  --continue-on-error

# 可选加速：在兼容的 Mimics 准备机预生成 .mcs
sp mimics prebuild-many /data/dataset_package/cases \
  --config mimics_workstation.verified.yaml \
  --continue-on-error

sp review export-worklist \
  --registry /data/platform_registry \
  --output-root /transfer/batch_001 \
  --limit 30
```

平台必须在导出工作包前完成 `prepare`。`prebuild` 是可选加速，不是正确性前提：若工作包没有 `.mcs`，首次打开时由 Mimics 内脚本直接导入工作包中的 DICOM、创建 Mask、注入已准备好的 buffer 并保存 `.mcs`。所有 `Labeling_*.py` 都不运行外部平台命令。

**平台提前做的事**：

- 批量创建病例包和 Registry 记录；
- 可选地按中央 `assignee` 筛选 review，但不把身份配置带到标注机；
- 批量运行 `sp mimics prepare-many`；
- 可选运行 `sp mimics prebuild-many`，减少标注者首次打开等待；
- 用 `sp review export-worklist` 生成包含脚本、相对路径清单和病例的可移动工作包；有 `.mcs` 时一并携带。

**`prepare` 后台做的事**：

- 再次校验病例包；
- 如果 P05 已通过 → 把逐器官 NIfTI 标签转为 `.u8` 缓冲区，写入 `working/bridge/import/{image_id}/{organ}.u8`
- 生成 `working/mimics_runtime.json` — 这是 Mimics 内部脚本的任务说明书：
  ```text
  review_id: review_case001_001
  dicom_import_root: /data/...
  image_sets:
    - image_id: img_noncontrast
      dicom_uid_hash: ...
      platform_shape: [512, 512, 200]
    - image_id: img_arterial
      ...
  targets:
    - target_id: target_abdomen
      image_id: img_noncontrast
      masks:
        - organ: liver
        - organ: kidney_left
      base_label_id: label_xxx
      base_label_sha256: ...
  mcs_path: working/review_case001_001.mcs
  reports_dir: reports/
  submissions_dir: submissions/review_case001_001/
  ```

**Mimics 直接入口打开任务时做的事**：

- 在 Mimics 内调用 `sp_review_console.py`；
- 读取工作包中的 `worklist_manifest.json` 和自动生成的 `worklist_progress.json`；
- 按顺序打开下一例、继续上次或由标注者选择任意病例；
- 按工作包当前路径重绑定 runtime 和 Mask metadata；
- 在当前 Mimics 会话里调用 `sp_open_review.py`；
- 有预生成 `.mcs` 时直接打开；没有时在 Mimics 内完成首次 DICOM 导入、Mask 创建和初始 buffer 注入；
- 核对工作包要求的 Mimics 版本，校验 image set 和受管 Mask，并更新移动后的 `package_root`。

`worklist_progress.json` 不是本机配置，也不包含 Python、Mimics、Registry 或固定盘符路径。它只是由 Console 自动维护的“上次打开哪例、哪些例已提交或暂时跳过”记录；删除后可由工作包内容重建。

已提交病例通过 Choose Case 重新打开后，本地状态立即回到 `in_progress`。旧的 `submission_manifest.json` 仍作为上一版提交记录保留；Console 通过 `submission_id` 判断磁盘上的提交是否仍是同一版，不会在刷新清单时把正在修订的病例错误覆盖回 `submitted`。再次提交后才生成新的 `submission_id/submitted_at` 并恢复提交状态。

**为什么取消本机 Console 配置**：

旧方案让标注机保存 `platform_python`、`registry_root`、`workstation_config` 和 `assignee`，再由 Console 查询中央任务并调用平台命令。这把控制面、机器路径和标注操作耦合在一起：每台机器都要配置，换盘符会失效，离线分发困难，标注者还可能被平台环境错误阻塞。

当前边界改为：

- 中央平台决定准备哪些病例，并生成不可变的工作包清单；
- 导出前强制核对中央 Review、病例包 `manifest.json` 和 `mimics_runtime.json` 的 `review_id/package_id/case_id`，任一不一致都阻断分发；
- 工作包复制到哪里都可以，Console 只解析相对路径；
- 标注者在包内自由选择、继续、跳过和重新提交；
- 中央平台只回收实际提交的结果，不读取标注机本地进度；
- 严格身份审计是可选模式，若 Review 显式设置 `enforce_assignee=true`，身份由平台在导出工作包时冻结，不由标注者配置。

**验证方式**：

- `prepare` 后检查 `working/mimics_runtime.json` 和 `working/bridge/import/` 是否有内容
- 可选的 `sp mimics prebuild-workspace CASE --config CONFIG --dry-run` 应生成包含 `-background_mode` 和 `--background-prebuild` 的命令；Windows 实机运行成功后应生成 `working/prebuilt_workspace.json`
- `Labeling_Open_Next_Case.py` 或其他打开入口成功后，Mimics 显示一次任务摘要
- 标注机只更新 `worklist_progress.json`，不连接或修改中央 Registry
- 报告写入 `reports/mimics_open_report.json`

---

### 阶段 4：标注者工作

**谁做**：标注者。只在 Mimics 里操作，不碰命令行。

**标注者看到的流程**：

1. 打开 Mimics。
2. 建议把工作包根目录设为 Scripting Library；也可从 `Script → Run Script` 直接选择入口。
3. 默认运行 `Labeling_Open_Next_Case.py`；需要继续、选择或跳过时运行 `Labeling_Case_Navigation.py`。
4. 首次打开时核对病例、序列数量和目标器官统计；如不一致，运行 `Labeling_Submit_or_Report_Issue.py` 并选择 Report Problem。
5. 如一致 → 使用 Mimics 正常工具编辑每个 Mask。每个 Mask 的名称、metadata 由平台管理，标注者不改。
6. 随时 Ctrl+S 保存 `.mcs`。保存只保留进度，不触发提交。
7. 长时间工作、完成一大段器官或准备离开工作站前，可运行 `Labeling_Save_Recovery_Backup.py`。
8. 关闭软件后，下次在 `Labeling_Case_Navigation.py` 中选择 Continue Last Case。

工作包只暴露 6 个入口：

| 入口 | 行为 |
| --- | --- |
| `Labeling_Open_Next_Case.py` | 高频默认动作，直接打开下一例 |
| `Labeling_Case_Navigation.py` | 低频导航：继续、选择或跳过 |
| `Labeling_Submit_Complete.py` | 高频默认提交，直接按完成处理 |
| `Labeling_Submit_or_Report_Issue.py` | 异常结果：Needs Review 或 Report Problem |
| `Labeling_View_Task_List.py` | 直接查看任务清单 |
| `Labeling_Save_Recovery_Backup.py` | 直接保存灾备快照 |

这不是六套业务逻辑。入口只传递动作，实际状态、打开、提交和校验仍由共享控制器实现。这样避免一个万能菜单，也避免把每个细小分支都拆成独立脚本。

任务器官很多时，运行 `Labeling_View_Task_List.py`。清单在 Mimics 弹窗内分页显示，并可按 Missing、Ready、With Initial、Known Absent 筛选。

**标注者不需要知道的事**：标签生命周期、文件哈希、NIfTI 格式、训练编号、Registry 路径。

---

### 阶段 5：提交

**谁做**：标注者触发，Mimics 内部脚本执行导出。

**标注者的操作**：

1. 已完成时运行 `Labeling_Submit_Complete.py`
2. 医学判断不确定或遇到数据/工具问题时运行 `Labeling_Submit_or_Report_Issue.py`
4. 如果有多个目标组，选择要提交的目标组 — 一个、多个或全部
5. 如有空 Mask，确认其语义
6. 等待脚本提示 "已导出，仍需平台检查"

单目标组、无空 Mask 的常见完成路径是直接运行 `Labeling_Submit_Complete.py`。不会先显示功能总菜单或提交类型菜单。

当前病例暂时不处理时，在 `Labeling_Case_Navigation.py` 中选择 Skip Case，而不是 Report Problem。

**脚本在后台做的事**（`sp_submit_review.py`）：

- **提交完成**：检查所有 Mask 存在且绑定正确 → 空 Mask 确认语义 → `get_voxel_buffer()` 导出每个 Mask 为 `.u8` 到 staging 目录 → 生成 `export_manifest.json` 和带 `submission_id/submitted_at` 的 `submission_manifest.json`（action=submit_complete）→ 一次性发布到 `submissions/{review_id}/` → 保存 `.mcs` → 弹窗提示
- **提交复查**：同提交完成，action=submit_for_review，记录不确定原因
- **报告阻塞**：不要求所有 Mask 完成，写入阻塞类型和原因

提交过程中 Mimics 崩溃时，半成品留在 `.partial_*` staging 目录，下一次提交会自动清理。`finalize` 只处理正式 `submissions/{review_id}/`，不会误收半截 buffer。

**验证方式**：检查 `submissions/{review_id}/` 下是否出现了 `submission_manifest.json`、`export_manifest.json` 和 `buffers/` 中的 `.u8` 文件，且不存在需要人工处理的 `.partial_*` 目录。

---

### 阶段 6：平台收尾

**谁做**：平台后台脚本或管理员批处理，不由标注者执行。

```bash
sp mimics finalize /data/dataset_package/cases/case_001 --config mimics_workstation.yaml --registry /data/platform_registry
```

批量收尾使用：

```bash
sp mimics finalize-many /data/dataset_package/cases \
  --config mimics_workstation.verified.yaml \
  --registry /data/platform_registry \
  --continue-on-error
```

**`finalize` 做的事**（这是最关键的 QC 闸门，全部检查通过才写 Registry）：

1. **身份检查**：review_id、target_id 是否匹配；只有 Review 显式设置 `enforce_assignee=true` 时才检查 assignee
2. **完整性检查**：每个 target 要求的所有器官是否都有导出（或已声明 confirmed_absent）
3. **基础版本检查**：提交的 base_label_id 和 base_label_hash 与病例包初始标签是否一致
4. **哈希检查**：导出 buffer 的 SHA-256 与 export_manifest 记录是否一致
5. **几何检查**：通过 P05 验证的轴映射反转后，shape/spacing/origin/direction 是否与目标 Image Artifact 完全匹配
6. **空 Mask 检查**：声明 confirmed_absent 的 Mask 是否确实为空；complete 提交不能有 uncertain

**结果**：

| 提交动作 | 检查通过 | 检查失败 |
| --- | --- | --- |
| submit_complete | 创建新的 `verified_label`（追加版本），目标组标记 completed | 不创建标签，目标组回到 in_progress，生成 `reports/review_report.json` |
| submit_for_review | 创建新的 `draft_label`，目标组标记 needs_review | 同上 |
| report_blocked | 不创建标签，目标组标记 blocked | — |

如果提交基于旧 `base_label_id`，`submit_complete` 会把 base 中未重标的器官 carry-forward 到新 Label Artifact，并把旧 base 标记为 `superseded`。因此“补标 kidney”不会丢掉已完成的 liver/spleen；Snapshot 默认只看到新的 active 标签。`submit_for_review` 产生 draft，不会 supersede 旧 verified 标签。

`sp_review_console.py` 不执行 finalize。提交只写回工作包，平台回收后统一或分批运行 QC，标注者不等待平台处理。

多标注者不要求统一等所有人完成后一次性处理。每个标注者或每批返回的病例都可以独立运行 `collect-submissions` 和 `finalize-many`，通过的标签会追加到中央 Registry；未返回或 QC 失败的病例留在原状态，不影响其他病例。

无共享盘时，中央机和工作站之间使用离线工作包：

```bash
# 中央机导出任意可移动工作包；--assignee 仅是可选筛选
sp review export-worklist \
  --registry /data/platform_registry \
  --output-root /transfer/batch_001_worklist \
  --limit 30 \
  --overwrite

# 标注者完成后，返回目录可以位于任意盘符；平台只从其内容收回 submissions
sp mimics collect-submissions \
  /transfer/returned_batch_001/cases \
  /data/dataset_package/cases \
  --registry /data/platform_registry \
  --overwrite

# 中央机再批量 finalize
sp mimics finalize-many /data/dataset_package/cases \
  --config mimics_workstation.verified.yaml \
  --registry /data/platform_registry \
  --continue-on-error
```

平台不要求知道工作包被复制到标注机后的绝对路径，也不让标注机直接连接 Registry。若使用共享盘，也应共享导出的工作包，而不是把中央 Registry 暴露给标注者。

每次导出后，中央 Review 只追加一条 `worklist_exports` 记录，用于防止下一次批量导出重复选中同一 review；它不追踪标注者本地进度。默认重复导出会被跳过。工作包确实丢失时可用 `--include-distributed` 重发；需要双人独立标注时应创建两个独立 review，而不是让两个人写同一个 review 的副本。

数据集标注中继续增加病例时，不远程修改已经发出的目录。中央机创建新增病例包后，导出新的增量工作包：

```bash
sp review export-worklist \
  --registry /data/platform_registry \
  --output-root /transfer/batch_002_increment \
  --limit 20
```

标注者分别从两个工作包运行各自的 `Labeling_*.py`。`--merge` 只用于平台仍持有同一 staging 工作包时补充内容，不能远程更新已经复制走的标注机目录。

**验证方式**：

- Registry 中出现新的 Label Artifact（source=manual，lifecycle_status=verified）
- `reports/review_report.json` 记录完整 QC 结果
- 病例包中 Review Task 状态更新

---

### 完整链路速览

```text
[一次性] 工作站配置
  doctor → probe-run → probe-evaluate → verified 配置
         │
[每批] 平台操作者
  sp package create → manifest.json + Registry 记录
  sp package validate → 确认数据完整
         │
[每任务] 平台操作者
  分配 review_id + 可选提前 prepare/prebuild .mcs
         │
[标注者] 打开 Mimics → Labeling_Open_Next_Case.py
         │
[标注者] 编辑 Mask → 随时保存 .mcs → 可选 Labeling_Save_Recovery_Backup.py
         │
[标注者] 运行对应 Submit/Report 脚本 → 导出 .u8 或记录阻塞原因
         │
[平台后台]
  sp mimics finalize 或 watcher → 身份/完整/哈希/几何 QC
                    → 通过：verified_label
                    → 失败：review_report.json + 回到 in_progress
```

---

## 3. 代码位置

| 位置 | 作用 |
| --- | --- |
| `src/segplatform/cli.py` | `sp` 命令入口 |
| `src/segplatform/ingest.py` | DICOM 发现扫描和批量病例包请求生成 |
| `src/segplatform/imaging.py` | DICOM/NIfTI/MetaImage 几何、Mask 读写和轴映射 |
| `src/segplatform/case_packages.py` | 病例包创建、初始标签拆分和登记 |
| `src/segplatform/registry.py` | 文件式 Registry 的不可变写入和查询 |
| `src/segplatform/snapshots.py` | 标签准入、split 检查和 Snapshot 冻结 |
| `src/segplatform/adapters/mimics/` | Mimics 外部现代 Python 侧 |
| `adapters/mimics/scripting_library/` | Mimics 菜单中唯一给标注者使用的 Console 入口 |
| `adapters/mimics/runtime_py35/` | Mimics 内 Python 3.5.2 的内部打开、checkpoint 和提交脚本 |
| `adapters/mimics/probes/` | P01/P02/P04/P05/P06 工作站探针 |
| `registry/schemas/` | Image、Label、Review、Snapshot 等 JSON Schema |
| `examples/labeling/` | 病例包和 Snapshot 请求示例 |
| `tests/test_labeling_workflow.py` | 合成 DICOM 到 Snapshot 的端到端测试 |

## 4. 安装外部运行环境

在平台操作者使用的现代 Python 环境中执行：

```bash
python -m venv .venv
.venv/bin/python -m pip install -e '.[dev]'
```

Windows 使用：

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
```

MetaImage（`.mhd/.mha`）另装：

```bash
python -m pip install -e '.[metaimage]'
```

Mimics 内置 Python 不安装 nibabel、pydicom 或 SimpleITK。它只运行 `scripting_library/` 包装入口和 `runtime_py35/` 内部脚本。

当 review 工具是 Mimics 且来源图像是 NIfTI/MHD/MHA 时，病例包创建器会在外部 Python 中自动生成 `images/{image_id}/dicom/` 派生 DICOM，并在 manifest 中同时记录：

- `image_path`：原始 NIfTI/MHD/MHA，`sha256` 校验它；
- `dicom_path`：给 Mimics 21 导入的工作影像，`dicom_sha256` 校验它；
- `mimics_import.strategy: derived_dicom_series`：说明该 DICOM 是工具工作格式，不是原始数据。

因此标注者仍然只使用 Mimics 中的 `Labeling_*.py`，不需要知道原始数据是 DICOM、NIfTI 还是 MHD。

RAW/MHD 不是被否定的路径。MHD 的 `.raw` 只是体素字节，关键空间信息在 `.mhd` header；Mimics 21 标准图像导入资料只明确到 xy/z resolution 和方向确认，`test_images(force_raw_import=True)` 也没有给出完整的脚本化 RAW header 契约。阶段 A 因此默认派生 DICOM。后续若 POC 证明 RAW 的维度、像素类型、字节序、slice 顺序、方向预答和 P03/P05 都稳定，则可以把 RAW 作为节省存储和导入时间的可选优化。

## 5. 准备病例包

大批量数据优先从扫描开始：

```bash
sp ingest plan /data/source /data/package_requests \
  --organs-file /data/config/target_organs.txt \
  --import-batch batch_20260616 \
  --workers 8
sp package create-many /data/package_requests /data/dataset_package \
  --registry /data/platform_registry \
  --copy-mode hardlink
```

`plan` 对目录输入会调用 `scan`：把一个混合 DICOM 根目录拆成候选 Series，并为每个 Series 记录 `source_files`；也会发现三维 NIfTI 和 MetaImage 文件，并用父目录启发式生成 Case。来源目录不必预先人工整理成“一个文件夹一个序列”，但文件型数据集若有复杂含义，仍要审阅并修改生成的请求 YAML。`--workers` 并发读取文件头；需要观察耗时时可加 `--progress`。DICOM Series 的完整哈希和几何检查仍会读取实际文件，这是可复现性成本，不能省。

`package create-many --copy-mode hardlink` 可在同一磁盘上显著减少复制时间和存储占用；跨盘硬链接失败时会退回复制。`symlink` 只适合受控共享盘，不适合作为可离线搬运的交付包。

如果文件型数据集包含初始标签、CSV 配对或多标签值映射，不建议靠人工批量改 request。优先走 `sp ingest plan dataset_description.yaml ...`。

TotalSegmentator、MSD 或 CSV 配对这类数据集优先使用：

```bash
sp ingest plan /data/dataset_description.yaml /data/package_requests
```

它会根据正则或 CSV 表生成同样的 `case_package_request.v1`，包括 `initial_labels.organ` 或 `initial_labels.label_map`。后续仍由 `sp package create-many` 做图像/标签几何校验和拆分。

如果数据集需要 L4 专用 importer，交付物不是一个孤立脚本，而是一整个 import run：

```text
import_runs/{dataset_id}_{run_id}/
  requests/
  reports/import_summary.json
  reports/import_issues.csv
  reports/importer_manifest.json
```

模板见 `examples/importers/custom_importer_template.py`。平台操作者先审阅 summary 和 issues，再运行：

```bash
sp package create-many import_runs/run_001/requests /data/dataset_package \
  --registry /data/platform_registry \
  --continue-on-error
```

单个病例调试时，可以复制并修改 [病例包请求示例](../../../examples/labeling/case_package_request.yaml)。每个 DICOM `image_set` 必须只指向一个 Series；包含多个 SeriesInstanceUID 的目录会被阻断。NIfTI/MHD `image_set` 指向单个三维文件或文件组。

```bash
sp package create \
  examples/labeling/case_package_request.yaml \
  /data/dataset_package \
  --registry /data/platform_registry
```

输出包括：

```text
/data/dataset_package/
  config/
  cases/case_001/
    manifest.json
    images/
    labels/
    working/
    submissions/
    reports/
    provenance/

/data/platform_registry/
  cases/
  images/
  labels/
  reviews/
  snapshots/
```

再次检查：

```bash
sp package validate /data/dataset_package/cases/case_001
```

关键阻断规则：

- 开启 `data_governance.strict_deidentification=true` 且去标识证据不满足要求。
- 一个 image set 混入多个 DICOM Series。
- 初始 Mask 与目标图像的物理 affine 不一致。
- 器官名不在 `anatomy_vocabulary.yaml`。
- 文件复制后的哈希发生变化。
- 默认高风险 DICOM 标签仍有值，或 `BurnedInAnnotation=YES`。

扫描报告写入 `reports/ingest_report.json`，只记录标签名和策略结果，不保存原始身份值。默认行为是记录风险、不阻断标注；`deidentification_status=pending` 的数据仍可进入病例包。确有合规要求时，在 request 的 `data_governance` 中设置 `strict_deidentification: true`，这时敏感 DICOM tag 或 `BurnedInAnnotation=YES` 会阻断创建。确有治理依据允许保留某个机构字段时，可在对应 image set 请求中加入 `allowed_dicom_tags`；该例外必须与去标识 profile 一起审查。

## 6. Mimics 21 工作站一次性配置

Windows 工作站现在优先使用
[`scripts/windows/setup_mimics_workstation.ps1`](../../../scripts/windows/setup_mimics_workstation.ps1)
完成安装和本地配置，逐步命令见
[Mimics Research 21 Windows 工作站操作手册](mimics_windows_runbook.md)。

1. 安装 Mimics Research 21.0，并确认许可包含 Scripting。
2. 在 Mimics Preferences 中确认 Python 3.5.2。
3. 把 `adapters/mimics/scripting_library/` 配置为 Scripting Library。
4. 复制并修改 `config/mimics_workstation.example.yaml`。
5. 运行静态诊断：

```powershell
sp mimics doctor --config C:\SegmentationPlatform\config\mimics_workstation.yaml
```

6. 在可以启动 Mimics 的工作站运行内部诊断：

```powershell
sp mimics doctor \
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml \
  --run-diagnostics
```

7. 运行 `sp mimics probe-run`，在一个 Mimics 会话内执行 P01、P02、P04、P05、P06。
8. 运行 `sp mimics probe-evaluate`，由平台比较 DICOM LPS 几何并生成 verified 配置。不要手工猜测轴顺序。

```yaml
buffer_mapping:
  schema_version: mimics_buffer_mapping.v1
  status: verified
  evidence_id: P05_WORKSTATION_01_20260615
  platform_to_mimics_axes: [0, 1, 2]
  platform_to_mimics_flips: [false, false, false]
```

轴顺序和翻转值必须来自探针世界坐标与 Case Package 几何的唯一匹配。不同 Mimics 构建、工作站配置或导入路径变化后应重新验证。

正常情况下，一台 Mimics 工作站使用一套默认 `buffer_mapping`。如果 P05 明确证明某个 `image_id` 需要不同的轴排列或翻转，可以在同一配置中加入 per-image 覆盖：

```yaml
buffer_mapping_by_image_id:
  img_venous:
    schema_version: mimics_buffer_mapping.v1
    status: verified
    evidence_id: P05_WORKSTATION_01_IMG_VENOUS_20260615
    platform_to_mimics_axes: [2, 1, 0]
    platform_to_mimics_flips: [false, false, false]
```

覆盖项只按 `image_id` 生效。没有覆盖的图像继续使用默认 `buffer_mapping`。每个覆盖项都必须有自己的 P05 evidence；不能因为一个序列通过 P05 就推断另一个序列也相同。

## 7. Mimics 探针怎么运行

正式工作站验收优先运行自包含探针套件：

```powershell
sp mimics probe-run D:\cases\pkg_probe `
  --config C:\SegmentationPlatform\config\mimics_workstation.local.yaml

sp mimics probe-evaluate D:\cases\pkg_probe `
  D:\cases\pkg_probe\reports\mimics_probe\mimics_probe_evidence.json `
  --config C:\SegmentationPlatform\config\mimics_workstation.local.yaml `
  --output-config C:\SegmentationPlatform\config\mimics_workstation.verified.yaml
```

`sp_probe_suite.py` 会在同一个 Mimics 会话内维持图像、Mask 和 `.mcs` 上下文。下面的单项脚本用于定位某一步失败，不再要求操作者手工拼接完整验收流程。

```powershell
MimicsResearch.exe -background_mode -run_script `
  "C:\SegmentationPlatform\adapters\mimics\probes\p01_dicom_grouping.py" `
  "D:\cases\dicom" "D:\evidence\p01.json"
```

| 探针 | 输入 | 产生的证据 |
| --- | --- | --- |
| `p01_dicom_grouping.py` | DICOM 根目录、JSON 输出 | 实际 image sets、UID 哈希、shape |
| `p02_image_set_binding.py` | `.mcs` 输出、JSON 输出 | Mask 与 image set 绑定及重开项目 |
| `p04_mask_buffer.py` | `.u8` 输出、JSON 输出 | 非对称体素点和 buffer shape |
| `p05_geometry_roundtrip.py` | JSON 输出 | 原点、三个单位轴和末端体素的世界坐标 |
| `p06_selective_export.py` | review/target/organ、输出路径 | 单个指定 Mask 的哈希和 shape |

P05 不是收集到坐标就结束。`probe-evaluate` 必须得到唯一轴排列与翻转组合，并满足物理坐标误差阈值，生成的配置才会标记为 verified。

## 8. 标注者完整流程

标注机不做平台配置。平台在准备机完成 `prepare/prebuild`，随后导出工作包：

```powershell
sp mimics prebuild-workspace D:\dataset_package\cases\case_001 `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml

sp mimics prebuild-many D:\dataset_package\cases `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml `
  --continue-on-error

sp review export-worklist `
  --registry D:\platform_registry `
  --output-root D:\transfer\batch_001 `
  --limit 30 `
  --overwrite
```

`prebuild` 默认只处理尚未有 `.mcs` 的任务；已有 `working/prebuilt_workspace.json` 的任务会跳过为 `already_prebuilt`，已有普通 `.mcs` 的任务会跳过为 `already_exists`，避免后台覆盖标注者正在编辑的工作现场。确需重建时显式加 `--rebuild-workspace`。

后台 `prepare` 完成：

- 再次检查病例包。
- 生成 `working/mimics_runtime.json`。
- 有初始标签时生成 `working/bridge/import/{image_id}/{organ}.u8`。
- 未通过 P05 时阻止已有标签注入。

同一图像的初始逐器官 Mask 会登记成一份多 segment Label Artifact。若一个目标组的全部器官都来自该 Artifact，病例包会自动把它设为目标组的基础标签，后续提交必须回传相同 ID 和 bundle hash。

标注者默认运行 `Labeling_Open_Next_Case.py`，非默认导航使用 `Labeling_Case_Navigation.py`。共享控制器调用 `sp_open_review.py`，内部脚本完成：

- 首次任务导入 DICOM；预生成或继续任务打开专属 `.mcs`。
- 使用 Series UID 哈希和 shape 唯一匹配 image set。
- 每次操作目标前显式 `set_active()`。
- 为每个目标器官建立一个平台受管 Mask。若 target 中存在 `known_absent`，只把它当作来源数据已明确给出的例外事实：对应器官跳过，不建 Mask、不导出、不参与 QC。普通标注任务不要求也不建议在打开病例前填写它。
- 写入 `review_id/target_id/image_id/organ/base_label` metadata。
- 继续任务时先核对已有 Mask 的 `base_label_id + bundle hash`，不一致即阻断。
- 只在首次创建 Mask 时注入初始缓冲区。
- `.mcs` 不可用且选择重建时，优先恢复匹配当前任务版本和 mapping evidence 的 recovery backup。
- 保存任务专属 `.mcs`；首次打开显示一次摘要，续标不再弹（可随时用 Task List 重看）。Task List 会分页显示器官统计和当前 Mask 状态，并支持按 Missing、Ready、With Initial、Known Absent 筛选；完整清单写入 `reports/mimics_task_list.txt`。

打开成功后，Registry 中该 Review 和尚未开始的目标组会更新为 `in_progress`，并追加 `open_started` 事件。

标注者只执行：

1. 打开 Mimics。
2. 运行与目的对应的 `Labeling_*.py` 入口。
3. 打开下一例、继续上一例或选择任意病例。
4. 核对病例、序列和目标器官统计；完整器官清单通过 Mimics 内的 Task List 分页和状态筛选查看，必要时再查 `reports/mimics_task_list.txt`。
5. 使用 Mimics 正常工具编辑 Mask。
6. 可随时保存 `.mcs` 并关闭。
7. 长时间工作后可运行 `Labeling_Save_Recovery_Backup.py`。
8. 根据结果运行 `Labeling_Submit_Complete.py` 或 `Labeling_Submit_or_Report_Issue.py`。
9. 如有 2–5 个目标组，可勾选任意组合一次提交。

保存 `.mcs` 不会创建正式标签。提交脚本也只写出缓冲区和提交意图。
提交前会聚合检查 Mask 完整性、image set、基础版本和 shape。多个空 Mask 只在弹窗中预览前若干项，完整清单写入报告；可统一确认，也可以逐项判断。

## 9. 平台收尾

Mimics 导出后由平台后台或管理员批处理执行：

```powershell
sp mimics finalize D:\dataset_package\cases\case_001 `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml `
  --registry D:\platform_registry
```

`finalize` 先完成全部预检，再写任何 Registry 标签：

- `review_id`、`target_id` 和基础标签版本；assignee 仅在显式强制时检查。
- 每个目标组要求的全部器官。
- export manifest 中的 `image_id`。
- export buffer 使用相对 Case Package 的路径，且不能逃逸病例包目录。
- `.u8` 字节数和 SHA-256。
- 经 P05 校准后的反向轴映射和 shape。
- 空 Mask 是否明确声明 `confirmed_absent`。
- “完成”提交中不能包含 `uncertain`。

结果：

| 提交动作 | QC 通过后的标签 | Review 状态 |
| --- | --- | --- |
| `submit_complete` | 新的 `verified_label` | 目标组 `completed` |
| `submit_for_review` | 新的 `draft_label` | 目标组 `needs_review` |
| `report_blocked` | 不创建标签 | 目标组 `blocked` |
| QC 失败 | 不登记新标签 | 目标组回到 `in_progress` |

人工修订继承基础标签的生成器血统和使用限制。旧 Label Artifact 不被覆盖。

## 10. 标注中需求变化

### 10.1 数据集增加病例

新增病例不影响已有病例包、已完成 review 或已登记 Label Artifact。推荐流程：

```bash
sp ingest plan /data/new_cases /data/new_requests \
  --organs-file /data/config/target_organs.txt \
  --import-batch batch_002 \
  --workers 8
sp package create-many /data/new_requests /data/dataset_package \
  --registry /data/platform_registry \
  --continue-on-error
sp mimics prepare-many /data/dataset_package/cases \
  --config mimics_workstation.verified.yaml \
  --continue-on-error
sp review export-worklist \
  --registry /data/platform_registry \
  --output-root /transfer/batch_002_increment
```

新增工作包独立分发，不覆盖标注者已经在做的病例。需要中央记录接收者时可加 `--assignee annotator_01`；它只是筛选和提示，不是标注端运行条件。

### 10.2 标注任务追加器官

不要用 `overwrite=True` 重建原病例包。对已完成或需要返修的病例，创建 follow-up review：

```bash
sp review create-followup \
  --registry /data/platform_registry \
  --output-root /data/dataset_package \
  --case-id case_001 \
  --organs kidney_left kidney_right \
  --review-suffix add_kidney \
  --assignee annotator_01
```

该命令会：

- 找到该 case/image 当前 active 的基础 Label Artifact；
- 创建新的 review package，路径形如 `cases/case_001-add_kidney/`；
- 把旧标签作为 `base_label_id`；
- 在 Mimics 中只要求标注新增器官；
- Finalize 通过后生成包含旧器官和新增器官的新 Label Artifact；
- 把旧 base 标记为 `superseded`，但不删除旧文件、旧提交或旧报告。

对于尚未开始的 `ready` review，如果确认标注者还没有打开 `.mcs`，平台管理员可以删除并重建该 review package，或用后续专门命令做安全更新。对于已经 `in_progress` 的 review，阶段 A 不支持直接追加器官到原任务：标注者本地 `.mcs`、Mask metadata、`mimics_runtime.json`、提交清单和 Registry 记录已经形成一组一致状态，动态插入新器官会增加 Mask 缺失、基础标签 hash 不一致和提交范围混乱的风险。

因此 `in_progress` 追加器官统一走 follow-up review。旧 review 继续完成原目标；新增器官创建新的 review package，并把当前 active Label Artifact 作为 base label。这样不会丢弃已完成工作，也不会要求标注者在一个已经打开的 `.mcs` 中理解“任务范围突然变化”。

这不是禁止现场探索。标注者可以在 Mimics 中临时自建 Mask 做判断或记录，但这些 Mask 没有平台 metadata，也不在 `mimics_runtime.json` 和 manifest 的目标清单中，因此不会被 `sp_submit_review.py` 导出。提交脚本会在发现未管理 Mask 时提示“这些不会被导出”，并写入 `reports/mimics_unmanaged_masks.txt`。如果临时 Mask 有价值，标准处理是创建 follow-up review，然后由标注者或管理员把它复制/转移到平台创建的正式 Mask 中再提交。

这条规则把灵活性放在“现场工作区”和“follow-up 接入点”，把严格性保留在“正式提交和 Label Artifact”。否则短期看似灵活，长期会失去 provenance、QC 和版本复现能力。

### 10.3 已完成标签继续修正

同样使用 `sp review create-followup`。若要重修 liver：

```bash
sp review create-followup \
  --registry /data/platform_registry \
  --output-root /data/dataset_package \
  --case-id case_001 \
  --organs liver \
  --review-suffix relabel_liver \
  --assignee annotator_02
```

标注者打开新 review 时看到 liver 从旧版本导入，可直接修正。提交完成后，新 Label Artifact 会 carry-forward base 中未重修的其他器官。

### 10.4 分配的数据不一定全标

三种方式：

| 需求 | 做法 |
| --- | --- |
| 只先分发 N 例 | `sp review export-worklist --limit N` |
| 标注者临时跳过当前病例 | Mimics 中选择 **Skip Case**，只修改工作包进度；可用 **Choose Case** 随时重开 |
| 中央管理员长期暂停某 review | 在下一次分发前使用 `sp review defer --registry ...`；不会远程修改已发出的工作包 |

`deferred` 不等于 `blocked`。前者只是暂不处理，后者表示数据或工具问题导致无法继续。

## 11. 创建训练前快照

对少量病例，可以手写 `snapshot_request.v1` 并明确每个器官使用哪个 `label_id`。对几百到几千病例，不应手写 `label_id`，先从 Registry 生成请求草稿：

```bash
sp snapshot build-request \
  --registry /data/platform_registry \
  --output /data/requests/snapshot_liver.yaml \
  --snapshot-id snapshot_liver_001 \
  --task-id liver_task \
  --organs liver \
  --allow-lifecycle-status verified_label \
  --default-split train
```

如果已有患者级 split 计划，提供 CSV：

```bash
sp snapshot build-request \
  --registry /data/platform_registry \
  --output /data/requests/snapshot_abdomen.yaml \
  --snapshot-id snapshot_abdomen_001 \
  --task-id abdomen_task \
  --organs liver spleen kidney_left kidney_right \
  --split-plan /data/splits/abdomen_split.csv \
  --allow-lifecycle-status verified_label
```

`split_plan.csv` 至少包含 `case_id,split`，可选 `image_id`。生成器会查找每个 case/image 下任务器官的唯一 active Label Artifact；有多个候选会跳过并报告，避免静默选错版本。默认允许部分器官标签进入请求草稿；如果任务必须每例全器官齐全，加 `--require-all-organs`。

草稿审阅后再冻结 Snapshot：

```bash
sp snapshot create \
  /data/requests/snapshot_liver.yaml \
  --registry /data/platform_registry
```

创建时检查：

- 器官名和任务标签编号。
- 编号从 0 连续。
- 标签生命周期满足本次 `label_policy`。
- Label 的 case/image 与请求一致。
- Image Artifact 的用途限制：`train` 检查 `usability.training`，`val/test` 检查 `usability.evaluation`；`blocked` 不得进入 Snapshot。
- 同一 `leakage_group_id` 不跨 train/val/test。
- 所有输入的 `usage_constraints` 取最严结果。

`cases[].segments` 是本病例实际进入监督的器官列表，不要求等于 `task_label_map` 的全集。一个病例只有肝标签时可以只列 liver；缺失器官不能在 Snapshot 中伪装成背景。后续训练导出适配器必须根据 Snapshot 中实际存在的 segment 决定监督、ignore 或按器官排除。

快照写入后不可覆盖：

```bash
sp snapshot validate /data/platform_registry/snapshots/snap_abdomen_v1.json
```

到这里训练前闭环结束。后续 nnUNet Adapter 只能读取已冻结的 Snapshot。

## 12. 异常和恢复

| 情况 | 处理 |
| --- | --- |
| Mimics 打开失败 | 查看 `reports/mimics_open_error.json`，修复后重新运行对应打开入口 |
| 标注中断 | 保存 `.mcs`，以后在 `Labeling_Case_Navigation.py` 中继续 |
| Mask 错序列 | 提交脚本阻断；不要手工改 header |
| Mimics 提交前检查失败 | 查看弹窗和 `reports/mimics_submit_precheck.json` |
| 提交 QC 失败 | 弹窗显示主要 finding 和动作建议；完整技术细节见 `reports/review_report.json` |
| 提交过程中 Mimics 崩溃 | 半成品在 `.partial_*` staging 目录；下一次提交自动清理，正式 `submissions/` 不会被半截结果污染 |
| 已验证标签要修改 | `sp review create-followup` 新建 review，旧标签作为 base label；complete 通过后旧标签变为 `superseded` |
| 病例包创建中途失败 | 下次 `sp package create` 发现无 `manifest.json` 的残留目录会自动清理后重试 |
| 多标注者 | 每人独立 `review_id` 和 `.mcs`；阶段 A 不共享写同一文件 |
| `.mcs` 损坏 | 运行 `prepare --rebuild-workspace` 保留旧文件，并从最新 recovery backup 或初始标签重建 |

## 13. 规模化标注的当前决策

| 问题 | 当前处理 |
| --- | --- |
| 手写 10000 份 YAML 不可行 | 推荐 `sp ingest plan` + `sp package create-many`。`plan` 可以从目录、scan JSON 或 dataset description 生成 request，人工只审阅规则和异常项。 |
| 图像和标签规则复杂 | 使用 `sp ingest plan dataset_description.yaml ...`，用正则或 CSV 明确图像-标签配对和 label value 映射；仍表达不了时按 L4 importer 契约输出标准 request 和 issues。 |
| 一个 `.mcs` 多病例能否减少启动成本 | 阶段 A 不采用。单 `.mcs` 多病例会放大项目损坏、Mask 误绑定、部分提交、多人分派和失败回滚的风险。当前选择一个 review/case 一个 `.mcs`，用批量发现和批量创建降低平台侧成本。 |
| prepare/open/finalize 是否仍需逐病例 | 已提供批量平台命令。标注者不运行平台 `open`，只运行工作包中的直接 Mimics 入口。 |
| Registry 标签查询 O(N) | 文件式 Registry 已维护 `_indexes/labels_by_case_image_organ.json`。旧 Registry 可运行 `sp registry rebuild-index /data/platform_registry` 生成索引。 |
| 空间信息不完整 | 数据导入契约允许 `complete/partial/index_only`，但 Mimics 病例包当前仍要求可控的工具空间。纯 RAW 和无法证明空间的来源应先创建带明确假设的派生图像，或停在导入报告中。 |
| 部分器官标签 | Snapshot 支持按病例列出实际 segment 子集。不能把未标器官当背景；训练导出层后续要显式实现 ignore/排除策略。 |
| 几千病例手写 Snapshot `label_id` 不可行 | 使用 `sp snapshot build-request` 从 Registry 自动生成请求草稿；人工只审阅 skipped/ambiguous 项和 split。 |
| 标注中追加器官或返修 | 使用 `sp review create-followup` 创建增量 review；旧 submissions/reports 不删除，旧 Label Artifact superseded 而非覆盖。 |
| 不想标完工作包中的全部病例 | 标注者可任选、跳过或停止，平台只回收实际提交的病例；`--limit` 仅控制每次工作包大小。 |

## 14. 非线性流程和当前缺口

阶段 A 的命令看起来是线性的，但实现目标不是固定流水线。当前应把流程理解为 Registry 对象图：

```text
Image Artifact
  -> Review Task -> Label Artifact
  -> Candidate Generation Job -> Candidate Label
Label Artifact(s)
  -> Dataset Snapshot -> Model Record
```

当前支持和缺口如下：

| 场景 | 当前是否支持 | 处理方式或缺口 |
| --- | --- | --- |
| 一批图像先登记，稍后再决定标注器官 | 支持 | `sp ingest register` 只写 Case/Image，不创建病例包和 review |
| 同一图像分给不同工具标注 | 部分支持 | 可创建多个 review package；新对象图命令会写入最小 run record，但还不是完整调度 DAG |
| 两个标注者标同一病例不同器官 | 支持 | 可用 `sp label merge` 合并同一 case/image 下互不冲突的 Label Artifact；同器官冲突必须显式 `--organ-source organ=label_id` |
| Finalize 失败后回到标注者 | 支持 | `finalize` 失败写 `review_report.json`，review 回到 `in_progress` |
| Snapshot 发现 leakage 冲突 | 支持修正，不需要标注者 | 修正 split plan 后重新创建 Snapshot；这不是标签错误 |
| Snapshot 发现标签版本、来源或质量问题 | 支持 | `sp review create-from-finding` 可从 Snapshot/QC 报告生成 follow-up review；无器官信息的 finding 会被列为 unsupported |
| 高质量外部标签直接进入训练 | 支持 | `sp label register` 可给已登记 Image Artifact 追加 `source_label`，Snapshot policy 决定是否采用；无需创建 review |
| 自建或临时 Mask 进入正式链路 | 受控支持 | 当前提交会提示未管理 Mask 不导出；后续应实现 `adopt unmanaged mask` 或 follow-up 中的正式转入 |

因此，下一步仍不应直接上 Airflow/Celery。当前已经补齐的对象图命令包括：

1. `sp label merge`：把同一 case/image 下不同 Label Artifact 的互不冲突 segment 合成一个新 Label Artifact，并记录每个 segment 的 lineage。
2. `sp review create-from-finding`：把 Snapshot 或 QC finding 转成 follow-up review 草稿。
3. `sp label register-many`：从 CSV、JSON 或 YAML 表格批量追加外部标签，避免逐条命令。
4. 最小 run record：上述对象图命令会在 Registry `_runs/` 下记录 `run_id`、输入、输出和结果摘要。

仍未实现的是 Mimics 临时自建 Mask 的正式纳管命令，以及覆盖所有历史批处理命令的统一 run record。

## 15. 命令速查

标注者不直接运行任何 `sp` 命令；下表面向平台实施者。

| 目的 | 推荐命令 | 关键输入 | 关键产出 | 备注 |
| --- | --- | --- | --- | --- |
| 从目录生成标注请求 | `sp ingest plan SOURCE REQUESTS --organs-file ORGANS --import-batch BATCH --workers N` | 数据目录、器官文件 | `source_scan.json`、`case_package_request.v1` | 统一入口；可加 `--progress` |
| 从复杂描述生成请求 | `sp ingest plan dataset_description.yaml REQUESTS` | 数据集描述 | `case_package_request.v1` | 用于图像/标签配对、label map、CSV |
| 只登记图像资产 | `sp ingest register source_scan.json --registry REGISTRY --import-batch BATCH` | scan JSON | `cases/`、`images/` | 不创建 review，可后续复用 |
| 创建病例包 | `sp package create-many REQUESTS PACKAGE --registry REGISTRY --copy-mode hardlink` | request 目录 | `cases/{case_id}/manifest.json`、Review Task | `hardlink` 降低复制成本 |
| 中央筛选或改派 | `sp review assign --review-id R --assignee A` | Review Task | 更新协调信息 | 不影响已导出工作包或标签 |
| 导出可移动工作包 | `sp review export-worklist --limit N` | Registry、已 prepare 病例包 | `Labeling_*.py`、runtime、cases、相对路径 manifest | `--assignee A` 仅作可选筛选；默认跳过已分发 review |
| 回收提交 | `sp mimics collect-submissions RETURNED CENTRAL --registry REGISTRY` | 标注者返还目录 | 中央 `submissions/`、`reports/` | 后续再 finalize |
| 批量收尾 | `sp mimics finalize-many CASES --registry REGISTRY --config CONFIG` | 已提交病例包 | Label Artifact、review_report | 标注者不执行 |
| 追加外部标签 | `sp label register-many table.csv --registry REGISTRY` | CSV/JSON/YAML 表 | Label Artifact | 适合 source label 或算法标签 |
| 合并标签版本 | `sp label merge --label-id A --label-id B` | 同一 case/image 的标签 | 新 Label Artifact | 冲突器官需显式指定来源 |
| 从问题生成返修 | `sp review create-from-finding finding.json --registry REGISTRY --output-root PACKAGE` | Snapshot/QC finding | follow-up review | 不覆盖旧标签 |

常见中间文件含义：

| 文件 | 谁生成 | 用途 |
| --- | --- | --- |
| `source_scan.json` | `sp ingest plan` 或 `sp ingest scan` | 数据发现报告，不写 Registry |
| `case_package_request.v1` | `plan`、description 或 importer | 可审阅建包请求，说明图像、目标器官和初始标签 |
| `manifest.json` | `sp package create*` | 单病例包事实来源，给 Mimics 和 finalize 使用 |
| `mimics_runtime.json` | `sp mimics prepare` | Mimics 内脚本的运行计划；路径在工作包首次打开时自动重绑定 |
| `worklist_manifest.json` | `sp review export-worklist` | 工作包病例清单，所有路径相对工作包根目录 |
| `worklist_progress.json` | Mimics Console | 可删除、可重建的本地进度，不是配置或 Registry |
| `submission_manifest.json` | Mimics 内提交脚本 | 标注者选择的提交动作和目标组 |
| `export_manifest.json` | Mimics 内提交脚本 | 导出的 Mask buffer 列表和 hash |
| `review_report.json` | `finalize` | 平台 QC 结果和问题说明 |

## 16. 验证命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests adapters/mimics
.venv/bin/python -m pip check
```

自动测试覆盖合成 DICOM、候选标签、病例包、Registry、Mimics buffer 准备、模拟提交、Label Artifact 和 Dataset Snapshot。真实 Mimics API、许可、界面行为和空间往返只能在 Mimics 21 工作站验收。
