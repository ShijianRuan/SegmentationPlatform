# Mimics 适配器设计与开发流程

> 适用版本：优先验证 Mimics Research 21.0
> 状态：阶段 A 代码已实现；带“本机门禁”的部分在 Mimics 21 工作站验证通过前不得投入真实数据生产
> 目标：让标注者只处理图像和 Mask，不处理路径、格式转换、Python 环境和平台状态

## 1. 先给出结论

Mimics 接入采用两个运行环境，不把整个平台塞进 Mimics Python 3.5：

| 运行环境 | 负责 | 不负责 |
| --- | --- | --- |
| 外部现代 Python | 病例包、格式转换、桥接缓冲区、启动 Mimics、哈希、几何检查、提交登记 | 操作 Mimics 内部 image set 和 Mask |
| Mimics Python 3.5.2 | 打开或创建 `.mcs`、选择 image set、创建和读取 Mask、保存项目、显示少量对话框 | Data Registry、NIfTI 长期读写、训练准入、模型推理 |

第一阶段不开发 Mimics 插件、后台服务或跨进程 RPC。两个环境通过病例包中的 JSON、必要时使用的 Mask 缓冲区、日志和退出状态通信。

Mimics 是人工编辑器，不是平台控制中心。即使 Mimics 不可用，病例包、Label Artifact 和 Dataset Snapshot 仍然成立。

## 2. 哪些能力已经有依据

Mimics 21.0 Scripting Guide 可以确认：

- 使用 Python 3.5.2，并可在 Preferences 中配置兼容 Python 3.5 解释器；
- 脚本可以通过 Editor、Run Script、Scripting Library 或 Windows 命令行运行；
- 命令行可以向脚本传入参数，脚本通过 `sys.argv` 读取；
- 可以自动导入 DICOM，并使用底层 API 检查、配置、分组和加载图像；
- 一个项目可包含多个 image sets，并可通过 `get_active()` 和 `set_active()` 显式切换；
- Mask 支持 `get_voxel_buffer()` 和 `set_voxel_buffer()`；
- Mimics 对象支持字符串 metadata；
- 可以打开和保存 `.mcs`；
- 可以通过 `message_box()`、`question_box()` 和 `set_predefined_answer()` 控制必要交互。

Materialise 当前产品页也继续把 Python scripting 描述为自动化重复步骤的正式能力，但版本 21 的具体接口仍以仓库中的 21.0 Scripting Guide 为准。

## 3. 哪些能力仍不能当作已确定

下面内容必须通过实际 Mimics 21.0 安装验证：

| 未决项 | 验证前的处理 |
| --- | --- |
| Research 版本可执行文件名、安装路径和许可模块 | 写入工作站配置，不在代码中硬编码 |
| 一个复杂 DICOM 目录实际生成哪些 image sets | 先由平台给出预期序列清单，导入后逐项核对 |
| Mask buffer 的轴顺序和图像物理坐标关系 | 使用人工体模和已知点验证，未通过前不导入真实标签 |
| 不使用 NumPy 时能否高效写入和导出 Mask buffer | 先验证标准库 `memoryview` 路径；失败才锁定旧版 NumPy |
| NIfTI、MHD/MHA 图像能否直接稳定导入 | 不能假设有原生 importer；当前实现先由外部 Python 派生 DICOM，再由 Mimics 导入；实机验证关注导入后的方向、灰度和 Mask 往返 |
| `.mcs` 跨机器、跨 edition 和跨许可使用 | 只作为工作检查点，不作为唯一交付文件 |
| 部分内置对话框能否安全预答 | 只有答案由平台预检查唯一确定时才启用 |

搜索不到或本机无法证明的能力不进入生产设计。

## 4. 目标代码结构

平台主代码和 Mimics 内部脚本必须分开：

```text
src/segplatform/adapters/mimics/
  doctor.py
  prepare.py
  launcher.py
  bridge.py
  probes.py
  finalize.py

adapters/mimics/
  scripting_library/
    Start_Labeling.py
  runtime_py35/
    sp_review_console.py
    sp_common.py
    sp_diagnostics.py
    sp_open_review.py
    sp_save_checkpoint.py
    sp_submit_review.py
  probes/
    sp_probe_suite.py
    p01_dicom_grouping.py
    p02_image_set_binding.py
    p04_mask_buffer.py
    p05_geometry_roundtrip.py
    p06_selective_export.py
  README.md
  README_for_annotators.md
```

两类脚本含义不同：

- `probes/sp_probe_suite.py` 是工作站验收入口；单项探针用于失败定位和回归；
- `scripting_library/Start_Labeling.py` 是标注者在 Mimics 菜单中看到的唯一入口；
- `runtime_py35/sp_review_console.py` 是 Console 的内部实现，必须兼容 Python 3.5；
- `runtime_py35/` 中其他脚本是内部实现或管理员诊断入口，不要求标注者直接运行。

## 5. 外部现代 Python 要开发什么

### 5.1 `doctor.py`

目标命令：

```bash
sp mimics doctor --config config/mimics_workstation.yaml
```

职责：

1. 检查 Mimics 可执行文件和脚本目录是否存在；
2. 启动 `sp_diagnostics.py`；
3. 收集 Mimics 版本、edition、Python 版本和关键 API 是否存在；
4. 检查当前用户对工作目录是否有读写权限；
5. 生成 `mimics_doctor_report.json`。

它不尝试证明空间一致性。空间能力由 P04/P05 单独验证。

### 5.2 `prepare.py`

目标命令：

```bash
sp mimics prepare /path/to/case_package --config /path/to/mimics_workstation.yaml
```

职责：

1. 运行病例包预检查；
2. 判断每个 image set 是否存在 Mimics 已验证的输入路径；
3. 为已有标签生成逐器官 Mask 桥接缓冲区；
4. 生成 `working/mimics_runtime.json`；
5. 如果输入格式未获支持，给出明确降级路径，不启动 Mimics。

图像处理默认规则：

- DICOM：进入 Mimics 直接导入路径；
- 已有 `.mcs`：进入继续任务路径；
- NIfTI/MHD 图像：外部现代 Python 读取并派生 Mimics 可导入表示；只有 P03 证明导入后维度、灰度和方向一致时才进入；
- 无法证明空间的格式：改用 ITK-SNAP、3D Slicer 或其他原生工具。

NIfTI/MHD 的推荐路径不是在 Mimics Python 3.5 中安装 nibabel/SimpleITK 并直接写 `ImageData`。官方 API 可确认 `ImageData.get_voxel_buffer()`，但没有对应的 `ImageData.set_voxel_buffer()`。第三方库读取应发生在外部 Python；Mimics 内脚本只负责导入已派生的 DICOM 或经 POC 证明可用的标准图像/RAW 工作表示、保存 `.mcs` 和管理 Mask。

### 5.3 `bridge.py`

它处理的是标签，不负责创建 Mimics 图像。

输入方向：

```text
NIfTI / MHD+RAW / 逐器官 mask
-> 重采样到目标 Image Artifact 网格
-> 每器官一个布尔缓冲区
-> buffer manifest
```

输出方向：

```text
Mimics Mask 缓冲区
-> 逐器官医学图像文件
-> 可选多标签 NIfTI
```

推荐的桥接格式是一字节一个体素的布尔缓冲区加 JSON，而不是默认使用 `.npy`：

```text
working/bridge/
  import/
    img_ct/
      liver.u8
  buffer_manifest.json
```

Mimics 导出的提交 buffer 不写入 `working/bridge/`，而是写入
`submissions/{review_id}/buffers/`。导出清单保存相对 Case Package 的路径，
使病例包可从 Windows 工作站迁移回持有主 Registry 的平台机器完成 Finalize。

`buffer_manifest.json` 至少记录：

- `review_id`、`target_id`、`image_id` 和器官名；
- shape 和待验证的 Mimics 轴顺序标识；
- 文件字节数和 SHA-256；
- 来源标签 ID 和 hash；
- 缓冲区是导入还是导出。

这样 Mimics 内部脚本可以优先只使用标准库和 `memoryview`。如果本机验证证明该路径性能或兼容性不足，再为内部 Python 3.5 固定 NumPy 版本；不能反过来让整个适配器依赖旧科学计算栈。

### 5.4 `launcher.py`

目标命令：

```bash
sp mimics open /path/to/case_package --config /path/to/mimics_workstation.yaml --registry /path/to/registry
sp mimics prebuild-workspace /path/to/case_package --config /path/to/mimics_workstation.yaml
sp mimics prebuild-many /path/to/cases_root --config /path/to/mimics_workstation.yaml --continue-on-error
```

`open` 是管理员调试和兼容入口，不作为标注者日常入口。正式标注由 **Start Labeling** 在当前 Mimics 会话中调用内部打开逻辑。`prebuild-*` 是平台/管理员侧批量入口，用 Mimics background mode 预生成 `.mcs`，把首次导入从标注者在场时移走。

职责：

1. 检查 `mimics_runtime.json`；
2. 设置本次任务需要的环境变量；
3. 使用工作站配置中的实际可执行文件启动 Mimics；
4. 交互 open 调用 `sp_open_review.py`；后台 prebuild 调用 `sp_open_review.py --background-prebuild`；
5. 把 Mimics 系统日志保存到病例包 `reports/`。

官方命令行参数形式为：

```text
<mimics_executable>
  [-background_mode]
  [-kill]
  [-save_log <filename.txt>]
  [-run_script <script_name.py [args]>]
```

人工编辑不能使用 `-background_mode`。批量预生成项目、诊断或无交互检查才使用后台模式。`prebuild_workspace()` 默认跳过已有预生成 marker 的 `.mcs`，也跳过已有普通 `.mcs`，避免后台进程覆盖标注者现场；只有显式 `--rebuild-workspace` 才重建。

### 5.5 `finalize.py`

目标命令：

```bash
sp mimics finalize /path/to/case_package --config /path/to/mimics_workstation.yaml --registry /path/to/registry
```

职责：

1. 读取 Mimics 生成的提交意图和导出缓冲区；
2. 检查器官、目标组、image set、shape、hash 和基础标签版本；
3. 写出 NIfTI 或平台要求的标签文件；
4. 执行物理空间或索引空间 QC；
5. 更新 `submission_manifest.json` 和结构化报告；
6. 只有检查通过的“提交完成”才交给平台创建新 Label Artifact。

它不能把 Mimics 中的“保存项目”解释为 verified。

## 6. Mimics Python 3.5 要开发什么

### 6.1 `sp_review_console.py`

这是标注者在 Mimics 内通过 `scripting_library/Start_Labeling.py` 调用的主入口，推荐在菜单中显示为 **Start Labeling**。

它负责把平台流程收敛成少量 Mimics 内动作：

- **Open Case**：读取本机 JSON 配置，调用外部平台 Python 查询 `sp review next`，必要时用 `--claim-unassigned` 认领未分配任务，再后台执行 `sp mimics prepare`，然后在当前 Mimics 会话内调用 `sp_open_review.py`。它既可打开新任务，也可继续上次未完成任务。
- **Complete / Needs Review / Report Problem**：把业务结果直接传给 `sp_submit_review.py`，导出 Mask 或记录阻塞原因。默认不阻塞等待最终 QC；平台 watcher 或管理员批处理独立运行 `sp mimics finalize`。
- **Skip Case**：保存并关闭当前 `.mcs`，本次领取时排除当前 review 后打开下一例。它不是提交，也不是阻塞，也不改变 Registry 状态。长期移出队列由管理员运行 `sp review defer`。
- **Save Recovery Backup**：调用 `sp_save_checkpoint.py` 保存恢复快照。
- **Task List**：在 Mimics 弹窗内分页显示当前 review、case、image set、目标器官和当前 Mask 状态，并支持按 Missing、Ready、With Initial、Known Absent 筛选，替代常驻弹窗。
- **Open Case** 可在当前项目保存并关闭后继续下一例，但每个 `.mcs` 仍只对应一个 review/case。

本机配置使用 JSON，而不是 YAML，因为 Mimics 21 内 Python 3.5 只应依赖标准库：

```json
{
  "platform_python": "C:\\SegmentationPlatform\\.venv\\Scripts\\python.exe",
  "registry_root": "D:\\platform_registry",
  "workstation_config": "C:\\SegmentationPlatform\\config\\mimics_workstation.verified.yaml",
  "assignee": "annotator_01",
  "claim_unassigned": true,
  "auto_finalize": false,
  "checkpoint_keep_count": 3
}
```

`auto_finalize=false` 是阶段 A 推荐默认值。提交后的几何、hash、Registry 写入和标签版本创建属于平台 QC，不是标注者交互流程。确需即时反馈时，可在受控工作站上设为 `true`。

### 6.2 `sp_diagnostics.py`

只做环境探测：

- Python 和 Mimics 版本；
- edition 和许可可用性；
- `mimics.file`、`mimics.segment`、`mimics.dialogs` 关键 API；
- 脚本参数和日志写入；
- 可选 NumPy 是否可用。

输出 JSON，不修改病例数据。

### 6.3 `sp_open_review.py`

输入是 `mimics_runtime.json`。

首次打开任务时：

1. 读取 runtime manifest；
2. 导入该 Case 的 DICOM，或打开已准备的 `.mcs`；
3. 枚举实际 image sets；
4. 使用 DICOM 标识、尺寸和其他已验证指纹与 `image_id` 对应；
5. 对每个目标显式调用 `set_active()`；
6. 创建或更新一个器官一个 Mask；
7. 必要时通过 `set_voxel_buffer()` 注入初始标签；
8. 给 Mask 写入平台 metadata；
9. 保存到任务专属 `.mcs`；
10. 只显示一次任务摘要。

继续任务时：

1. 打开已有 `.mcs`；
2. 重新核对 Mask 和 image set；
3. 刷新本机路径相关 metadata；
4. 不重新注入或覆盖标注者已经修改的 Mask。

### 6.4 Mask metadata 契约

每个由平台管理的 Mask 至少保存：

| metadata 名称 | 含义 |
| --- | --- |
| `sp.review_id` | 标注任务 |
| `sp.target_id` | 最小提交目标组 |
| `sp.image_id` | 绑定的平台图像 |
| `sp.organ` | 平台统一器官名 |
| `sp.base_label_id` | 初始标签版本，可为空 |
| `sp.base_label_hash` | 初始标签校验值，可为空 |
| `sp.package_root` | 当前工作站病例包路径，每次通过 Console/open 内部脚本打开时刷新 |

正式逻辑不能只依赖 Mask 名称或当前 active image。名称用于人看，metadata 用于机器核对。

一个 `.mcs` 第一阶段只承载一个 `review_id`。这条限制可以避免提交脚本不知道当前在提交哪个任务，也使中断恢复和多人协作更清楚。

Resume 时先比较已有 Mask metadata 与当前 target 的 `base_label_id` 和
`base_label_sha256`。这里比较的是 Label Artifact bundle 版本，不把逐器官 import buffer
文件 hash 错当成同一个 hash；任一版本不一致都阻断打开。

### 6.5 `sp_submit_review.py`

日常使用时由 **Start Labeling** 调用。管理员调试时可临时运行该脚本；生产工作站不应把整个 `runtime_py35/` 目录暴露给标注者。

脚本先自动检查：

- 项目中是否只有一个有效 `review_id`；
- 所有目标 Mask 是否存在；
- Mask metadata 是否完整；
- Mask 是否绑定到正确 image set；
- 导出缓冲区能否写入。

提交时只显示与当前决定有关的对话框：

```text
提交意图 -> 目标组选择 -> 仅在存在空 Mask 时确认缺失语义
```

处理规则：

- **提交完成**：导出该目标组要求的 Mask，写入 `submission_intent=completed`；
- **提交复查**：导出当前结果，写入 `submission_intent=needs_review`；
- **报告阻塞**：不要求所有 Mask 完成，写入阻塞类型和可选说明；
- **取消**：不写提交结果。

2–5 个目标组使用 `question_box()` 模拟勾选，可一次组成任意提交组合。Mimics 21 API
没有原生 checkbox/multi-select 对话框，因此不依赖不存在的控件能力。

导出前脚本聚合检查 Mask 是否存在、image set、基础标签版本和 shape。多个空 Mask 先显示
总清单，允许统一确认或逐项处理。

脚本完成后保存 `.mcs`，并提示“已导出，仍需平台检查”。它不直接写 `verified_label`。

### 6.6 `sp_save_checkpoint.py`

该脚本显式导出当前 review 的全部受管 Mask 为 gzip 压缩 `.u8.gz`，并写入 recovery backup manifest。它用于 `.mcs`
损坏后的恢复，不创建提交、不改变标签状态。

它不是 Ctrl+S 的替代品：

- Ctrl+S / 保存 `.mcs` 是日常进度保存，速度快，标注者可以频繁使用。
- **Save Recovery Backup** 是灾备快照，用于 `.mcs` 损坏、跨机器恢复或重建工作区。

Mimics 21 资料没有证明存在稳定的项目保存事件回调，因此第一阶段不伪造“每次保存自动 backup”。
标注者只在长时间工作、完成一大段器官或准备离开工作站前主动运行一次。
脚本默认保留最新 `checkpoint_keep_count=3` 份 recovery backup，自动清理更旧目录，避免长期标注产生大量 `.u8.gz` 文件。

## 7. 标注者实际怎样使用

### 7.1 一次性工作站设置

由开发者或平台操作者完成：

1. 安装并确认 Mimics Research 21.0 和许可；
2. 在 `File -> Preferences -> Scripting` 配置 Python 3.5.2；
3. 把部署后的 `adapters/mimics/scripting_library/` 设置为 Scripting Library 目录；
4. 复制并填写 `config/mimics_review_console.example.json` 到 `adapters/mimics/scripting_library/sp_review_console.local.json`，或用 Windows setup 脚本自动生成；
5. 运行 `sp mimics doctor`；
6. 用 P04/P05 体模确认该工作站的 buffer 和空间映射。

标注者不安装 Python 包，也不修改脚本。

`buffer_mapping` 是默认映射，不再被视为不可替代的全局单例。实现支持可选 `buffer_mapping_by_image_id`，当 P05 证明某个 `image_id` 的 Mimics buffer 轴排列不同于默认值时，`prepare`、Mask 注入、Recovery Backup、提交导出和 `finalize` 会按 `image_id` 选择对应映射。没有覆盖的图像继续使用默认映射。覆盖项同样必须 `status=verified` 且带独立 `evidence_id`。

### 7.2 打开新任务

标注者只做：

1. 打开 Mimics。
2. 运行 `Script -> Scripting Library -> Start Labeling`。
3. 选择 **Open Case**。

Console 在后台查询任务队列、准备病例、打开 `.mcs` 或导入 DICOM。任务打开后，标注者只核对：

- 病例是否正确；
- 当前需要处理哪些序列；
- 每个序列有哪些目标器官；
- 初始 Mask 是否大致位于正确位置。

如果不一致，直接报告阻塞，不自行换序列或复制 header。

任务摘要不是常驻窗口。标注中途忘记目标范围时，重新运行 **Start Labeling** 并选择 **Task List**；多器官任务可在弹窗内翻页，也可按 Missing、Ready、With Initial、Known Absent 筛选。
该摘要是当前稳定主路径：它从 `mimics_runtime.json` 和受管 Mask metadata 生成，不要求标注者打开外部文件。

`known_absent` 不作为常规任务准备手段。平台在建包前通常不知道扫描覆盖范围，也不能凭“腹部/头颈”等粗略判断把目标器官排除。
只有来源数据已有明确结构化事实时，才允许在病例包中写入 `known_absent`。标注者在打开病例后遇到空 Mask、无法确认或上下文不足时，通过提交时的
`confirmed_absent`、`Needs Review` 或 `Report Problem` 表达，不回头修改病例包。

Project Tree 中的 Custom/注释对象可以作为更好的常驻任务清单候选，但 Mimics 21 API 文档目前只确认 masks、parts、measurements、planes、points 等对象以及对象 metadata，
未确认有稳定的“项目级任务注释”创建接口。因此生产实现暂不依赖该能力；若 POC 证明可创建不会污染图像视图的 Custom 注释对象，再把 Task List 同步写入该对象。

### 7.3 标注和保存

- 使用 Mimics 正常编辑工具修改 Mask；
- 可以任意多次保存 `.mcs`；
- 长时间工作后可在 **Start Labeling** 中保存独立 Mask checkpoint；
- 关闭后继续时，仍打开 Mimics 并通过 **Start Labeling** 进入任务；
- 保存只保留进度，不产生提交。

### 7.4 提交

1. 在 **Start Labeling** 直接选择 **Complete**、**Needs Review** 或 **Report Problem**；
2. 如有多个目标组，选择本次提交哪些目标组；
3. 等待脚本提示导出完成；
4. 平台后台或管理员批处理独立运行 `sp mimics finalize`；
5. QC 通过后，平台更新任务和标签版本；QC 失败的任务回到可返修队列。

单目标组、无空 Mask 的常见路径不会再出现“提交意图”二次选择。额外弹窗只保留在多目标组选择、空 Mask 语义确认、待复查原因和阻塞原因这些确实需要人工判断的分支。

标注者不手工导出 NIfTI，不选择输出文件名，也不维护生命周期状态。

## 8. 多序列、继续修订和多人协作

### 多序列

- 不设主图像和参考图像；
- 每个目标组直接引用一个 `image_id`；
- 脚本在创建、检查和导出 Mask 前显式激活该 image set；
- 不同序列未配准时，不跨序列复制 Mask。

### 已验证标签继续修订

- 平台创建新的 `review_id`；
- 已验证标签作为新任务的 `base_label`；
- 创建新的任务专属 `.mcs` 或受控副本；
- 新提交产生新 Label Artifact，旧版本不覆盖。

### 多标注者

- 每位标注者获得不同 `review_id` 和 `.mcs`；
- 不共享写同一个项目文件；
- 提交时比较 `base_label_hash`；
- 冲突由平台创建新复查任务处理，不在 Mimics 内合并版本。

## 9. 异常怎样反馈

| 异常 | 谁发现 | 标注者看到什么 | 平台行为 |
| --- | --- | --- | --- |
| 病例包或桥接文件损坏 | `prepare` | 不启动 Mimics | 修复或重新生成 |
| DICOM 分组与清单不一致 | `sp_open_review.py` | 阻断对话框，显示病例和序列摘要 | 写错误报告 |
| Mask shape 或 image set 不匹配 | 打开或提交脚本 | 阻断，不允许继续提交 | 保留 `.mcs` 和证据 |
| 器官 Mask 缺失 | 提交脚本 | 列出缺少目标 | 返回继续编辑 |
| 医学上不能确认 | 标注者 | 选择“提交复查” | 保留草稿并创建复查队列 |
| 工具或数据导致无法工作 | 标注者 | 选择“报告阻塞” | 平台操作者处理后重开 |
| 导出后平台 QC 失败 | `finalize` | 弹窗显示主要 finding 和动作建议；完整报告在 `review_report.json` | 禁止创建 verified 标签，能返修的任务回到 in_progress |
| `.mcs` 损坏 | Console/open 内部脚本 | 保留旧文件并提示重建 | 从匹配当前版本的 checkpoint 恢复 |

用户提示只显示任务相关信息。完整堆栈、API 参数和文件路径写入 `reports/`，不直接展示给标注者。

## 10. 对话框使用原则

人为交互只保留四类：

1. 打开后的任务摘要确认；
2. 提交意图和目标组选择；
3. 仅在存在空 Mask 时确认缺失语义；
4. 无法继续的阻断信息。

可预答的对话框必须满足“平台预检查已确定唯一答案”。例如方向信息已从可信 DICOM 验证时，才可以预设 `ChangeOrientation=default`。

下面情况不能自动预答：

- 图像方向不明确；
- raw spacing 或字节序不明确；
- 多个序列无法唯一匹配；
- 旧项目坐标系转换会改变对象位置；
- 导入过程排除了冲突图像。

## 11. 开发顺序和工作量

| 顺序 | 工作 | 产物 | 估算 |
| ---: | --- | --- | ---: |
| 1 | 工作站诊断 | `doctor.py`、`sp_diagnostics.py`、环境报告 | 1-2 人日 |
| 2 | 能力探针 | P01/P02/P04/P05/P06 脚本和证据 | 3-5 人日 |
| 3 | 标签桥接 | `bridge.py`、buffer manifest、往返测试 | 3-5 人日 |
| 4 | 打开任务和预生成工作区 | `prepare.py`、`launcher.py`、`sp_review_console.py`、`sp_open_review.py`、`prebuild-workspace` | 3-5 人日 |
| 5 | 保存与提交 | metadata 契约、`sp_submit_review.py`、`sp_save_checkpoint.py` | 2-4 人日 |
| 6 | 收尾与 QC | `finalize.py`、提交报告和失败恢复 | 2-4 人日 |
| 7 | 真实病例验收 | 3 至 5 例、继续任务、返修和双标注者 | 2-4 人日 |

Mimics 主路径预计 **16-29 人日**。如果直接文件路径无法使用，需要为 NIfTI/MHD 图像开发并验证额外转换路径，再增加约 **3-8 人日**，且仍可能最终退出 Mimics 主路径。

这些工作与通用病例包和 QC 有重叠，不能把全部时间重复计入平台总开发量。

## 12. 分阶段门禁

### Gate A：生产脚本可以连接真实数据

必须通过：

- doctor 能运行；
- DICOM 能形成可核对的 image sets；
- active image 可显式切换；
- Mask metadata 可保存并随 `.mcs` 重开；
- 单个 Mask buffer 可以无歧义往返。

### Gate B：可以让标注者试用

必须通过：

- 任务打开不需要手工改路径；
- 初始 Mask 与目标图像对齐；
- 保存并重开不丢失任务上下文；
- 可以选择性导出目标组；
- 错误会阻断并写报告。

### Gate C：可以成为主要标注工具

必须通过：

- 3 至 5 个真实病例重复通过；
- 多序列、继续修订和不同标注者任务可区分；
- 标注者不处理格式、脚本参数和 Python 环境；
- 与备用工具相比，操作成本可接受；
- 空间往返没有无法解释的偏移。

任一硬门禁失败，就继续使用 NIfTI 原生标注工具。平台闭环不等待 Mimics。

## 13. 暂时不做

- 在 Mimics 内运行深度学习推理；
- 把 Data Registry 或任务状态机实现到 Mimics metadata；
- 通过外部 IDE/RPyC 驱动日常生产标注；
- 在一个 `.mcs` 中混放多个平台 review task；
- 自动处理存在歧义的方向、spacing 或序列选择；
- 把 `.mcs` 当作唯一标签交付物；
- 在未验证前承诺 NIfTI/MHD 图像原生导入；
- 绕过 Mimics 导入 API，直接把外部数组写成 `ImageData`。

外部 IDE 和 listener 适合开发调试，不是阶段 A 的生产运行依赖。

## 14. 事实来源

- 仓库内 [Mimics Research 21.0 Scripting Guide](../../references/mimics/api_21/Mimics_API_Documentation_CN.md)
- [Materialise Mimics Core](https://www.materialise.com/en/healthcare/mimics/mimics-core)
- [Materialise: Anonymize Personal Data Using Mimics 21.0](https://www.materialise.com/en/inspiration/articles/anonymize-personal-data-mimics)

版本 21 的接口结论以 21.0 Scripting Guide 和本机验证为准；当前产品页面不能证明旧版本拥有后来增加的能力。
