# 训练前标注闭环实现与运行指南

> 版本：v0.1  
> 日期：2026-06-15  
> 适用范围：离线阶段 A，结束于不可变 Dataset Snapshot，不包含 nnUNet 导出和训练  
> Mimics：以 Mimics Research 21.0 API 为实现依据，真实工作站 Gate A/B/C 仍需执行

## 1. 已经实现到哪里

当前代码已经可以在外部现代 Python 环境中完成：

1. 检查 DICOM、NIfTI 和可选 MetaImage 图像的格式、哈希与三维空间。
2. 从请求文件创建 Case Package v0.5。
3. 把 Case、Image Artifact、初始 Label Artifact 和 Review Task 写入文件式 Registry。
4. 把已有逐器官或多标签文件拆成逐器官 NIfTI。
5. 为 Mimics 21 生成运行清单和逐器官 `.u8` 体素缓冲区。
6. 启动 Mimics，并在 Mimics 内创建、绑定、恢复和导出受平台管理的 Mask。
7. 区分保存进度、提交完成、提交复查和报告阻塞。
8. 在外部环境回收 Mask，执行身份、基础版本、哈希、shape、轴映射、空 Mask 和空间检查。
9. 追加创建 `verified_label` 或 `draft_label`，不覆盖旧版本。
10. 从 Registry 选择明确标签版本，检查患者级 split 泄漏，创建不可变 Dataset Snapshot。

没有宣称已经完成的部分：

- 当前机器不是 Mimics 21 Windows 工作站，因此 P01-P14 尚未产生真实证据。
- `buffer_mapping.status=verified` 必须来自 P05 实测，不能照抄示例值。
- 未校准时可以创建空 Mask 从零标注，但不能导入已有 Mask，也不能把导出缓冲区转换为正式标签。
- RAW 图像没有可靠 sidecar 时仍然阻断；MetaImage 需要安装可选依赖。
- 本阶段没有 Web UI、在线锁、队列、权限系统或多人实时协同。

## 2. 端到端流程走查

下面沿完整的标注链路走一遍，每一步说明做什么、产出什么、怎么验证。涉及三个角色：平台操作者（运行命令）、标注者（只在 Mimics 内操作）、平台脚本（自动执行）。

### 阶段 1：一次性工作站配置

**谁做**：平台操作者，在每台 Mimics 21 工作站上执行一次。

**目标**：确认这台机器能可靠地导入平台 DICOM、操作 Mask 并原样导出。

**步骤**：

1. 安装 Mimics Research 21.0，确认许可含 Scripting 模块。在 `File → Preferences → Scripting` 中配置 Python 3.5.2。
2. 把 `adapters/mimics/runtime_py35/` 设为 Scripting Library。
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

```bash
sp package create examples/labeling/case_package_request.yaml /data/dataset_package --registry /data/platform_registry
```

**这个命令做的事**：

- 从 DICOM 区读取图像 → 按患者 → 检查 → 序列分组 → 为每个序列创建 `image_id`
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

### 阶段 3：为 Mimics 准备并启动任务

**谁做**：平台操作者。

**目标**：把病例包中的数据转成 Mimics 能理解的格式，生成任务说明书，启动 Mimics。

```bash
sp mimics prepare /data/dataset_package/cases/case_001 --config mimics_workstation.yaml
sp mimics open /data/dataset_package/cases/case_001 --config mimics_workstation.yaml --registry /data/platform_registry
```

**`prepare` 做的事**：

- 再次校验病例包
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

**`open` 做的事**：

- 启动 Mimics，通过 `-run_script` 调用 `sp_open_review.py`
- `sp_open_review.py` 在 Mimics 内部执行：导入 DICOM → 用 UID 哈希 + shape 将 image set 与 `image_id` 一一匹配 → 为每个 target 的每个器官创建/找到 Mask → 写入 7 个 metadata（review_id、target_id、image_id、organ、base_label_id/hash、package_root）→ 如有 import buffer 则在首次创建时注入 → 保存 `.mcs` → 弹出任务摘要对话框

**验证方式**：

- `prepare` 后检查 `working/mimics_runtime.json` 和 `working/bridge/import/` 是否有内容
- `open` 后 Mimics 弹窗显示任务摘要（病例号、序列数、目标器官列表）
- Registry 中 Review 状态更新为 `in_progress`
- 报告写入 `reports/mimics_open_report.json`

---

### 阶段 4：标注者工作

**谁做**：标注者。只在 Mimics 里操作，不碰命令行。

**标注者看到的流程**：

1. Mimics 自动打开，弹窗显示任务摘要。**核对**：病例是否正确、有哪些序列、每个序列要标哪些器官。
2. 如不一致 → 直接 `Script → SP - Submit Review → 报告阻塞`，不编辑。
3. 如一致 → 使用 Mimics 正常工具编辑每个 Mask。每个 Mask 的名称、metadata 由平台管理，标注者不改。
4. 随时 Ctrl+S 保存 `.mcs`。保存只保留进度，不触发提交。
5. 长时间工作后可选运行 `Script → SP - Save Checkpoint`，额外保存一份独立于 `.mcs` 的 Mask 恢复快照。
6. 关闭软件后，下次仍通过平台操作者运行 `sp mimics open` 继续。

**标注者不需要知道的事**：标签生命周期、文件哈希、NIfTI 格式、训练编号、Registry 路径。

---

### 阶段 5：提交

**谁做**：标注者触发，Mimics 内部脚本执行导出。

**标注者的操作**：

1. `Script → Scripting Library → SP - Submit Review`
2. 第一个对话框：选择提交意图 — **提交完成 / 提交复查 / 报告阻塞 / 取消**
3. 第二个对话框：选择要提交的目标组 — 一个、多个（2–5 个时模拟勾选）或全部
4. 如有空 Mask，弹出聚合清单 — 可统一选择"全部确认不存在""全部待复查"或逐项判断
5. 等待脚本提示 "已导出，仍需平台检查"

**脚本在后台做的事**（`sp_submit_review.py`）：

- **提交完成**：检查所有 Mask 存在且绑定正确 → 空 Mask 确认语义 → `get_voxel_buffer()` 导出每个 Mask 为 `.u8` → 写入 `submissions/{review_id}/buffers/` → 生成 `export_manifest.json` 和 `submission_manifest.json`（action=submit_complete）→ 保存 `.mcs` → 弹窗提示
- **提交复查**：同提交完成，action=submit_for_review，记录不确定原因
- **报告阻塞**：不要求所有 Mask 完成，写入阻塞类型和原因

**验证方式**：检查 `submissions/{review_id}/` 下是否出现了 `submission_manifest.json`、`export_manifest.json` 和 `buffers/` 中的 `.u8` 文件。

---

### 阶段 6：平台收尾

**谁做**：平台操作者。

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
  sp mimics prepare → mimics_runtime.json + import buffers
  sp mimics open → 启动 Mimics + 创建/恢复 Mask + 注入初始标签
         │
[标注者] 在 Mimics 中编辑 Mask → 随时保存 .mcs → 可选 Save Checkpoint
         │
[标注者] SP - Submit Review → 选意图 → 选目标组 → 确认空 Mask → 导出 .u8
         │
[平台操作者]
  sp mimics finalize → 身份/完整/哈希/几何 QC
                    → 通过：verified_label
                    → 失败：review_report.json + 回到 in_progress
```

---

## 3. 代码位置

| 位置 | 作用 |
| --- | --- |
| `src/segplatform/cli.py` | `sp` 命令入口 |
| `src/segplatform/imaging.py` | DICOM/NIfTI/MetaImage 几何、Mask 读写和轴映射 |
| `src/segplatform/case_packages.py` | 病例包创建、初始标签拆分和登记 |
| `src/segplatform/registry.py` | 文件式 Registry 的不可变写入和查询 |
| `src/segplatform/snapshots.py` | 标签准入、split 检查和 Snapshot 冻结 |
| `src/segplatform/adapters/mimics/` | Mimics 外部现代 Python 侧 |
| `adapters/mimics/runtime_py35/` | Mimics 内 Python 3.5.2 打开、checkpoint 和提交脚本 |
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

Mimics 内置 Python 不安装 nibabel、pydicom 或 SimpleITK。它只运行 `runtime_py35/` 中的脚本。

## 5. 准备病例包

先复制并修改 [病例包请求示例](../../../examples/labeling/case_package_request.yaml)。每个 `image_set` 必须只指向一个 DICOM Series；包含多个 SeriesInstanceUID 的目录会被阻断。

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
3. 把 `adapters/mimics/runtime_py35/` 配置为 Scripting Library。
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

平台操作者先执行：

```powershell
sp mimics prepare D:\dataset_package\cases\case_001 `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml

sp mimics open D:\dataset_package\cases\case_001 `
  --config C:\SegmentationPlatform\config\mimics_workstation.yaml `
  --registry D:\platform_registry
```

`prepare` 完成：

- 再次检查病例包。
- 生成 `working/mimics_runtime.json`。
- 有初始标签时生成 `working/bridge/import/{image_id}/{organ}.u8`。
- 未通过 P05 时阻止已有标签注入。

同一图像的初始逐器官 Mask 会登记成一份多 segment Label Artifact。若一个目标组的全部器官都来自该 Artifact，病例包会自动把它设为目标组的基础标签，后续提交必须回传相同 ID 和 bundle hash。

`open` 启动 `sp_open_review.py`。内部脚本完成：

- 首次任务导入 DICOM；继续任务打开专属 `.mcs`。
- 使用 Series UID 哈希和 shape 唯一匹配 image set。
- 每次操作目标前显式 `set_active()`。
- 每个目标器官建立一个 Mask。
- 写入 `review_id/target_id/image_id/organ/base_label` metadata。
- 继续任务时先核对已有 Mask 的 `base_label_id + bundle hash`，不一致即阻断。
- 只在首次创建 Mask 时注入初始缓冲区。
- `.mcs` 不可用且选择重建时，优先恢复匹配当前任务版本和 mapping evidence 的 checkpoint。
- 保存任务专属 `.mcs` 并显示一次摘要。

外部启动成功后，Registry 中该 Review 和尚未开始的目标组会更新为 `in_progress`，并追加 `open_started` 事件。没有提供 `--registry` 时仍可打开，但不会更新集中进度。

标注者只执行：

1. 核对病例、序列和目标器官。
2. 使用 Mimics 正常工具编辑 Mask。
3. 可随时保存 `.mcs` 并关闭。
4. 长时间工作后可运行 `SP - Save Checkpoint` 保存独立 Mask 恢复快照。
5. 完成时运行 `Script -> Scripting Library -> SP - Submit Review`。
6. 选择完成、复查、阻塞或取消；2–5 个目标组可勾选任意组合一次提交。

保存 `.mcs` 不会创建正式标签。提交脚本也只写出缓冲区和提交意图。
提交前会聚合检查 Mask 完整性、image set、基础版本和 shape。多个空 Mask 可统一确认，
也可以逐项判断。

## 9. 平台收尾

Mimics 导出后执行：

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

快照写入后不可覆盖：

```bash
sp snapshot validate /data/platform_registry/snapshots/snap_abdomen_v1.json
```

到这里训练前闭环结束。后续 nnUNet Adapter 只能读取已冻结的 Snapshot。

## 11. 异常和恢复

| 情况 | 处理 |
| --- | --- |
| Mimics 打开失败 | 查看 `reports/mimics_open_error.json`，修复后重新 `open` |
| 标注中断 | 保存 `.mcs`，以后仍通过 `sp mimics open` 继续 |
| Mask 错序列 | 提交脚本阻断；不要手工改 header |
| Mimics 提交前检查失败 | 查看弹窗和 `reports/mimics_submit_precheck.json` |
| 提交 QC 失败 | 查看 `reports/review_report.json`；下次 open 会显示失败摘要 |
| 已验证标签要修改 | 新建 `review_id`，旧标签作为 base label，不覆盖旧版本 |
| 多标注者 | 每人独立 `review_id` 和 `.mcs`；阶段 A 不共享写同一文件 |
| `.mcs` 损坏 | 运行 `prepare --rebuild-workspace` 保留旧文件，并从最新 checkpoint 或初始标签重建 |

## 12. 验证命令

```bash
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q src tests adapters/mimics
.venv/bin/python -m pip check
```

自动测试覆盖合成 DICOM、候选标签、病例包、Registry、Mimics buffer 准备、模拟提交、Label Artifact 和 Dataset Snapshot。真实 Mimics API、许可、界面行为和空间往返只能在 Mimics 21 工作站验收。
