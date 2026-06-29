# DINOv3 Few-Shot Segmenter for Mimics Research 21

## 1. 结论

**DINOv3 Few-Shot Segmenter** 是一个独立 Mimics 功能，目标是在 Mimics 内形成“少量人工标注样本 -> 本地训练 -> 新病例初始分割 -> 人工修正 -> 再加入样本”的闭环。

它不依赖 SegmentationPlatform 的 Registry、Snapshot、病例包、Review、Label Artifact 或任务队列。只要 Mimics 当前打开了图像和 Mask，用户就可以使用它。

推荐第一版定位：

- Mimics Python 3.5 只负责用户交互、读取当前 Image/Mask、写回预测 Mask；
- 外部 Python 3.10+ 环境负责 DINOv3 训练、推理、NIfTI 写入和模型管理；
- 本地 workspace 保存训练样本、模型版本、训练任务、推理日志；
- 每个器官先训练一个二分类模型，不做全身多器官模型；
- 训练在后台执行，不阻塞 Mimics 标注工作；
- 标注者不需要理解训练参数、权重路径或数据目录。

这与 nnInteractive 的关系是并列的：

| 工具 | 主要作用 | 数据范围 | 用户交互 |
| --- | --- | --- | --- |
| nnInteractive | 单病例交互式分割修正 | 当前图像和当前 Mask | 点、框、涂抹、套索 |
| DINOv3 Few-Shot Segmenter | 跨病例学习某个器官的初始分割模型 | 本地积累的样本库 | 加入样本、训练模型、应用模型 |

## 2. 设计目标

### 2.1 必须做到

1. 独立运行在 Mimics 中，不要求平台项目存在。
2. 标注者只在 Mimics UI 内操作，不执行命令行。
3. 数据选择基于当前 Mimics 上下文，不扫描大型外部数据集。
4. 器官选择尽量自动推断，必要时让用户确认。
5. 本地维护样本库和模型库，模型权重不覆盖旧版本。
6. 训练和推理都可异步运行，避免 Mimics 长时间卡死。
7. 推理结果写回 Mimics 为可编辑 Mask，而不是自动当成最终标签。
8. 错误原因要对用户可读，同时保留技术日志供开发者定位。

### 2.2 第一版不做

1. 不接入平台 Registry/Snapshot/Review。
2. 不要求标注者分配任务、提交任务或管理病例包。
3. 不做多器官联合训练。
4. 不做实时在线学习，不是每画一笔就训练一次。
5. 不做复杂主动学习和样本自动打分。
6. 不直接在 Mimics Python 3.5 中安装 PyTorch/DINOv3。
7. 不假设可以向 Mimics 原生 Segment 工具栏注册自定义图标。

## 3. 当前 DINOv3 项目的能力边界

参考 `/Users/ruanshijian/projects/dinov3-medical-seg` 当前实现，它更适合作为本功能的本地训练引擎，而不是直接嵌入 Mimics Python。

当前能力：

- 使用 DINOv3 ViT backbone；
- 支持 `frozen`、`lora`、`adapter`、`full` 微调；
- 支持 `linear3d`、`mlp_probe`、`segformer3d`、`dpt3d` decoder；
- 数据输入是 NIfTI 目录：
  - `imagesTr/`
  - `labelsTr/`
  - `imagesTs/`
  - `labelsTs/`
- `scripts/train.py` 支持 `--data.k_shot`；
- `scripts/infer.py` 支持单个 NIfTI 输入和输出。

重要限制：

- 当前 few-shot 是普通监督小样本微调，不是原型网络或元学习；
- 默认更适合单器官二分类，`num_classes: 2`；
- 训练和推理都依赖现代 PyTorch，不适合 Mimics Python 3.5；
- 当前推理归一化较粗，CT/MRI 最终需要更明确的预处理策略；
- 当前没有本地样本库、模型索引、后台任务和 Mimics buffer bridge。

因此第一版应把它封装成外部 AI 引擎：

```text
Mimics script
  -> export current image/mask buffers
  -> external DINOv3 bridge
  -> local few-shot workspace
  -> train/infer
  -> import predicted mask back to Mimics
```

## 4. 本地目录结构

建议把功能打包为一个可复制目录，例如：

```text
DINOv3FewShot/
  DINOv3_FewShot.py
  runtime_py35/
    dinov3_fewshot_mimics.py
  bridge/
    dinov3_fewshot_bridge.py
  dinov3_medical_seg/
    scripts/
    src/
    config/
    models/
  dinov3_env/
    python/
    Scripts/
  workspace/
    config.json
    organ_aliases.json
    samples/
    models/
    jobs/
    logs/
```

职责划分：

| 目录 | 职责 |
| --- | --- |
| `runtime_py35/` | Mimics Python 3.5 侧代码 |
| `bridge/` | 外部 Python 侧训练/推理/模型管理 |
| `dinov3_medical_seg/` | DINOv3 训练代码副本或子模块 |
| `dinov3_env/` | 可迁移 Python 环境 |
| `workspace/samples/` | 本地少样本训练样本 |
| `workspace/models/` | 本地模型版本 |
| `workspace/jobs/` | 后台训练/推理任务 |
| `workspace/logs/` | 用户日志和开发者日志 |

这个 workspace 是该工具自己的本地状态，不是平台 Registry。

## 5. Mimics 用户入口

可靠入口：

```text
Script -> Scripting Library -> DINOv3 Few-Shot Segmenter
```

Mimics Research 21 的公开 Python API 可以注册 Scripting Library 脚本，但没有可靠证据表明能把自定义按钮注册到 `Segment` 或 `Advanced Segment` 原生工具栏。因此第一版不承诺工具栏图标。

入口打开后建议只提供四类动作：

| 动作 | 用户含义 |
| --- | --- |
| `Add Current Mask as Sample` | 把当前图像和当前 Mask 加入某个器官的训练样本库 |
| `Train or Update Model` | 用某个器官的本地样本后台训练新模型 |
| `Segment Current Image` | 用已训练模型对当前图像生成初始 Mask |
| `Manage Samples and Models` | 查看样本、禁用样本、选择默认模型、归档旧模型 |

不要在主菜单暴露学习率、epoch、checkpoint 路径、GPU 参数。高级参数可以写在 `workspace/config.json`，由开发者或实施者维护。

## 6. 数据选择

### 6.1 基本原则

独立工具不管理大型数据集，只管理用户主动加入的 Mimics 当前数据。

数据来源固定为：

1. 当前打开的 Mimics Project；
2. 当前 active Image Set；
3. 用户选中的 Mask；
4. 本地 workspace 中已经保存的样本和模型。

用户不需要选择外部路径，也不需要知道图像文件原始来源。

### 6.2 加入训练样本

入口：

```text
Add Current Mask as Sample
```

流程：

```text
读取当前 active image
  -> 读取用户选中的 Mask
  -> 推断或确认器官
  -> 检查 Mask 非空
  -> 检查 Mask 与图像 shape 一致
  -> 导出 image 和 binary label
  -> 写入 samples/{organ}/{sample_id}/
```

样本记录示例：

```json
{
  "schema_version": "dinov3_fewshot_sample.v1",
  "sample_id": "liver_20260629_001",
  "organ": "liver",
  "image_name": "CT Venous",
  "mask_name": "Liver",
  "source_project": "case_001.mcs",
  "created_at": "2026-06-29T10:00:00Z",
  "enabled": true,
  "image_path": "image.nii.gz",
  "label_path": "label.nii.gz",
  "geometry": {
    "shape": [512, 512, 260],
    "source": "mimics_buffer",
    "physical_space_status": "unknown_or_partial"
  }
}
```

### 6.3 多序列项目

如果当前 Mimics 项目中有多个 Image Set：

- 默认使用 active image；
- 如果当前 Mask 绑定了某个 image，则优先使用 Mask 绑定的 image；
- 如果无法判断，弹窗列出 Image Set 名称、shape 和序列描述。

标注者选择的是 Mimics 中可见的图像名称，不选择磁盘路径。

## 7. 器官选择

### 7.1 自动推断优先

器官选择按以下优先级：

1. 从当前 Mask 名称推断；
2. 从本地 `organ_aliases.json` 归一化；
3. 从已有样本库或模型库选择；
4. 无法判断时让用户手动选择或输入。

示例别名：

```json
{
  "liver": ["liver", "Liver", "肝", "肝脏", "mask_liver"],
  "spleen": ["spleen", "Spleen", "脾", "脾脏"],
  "kidney_left": ["left kidney", "kidney_l", "左肾"]
}
```

### 7.2 用户确认

当工具从 Mask 名称推断出器官时，只需要轻量确认：

```text
Use organ: liver?

Buttons:
Confirm / Change
```

如果用户选择 `Change`，弹出本地已有器官列表，并允许新增器官。

### 7.3 单器官二分类

第一版每个模型只对应一个器官：

```text
liver samples  -> liver model
spleen samples -> spleen model
kidney samples -> kidney model
```

原因：

- 当前 DINOv3 项目默认适合 `background + organ` 二分类；
- Mimics Mask 天然按器官编辑；
- 少样本条件下单器官模型更稳定；
- 避免多器官部分缺标、类别不均衡和 label map 管理问题。

## 8. 训练流程

### 8.1 用户视角

入口：

```text
Train or Update Model
```

用户只选择器官：

```text
Choose organ:
- liver: 6 enabled samples
- spleen: 3 enabled samples
- kidney_left: 2 enabled samples
```

默认行为：

- 使用该器官所有 `enabled=true` 样本；
- 自动生成 DINOv3 训练目录；
- 后台启动训练；
- Mimics 立即返回，用户可继续工作；
- 用户稍后通过同一入口查看训练状态。

### 8.2 训练数据导出

外部 bridge 把本地样本库整理成 DINOv3 项目需要的目录：

```text
job_xxx/data/
  imagesTr/
  labelsTr/
  imagesTs/
  labelsTs/
```

训练 label 始终是二分类：

```text
0 = background
1 = selected organ
```

### 8.3 默认训练策略

第一版推荐默认配置：

| 项 | 默认值 | 理由 |
| --- | --- | --- |
| backbone | DINOv3 ViT-B/16 | 速度和效果平衡 |
| fine-tuning | LoRA | 权重小，适合反复训练 |
| decoder | segformer3d | 当前项目推荐默认 |
| num_classes | 2 | 单器官二分类 |
| epoch | 小样本短训练，例如 10-30 | 控制等待时间 |
| validation | 自动留出 1 个或少量样本 | 防止完全无质量反馈 |

如果样本数少于 2 个：

- 工具提示“样本过少，模型可能不稳定”；
- 可以允许开发者模式继续训练；
- 默认不建议设为 default 模型。

### 8.4 后台任务

训练任务写入：

```text
workspace/jobs/train_{timestamp}/
  request.json
  status.json
  stdout.log
  stderr.log
  data/
  outputs/
```

`status.json` 示例：

```json
{
  "schema_version": "dinov3_fewshot_job.v1",
  "job_id": "train_20260629_001",
  "type": "train",
  "organ": "liver",
  "status": "running",
  "stage": "epoch_4_of_20",
  "started_at": "2026-06-29T10:05:00Z"
}
```

Mimics 侧只轮询状态，不阻塞等待完整训练。

## 9. 模型管理

### 9.1 版本目录

每次训练生成一个新模型版本：

```text
workspace/models/liver/model_0003/
  model_manifest.json
  config.yaml
  best_model.pth
  metrics.json
  training_samples.json
  logs/
```

### 9.2 模型状态

模型状态建议：

| 状态 | 含义 |
| --- | --- |
| `candidate` | 新训练完成，尚未设为默认 |
| `default` | 当前器官默认推理模型 |
| `archived` | 旧模型，不再默认使用 |
| `failed` | 训练失败或不可用 |

同一器官只能有一个 `default` 模型。设置新模型为 `default` 时，旧模型自动变为 `archived`。

### 9.3 模型记录

`model_manifest.json` 示例：

```json
{
  "schema_version": "dinov3_fewshot_model.v1",
  "model_id": "liver_model_0003",
  "organ": "liver",
  "status": "candidate",
  "algorithm": "dinov3-medical-seg",
  "base_model": "dinov3-vitb16",
  "finetune_method": "lora",
  "decoder": "segformer3d",
  "checkpoint_path": "best_model.pth",
  "checkpoint_hash": "sha256:...",
  "sample_ids": ["liver_001", "liver_002", "liver_003"],
  "metrics": {
    "mean_dice": 0.82
  },
  "created_at": "2026-06-29T11:00:00Z"
}
```

## 10. 推理流程

### 10.1 用户视角

入口：

```text
Segment Current Image
```

流程：

```text
读取当前 active image
  -> 选择或推断器官
  -> 查找该器官 default 模型
  -> 导出当前图像 buffer
  -> 外部 Python 推理
  -> 写回新的 Mimics Mask
```

输出 Mask 命名：

```text
DINOv3 liver prediction
```

如果当前已有同名 Mask：

- 默认创建新版本，例如 `DINOv3 liver prediction 2`；
- 不覆盖人工 Mask；
- 用户可自行复制、合并、修正。

### 10.2 推理结果的语义

推理结果只是初始分割，不是最终标签。

推荐用户流程：

```text
Segment Current Image
  -> 生成 prediction Mask
  -> 人工修正
  -> 修正后可 Add Current Mask as Sample
```

不要把未经修正的预测结果自动加入训练样本库。

### 10.3 无模型时的行为

如果某器官没有可用模型：

```text
No model is available for liver.

Add several verified masks as samples, then train a model.
```

不自动触发训练，避免用户误以为推理正在进行。

## 11. 样本管理

入口：

```text
Manage Samples and Models
```

第一版只需要支持：

- 查看每个器官的样本数量；
- 查看样本名称、来源项目、创建时间；
- 启用/禁用样本；
- 删除误加入但未参与训练的样本；
- 查看模型版本；
- 设置某个模型为 default；
- 归档旧模型。

样本默认不自动删除。禁用样本不影响历史模型，只影响下一次训练。

## 12. 异常和用户提示

### 12.1 加入样本失败

需要给出清楚原因：

| 失败原因 | 用户提示 |
| --- | --- |
| 没有图像 | 当前 Mimics 项目没有可用 Image Set |
| 没有选 Mask | 请先选择一个要加入训练的 Mask |
| Mask 为空 | 当前 Mask 为空，不能作为训练样本 |
| shape 不一致 | Mask 与图像尺寸不一致，请检查 Mask 绑定 |
| 器官无法识别 | 请选择或输入器官名称 |

### 12.2 训练失败

用户看到简短原因：

```text
Training failed for liver.
Reason: CUDA out of memory.
Log: workspace/logs/train_20260629_001.log
```

开发者日志保留 stdout/stderr 和完整 traceback。

### 12.3 推理失败

常见原因：

- 没有 default 模型；
- 外部 Python 环境不可用；
- GPU 显存不足；
- 输入图像过大；
- checkpoint 损坏；
- 模型器官和用户选择不一致。

推理失败不应修改当前 Mask。

## 13. 环境和生命周期

### 13.1 外部 Python 环境

必须使用外部 Python 3.10+ 环境运行 DINOv3 和 PyTorch。

Mimics Python 3.5 侧只调用外部 bridge，不安装 torch、nibabel 或 transformers。

### 13.2 后台进程

建议两类后台进程：

| 进程 | 生命周期 |
| --- | --- |
| training job | 每次训练单独启动，完成后退出 |
| inference worker | 可按模型短期复用，空闲后退出 |

训练不建议常驻。推理 worker 可复用模型加载结果，但必须有 idle timeout。

推荐默认：

- inference worker idle timeout: 30 分钟；
- DINOv3 model cache: 每个器官最多保留一个活跃 worker；
- Mimics 正常退出时写 close request；
- Mimics 崩溃时依靠 idle timeout 自清理。

## 14. 与平台的边界

本功能第一版完全独立：

| 能力 | 是否依赖平台 |
| --- | --- |
| 打开 Mimics 图像 | 否 |
| 添加训练样本 | 否 |
| 训练 DINOv3 模型 | 否 |
| 管理本地模型 | 否 |
| 当前图像推理 | 否 |
| 写回 Mask | 否 |

未来可以增加可选同步能力：

- 把本地样本导出为平台 Label Artifact；
- 把本地模型登记为平台 Model Record；
- 从平台拉取 verified label 初始化样本库；
- 把推理结果回流为 candidate label。

这些都必须是可选项，不能成为本地 Mimics 功能运行的前提。

## 15. MVP 实现清单

### 15.1 Mimics 侧

- `DINOv3_FewShot.py`
  - Scripting Library 入口。
- `runtime_py35/dinov3_fewshot_mimics.py`
  - 主菜单；
  - 当前 image/mask 选择；
  - 器官推断和确认；
  - buffer 导出；
  - 预测 Mask 写回；
  - 后台 job 状态查看。

### 15.2 外部 Python 侧

- `bridge/dinov3_fewshot_bridge.py`
  - `add_sample`
  - `train`
  - `infer`
  - `list_samples`
  - `list_models`
  - `set_default_model`
- DINOv3 数据导出器
  - 本地样本 -> `imagesTr/labelsTr/imagesTs/labelsTs`
- 模型索引
  - 每个器官维护模型版本和 default 模型。

### 15.3 配置

`workspace/config.json` 最小字段：

```json
{
  "schema_version": "dinov3_fewshot_config.v1",
  "python_executable": "dinov3_env/python/python.exe",
  "dinov3_project_root": "dinov3_medical_seg",
  "default_config": "config/synthstrip_lora_segformer3d.yaml",
  "default_epochs": 20,
  "minimum_recommended_samples": 3,
  "inference_worker_idle_seconds": 1800
}
```

## 16. 推荐的第一版用户流程

### 16.1 从零开始

```text
1. 用户在 Mimics 中打开病例 A。
2. 用户人工标注 liver Mask。
3. 运行 DINOv3 Few-Shot Segmenter。
4. 选择 Add Current Mask as Sample。
5. 工具自动识别器官 liver，用户确认。
6. 用户继续标注病例 B、C，并重复加入样本。
7. 样本达到 3-5 例后，用户选择 Train or Update Model -> liver。
8. 后台训练完成，生成 liver/model_0001。
9. 用户打开病例 D。
10. 选择 Segment Current Image -> liver。
11. 工具生成 DINOv3 liver prediction。
12. 用户修正该 Mask。
13. 修正后再次 Add Current Mask as Sample。
14. 后续重新训练 liver/model_0002。
```

### 16.2 日常使用

```text
打开新病例
  -> Segment Current Image
  -> 修正预测 Mask
  -> Add Current Mask as Sample
  -> 继续下一个病例
```

训练可以每天或每积累若干样本后执行一次，不要求每个病例后立即训练。

## 17. 风险和待验证问题

| 风险 | 影响 | 第一版处理 |
| --- | --- | --- |
| Mimics buffer 缺少完整物理空间 | NIfTI affine 可能不等价于原始 DICOM | 本地训练和本地推理使用同一导出约定，先保证 index-space 一致 |
| CPU 训练很慢 | 用户等待时间长 | 训练后台化，推荐 GPU |
| 样本质量不稳定 | 模型学到错误 | 只由用户显式加入样本，提供禁用样本 |
| 单器官模型很多 | 模型目录变多 | 每个器官只保留一个 default，旧模型归档 |
| 当前 DINOv3 预处理粗糙 | CT/MRI 泛化受影响 | 第一版记录模态和强度范围，后续按模态补预处理 |
| 小样本过少 | 模型不稳定 | 少于阈值提示，不自动设为 default |

## 18. 一句话原则

**标注者只负责判断当前 Mimics 中哪个 Mask 值得加入样本、当前图像要不要用已有模型生成初始分割；训练数据组织、权重路径、模型版本和后台任务都由本地 DINOv3 Few-Shot 工具自动管理。**
