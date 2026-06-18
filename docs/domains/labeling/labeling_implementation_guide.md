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

### 阶段 1：一次性工作站配置

**谁做**：平台操作者，在每台 Mimics 21 工作站上执行一次。

**目标**：确认这台机器能可靠地导入平台 DICOM、操作 Mask 并原样导出。

**步骤**：

1. 安装 Mimics Research 21.0，确认许可含 Scripting 模块。在 `File → Preferences → Scripting` 中配置 Python 3.5.2。
2. 把 `adapters/mimics/scripting_library/` 设为 Scripting Library；`runtime_py35/` 是内部实现目录，不直接暴露给标注者。
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

**验证方式**：检查 `buffer_mapping.status` 是否为 `verified`；不是 verified 时不允许注入初始标签和回收提交。

---

### 阶段 2：创建病例包

**谁做**：平台操作者，每批标注任务执行一次。

**目标**：把原始数据整理成标注者可以直接使用的离线工作目录，同时在 Registry 中登记所有资产。

推荐批量入口：

```bash
sp ingest scan /data/source --output /data/reports/source_scan.json

sp ingest build-requests /data/reports/source_scan.json /data/package_requests \
  --organs liver spleen kidney_left kidney_right \
  --import-batch batch_20260616 \
  --assignee annotator_01

sp package create-many /data/package_requests /data/dataset_package \
  --registry /data/platform_registry \
  --continue-on-error
```

这三步分别负责“发现”“生成可审阅请求”“创建病例包”。中间的请求文件允许人工批量检查和修改，比如只保留静脉期、修改 assignee、补充初始标签或调整目标器官。扫描报告不保存原始 PatientID，只保存哈希、相对路径和导入可用性。

`scan` 的边界要分清：

- DICOM：按 Study/Series 元数据分组，一个 Series 生成一个 `image_set`。
- NIfTI/MHD/MHA：按文件发现，同一父目录默认归为一个 Case；顶层文件各自成为独立 Case。
- RAW：没有明确 sidecar 时只报告为不可直接导入。
- 复杂数据集：自动生成的请求只是草稿，仍需要人工或数据集描述文件补充“哪些文件是标签、标签值对应哪个器官、哪些序列应进入标注”。

病例包可以登记 NIfTI/MHD，但 Mimics 21 主路径的首次打开仍以 DICOM 或已有 `.mcs` 为准。若标注工具选择 Mimics，非 DICOM 图像需要先转换成 Mimics 可接受的 DICOM/`.mcs` 工作区，或改用能原生打开该格式的标注工具。

单例调试入口仍然可用：

```bash
sp package create examples/labeling/case_package_request.yaml /data/dataset_package --registry /data/platform_registry
```

**这个命令做的事**：

- 从来源区读取图像 → DICOM 按患者/检查/序列分组，文件型图像按路径启发式分组 → 为每个三维体素网格创建 `image_id`
- 复制图像到 `images/{image_id}/`，检查去标识状态和文件哈希
- 如有初始候选标签，拆为逐器官 NIfTI 放入 `labels/{image_id}/masks/`
- 生成 `manifest.json`（image_sets、器官列表、标注目标组、base label 版本）
- 在 Registry 中创建 Case、Image Artifact、Label Artifact、Review Task 记录

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

检查项：去标识是否 verified、DICOM 序列是否单一、初始 Mask 与图像 affine 是否一致、器官名是否在词表中、文件复制后哈希是否变化。

---

### 阶段 3：为 Mimics 准备任务队列

**谁做**：平台操作者或后台脚本。

**目标**：把病例包和 Registry 变成 Mimics 内 `SP Review Console` 可以领取的任务队列。这个阶段不要求标注者参与。

```bash
sp review next --registry /data/platform_registry --assignee annotator_01
sp mimics prepare /data/dataset_package/cases/case_001 --config mimics_workstation.yaml
```

平台可以提前批量运行 `prepare`，也可以让 `SP Review Console` 在标注者点击 **Open Next Review** 后后台调用 `prepare`。两种方式都不能暴露给标注者。

**平台提前做的事**：

- 批量创建病例包和 Registry 记录；
- 为每个标注者分配 `review_id`；
- 配置 `adapters/mimics/scripting_library/sp_review_console.local.json`，或由 Windows setup 脚本生成；
- 可选批量运行 `sp mimics prepare`，生成 `working/mimics_runtime.json` 和导入缓冲区；
- 运行 `sp review next` 检查队列是否能取到下一例。

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

**`SP Review Console` 打开任务时做的事**：

- 在 Mimics 内调用 `sp_review_console.py`；
- 通过外部 Python 查询 `sp review next`；
- 如本例尚未准备，后台调用 `sp mimics prepare`；
- 标记 Review 为 `in_progress`；
- 在当前 Mimics 会话里调用 `sp_open_review.py`；
- `sp_open_review.py` 导入 DICOM 或打开 `.mcs` → 用 UID 哈希 + shape 将 image set 与 `image_id` 一一匹配 → 为每个 target 中**未声明 `known_absent`** 的器官创建/找到 Mask → 写入 7 个 metadata（review_id、target_id、image_id、organ、base_label_id/hash、package_root）→ 如有 import buffer 则在首次创建时注入 → 保存 `.mcs` → 首次打开（new）弹出任务摘要对话框，续标（resume）不再弹（可随时用 Show Summary 重看）。

**验证方式**：

- `prepare` 后检查 `working/mimics_runtime.json` 和 `working/bridge/import/` 是否有内容
- `SP Review Console` 打开后 Mimics 弹窗显示任务摘要（病例号、序列数、目标器官列表）
- Registry 中 Review 状态更新为 `in_progress`
- 报告写入 `reports/mimics_open_report.json`

---

### 阶段 4：标注者工作

**谁做**：标注者。只在 Mimics 里操作，不碰命令行。

**标注者看到的流程**：

1. 打开 Mimics。
2. 运行 `Script → Scripting Library → SP Review Console`。
3. 选择 **Open Next Review**，弹窗显示任务摘要。**核对**：病例是否正确、有哪些序列、每个序列要标哪些器官。
4. 如不一致 → 通过 `SP Review Console` 进入提交动作并报告阻塞，不编辑。
5. 如一致 → 使用 Mimics 正常工具编辑每个 Mask。每个 Mask 的名称、metadata 由平台管理，标注者不改。
6. 随时 Ctrl+S 保存 `.mcs`。保存只保留进度，不触发提交。
7. 长时间工作后可在 `SP Review Console` 里选择 **Save Checkpoint**，额外保存一份独立于 `.mcs` 的 Mask 恢复快照。
8. 关闭软件后，下次仍打开 Mimics 并进入 `SP Review Console` 继续。

**标注者不需要知道的事**：标签生命周期、文件哈希、NIfTI 格式、训练编号、Registry 路径。

---

### 阶段 5：提交

**谁做**：标注者触发，Mimics 内部脚本执行导出。

**标注者的操作**：

1. `Script → Scripting Library → SP Review Console`
2. 选择 **Submit Current Review**
3. 第一个对话框：选择提交意图 — **提交完成 / 提交复查 / 报告阻塞 / 取消**
4. 第二个对话框：选择要提交的目标组 — 一个、多个（2–5 个时模拟勾选）或全部
5. 如有空 Mask，弹出聚合清单 — 可统一选择"全部确认不存在""全部待复查"或逐项判断
6. 等待脚本提示 "已导出，仍需平台检查"

**脚本在后台做的事**（`sp_submit_review.py`）：

- **提交完成**：检查所有 Mask 存在且绑定正确 → 空 Mask 确认语义 → `get_voxel_buffer()` 导出每个 Mask 为 `.u8` → 写入 `submissions/{review_id}/buffers/` → 生成 `export_manifest.json` 和 `submission_manifest.json`（action=submit_complete）→ 保存 `.mcs` → 弹窗提示
- **提交复查**：同提交完成，action=submit_for_review，记录不确定原因
- **报告阻塞**：不要求所有 Mask 完成，写入阻塞类型和原因

**验证方式**：检查 `submissions/{review_id}/` 下是否出现了 `submission_manifest.json`、`export_manifest.json` 和 `buffers/` 中的 `.u8` 文件。

---

### 阶段 6：平台收尾

**谁做**：平台后台脚本或管理员批处理，不由标注者执行。

```bash
sp mimics finalize /data/dataset_package/cases/case_001 --config mimics_workstation.yaml --registry /data/platform_registry
```

**`finalize` 做的事**（这是最关键的 QC 闸门，全部检查通过才写 Registry）：

1. **身份检查**：review_id、target_id、assignee 与 Registry 记录是否匹配
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

`sp_review_console.py` 支持 `auto_finalize=true`，可以在提交后立即调用 `finalize`；阶段 A 推荐默认 `false`，由平台独立 watcher 或批处理收尾，避免标注者等待长时间 QC。

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
  分配 review_id + 可选提前 prepare
         │
[标注者] 打开 Mimics → SP Review Console → Open Next Review
         │
[标注者] 在 Mimics 中编辑 Mask → 随时保存 .mcs → 可选 Save Checkpoint
         │
[标注者] SP Review Console → Submit Current Review → 导出 .u8
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

## 5. 准备病例包

大批量数据优先从扫描开始：

```bash
sp ingest scan /data/source --output /data/reports/source_scan.json
sp ingest build-requests /data/reports/source_scan.json /data/package_requests \
  --organs liver spleen kidney_left kidney_right \
  --import-batch batch_20260616
sp package create-many /data/package_requests /data/dataset_package --registry /data/platform_registry
```

`scan` 会把一个混合 DICOM 根目录拆成候选 Series，并为每个 Series 记录 `source_files`；也会发现三维 NIfTI 和 MetaImage 文件，并用父目录启发式生成 Case。来源目录不必预先人工整理成“一个文件夹一个序列”，但文件型数据集若有复杂含义，仍要审阅并修改生成的请求 YAML。`build-requests` 生成的是可审阅 YAML，不直接写 Registry。

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

- 去标识状态不是 `verified`。
- 一个 image set 混入多个 DICOM Series。
- 初始 Mask 与目标图像的物理 affine 不一致。
- 器官名不在 `anatomy_vocabulary.yaml`。
- 文件复制后的哈希发生变化。
- 默认高风险 DICOM 标签仍有值，或 `BurnedInAnnotation=YES`。

扫描报告写入 `reports/ingest_report.json`，只记录标签名和策略结果，不保存原始身份值。确有治理依据允许保留某个机构字段时，可在对应 image set 请求中加入 `allowed_dicom_tags`；该例外必须与去标识 profile 一起审查。

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

管理员先完成一次性配置：

```powershell
copy C:\SegmentationPlatform\config\mimics_review_console.example.json `
  C:\SegmentationPlatform\adapters\mimics\scripting_library\sp_review_console.local.json
```

本机 JSON 至少记录：

- 外部平台 Python；
- Registry 根目录；
- verified 工作站配置；
- 当前标注者 assignee；
- 是否在提交后立刻 `auto_finalize`。

平台可提前批量运行 `prepare`；如果没有提前准备，`SP Review Console` 会在打开下一例时后台调用 `prepare`。

后台 `prepare` 完成：

- 再次检查病例包。
- 生成 `working/mimics_runtime.json`。
- 有初始标签时生成 `working/bridge/import/{image_id}/{organ}.u8`。
- 未通过 P05 时阻止已有标签注入。

同一图像的初始逐器官 Mask 会登记成一份多 segment Label Artifact。若一个目标组的全部器官都来自该 Artifact，病例包会自动把它设为目标组的基础标签，后续提交必须回传相同 ID 和 bundle hash。

标注者打开 Mimics 后运行 `Script -> Scripting Library -> SP Review Console`，选择 **Open Next Review**。Console 后台调用 `sp_open_review.py`，内部脚本完成：

- 首次任务导入 DICOM；继续任务打开专属 `.mcs`。
- 使用 Series UID 哈希和 shape 唯一匹配 image set。
- 每次操作目标前显式 `set_active()`。
- 为每个目标器官建立一个 Mask；target 中 `known_absent` 声明的器官跳过（不建 Mask、不导出、不参与 QC）。
- 写入 `review_id/target_id/image_id/organ/base_label` metadata。
- 继续任务时先核对已有 Mask 的 `base_label_id + bundle hash`，不一致即阻断。
- 只在首次创建 Mask 时注入初始缓冲区。
- `.mcs` 不可用且选择重建时，优先恢复匹配当前任务版本和 mapping evidence 的 checkpoint。
- 保存任务专属 `.mcs`；首次打开显示一次摘要，续标不再弹（可随时用 Show Summary 重看）。

打开成功后，Registry 中该 Review 和尚未开始的目标组会更新为 `in_progress`，并追加 `open_started` 事件。

标注者只执行：

1. 打开 Mimics。
2. 运行 **SP Review Console**。
3. 打开下一例或继续当前例。
4. 核对病例、序列和目标器官。
5. 使用 Mimics 正常工具编辑 Mask。
6. 可随时保存 `.mcs` 并关闭。
7. 长时间工作后可在 Console 里选择 **Save Checkpoint**。
8. 完成时在 Console 里选择 **Submit Current Review**。
9. 选择完成、复查、阻塞或取消；2–5 个目标组可勾选任意组合一次提交。

保存 `.mcs` 不会创建正式标签。提交脚本也只写出缓冲区和提交意图。
提交前会聚合检查 Mask 完整性、image set、基础版本和 shape。多个空 Mask 可统一确认，
也可以逐项判断。

## 9. 平台收尾

Mimics 导出后由平台后台或管理员批处理执行：

```powershell
sp mimics finalize D:\dataset_package\cases\case_001 `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml `
  --registry D:\platform_registry
```

`finalize` 先完成全部预检，再写任何 Registry 标签：

- `review_id`、`target_id`、assignee 和基础标签版本。
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

## 10. 创建训练前快照

修改 [Snapshot 请求示例](../../../examples/labeling/snapshot_request.yaml)，明确每个器官使用哪个 `label_id`：

```bash
sp snapshot create \
  examples/labeling/snapshot_request.yaml \
  --registry /data/platform_registry
```

创建时检查：

- 器官名和任务标签编号。
- 编号从 0 连续。
- 标签生命周期满足本次 `label_policy`。
- Label 的 case/image 与请求一致。
- 同一 `leakage_group_id` 不跨 train/val/test。
- 所有输入的 `usage_constraints` 取最严结果。

`cases[].segments` 是本病例实际进入监督的器官列表，不要求等于 `task_label_map` 的全集。一个病例只有肝标签时可以只列 liver；缺失器官不能在 Snapshot 中伪装成背景。后续训练导出适配器必须根据 Snapshot 中实际存在的 segment 决定监督、ignore 或按器官排除。

快照写入后不可覆盖：

```bash
sp snapshot validate /data/platform_registry/snapshots/snap_abdomen_v1.json
```

到这里训练前闭环结束。后续 nnUNet Adapter 只能读取已冻结的 Snapshot。

## 11. 异常和恢复

| 情况 | 处理 |
| --- | --- |
| Mimics 打开失败 | 查看 `reports/mimics_open_error.json`，修复后由 **SP Review Console** 重新打开 |
| 标注中断 | 保存 `.mcs`，以后仍打开 Mimics 并通过 **SP Review Console** 继续 |
| Mask 错序列 | 提交脚本阻断；不要手工改 header |
| Mimics 提交前检查失败 | 查看弹窗和 `reports/mimics_submit_precheck.json` |
| 提交 QC 失败 | 查看 `reports/review_report.json`；下次通过 Console 打开时会显示失败摘要 |
| 已验证标签要修改 | 新建 `review_id`，旧标签作为 base label，不覆盖旧版本 |
| 多标注者 | 每人独立 `review_id` 和 `.mcs`；阶段 A 不共享写同一文件 |
| `.mcs` 损坏 | 运行 `prepare --rebuild-workspace` 保留旧文件，并从最新 checkpoint 或初始标签重建 |

## 12. 规模化标注的当前决策

| 问题 | 当前处理 |
| --- | --- |
| 手写 10000 份 YAML 不可行 | 已提供 `sp ingest scan`、`sp ingest build-requests` 和 `sp package create-many`。扫描和请求生成是批量入口，人工只审阅规则和异常项。 |
| 一个 `.mcs` 多病例能否减少启动成本 | 阶段 A 不采用。单 `.mcs` 多病例会放大项目损坏、Mask 误绑定、部分提交、多人分派和失败回滚的风险。当前选择一个 review/case 一个 `.mcs`，用批量发现和批量创建降低平台侧成本。 |
| prepare/open/finalize 是否仍需逐病例 | 已提供 `sp mimics prepare-many`、`sp mimics finalize-many` 和 `sp review stats`。标注者不直接运行 `open`，而是在 Mimics 内通过 **SP Review Console** 领取下一例。 |
| Registry 标签查询 O(N) | 文件式 Registry 已维护 `_indexes/labels_by_case_image_organ.json`。旧 Registry 可运行 `sp registry rebuild-index /data/platform_registry` 生成索引。 |
| 空间信息不完整 | 数据导入契约允许 `complete/partial/index_only`，但 Mimics 病例包当前仍要求可控的工具空间。纯 RAW 和无法证明空间的来源应先创建带明确假设的派生图像，或停在导入报告中。 |
| 部分器官标签 | Snapshot 支持按病例列出实际 segment 子集。不能把未标器官当背景；训练导出层后续要显式实现 ignore/排除策略。 |

## 13. 验证命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests adapters/mimics
.venv/bin/python -m pip check
```

自动测试覆盖合成 DICOM、候选标签、病例包、Registry、Mimics buffer 准备、模拟提交、Label Artifact 和 Dataset Snapshot。真实 Mimics API、许可、界面行为和空间往返只能在 Mimics 21 工作站验收。
