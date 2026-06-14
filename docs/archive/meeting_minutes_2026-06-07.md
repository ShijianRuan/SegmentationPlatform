# 分割平台架构设计汇报 — 会议纪要

> 日期：2026-06-07
> 参会人：领导（提问方）、架构师 ShijianRuan（汇报方）
> 主题：医学图像分割平台架构设计全面介绍
>
> 历史口径说明：本文保留会议原话。现行蓝图已取消 `accepted_pseudo_label` 底层状态；相关表述应理解为“保持 `candidate_label`，由 Dataset Snapshot 记录准入结果”。本文中的“人修正保存即 verified”、新版 Mimics NIfTI 能力和早期单人一次性工作流也已被 2026-06-12 的 `labeling_workflow.md` 与 Mimics 21 技术参考取代。

---

## 第一轮：开场与全局概览

**架构师**：平台的根本目标是**全身器官分割**。核心认识：训练任务不必一开始就是「一个模型分割全身所有器官」。真实数据有不同扫描区域、不同模态、不同标注完整度，因此平台要允许同一批病例被组织成多个训练任务。

平台中心不是 nnUNet，也不是 Mimics，而是**病例、图像、标签、训练任务和模型版本之间的关系**。

---

## 第二轮：三大实现域的划分

**领导提问**：为什么一定是这三个域？各自的职责需要再明晰。

**架构师回答**：三个域按「三种不同责任」划分。

如果在一条 pipeline 里混在一起会导致严重混乱：标签到底是谁标的说不清、训练编号混淆、候选标签悄悄混入训练集无法审计。

| 域名 | 职责 | 核心对象 | 明确不管什么 |
|------|------|---------|------------|
| **labeling** | 标签怎么生产并安全导回 | Case Package、Mimics、`verified_label` | 器官在训练任务里是几号 |
| **training** | 任务怎么消费标签并产出模型 | TaskLabelMap、Dataset Snapshot、nnUNet Adapter、Model Record | 标签是人标的还是伪标签 |
| **label_generation** | 候选标签生成、筛选、回流治理 | `candidate_label`、`accepted_pseudo_label`、离线推理 | 人怎么修正、标签怎么变训练数据 |

第三个域不叫 `pseudo_labeling`，因为它不只是生成伪标签，还负责完整的治理和回流。

---

## 第三轮：QC 和标签状态设计

**领导提问**：QC 是什么意思？candidate_label 和 draft_label 怎么区分？这些状态设计都合理吗？

**架构师回答**：

**QC（Quality Control，质量控制）** = 自动检查规则，分三个层面：

| 层面 | 检查内容 | 不通过的后果 |
|------|---------|------------|
| 空间/几何 QC | 文件可读、shape 一致、spacing/origin/direction/affine 对齐、标签值合法 | 直接拒绝 |
| 标签内容 QC | 空标签、越界、器官覆盖 | 标记但不一定拒绝 |
| 准入策略 QC | 标签状态是否允许进入训练 | 由任务策略决定 |

**candidate_label vs draft_label**：

- **candidate_label**：模型/公开算法刚跑完的原始结果，未经任何处理。毛坯房。
- **draft_label**：专门准备好给人修正的起点。已拆分、已映射、已配颜色。端到服务员面前的菜。

六种标签状态：

```
外部数据集标签 → source_label → verified_label（可信源，直接确认）
模型/算法输出 → candidate_label → draft_label → 人修正保存 → verified_label
                   │
                   ├→（QC通过）→ accepted_pseudo_label
                   │                   ↑
                   │            可选：人工抽检后升级
                   └→（QC失败）→ rejected_label
```

**表示方式**：Case Package 文件系统命名 + provenance JSON 来源追溯，两套机制互补。

**candidate_label 能否直接进训练？** 默认建议不放进，但 `allow_status` 可以做任意标签状态。如果你信任某个算法（如 TotalSegmentator 的肝脏输出），完全可以在 `label_policy` 中把 `candidate_label` 加进 `allow_status`，同时用 `trusted_sources` 限定来源。核心原则是 **provenance 永远保留真实状态，不在标签状态上造假**。决定最终被写入蓝图 §7 的标签状态表。

---

## 第四轮：三种 Label Map 的设计

**领导提问**：三个 Label Map（anatomy_vocabulary / review_label_map / task_label_maps）真的合理且必要吗？

**架构师回答**：用反证法证明——尝试合并。

- **合并 anatomy + review**：换标注工具就要改器官名称表，而器官名称应是稳定的全平台引用。
- **合并 review + task**：同一个 liver 在不同任务里编号不同（CT5_Liver=2, CT_All_Coarse=5, Mimics=10, CT_Combine=37），没有一个能当唯一编号。

三层各司其职：

| 层 | 回答什么问题 | 约束来源 |
|----|------------|---------|
| anatomy_vocabulary | 这是什么器官？ | 纯语义，零数字 |
| review_label_map | 工具里是几号？ | 标注软件限制 |
| task_label_maps | 训练时是几号？ | nnUNet 要求连续整数编号 |

**领导确认**：说明清楚了。

---

## 第五轮：Case Package 契约

**架构师按「数据怎么来→怎么组织→怎么训练→怎么回流」顺序汇报。**

Case Package 是标注工具和平台之间的离线文件交换标准格式。一个病例一个包，自包含、可搬运。

核心目录结构：`manifest.json`（包身份 + 图像元数据 + SHA-256 hash）、`images/`、`labels/`（含逐状态文件 + `masks/` 逐器官目录）、`config/`（三种 YAML 配置）、`reports/`、`provenance/`。

**领导提问**：共用配置（anatomy_vocabulary.yaml 等）是每个包存一份还是集中管理？

**架构师回答**：
- **文件包阶段**：每个包复制一份，自包含。manifest 记录 hash，导回时校验防篡改。
- **平台注册层（后期）**：集中存储一份，病例只存引用。导出时按需打包。

`task_label_maps.yaml` 归属 Dataset Snapshot 层，不进 Case Package。

**此结论已写入 `case_package_contract.md` §10。**

---

## 第六轮：nnUNet 五阶段训练管线

现有训练代码在 `pipelines/nnunet/`，由一个 Framework 编排五个 Action：

| Action | 职责 | 关键细节 |
|--------|------|---------|
| **Action1** | 标注数据 → nnUNet 格式 | 数据集划分、重采样（图像三线性/mask 最近邻）、方位重定向（无插值）、多器官合并为单文件 |
| **Action2** | 指纹提取 + 实验规划 + 预处理 | **扩展**：允许手动覆盖 spacing/patch_size/batch_size，自动重算网络拓扑 |
| **Action3** | 训练 | GPU 管理、延迟导入、多线程控制 |
| **Action4** | 推理 | 四种模式：标准/简化/预插值加速/多模型共享分辨率（模拟 C++ 部署） |
| **Action5** | 评估 | Dice + Surface Dice、多格式报告、多模型聚合 |

**ModelMap.toml** 已经是 TaskLabelMap 的雏形：每个模型内部从 1 开始编号，CT_Combine/MR_Combine 只用于拼接展示。支持扁平格式（细粒度）和分组格式（粗分割）。

---

## 第七轮：标签生成域 — 闭环引擎

公开算法输出 → candidate_label → 名称映射 + 空间校验 + 质量筛选 → 三个出口：
- `draft_label`（送人工修正）
- `accepted_pseudo_label`（策略准入）
- `rejected_label`（丢弃）

**领导决策**：移除许可检查——这不是本域职责。

闭环全景：

```
无标签病例 → TotalSegmentator → candidate_label
  → draft_label → Case Package → Mimics → verified_label
  → Data Registry → Dataset Snapshot → nnUNet Adapter → 训练 → Model v1
  → 批量推理 → candidate_label → QC → 回流
```

---

## 第八轮：Mimics POC 风险评估

**M5（空间一致性）深度讨论**：

领导认为 mask 的 spacing/affine 不是必须的。架构师确认：模型学的不是元数据，但 nnUNet 预处理做 resample 时依赖 affine 定位体素物理坐标。Mask affine 错 → 重采样后标签错位。

| 不一致项 | 能否修复 | 判定 |
|----------|:--:|------|
| shape | ❌ 不可修复 | 硬故障 |
| spacing/affine/origin | ✅ `check_geometry.py` 可把图像 affine 抄到 mask | 可自动修复 |

**M5 底线重新定义为 shape 必须一致。**

**Mimics 调研**（Web 搜索 Materialise 社区 + 官方页面）：

确定的事实：
- `mimics.data.masks` 支持 `find()`、`get_voxel_buffer()`、`set_voxel_buffer()`
- 2025 版原生支持 NIfTI 导入导出
- **Scripting Guide 内置于 Mimics（Help > Scripting Guide），含完整 API 文档**
- Demo Scripts 随安装提供

不确定的风险（需本机实测）：
- R1：`set_voxel_buffer` 写入的数组是否与 CT 空间对齐
- R4：完整闭环能否无 GUI 干预

**结论**：没有现成的开源 Mimics + AI 管线集成方案，需自己写 Adapter 脚本。但 API 确定存在，Scripting Guide 在手，不是黑盒。

---

## 第九轮：少样本学习的架构定位

**领导认可**：少样本学习 = training 域新 Adapter，与 nnUNet Adapter 平级。

生产级引入路径不是选一个算法，而是**先建立可复现的实验协议**：

1. 选定器官 → 选出 verified 病例 → 患者级别冻结划分
2. N-shot Snapshot（N=1,3,5,10,20）
3. 三个对照组：nnUNet 全监督（上界）/ nnUNet 同数据量（基线）/ 预训练+微调（实验组）
4. 准入标准：至少 3 次独立复现、Dice ≥ 全监督 90%、跨扫描协议差距 ≤0.05、失败率 <5%

**当时写入三个文档**：`docs/domains/training/README.md` §3、`docs/architecture/platform_blueprint.md` §8.4、原 `docs/research/digests/few_shot_learning_digest.md` §4。该摘要后来已并入 `docs/research/few_shot_learning_survey.md` 并删除。

---

## 第十轮：三域联动与扩展性验证

**领导提问**：三个域能否真正联动？引入新算法/框架是否需要从头调整？

**架构师用两个压力测试验证**：

**测试 1（端到端）**：一个无标签腹部 CT → TotalSegmentator 生成 candidate → Case Package → Mimics 修正 → verified → Dataset Snapshot → nnUNet 训练 → 模型 → 批量推理新病例 → candidate → 循环。三域联动成立，每一步有状态转换。

**测试 2（新框架接入）**：换 MONAI、加 SAM 标注、导入新数据集——只影响对应域的 Adapter，不动其他域。因为架构把「不变的」固定在数据契约层（Case / Label Artifact / Snapshot / label_policy），把「会变的」封装在 Adapter 层。

---

## 第十一轮：待决策问题逐项确认

| # | 问题 | 领导决定 |
|:--:|------|---------|
| 1 | 伪标签准入 | **默认允许进入训练**，取决于器官/任务/模型。默认允许 + 特定排除 |
| 2 | 正式评估 | **考虑太早**，以后再说 |
| 3 | 第一阶段器官 | **v500 所有模型**（CT1-16、MR1-8），全身多处器官 |
| 4 | 全身模型方案 | **保持现状**，多模型组合 |
| 5 | Mimics POC | 先了解使用和集成方案，**做好调研准备后再启动** |
| 6 | 数据传输 | 可手动挪，不是问题 |
| 7 | 数据量 | 大量数据可用，不构成瓶颈 |

**蓝图 §12 已更新为「已决定」和「仍待讨论」两部分。**

---

## 第十二轮：架构实现前的遗留项

自查发现三个层面还停留在设计层：

| 遗留项 | 当前状态 | 影响 |
|--------|---------|------|
| Data Registry + Dataset Snapshot | 纯设计，代码里不存在 | 无法保证训练可复现、无法让同一套数据服务多个任务 |
| Adapter 最小接口 | 未定义 | 新 Adapter 接入缺乏约束 |
| label_policy 代码化 | YAML 示例，无执行代码 | 当前 Action1 不校验标签状态，`candidate_label` 放进去也不会被拦 |

**领导决定**：C1/C2 先不实现但要记住；C3 先不做只做设计构思；C4 可以故意把 `candidate_label` 放入训练——如果信任某个算法的输出，`allow_status` 就支持这样做。**核心是不在 provenance 上造假。**

---

## 第十三轮：实现前待确认清单

### 阻塞项（必须确认才能开始）

| # | 事项 | 现在状态 |
|:--:|------|:--:|
| A1 | Mimics 版本 + 许可证类型 | ❓ |
| A2 | Scripting Guide 中 mask 相关 API 清单 | ❓ 需在 Mimics Help 中查看 |
| A3 | Mimics 能否运行 Python 脚本 | ❓ |
| A4 | 第一批 3-5 个病例 | ❓ 领导说数据不是瓶颈 |
| A5 | 训练服务器环境（GPU、路径）| ❓ |

### 非阻塞项（设计已定，可立即实现）

| # | 模块 | 用途 |
|:--:|------|------|
| B1 | `scripts/split_multilabel_to_masks.py` | 多标签 NIfTI → 逐器官二值 mask |
| B2 | `scripts/merge_masks_to_multilabel.py` | 逐器官 mask → 多标签 NIfTI |
| B3 | `scripts/check_geometry.py` | shape/spacing/affine 校验 + 自动修复 |
| B4 | `scripts/package_case.py` | 生成 Case Package |
| B5 | `adapters/mimics/import_case_package.py` | 读 masks → numpy → set_voxel_buffer |
| B6 | `adapters/mimics/export_review_package.py` | get_voxel_buffer → numpy → masks |
| B7 | `config/anatomy_vocabulary.yaml` | 基于 ModelMap.toml 提取 |

### 后置项（不阻塞闭环）

| # | 模块 | 原因 |
|:--:|------|------|
| C1 | Data Registry | 手动闭环跑通后再代码化 |
| C2 | Dataset Snapshot | 同上 |
| C3 | Adapter 接口契约 | 只做设计构思 |
| C4 | label_policy 执行 | 同上 |
| C5 | FewShot Adapter | 生产级验证后再实现 |

---

## 第十四轮：时间估算

| 模块 | 工时 | 信心 |
|------|:--:|:--:|
| 平台脚本（B1-B4）| 4-5 天 | 高 |
| Mimics Adapter（B5-B6）| 乐观 2 天，悲观 2 周 | 中低，依赖 A1-A3 |
| 闭环测试 + 调试 | 1-2 周 | — |
| 3-5 病例验证 | 1 周 | — |
| **一切顺利** | **3-4 周** | 中 |
| **正常（1-2 个弯路）** | **5-6 周** | 中 |
| **Mimics API 受限** | 加 2-3 周转 3D Slicer | 中低 |

最大减速带不是代码量，是 Mimics 确认和几何对齐调试。

---

## 附录：本次会议同步更新的设计文档

| 文档 | 更新内容 |
|------|---------|
| `docs/architecture/platform_blueprint.md` | label_policy 默认允许 + 排除；少样本 Adapter 定位；待决策问题分已决定/待讨论 |
| `docs/domains/training/README.md` | Adapter 并行架构图；FewShot 平行定位 |
| `docs/domains/labeling/case_package_contract.md` | 共用配置改为集中存储+引用（dataset_package/config/）；task_label_maps 归属 Snapshot |
| `docs/domains/labeling/mimics_feasibility.md` | 新增 §10 Web 调研：affine 问题证实、M5 底线重定义、Scripting Guide 存在 |
| `docs/domains/label_generation/cads_reference.md` | 移除许可裁决相关条目 |
| 原 `docs/research/digests/few_shot_learning_digest.md` | 新增 §4 平台架构落点；内容后来并入综合综述并删除 |

---

### 2026-06-08 补充审读

**架构师审读领导更新后的文档，逐项确认：**

1. 新增 ADR-012~015 — 全部确认
2. QC 三层递进模型（§7.1）— 空间→内容→准入，确认
3. Case Package 共用配置 — 改为 dataset_package/config/ 集中共享 + manifest config_ref 引用
4. Case Package 不再携带 task_label_maps.yaml — 归属 Dataset Snapshot 层，确认
5. 实施计划修正：
   - M3 开始日 07-13 → 07-20（等 M2 完成）
   - M1 增加 3D Slicer 并行最小验证
   - 命令清单加阶段标注
6. backlog 补齐 label_generation 脚本条目（G2/G3）
