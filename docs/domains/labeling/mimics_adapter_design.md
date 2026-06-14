# Mimics 适配器设计与开发流程

> 适用版本：优先验证 Mimics Research 21.0
> 状态：阶段 A 实施设计；带“本机门禁”的部分在验证通过前不得承诺
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
| NIfTI、MHD/MHA 图像能否直接稳定导入 | 默认不支持；优先走 DICOM 或改用原生支持工具 |
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
  finalize.py

adapters/mimics/
  runtime_py35/
    sp_common.py
    sp_diagnostics.py
    sp_open_review.py
    sp_submit_review.py
  probes/
    p01_dicom_grouping.py
    p02_image_set_binding.py
    p04_mask_buffer.py
    p05_geometry_roundtrip.py
    p06_selective_export.py
  README.md
  README_for_annotators.md
```

两类脚本含义不同：

- `probes/` 是可丢弃或保留作回归测试的能力探针，不是正式工作流；
- `runtime_py35/` 是标注者实际使用的稳定脚本，必须兼容 Python 3.5。

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
sp mimics prepare /path/to/case_package
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
- NIfTI/MHD 图像：只有 P03 已证明当前环境可安全导入或转换时才进入；
- 无法证明空间的格式：改用 ITK-SNAP、3D Slicer 或其他原生工具。

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
  export/
    img_ct/
      liver.u8
  buffer_manifest.json
```

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
sp mimics open /path/to/case_package
```

职责：

1. 检查 `mimics_runtime.json`；
2. 设置本次任务需要的环境变量；
3. 使用工作站配置中的实际可执行文件启动 Mimics；
4. 调用 `sp_open_review.py` 并传入 runtime manifest；
5. 把 Mimics 系统日志保存到病例包 `reports/`。

官方命令行参数形式为：

```text
<mimics_executable>
  [-background_mode]
  [-kill]
  [-save_log <filename.txt>]
  [-run_script <script_name.py [args]>]
```

人工编辑不能使用 `-background_mode`。批量准备项目、诊断或无交互检查才可以考虑后台模式。

### 5.5 `finalize.py`

目标命令：

```bash
sp mimics finalize /path/to/case_package
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

### 6.1 `sp_diagnostics.py`

只做环境探测：

- Python 和 Mimics 版本；
- edition 和许可可用性；
- `mimics.file`、`mimics.segment`、`mimics.dialogs` 关键 API；
- 脚本参数和日志写入；
- 可选 NumPy 是否可用。

输出 JSON，不修改病例数据。

### 6.2 `sp_open_review.py`

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

### 6.3 Mask metadata 契约

每个由平台管理的 Mask 至少保存：

| metadata 名称 | 含义 |
| --- | --- |
| `sp.review_id` | 标注任务 |
| `sp.target_id` | 最小提交目标组 |
| `sp.image_id` | 绑定的平台图像 |
| `sp.organ` | 平台统一器官名 |
| `sp.base_label_id` | 初始标签版本，可为空 |
| `sp.base_label_hash` | 初始标签校验值，可为空 |
| `sp.package_root` | 当前工作站病例包路径，每次通过 launcher 打开时刷新 |

正式逻辑不能只依赖 Mask 名称或当前 active image。名称用于人看，metadata 用于机器核对。

一个 `.mcs` 第一阶段只承载一个 `review_id`。这条限制可以避免提交脚本不知道当前在提交哪个任务，也使中断恢复和多人协作更清楚。

### 6.4 `sp_submit_review.py`

标注者从 `Script -> Scripting Library` 运行 **SP - Submit Review**。

脚本先自动检查：

- 项目中是否只有一个有效 `review_id`；
- 所有目标 Mask 是否存在；
- Mask metadata 是否完整；
- Mask 是否绑定到正确 image set；
- 导出缓冲区能否写入。

随后只显示一个对话框：

```text
提交完成 | 提交复查 | 报告阻塞 | 取消
```

处理规则：

- **提交完成**：导出该目标组要求的 Mask，写入 `submission_intent=completed`；
- **提交复查**：导出当前结果，写入 `submission_intent=needs_review`；
- **报告阻塞**：不要求所有 Mask 完成，写入阻塞类型和可选说明；
- **取消**：不写提交结果。

脚本完成后保存 `.mcs`，并提示“已导出，仍需平台检查”。它不直接写 `verified_label`。

## 7. 标注者实际怎样使用

### 7.1 一次性工作站设置

由开发者或平台操作者完成：

1. 安装并确认 Mimics Research 21.0 和许可；
2. 在 `File -> Preferences -> Scripting` 配置 Python 3.5.2；
3. 把部署后的 `runtime_py35/` 设置为 Scripting Library 目录；
4. 运行 `sp mimics doctor`；
5. 用 P04/P05 体模确认该工作站的 buffer 和空间映射。

标注者不安装 Python 包，也不修改脚本。

### 7.2 打开新任务

平台操作者或桌面启动器运行：

```bash
sp mimics prepare D:\review_packages\case_001
sp mimics open D:\review_packages\case_001
```

Mimics 自动打开任务后，标注者只核对：

- 病例是否正确；
- 当前需要处理哪些序列；
- 每个序列有哪些目标器官；
- 初始 Mask 是否大致位于正确位置。

如果不一致，直接报告阻塞，不自行换序列或复制 header。

### 7.3 标注和保存

- 使用 Mimics 正常编辑工具修改 Mask；
- 可以任意多次保存 `.mcs`；
- 关闭后继续时，仍通过 `sp mimics open` 打开同一个病例包；
- 保存只保留进度，不产生提交。

### 7.4 提交

1. 在 Scripting Library 运行 **SP - Submit Review**；
2. 选择完成、复查、阻塞或取消；
3. 等待脚本提示导出完成；
4. 平台操作者或启动器运行 `sp mimics finalize`；
5. QC 通过后，平台更新任务和标签版本。

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
| 导出后几何 QC 失败 | `finalize` | 任务显示提交失败，不丢失项目 | 禁止创建 verified 标签 |

用户提示只显示任务相关信息。完整堆栈、API 参数和文件路径写入 `reports/`，不直接展示给标注者。

## 10. 对话框使用原则

只保留三类人为确认：

1. 打开后的任务摘要确认；
2. 提交意图选择；
3. 无法继续的阻断信息。

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
| 4 | 打开任务 | `prepare.py`、`launcher.py`、`sp_open_review.py` | 3-5 人日 |
| 5 | 保存与提交 | metadata 契约、`sp_submit_review.py` | 2-4 人日 |
| 6 | 收尾与 QC | `finalize.py`、提交报告和失败恢复 | 2-4 人日 |
| 7 | 真实病例验收 | 3 至 5 例、继续任务、返修和双标注者 | 2-4 人日 |

Mimics 主路径预计 **16-29 人日**。如果直接文件路径无法使用，需要为 NIfTI/MHD 图像开发并验证额外转换路径，再增加约 **3-8 人日**，且仍可能最终退出 Mimics 主路径。

这些工作与通用病例包和 QC 有重叠，不能把全部时间重复计入平台总开发量。

## 12. 分阶段门禁

### Gate A：可以开始写生产脚本

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
- 在未验证前承诺 NIfTI/MHD 图像原生导入。

外部 IDE 和 listener 适合开发调试，不是阶段 A 的生产运行依赖。

## 14. 事实来源

- 仓库内 [Mimics Research 21.0 Scripting Guide](../../references/mimics/api_21/Mimics_API_Documentation_CN.md)
- [Materialise Mimics Core](https://www.materialise.com/en/healthcare/mimics/mimics-core)
- [Materialise: Anonymize Personal Data Using Mimics 21.0](https://www.materialise.com/en/inspiration/articles/anonymize-personal-data-mimics)

版本 21 的接口结论以 21.0 Scripting Guide 和本机验证为准；当前产品页面不能证明旧版本拥有后来增加的能力。
