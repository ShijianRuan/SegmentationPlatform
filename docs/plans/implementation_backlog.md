# 分割平台近期实现 Backlog

> 日期：2026-06-06
> 范围：Case Package v0.1 + Mimics POC + 手动闭环
> 状态：执行草案，不是架构主文档；当前主设计以 `docs/architecture/platform_blueprint.md` 为准。

> 说明：本文属于执行草案。相关实现应优先按三大域理解位置：
> `labeling` 负责病例包、导入导出、人工 review；
> `training` 负责 nnUNet 小闭环；
> `label_generation` 负责候选标签和下一轮草稿回流。
>
> 2026-10-30 前的总体节奏、里程碑和验收清单见
> `docs/plans/platform_implementation_plan_2026-10-30.md`。
> 本文主要服务该计划中的 M0-M3 近期落地任务。

---

## 1. 当前不应做的事

先明确边界，避免一上来把工程拖重：

1. 不先做完整 Web UI。
2. 不先做复杂 Orchestrator。
3. 不先把 nnUNet、MONAI、Mimics 强行统一到一个大包里。
4. 不在 provenance 上造假；`candidate_label`、`accepted_pseudo_label` 是否进入训练由 `label_policy.allow_status` 显式控制。
5. 不直接认定 Mimics 是最终标注工具。

近期目标只有一个：用 3-5 个病例跑通 `Case Package -> Review -> Review Export -> Registry Import -> nnUNet Training Snapshot -> Predict Draft` 的手动闭环。

---

## 2. 里程碑

| 里程碑 | 目标 | 完成标准 |
|---|---|---|
| M0 | 样例病例选择 | 选出 3-5 个病例，覆盖无标签、有草稿、部分标签、空间边界 |
| M1 | Case Package 生成 | 每个病例可生成符合 v0.1 契约的文件夹 |
| M2 | Mimics 导入 POC | Windows Mimics 能打开 CT 与草稿 mask |
| M3 | Mimics 导出 POC | Mimics 结果能导回 `verified_label.nii.gz` |
| M4 | Registry Import | 导回包能注册为 verified 标签 |
| M5 | nnUNet 小训练 | 使用 verified 标签生成训练快照并跑通一次训练/预测 |
| M6 | 第二轮草稿 | 新模型预测能成为下一轮 `draft_label` |

---

## 3. 第一批脚本任务

### 3.1 平台侧脚本

| 任务 | 文件 | 输入 | 输出 |
|---|---|---|---|
| 生成病例包 | `scripts/package_case.py` | `ct.nii.gz`, optional labels, anatomy/review config | `case_package_*` |
| 校验病例包 | `scripts/check_case_package.py` | `case_package_*` | `preflight_report.json` |
| 拆分多标签 | `scripts/split_multilabel_to_masks.py` | `draft_label.nii.gz`, `review_label_map.yaml` | `masks/{organ}.nii.gz` |
| 合并二值 mask | `scripts/merge_masks_to_multilabel.py` | `masks/*.nii.gz`, `review_label_map.yaml` | `verified_label.nii.gz` |
| 空间校验 | `scripts/check_geometry.py` | `ct.nii.gz`, label | `geometry_check.json` |
| hash 生成 | `scripts/hash_package.py` | package dir | `checksums.sha256` |

当前进度：

| 状态 | 脚本 | 说明 |
|---|---|---|
| 已存在 | `scripts/hash_package.py` | 无额外依赖，生成 package checksum |
| 已存在 | `scripts/check_case_package.py` | 无额外依赖，已按当前 Case Package 契约检查 `anatomy_vocabulary.yaml` 和 `review_label_map.yaml` |
| 待实现 | `scripts/split_multilabel_to_masks.py` | 需要 `numpy`, `nibabel`, `PyYAML` |
| 待实现 | `scripts/merge_masks_to_multilabel.py` | 需要 `numpy`, `nibabel`, `PyYAML` |
| 待实现 | `scripts/check_geometry.py` | 需要 `numpy`, `nibabel` 或 `SimpleITK` |

### 3.2 Mimics 侧脚本

| 任务 | 文件 | 说明 |
|---|---|---|
| 导入病例包 | `adapters/mimics/import_case_package.py` | 当前已建立占位入口；后续在 Mimics 内补齐导入逻辑 |
| 导出 Review 包 | `adapters/mimics/export_review_package.py` | 当前已建立占位入口；后续补齐导出逻辑 |
| 标注员说明 | `adapters/mimics/README_for_annotators.md` | 当前已建立第一阶段手动闭环说明 |

### 3.3 label_generation 侧脚本

| 任务 | 文件 | 所属里程碑 | 说明 |
|---|---|---|---|
| 批量推理入口 | `adapters/label_generation/run_batch_inference.py` | M6 | 对病例列表生成 candidate_label |
| QC routing | `adapters/label_generation/route_candidates.py` | M6 | 根据 QC 报告和 label_policy 决定输出到 draft/accepted_pseudo/rejected |
| candidate → draft | `adapters/label_generation/candidate_to_draft.py` | M6 | 将 candidate_label 转成下一轮 review 的 draft_label |

当前状态：目录 `adapters/label_generation/` 已建立；所有脚本待实现。M6 之前不必启动，但 backlog 需要条目占位以保证计划可追溯。

### 3.4 暂缓脚本

| 脚本 | 暂缓原因 |
|---|---|
| `orchestrator/serve` | 手动闭环未跑通前没有意义 |
| Web UI | 需求和数据状态还在变 |
| 自动主动学习策略 | 先用简单筛选和人工选择病例 |
| MONAI Adapter | nnUNet 小闭环和 Mimics POC 先跑通 |
| FewShot Adapter | 架构位置已确认，但需要 Data Registry、Dataset Snapshot 和冻结评估集后再生产级验证 |

---

## 4. 实现顺序

### Step 1. 文件契约脚本

先实现纯 Python、与 Mimics 无关的脚本：

```text
package_case.py
check_case_package.py
split_multilabel_to_masks.py
merge_masks_to_multilabel.py
check_geometry.py
hash_package.py
```

原因：这些脚本在 Mimics、3D Slicer、ITK-SNAP 之间通用，即使后面换标注工具也不会浪费。

### Step 2. Mimics 手动导入验证

先不写复杂 Mimics 插件。用一个病例包，手动在 Mimics 中尝试：

1. 导入 CT。
2. 导入逐器官 mask。
3. 修正一个器官。
4. 导出 mask。

记录每一步是否需要人工不可控操作。

### Step 3. Mimics 脚本化

只有 Step 2 证明 Mimics 能稳定导入导出后，再写 Mimics 内 Python 脚本。

### Step 4. nnUNet 小闭环

用导回的 `verified_label.nii.gz` 创建最小训练快照，只训练少量器官或少量 case，目标不是模型效果，而是验证数据路径。

---

## 5. 关键设计风险

| 风险 | 优先级 | 当前处理 |
|---|---|---|
| Mimics 导出 shape 不一致 | P0 | shape 不一致是硬故障；需切换导出方式或工具 |
| Mimics affine/origin/direction 不一致 | P1 | shape 一致时由 `check_geometry.py` 检测并修复几何头，再抽检 |
| 多标签与 Mimics 多 mask 映射复杂 | P0 | 统一用 `review_label_map.yaml` 和 mask name 映射 |
| 伪标签误入训练 | P0 | `label_policy.allow_status` 显式控制；状态和来源不改写 |
| Windows 与远程路径不同 | P1 | manifest 中只用相对路径 |
| 训练框架扩展过早 | P2 | 先只实现 nnUNet 小闭环 |
| 标注员负担过重 | P1 | 不做逐器官 checklist，只要求保存导出 |

---

## 6. 待用户确认

这些问题需要在真正开始 POC 前确认：

1. Mimics 当前可用版本和许可证类型是什么？是否能运行 Python 脚本？
2. 第一批 POC 病例在哪里？是否已有可公开给脚本处理的 3-5 个样例？
3. 第一阶段目标范围已按会议确定为 v500 现有 CT1-16、MR1-8 多模型组合；POC 可从其中挑 3-5 个病例验证闭环。
4. 训练服务器能否访问病例包输出目录？还是必须 zip 手动传输？
5. 哪些任务或来源应从默认伪标签准入中排除？

---

## 7. 下一步建议

下一步最值得做的是实现平台侧通用脚本的最小版本：

1. `split_multilabel_to_masks.py`
2. `merge_masks_to_multilabel.py`
3. `check_geometry.py`
4. `hash_package.py`

有了这四个脚本，就可以开始验证 Mimics 导入导出，而不需要等完整 Registry。
