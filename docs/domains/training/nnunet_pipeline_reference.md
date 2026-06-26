# 现有 nnUNet 训练与推理管线

> 日期：2026-06-13
> 状态：当前代码的实现说明，不是平台总体设计
> 适用读者：准备维护 `pipelines/nnunet/`，或实现 nnUNet 工具适配器的开发者

## 1. 先理解这份文档的边界

当前代码已经能够完成：

1. 把逐器官标注转换为 nnUNet 数据格式。
2. 运行 nnUNet 规划和预处理。
3. 训练模型。
4. 对单个模型或多个模型运行推理。
5. 计算基础 Dice 并生成报告。

它适合作为平台的 nnUNet 训练核心，但还不是完整的平台训练入口。下面四个问题必须由平台工具适配器补齐：

| 当前限制 | 实际风险 | 平台接入要求 |
| --- | --- | --- |
| 缺少 `meta.csv` 时随机划分病例 | 随机种子未固定，也不保证同一患者的不同检查留在同一侧 | 正式训练只使用训练数据快照中固定的患者级划分 |
| 缺少某个器官 mask 时跳过该文件 | 输出中相应区域仍是背景 0，会把“没有标注”误当成“器官不存在” | 导出前检查目标器官是否完整；不完整病例默认排除 |
| `dataset.json` 的名称、描述和许可存在硬编码 | 生成文件不能反映真实数据来源 | 由工具适配器根据训练数据快照生成真实元数据 |
| Surface Dice 依赖导入被注释 | 运行可能失败或产生空指标 | 修复并测试前，只把 Dice 当作可用的基础指标 |

正式评估还要检查患者泄漏和参考标签来源，并创建独立评估记录。本文只描述当前代码怎样运行。

## 2. 管线由哪些文件组成

### 2.1 主流程

| 文件 | 作用 |
| --- | --- |
| `AutoSegmentationFramework.py` | 读取配置，按顺序调用数据转换、预处理、训练、预测和评估 |
| `Action1_ConvertLabeledToTrainData.py` | 把现有标注目录转换为 nnUNet 数据集 |
| `Action2_PlanAndPreprocess.py` | 调用 nnUNet 数据指纹、实验规划和预处理 |
| `Action3_Train.py` | 设置设备和线程，调用 nnUNet 训练 |
| `Action4_Predict.py` | 提供单模型、多模型和预重采样推理 |
| `Action5_Evaluation.py` | 计算 Dice、尝试计算 Surface Dice，并生成评估报告 |

### 2.2 辅助工具

| 文件 | 作用 |
| --- | --- |
| `ResampleImageAndMask.py` | 重采样图像和 mask |
| `SetEnvionmentVariables.py` | 设置 nnUNet 目录和运行环境变量 |
| `ImageConvertor.py` | 图像格式转换、裁剪和 spacing 修正 |
| `MaskOperation.py` | 标签重映射、合并和形态学处理 |
| `DicomToMhd.py` | 把 DICOM 序列转换为 MHD 或 NIfTI |

### 2.3 配置文件

| 文件 | 作用 |
| --- | --- |
| `Config_*.toml` | 定义路径、模态、任务、GPU、预处理、训练、推理和评估参数 |
| `ModelMap.toml` | 定义每个局部模型负责哪些器官，以及训练时使用的整数标签 |

## 3. 总体执行顺序

```mermaid
flowchart LR
    accTitle: 现有 nnUNet 管线执行顺序
    accDescr: 配置和任务标签表交给主编排脚本，依次完成数据转换、预处理、训练、预测和评估。

    config["配置文件与 ModelMap"]
    framework["主编排脚本"]
    convert["1. 数据转换"]
    preprocess["2. 规划与预处理"]
    train["3. 训练"]
    predict["4. 推理"]
    evaluate["5. 基础评估"]

    config --> framework
    framework --> convert
    convert --> preprocess
    preprocess --> train
    train --> predict
    predict --> evaluate
```

每个步骤都可以单独调用。四种预定义工作流只是组合了不同步骤，见第 9 章。

## 4. 配置怎样工作

### 4.1 配置分区

每个训练任务使用一个 TOML 配置文件。主要分区如下：

```toml
[COMMON]       # CT 或 MR 等通用设置
[PATHS]        # 标注数据、训练数据和 nnUNet 目录
[MODEL]        # 数据集名称、任务名称和 ModelMap
[GPU]          # GPU 分配
[PREPROCESS]   # spacing、patch size、batch size 和方向
[TRAIN]        # epoch、fold、trainer 和 plans
[PREDICT]      # 推理与统计开关
[EVALUATION]   # 评估目录和聚合开关
```

### 4.2 配置加载步骤

主编排脚本加载配置时：

1. 读取 `Config_*.toml`。
2. 读取 `ModelMap.toml`。
3. 根据 `segment_list_name` 找到当前任务负责的器官和标签值。
4. 根据基础路径和数据集名称构建 nnUNet 目录。
5. 保存一份带时间戳的 JSON 配置快照。
6. 生成运行时配置对象。

配置快照能帮助追溯一次运行使用了哪些参数，但它不能替代平台的训练数据快照。后者还要固定病例、标签版本和患者划分。

### 4.3 `ModelMap.toml` 的两种写法

细粒度任务中，每个器官使用独立标签：

```toml
[CT1_Head]
brain = 1
skull = 2
```

粗分割任务中，多个器官可以合并为一个区域：

```toml
[CT_All_Coarse]
head = { label = 1, organs = ["brain", "skull"] }
chest = { label = 2, organs = ["heart", "aorta"] }
```

每个局部模型内部的前景标签从 1 开始，0 表示背景。不同模型可以重复使用相同整数。`CT_Combine` 和 `MR_Combine` 用于合并多个模型的输出，不用于单个模型训练。

## 5. 第一步：转换标注数据

### 5.1 输入

当前转换脚本期望每个病例包含：

```text
patient/
  ct.nii.gz
  segmentations/
    liver.nii.gz
    gallbladder.nii.gz
```

配置决定：

- 原始标注目录。
- 当前任务需要哪些器官。
- 是否重采样。
- 是否调整图像方向。
- 训练、验证和测试划分。

### 5.2 处理顺序

1. 读取病例划分。
2. 加载图像和逐器官 mask。
3. 按需重采样。
4. 按需调整方向。
5. 按 `ModelMap.toml` 合并为一份多标签 mask。
6. 写入 nnUNet 目录。
7. 生成 `dataset.json` 和 `splits_final.json`。

### 5.3 数据划分

脚本优先读取带 `split` 列的 `meta.csv`。

如果没有 `meta.csv`，当前代码会：

- 自动扫描病例。
- 按 80% / 10% / 10% 随机划分。
- 验证集为空时，从训练集末尾取 10%。

这个回退只适合临时实验。正式平台运行禁止依赖它，因为它没有固定随机种子，也不保证患者级分组。

### 5.4 重采样

当前实现使用 `scipy.ndimage.zoom`：

- 图像采用一阶线性插值。
- mask 采用最近邻插值。
- 重采样后重建 affine。

平台工具适配器仍要在导出前后检查实际空间信息，不能仅因脚本完成就假设结果正确。

### 5.5 调整图像方向

当前实现支持类似 `RAI` 和 `LPS` 的三字母方向代码。

处理方式主要是轴置换和翻转，不对体素值插值。代码还会对 affine 的方向矩阵做正交化，以减少部分软件因方向余弦误差而拒绝读取的问题。

MHD/ITK-SNAP 与 nibabel 对方向字母的解释不同。当前代码通过每个字母取反处理二者转换，例如 MHD 约定的 `RAI` 对应 nibabel 约定的 `LPS`。

### 5.6 合并逐器官 mask

转换脚本按当前任务标签表，把多个二值 mask 写入一份整数 mask。

- 后写入的器官会覆盖先写入器官的重叠体素。
- 并行加载版本使用 `ThreadPoolExecutor` 加速。
- 粗分割配置可以把多个器官写成同一个区域标签。

平台接入时要记录重叠体素，并在任务配置中明确覆盖顺序。

### 5.7 输出

```text
nnUNet_raw/DatasetXXX_Name/
  imagesTr/
  labelsTr/
  imagesTs/
  labelsTs/
  dataset.json
  splits_final.json
```

已知问题：

- 缺失器官 mask 会被跳过，不能由当前脚本自行判断是否应当作背景。
- `dataset.json` 的名称、描述和许可必须由平台工具适配器覆盖。

## 6. 第二步：规划和预处理

`Action2_PlanAndPreprocess.py` 依次调用 nnUNet 的三个步骤：

1. **提取数据指纹**：统计图像大小、间距和强度范围。
2. **规划实验**：计算目标间距、patch size、网络结构等。
3. **预处理数据**：根据规划完成重采样和归一化。

### 6.1 手工覆盖参数

当前管线允许在 nnUNet 自动规划后覆盖：

| 参数 | 当前处理 | 主要影响 |
| --- | --- | --- |
| `target_spacing` | 传给实验规划 | 重采样分辨率 |
| `patch_size` | 修改 plans 并重算网络拓扑 | 感受野和显存 |
| `batch_size` | 直接覆盖 plans | 训练速度和显存 |

覆盖 `patch_size` 时，代码会：

- 调整尺寸以满足池化约束。
- 重新计算池化核和卷积核。
- 重新估算显存和 batch size。
- 最后以用户明确指定的 batch size 为准。

这些参数的实际值必须进入模型记录。仅保存原始配置不足以证明最终训练使用了什么。

## 7. 第三步：训练

`Action3_Train.py` 负责设置设备和线程，然后调用 nnUNet 的 `run_training`。

主要参数：

| 参数 | 含义 | 当前常见值 |
| --- | --- | --- |
| `dataset_id` | nnUNet 数据集编号或名称 | 必填 |
| `configuration` | nnUNet 配置 | `3d_fullres` |
| `fold` | 交叉验证折 | `0` |
| `trainer` | trainer 类名 | `nnUNetTrainerNoMirroring` |
| `plans` | plans 标识 | `nnUNetPlans` |
| `num_gpus` | 单次训练使用的 GPU 数量 | `1` |
| `gpu_id` | 指定 GPU | 配置决定 |

工程处理：

- nnUNet 模块在函数内延迟导入，减少子进程重复加载。
- CPU 模式按核心数设置线程。
- GPU 模式把部分 CPU 线程数限制为 1，避免不必要调度开销。

## 8. 第四步：推理

当前代码提供四种推理入口：

| 入口 | 适用场景 | 分辨率处理 |
| --- | --- | --- |
| `stage_predict` | 训练后的标准验证 | 由 nnUNet 内部处理 |
| `easy_predict` | 单模型快速调用 | 由 nnUNet 内部处理 |
| `easy_predict_with_preresample` | 离线批量推理或部署验证 | 外部先缩放，预测后恢复 |
| `multimodel_predict_and_merge` | 多模型全身推理 | 多个模型共享一次图像缩放 |

### 8.1 预重采样推理

该路径先把图像缩放到训练分辨率，再调用 nnUNet，最后把预测 mask 恢复到原始分辨率。

设计目的：

- 避免 nnUNet 对每个病例重复执行较慢的内部重采样。
- 允许外部代码控制图像和 mask 插值。
- 降低多模型重复缩放的成本。

原文档记录的秒级耗时来自特定运行环境，不应视为平台承诺。不同图像大小、CPU、GPU 和存储环境都需要重新测试。

mask 恢复当前支持：

- GPU 线性插值后取类别。
- 最近邻插值。
- CPU one-hot 线性插值后取最大类别。

分割标签最终仍要使用离散整数，选择插值方式时必须验证边界和小结构是否受损。

### 8.2 多模型共享分辨率

传统方式让每个模型分别完成：

```text
缩放图像 -> 推理 -> 恢复 mask
```

共享分辨率方式改为：

```text
图像只缩放一次
-> 多个模型依次推理
-> 在低分辨率下合并
-> 合并结果只恢复一次
```

这种方式适合同一批模型使用相同目标分辨率的情况。模型分辨率不同或合并规则复杂时，应使用独立推理路径。

### 8.3 Windows 和 Linux

| 环境 | 当前策略 | 原因 |
| --- | --- | --- |
| Linux | 可使用 nnUNet 文件级多进程推理 | `fork` 创建子进程成本相对较低 |
| Windows | 倾向单进程数组推理 | `spawn` 会重新导入 PyTorch 和 nnUNet，启动成本较高 |

### 8.4 显存和内存记录

显存监控使用 `pynvml` 和 `psutil`：

- 后台定时采样。
- 记录峰值、低谷和变化。
- 非 NVIDIA 环境降级为零值记录。

推理结束后，代码尝试：

- 清理 nnUNet 高斯权重缓存。
- 清理部分 `lru_cache`。
- 把网络权重移回 CPU。
- 删除 fold 参数副本。
- 运行垃圾回收和 `torch.cuda.empty_cache()`。

这些措施属于当前工程实现，不代表已经彻底证明不存在内存泄漏。

## 9. 第五步：基础评估

`Action5_Evaluation.py` 比较参考 mask 和预测 mask，并输出：

- 每病例、每器官详细 CSV。
- 每器官汇总 CSV。
- 结构化 JSON。
- 人可读文本报告。

当前状态分类：

| 状态 | 含义 | Dice |
| --- | --- | --- |
| `success` | 参考标签和预测都包含该器官 | 正常计算 |
| `FN_only` | 参考标签有该器官，预测完全缺失 | 0 |
| `not_present` | 参考标签中没有该器官 | 不计算 |

评估代码还支持按模型和病例聚合结果。

Surface Dice 所需依赖当前未启用。修复并测试前：

- 不把 Surface Dice 作为正式验收指标。
- 不把空值解释为真实零分。
- 不用当前 Action5 输出替代平台正式评估记录。

## 10. 四种预定义工作流

| 工作流 | 执行内容 | 适用场景 |
| --- | --- | --- |
| Workflow 1 | 单配置完成转换、预处理，并生成训练与预测脚本 | 一组共享配置的任务 |
| Workflow 2 | 多配置分别转换和预处理，再按 GPU 分配任务 | 多组配置批量训练 |
| Workflow 3 | 各模型独立推理和恢复分辨率，最后合并 | 模型使用不同分辨率 |
| Workflow 4 | 图像缩放一次，多模型依次推理，在低分辨率合并后恢复一次 | 多模型共享分辨率 |

### 10.1 多 GPU 分配

配置中的 `gpu_id` 可以是：

- 单个编号：所有任务在同一 GPU 上依次运行。
- 与训练数据集列表等长的编号列表：每个任务分配到对应 GPU。

不同 GPU 上的任务可以并行，同一 GPU 上的任务顺序执行，避免显存冲突。

当前编排器会生成 shell 脚本。Windows 环境不能直接执行这些 shell 脚本，需要改用手工命令或后续跨平台启动器。

## 11. 数据目录

```text
train_path/
  train_project/
    nnUNet_raw/
      Dataset101_CT1_Head/
        imagesTr/
        labelsTr/
        imagesTs/
        labelsTs/
        labelsTs_predicted/
        evaluation/
        dataset.json
        splits_final.json
    nnUNet_preprocessed/
      Dataset101_CT1_Head/
        nnUNetPlans.json
        ...
    nnUNet_results/
      Dataset101_CT1_Head/
        nnUNetTrainerNoMirroring__nnUNetPlans__3d_fullres/
          fold_0/
            checkpoint_final.pth
            checkpoint_best.pth
          plans.json
          dataset.json
```

平台接入后，这些目录都是由训练数据快照生成的实际导出物。可复现依据仍然是快照和模型记录，不是手工留下的目录。

## 12. 其他关键实现细节

### 12.1 NIfTI 头信息修复

部分 NIfTI 文件的 qform 和 sform 不一致。当前代码在数据转换和推理输出时使用 nibabel 重写头信息，使二者保持一致。

这项修复不能替代平台空间检查。重写成功只说明文件头格式可读，不能证明标签与图像的医学坐标正确。

### 12.2 Affine 正交化

当前代码对 affine 的 3×3 方向部分执行：

1. 根据列范数提取 spacing。
2. 归一化得到方向矩阵。
3. 通过奇异值分解寻找最近的正交矩阵。
4. 乘回 spacing，重建旋转和缩放部分。

目的在于减少浮点误差造成的方向余弦非正交问题。它不应用于掩盖真实错位。

### 12.3 延迟导入

nnUNet 和部分重量级库在函数内部导入，主要为了降低多进程子进程的重复加载成本，尤其是 Windows `spawn` 模式。

## 13. 当前直接调用示例

下面示例描述现有代码入口，不是未来平台最终用户接口。

### 13.1 单配置训练

```python
from AutoSegmentationFramework import workflow1_nnUnet_train_and_predict

workflow1_nnUnet_train_and_predict()
```

运行前需要准备：

- `Config_*.toml`
- `ModelMap.toml`
- 当前脚本期望的标注目录

### 13.2 多配置批量训练

```python
from AutoSegmentationFramework import workflow2_nnUnet_train_and_predict_batch

workflow2_nnUnet_train_and_predict_batch()
```

该入口会生成按 GPU 分组的脚本。

### 13.3 单模型离线推理

```python
from Action4_Predict import easy_predict_with_preresample

easy_predict_with_preresample(
    model_folder="/path/to/model",
    input_path="/path/to/images",
    output_path="/path/to/output",
    enable_stats=True,
)
```

### 13.4 多模型共享分辨率推理

```python
from AutoSegmentationFramework import workflow4_shared_spacing_predict_and_merge

workflow4_shared_spacing_predict_and_merge()
```

## 14. 依赖和运行环境

核心依赖：

| 包 | 用途 |
| --- | --- |
| `nnunetv2` | 训练、预处理和预测 |
| `torch` | 深度学习和 GPU 计算 |
| `numpy`、`scipy` | 数组和重采样 |
| `nibabel`、`SimpleITK` | NIfTI、MHD 和医学图像读写 |
| `pandas` | 评估结果处理 |
| `tomllib` 或 `tomli` | TOML 配置解析 |
| `tqdm`、`p_tqdm` | 进度显示和部分并行处理 |

可选依赖：

| 包 | 使用条件 |
| --- | --- |
| `pynvml` | 记录 NVIDIA GPU 显存 |
| `psutil` | 记录进程资源 |
| `pydicom` | 使用 DICOM 转换工具 |

仓库当前没有锁定一套完整、经过验证的依赖版本。准备正式复现时，应建立独立环境文件并记录 Python、CUDA、PyTorch、nnUNet 和医学图像库版本。

## 15. nnUNet 工具适配器应怎样复用本管线

适配器不应重写现有五个步骤。它要在管线前后补齐平台契约：

```text
训练数据快照
-> 检查患者划分、标签来源和缺失标签
-> 生成真实的 nnUNet 数据目录与 dataset.json
-> 调用现有 Action2、Action3、Action4
-> 保存实际配置、代码版本和权重
-> 创建模型记录
-> 在独立评估流程中创建评估记录
```

优先复用：

- 配置加载。
- nnUNet 规划和预处理。
- 训练封装。
- 单模型和多模型推理。
- Dice 报告的基础计算。

必须替换或加固：

- 随机数据划分回退。
- 缺失 mask 自动变背景。
- `dataset.json` 硬编码。
- Surface Dice 依赖。
- 正式评估前的患者和标签来源泄漏检查。
