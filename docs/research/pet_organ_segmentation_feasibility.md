# 基于 PET 的器官分割技术可行性评估报告

> **生成日期**: 2026-06-16 | **来源文献数**: 25+ | **置信度**: 高
>
> **调研范围**: 脊椎、脑、肝脏、肾脏的 PET-based 器官分割深度学习研究

---

## 执行摘要

基于 PET 图像的器官分割是核医学影像分析中的新兴方向。**结论：技术上可行，但成熟度显著低于 CT/MRI-based 分割**。目前已有明确论文覆盖四个目标器官的分割任务，其中**脑部分割最为成熟（Dice 0.93–0.96），肝脏次之（Dice 0.87–0.92），肾脏居中（Dice 0.82–0.85），脊椎/骨骼分割最挑战（Dice ~0.76–0.82）**。

核心方法以 nnU-Net 为主流框架，2024–2025 年出现了专门的 CT-less PET 多器官分割方案（Salimi et al., 2025, *Clinical Nuclear Medicine*），代码已开源。最大挑战在于：(1) PET 空间分辨率低；(2) PET/CT 配准错位高发（约 65% 病例存在）；(3) 示踪剂特异性导致的模型泛化困难；(4) 缺乏大规模公开标注数据集。

**建议**：如果目标是开发 PET-only 器官分割产品，应从脑和肝这两个 Dice 最高的器官切入；如果目标是辅助 CT 分割，Pet-based pre-segmentation 已被证明能显著提升 CT 分割精度。

---

## 1. 各器官 PET 分割研究现状

### 1.1 脑 (Brain)

**结论：四器官中 PET 分割最成熟的器官，已有高质量论文发表。**

| 研究 | 方法 | 数据集 | Dice |
|------|------|--------|------|
| Salimi et al. (2025) — FDG PET-NC | nnU-Net V2 3D | 540 FDG PET/CT | **0.961 ± 0.027** |
| Salimi et al. (2025) — FDG PET-ASC | nnU-Net V2 3D | 540 FDG PET/CT | **~0.93–0.96** |
| Salimi et al. (2025) — 68Ga-PSMA PET-NC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.928 ± 0.046** |
| Salimi et al. (2025) — 68Ga-PSMA PET-ASC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.942 ± 0.042** |
| JNM (2023) — 18F-FET PET 脑肿瘤 | Deep Learning | 脑肿瘤患者 | 自动 MTV 评估可靠 |

**关键发现**：
- 脑是 PET 上最易分割的器官，因为 FDG 在大脑皮层有高生理性摄取，形成鲜明对比
- 跨示踪剂性能稳定（FDG 和 PSMA 均 > 0.93）
- 即使使用未校正 PET (PET-NC) 也能达到 0.961 Dice — 说明脑的解剖信息在 PET 上非常丰富
- **成熟度评估：高。可直接产品化。**

### 1.2 肝脏 (Liver)

**结论：已有明确论文，PET 分割性能良好，但略低于 CT-based 分割。**

| 研究 | 方法 | 数据集 | Dice |
|------|------|--------|------|
| Salimi et al. (2025) — FDG PET-NC | nnU-Net V2 3D | 540 FDG PET/CT | **0.915 ± 0.049** |
| Salimi et al. (2025) — 68Ga-PSMA PET-ASC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.904 ± 0.062** |
| Salimi et al. (2025) — 68Ga-PSMA PET-NC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.867 ± 0.075** |
| Suganuma et al. (2023) — PET+LDCT Hybrid | U-Net/DenseUNet + ImageNet Pretrain | PET/CT | **0.941** |
| Banook (industry) — PET/CT 肝转移 | Deep Learning | PET/CT | Dice 0.95 (CT-based liver) |

**关键发现**：
- 肝脏在 FDG PET 上有中等生理性摄取，边界相对清晰
- PET-ASC（衰减校正后）模型显著优于 PET-NC（Mann-Whitney P < 0.001）
- 呼吸运动导致的 PET/CT 错位是肝脏分割的主要挑战（肝-肺/肝-脾交界处）
- Suganuma 等人用 PET+LDCT 混合方法达到 0.941 Dice，说明多模态是提升方向
- **成熟度评估：中高。需注意呼吸运动伪影处理。**

### 1.3 肾脏 (Kidney)

**结论：已有明确论文，PET 分割可行但挑战较大，PET 作为辅助信息价值高。**

| 研究 | 方法 | 数据集 | Dice |
|------|------|--------|------|
| Salimi et al. (2025) — FDG PET-NC | nnU-Net V2 3D | 540 FDG PET/CT | **0.851 ± 0.077** |
| Salimi et al. (2025) — 68Ga-PSMA PET-ASC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.819 ± 0.120** |
| Salimi et al. (2025) — 68Ga-PSMA PET-NC | nnU-Net V2 3D | 185 PSMA PET/CT | **0.824 ± 0.109** |
| Leube et al. (2023) — PSMA-PET + CT | U-Net with PET pre-seg mask | 108 PSMA PET/CT | PET 辅助显著提升 CT 分割 |
| Suganuma et al. (2023) — PET+LDCT Hybrid | U-Net/DenseUNet | PET/CT | **0.939** |
| Klyuzhin et al. (2024) — PSMA-HORNET | Multi-target UNET | PSMA PET/CT | 多器官同时分割 |

**关键发现**：
- 肾脏在 PSMA PET 上有一定生理性摄取（PSMA 经肾脏排泄），FDG 摄取较低
- PSMA-PET 在肾脏分割中方差较大（±0.120），可能与肾囊肿、肾积水等病理状态有关
- **Leube et al. (2023) 的重要结论：PET-based pre-segmentation 能显著提升肾脏 CT 分割效果，在 80% 的病例中核医学医师更偏好 PET 辅助的分割结果**
- 肾脏与脾脏、肝脏、胰腺的边界模糊是主要挑战
- **成熟度评估：中。PET-only 分割有可行性但精度波动大；PET 辅助 CT 分割是更稳健的策略。**

### 1.4 脊椎 (Spine/Vertebra/Bone)

**结论：已有论文但相对较少，是四器官中最具挑战性的任务。**

| 研究 | 方法 | 数据集 | Dice |
|------|------|--------|------|
| Salimi et al. (2025) — FDG PET-NC | nnU-Net V2 3D | 540 FDG PET/CT | **约 0.76**（vertebrae） |
| Salimi et al. (2025) — FDG PET-ASC | nnU-Net V2 3D | 540 FDG PET/CT | 优于 PET-NC（P=0.001） |
| Bao et al. (2024) — CT-Less Whole-Body Bone | **MMF-Net** (多模态融合) | 130 WB PET | 中高精度（骨骼整体） |
| Malekzadeh et al. (2026) — FLT-PET Bone/Marrow | DL 多器官验证 | AML/HCT 患者 | 骨骼+骨髓分割 |

**关键发现**：
- 骨骼在 PET 上的生理性摄取低（FDG 正常情况下骨髓摄取不高），导致边界信息不足
- **Bao et al. (2024) 是专门针对 CT-less PET 骨骼分割的工作**，提出了 MMF-Net，利用 λ-MLAA（示踪剂活动图）、μ-MLAA（衰减图）和合成衰减图三种模态信息
- 椎体分割效果弱于大器官，属于 Salimi 论文中 Dice 偏低的器官组
- CT-based 脊椎分割早已非常成熟（VerSe 挑战赛 Dice > 0.89），PET-based 与之差距明显
- **成熟度评估：中低。PET-only 骨骼/椎体分割是最难的子任务，建议优先使用 CT 或多模态方案。**

---

## 2. 核心技术方法总结

### 2.1 主流架构

| 方法类别 | 代表性工作 | 特点 |
|----------|-----------|------|
| **nnU-Net（自配置）** | Salimi et al. (2025), Clement et al. (2024) | 当前 PET 器官分割的 SOTA 框架，无需手动调参 |
| **U-Net 变体 + 预训练** | Suganuma et al. (2023) | ImageNet/RadImageNet 预训练提升 LDCT+PET 混合分割 |
| **多模态融合网络** | Bao et al. (2024) MMF-Net | 多编码器结构，融合 PET 多种重建模态 |
| **Swin UNETR + 自监督** | Yazdani et al. (2024) | Transformer-based，自监督预训练 |
| **Vision-Language Model** | Duan et al. (2025) | 最新方向，用 VLM 辅助 PET 器官分割 |
| **混合 PET+CT** | Klyuzhin et al. (2024) PSMA-HORNET | PET 和 CT 双输入，性能最优但依赖 CT |

### 2.2 输入模态选择

Salimi et al. (2025) 系统比较了不同输入模态：

| 输入模态 | 优点 | 缺点 | 适用场景 |
|----------|------|------|----------|
| **PET-ASC** (衰减散射校正) | 对比度好，信息丰富，Dice 最高 | CT 错位时产生伪影 (halo artifact) | CT 配准良好时首选 |
| **PET-NC** (未校正) | 不受 CT 错位影响，无伪影 | 图像质量差，Dice 略低 | CT 不可靠/不可用时 |
| **PET + CT 混合** | 性能最优 | 依赖 CT，受错位影响 | 常规 PET/CT 检查 |

### 2.3 训练策略

- **标注迁移**：先用 CT 训练高精度分割模型 → 将 mask 重采样到 PET 空间 → 作为 PET 模型训练的伪标签（Salimi 的核心策略）
- **5 折交叉验证 + 集成**：nnU-Net 默认配置，所有 fold 集成后推理
- **数据清洗**：关键步骤 — Salimi 团队排除了约 65% 的 PET/CT 错位病例，仅用 540/1487 FDG 和 185/575 PSMA 干净数据训练

---

## 3. 数据可用性评估

### 3.1 公开数据集

| 数据集/挑战赛 | 模态 | 规模 | 标注类型 | 器官覆盖 |
|-------------|------|------|----------|----------|
| **AutoPET I/II/III** (2022–2025) | FDG-PET/CT + PSMA-PET/CT | 1014→1614 例 | **病灶分割** | 全身肿瘤病灶，非器官 |
| **HECKTOR** (2021–2022) | FDG-PET/CT | ~300 例 | 头颈部肿瘤 + 器官 | 头颈部 GTV |
| **TotalSegmentator (CT)** | CT | ~1200 例 | 104 个解剖结构 | 全身多器官 |
| **LiTS** | CT | 201 例 | 肝脏 + 肿瘤 | 肝脏 |
| **KiTS** | CT | 300 例 | 肾脏 + 肿瘤 | 肾脏 |
| **VerSe** | CT | ~300 例 | 椎体分割+标注 | 脊椎 |

**⚠️ 关键缺口**：**目前没有专门针对 PET 图像的大规模公开多器官分割数据集**。现有 PET 公开数据集（AutoPET、HECKTOR）均以病灶分割为目标而非器官分割。Salimi 等研究均依赖自建数据集，数据未公开，但模型权重已开源（[GitHub: YazdanSalimi/Organ-Segmentation](https://github.com/YazdanSalimi/Organ-Segmentation)）。

### 3.2 标注获取策略

当前主流方案是 **CT 伪标签迁移**：
1. 用公开 CT 器官分割模型（如 TotalSegmentator）在 CT 组件上生成高质量标注
2. 将标注重采样到 PET 空间
3. 人工/自动排除 PET/CT 错位病例
4. 用迁移后的标注训练 PET-only 模型

这意味着如果拥有 PET/CT 配准数据，可以较低成本构建 PET 器官分割训练集。

---

## 4. 与 CT/MRI-based 分割的对比

| 维度 | CT-based | MRI-based | PET-only | PET/CT Hybrid |
|------|----------|-----------|----------|---------------|
| **技术成熟度** | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐ | ⭐⭐⭐⭐ |
| **肝脏 Dice (典型)** | 0.95–0.98 | 0.93–0.96 | 0.87–0.92 | 0.94–0.96 |
| **肾脏 Dice (典型)** | 0.93–0.96 | 0.90–0.94 | 0.82–0.85 | 0.93–0.94 |
| **脑 Dice (典型)** | 0.95–0.98 | 0.95–0.98 | 0.93–0.96 | 0.96–0.98 |
| **椎体 Dice (典型)** | 0.89–0.93 | 0.85–0.90 | ~0.76–0.82 | 0.90+ |
| **空间分辨率** | 高 (0.5–1mm) | 高 (0.5–1mm) | 低 (2–4mm) | — |
| **解剖信息** | 丰富 | 丰富 | 有限 | 丰富 |
| **功能信息** | 无 | 有限 | 丰富（代谢） | 丰富 |
| **辐射暴露** | 有 | 无 | 有 | 有 |
| **公开数据集** | 丰富 | 中等 | 稀缺 | 稀缺 |
| **配准问题** | N/A | 运动伪影 | 无（PET-only） | PET/CT 错位高发 |
| **示踪剂依赖性** | 无 | 无 | **强依赖** | 中 |

### 关键结论

1. **PET-only 器官分割的 Dice 普遍比 CT-based 低 5–15 个百分点**，这主要源于 PET 的低空间分辨率和有限的解剖信息
2. **在 PET 不可替代的场景下（PET-only 扫描仪、CT-less 衰减校正、动态 PET 运动追踪），PET-only 分割具有独特价值**
3. **混合 PET+CT 方法在精度上最接近纯 CT 方法**，但受限于 PET/CT 配准质量
4. PET 的独特优势：提供代谢/功能信息，可用于器官功能定量分析，这是 CT/MRI 无法替代的

---

## 5. 技术挑战与难点

### 5.1 高优先级挑战

| 挑战 | 严重程度 | 描述 | 缓解策略 |
|------|---------|------|----------|
| **PET/CT 配准错位** | 🔴 极高 | Salimi 研究中 65% 病例因错位被排除；呼吸运动导致肝/肺/脾边界错位 | PET-only 方法；动态 PET 帧间配准；数据清洗 |
| **低空间分辨率** | 🔴 高 | PET 体素间距 1.6–4mm，CT 为 0.5–1.5mm；下采样时细小结构（肋骨、肾上腺）丢失 | 2mm dilation 补偿；超分辨率预处理 |
| **示踪剂特异性** | 🟡 中高 | FDG、PSMA、DOTATATE 等器官摄取模式完全不同，模型无法跨示踪剂泛化 | 每个示踪剂单独训练；迁移学习；多示踪剂联合训练 |
| **小器官分割差** | 🟡 中高 | 肾上腺 Dice 仅 0.42–0.57，胰腺 0.60–0.68 | 器官特定模型；注意力机制；后处理约束 |

### 5.2 中低优先级挑战

| 挑战 | 严重程度 | 描述 |
|------|---------|------|
| **病理状态影响** | 🟡 中 | 肾囊肿、肝脂肪变性等改变器官 PET 摄取和形态 |
| **动态 PET 噪声** | 🟡 中 | 动态 PET 早期帧信噪比极低，但 Salimi 模型表现出鲁棒性 |
| **多中心泛化** | 🟡 中 | 不同扫描仪、重建算法导致域偏移，需联邦学习或微调 |
| **膀胱/肠道运动** | 🟢 中低 | 膀胱充盈和肠道蠕动导致的形态变化 |

---

## 6. 技术可行性总体评估

### 6.1 各器官可行性矩阵

| 器官 | 论文覆盖 | 技术成熟度 | PET-only Dice | 公开数据 | 产品化建议 |
|------|---------|-----------|--------------|----------|-----------|
| **脑** | ✅ 充分 | ⭐⭐⭐⭐ 高 | 0.93–0.96 | 中等 | **一线开发目标**，最易产品化 |
| **肝脏** | ✅ 充分 | ⭐⭐⭐½ 中高 | 0.87–0.92 | 中等 | **一线开发目标**，需处理呼吸运动 |
| **肾脏** | ✅ 有 | ⭐⭐⭐ 中 | 0.82–0.85 | 中等 | **二线目标**，推荐 PET 辅助 CT 策略 |
| **脊椎/骨骼** | ✅ 有（少） | ⭐⭐½ 中低 | ~0.76–0.82 | 有限 | **三线目标**，建议依赖 CT 或多模态 |

### 6.2 推荐的开发路线

```
Phase 1 (快速验证):  脑分割 → 利用 TotalSegmentator CT 伪标签 + 自建 PET/CT 数据
Phase 2 (核心能力):  肝分割 → 加入呼吸运动处理模块
Phase 3 (扩展):      肾分割 → 引入 PSMA-PET 数据，验证 PET 辅助 CT 策略
Phase 4 (研究探索):  椎体/骨骼分割 → 需专门方法（如 MMF-Net），ROI 优先较低
```

### 6.3 开源资源

- **模型代码**: [github.com/YazdanSalimi/Organ-Segmentation](https://github.com/YazdanSalimi/Organ-Segmentation) — Salimi 团队的 PET 多器官分割预训练模型（nnU-Net）
- **CT 伪标签工具**: [TotalSegmentator](https://github.com/wasserth/TotalSegmentator) — 104 结构 CT 分割
- **nnU-Net V2**: [github.com/MIC-DKFZ/nnUNet](https://github.com/MIC-DKFZ/nnUNet) — 自配置分割框架
- **AutoPET 数据**: 公开可获取，但面向病灶分割

---

## 7. 核心参考文献

1. **Salimi Y, Mansouri Z, Shiri I, et al.** "Deep Learning–Powered CT-Less Multitracer Organ Segmentation From PET Images." *Clinical Nuclear Medicine*, 2025. DOI: [10.1097/RLU.0000000000005685](https://doi.org/10.1097/RLU.0000000000005685) ⭐ **核心文献**

2. **Bao N, Zhang J, Li Z, et al.** "CT-Less Whole-Body Bone Segmentation of PET Images Using a Multimodal Deep Learning Network." *IEEE JBHI*, 2024. DOI: [10.1109/JBHI.2024.3501386](https://doi.org/10.1109/JBHI.2024.3501386) — 骨骼专项

3. **Leube J, Horn M, Hartrampf P, et al.** "PSMA-PET Improves Deep Learning-Based Automated CT Kidney Segmentation." *Zeitschrift für Medizinische Physik*, 2023. DOI: [10.1016/j.zemedi.2023.08.006](https://doi.org/10.1016/j.zemedi.2023.08.006) — 肾脏专项

4. **Suganuma Y, Teramoto A, Saito K, et al.** "Hybrid Multiple-Organ Segmentation Method Using Multiple U-Nets in PET/CT Images." *Applied Sciences*, 2023. DOI: [10.3390/app131910765](https://doi.org/10.3390/app131910765)

5. **Klyuzhin IS, Chaussé G, Bloise I, et al.** "PSMA-HORNET: Fully-Automated, Multi-Target Segmentation of Healthy Organs in PSMA PET/CT Images." *Medical Physics*, 2024. DOI: [10.1002/mp.16894](https://doi.org/10.1002/mp.16894)

6. **Yazdani E, Karamzadeh-Ziarati N, Cheshmi SS, et al.** "Automated Segmentation of Lesions and Organs at Risk on [68Ga]Ga-PSMA-11 PET/CT Images Using Self-Supervised Learning with Swin UNETR." *Cancer Imaging*, 2024. DOI: [10.1186/s40644-024-00675-x](https://doi.org/10.1186/s40644-024-00675-x)

7. **Liu X, Qu L, Xie Z, et al.** "Towards More Precise Automatic Analysis: A Systematic Review of Deep Learning-Based Multi-Organ Segmentation." *BioMedical Engineering OnLine*, 2024. DOI: [10.1186/s12938-024-01238-8](https://doi.org/10.1186/s12938-024-01238-8) — 综述

8. **Gatidis S, Früh M, Fabritius M, et al.** "Results from the AutoPET Challenge on Fully Automated Lesion Segmentation in Oncologic PET/CT Imaging." *Nature Machine Intelligence*, 2024. DOI: [10.1038/s42256-024-00912-9](https://doi.org/10.1038/s42256-024-00912-9)

9. **Clement C, Xue S, Zhou X, et al.** "Multi-Organ Segmentation on CT-Free Total-Body Dynamic PET Scans." *Journal of Nuclear Medicine*, 2024.

10. **Duan C, Krokos G, Reader A, et al.** "Vision-Language Model Assistance for Improved PET Organ Segmentation." *IEEE NSS/MIC/RTSD*, 2025. DOI: [10.1109/NSS/MIC/RTSD57106.2025.11286341](https://doi.org/10.1109/NSS/MIC/RTSD57106.2025.11286341)

11. **Rokuss M, Kovacs B, Kirchhoff Y, et al.** "From FDG to PSMA: A Hitchhiker's Guide to Multitracer, Multicenter Lesion Segmentation in PET/CT Imaging." *arXiv*, 2024. [arXiv:2409.09478](https://arxiv.org/abs/2409.09478)

12. **Wang X, Jemaa S, Fredrickson J, et al.** "Heart and Bladder Detection and Segmentation on FDG PET/CT by Deep Learning." *BMC Medical Imaging*, 2022.

---

## 研究方法说明

本报告通过以下方式完成：
- **搜索工具**: Semantic Scholar（学术论文）、Firecrawl（网页搜索）
- **搜索查询数**: 10+ 个关键词组合
- **深度阅读论文数**: 6 篇全文，15+ 篇摘要
- **覆盖时间范围**: 2020–2026，重点 2023–2025
- **子问题覆盖**: 脊椎、脑、肝脏、肾脏四个目标器官 + 数据集/挑战赛 + 方法综述
