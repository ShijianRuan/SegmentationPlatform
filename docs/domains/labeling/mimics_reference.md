# Mimics Research 21.0 技术参考

> 版本：v0.4
> 更新日期：2026-06-13
> 用途：为 Mimics 适配器设计和本机验证提供事实依据

本文区分三类信息：

- **已确认**：Mimics 21.0 官方资料中有明确依据；
- **未确认**：资料不足，必须在当前安装环境中验证；
- **设计结论**：平台根据已确认事实采用的边界，不是 Mimics 自带功能。

不要用新版 Mimics 的能力反推 21.0。

## 1. 资料优先级

1. 仓库内的 [Mimics 21.0 API 文档](../../references/mimics/api_21/Mimics_API_Documentation_CN.md)。
2. 当前安装环境的 Scripting Guide、edition、license 和实际运行结果。
3. Materialise 官方其他版本资料，只用于识别版本变化。
4. 社区讨论，只用于发现可能需要验证的风险。

## 2. Python 和脚本入口

### 2.1 已确认事实

- Mimics 21 安装流程使用 Python 3.5.2。
- Preferences 可以指向其他兼容的 Python 3.5 环境。
- 兼容 Python 3.5 的第三方包可以通过 `pip` 安装。
- Python 3.5 已于 2020 年 9 月 30 日停止维护。

经过版本元数据核对，可用于 Python 3.5 的较新版本大致为：

| 库 | 可用边界 | 对平台的含义 |
|---|---|---|
| nibabel | 3.0.2 仍支持 Python 3.5.1；3.1.0 起要求 Python 3.6 | 只能锁定旧版 |
| NumPy | 1.18.5 有 CPython 3.5 Windows wheel；1.19.5 要求 Python 3.6 | 可用于薄交换脚本 |
| SimpleITK | 2.0.2 有 CPython 3.5 Windows wheel；2.1.1 不再提供 | 仍属于冻结旧栈 |

这些事实说明旧库“可以安装”，不说明它们适合作为平台主运行时。

### 2.2 命令行参数

官方命令行形式包括：

```text
<mimics_executable> [-help] [-background_mode] [-kill]
                    [-save_log <filename.txt>]
                    [-run_script <script_name.py [args]>]
```

脚本可以通过 `sys.argv` 读取任务清单、输入目录和输出目录，因此路径不需要写死。

```python
import sys

manifest_path = sys.argv[1]
output_dir = sys.argv[2]
```

脚本既可以处理一个病例，也可以循环处理多个病例。是否批量运行由脚本决定，不受 Mimics 固定限制。

`-background_mode` 适合无人参与的导入、转换、导出和检查，不适合人工编辑。Scripting Library 可以把脚本暴露为 Mimics 内的一键动作。

官方示例使用 Medical 版可执行文件，并说明 Research 版采用相应 Research 可执行文件。实际文件名和安装路径必须由工作站配置或 `-help` 实测获得，平台代码不能硬编码。

### 2.3 设计结论

Mimics Python 只负责：

- 调用 Mimics API；
- 选择 image set；
- 创建、读取和写入 Mask；
- 显示必要提示；
- 保存项目和输出运行日志。

外部受维护的 Python 负责：

- NIfTI、MetaImage 等文件读写；
- 重采样和空间变换；
- 哈希、结构校验和质量检查；
- 平台数据登记。

外部 Python 不能被默认视为 Mimics 内部解释器。若需要联动，采用启动器、文件交换或经过验证的官方 listener 机制。

## 3. DICOM 导入

### 3.1 已确认的底层步骤

官方 API 暴露了下面的处理链：

```text
test_images(...)
  -> configure_dicom_images(...)
  -> split_images_into_studies(...)
  -> load_series_into_memory(...)
  -> open_images_as_project(...) / add_images_to_project(...)
```

也有较简单的入口，例如：

- `import_dicom_images(folder)`；
- `convert_dicom_images_to_mcs(source, target)`。

`split_images_into_studies()` 会使用患者、Study、Series Description、phase、protocol 和 image center 等信息组织数据。官方教程允许输入目录包含一个或多个检查。

### 3.2 多患者、多检查和多序列

已确认：

- 一个 DICOM 序列通常成为一个 `ImageData`，也可称为一个 image set；
- 一个 Mimics 项目可以包含多个 image sets；
- `mimics.data.images.get_active()` 返回当前活动的 image set；
- `add_images_to_project()` 可以加入更多 image sets；
- Mask 等对象与具体 image set 关联。

平台设计不要求人为规定“主序列”和“参考序列”。多个序列可以是平等输入，也可以各自承担不同标注目标。

平台不能把 Mimics 自动分组当作病例登记的唯一依据。平台应先保存预期的患者、检查和序列清单；导入后再把实际 image sets 与清单逐项核对。

脚本在处理每个任务目标前必须显式激活对应 image set，不能依赖用户最后点击的图像。

## 4. 图像格式

### 4.1 已确认支持

21.0 的 IFU 和 API 可以确认：

- DICOM 3.0；
- BMP；
- TIFF；
- JPEG；
- raw images。

`import_standard_images()` 面向 BMP、TIFF 和 JPEG。raw 导入需要调用者提供尺寸、数据类型、字节序和 spacing 等信息。

### 4.2 未确认支持

当前 21.0 资料没有证明可以直接导入：

- NIfTI（`.nii`、`.nii.gz`）；
- MetaImage（`.mhd`、`.mha`）。

若当前安装界面或 edition 提供相关功能，必须记录菜单、API、版本、模块和空间验证结果，不能只记录“文件能打开”。

### 4.3 图像数组写入限制

已确认 `ImageData.get_voxel_buffer()` 可以读取图像体素。当前资料没有找到可用于任意创建图像体数据的 `ImageData.set_voxel_buffer()`。

因此：

- “外部读取 NIfTI 后直接写成新的 Mimics 图像”不是已成立能力；
- 只有 NIfTI 或 MetaImage 图像时，优先验证受控格式转换；
- 无法可靠恢复方向和坐标时，应改用原生支持该格式的工具。

## 5. 空间坐标

常用 API 包括：

```python
image = mimics.data.images.get_active()
buffer = image.get_voxel_buffer()
tags = image.get_dicom_tags()
info = image.get_image_information()

world = image.get_voxel_center((0, 0, 0))
index = image.get_voxel_indexes(world)
```

### 5.1 为什么 shape 不够

两个数组 shape 相同，仍可能存在：

- 轴顺序不同；
- 某个轴方向相反；
- origin 不同；
- spacing 不同；
- 患者坐标系不同。

因此不能通过复制 NIfTI header 或 affine 来“修复”未经证明的对齐。

### 5.2 推荐验证方法

读取以下索引点的世界坐标：

- `(0, 0, 0)`；
- `(1, 0, 0)`；
- `(0, 1, 0)`；
- `(0, 0, 1)`。

这些点可以确定索引轴在世界坐标中的方向和步长。再使用一个带不对称标记的人工体模检查轴交换、翻转和偏移。

官方资料只证明 Mask buffer 是三维 memory view，没有充分依据把它固定写成 `(Z, Y, X)`。实际轴顺序必须通过上述测试确定。

当前桥接只表达三维索引轴的排列和翻转，不执行任意角度旋转、剪切、重采样或非线性变换。
平台只接受规则、正交、等间距的 DICOM 体素网格；检测到 gantry tilt、sheared slice grid
或 P05 无法得到唯一排列/翻转时会阻断，而不是近似转换。

发生重采样时：

- 图像可根据用途选择合适插值；
- 标签只使用最近邻插值；
- 平台创建新的文件版本和哈希；
- 保存输入、输出和变换记录。

## 6. Mask 对象

### 6.1 已确认能力

```python
mask = mimics.segment.create_mask()
mask.name = "liver"
mask.color = (1.0, 0.4, 0.2)

pixels = mask.get_voxel_buffer()
mask.set_voxel_buffer(pixels)
```

Mask 具有名称、颜色、关联图像、metadata、选中状态和可见状态等字段，也可以遍历、查找、复制和删除。

`set_voxel_buffer()` 可用于注入初始标签，但数组必须与目标 image set 的索引网格完全一致。

### 6.2 平台推荐表示

在 Mimics 内，一个器官使用一个 Mask，原因是：

- 可以独立显示和隐藏；
- 可以逐器官编辑；
- 可以选择性导出；
- 名称可以直接使用平台统一器官名；
- metadata 可以保存任务、器官和来源标签标识。

“逐器官 Mask”是 Mimics 工作表示。平台长期存储仍可同时支持逐器官文件和多标签文件。

## 7. 初始标签导入

图像导入与标签导入不是同一条链路：

- 图像导入要创建 image set；
- 标签导入要把 Mask 绑定到已有 image set。

推荐顺序：

1. 先验证当前安装是否能直接导入标签并保持空间位置和名称；
2. 直接路径不足时，外部程序读取标签并重采样到目标网格；
3. 外部程序写出数组、哈希、shape、轴说明和 image set 标识；
4. Mimics 脚本创建 Mask 并调用 `set_voxel_buffer()`；
5. 使用人工体模和真实病例复核。

## 8. 标签导出

`mimics.file.export_dicom()` 用于导出活动图像切片，并可带可见 Mask 的轮廓。它不是平台标签文件的通用导出接口。

平台推荐通过 `get_voxel_buffer()` 导出 Mask：

- 可只导出指定器官；
- 可按一次提交声明导出多个目标器官；
- 不应依赖界面当前“可见”的对象来决定正式提交内容；
- 输出路径和名称来自任务清单或命令行参数。

需要 NIfTI 或多标签文件时，由外部程序完成格式写入和器官编号合并。

## 9. `.mcs` 项目文件

`.mcs` 保存 image sets、Masks、parts、测量和工作状态。

已确认：

- `save_project()` 支持当前格式和旧版兼容格式；
- Mimics 18 之后使用的现代 SQLite serialization backend 不受旧 ZIP backend 的 4 GB 限制；
- 项目仍可能因包含完整图像和派生对象而很大；
- 保存为 Mimics 16 至 20 兼容格式时，多 image set 项目只保存 active image set 及其关联对象；
- 有损 JPEG 压缩会改变图像，不应作为默认标注方案。

跨机器使用仍取决于兼容版本、edition、license 和环境。`.mcs` 只作为工作现场，平台仍保存
病例包、原始文件和提交结果。实现另外提供显式 Mask checkpoint；它不依赖 `.mcs` 内部结构，
但仍要求相同 review、基础标签和 buffer mapping evidence。

## 10. 对话框

Mimics API 提供：

- `set_predefined_answer()`：为可预测的内置对话框预设答案；
- `question_box()`：要求用户做少量明确选择；它返回一个按钮结果，没有原生多选返回值；
- `message_box()`：显示提示或阻断信息。

平台只应在三类场景打断标注者：

1. 打开任务时，病例、序列或目标与任务清单不一致；
2. 提交时，选择完成、复查或阻塞；
3. 出现无法继续的空间、数据或脚本错误。

只有平台预检查已经证明答案唯一时，才能自动关闭或预答对话框。方向、raw 参数和序列选择存在歧义时必须阻断。

## 11. 文件交换边界

只有直接导入导出不足时，才增加外部与内部的文件交换：

| 运行环境 | 负责 | 不负责 |
|---|---|---|
| Mimics Python 3.5 | DICOM、`.mcs`、active image、Mask、Mimics 界面 | 现代文件格式、平台数据登记、长期数据校验 |
| 外部现代 Python | 格式转换、空间处理、哈希、结构校验、平台登记 | 替代 Mimics 界面和内部对象操作 |

两者通过结构化清单、数组文件、日志和退出码通信。阶段 A 不需要跨进程服务。

具体脚本、启动命令、Mask metadata 和标注者操作见 [Mimics 适配器设计与开发流程](mimics_adapter_design.md)。

## 12. 本机验证问题索引

| 编号 | 必须回答的问题 |
|---|---|
| P01 | 多患者、检查和序列如何成为 image sets |
| P02 | 每个任务目标能否稳定绑定正确 active image |
| P03 | 当前安装实际支持哪些图像格式 |
| P04 | 初始 Mask 能否准确注入 |
| P05 | buffer 轴顺序和索引到世界坐标的变换是什么 |
| P06 | 能否选择性导出一个或多个目标 Mask |
| P07 | `.mcs` 能否可靠恢复和有限度跨机器使用 |
| P08 | 命令行参数和批量运行是否可靠 |
| P09 | 对话框能否减少而不掩盖歧义 |
| P10 | 保存、完成提交、复查和阻塞是否能区分 |
| P11 | 已验证标签能否创建新版本继续修订 |
| P12 | 多标注者提交能否避免明显覆盖 |
| P13 | 异常能否生成可操作反馈 |
| P14 | 提交结果能否进入平台登记和训练快照 |

详细操作只在 [可行性验证计划](mimics_poc_plan.md) 中维护。

## 13. 外部版本依据

- [Python 3.5.10 发布与停止维护说明](https://www.python.org/downloads/release/python-3510/)
- [nibabel 3.0.2](https://pypi.org/project/nibabel/3.0.2/)
- [nibabel 3.1.0](https://pypi.org/project/nibabel/3.1.0/)
- [SimpleITK 2.0.2](https://pypi.org/project/SimpleITK/2.0.2/)
- [SimpleITK 2.1.1](https://pypi.org/project/SimpleITK/2.1.1/)
