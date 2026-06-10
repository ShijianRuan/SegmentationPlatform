# Mimics 标注工具 POC 验证方案

> 版本：v0.2
> 日期：2026-06-10
> 状态：执行草案；API 参考以 `docs/domains/labeling/mimics_reference.md` 为准；事实边界以 `docs/domains/labeling/mimics_feasibility.md` 为准

---

## 1. 结论先行

Mimics 不应直接被定为平台唯一标注工具。它应先作为优先 POC 候选，因为它的人机交互和医学图像工程能力很强，但平台真正需要的是可重复、可追踪、可自动导入导出的标注管线能力。

POC 要回答一个具体问题：

> Mimics 能否在“Windows 本地标注 + 远程训练服务器”的现实约束下，稳定承担 Case Package Review 工具？

如果答案是“能”，就开发 Mimics Adapter；如果答案是“不稳定或自动化边界太窄”，就把 Mimics 作为人工高级修正工具，同时并行评估 3D Slicer/MONAI Label 或其他工具。

---

## 2. 验证范围

### 2.1 必须验证

| 编号 | 验证项 | 目标 |
|---|---|---|
| M1 | 图像导入 | 能打开 `ct.nii.gz` 或 DICOM，并保持空间信息 |
| M2 | 草稿导入 | 能把 `draft_label.nii.gz` 拆为多个 Mimics Mask，名称和颜色正确 |
| M3 | 人工修正 | 标注员能在 Mimics 中正常编辑、保存 |
| M4 | 标签导出 | 能导出单个多标签 NIfTI，或逐器官二值 mask |
| M5 | 空间往返 | 导出的标签与原始 CT shape/spacing/origin/direction 一致或可无损校正 |
| M6 | ID 映射 | Mimics Mask 名称能稳定映射回平台统一器官名称和 `review_label_map.yaml` |
| M7 | 批量可用 | 至少 3 个病例重复执行，不靠临时手工命名 |
| M8 | 本地远程流转 | Windows 侧导出的 review package 能回到远程训练环境通过校验 |

### 2.2 暂不验证

| 项目 | 暂不验证原因 |
|---|---|
| Mimics Flow 云端 AI 分割 | 不是平台闭环的必要条件，且受许可/网络限制 |
| Custom Plugin | 成本较高，先用 Python 脚本验证边界 |
| 临床合规流程 | 当前目标是研究/工程数据闭环，不是临床部署 |
| 167 个器官全量标注体验 | POC 先验证机制，后续再做规模化人因评估 |

---

## 3. 输入数据

建议使用 3-5 个病例，每个病例生成 `Case Package v0.1`：

| 病例类型 | 目的 |
|---|---|
| 无标签病例 | 验证从零创建 mask 和导出 |
| 有公开算法草稿病例 | 验证 `draft_label` 导入、显示和修正 |
| 部分器官已有标签病例 | 验证已有人工作为最高优先级、新草稿补缺失器官 |
| 空间边界病例 | 验证 spacing 非等距、方向复杂或扫描范围不完整时的往返 |

每个病例至少包含：

```text
manifest.json
review_label_map.yaml
images/ct.nii.gz
tool/color_table.json
tool/label_mapping.json
checksums.sha256
```

有草稿时额外包含：

```text
labels/draft_label.nii.gz
labels/sources/{source_name}.nii.gz
```

---

## 4. POC 操作流程

### 4.1 准备阶段

```text
远程/本地脚本生成 Case Package
  ↓
复制到 Windows Mimics 工作机
  ↓
运行 Mimics import 脚本或按导入说明手动导入
```

准备阶段输出：

```text
review_workspace/
├── case_package_*
├── mimics_import_log.json
└── screenshots/                      # 可选：记录导入结果
```

### 4.2 Mimics Review 阶段

要求人工只做三件事：

1. 检查图像和已有草稿是否对齐。
2. 修正目标器官 mask。
3. 保存并运行导出脚本。

不希望人工做：

1. 手动重命名所有 mask。
2. 手动整理导出目录。
3. 手动填写复杂 checklist。
4. 手动判断训练准入策略。

### 4.3 导回阶段

```text
Mimics 导出 raw labels
  ↓
mimics ingest 脚本转换
  ↓
生成 Review Export Package
  ↓
复制回 Registry / 训练环境
  ↓
运行 geometry + label ID 校验
```

导回阶段输出：

```text
review_export_{case_id}_{review_id}/
├── manifest.json
├── labels/
│   └── verified_label.nii.gz
├── reports/
│   ├── geometry_check.json
│   ├── label_mapping_check.json
│   └── diff_from_draft.json
└── checksums.sha256
```

---

## 5. 关键实验

### M1. 图像导入

步骤：

1. 在 Mimics 中导入 `images/ct.nii.gz`。
2. 如果 NIfTI 导入不稳定，改用 `images/dicom/`。
3. 记录 Mimics 内显示的 spacing、slice 数、方向。

通过标准：

1. CT 可以打开。
2. 视图方向符合医学常识。
3. 导入后导出的参考图像与原始图像 shape/spacing 一致，或差异可被脚本解释。

失败处理：

1. NIfTI 导入失败但 DICOM 成功：Case Package 必须强制包含 DICOM。
2. DICOM 也不稳定：Mimics 不适合作为首选管线工具。

### M2. 草稿导入

步骤：

1. 将 `draft_label.nii.gz` 按 `review_label_map.yaml` 拆成逐器官二值 mask。
2. 导入 Mimics。
3. 检查 mask 名称、颜色、可见性、与 CT 对齐。

通过标准：

1. 每个目标器官都成为一个独立 Mimics Mask。
2. Mask 名称与平台统一器官名称或 `review_label_map.yaml` key 一致。
3. 颜色与 `color_table.json` 一致或可接受。
4. 至少 3 个病例不需要手工重命名。

失败处理：

1. 若只能手动导入和命名，Mimics 只能作为临时人工工具，不能作为自动管线工具。

### M3. 人工修正体验

步骤：

1. 标注员对每个病例修正 1-3 个器官。
2. 记录每例耗时、明显卡顿、误操作点。
3. 保存 Mimics 项目。

通过标准：

1. 标注员能自然完成修正。
2. 修正后的 mask 可稳定保存。
3. 不要求逐器官 checklist。

### M4. 标签导出

步骤：

1. 从 Mimics 导出每个 mask。
2. 如果支持单多标签 NIfTI，优先使用单文件。
3. 如果只支持逐 mask 导出，则用 ingest 脚本合并。

通过标准：

1. 导出文件可由 Python/SimpleITK/nibabel 读取。
2. 文件命名可自动映射回器官 key。
3. 没有未知 label 或重复 label。

### M5. 空间往返

步骤：

1. 读取原始 `ct.nii.gz`。
2. 读取导出的 `verified_label.nii.gz`。
3. 比较 shape、spacing、origin、direction、affine。
4. 若不一致，尝试 nearest-neighbor 重采样到 CT 网格。

通过标准：

1. 最好完全一致。
2. 若不完全一致，必须能无歧义重采样回 CT 网格。
3. 重采样后标签边界无明显整体偏移、翻转或轴置换错误。

失败处理：

1. 出现无法稳定解释的 affine/方向问题：Mimics Adapter 暂停，优先测试 3D Slicer。

### M6. 导入训练管线

步骤：

1. 将 Review Export Package 导入 Data Registry。
2. 创建小型 dataset snapshot。
3. 运行 nnUNet Action1 转换。

通过标准：

1. 训练快照只包含 `verified_label`。
2. `draft_label` 不进入 labelsTr。
3. review label ID 与 `review_label_map.yaml` 一致；训练 label ID 由任务级 TaskLabelMap 决定。

---

## 6. 判定矩阵

| 结果 | 判定 | 后续动作 |
|---|---|---|
| M1-M6 全部通过 | Mimics 可作为第一优先标注工具 | 开发 `adapters/mimics`，进入小闭环 |
| M1/M3 通过，M2/M4/M5 需人工 | Mimics 可作为人工高级工具，不适合作为自动管线主工具 | 并行评估 3D Slicer/MONAI Label，Mimics 用于疑难病例 |
| M5 失败 | Mimics 暂不进入主流程 | 优先解决空间往返或切换工具 |
| M3 失败 | 标注体验不满足 | 不推荐 Mimics，改评估其他工具 |
| 许可/脚本权限受限 | 工程不可控 | 降级为手动辅助工具 |

---

## 7. 需要准备的脚本

拿到 Mimics 软件和 license 后，不要马上开发完整 Adapter。先分两类验证：

| 类别 | 要验证什么 | 结论用途 |
|---|---|---|
| Mimics 本身功能 | 图像导入、草稿显示、人工编辑、标签导出、空间往返 | 判断 Mimics 能否作为 review 工具 |
| 脚本联动能力 | Python scripting 权限、批量创建 mask、自动命名/配色、读取/导出 mask buffer | 判断 Mimics 能否成为自动化 Adapter |

建议顺序：

1. 确认 license 是否包含 Python scripting。
2. 在 Help 中打开 Scripting Guide，**对照 `mimics_reference.md` §5 的关键 API 清单逐项确认**。
3. **优先验证 M5（空间往返）**，因为 DICOM↔NIfTI affine 转换是已知社区问题（详见 `mimics_reference.md` §4-M5）。
3. 用一个病例手动完成 DICOM/NIfTI 图像导入。
4. 用一个病例测试逐器官 mask 导入、编辑、导出。
5. 导出后立刻跑 `check_geometry.py`，不要等多个病例后再查。
6. 手动路径通过后，再写 `import_case_package.py` 和 `export_review_package.py`。

### 7.1 平台侧脚本

```text
scripts/package_case.py
scripts/split_multilabel_to_masks.py
scripts/merge_masks_to_multilabel.py
scripts/check_geometry.py
scripts/check_label_ids.py
scripts/hash_package.py
```

### 7.2 Mimics 侧脚本

```text
adapters/mimics/import_case_package.py
adapters/mimics/export_review_package.py
adapters/mimics/README_for_annotators.md
```

Mimics 侧脚本第一版只要求：

1. 打开/导入 CT。
2. 导入逐器官 mask。
3. 设置 mask 名称和颜色。
4. 提供一键导出当前 mask 集合。

### 7.3 为什么先用逐器官 mask

逐器官 mask 是 POC 阶段的保守交换格式，不是平台最终唯一格式。

原因：

1. Mimics 内部更自然的对象通常是一个结构一个 mask。
2. 单个多标签 NIfTI 依赖工具正确解释 label id、名称、颜色和多类别编辑。
3. 逐器官 mask 的命名可以直接绑定 `anatomy_vocabulary` 或 `review_label_map.yaml`。
4. 导出后哪个器官错位、丢失或为空，更容易定位。
5. 平台可以在导回时再用 `merge_masks_to_multilabel.py` 合成训练需要的多标签文件。

---

## 8. 不通过时的备选路线

| 工具 | 优势 | 风险 |
|---|---|---|
| 3D Slicer + Segment Editor | 免费、Python 自动化强、医学影像生态成熟 | 用户体验和培训成本可能高 |
| 3D Slicer + MONAI Label | 标注和模型辅助结合成熟，可借鉴主动学习 | 上手门槛高，仍偏工具而非平台 |
| MITK | 医学图像桌面工具，MONAI Label 有部分集成 | 生态和国内使用经验可能少 |
| ITK-SNAP | 简洁稳定，适合人工分割 | 自动化和多源融合能力弱 |
| OHIF/Web 自研 | 最终平台体验最好，适合协作 | 初期开发成本高，3D 编辑能力难做 |

建议策略：

1. Mimics POC 与 3D Slicer 最小 POC 可以并行，但 Mimics 优先。
2. 最终平台不绑定工具，保留 `tool_adapter` 接口。
3. 无论工具如何选择，Case Package 契约不变。

---

## 9. POC 结束交付物

POC 完成后应产出：

1. `mimics_poc_report.md`
2. 3-5 个 `Case Package`
3. 3-5 个 `Review Export Package`
4. geometry / label ID 校验报告
5. 是否开发 Mimics Adapter 的决策

决策模板：

```text
Mimics POC 结论：
- 工具结论：通过 / 部分通过 / 不通过
- 最大风险：
- 是否进入主流程：
- 是否需要备选工具并行：
- 下一步工程任务：
```
