# 医学影像标注平台设计说明

> 面向 Mimics Research 21 工作站 + AI 辅助分割的完整标注系统。
> 本文档面向技术决策者，说明系统设计目标、架构决策、当前能力和待完成事项。
> 不包含具体实现的代码细节、测试统计或 commit 历史。

## 1. 系统定位与目标

### 1.1 核心目标

构建一套完整的医学影像标注闭环系统，覆盖从数据摄入、标注分发、工作站编辑、AI 辅助分割到 QC 收尾与标签版本登记的全流程。

**关键指标：**

| 维度 | 目标 |
|------|------|
| 标注者体验 | 只需 Mimics 软件本身，无需安装 Python、配置环境变量或理解文件格式 |
| 交互次数 | 标准病例打开 → 编辑 → 提交三步完成，无多余的中间菜单选择 |
| 错误可诊断性 | 任何失败都能追溯到具体阶段，不出现 "connection refused" 这类无上下文错误 |
| 数据完整性 | 每个标签都有完整的 provenance chain（来源、基础版本、提交动作、QC 结果） |
| AI 辅助效率 | 标注者在 Mimics 内一键启动 AI 工具，GPU 推理 4-10 秒 / 次，CPU 约 6 分钟 / 次 |
| 可并行性 | 多位标注者独立工作，互不阻塞；平台侧可分批收回、独立 QC |

### 1.2 系统边界

本系统覆盖：

- 数据摄入（DICOM → Case Package → Registry）
- 病例包创建与管理
- Mimics 工作站空间映射校准
- 标注任务分发与回收
- Mimics 21 内标注操作（打开、编辑、提交、灾备、任务导航）
- nnInteractive AI 交互分割工具集成
- 提交后 QC、标签版本登记与 Registry 更新

本系统不覆盖：

- 模型训练或算法开发
- PACS / DICOM 路由
- 标注者身份认证与权限管理
- 多标注者仲裁与共识机制
- Web 端标注界面

---

## 2. 架构设计

### 2.1 双 Python 环境隔离

系统最根本的架构约束来自 Mimics Research 21 内置 Python 3.5.2，无法安装 PyTorch、nnInteractive 等现代依赖。因此采用严格的双环境隔离：

| 环境 | 位置 | 职责 |
|------|------|------|
| 平台环境 (Python 3.10+) | 平台准备/QC 机器 | Case Package 管理、Registry 操作、空间校验、NIfTI 转换、标签登记 |
| Mimics 环境 (Python 3.5.2) | 标注机 Mimics 内 | DICOM 导入、Mask 创建编辑、提示采集、结果写回、弹窗交互 |

**设计原则：**

- Mimics 内代码不导入平台模块，不读取 Registry，不进行医学格式转换
- 平台代码不假设 Mimics 会话状态，不直接操作 `.mcs` 文件
- 两者通过 Case Package 中的文件（`.u8` buffer、JSON manifest）交换数据

### 2.2 Case Package 作为数据交换中枢

Case Package (v0.5) 是所有数据交换的标准化容器：

```text
case_package/
  manifest.json           ← 图像集、器官清单、标签映射
  images/                 ← DICOM 源文件
  labels/{image_id}/      ← 已有标签（NIfTI + .u8 buffer）
  working/                ← Mimics 运行时数据
  submissions/{review_id}/← 标注提交（buffer + manifest）
  reports/                ← 诊断与 QC 报告
```

**设计决策：**

- 一个 Case Package 承载一个病例。多个 review 可以是同一个 Case Package 的不同标注轮次。
- 提交 buffer 使用相对路径保存，确保工作包在不同机器间迁移后仍可回溯。
- Case Package 不依赖数据库或 Registry 即可独立工作，使离线标注成为可能。

### 2.3 工作包导出与离线标注

标注机不需要安装平台 Python、Registry 或网络连接。工作包是自包含的目录：

```text
worklist/
  Labeling_Open_Next_Case.py
  Labeling_Case_Navigation.py
  Labeling_Submit_Complete.py
  Labeling_Submit_or_Report_Issue.py
  Labeling_View_Task_List.py
  Labeling_Save_Recovery_Backup.py
  nnInteractive.py                    ← AI 工具入口（若可用）
  nninteractive_bridge.py             ← AI 推理桥接（若可用）
  runtime_py35/                       ← Mimics 内部实现
  cases/                              ← Case Package
  worklist_manifest.json              ← 平台冻结的任务清单
  worklist_progress.json              ← 本地进度（可重建）
```

**设计决策：**

- 脚本名即动作语义。标注者不需要理解功能菜单层级——要做什么就运行什么。
- 高频路径（打开、提交）直达，不做中间菜单。低频路径（任务查看、灾备、跳过）各自独立入口。
- 本地进度是可重建的——工作包丢失后重发不依赖标注机上的文件。

### 2.4 空间映射校准

Mimics 内部的 voxel buffer 轴序和方向有 48 种可能排列。平台通过一次性探针验证，确定唯一的坐标映射关系：

```
工作站准备 → Doctor（API 可用性检查）
           → ProbeRun（P01-P06 完整探针）
           → ProbeEvaluate（与 DICOM LPS 几何比较，误差 < 0.001 mm）
           → Verified Config（冻结此工作站的 buffer mapping）
```

只有 verified 配置才能用于正式标注。Mimics 版本、插件或工作站硬件变更后必须重新探针。

---

## 3. 标注流程设计

### 3.1 完整闭环

```
平台操作者                               标注者
─────────                               ──────
数据摄入 → Case Package → Registry
   ↓
Prepare（转 .u8 buffer + runtime）
   ↓
Prebuild（可选：预生成 .mcs）
   ↓
Export Worklist ─────────────────────→  接收工作包
                                         ↓
                                     Mimics 内：
                                     - 打开病例
                                     - AI 辅助分割
                                     - 手工编辑 Mask
                                     - 保存 .mcs
                                     - 提交 / 标记问题
                                         ↓
Collect Submissions ←────────────────  返回工作包
   ↓
Finalize（QC + Label Artifact 登记）
   ↓
Registry 更新
```

### 3.2 标注者操作路径

**标准路径（单 target + 已确认）：**

1. `Labeling_Open_Next_Case` → 查看任务摘要 → 开始编辑
2. 使用 Mimics 工具或 `nnInteractive` AI 辅助修正 Mask
3. `Labeling_Submit_Complete` → 导出 → 完成

**异常路径：**

| 场景 | 操作 |
|------|------|
| 医学不确定 | `Submit_or_Report_Issue` → Needs Review |
| 数据/工具阻塞 | `Submit_or_Report_Issue` → Report Problem |
| 暂不处理本病例 | `Case_Navigation` → Skip Case |
| 忘记任务范围 | `View_Task_List` |
| 长时间工作后保护 | `Save_Recovery_Backup` |
| 中途关闭后继续 | `Case_Navigation` → Continue / Choose Case |

**设计决策：**

- 提交前自动聚合预检（Mask 完整性、绑定关系、shape 一致性），不合格项弹窗告知
- 提交使用 staging 目录 + 原子重命名，Mimics 崩溃不会生成半成品提交
- 空 Mask 必须显式确认（"确认不存在" / "待复查"），不允许静默跳过
- Skip 与 Report Problem 是不同语义：前者是"I'll come back later"，后者是"需要外部处理才能继续"

### 3.3 标签生命周期

```
[数据摄入] → in_progress
                ↓ 标注者提交 Complete + QC 通过
           verified_label
                ↓ 管理员创建返修任务 → superseded
           in_progress (new review, old as base_label)
                ↓ 标注者提交 Complete + QC 通过
           verified_label (新版本)
```

```
                ↓ 标注者提交 Needs Review
           draft_label → [人工审核] → verified_label
                ↓ 标注者提交 Report Problem
           blocked → [管理员处理阻塞原因]
```

- verified_label 不可覆盖；修改只能通过创建新 review 并标记旧标签为 superseded
- base_label → new_label 形成完整的 provenance chain
- 追加器官通过 create-followup 创建新 review，已完成的器官不丢失

---

## 4. nnInteractive AI 辅助分割设计

### 4.1 核心约束与方案

| 约束 | 解决方案 |
|------|----------|
| Mimics Python 3.5 无法装 PyTorch | 双进程：Mimics 侧采集提示 → 外部 Python 3.10+ 推理 |
| 现代模型需要 GPU 显存 | 外部 worker 进程管理 GPU，Mimics 侧不与 torch 交互 |
| 推理可能耗时数分钟 (CPU) | 异步模式：提示采集后立即返回，推理完成后自动写回 |
| Mimics 无原生进度条 API | 后台轮询 + Log Panel 状态记录 |
| Windows 部署简化 | 一键安装脚本 + 离线 bundle 构建，标注者只需解压 |

### 4.2 提示类型与采集方式

| AI 提示类型 | Mimics 采集方式 | 语义 |
|-------------|----------------|------|
| Point Set | `indicate_coordinate()` 多次采集，正(绿)/负(红) | 精确指定前景/背景位置 |
| Scribble Set | `activate_edit_mask(Ellipse, Draw)` 绘涂区域 | 大范围前景/背景区域 |
| Foreground Box | `indicate_distance_measurement()` 两端点矩形 | 框选前景器官范围 |
| Foreground Lasso | `indicate_spline(closed=True)` 闭合轮廓 | 勾勒器官边界 |

**设计决策：**

- Point Set 支持一次会话中混合正负点，所有点放置完毕后一次性触发一次预测
- Scribble 使用 Prompt Mask + Ellipse 工具（Mimics 无自由画笔 API），绘制完成后立即删除 Prompt Mask，目标 Mask 只接收模型结果
- Box 和 Lasso 固定为前景语义，排除区域使用 Exclude Points 或 Exclude Scribble
- 每条提示作为独立事件保存，支持 Undo Last Prompt 和 Reset To Start

### 4.3 连续修正的重放策略

外部 bridge 每次调用都会关闭远程 session，无法保留服务器端状态。采用等价有序重放：

1. 进入工具时保存一次目标 Mask 作为 initial segmentation
2. 每次新增提示后，新建 remote session
3. 注入同一份 initial segmentation
4. 按原顺序重放此前所有提示 → 触发本次预测 → 写回结果

**设计依据：** 每次从 initial segmentation + 全部提示重放，避免累积模型误差。提示不修改 initial segmentation，因此 Undo 只需移除提示即可回到上一步。

### 4.4 异步推理与自动写回

这是解决"标注者等待推理完成"的关键设计。

**两层异步架构：**

```
Mimics UI 线程                    外部 Worker 进程           Model Server
─────────────                     ────────────────          ────────────
选择提示 → 提交 job                    ↓
    ↓                          加载图像 + 重放提示
立即返回（标注者可继续操作）              ↓
    ↓                          调用 nnInteractive         加载模型权重
轮询结果（timer）←──────────────── 写入 result.json ────────→ 推理
    ↓
检测到结果 → 自动写回 Mask
    ↓
弹窗提示（非阻塞）
```

**Target Job（绑定一个 Mask）：** 保存 base mask、提示序列、pending sequence 和结果状态。Finish 或 Discard 结束。

**Image Worker（绑定一个 Mimics image）：** 持有外部 Python worker、远程 session 和预处理结果。同一 image 下的不同 target Mask 复用同一个 worker，不重复上传影像或重新 `set_image()`。

**Model Server（绑定模型目录 + 设备）：** 加载权重并服务远程 session。不会因为单个 target job 结束而退出；默认空闲 1 小时后释放。

**自动写回机制：** Mimics 侧通过以下任一方式周期性检测推理结果：
1. PyQt5 QTimer（利用 Mimics 21 的 Qt 事件循环）
2. Win32 SetTimer API（Windows 原生，不依赖 Qt）
3. 两种方式都不可用时：回退到用户手动重新点击 nnInteractive 入口

**设计决策：**
- 推理提交后不弹确认框，Log Panel 记录状态
- 自动写回时弹非阻塞提示框告知结果
- 空预测不报错，提示用户移动点位置
- Worker 空闲 30 分钟后自动退出，避免残留进程堆积
- 进程管理使用 PowerShell Get-CimInstance 精确定位，只杀与当前模型目录匹配的旧进程

### 4.5 后端生命周期与资源管理

```
Target Job:  创建 → queued → ready → closed/discarded/failed
Image Worker: 创建 → running → idle (30 min) → exit
Model Server: 启动 → idle (1 hour) → watchdog 确认后退出

用户关闭 Mimics:
  → 写入 close.json → Worker 接收退出请求 → 等待当前推理完成 → 退出
  → Watchdog 在空闲期后关闭 Server → 释放 GPU

Mimics 崩溃:
  → Worker 未收到 close.json → 空闲 30 分钟后自动退出
  → Server 空闲 1 小时后 watchdog 关闭
```

**设计决策：**
- 后端不依赖 Mimics 进程存活，Mimics 崩溃不会导致 GPU 永久占用
- 模型路径、PID、设备、启动时间等元数据记录在 `.nninteractive_server.json`，watchdog 基于这些信息判断是否应关闭
- 不根据来源不明的 PID 终止进程
- 端口被占用时阻断并提示，不随机选新端口（防止多个模型服务同时加载导致 OOM）

---

## 5. 质量保障设计

### 5.1 错误可诊断性

每一层失败都能追溯到具体阶段，不需要标注者猜测原因：

| 失败阶段 | 证据 | 使用者 |
|----------|------|--------|
| Mimics API 异常 | Mimics Log Panel + `nninteractive_mimics.log` | 标注者 / 开发者 |
| 外部环境检查 | 解释器路径 + 缺失包名称（在连接服务器前阻断） | 管理员 |
| Bridge 通信 | `nninteractive_bridge.jsonl`（结构化阶段 + traceback） | 开发者 |
| Worker 崩溃 | `nninteractive_worker.stderr.log` | 开发者 |
| 模型加载 / 推理 | `.nninteractive_server.log` | 开发者 |
| 提交预检 | `mimics_submit_precheck.json` | 标注者 |
| 空间 QC 失败 | `review_*_finalize.json` | 管理员 |

**设计决策：**
- 不再出现 `ConnectionRefusedError [WinError 10061]` 作为最终错误信息
- 环境检查在实际推理前完成，避免走到连接失败才发现环境不完整
- 失败弹窗直接给出失败阶段和日志路径

### 5.2 渐进式设备选择

- 默认 `device: auto`
- 有 CUDA → `cuda:0`
- 无 CUDA → CPU（自动回退，记录日志）
- 只有显式设置 `allow_cpu_fallback: false` 才会因无 GPU 而阻断
- MPS (Apple GPU) 支持自动检测和启用（40x 加速 vs CPU）

### 5.3 镜像加速与 auto-detection

部署脚本支持国内 pip 镜像，并实现分层的索引策略：
- PyTorch CUDA wheels 从官方 PyTorch index 获取（镜像通常缺少 Windows CUDA wheels）
- 常规包从镜像获取
- CUDA 版本自动检测：nvidia-smi → nvcc → CUDA_PATH → version.txt
- 安装后自动验证 `torch.cuda.is_available()`，输出诊断信息

---

## 6. 测试覆盖策略

系统设计目标要求以下层面的自动化验证：

| 测试层面 | 覆盖内容 | 执行环境 |
|----------|----------|----------|
| 单元逻辑 | Bridge JSON 协议、缓冲区映射、序列化/反序列化 | 任意 Python 3.10+ |
| 子进程通信 | Worker 持久进程、超时、异常退出、JSON 解析容错 | 任意 Python 3.10+ |
| 端到端仿真 | Mimics API 完整模拟（FakeMimics），覆盖所有提示类型、错误路径、边界条件 | 任意 Python 3.10+ |
| 异步状态机 | Job 状态流转、worker 存活检测、SHA 检测、结果自动写回、visual objects 生命周期、GUID 跟踪 | 任意 Python 3.10+ |
| 真实推理 | 实际模型权重 + HTTP 远程模式，验证所有交互类型的真实推理结果 | Windows GPU / CPU |

**设计决策：**
- 仿真测试使用 FakeMimics API（完全模拟 Mimics Python 3.5 对象模型），不依赖 Mimics 实例
- 真实推理测试使用实际 `.pt` 权重文件和 HTTP 通信，验证完整的端到端推理链路
- 异步测试覆盖状态机的所有终端状态和边缘情况

---

## 7. 待完成事项

### 7.1 Windows 实机验收（高优先级）

以下项目必须在 Mimics Research 21 Windows 实机上验证通过后，系统才能进入生产标注：

| 验收项 | 说明 |
|--------|------|
| Gate A: API 可用性 | Doctor 返回 ready，所有必需 API 在实机上可用 |
| Gate B: 空间映射 | 六个探针全部通过，ProbeEvaluate 返回唯一映射且误差 < 0.001 mm |
| Gate C: 标注闭环 | 完整走过 Open → Edit → Submit → Finalize 流程，包含带初始标签和无初始标签病例 |
| nnInteractive 实机验收 | 所有提示类型可用，模型加载成功，推理结果写回正确，异常路径处理正确 |
| Qt / Win32 Timer 稳定性 | 验证 `QTimer` 和 `Win32 SetTimer` 在 Mimics 21 中的生命周期、回调线程安全性和可靠性 |
| Ellipse Edit Masks 多区域绘制 | 确认一次 Ellipse 编辑会话中能否连续绘制多个区域 |
| Scribble 的 Cancel 行为 | 确认 `activate_edit_mask()` Cancel 时是否正常返回空 Mask 或抛异常 |
| Gray Value 强度一致性 | 验证 Mimics Gray Value 与 DICOM HU 的线性关系，确认 z-score 后等效 |

### 7.2 功能完善

| 项目 | 说明 |
|------|------|
| 3D Box 支持 | 当前 nnInteractive v1 权重仅支持 2D bbox。如果后续权重支持 3D box，Mimics 入口需要扩展 |
| 自由画笔 Scribble | 如果 Mimics 后续版本公开自由画笔 API，替换当前的 Ellipse 近似方案 |
| 原生工具栏图标 | 需与 Materialise 确认扩展 SDK，将 nnInteractive 注册为 Segment 工具栏按钮 |
| 批量 GPU 工作站管理 | 多 GPU 工作站上的模型服务调度和显存分配策略 |
| 标注质量自动检查 | 基于解剖学规则的标注异常检测（连通域、孔洞、器官边界冲突等） |

### 7.3 运维与扩展

| 项目 | 说明 |
|------|------|
| 性能基准 | 建立不同硬件配置（GPU/CPU/MPS）下的各阶段耗时基线 |
| 多站点部署 | 多台标注工作站的分发策略、Registry 同步和冲突处理 |
| 标注者培训材料 | 基于实机验收结果制作标注员操作手册和常见问题指南 |
| 模型升级流程 | nnInteractive 权重升级时的兼容性验证和灰度发布策略 |
| 大规模并发 | 10+ 标注者并行时的 Registry 锁策略和工作包分发效率 |
| 断点续传标注 | 标注进程崩溃后自动恢复到最近 checkpoint，减少手工维护 |

---

## 8. 风险与缓解

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| Mimics 21 Timer API 不可靠 | 自动写回失败，标注者需手动检查 | 保留回退机制（手动重新点击）；Log Panel 明确提示 |
| CPU 推理 6 分钟/次 | 标注效率明显降低 | GPU 优先；`allow_cpu_fallback` 可关闭；异步模式不阻塞 UI |
| Mimics 版本升级 | API 行为变化，探针可能失败 | 重新运行探针；verified config 包含 Mimics 版本信息 |
| 模型推理与 Mimics 编辑并发 | 光标闪烁或 UI 延迟 | 异步架构隔离；worker 在独立进程中运行 |
| Windows 镜像缺少 CUDA wheel | 部署失败，装成 CPU 版 PyTorch | 分层索引策略（PyTorch CUDA 从官方 index）；安装后自动验证 |
| 多模型服务 OOM | 工作站卡死 | 端口占用时阻断而不是开新端口；旧进程自动清理 |

---

## 9. 关键技术选型理由

| 选择 | 理由 |
|------|------|
| Case Package 而非数据库 | 离线标注必须有文件自描述能力；数据库增加标注机依赖 |
| `.u8` buffer 而非 NIfTI | Mimics API 原生 dtype；避免 Mimics 侧引入 nibabel 依赖 |
| 双进程 + JSON stdin/stdout | 最简单可靠的跨进程通信；不依赖网络栈或消息队列 |
| HTTP remote mode (实际推理) | nnInteractive 官方唯一支持的远程推理协议 |
| 异步 + Timer 自动写回 | Mimics 无原生回调或事件机制；timer 是唯一不阻塞 UI 的轮询手段 |
| 固定版本 nninteractive==2.4.2 | 避免 `>=` 版本漂移改变预处理/后处理行为 |
| Gray Value 原样传递（缓转 HU） | nnInteractive 内部做 z-score；线性关系下等效，避免引入零值判定偏差 |
| 每次重放全部提示 | 比增量预测更正确；避免累积误差；Undo 实现简单 |
| 端口占用阻断 | 多个模型服务会导致 OOM；阻断比自动选端口更安全 |
