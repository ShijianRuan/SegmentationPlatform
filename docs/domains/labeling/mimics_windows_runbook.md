# Mimics Research 21 Windows 工作站操作手册

> 病例包版本：v0.5。  
> 状态：代码已准备并通过本地自动化测试；Mimics 21 的实际 API 与空间映射证据由 Windows 工作站运行后生成。  
> 目标：让管理员在 Windows 机器上完成工作站初始化、探针验收和平台收尾；标注者只打开 Mimics，并通过 Scripting Library 中的 **SP Review Console** 领取、保存和提交任务。

## 1. 运行边界

标注闭环使用两个相互隔离的 Python 环境：

| 环境 | 负责内容 | 操作者如何使用 |
| --- | --- | --- |
| Windows Python 3.10+ | Case Package、Registry、几何校验、buffer 转换、最终 NIfTI 和标签登记 | 通过 `sp` 命令或 PowerShell 脚本运行 |
| Mimics 21 内置 Python 3.5 | DICOM 导入、`.mcs`、Mask 创建与编辑、Mask buffer 导出、交互弹窗 | 由 Mimics `-run_script` 或软件内脚本入口运行 |

Mimics 内置 Python 不负责读取 NIfTI、维护 Registry 或安装现代第三方依赖。标注者也不需要手工执行数据格式转换。

## 2. Windows 机器需要准备什么

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

## 3. 一次性初始化

以 PowerShell 打开项目目录：

```powershell
Set-ExecutionPolicy -Scope Process Bypass

.\scripts\windows\setup_mimics_workstation.ps1 `
  -MimicsExecutable "C:\Program Files\Materialise\Mimics Research 21.0\MimicsResearch.exe" `
  -WorkRoot "D:\SegmentationPlatform\work" `
  -RegistryRoot "D:\SegmentationPlatform\data\registry" `
  -Assignee "annotator_01"
```

脚本会创建项目专用 `.venv`、安装平台依赖、生成
`config\mimics_workstation.local.yaml`。如果提供 `RegistryRoot` 和 `Assignee`，还会生成
`adapters\mimics\scripting_library\sp_review_console.local.json`，供 Mimics 内 **SP Review Console** 使用。

在 Mimics 的 `File -> Preferences -> Scripting` 中，把 Scripting Library 路径设置为：

```text
C:\SegmentationPlatform\adapters\mimics\scripting_library
```

不要把 `runtime_py35` 直接设为 Scripting Library；那是内部脚本目录，会把诊断、打开、提交等实现脚本暴露给标注者。

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

平台可以提前批量准备病例，也可以不提前准备，让 **SP Review Console** 在标注者点击 **Open Next Review** 后后台执行。提前准备时可运行：

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Prepare `
  -ConfigPath $Config `
  -CaseRoot $Case
```

平台会校验 Case Package，将已有初始标签转换成 Mimics `.u8` buffer，生成
`working\mimics_runtime.json`，并在发现既有 `.mcs` 时切换为继续标注模式。

### 6.2 打开 Mimics

正式标注时，标注者只手动打开 Mimics，然后在 Scripting Library 运行 **SP Review Console**。Console 会读取本机 JSON 配置，查询分配给当前 assignee 的下一例，必要时后台运行 `prepare`，并在当前 Mimics 会话中打开 `.mcs` 或导入 DICOM。

`invoke_mimics_case.ps1 -Action Open` 只作为管理员调试入口保留，不作为标注者日常步骤。

Mimics 启动后会自动：

- 导入 DICOM，或重新打开 `working\<review_id>.mcs`；
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
2. 运行 `Script -> Scripting Library -> SP Review Console`。
3. 选择 **Open Next Review**，核对病例、序列和目标器官。
4. 使用 Mimics 工具修正对应的 `SP__<target_id>__<organ>` Mask。
5. 随时保存 `.mcs`，关闭 Mimics 后可以继续。
6. 长时间工作或完成一个阶段后，在 Console 中选择 **Save Checkpoint**。
7. 不修改以 `sp.` 开头的 Mask metadata。
8. 不把 Mask 移到另一个 image set。

保存 `.mcs` 只代表保存进度，不代表标签已经提交或验证。

### 6.4 在当前 Mimics 会话提交

完成或需要中断时，仍在 **SP Review Console** 中选择 **Submit Current Review**。Console 会在当前已打开病例的 Mimics 会话中调用内部提交脚本，不需要标注者填写命令行参数或文件路径。

| 动作 | 平台语义 |
| --- | --- |
| Submit Complete | 标注者认为所选 target 已完成，等待平台 QC |
| Submit For Review | 已保存并导出，但存在医学不确定、图像质量或上下文不足 |
| Report Blocked | 数据、图像集或工具问题导致无法继续 |
| Cancel | 不提交，继续保留 `.mcs` 当前进度 |

当任务包含 2–5 个 target 时，脚本允许逐个勾选后一次提交任意组合。提交前会聚合检查 Mask
完整性、image set、基础版本和 shape；检查失败时直接显示主要问题，并写入
`reports\mimics_submit_precheck.json`。

空 Mask 必须明确选择：

- 多个空 Mask 先显示一份总清单；
- 可以统一选择全部 `Confirmed Absent` 或全部 `Needs Review`；
- 情况不一致时选择逐项判断；
- 取消不会写提交。

脚本会保存 `.mcs`，并在 `submissions\<review_id>\` 下写入：

```text
submission_manifest.json
export_manifest.json
buffers\<image_id>\<target_id>\<organ>.u8
```

此时仍未生成最终标签。

### 6.5 把病例包带回平台机器

Mimics 提交清单中的 buffer 路径相对 Case Package 保存，因此整个病例目录可以迁移。复制完成后先运行：

```powershell
sp package validate D:\returned\pkg_case_001
```

不要只复制 `.mcs`、单个 `.u8` 或 submission JSON。

### 6.6 平台完成 QC 和标签登记

```powershell
sp mimics finalize D:\returned\pkg_case_001 `
  --config .\config\mimics_workstation.verified.yaml `
  --registry D:\SegmentationPlatform\data\registry
```

该命令应在持有主 Registry 的平台机器执行。verified 配置中的 Windows 可执行文件路径此时不会被调用，Finalize 只使用其中已经冻结的 buffer mapping。

平台会检查 review、target、assignee、base label、相对路径边界、buffer hash 和尺寸、空间映射、图像和器官对应关系、空 Mask outcome，以及最终 NIfTI 的物理几何。

| 提交动作 | 标签状态 | Review 状态 |
| --- | --- | --- |
| Submit Complete 且 QC 通过 | `verified_label` | `completed` |
| Submit For Review 且 QC 通过 | `draft_label` | `needs_review` |
| Report Blocked | 不生成标签 | `blocked` |
| QC 失败 | 不生成标签 | 返回 `in_progress` |

QC 报告位于 `reports\review_<review_id>_finalize.json`。

### 6.7 查看进度

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Status `
  -ConfigPath $Config `
  -RegistryRoot $Registry
```

增加 `-ReviewId "review_case_001_v1"` 可查看单个 review。

## 7. 继续修改已经提交的标签

`verified_label` 不会被覆盖写。需要继续修正时：

1. 平台创建新的 review 版本和新 Case Package，旧 verified label 作为 `base_label_id`。
2. 平台可提前执行 `Prepare`，或等待 Console 打开任务时后台准备。
3. Mimics 首次创建新 review 的 Mask 时导入旧标签。
4. 标注者通过 **SP Review Console** 打开新任务，修正并重新提交。
5. Finalize 生成新的 Label Artifact，并保留旧版本和父子来源关系。

不要直接修改旧 Case Package 后覆盖 Registry 中已经登记的标签。

## 8. `.mcs` 损坏时恢复

**SP Review Console** 的 **Save Checkpoint** 会把全部受管 Mask 保存为 gzip 压缩的 `.u8.gz`：

```text
working\checkpoints\<review_id>\<timestamp>\
```

Mimics 21 文档没有提供可依赖的“每次保存项目后自动回调脚本”接口，因此 checkpoint 是显式
灾备动作，不会在每次 Ctrl+S 后自动执行。

如果 `.mcs` 无法打开：

```powershell
.\scripts\windows\invoke_mimics_case.ps1 `
  -Action Prepare `
  -ConfigPath $Config `
  -CaseRoot $Case `
  -RebuildWorkspace
```

平台会把旧 `.mcs` 改名保留，然后验证 checkpoint 的 review、package、base label、mapping
evidence、shape 和 hash。通过后，标注者下一次通过 Console 打开任务时会重新导入 DICOM 并恢复 checkpoint；没有可用
checkpoint 时退回初始标签或空 Mask。

## 9. 多标注者使用

第一阶段采用离线文件式 Registry，建议遵守：

1. 一个 review 只分配给一个 assignee。
2. 一个 Case Package 同一时刻只由一个标注者写入。
3. 不同标注者使用不同 Case Package 目录，可以并行工作。
4. Registry 应由一个平台操作进程写入，不让多人同时直接编辑 JSON。
5. 标注结果回收时复制完整 Case Package，而不是仅复制 `.mcs` 或 `.u8`。

同一病例需要双人独立标注时，创建两个 review 和两个工作目录，最终另行比较或仲裁，不在同一 `.mcs` 中混合。

## 10. Windows 与其他机器之间传输什么

送往 Windows：

- 完整项目仓库；
- Case Package；
- 工作站本地配置模板。

从 Windows 带回：

- 完整 Case Package，包括 `working/`、`submissions/` 和 `reports/`；
- 首次验收时的 probe evidence、评估报告和 verified 配置。

平台机器运行 Finalize 后，最终 `labels/` 和更新后的 Registry 留在平台侧。只有当 Windows 与平台机器共享同一存储时，才在 Windows 直接运行 Finalize。

`.mcs` 是 Mimics 的工作状态文件，便于继续标注，但它不是平台标签、QC 报告或 Registry 的替代品。

## 11. 常见故障

| 现象 | 处理 |
| --- | --- |
| Doctor 报 API 缺失 | 核对 Mimics 版本、Research edition 和 Scripting 模块 |
| P01 出现多个 image set | 检查 Case Package 中是否混入多个 DICOM Series |
| P02 Mask 绑定失败 | 不进入正式标注，保留探针证据 |
| ProbeEvaluate 无唯一映射 | 换用三轴尺寸不同的 DICOM，检查方向和坐标输出 |
| Prepare 报 mapping unverified | 使用探针生成的 verified 配置 |
| Console 打开时报 image set 匹配数量不是 1 | 管理员检查 Series UID、DICOM 内容和 `.mcs` |
| Console 提交时报找不到 managed Mask | 不改 metadata；管理员重新 Prepare 或重建工作区后由 Console 恢复 |
| Finalize hash或尺寸失败 | 不手改 `.u8`；回到 Mimics 重新提交 |
| Finalize geometry 失败 | 保留报告，禁止人工强制登记 |
| `.mcs` 损坏 | 使用 `Prepare -RebuildWorkspace`，从 checkpoint 重建 |

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
- [ ] Submit For Review 生成 `draft_label`
- [ ] Report Blocked 不生成标签
- [ ] Finalize 失败不会留下半登记 Label Artifact
- [ ] 关闭并重开 `.mcs` 后可继续标注
- [ ] 保存 checkpoint 后可用 `-RebuildWorkspace` 恢复全部 Mask

完成以上项目后，该 Windows 工作站可以进入 3–5 例真实病例的小批量试运行。
