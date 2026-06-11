# Mimics Research 21.0 开发者参考

> 日期：2026-06-11
> 来源：软件自带 Scripting Guide (Help → Scripting Guide)、API 文档、教程脚本、IFU (L-10790-02)
> 用途：POC 验证和 Mimics Adapter 开发

## 1. 关键事实

### 1.1 Python 环境

- **Python 3.5.2** — Mimics 安装向导自动安装到 `C:\Program Files\Common Files\Materialise\Python\3.5.2`
- 可在 File → Preferences → Scripting 中切换为外部 Python 3.5（如 Anaconda）
- 通过 `pip install numpy` 等安装额外库
- `mimics` 模块随 Mimics 安装，在 Mimics 内执行脚本时自动可用，不需显式 `import mimics`

### 1.2 命令行背景模式

```bash
MimicsResearch.exe -b -run_script "C:\path\to\script.py" [args]
```

`-b` = background mode（无 GUI），`-k` = 完成后退出，`-save_log` = 保存日志。脚本参数通过 `sys.argv[n]` 获取。

### 1.3 支持的图像导入格式

来自官方 IFU (L-10790-02)："Dicom 3.0 format, BMP, TIFF, JPG and raw images" — **不含 NIfTI**。

### 1.4 脚本 API 的图像导入链路

```
test_images(filenames)          → 识别格式，生成 ImageFile 对象
    ↓
configure_dicom_images()        → DICOM → ConfiguredImageFile
configure_standard_images()     → BMP/TIFF/JPEG → ConfiguredImageFile
    ↓
split_images_into_studies()     → 按 Study 分组
    ↓
load_series_into_memory()       → 加载像素数据
    ↓
open_images_as_project()        → 在 Mimics 中打开

便捷封装：
import_dicom_images(folder)     — 一步完成 DICOM 导入
import_standard_images(folder, xy_res, z_res) — 一步完成标准图像导入
```

## 2. Mask API（最常用）

```python
# 创建
mask = mimics.segment.create_mask()
mask.name = "liver"

# 阈值分割
mask.threshold_low = 0
mask.threshold_high = 1
mimics.segment.threshold(mask=mask, threshold_min=226, threshold_max=3071)

# 读写体素 — 这是 NIfTI 互操作的关键
vp = mask.get_voxel_buffer()    # → memoryview of bool，形状 = (Z, Y, X)
mask.set_voxel_buffer(vp)       # ← memoryview of bool，形状必须一致

# 遍历/查找
mask = mimics.data.masks[0]            # 第一个 mask
mask = mimics.data.masks.find("liver") # 按名称查找，无匹配返回 None

# 容器操作
mimics.data.masks.duplicate(mask)
mimics.data.masks.delete(mask)
for m in mimics.data.masks:           # 遍历所有 mask
    print(m.name)
```

### 2.1 Mask 体素坐标系

`get_voxel_buffer()` 返回三维 memoryview，索引为 `[Z, Y, X]`。API 示例证实了这一布局：

```python
vp = mask.get_voxel_buffer()
vp[i, i, i] = True          # 画主对角线
click = image3d.get_voxel_indexes(click)   # 世界坐标 → 体素索引
vb[click[0], click[1], click[2]] = True    # [Z, Y, X]
```

### 2.2 灰度值单位

Mimics Python API 始终使用 **gray values (GV)**，不是 Hounsfield units (HU)。转换方式：
```python
low_gv = mimics.segment.HU2GV(low_hu)
high_gv = mimics.segment.HU2GV(high_hu)
```

## 3. ImageData API（CT 图像）

```python
img = mimics.data.images.get_active()       # 当前活动图像
img = mimics.data.images[0]                 # 第一个图像集
voxels = img.get_voxel_buffer()             # 16-bit 灰度 3D 数组
tags = img.get_dicom_tags()                 # DICOM 标签字典
info = img.get_image_information()          # ImageInformation 对象

# 几何属性
img.logical_dimensions      # 体素维度 (Z, Y, X)
img.physical_dimensions     # 物理尺寸
img.pixel_size              # 面内像素大小
img.logical_slice_distance  # 层间距

# 坐标转换
idx = img.get_voxel_indexes(world_coord)    # 世界坐标 (mm) → 体素索引
gv = img.get_grey_value(world_coord)        # 某点的灰度值
```

## 4. 文件/项目操作

```python
# 项目
mimics.file.open_project("path.mcs")
mimics.file.save_project()
mimics.file.close_project()

# DICOM 导入导出
mimics.file.import_dicom_images(source_folder="C:\\DICOM\\")
mimics.file.export_dicom(path="C:\\output\\", filename_prefix="case001_")

# Part/STL 导出
mimics.segment.calculate_part(mask=mask, quality="High")
mimics.file.export_part(object_to_convert=part, file_name="output.stl")

# 项目合并
mimics.file.add_images_to_project(imagedata)
mimics.file.import_mimics_project("other.mcs")
```

## 5. 对话框抑制（自动化关键）

```python
mimics.dialogs.set_predefined_answer("ChangeOrientation", "default")
mimics.dialogs.set_predefined_answer("SelectPixelSize", "X")  # 非方形像素
```

可用对话框 ID：`ChangeOrientation`（方向）、`SelectPixelSize`（非方形像素）。

## 6. 完整工作流示例（来自官方教程）

```python
# 打开项目
mimics.file.open_project(r'C:\MedData\DemoFiles\Hip.mcs')

# 创建 mask 并阈值分割
mask = mimics.segment.create_mask()
mask.name = "Lower limb"
mimics.segment.threshold(mask=mask, threshold_min=1250, threshold_max=2650)

# 填充空洞
mimics.segment.fill_holes(mask)

# 区域生长
point = mimics.analyze.indicate_point(
    title="Region growing point",
    message="Please indicate a point on the part of interest")
mask2 = mimics.segment.region_grow(
    point=point, input_mask=mask, target_mask=None,
    slice_type="Axial", keep_original_mask=True)
mask2.name = "Segmented right femur"

# 计算 3D Part 并导出 STL
part = mimics.segment.calculate_part(mask=mask2, quality="High")
mimics.file.export_part(object_to_convert=part, file_name=r"C:\output.stl")

# 保存并退出
mimics.file.save_project()
mimics.file.exit()
```

## 7. 对平台 POC 的 API 覆盖确认

| 需要的操作 | Mimics API | 状态 |
|-----------|-----------|------|
| CT 图像导入 (DICOM) | `import_dicom_images()` | ✅ |
| CT 图像体素读取 | `get_voxel_buffer()` on ImageData | ✅ |
| 创建新 mask | `create_mask()` | ✅ |
| 写入 mask 体素 (从 NIfTI) | `set_voxel_buffer()` | ✅ |
| 读 mask 体素 (导出 NIfTI) | `get_voxel_buffer()` | ✅ |
| 设置 mask 名称 | `mask.name = "liver"` | ✅ |
| 查找 mask | `mimics.data.masks.find()` | ✅ |
| 遍历所有 mask | `for m in mimics.data.masks` | ✅ |
| 删除 mask | `mimics.data.masks.delete()` | ✅ |
| 复制 mask | `mimics.data.masks.duplicate()` | ✅ |
| 抑制导入对话框 | `set_predefined_answer()` | ✅ |
| 背景模式运行 | `MimicsResearch.exe -b -run_script` | ✅ |
| 获取图像几何 (spacing/dims) | `logical_dimensions`, `pixel_size`, `logical_slice_distance` | ✅ |
| 获取 DICOM 标签 | `get_dicom_tags()` | ✅ |
| Mask 颜色设置 | API 文档未暴露 `mask.color` 属性 | ⚠️ 待确认 |
| NIfTI 直读 | 无 | ❌ 用外部 nibabel |

## 8. 开放风险

1. **Mask 颜色 API** — 文档未暴露 `mask.color`。需要在实际软件中通过 `dir(mask)` 或 Scripting Guide 确认
2. **`get_voxel_buffer` 内存布局** — 返回 memoryview，shape=(Z,Y,X)。与 numpy/nibabel 的 (X,Y,Z) 布局交互时需验证轴顺序
3. **Python 3.5 兼容性** — nibabel、SimpleITK 最新版可能不再支持 3.5，需在外部 Python 3.8+ 完成 NIfTI 操作
