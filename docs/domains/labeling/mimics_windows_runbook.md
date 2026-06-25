# Mimics Research 21 Windows 工作站操作手册

> 病例包版本：v0.5。  
> 状态：代码已准备并通过本地自动化测试；Mimics 21 的实际 API 与空间映射证据由 Windows 工作站运行后生成。  
> 目标：平台准备机完成探针、数据准备、分发和收尾；标注机只安装 Mimics，并运行工作包自带的语义化 `Labeling_*.py` 入口。

## 快速部署清单

以下是一次完整标注批次的端到端步骤。每步的详细说明和故障处理见后续各节。

### 角色分工

| 角色 | 机器上需要什么 | 做什么 |
|------|--------------|--------|
| 平台操作者 | 项目仓库 + Python 3.10+ + Mimics 21 + Registry | 探针校准、数据摄入、病例包创建、工作包导出、提交回收、QC 收尾 |
| 标注者 | 仅 Mimics Research 21 | 接收工作包 → 设 Scripting Library → 编辑 Mask → 提交 |

### 平台操作者：一次性准备

```powershell
# 工作站验收
.\scripts\windows\setup_mimics_workstation.ps1 `
  -MimicsExecutable "C:\Program Files\Materialise\Mimics Research 21.0\MimicsResearch.exe"

# 探针校准 → 生成 verified 配置
.\scripts\windows\invoke_mimics_case.ps1 -Action Doctor -ConfigPath ".\config\mimics_workstation.local.yaml"
.\scripts\windows\invoke_mimics_case.ps1 -Action ProbeRun -ConfigPath ".\config\mimics_workstation.local.yaml" -CaseRoot "D:\cases\pkg_probe"
.\scripts\windows\invoke_mimics_case.ps1 -Action ProbeEvaluate ... -OutputConfigPath ".\config\mimics_workstation.verified.yaml"

# 安装 nnInteractive 环境（如需 AI 辅助标注，只需做一次，~5 GB）
python scripts\setup_nninteractive_env.py --cuda cu124 --device cuda:0
```

### 平台操作者：每批标注任务

```powershell
# 1. 数据摄入 → 生成病例包请求
sp ingest plan D:\data\source D:\requests `
  --organs liver spleen kidney_left kidney_right `
  --import-batch batch_001

# 2. 创建病例包 + 写入 Registry
sp package create-many D:\requests D:\dataset_package `
  --registry D:\platform_registry `
  --continue-on-error

# 3. 为 Mimics 准备（生成 runtime + import buffer）
sp mimics prepare-many D:\dataset_package\cases `
  --config .\config\mimics_workstation.verified.yaml `
  --continue-on-error

# 4. 可选：后台预生成 .mcs（减少标注者首次等待）
sp mimics prebuild-many D:\dataset_package\cases `
  --config .\config\mimics_workstation.verified.yaml `
  --continue-on-error

# 5. 导出可移动工作包
sp review export-worklist `
  --registry D:\platform_registry `
  --output-root D:\transfer\batch_001 `
  --limit 30
```

`export-worklist` 自动把六个 `Labeling_*.py` 标注脚本、`runtime_py35\` 内部脚本和病例包一并复制到输出目录。如果仓库中已准备好 nnInteractive 脚本，`nnInteractive.py` 和 `nninteractive_bridge.py` 也会自动包含。

### 标注者：一次性配置

标注者收到的 `batch_001\` 目录，复制到本机任意位置（如 `D:\MyWork\`）。

**如果包含 nnInteractive**：平台操作者需额外把离线 bundle 解压到工作包的父目录：

```text
D:\MyWork\
  nninteractive_env\          ← 离线 bundle（平台操作者提供，只需一次）
    python\
    models\
  batch_001\                  ← 工作包
    Labeling_Open_Next_Case.py
    nnInteractive.py
    runtime_py35\
    cases\
    worklist_manifest.json
```

标注者只需做一件事：Mimics → `File → Preferences → Scripting → Scripting Library` → 指向 `D:\MyWork\batch_001\`。

`Script → Scripting Library` 中出现 7 个入口：

| 入口 | 时机 |
|------|------|
| `Labeling_Open_Next_Case` | 打开下一个待处理病例（高频） |
| `Labeling_Case_Navigation` | 继续上次、选择或跳过病例 |
| `Labeling_Submit_Complete` | 标注完成，直接提交（高频） |
| `Labeling_Submit_or_Report_Issue` | 需要复查或报告数据问题 |
| `Labeling_View_Task_List` | 忘记任务范围时查看 |
| `Labeling_Save_Recovery_Backup` | 长时间工作后保存灾备快照 |
| `nnInteractive` | AI 辅助分割 |

### 标注者：日常工作

1. 打开 Mimics → `Labeling_Open_Next_Case` → 核对任务摘要 → 编辑 Mask
2. 随时 Ctrl+S 保存 `.mcs`（保存进度 ≠ 提交）
3. 完成一段器官后可选 `Labeling_Save_Recovery_Backup`
4. 完成整个病例后 `Labeling_Submit_Complete`
5. 不确定时 `Labeling_Submit_or_Report_Issue` → Needs Review
6. 数据/工具问题时 `Labeling_Submit_or_Report_Issue` → Report Problem
7. 当前病例暂不处理时 `Labeling_Case_Navigation` → Skip Case
8. AI 辅助：选中目标 Mask → `nnInteractive` → Point/Scribble/Box/Lasso → Finish

### 平台操作者：回收和收尾

标注者完成后，把工作包目录拷回。平台操作者：

```powershell
# 1. 收集提交 → 复制到中央病例包
sp mimics collect-submissions D:\returned\batch_001\cases `
  D:\dataset_package\cases `
  --registry D:\platform_registry `
  --overwrite

# 2. 批量 QC + 登记 Label Artifact
sp mimics finalize-many D:\dataset_package\cases `
  --config .\config\mimics_workstation.verified.yaml `
  --registry D:\platform_registry `
  --continue-on-error

# 3. 查看进度
sp review stats --registry D:\platform_registry
```

### 需求变化

**追加器官**（已标完 liver+spleen，要加 kidney）：

```powershell
sp review create-followup `
  --registry D:\platform_registry `
  --output-root D:\dataset_package `
  --case-id case_001 `
  --organs kidney_left kidney_right `
  --review-suffix add_kidney
```

已完成工作不丢失；标注者打开新 review 时看到 liver+spleen 已存在，只需标 kidney。

**数据集增长**（50 例基础上新增 20 例）：重新 `ingest plan → package create-many → export-worklist`，新例生成独立增量工作包。

**只分发部分**：`--limit 30`。**重发已分发的**：`--include-distributed`。

---

## 1. 运行边界

标注闭环使用两个相互隔离的 Python 环境：

| 环境 | 负责内容 | 操作者如何使用 |
| --- | --- | --- |
| 平台 Python 3.10+ | Case Package、Registry、几何校验、buffer 转换、最终 NIfTI 和标签登记 | 只在平台准备/QC 机器通过 `sp` 命令运行 |
| Mimics 21 内置 Python 3.5 | DICOM 导入、`.mcs`、Mask 创建与编辑、Mask buffer 导出、交互弹窗 | 由 Mimics `-run_script` 或软件内脚本入口运行 |

Mimics 内置 Python 不负责读取 NIfTI、维护 Registry 或安装现代第三方依赖。标注者也不需要手工执行数据格式转换。

## 2. 平台准备机需要什么

1. Windows 10/11 机器。
2. Mimics Research 21 和可用许可证。
3. Mimics Scripting 模块。
4. 64 位 Python 3.10 或 3.11。
5. 本项目完整仓库。
6. 至少一个已经生成的 Case Package。
7. Case Package；主 Registry 可以保留在平台机器。

建议目录：

```text
C:\SegmentationPlatform\                 项目仓库
D:\SegmentationPlatform\work\            工作站报告和诊断输出
D:\SegmentationPlatform\data\packages\   Case Package
D:\SegmentationPlatform\data\registry\   Registry
```

Case Package 可以在其他机器生成后整体复制到 Windows。推荐把主 Registry 留在平台机器，避免多份 Registry 分叉。

标注机只需要第 1-3 项，不需要 Python、项目仓库或 Registry。

## 3. 平台准备机一次性初始化

以 PowerShell 打开项目目录：

```powershell
Set-ExecutionPolicy -Scope Process Bypass

.\scripts\windows\setup_mimics_workstation.ps1 `
  -MimicsExecutable "C:\Program Files\Materialise\Mimics Research 21.0\MimicsResearch.exe" `
  -WorkRoot "D:\SegmentationPlatform\work"
```

脚本会创建项目专用 `.venv`、安装平台依赖并生成 `config\mimics_workstation.local.yaml`。它只用于平台准备/QC 机器，不在标注机执行。

如果机器使用其他 Python：

```powershell
.\scripts\windows\setup_mimics_workstation.ps1 `
  -PythonCommand "C:\Python310\python.exe" `
  -PythonSelector "" `
  -MimicsExecutable "C:\Path\To\MimicsResearch.exe"
```

配置文件是工作站本地文件，不应提交到 Git。它记录软件路径和该工作站通过探针确认的 buffer 映射。

## 4. 检查 Mimics API

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Doctor `
  -ConfigPath ".\config\mimics_workstation.local.yaml"
```

该命令检查 Mimics 版本、内置 Python、NumPy，以及 DICOM 导入、项目打开/关闭/保存、active image、Mask 创建和弹窗 API。

结果写入工作站配置中的 `work_root`：

```text
mimics_doctor_report.json
mimics_diagnostics.json
mimics_diagnostics.log
```

`status=ready` 才继续。失败时先查看 JSON 中具体失败的 API，不要修改适配器绕过检查。

## 5. 一次性空间映射探针

空间映射是工作站级验收，不需要对每个病例重复执行。选择一个矩阵三轴长度不同、方向信息完整的 DICOM Case Package。

### 5.1 在 Mimics 中运行完整探针

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action ProbeRun `
  -ConfigPath ".\config\mimics_workstation.local.yaml" `
  -CaseRoot "D:\SegmentationPlatform\data\packages\pkg_probe"
```

单次 Mimics 会话会完成：

| 探针 | 验证内容 |
| --- | --- |
| P01 | DICOM 导入后形成的 image set 及 Series UID |
| P02 | Mask 与 image set 的绑定在 `.mcs` 保存、关闭、重开后是否保持 |
| P04 | 非对称体素写入和原始 buffer 导出 |
| P05 | Mimics voxel index 到患者物理坐标的对应关系 |
| P06 | 按 review、target、organ 精确选择并导出一个 Mask |

结果默认位于 `<CaseRoot>\reports\mimics_probe\`。其中
`mimics_probe_evidence.json` 是平台评估输入，`sp_probe_suite.mcs` 用于人工复查。
看到探针完成弹窗后关闭该 Mimics 进程，PowerShell 命令才会取得最终退出码。

### 5.2 生成带验证映射的配置

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action ProbeEvaluate `
  -ConfigPath ".\config\mimics_workstation.local.yaml" `
  -CaseRoot "D:\SegmentationPlatform\data\packages\pkg_probe" `
  -EvidencePath "D:\SegmentationPlatform\data\packages\pkg_probe\reports\mimics_probe\mimics_probe_evidence.json" `
  -OutputConfigPath ".\config\mimics_workstation.verified.yaml"
```

平台会枚举轴排列和翻转组合，将 Mimics P05 坐标与 Case Package 的 DICOM LPS 几何比较。只有以下条件全部满足时，输出配置才会写为 `status: verified`：

- P01/P02/P04/P05/P06 完整；
- Series UID 唯一匹配；
- Mask 绑定和选择性导出通过；
- 空间映射候选唯一；
- 最大物理坐标误差不超过默认 `0.001 mm`。

评估失败时，输出配置仍保持 `unverified`，正式导入初始 mask 和最终导出都会被阻止。之后的正式病例统一使用 `config\mimics_workstation.verified.yaml`。

Mimics 版本、安装构建、插件或工作站发生变化后应重新运行探针。

## 6. 单个病例的标注流程

以下路径仅为示例：

```powershell
$Config = ".\config\mimics_workstation.verified.yaml"
$Case = "D:\SegmentationPlatform\data\packages\pkg_case_001"
$Registry = "D:\SegmentationPlatform\data\registry"
```

### 6.1 平台准备病例

平台必须在导出工作包前完成 prepare：

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Prepare `
  -ConfigPath $Config `
  -CaseRoot $Case
```

批量准备一批 Case Package 时优先用平台命令：

```powershell
sp mimics prepare-many D:\SegmentationPlatform\data\packages\cases `
  --config $Config `
  --continue-on-error
```

平台会校验 Case Package，将已有初始标签转换成 Mimics `.u8` buffer，生成
`working\mimics_runtime.json`，并在发现既有 `.mcs` 时切换为继续标注模式。

工作站通过 Mimics Gate 后，可在标注者领取前预生成 `.mcs`：

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Prebuild `
  -ConfigPath $Config `
  -CaseRoot $Case

sp mimics prebuild-many D:\SegmentationPlatform\data\packages\cases `
  --config $Config `
  --continue-on-error
```

`prebuild` 会启动 Mimics `-background_mode`，调用内部 `sp_open_review.py --background-prebuild`，导入 DICOM、创建受管 Mask、注入初始 buffer、保存 `.mcs`，并写入 `working\prebuilt_workspace.json`。它是减少首次打开等待的可选加速，不是工作包导出的硬前提。没有 `.mcs` 时，标注机首次打开会在 Mimics 内完成同样的导入和创建流程。重复运行时，已有预生成 marker 的任务返回 `already_prebuilt`；已有普通 `.mcs` 的任务返回 `already_exists`。

### 6.2 打开 Mimics

正式标注时，建议把工作包根目录设为 Scripting Library。标注者也可以使用 `Script -> Run Script` 直接选择 `Labeling_*.py`。这些入口只读取工作包，不连接 Registry、不调用外部 Python、不认领任务。

`invoke_mimics_case.ps1 -Action Open` 只作为管理员调试入口保留，不作为标注者日常步骤。

Mimics 启动后会自动：

- 首次打开时导入 DICOM，或直接打开/重新打开 `working\<review_id>.mcs`；
- 按 Series UID 和形状匹配 image set；
- 显式设置当前 active image；
- 创建每个目标器官对应的 Mask；
- 仅在首次创建时导入初始 mask；
- 写入 review、target、image、organ 和 base label 元数据；
- 保存 `.mcs`。

打开失败时不会生成 verified label。查看 `reports\mimics_open_error.json` 和 `reports\mimics_open.log`。

### 6.3 标注者在 Mimics 中工作

标注者只需要：

1. 打开 Mimics。
2. 默认运行 `Labeling_Open_Next_Case.py`；需要继续、选择或跳过时运行 `Labeling_Case_Navigation.py`。
3. 核对病例、序列数量、目标器官统计和初始 Mask。
4. 使用 Mimics 工具修正对应的 `SP__<target_id>__<organ>` Mask。
5. 随时保存 `.mcs`，关闭 Mimics 后可以继续。
6. 忘记任务范围时运行 `Labeling_View_Task_List.py`。
7. 长时间工作后运行 `Labeling_Save_Recovery_Backup.py`。
8. 当前病例暂时不处理时，在 `Labeling_Case_Navigation.py` 中选择 Skip Case。
9. 不修改以 `sp.` 开头的 Mask metadata。
10. 不把 Mask 移到另一个 image set。

保存 `.mcs` 只代表保存进度，不代表标签已经提交或验证。

### 6.4 在当前 Mimics 会话提交

完成时直接运行 `Labeling_Submit_Complete.py`。需要复查或遇到阻塞时运行 `Labeling_Submit_or_Report_Issue.py`，再在两个异常结果中选择。

| 动作 | 平台语义 |
| --- | --- |
| Complete | 标注者认为所选 target 已完成，等待平台 QC |
| Needs Review | 已保存并导出，但存在医学不确定、图像质量或上下文不足 |
| Report Problem | 数据、图像集或工具问题导致无法继续 |
| Cancel | 不提交，继续保留 `.mcs` 当前进度 |

Case Navigation 中的 Skip Case 只保存并关闭当前 `.mcs`，在本地进度中标记为暂缓并打开下一例；不会改变中央 Review。不要用 Report Problem 表示“先放一边”。

当任务包含 2–5 个 target 时，脚本允许逐个勾选后一次提交任意组合。提交前会聚合检查 Mask
完整性、image set、基础版本和 shape；检查失败时直接显示主要问题，并写入
`reports\mimics_submit_precheck.json`。

最常见路径是单 target、无空 Mask 时直接运行 `Labeling_Submit_Complete.py`：只执行导出并显示完成提示。

空 Mask 必须明确选择：

- 多个空 Mask 先显示数量和前若干项，完整清单写入 `reports\mimics_empty_masks.txt`；
- 可以统一选择全部 `Confirmed Absent` 或全部 `Needs Review`；
- 情况不一致时选择逐项判断；
- 取消不会写提交。

不要在打开病例前根据扫描部位猜测器官不存在。病例包里的 `organs` 是本次任务清单；
`confirmed_absent`、`Needs Review` 和 `Report Problem` 才是打开病例后对具体器官作出的结果。

脚本会保存 `.mcs`，并在 `submissions\<review_id>\` 下写入：

```text
submission_manifest.json
export_manifest.json
buffers\<image_id>\<target_id>\<organ>.u8
```

此时仍未生成最终标签。

提交写入使用 staging 目录；如果 Mimics 在导出中途崩溃，半成品不会进入正式 `submissions\<review_id>\`，下一次提交会自动清理旧 `.partial_*`。

### 6.5 把提交带回平台机器

Mimics 提交清单中的 buffer 路径相对 Case Package 保存，因此提交目录可以从工作站收回到中央病例包。无共享盘时，推荐先收集提交：

```powershell
sp mimics collect-submissions D:\returned\cases `
  D:\SegmentationPlatform\data\packages\cases `
  --registry D:\SegmentationPlatform\data\registry `
  --overwrite
```

复制完成后可抽查病例包：

```powershell
sp package validate D:\SegmentationPlatform\data\packages\cases\case_001
```

不要只复制 `.mcs` 或单个 `.u8`。最低限度也必须收回 `submissions\<review_id>\submission_manifest.json`、`export_manifest.json` 和 `buffers\`。`collect-submissions` 会把这些内容放回中央病例包对应位置；`working\` 和 `.mcs` 默认不收回，除非管理员需要灾备或调试。

### 6.6 平台完成 QC 和标签登记

```powershell
sp mimics finalize D:\returned\pkg_case_001 `
  --config .\config\mimics_workstation.verified.yaml `
  --registry D:\SegmentationPlatform\data\registry
```

批量处理多个已提交病例时使用：

```powershell
sp mimics finalize-many D:\returned\cases `
  --config .\config\mimics_workstation.verified.yaml `
  --registry D:\SegmentationPlatform\data\registry `
  --continue-on-error
```

该命令应在持有主 Registry 的平台机器执行。verified 配置中的 Windows 可执行文件路径此时不会被调用，Finalize 只使用其中已经冻结的 buffer mapping。

不同标注者可以分别返回、分别 collect、分别 finalize。无需等所有标注者完成后再统一处理；中央 Registry 会追加通过 QC 的 Label Artifact，失败项只影响对应 review。

平台会检查 review、target、base label、相对路径边界、buffer hash 和尺寸、空间映射、图像和器官对应关系、空 Mask outcome，以及最终 NIfTI 的物理几何。只有 Review 显式启用 `enforce_assignee=true` 时才检查 assignee。

| 提交动作 | 标签状态 | Review 状态 |
| --- | --- | --- |
| Complete 且 QC 通过 | `verified_label` | `completed` |
| Needs Review 且 QC 通过 | `draft_label` | `needs_review` |
| Report Problem | 不生成标签 | `blocked` |
| QC 失败 | 不生成标签 | 返回 `in_progress` |

QC 报告位于 `reports\review_<review_id>_finalize.json`。

如果提交基于旧 `base_label_id` 且 **Complete** 通过，平台会 carry-forward base 中未重标的器官，并把旧 base Label Artifact 标记为 `superseded`。因此追加 kidney 不会丢弃已经完成的 liver/spleen。

### 6.7 查看进度

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Status `
  -ConfigPath $Config `
  -RegistryRoot $Registry
```

增加 `-ReviewId "review_case_001_v1"` 可查看单个 review。

管理员也可以直接查看队列聚合统计：

```powershell
sp review stats --registry $Registry
```

## 7. 继续修改已经提交的标签

`verified_label` 不会被覆盖写。需要继续修正时：

1. 平台创建新的 review 版本和新 Case Package，旧 verified label 作为 `base_label_id`。
2. 平台必须执行 `Prepare`，并可选执行 `Prebuild`。
3. Mimics 首次创建新 review 的 Mask 时导入旧标签。
4. 标注者通过对应的打开和提交入口修正并重新提交。
5. Finalize 生成新的 Label Artifact，并保留旧版本和父子来源关系。

命令示例：

```powershell
sp review create-followup `
  --registry D:\SegmentationPlatform\data\registry `
  --output-root D:\SegmentationPlatform\data\packages `
  --case-id case_001 `
  --organs liver `
  --review-suffix relabel_liver `
  --assignee annotator_01
```

追加器官也用同一命令，例如 `--organs kidney_left kidney_right --review-suffix add_kidney`。不要用 `package create --overwrite` 重建原病例包。

不要直接修改旧 Case Package 后覆盖 Registry 中已经登记的标签。

## 8. `.mcs` 损坏时恢复

`Labeling_Save_Recovery_Backup.py` 会把全部受管 Mask 保存为 gzip 压缩的 `.u8.gz`：

```text
working\checkpoints\<review_id>\<timestamp>\
```

Mimics 21 文档没有提供可依赖的“每次保存项目后自动回调脚本”接口，因此 recovery backup 是显式
灾备动作，不会在每次 Ctrl+S 后自动执行。默认只保留最新 3 份；平台可在 `worklist_manifest.json` 中统一调整 `checkpoint_keep_count`。

如果 `.mcs` 无法打开：

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Prepare `
  -ConfigPath $Config `
  -CaseRoot $Case `
  -RebuildWorkspace
```

平台会把旧 `.mcs` 改名保留，然后验证 recovery backup 的 review、package、base label、mapping
evidence、shape 和 hash。通过后，标注者下一次通过 Console 打开任务时会重新导入 DICOM 并恢复 recovery backup；没有可用
recovery backup 时退回初始标签或空 Mask。

## 9. 多标注者使用

中央 Registry 不进入标注机。并行标注遵守：

1. 同一个可写工作包副本同一时刻只由一个标注者写入。
2. 不同标注者使用不同工作包副本，可以并行工作。
3. 同一病例需要双人独立标注时，导出两个独立 review/工作包。
4. 标注结果回收时返回工作包或完整 `cases\*\submissions\`，不只复制 `.mcs` 或单个 `.u8`。

同一病例需要双人独立标注时，创建两个 review 和两个工作目录，最终另行比较或仲裁，不在同一 `.mcs` 中混合。

### 9.1 导出可移动工作包

中央机可以按中央 assignee 筛选，也可以不指定 assignee，直接导出一批可自由处理的病例：

```powershell
sp review export-worklist `
  --registry D:\SegmentationPlatform\data\registry `
  --output-root D:\transfer\batch_001_worklist `
  --limit 30 `
  --overwrite
```

工作包可复制到任意盘符，平台不需要知道最终路径。目录包含：

- `Labeling_*.py`：打开、提交、查看、跳过和恢复备份的直接入口；
- `nnInteractive.py`：AI 交互分割工具（若仓库中已准备好 nnInteractive 脚本，导出时自动包含）；
- `runtime_py35\`：Mimics 内部脚本（标注与 AI 工具共用）；
- `cases\`：病例包和预生成 `.mcs`；
- `nninteractive_bridge.py`：AI 工具的外部推理桥接（若可用，与 `nnInteractive.py` 同时出现）；
- `worklist_manifest.json`：平台冻结的相对路径清单；
- `worklist_progress.json`：可重建的本地进度，不是配置或 Registry。

标注者可以任选病例、跳过、继续或重新打开已提交病例。标注完成后，把工作包拷回中央机，运行 `sp mimics collect-submissions` 和 `sp mimics finalize-many`。

中央 Registry 只记录 review 被导出到哪个 `worklist_id`，以防下一批再次拿到同一 review；它不知道工作包在标注机上的路径，也不接收标注过程中的实时进度。工作包丢失需要重发时显式加 `--include-distributed`。双人独立标注应创建两个 review，不应把同一个可写 review 复制给两个人。

标注中新增病例时，默认导出一个新的增量工作包。平台无法也不应远程修改已经复制到标注机的目录：

```powershell
sp review export-worklist `
  --registry D:\SegmentationPlatform\data\registry `
  --output-root D:\transfer\batch_002_increment
```

`--merge` 只适用于平台仍持有同一个 staging 工作包、尚未重新分发的情况。`--assignee annotator_01` 仍可作为中央筛选条件，但不会在标注机形成身份或路径依赖。Skip 只修改本地 `worklist_progress.json`，不改变中央 Review。

## 10. Windows 与其他机器之间传输什么

送往标注机：仅 `sp review export-worklist` 生成的完整工作包。

从 Windows 带回：

- 离线模式：返回工作包中的 `cases\*\submissions\` 和 `reports\`，由 `sp mimics collect-submissions` 收回中央病例包；
- probe evidence 和 verified 配置留在平台准备机。

平台机器运行 Finalize 后，最终 `labels/` 和更新后的 Registry 留在平台侧。标注机不运行 Finalize。

`.mcs` 是 Mimics 的工作状态文件，便于继续标注，但它不是平台标签、QC 报告或 Registry 的替代品。

## 11. 常见故障

| 现象 | 处理 |
| --- | --- |
| Doctor 报 API 缺失 | 核对 Mimics 版本、Research edition 和 Scripting 模块 |
| P01 出现多个 image set | 检查 Case Package 中是否混入多个 DICOM Series |
| P02 Mask 绑定失败 | 不进入正式标注，保留探针证据 |
| ProbeEvaluate 无唯一映射 | 换用三轴尺寸不同的 DICOM，检查方向和坐标输出 |
| Prepare 报 mapping unverified | 使用探针生成的 verified 配置 |
| Prebuild 失败 | 查看 `reports\mimics_prebuild.log` 和 `reports\mimics_open_error.json`；不要把该病例交给标注者，修复后重跑 |
| Prebuild 返回 `already_exists` | 已有普通 `.mcs`，默认不后台覆盖；确认无人编辑且需要重建时使用 `--rebuild-workspace` |
| Console 打开时报 image set 匹配数量不是 1 | 管理员检查 Series UID、DICOM 内容和 `.mcs` |
| Console 提交时报找不到 managed Mask | 不改 metadata；管理员重新 Prepare 或重建工作区后由 Console 恢复 |
| Finalize hash或尺寸失败 | 不手改 `.u8`；回到 Mimics 重新提交 |
| Finalize geometry 失败 | 保留报告，禁止人工强制登记 |
| `.mcs` 损坏 | 使用 `Prepare -RebuildWorkspace`，从 recovery backup 重建 |
| 建包中途失败后目录残留 | 重新运行 `sp package create`；无 `manifest.json` 的残留目录会被自动清理 |
| 标注者误 Skip | 在 **Choose Case** 中重新打开该病例 |

处理顺序是：先看终端退出码，再看 Case Package `reports/` 中的 JSON，最后看 Mimics `.log`。保留 `.mcs` 和工作目录，修正后重跑当前步骤。

## 12. 工作站验收清单

- [ ] Doctor 返回 `ready`
- [ ] 必要 API 全部可用
- [ ] ProbeRun 生成完整 evidence 和 `.mcs`
- [ ] P02 保存重开后所有 Mask 仍绑定正确 image set
- [ ] P04 与 P06 buffer 内容一致
- [ ] ProbeEvaluate 返回 `passed`
- [ ] verified 配置包含 evidence hash
- [ ] 无初始标签病例可通过 Console 打开、提交并由 Finalize 收尾
- [ ] 带初始标签病例可正确导入并回写
- [ ] Needs Review 生成 `draft_label`
- [ ] Report Problem 不生成标签
- [ ] Finalize 失败不会留下半登记 Label Artifact
- [ ] 关闭并重开 `.mcs` 后可继续标注
- [ ] 保存 recovery backup 后可用 `-RebuildWorkspace` 恢复全部 Mask

完成以上项目后，该 Windows 工作站可以进入 3–5 例真实病例的小批量试运行。
