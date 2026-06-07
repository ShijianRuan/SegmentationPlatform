# 事实核查记录

> 日期：2026-06-07  
> 用途：记录本轮文档重写时保留、修正或降级的关键事实。

## 1. 核查结论

| 主题 | 原文档风险 | 当前处理 |
| --- | --- | --- |
| nnUNet 标签编号 | 容易把统一器官名误解成统一训练 label id | 改为“统一器官名称 + 任务级 label map” |
| Mimics 版本 | 官方页面提到 Mimics Medical 28.0 和 3-matic Medical 20.0 released 2025；但本机是否可用、许可证是否覆盖、模块是否可用仍未验证 | 文档可写官方版本信息，但不能写成本项目已可直接使用 |
| Mimics API | 旧文档写了具体函数名和参数，公开来源不足 | 删除具体函数名，改为 POC 待验证 |
| Mimics NIfTI | 旧文档倾向认为 NIfTI 往返可直接依赖 | 改为最高风险项，要求几何校验 |
| Orchestrator | 旧蓝图过早写 FastAPI/Celery 等实现 | 改为后期调度层，不作为当前核心 |
| 伪标签 | 旧文档有时把伪标签和金标准混写 | 改为标签状态 + label policy |
| CADS 指标 | 具体 Dice 数字容易上下文错配 | 保留数据规模等来源清楚的事实，指标需查论文表格后再写 |
| Feishu 研究材料 | 论文条目多，未逐条核查时容易被误当成事实库 | 压缩为研究方向备忘，删除未核实的论文细节，进入主设计前必须回查原文 |
| `scripts/` 目录 | 旧脚本曾使用 `organ_config.yaml` 假设 | 已收敛为当前 Case Package 最小工具脚本，并与 `anatomy_vocabulary.yaml` / `review_label_map.yaml` 对齐 |

## 2. 使用来源

| 来源 | 支撑内容 |
| --- | --- |
| [nnU-Net dataset format](https://github.com/MIC-DKFZ/nnUNet/blob/master/documentation/dataset_format.md) | 背景 0、类别连续编号、图像和标签几何一致、dataset.json |
| [Materialise Mimics 2025 Product Update](https://www.materialise.com/en/healthcare/mimics/whats-new) | NIfTI/RT-DICOM、Python API 增强、AI-enabled segmentation |
| [Materialise Mimics Core](https://www.materialise.com/en/healthcare/mimics/mimics-core) | Mimics Core 定位、系统要求、Mimics Medical 28.0/3-matic Medical 20.0 信息 |
| [Materialise community affine issue](https://community.materialise.com/t/dicom-to-nifti-format-using-mimics-scripting-problem-with-affine-transformation-matrix/438) | Mimics scripting 导出 NIfTI 时 affine/orientation 风险 |
| [MONAI Label repository](https://github.com/project-monai/monailabel) | server-client、AI-assisted annotation 参考架构 |
| [TotalSegmentator repository](https://github.com/wasserth/totalsegmentator) | CT/MR 多结构分割、NIfTI/DICOM 输入、非医疗器械声明 |
| [CADS arXiv](https://arxiv.org/abs/2507.22953) | 22,022 CT、167 结构、公开框架、评估范围 |
| [CADS Hugging Face dataset](https://huggingface.co/datasets/mrmrx/CADS-dataset) | 数据集说明、访问条款、伪标签、质量控制描述、NIfTI 组织和更新记录 |

## 3. 后续仍需实测

1. Mimics 本机版本的导入导出能力。
2. Mimics 导出标签与原 CT 的几何一致性。
3. 当前 nnUNet Adapter 需要的最小导出目录是否完全覆盖现有训练脚本。
4. CADS 或 TotalSegmentator 输出映射到平台器官名称后的质量。
5. Feishu 研究材料中的论文年份、会议归属、指标和代码链接。
6. Mimics 和 nnUNet 的 adapter 目录目前已落地为骨架，但真正的平台级导入导出逻辑仍需后续实现。
