# nnInteractive for Mimics Research 21

## 1. 结论

nnInteractive 可以作为 Mimics Research 21 的独立交互分割工具，但必须采用双进程结构：

- Mimics Python 3.5 负责选择图像和目标 Mask、采集提示、写回结果；
- 外部 Python 3.10+ 环境负责 PyTorch 和 nnInteractive 推理；
- 两者通过临时体素 buffer 和 JSON 调用协议连接。

该功能不依赖病例包、任务队列、Registry 或任何特定标注流程。只要 Mimics 当前打开了图像，用户就可以运行它。已有标注流程中的病例也可以使用同一个入口，不需要专门集成。

用户入口统一命名为 **nnInteractive**，窗口标题为 **nnInteractive Segmentation**。不再使用含义宽泛的 “AI Refine”。

## 2. 为什么不能直接安装进 Mimics Python

Mimics Research 21 的脚本环境基于 Python 3.5。nnInteractive 当前要求 Python 3.10+，并依赖现代 PyTorch，因此不能在 Mimics 解释器内运行。

Mimics 侧只做轻量工作：

1. 读取当前 active image 的灰度 buffer；
2. 读取或创建目标 Mask；
3. 通过 Mimics 原生 API 采集交互；
4. 调用外部 bridge；
5. 把预测结果写回目标 Mask。

## 3. 入口与 GUI 边界

Mimics 21 官方脚本 API 支持：

- 将脚本注册到 `Script -> Scripting Library`；
- 通过脚本一键运行；
- 打开 `Edit Mask`、点选、Spline 等交互工具。

现有公开 API 没有提供向 `Segment` 或 `Advanced Segment` 工具栏注册自定义图标、按钮或 Ribbon 命令的接口。因此当前可靠入口是：

```text
Script -> Scripting Library -> nnInteractive
```

这已经是单击启动，不需要打开 Editor、Console 或命令行。若以后要进入 Mimics 原生分割工具栏，需要单独向 Materialise 确认扩展 SDK 或厂商支持，不能把它当作 Python API 已有能力。

## 4. 目标 Mask 的选择

运行前，用户在 Project Tree 中选择一个目标 Mask：

- 恰好选择一个 Mask：在该 Mask 上继续分割或修正；
- 没有选择 Mask：脚本可创建新的 `nnInteractive Result`；
- 选择多个 Mask：脚本停止并要求只选一个，避免把结果写错对象；
- 目标 Mask 不属于 active image：脚本停止，不做隐式跨图像绑定。

已有 Mask 会作为 nnInteractive 的 initial segmentation。空 Mask 则从提示开始生成新分割。

## 5. Mimics 交互与 nnInteractive 提示的映射

### 5.1 已实现的提示

| nnInteractive 提示 | Mimics 采集方式 | 转换方式 |
| --- | --- | --- |
| Foreground point | `mimics.indicate_coordinate()` | 世界坐标转 active image voxel index |
| Background point | `mimics.indicate_coordinate()` | 同上，`include_interaction=false` |
| Foreground scribble | `mimics.analyze.indicate_spline()` | 读取 `geometry_points` 并栅格化为细线 |
| Background scribble | `mimics.analyze.indicate_spline()` | 同上，作为排除提示 |
| Foreground box | 临时 Prompt Mask + `activate_edit_mask(..., "Rectangle", "Draw")` | 从绘制区域提取 bounding box |
| Background box | 同上 | 作为排除 box |
| Foreground lasso | 临时 Prompt Mask + `activate_edit_mask(..., "Lasso", "Draw")` | 把填充区域转换成闭合边界 |
| Background lasso | 同上 | 作为排除 lasso |

### 5.2 为什么不直接监听 Edit Mask 的笔迹

`mimics.segment.activate_edit_mask()` 可以启动 `Ellipse`、`Rectangle`、`Lasso`、`FloodFill`、`LiveWire` 等编辑工具，并返回编辑后的 Mask。

但是 Mimics 21 公开 API 没有提供以下信息：

- 每次 stroke 的轨迹；
- Draw 与 Erase 的逐次历史；
- Lasso 顶点列表；
- Edit Mask 完成事件中的工具参数；
- 删除某个历史 stroke 的接口。

`mimics.events` 只有 `doc_opened`、`doc_closed`、`obj_deleted`、`obj_changed` 和 `timer` 等通用通知。`obj_changed` 能说明对象发生了变化，但不能恢复是哪种编辑工具、正负语义或笔迹几何。

因此，直接激活用户的目标 Mask 再尝试“读取编辑动作”仍会退化为 Mask diff，而且会污染目标结果。当前实现改用短生命周期 Prompt Mask：

1. 脚本创建空 Prompt Mask；
2. 在 Prompt Mask 上激活 Rectangle 或 Lasso；
3. 用户确认后读取 prompt buffer；
4. Rectangle 只传 bbox，Lasso 只写非空裁剪区；
5. 立即删除 Prompt Mask；
6. 目标 Mask 只接收 nnInteractive 结果。

Spline 和 point 不需要 Prompt Mask，Mimics API 能直接返回几何信息。

## 6. 与旧 diff 方案的区别

旧方案把目标 Mask 的增删变化解释为正负 Scribble，需要保存完整 baseline。它存在以下问题：

- 所有提示都被降级成区域 diff；
- 无法保留 point、box、lasso 的真实语义；
- baseline 占用磁盘并产生额外 I/O；
- baseline 刷新后无法撤销某一条提示；
- 必须依赖此前生成的 runtime 和初始 baseline；
- 用户在目标 Mask 上画提示时会暂时破坏结果。

当前方案：

- 不保存长期 baseline；
- 进入工具时只在临时目录保存一次初始目标 Mask；
- 当前工具会话中按顺序保存提示；
- 每次从初始目标 Mask 重放提示；
- 支持 **Undo Last Prompt**；
- 支持 **Reset To Start**；
- 工具退出时删除图像、初始 Mask 和 prompt 临时文件；
- 最终结果只保留在用户选中的 Mimics Mask 中。

重新启动 nnInteractive 时，当前 Mask 成为新的 initial segmentation。上一会话的提示历史不会继续保留，但分割结果不会丢失。

## 7. 用户工作流

1. 在 Mimics 中打开任意项目。
2. 激活要处理的 image set。
3. 在 Project Tree 选择一个目标 Mask；也可以不选，由脚本创建新 Mask。
4. 运行 `Script -> Scripting Library -> nnInteractive`。
5. 选择 Point、Scribble、Box 或 Lasso。
6. 选择 Foreground 或 Background。
7. 在 Mimics 视图中完成提示并确认。
8. 脚本调用外部 nnInteractive，结果自动写回目标 Mask。
9. 继续增加提示，或使用 **Undo Last Prompt** / **Reset To Start**。
10. 选择 **Finish**，按正常 Mimics 方式保存项目。

第一次推理需要启动模型服务，通常比后续提示慢。脚本会复用正在运行的本机服务。

服务由 bridge 创建并记录所有权，不会根据一个来源不明的 PID 直接终止进程。每次提示都会刷新活动时间；默认连续 30 分钟没有推理请求后，独立 watchdog 会核对 PID、启动命令、模型路径和所有权 token，再关闭自己启动的服务并释放 GPU。nnInteractive 官方的 `idle-timeout` 只回收 client session，本集成没有把它误当作服务退出机制。

`start_server.bat` 只用于人工诊断。默认自动管理模式下，诊断结束后应按 Ctrl+C 停止它再运行 Mimics；若确实要长期连接手工启动的服务，需要在 `nninteractive_config.json` 中显式设置 `auto_start_server: false`。自动模式遇到来源不明的 1527 端口服务会报错，不会接管或结束它。

## 8. 代码结构

| 文件 | 职责 |
| --- | --- |
| `adapters/mimics/scripting_library/nnInteractive.py` | Mimics Scripting Library 独立入口 |
| `adapters/mimics/runtime_py35/nninteractive_mimics.py` | 目标选择、提示采集、临时文件和结果写回 |
| `adapters/mimics/nninteractive_bridge.py` | 外部 Python 中加载图像、重放提示并调用 nnInteractive |
| `scripts/setup_nninteractive_env.py` | 在 Windows 上联网安装独立环境 |
| `scripts/build_nninteractive_bundle.py` | 在 Windows 上构建含环境、权重、bridge 和 Mimics 脚本的离线包 |

`nnInteractive` 入口不会导入平台 Console，也不会读取平台 runtime。

## 9. Windows 安装

### 9.1 联网安装

在项目根目录使用 Python 3.10+：

```powershell
python scripts\setup_nninteractive_env.py --cuda cu124 --device cuda:0
```

安装脚本可恢复“权重已经下载、但虚拟环境不完整”的中断状态：重建 Python 环境时暂存并恢复 `nninteractive_env\models\`，不重新下载已有权重。

然后将 Mimics 的 Scripting Library 路径设为：

```text
<project>\adapters\mimics\scripting_library
```

### 9.2 离线包

必须在 Windows 机器上构建 Windows 包：

```powershell
python scripts\build_nninteractive_bundle.py
```

解压后，把 Mimics Scripting Library 指向：

```text
<extract-root>\nninteractive_env\mimics\scripting_library
```

虚拟环境、PyTorch wheel 和 Python 可执行文件不能从 macOS 直接复制为 Windows 运行环境。

### 9.3 与标注工作包合并（推荐）

平台操作者可以为标注者生成一个同时包含标注入口和 nnInteractive 的单一工作目录。标注者只需在 Mimics 中配置一次 Scripting Library 路径，就能同时使用六个 `Labeling_*.py` 标注脚本和 `nnInteractive` AI 工具。

**平台操作者执行**：

```powershell
# 1. 安装 nnInteractive 环境（只需做一次）
python scripts\setup_nninteractive_env.py --cuda cu124 --device cuda:0

# 2. 导出工作包（自动包含 nnInteractive 脚本）
sp review export-worklist `
  --registry D:\platform_registry `
  --output-root D:\transfer\batch_001 `
  --limit 30
```

`export-worklist` 在检测到仓库中存在 nnInteractive 脚本时，会自动把它们复制进工作包。

**工作包目录（标注者收到）**：

```text
D:\transfer\batch_001\
  Labeling_Open_Next_Case.py
  Labeling_Case_Navigation.py
  Labeling_Submit_Complete.py
  Labeling_Submit_or_Report_Issue.py
  Labeling_View_Task_List.py
  Labeling_Save_Recovery_Backup.py
  nnInteractive.py              ← AI 工具入口（自动包含）
  nninteractive_bridge.py       ← Bridge 脚本（自动包含）
  runtime_py35/
    sp_common.py
    sp_open_review.py
    sp_review_console.py
    sp_save_checkpoint.py
    sp_submit_review.py
    nninteractive_mimics.py     ← AI 工具实现（自动包含）
  cases/
    case_001/
    case_002/
  worklist_manifest.json
  worklist_progress.json
```

外部 Python 环境和模型仍须单独放到标注者机器上。推荐把离线 bundle 解压到标注工作包的父目录下（脚本自动发现），或通过环境变量显式指定：

```powershell
setx NNINTERACTIVE_PYTHON "D:\nninteractive_env\python\python.exe"
setx NNINTERACTIVE_MODEL_DIR "D:\nninteractive_env\models\nnInteractive_v1.0"
```

如果离线 bundle 解压到工作包平级目录 `..\nninteractive_env\`，`nninteractive_mimics.py` 的自动发现机制会找到它。不设置环境变量也能运行。

**标注者**：在 Mimics 中 `File → Preferences → Scripting → Scripting Library` 指向 `D:\transfer\batch_001\` 即可使用全部 7 个入口。

## 10. 实机验证清单

在 Mimics Research 21 Windows 实机上依次验证：

1. Scripting Library 中出现 `nnInteractive`。
2. 任意非平台项目可以直接运行。
3. 选中已有 Mask 后结果写回正确 Mask。
4. 未选 Mask 时可创建新结果 Mask。
5. Foreground/Background point 均改变结果且方向正确。
6. Spline Scribble 能形成连续提示。
7. Rectangle 只产生一个合理 bbox。
8. Lasso 填充区域转换为闭合边界后结果合理。
9. 在 Rectangle/Lasso 中直接 Cancel，确认脚本返回且不采用未确认区域。
10. 在绘制部分区域后关闭 Edit Mask，确认 Mimics 是抛出 `UserInterrupted`、正常返回空 Mask，还是保留部分区域。
11. Undo 只撤销最后一个提示。
12. Reset 恢复进入工具时的 Mask。
13. 切换 image set 后不会写错图像或 Mask。
14. 工具退出后没有残留 `nnInteractive Prompt` Mask。
15. 第一次和后续推理耗时可接受。
16. Mimics 保存、关闭、重新打开项目后结果仍存在。

在这些检查通过前，应把功能视为工程验证版，而不是生产标注能力。

## 11. 已知限制

- Mimics 21 公开 Python API 不能注册原生 Segment 工具栏图标。
- `activate_edit_mask()` 文档没有声明 Cancel 时抛出的异常类型。代码处理 `mimics.UserInterrupted`、正常返回空 Mask 和其他异常，并始终删除 Prompt Mask 和临时目录；但 Cancel 是否可能正常返回带部分编辑的 Mask，必须实机验证。
- Spline Scribble 是曲线栅格化，不是 Mimics 原生自由画笔事件。
- Mimics 21 API 明确公开 `Spline.geometry_points` 和 `Spline.points`。若运行时两者都不可读或不足两个不同体素点，脚本会显示明确错误，不再静默忽略。
- 一个工具会话内提示可撤销；退出后只保留结果，不保留提示历史。
- 推理期间 Mimics 会等待外部 bridge 返回。
- 自动启动的服务使用本机 bearer token，并只复用带匹配所有权记录、模型目录和设备配置的进程；默认端口被其他服务占用时会明确停止，不会杀死来源不明的进程。
- 无法识别的 Mimics voxel buffer dtype 会阻断并要求补充工作站验证，不会默认猜成 `int16`。
- 当前官方模型权重的具体许可必须以实际下载版本携带的 license 为准，不能仅根据代码仓库许可推断用途。

## 12. 图像强度、预处理和后处理

### 12.1 Mimics 输出的强度

Mimics 21 API 文档明确说明：

- `ImageData.get_voxel_buffer()` 返回 16-bit Gray Value 三维数组；
- Mimics Python API 中涉及图像强度的方法统一使用 Gray Value；
- `mimics.segment.GV2HU()` 和 `HU2GV()` 用于 Gray Value 与 HU 的转换。

因此该 buffer 既不能简单称为原始 DICOM stored value，也不是直接的 HU 数组。

当前集成原样传递 Mimics Gray Value，不主动转换成 HU。原因是 nnInteractive 2.4.2 在 `set_image()` 后会：

1. 把图像转换为 float；
2. 查找非零区域；
3. 用非零区域的均值和标准差对整幅图像做 z-score；
4. 不在这一阶段按 spacing 对整幅图像重采样。

若 Gray Value 与 HU 是正向线性关系，z-score 后的值理论上相同。直接转换 HU 通常不会改变模型输入，反而可能改变“哪些体素等于零”的判定。

仍需实机验证：

1. 在已知 CT 位置读取 `image.get_grey_value()` 和 voxel buffer；
2. 用 `GV2HU()` 转换并与外部 DICOM Rescale Slope/Intercept 结果对比；
3. 记录 `GV2HU(0)`，确认零值在该项目中的物理含义；
4. 比较 Mimics buffer 与外部 NIfTI 在 z-score 后的数值分布；
5. 检查 Pixel Padding、截断、饱和或导入转换是否造成非线性差异。

只有发现非线性差异或零值区域明显不一致时，才应在 bridge 中增加显式强度转换。现在直接假设“必须转 HU”并不严谨。

### 12.2 nnInteractive 原生预处理

当前实现固定安装并验证 `nninteractive==2.4.2`，避免 `>=` 版本漂移改变内部行为。

nnInteractive 的推理预处理包括：

- 非零区域统计和全图 z-score；
- 以最新提示为中心裁剪局部 patch；
- 超出图像范围时做 constant padding；
- 图像使用 trilinear resize 到模型 patch size；
- previous segmentation 使用 nearest resize；
- Scribble/Lasso 等交互通道使用 area resize；
- 对可能在下采样中消失的细提示先做 dilation；
- AutoZoom 在预测变化触及 patch 边界时逐步扩大视野。

这意味着调用方不应再次自行做固定 spacing 重采样、强度标准化或 patch 裁剪，否则会与模型内部逻辑叠加。

### 12.3 nnInteractive 原生后处理

nnInteractive 2.4.2 的默认输出路径包括：

- 对网络输出做 `argmax` 得到离散预测；
- AutoZoom 后把 coarse prediction 缩放回对应区域；
- 二值 coarse mask 使用 trilinear resize 后以 `0.5` 阈值离散化；
- 根据 coarse prediction 与 previous segmentation 的差异规划 refinement patches；
- 在原图坐标空间把局部 refinement 结果写回 target buffer。

默认推理代码没有执行通用的最大连通域、孔洞填充、器官拓扑约束或解剖学冲突处理。若具体任务需要这些规则，应作为明确、可关闭的后处理层单独设计，不能假设 nnInteractive 已经处理。

## 13. 依据

- [nnInteractive 官方仓库](https://github.com/MIC-DKFZ/nnInteractive)
- [nnInteractive server-client 文档](https://github.com/MIC-DKFZ/nnInteractive/blob/master/SERVER_CLIENT.md)
- [nnInteractive API v2 变更说明](https://github.com/MIC-DKFZ/nnInteractive/blob/master/API_CHANGES_v2.md)
- [nnInteractive 2.4.2 on PyPI](https://pypi.org/project/nninteractive/2.4.2/)
- [Mimics Research 21 Python API 本地手册](../references/mimics/api_21/Mimics_API_Documentation.md)
