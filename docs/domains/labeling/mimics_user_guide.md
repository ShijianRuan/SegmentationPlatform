# Mimics Research 21.0 完整使用说明文档（新手友好版）

> **适用读者**：零基础新手及初级用户。本文整合官方IFU文档、Release Notes、Materialise Academy视频教程、社区论坛帖子、GitHub示例及中文博客教程，构建一份可直接上手的操作指南。代码示例保留英文原文，关键术语首次出现时标注英文原名。

---

## 一、软件定位与资源全景

**Mimics Research 21.0 是 Materialise 公司出品的医学图像处理与三维重建平台，其"Research"版的核心差异在于内置完整的 Python 脚本 API。** 标准版（Mimics Core/Medical）面向临床工作流，而 Research 版在此基础上开放了 Python 自动化接口，允许用户编写脚本批量处理 DICOM 数据、自动分割、生成 3D 模型，乃至与配套软件 3-matic 实现联动工作流。官方文档明确指出，该版本专为无需医疗器械注册的科研场景设计 [1]。

软件的核心工作流可概括为以下线性管道：

**导入 DICOM 图像堆栈 → 创建 Mask（掩膜）→ 图像分割（阈值/区域生长/手动编辑）→ 布尔运算与后处理 → 生成 3D Part（三维模型）→ 导出 STL/OBJ 或通过脚本自动化全流程**

### 1.1 官方资源索引

以下为所有已确认的学习资源入口：

| 资源类型 | 名称 | 获取方式 |
|---|---|---|
| 官方 IFU 文档 | IFU - Mimics Research 21.0 (L-10790-02) | Materialise 官网文档页 [1] / Scribd [2] |
| 脚本专项 IFU | IFU - AI Interference through Mimics Scripting | Materialise 官网文档页 [1] |
| Release Notes | Release Notes Mimics Research 21.0 | Scribd [3] |
| API 变更日志 | API Change Log（附录 A） | 内嵌于软件 Help > Scripting Guide [3] |
| 内置脚本指南 | Scripting Guide（含 API 完整参考） | 软件内 Help > Scripting Guide [3] |
| 官方免费课程 | A Comprehensive Guide to Mimics Innovation Suite Scripting | go.materialise.com/en/medical/mimics-innovation-course-scripting [4] |
| 官方视频：Python 安装 | How to Install Python to Use with Mimics and 3-Matic | materialise.com/academy [5] |
| 官方视频：脚本配置 | Tutorial: How to Get Set Up and Use Scripting in 3-Matic | materialise.com/academy [6] |
| 社区脚本论坛 | MIS Scripting Forum | community.materialise.com [7] |
| YouTube 入门系列 | Wout Learns Scripting in Mimics Ep. 1 | YouTube [8] |
| YouTube 自动报告 | Mimics Simple Auto Report Generation Script | YouTube [9] |
| GitHub 脚本示例 | mimics_3matic_Python_scripting | github.com/fahimehazari [10] |
| 中文视频教程 | 医学三维重建_Mimics Research 21.0 系列 | Bilibili [11] |
| 中文博客教程 | Mimics 21.0 软件学习笔记 | CSDN (YanLu99) [12] |

**重要说明**：Scripting Guide 和 Reference Guide 均**不作为独立 PDF 公开发布**，而是随软件安装后通过 Help 菜单访问 [3]。IFU 文档（L-10790-02）本身仅包含基础启动说明，并明确指引用户参阅 Reference Guide 获取详细操作说明 [2]。

### 1.2 版本背景与 21.0 vs 22.0 的关键差异

Mimics Research 21.0 与配套的 3-matic Research 13.0 同步发布，构成完整的 MIS（Mimics Innovation Suite）研究版工具链 [14]。21.0 版本在脚本系统上引入了两项重要升级：其一是 **Script Listener（脚本监听器）**，允许从 PyCharm、Eclipse、Visual Studio 等外部 IDE 实时连接 Mimics 进程执行脚本 [3]；其二是内置脚本编辑器和控制台新增了**对象名称自动补全（auto-completion）**功能 [3]。

从 21.0 迁移到 22.0 时，Release Notes 明确要求用户**重新验证（re-validate）**所有旧版脚本，因为部分 API 函数可能已被移除或重命名 [3]。查找变更的方法：打开 Release Notes 的 **Appendix B**（工具移动/重命名查找表）及软件内 Scripting Guide 中的 **API Change Log（附录 A）**。在实际使用中，社区论坛发布的 22.0 示例脚本通常可在 21.0 中运行，但需逐一核对函数签名。

---

## 二、安装与环境配置

### 2.1 软件安装

Mimics Research 21.0 的安装包通常以**分卷压缩包**形式分发，需先将所有分卷下载至同一目录，再使用 7-Zip 或 WinRAR 解压第一个分卷（其余分卷自动合并）。CSDN 博客（YanLu99）提供了详细的中文安装步骤，包括文件准备与授权激活流程 [12]。

**安装前置条件**（根据 IFU 文档 [2] 及社区经验）：

- 操作系统：Windows 10 64位（推荐）；不支持 32 位系统
- 显存：建议 2 GB 以上独立显卡，支持 OpenGL
- 内存：建议 16 GB 以上（处理大型 CT 数据集时）
- 磁盘空间：安装目录建议保留 10 GB 以上空间
- License：需通过 Materialise 授权服务器激活，学术用户可申请 Research 授权

**常见安装问题**：若安装后启动报错，通常与 Visual C++ Redistributable 缺失有关，安装对应版本的运行库可解决；License 激活失败时需检查防火墙是否阻断了授权服务器的连接端口。

### 2.2 Python 环境配置（脚本功能的前提）

官方视频教程明确说明了 Python 安装流程 [5]，以下为关键步骤：

**第一步：安装 Python**

Mimics 21.0 对应的推荐 Python 版本为 **Python 3.8**（64位）[5]。安装时需勾选"Add Python to PATH"选项，确保环境变量正确配置。

**第二步：在 Mimics 中关联 Python 解释器**

启动 Mimics 后，进入 Script 菜单 → Settings，指定 Python 解释器路径（通常为 `C:\Python38\python.exe` 或虚拟环境路径）。

**第三步：验证安装**

在 Mimics 内置脚本控制台中运行：

```python
import mimics
print(mimics.__version__)
```

若无报错且输出版本号，则配置成功。

**注意事项**：
- `mimics` 模块**仅在 Mimics 进程内部有效**，无法在独立 Python 环境中 `import mimics`
- 第三方库（如 `numpy`、`pandas`）需安装到 Mimics 关联的 Python 环境中，而非系统默认 Python
- 使用外部 IDE（PyCharm 等）时，需通过 Script Listener 功能建立连接（见第四章 4.1 节）

### 2.3 界面布局

Bilibili 系列教程对界面布局有详细的视频演示 [11]，以下为文字描述：

启动后主界面分为五个区域：

- **菜单栏与工具栏**（顶部）：包含 File、Segment、Analyze、Measure、Script 等主菜单，工具栏提供常用操作的快捷按钮
- **三视图窗口**（中央左侧）：轴状位（Axial）、冠状位（Coronal）、矢状位（Sagittal）三个二维切片视图，可同步联动显示当前切片位置
- **3D 视图窗口**（中央右侧）：实时渲染当前所有激活 Part 和 Mask 的三维模型
- **对象管理器（Objects Panel）**（左侧面板）：树状列表显示项目中所有对象，包括 Images（图像堆栈）、Masks（掩膜）、Parts（三维模型）、Measurements（测量）等
- **属性面板（Properties Panel）**（底部或右侧）：显示当前选中对象的属性，如 Mask 的颜色、可见性、HU 阈值范围等
- **脚本库（Scripting Library）**（Script 菜单 → Scripting Library）：用于管理和运行已保存的脚本

---

## 三、基本操作流程——从 DICOM 到 3D 模型

### 3.1 导入医学图像数据

**菜单路径**：File → Import Images

Mimics 支持 DICOM（最常用）、BMP、TIFF 等格式。导入 DICOM 时，软件会自动扫描所选文件夹中的所有序列，并按 Series UID 分组显示。选择目标序列后，需注意以下参数：

- **层厚（Slice Thickness）**：层厚越小，三维重建精度越高，但文件体积也更大；CT 骨骼重建通常使用 ≤1 mm 层厚
- **方向校正（Orientation）**：导入后若图像方向不正确，可通过 Tools → Reorient 调整
- **图像堆栈（Image Stack）**：导入成功后，图像以堆栈形式出现在对象管理器中，是所有分割操作的数据源

### 3.2 图像分割（Segmentation）——核心功能详解

分割的本质是在图像堆栈上创建 **Mask（掩膜）**——一个与图像等大的二值体素标记，标记为"1"的体素将被包含在分割结果中。

#### 3.2.1 阈值分割（Thresholding）

**菜单路径**：Segment → Thresholding

阈值分割基于 **Hounsfield 单位（HU 值，Hounsfield Unit）** 对 CT 图像进行分割。HU 值代表不同组织对 X 射线的衰减程度，典型范围如下：

| 组织类型 | HU 值范围 | 说明 |
|---|---|---|
| 空气 | 约 -1000 | 肺部、气道 |
| 脂肪 | -150 ~ -50 | 皮下脂肪 |
| 软组织 | -50 ~ 150 | 肌肉、器官 |
| 骨骼（松质骨） | 150 ~ 700 | 椎体、骨盆 |
| 骨骼（密质骨）| 700 ~ 3071 | 长骨骨皮质 |
| 金属植入物 | >3000 | 可能产生伪影 |

Mimics 提供预设阈值方案（如"Bone"、"Soft Tissue"），也可手动拖动滑块设置上下限。调整阈值时，三视图中的彩色高亮区域实时更新，便于直观判断分割范围。

**注意**：CT 图像内部存储的是灰度值（Gray Value，GV），与 HU 值之间需通过线性转换换算。Mimics 提供了 `mimics.segment.GV2HU()` 和 `mimics.segment.HU2GV()` 两个 API 函数专门处理此转换（详见第四章）。

#### 3.2.2 区域生长（Region Grow）

**菜单路径**：Segment → Region Grow

区域生长用于从已有 Mask 中提取**连通的特定结构**，解决阈值分割后多个解剖结构连在一起的问题。操作流程：

1. 先通过阈值分割创建初始 Mask（包含所有符合 HU 范围的体素）
2. 在目标结构上点击**种子点（Seed Point）**
3. 软件从种子点出发，仅保留与其空间连通的体素，删除其他孤立区域

连通性参数（6连通/18连通/26连通）决定了体素间的邻域关系，数值越大越宽松，可能将本应分离的结构连接在一起。

#### 3.2.3 手动编辑工具

对于自动分割无法精确处理的区域（如骨骼边界模糊、金属伪影），可使用手动工具：

- **画笔工具（Draw）**：在切片上手动涂抹添加体素到 Mask
- **橡皮擦（Erase）**：删除 Mask 中的体素
- **智能填充（Smart Fill）**：自动填充 Mask 内部的空洞区域
- **多层编辑**：按住 Shift 或设置层范围，可同时对多个切片执行相同操作，大幅提高效率

#### 3.2.4 布尔运算（Boolean Operations）

**菜单路径**：Segment → Boolean Operations

布尔运算对两个 Mask 进行集合操作：

- **Unite（合并/并集）**：合并两个 Mask 的体素，用于将分开分割的结构合并为一体
- **Minus（相减/差集）**：从 Mask A 中减去 Mask B 的体素，典型用途是从骨骼 Mask 中去除金属植入物伪影区域
- **Intersect（相交/交集）**：保留两个 Mask 共有的体素，用于提取重叠区域

#### 3.2.5 孔洞填充（Fill Holes）

**菜单路径**：Segment → Fill Holes

由于 CT 扫描噪声或骨小梁结构，分割后的 Mask 内部常存在空洞。Fill Holes 有两种模式：

- **2D 填充**：逐切片填充每层的封闭空洞，速度快，适合薄壁结构
- **3D 填充**：在三维空间中填充封闭的空腔，适合需要实心模型的场景（如有限元分析前处理）

#### 3.2.6 形态学操作（Morphology Operations）

形态学操作（Morphology Operations）是超出基础工作流但极为实用的高级分割工具，可对 Mask 进行**膨胀（Dilate）**或**腐蚀（Erode）**处理。腐蚀操作可去除 Mask 边缘的噪声像素，膨胀操作可弥合细小间隙。在脚本中的调用方式详见第四章。

### 3.3 生成 3D 模型（Calculate Part）

**菜单路径**：Segment → Calculate Part

当 Mask 分割满意后，执行 Calculate Part 将其转换为可操作的三维网格模型（Part）。质量选项的权衡：

| 质量选项 | 三角面数量 | 文件大小 | 适用场景 |
|---|---|---|---|
| Optimal | 最多 | 最大 | 高精度科研、有限元分析 |
| High | 较多 | 较大 | 一般科研、3D 打印 |
| Medium | 适中 | 适中 | 快速预览、初步验证 |

生成 Part 后，可通过 Tools → Smooth 对表面进行平滑处理，减少阶梯伪影。

### 3.4 测量与分析

Mimics 内置多种测量工具（Measure 菜单）：

- **距离测量（Distance Measurement）**：点选两点，获取三维空间距离
- **角度测量（Angle Measurement）**：三点定义角度
- **体积/面积统计**：右键点击 Part 或 Mask，可在属性面板查看体积、表面积等参数
- **`indicate_point` 功能**：在脚本自动化场景中，`mimics.analyze.indicate_point()` 允许脚本暂停，等待用户在视图中手动点击一个坐标点，再将坐标传回脚本继续执行——这是实现"半自动化"工作流的关键机制

### 3.5 导出与保存

- **保存项目**：File → Save Project，生成 `.mcs` 格式文件（包含图像数据和所有对象）
- **导出 3D 模型**：File → Export → Part，支持 STL、OBJ、VRML 等格式
- **子项目（Subproject）**：仅保存部分对象（如单个图像堆栈），文件更小，适合在 Mimics 与 3-matic 之间传递数据（详见 4.3.7 节）

---

## 四、Python 脚本集成与自动化——Research 版的核心竞争力

### 4.1 脚本系统架构

**Mimics Research 版与普通版的本质区别，在于提供了完整的 Python API，使软件内的几乎所有操作都可通过代码驱动。** 官方 FDA 510(k) 提交文件也将"创建 Python 脚本以自动化工作流"列为 MIS 21.0 的核心功能之一。

**三种脚本执行方式**：

1. **内置脚本编辑器（Script Editor）**：Script 菜单 → Script Editor，直接在软件内编写和运行，支持对象名称自动补全 [3]
2. **Script Listener（外部 IDE 连接）**：21.0 新增功能。在 Mimics 中启动 Listener（Script 菜单 → Start Listening），然后在 PyCharm、Eclipse、Visual Studio 中配置连接到指定端口，即可从外部 IDE 调试和执行脚本 [3]。3-matic 的对应端口默认为 15005
3. **脚本库（Scripting Library）**：Script 菜单 → Scripting Library，将常用脚本注册为库，可一键调用甚至添加到菜单栏作为自定义按钮

**加载机制**：`mimics` 模块由 Mimics 进程注入，仅在软件运行时有效。外部独立 Python 环境无法导入此模块，因此所有脚本必须在 Mimics 进程上下文中执行。

**Scripting Guide 获取**：完整的 API 参考文档位于软件内部，路径为 Help 菜单 → Scripting Guide，其中附录 A 包含 API Change Log [3]。

### 4.2 mimics Python API 模块结构

API 的命名遵循 `software.tab.operation` 的三层结构，例如 `mimics.segment.threshold` 对应"Mimics 软件 → Segment 标签页 → Threshold 操作" [7]。这一设计使 API 名称与界面操作直接对应，极大降低了学习门槛。

| 顶级模块 | 主要函数/子对象 | 功能说明 |
|---|---|---|
| `mimics.data` | `.images.get_active()`, `.masks.get_all()`, `.masks.find()`, `.parts`, `.objects.find()` | 数据访问层，读取当前项目中的所有对象 |
| `mimics.segment` | `.create_mask()`, `.threshold()`, `.region_grow()`, `.boolean_operations()`, `.fill_holes()`, `.calculate_part()`, `.calculate_mask_from_part()`, `.morphology_operations()`, `.GV2HU()`, `.HU2GV()`, `.local_threshold()`, `.activate_thresholding()` | 分割操作，覆盖所有分割工作流 |
| `mimics.analyze` | `.indicate_point()`, `.create_sphere_center_radius()`, `.create_line_fit_to_surface()` | 分析工具，含交互式点选和几何体创建 |
| `mimics.file` | `.open_project()`, `.save_project()`, `.save_subproject()`, `.export_part()`, `.import_images()`, `.export_dicom()`, `.get_project_information()` | 文件操作，支持项目保存与批量处理 |
| `mimics.measure` | `.create_distance_measurement()` | 测量功能，创建距离等测量对象 |
| `mimics.tools` | `.smooth()` | 后处理工具，如网格平滑 |
| `mimics.view` | 视图控制相关 | 控制三维视图显示状态 |

### 4.3 核心 API 函数详解与代码示例

以下代码示例均来源于 Materialise 官方社区论坛及学术论文，已在实际工作流中验证 [7][13][15]。

#### 4.3.1 数据访问

```python
# 获取当前激活的图像堆栈
image = mimics.data.images.get_active()

# 获取所有 Mask 对象（返回列表）
all_masks = mimics.data.masks.get_all()

# 按名称查找特定对象
my_mask = mimics.data.masks.find("Bone_Mask")

# 按名称查找任意对象（Mask、Part 等通用方法）
obj = mimics.data.objects.find("MyObject")
```

#### 4.3.2 创建 Mask 与阈值分割

`threshold_min` 和 `threshold_max` 参数接受**灰度值（Gray Value）**，而非直接的 HU 值。需先用 `GV2HU()` / `HU2GV()` 进行换算 [7]。

```python
# 创建新 Mask
new_mask = mimics.segment.create_mask()
new_mask.name = "Bone_Mask"

# 阈值分割：参数为灰度值范围
# 若已知 HU 值，先转换：gv = mimics.segment.HU2GV(226)
mimics.segment.threshold(mask=new_mask, threshold_min=226, threshold_max=3071)

# 链式写法（社区常见风格）：
mask = mimics.segment.threshold(
    mimics.segment.create_mask(select_new_mask=True),
    threshold_min=0,
    threshold_max=3071
)
```

#### 4.3.3 区域生长

```python
# 交互式点选种子点（脚本暂停，等待用户点击）
seed_point = mimics.analyze.indicate_point(
    message="请在目标骨骼上点击种子点"
)

# 执行区域生长
grown_mask = mimics.segment.region_grow(
    mask=new_mask,
    point=seed_point
)
```

#### 4.3.4 布尔运算

```python
# 合并两个 Mask（Unite）
result = mimics.segment.boolean_operations(
    mask_a=masks[0],
    mask_b=masks[1],
    operation="Unite"   # 可选："Unite", "Minus", "Intersect"
)

# 简洁写法（社区示例）
result = mimics.segment.boolean_operations(masks[0], masks[1], "Unite")
```

#### 4.3.5 孔洞填充与形态学操作

```python
# 填充孔洞
mimics.segment.fill_holes(mask=my_mask)

# 形态学腐蚀（去除边缘噪声像素）
mimics.segment.morphology_operations(
    mask=my_mask,
    operation='Erode',       # 或 'Dilate'
    number_of_pixels=1,
    connectivity=8
)
```

上述形态学操作的完整参数签名来自学术论文中的实际代码 [13]。

#### 4.3.6 生成 3D Part

```python
# 从 Mask 生成三维模型
part = mimics.segment.calculate_part(
    mask=my_mask,
    quality="High"    # "Optimal", "High", "Medium"
)

# 平滑处理
mimics.tools.smooth(part=part)

# Part 转回 Mask（用于进一步编辑）
back_to_mask = mimics.segment.calculate_mask_from_part(part=part)
```

`calculate_mask_from_part()` 函数对应界面中的"Mask from Object"功能，经社区论坛确认可通过脚本调用 [15]。

#### 4.3.7 文件操作

```python
# 保存完整项目
mimics.file.save_project(filename=r"C:\Projects\my_project.mcs")

# 获取当前项目路径
info = mimics.file.get_project_information()
project_path = info.path

# 保存子项目（仅含指定图像，速度更快，用于 Mimics→3-matic 数据传递）
mimics.file.save_subproject(
    r"C:\Temp\sub.mcs",
    [mimics.data.images.get_active()]
)

# 导出 STL 文件
mimics.file.export_part(part=part, file_path=r"C:\Output\bone.stl")

# 导出 DICOM（用于格式转换，如 DICOM→NIfTI 等下游处理）
mimics.file.export_dicom(...)
```

`save_subproject()` 的完整调用示例来自官方社区论坛 [16]，该函数比 `save_project()` 速度更快，是 Mimics 与 3-matic 之间传递数据的推荐方式。

#### 4.3.8 获取图像灰度/HU 数据

```python
# 获取激活图像堆栈（可进一步访问像素数据）
image = mimics.data.images.get_active()

# HU 值与灰度值互转
hu_value = mimics.segment.GV2HU(gray_value)
gv_value = mimics.segment.HU2GV(hu_value)
```

访问逐像素数据的完整方法可参考社区论坛专题帖 [17]，该功能常用于定量分析（如骨密度计算、CNR 计算等）。

### 4.4 完整自动化脚本示例

以下两个示例基于 Materialise 官方社区论坛发布的 Demo 脚本 [7][18]，已整理为带注释的完整版本。

#### 示例一：股骨（Femur）自动分割脚本

```python
import mimics

# ── 1. 打开项目 ──────────────────────────────────────────
mimics.file.open_project(r"C:\Data\femur_case.mcs")
image = mimics.data.images.get_active()

# ── 2. 创建 Mask 并执行阈值分割 ────────────────────────────
# 注意：threshold_min/max 为灰度值，需根据实际设备校准
bone_mask = mimics.segment.create_mask()
bone_mask.name = "Femur_Raw"
mimics.segment.threshold(
    mask=bone_mask,
    threshold_min=226,
    threshold_max=3071
)

# ── 3. 孔洞填充（先填洞再区域生长，效果更稳定）──────────────
mimics.segment.fill_holes(mask=bone_mask)

# ── 4. 区域生长（半自动：用户点击股骨种子点）──────────────────
seed = mimics.analyze.indicate_point(message="请点击股骨区域")
femur_mask = mimics.segment.region_grow(
    mask=bone_mask,
    point=seed
)
femur_mask.name = "Femur_Segmented"

# ── 5. 布尔运算（可选：去除其他连通骨骼）─────────────────────
# 若存在其他骨骼 mask，此处可执行 Minus 操作
# femur_mask = mimics.segment.boolean_operations(
#     femur_mask, other_mask, "Minus"
# )

# ── 6. 生成 3D Part ────────────────────────────────────
femur_part = mimics.segment.calculate_part(
    mask=femur_mask,
    quality="High"
)
mimics.tools.smooth(part=femur_part)

# ── 7. 导出 STL 并保存项目 ────────────────────────────────
mimics.file.export_part(
    part=femur_part,
    file_path=r"C:\Output\femur.stl"
)
mimics.file.save_project(filename=r"C:\Output\femur_result.mcs")
print("股骨分割完成！")
```

#### 示例二：颅骨（Skull）自动分割脚本

颅骨分割的难点在于颅骨与面骨、颈椎在 CT 中连续，需要更精确的阈值控制。此示例基于社区 Skull 分割 Demo [18]：

```python
import mimics

mimics.file.open_project(r"C:\Data\head_ct.mcs")

# 颅骨使用较高阈值（避免软组织混入）
skull_mask = mimics.segment.create_mask()
skull_mask.name = "Skull_Raw"
mimics.segment.threshold(
    mask=skull_mask,
    threshold_min=1250,   # 对应高密度骨皮质
    threshold_max=2800
)

# 交互式选择颅骨种子点
seed = mimics.analyze.indicate_point(message="请点击颅骨区域")
skull_segmented = mimics.segment.region_grow(
    mask=skull_mask,
    point=seed
)
skull_segmented.name = "Skull_Final"

skull_part = mimics.segment.calculate_part(
    mask=skull_segmented,
    quality="Optimal"
)

mimics.file.save_project(filename=r"C:\Output\skull_result.mcs")
```

#### 示例三：批量处理脚本框架

```python
import mimics
import os

# 批量处理多个 DICOM 文件夹
dicom_dirs = [
    r"C:\Data\Case001",
    r"C:\Data\Case002",
    r"C:\Data\Case003",
]
output_dir = r"C:\Output"

for case_dir in dicom_dirs:
    case_name = os.path.basename(case_dir)
    print(f"正在处理：{case_name}")

    try:
        # 导入 DICOM
        mimics.file.import_images(case_dir)
        image = mimics.data.images.get_active()

        # 标准骨骼分割流程
        mask = mimics.segment.create_mask()
        mimics.segment.threshold(mask=mask, threshold_min=226, threshold_max=3071)
        mimics.segment.fill_holes(mask=mask)

        # 生成 Part 并导出
        part = mimics.segment.calculate_part(mask=mask, quality="High")
        stl_path = os.path.join(output_dir, f"{case_name}_bone.stl")
        mimics.file.export_part(part=part, file_path=stl_path)

        # 保存项目
        mcs_path = os.path.join(output_dir, f"{case_name}.mcs")
        mimics.file.save_project(filename=mcs_path)
        print(f"  ✓ 已保存：{stl_path}")

    except Exception as e:
        print(f"  ✗ 处理失败：{e}")
        continue
```

自动报告生成的完整示例可参考 YouTube 官方频道的演示视频 [9]，其展示了如何将测量结果自动写入报告文件。

### 4.5 脚本开发调试技巧

**交互式测试**：在 Mimics 内置脚本控制台（Script Console）中逐行输入命令，实时查看返回值，是快速验证 API 用法的最佳方式。自动补全功能（21.0 新增）可在输入 `mimics.segment.` 后自动列出可用函数。

**错误处理最佳实践**：

```python
try:
    part = mimics.segment.calculate_part(mask=my_mask, quality="High")
    if part is None:
        raise ValueError("Part 生成失败，请检查 Mask 是否为空")
except Exception as e:
    print(f"错误详情：{e}")
    # 可选：保存当前状态以便排查
    mimics.file.save_project(filename=r"C:\Debug\error_state.mcs")
```

**与 3-matic 联动**：Mimics 与 3-matic 是 MIS 套件的两个组件，分别处理图像分割和网格后处理。联动方式有两种：
1. 使用 `mimics.file.save_subproject()` 将数据传递给 3-matic，在 3-matic 中使用 `trimatic` 模块继续处理
2. 通过 Script Listener 建立两软件间的实时脚本连接（需在 3-matic 中启动端口监听）

**PyAutoGUI 辅助自动化**：对于 API 尚未覆盖的 GUI 操作，社区用户发现可结合 `pyautogui` 库模拟鼠标点击和键盘输入，例如在 Mimics 和 3-matic 之间通过复制粘贴传递网格对象 [16]。这是一种权宜方案，稳定性依赖于界面布局不变。

### 4.6 API 版本兼容性与 21.0 特有注意事项

**从旧版本迁移**：所有来自 20.0 及更早版本的脚本，在 21.0 中使用前必须重新验证 [3]。检查方法：对照 Release Notes 附录 B 的工具移动/重命名查找表，逐一核对脚本中调用的函数名。

**21.0→22.0 适配**：社区论坛中大量示例基于 22.0，但函数签名在两个版本间高度一致。主要风险点是部分参数名称或默认值可能有细微变化，建议在 21.0 中运行时捕获 `TypeError` 异常以定位不兼容之处。

**阈值参数的灰度值问题**：这是新手最常见的困惑点——`threshold_min`/`threshold_max` 接受的是**灰度值**而非 HU 值，两者之间的换算系数因 CT 设备而异，需使用 `GV2HU()`/`HU2GV()` 在脚本中动态转换，而非硬编码 HU 值 [7]。

---

## 五、高级功能与专业应用场景

### 5.1 DICOM 数据匿名化

Mimics 21.0 的 Python API 支持对 `.mcs` 项目文件和 DICOM 图像中的患者信息进行**批量去标识化（de-identification）**处理，满足数据共享和科研伦理要求。这一功能通过 `mimics.file` 模块的相关接口实现，是 21.0 版本新增的 API 能力之一。

### 5.2 自定义菜单按钮

通过 Scripting Library，用户可将常用脚本注册为菜单栏按钮，使非技术背景的团队成员也能一键运行复杂的自动化流程。社区论坛有专题讨论如何配置自定义菜单项 [7]。

### 5.3 有限元分析（FEA）前处理工作流

GitHub 仓库 `mimics_3matic_Python_scripting` 提供了一套完整的 FEA 前处理脚本 [10]，包括：

- `wrap_and_smooth_fem.py`：对骨骼模型进行包裹和平滑
- `material_assignment.py`：基于 HU 值自动分配材料属性
- `create_mesh.py`：生成体积网格

这套脚本展示了 Mimics（图像分割）→ 3-matic（网格处理）→ FEA 软件的完整自动化管道，所需依赖包为 `mimics`、`trimatic`、`numpy` [10]。

### 5.4 4D 心脏可视化与 CT 心脏标记

社区论坛展示了利用 `mimics.data.images`、`mimics.view` 等模块实现 4D 心脏 Cineloop（动态心脏序列）可视化的脚本，以及基于 `mimics.analyze.create_sphere_center_radius()` 实现 CT 心脏解剖标记点自动化定位的案例，体现了 API 在心血管影像研究中的应用潜力。

### 5.5 场景分析：自动化程度选择策略

实际工作中，并非所有情况都适合完全自动化脚本，以下两种场景供参考：

**场景 A：标准化、批量化的科研数据集**
当所有病例的扫描协议一致（相同设备、相同层厚、相同序列），可编写全自动脚本（无 `indicate_point` 调用），通过批量处理框架（示例三）实现无人值守运行。这是 FEA 研究、骨骼形态学研究等场景的最佳选择。

**场景 B：临床数据集或图像质量参差不齐**
当数据来自多台设备或存在金属伪影，全自动分割容易失败。推荐采用"半自动"模式：脚本处理标准化步骤（阈值、填洞），在关键决策点（种子点选择、边界修正）通过 `indicate_point()` 暂停等待用户交互，兼顾效率与准确性。

---

## 六、学习路径建议

### 6.1 新手推荐路径（从零到可用）

| 阶段 | 目标 | 推荐资源 | 预计时间 |
|---|---|---|---|
| 第 1 阶段：认知建立 | 理解软件界面与基本概念 | Bilibili 系列教程 M1-M3 [11] | 2-3 小时 |
| 第 2 阶段：基础操作 | 完成一次完整的 DICOM→STL 流程 | Materialise Academy 快速入门视频；CSDN 博客 [12] | 3-4 小时 |
| 第 3 阶段：脚本入门 | 配置 Python 环境，运行第一个脚本 | 官方视频：How to Install Python [5]；Wout Learns Scripting Ep.1 [8] | 2-3 小时 |
| 第 4 阶段：脚本进阶 | 理解 API 结构，能够修改示例脚本 | 官方免费课程 [4]；社区论坛 Femur/Skull Demo [7] | 1-2 天 |
| 第 5 阶段：自主开发 | 编写针对自己数据的自动化脚本 | Scripting Guide（软件内 Help 菜单）；GitHub 示例 [10] | 持续学习 |

### 6.2 中文资源说明

中文资源主要覆盖**安装与基础操作**，脚本开发内容相对有限。Bilibili 系列教程 [11] 包含安装、界面布局、文件操作、基础分割（阈值、区域生长、3D 重建）以及颈椎重建、气管/肺部重建等案例实战，适合完全零基础的新手建立操作直觉。CSDN 博客 [12] 则提供了包含二值化处理、区域生长参数、有限元分析工作流等内容的文字教程，便于查阅。脚本开发阶段建议切换到英文资源，社区论坛和官方 Academy 的内容深度远超中文资源。

### 6.3 遇到问题时的求助渠道

1. **官方 Scripting Guide**（软件内 Help 菜单）：API 完整参考，应作为第一查询来源
2. **MIS Scripting Forum**（community.materialise.com）[7]：官方社区，可发帖提问，Materialise 工程师会参与回答
3. **Materialise Academy 免费课程** [4]：系统化的脚本学习路径，含视频和练习
4. **GitHub 示例仓库** [10]：参考实际可运行的脚本

---

## 参考文献

[1] Materialise Software Instructions for Use. https://www.materialise.com/en/documentation/software-instructions-for-use

[2] IFU Mimics Research 21.0 - English - L-10790-02. https://www.scribd.com/document/702919706/IFU-Mimics-Research-21-0-English-L-10790-02

[3] ReleaseNotes MimicsResearch 21.0. https://www.scribd.com/document/769697778/ReleaseNotes-MimicsResearch-21-0

[4] A Comprehensive Guide to Mimics Innovation Suite Scripting (Free Course). https://go.materialise.com/en/medical/mimics-innovation-course-scripting

[5] How to Install Python to Use with Mimics and 3-Matic - Materialise Academy. https://www.materialise.com/en/academy/healthcare/mimics-innovation-suite/video-tutorials/install-python

[6] Tutorial: How to Get Set Up and Use Scripting in 3-Matic - Materialise Academy. https://www.materialise.com/en/academy/healthcare/mimics-innovation-suite/video-tutorials/scripting-3-matic

[7] MIS Scripting Forum - Materialise Community. https://community.materialise.com/c/mis-scripting-forum/5

[8] Wout Learns Scripting in Mimics Ep. 1: Getting Started with Automation. https://www.youtube.com/watch?v=IjKct3lO2Is

[9] Materialise Mimics Simple Auto Report Generation Script. https://www.youtube.com/watch?v=Ybmf7rJ6m5o

[10] mimics_3matic_Python_scripting - GitHub. https://github.com/fahimehazari/mimics_3matic_Python_scripting

[11] 医学三维重建_Mimics Research 21.0 系列教程 - Bilibili. https://www.bilibili.com/video/BV1ui4y1w7H4/

[12] Mimics 21.0 安装教程 - CSDN 博客 (YanLu99). https://blog.csdn.net/YanLu99/article/details/119546777

[13] Sydney DHT MSc Thesis - Mimics Scripting API Usage Examples. https://skemman.is/bitstream/1946/51344/1/Sydney_DHT_MSc_Thesis_Final.pdf

[14] 3-matic Research 13.0 paired with Mimics Research 21.0 - Materialise Community. https://community.materialise.com/t/femur-segmentation-mimics-22-0/76

[15] Can Mask from Object be Called from a Script? - Materialise Community. https://community.materialise.com/t/can-mask-from-object-be-called-from-a-script/895

[16] Moving Meshes Between 3-matic and Mimics - Materialise Community. https://community.materialise.com/t/moving-meshes-between-3matic-and-mimics/279

[17] Getting Hounsfield or Gray Value Data from an Image Stack - Materialise Community. https://community.materialise.com/t/getting-houndsfield-or-gray-value-data-from-an-image-stack/313

[18] Skull Segmentation Mimics 22.0 - Materialise Community. https://community.materialise.com/t/skull-segmentation-mimics-22-0/75
