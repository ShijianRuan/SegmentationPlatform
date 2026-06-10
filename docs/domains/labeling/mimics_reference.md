# Mimics Research 21.0 技术参考

> 日期：2026-06-10
> 状态：调研阶段参考文档，用于指导 POC 验证和 Adapter 设计
> 信息来源：Materialise 官方社区 (community.materialise.com)、Wikipedia、YouTube 官方教程、GitHub 社区脚本

## 1. 软件概览

Materialise Mimics（Materialise Interactive Medical Image Control System）是 Materialise NV（比利时）开发的医学图像处理与 3D 建模软件。Mimics Research 21.0 属于 Mimics Innovation Suite (MIS) 的一部分。

| 属性 | 信息 |
|------|------|
| 操作系统 | Windows 10/11 x64 |
| 主要输入格式 | DICOM (CT/MRI/Micro CT/超声) |
| 原生输出格式 | STL (3D 表面模型)、DICOM |
| NIfTI 支持 | **不原生支持导入**；可通过 Python scripting + nibabel 导出 |
| Python 脚本 | 需安装 Python 3.8（32-bit 或 64-bit 取决于 Mimics 版本），使用内置 `mimics` 模块 |
| 脚本参考 | 内置 Scripting Guide（Help → Scripting → Scripting Guide），提供完整 API 文档 |
| Demo 脚本 | 随软件安装提供（`MIS - Demo Scripts` 目录），覆盖导入/分割/导出等常见任务 |
| 社区论坛 | [community.materialise.com](https://community.materialise.com)（MIS Scripting Forum + Demo Scripts） |

## 2. Python Scripting 环境搭建

### 2.1 官方要求

- Python **3.8**（社区和官方视频均明确指出）
- 必须安装与 Mimics 位数匹配的 Python（32-bit Mimics → 32-bit Python）
- 在 Mimics 中配置 Python 解释器路径

### 2.2 配置步骤（来自官方视频教程）

1. 安装 Python 3.8
2. Mimics → Help → Scripting → 打开 Scripting Guide
3. 在 Scripting Guide 中配置 Python interpreter 路径
4. 外部可配合 `nibabel`、`numpy`、`SimpleITK` 等库实现 NIfTI 读写

### 2.3 关键注意事项

- Python 脚本运行在 Mimics 进程内，可直接访问 Mimics 内部数据模型
- 不支持创建 mask from non-Part object（如 Sphere/其他几何体）— 2024 年社区确认此 API 限制
- 脚本可以预回答对话框（`mimics.dialogs.set_predefined_answer()`）

## 3. 已知 API 清单（来自社区论坛 + Demo 脚本）

### 3.1 文件与导入

| API | 功能 | 来源 |
|-----|------|------|
| `mimics.file.import_dicom_images(source_folder=path)` | 自动导入 DICOM 目录 | Demo Script |
| `mimics.file.anonymize_active_image()` | 匿名化当前图像 | Demo Script |
| `mimics.dialogs.set_predefined_answer("ChangeOrientation", "default")` | 预回答方向变更对话框 | Demo Script |

> ⚠️ Mimics 原生不支持 NIfTI (.nii/.nii.gz) 导入。NIfTI 数据需要在 Mimics 外部（Python nibabel/SimpleITK）读取后转为 DICOM 或直接操作 voxel buffer。

### 3.2 分割与 Mask 操作

| API | 功能 | 来源 |
|-----|------|------|
| `mimics.segment.create_mask(select_new_mask=True)` | 创建新 mask | Community (2024) |
| `mimics.segment.threshold(mask, threshold_min, threshold_max, bounding_box)` | 阈值分割 | Community (2024) |
| `mimics.segment.calculate_mask_from_part(part)` | 从 Part 计算 mask | Community (2024) |
| `mimics.data.masks.find(name="mask_name")` | 按名称查找 mask | Community (2021) |

### 3.3 数据导出

| API / 方法 | 功能 | 来源 |
|-----------|------|------|
| `mask.get_voxel_buffer()` | 获取 mask 体素数据 (numpy array) | Community (2021) |
| `nibabel.Nifti1Image(array, affine)` | 将体素数据写入 NIfTI（需外部 nibabel） | Community (2021) |
| 原生 STL 导出 | 3D 表面模型导出（GUI 或 Scripting） | 原生功能 |
| 原生 DICOM 导出 | DICOM 图像和 RT-Struct 导出 | 原生功能 |

### 3.4 元数据

| API | 功能 | 来源 |
|-----|------|------|
| `mimics.file.get_tag_value(tag)` | 读取 DICOM tag | Community (DICOM tags thread) |
| (Scripting Guide 中有完整 metadata API) | 图像方向、spacing、origin 等 | 需查内置文档 |

## 4. 对 POC 各验证项的直接影响

### M1. 图像导入

**已知情况**：
- DICOM 导入：✅ 脚本可自动化（`mimics.file.import_dicom_images()`），Demo 脚本已验证
- NIfTI 导入：❌ 不原生支持

**建议 POC 策略**：
- 如果 CT 是 DICOM 格式 → 直接用 scripting 导入，M1 风险低
- 如果 CT 是 NIfTI → 需要预转换为 DICOM（如 `dcm2niix` 逆向 / SimpleITK 写 DICOM / 或在 Mimics 中使用 "Import Image" 手动导入 .nii.gz）
- **Case Package 应强制包含 DICOM 版本**（与 POC 方案的失败处理策略一致）

### M2. 草稿导入

**已知情况**：
- 没有直接导入 NIfTI mask 的 API
- 工作路径：Python 侧用 nibabel 读取 draft_label.nii.gz → 逐器官转为 voxel buffer → 在 Mimics scripting 中创建 mask 并写入 voxel buffer

**Mimics 侧脚本伪代码**：
```python
import nibabel as nib
import numpy as np
import mimics

# 1. 在 Python 侧读取 draft_label.nii.gz
draft_nii = nib.load("draft_label.nii.gz")
draft_data = draft_nii.get_fdata()

# 2. 读取 label_map 获取器官到 label ID 的映射
# organ_label_map = load_json("review_label_map.yaml")

# 3. 对每个器官，提取二值 mask 并写入 Mimics
for organ_name, label_id in organ_label_map.items():
    binary_mask = (draft_data == label_id).astype(np.uint8)
    
    # 在 Mimics 中创建 mask 并写入体素数据
    mimics_mask = mimics.segment.create_mask(select_new_mask=True)
    mimics_mask.set_name(organ_name)
    # 需要查找 Scripting Guide 中 set_voxel_buffer 或类似 API
```

⚠️ **关键未知**：是否存在 `mask.set_voxel_buffer()` 或类似 API 来**写入**体素数据？内置 Scripting Guide 需确认。

### M4. 标签导出

**已知情况**：
- 可以通过 `get_voxel_buffer()` 获取每个 mask 的 numpy array
- 通过 nibabel 写入 NIfTI（带正确的 affine 矩阵）
- 需要在 Python 侧合并为多标签 NIfTI 或保持逐器官二值 mask

**导出脚本伪代码**：
```python
import nibabel as nib
import numpy as np
import mimics

# 获取 CT 图像的 affine 和 shape（需查 Scripting Guide 获取 image geometry）
# ct_affine = ... 
# ct_shape = ...

output_label = np.zeros(ct_shape, dtype=np.uint8)

for organ_name, label_id in organ_label_map.items():
    mask = mimics.data.masks.find(name=organ_name)
    if mask is not None:
        voxels = np.asarray(mask.get_voxel_buffer())
        output_label[voxels > 0] = label_id

nii = nib.Nifti1Image(output_label, ct_affine)
nib.save(nii, "verified_label.nii.gz")
```

### M5. 空间往返 ⚠️ 高风险

**已知问题**（来自社区论坛）：
> DICOM 坐标系 (LPS+) 与 NIfTI 坐标系 (RAS+) 的 affine 转换是一个**已知陷阱**。社区用户 Erica 报告了以下问题：
> - 用 `get_voxel_buffer()` 获取的体素方向与 NIfTI 预期不一致
> - 矢状面/冠状面/轴状面位置互换
> - `dicom2nifti` 外部库与 nibabel 的 affine 矩阵不一致

**建议 POC 策略**：
- 先不依赖脚本自动化 M5
- 先用 GUI 逐病例验证：Mimics 内显示的 mask 与 ITK-Snap/3D Slicer 中是否存在旋转/翻转/位移
- 确定正确的 affine 转换矩阵后再写自动化脚本
- 建议在 POC 报告中将 M5 标记为**最高风险项**

### M6. ID 映射

**已知情况**：
- `mask.set_name()` 可以为 mask 命名
- Mask 名称到平台器官名称的映射需要在 Python 侧维护

### M7. 批量可用

- 自动化导入 DICOM + 创建 mask 可以完全脚本化
- 批量处理的关键受阻点是 M5（空间往返）和 mask 写入 API 的存在性

### M8. 本地远程流转

- Mimics scripting 运行在 Windows 本地
- 导出的 NIfTI 可以复制到远程 Linux 训练服务器
- 需要在远端运行 `check_geometry.py` 做空间校验

## 5. 关键未知项（需在 Mimics 本机 Scripting Guide 中确认）

以下 API 的存在性无法从公开资料确认，必须在 Mimics 21.0 本机的 **Help → Scripting → Scripting Guide** 中查找：

| 优先级 | 要查找的 API | 对 POC 的影响 |
|--------|------------|--------------|
| 🔴 Critical | **写入**体素数据到 mask 的 API（`set_voxel_buffer` 或类似） | 决定 M2 草稿导入是否可自动化 |
| 🔴 Critical | 获取 CT 图像 geometry 的 API（affine / spacing / origin / direction） | 决定 M5 空间往返是否可脚本化 |
| 🟡 High | Mask 颜色设定的 API（`set_color` 或类似） | M3 标注体验 |
| 🟡 High | Mask 导出为 DICOM RT-Struct 的 API | M4 备选导出格式 |
| 🟢 Medium | 批量重命名 mask 的 API | M7 批量可用 |
| 🟢 Medium | 获取当前所有 masks 列表的 API | 批量操作必需 |

## 6. 执行 POC 的建议顺序

基于上述发现，POC 执行顺序应调整为：

```
Step 1 (30 min): 在 Mimics 本机打开 Scripting Guide
  → 确认上述 6 个关键 API 的存在性
  → 记录 API 签名和参数列表

Step 2 (1h): GUI 手动验证 M1 + M5
  → 导入 1 个 DICOM CT
  → 手动创建 1 个简单 mask（如阈值分割骨骼）
  → 导出 STL 观察是否对齐
  → 如果用 nibabel 导出 NIfTI，检查 3D Slicer 中方向

Step 3 (2h): 脚本验证 M1 + M4
  → 跑通 import_dicom_images()
  → 跑通 threshold → get_voxel_buffer → nibabel NIfTI 导出
  → 验证 NIfTI 中的 mask 与 Mimics 中显示一致

Step 4 (2h): 脚本验证 M2
  → 如果 set_voxel_buffer API 存在：跑通外部 NIfTI 读取 → Mimics mask 写入
  → 如果不存在：草稿导入改为 DICOM SEG / RT-Struct 路由，或放弃脚本化 M2

Step 5 (1h): 完整流程
  → 取 3 个真实病例测试全流程
```

## 7. 外部资源索引

| 资源 | 链接 | 用途 |
|------|------|------|
| Materialise 官方学院 | [materialise.com/en/academy](https://www.materialise.com/en/academy/healthcare/mimics-innovation-suite) | 视频教程、培训 |
| MIS Scripting 社区 | [community.materialise.com](https://community.materialise.com) | API 问答、Demo 脚本 |
| Python 环境配置视频 | YouTube: "Setup Scripting in Materialise Mimics" | Python 3.8 安装配置 |
| 匿名化文章 | [materialise.com/en/inspiration/articles/anonymize-personal-data-mimics](https://www.materialise.com/en/inspiration/articles/anonymize-personal-data-mimics) | Mimics 21.0 匿名化功能 |
| GitHub 社区脚本 | [github.com/fahimehazari/mimics_3matic_Python_scripting](https://github.com/fahimehazari/mimics_3matic_Python_scripting) | Mesh 生成参考 |
| Wikipedia | [en.wikipedia.org/wiki/Materialise_Mimics](https://en.wikipedia.org/wiki/Materialise_Mimics) | 软件概览 |
| DICOM↔NIfTI affine 讨论 | [community.materialise.com/t/438](https://community.materialise.com/t/dicom-to-nifti-format-using-mimics-scripting-problem-with-affine-transformation-matrix/438) | ⚠️ M5 关键参考 |

## 8. 结论

**Mimics 21.0 能否承担 Case Package Review 工具？**

- **M1（DICOM 导入）**：✅ 确定可脚本化
- **M2（草稿导入）**：⚠️ 取决于 `set_voxel_buffer()` API 存在性
- **M3（人工修正）**：✅ GUI 体验成熟
- **M4（标签导出）**：⚠️ 可通过 nibabel workaround，但需要正确的 affine
- **M5（空间往返）**：⚠️ **最高风险项**，DICOM↔NIfTI 坐标系转换是社区已知问题
- **M6–M8**：✅ 逻辑层面可实现

**最大不确定性**：Mimics 的内部 voxel buffer 坐标系与 NIfTI 标准之间的 affine 转换。POC 第一件事就应该是验证 M5，如果 M5 失败则 Mimics 不应作为自动管线主工具。
