# Mimics 适配器

> 状态：设计已收敛，等待 Mimics Research 21.0 本机验证后分阶段实现

本目录只保存必须在 Mimics 内置 Python 3.5.2 中运行的脚本、能力探针和标注员说明。平台侧的现代 Python 代码放在 `src/segplatform/adapters/mimics/`，不能混用两个运行环境的依赖。

完整设计见 [Mimics 适配器设计与开发流程](../../docs/domains/labeling/mimics_adapter_design.md)。

## 目标结构

```text
src/segplatform/adapters/mimics/
  doctor.py
  prepare.py
  launcher.py
  bridge.py
  finalize.py

adapters/mimics/
  runtime_py35/
    sp_common.py
    sp_diagnostics.py
    sp_open_review.py
    sp_submit_review.py
  probes/
    p01_dicom_grouping.py
    p02_image_set_binding.py
    p04_mask_buffer.py
    p05_geometry_roundtrip.py
    p06_selective_export.py
  README.md
  README_for_annotators.md
```

## 三类代码的边界

| 位置 | 运行环境 | 职责 |
| --- | --- | --- |
| `src/segplatform/adapters/mimics/` | 外部现代 Python | 病例包检查、医学格式读写、启动 Mimics、空间 QC、提交入库 |
| `adapters/mimics/runtime_py35/` | Mimics Python 3.5.2 | 调用 Mimics API、管理 image set 和 Mask、保存 `.mcs`、导出提交缓冲区 |
| `adapters/mimics/probes/` | Mimics Python 3.5.2 | 验证 API、轴顺序、空间往返和选择性导出，不作为生产入口 |

Mimics 内脚本不实现 Registry、标签生命周期、训练准入或医学格式长期存储。保存 `.mcs` 也不等于提交或验证标签。

## 开发顺序

1. 先实现 `doctor.py`、`sp_diagnostics.py` 和必要的 `probes/`，用于执行 [Mimics POC 计划](../../docs/domains/labeling/mimics_poc_plan.md)。
2. Gate A 通过后，才实现生产用 `prepare`、`open`、`submit` 和 `finalize` 流程。
3. 优先使用本机已证明稳定的 DICOM 图像导入路径。
4. 初始标签和提交结果必要时通过逐器官布尔缓冲区交换；不默认要求 Mimics 内安装 nibabel 或 SimpleITK。
5. 空间往返无法证明时停止该路径，使用 ITK-SNAP、3D Slicer 或其他 NIfTI 原生工具。

探针是 POC 的执行代码，不需要等待全部 POC 完成后才编写；生产脚本则必须受 Gate A、B、C 约束。

## Case Package 边界

适配器必须直接消费 Case Package v0.5：

- 从 `manifest.json.image_sets` 读取一个或多个平等图像集，不假设 primary/reference；
- 从 `labels/{image_id}/` 读取该图像的初始标签；
- 一个 `.mcs` 第一阶段只承载一个 `review_id`；
- 结果写入 `submissions/{review_id}/` 和 `reports/`；
- 调用 Mimics 前后运行病例包和空间检查；
- 不恢复旧版扁平 `labels/` 目录，也不根据当前 active image 猜测标签归属。

## 标注者入口

稳定后的预期入口是：

```bash
sp mimics prepare /path/to/case_package
sp mimics open /path/to/case_package
sp mimics finalize /path/to/case_package
```

标注者只需通过启动器打开任务、在 Mimics 中编辑和保存，并从 `Script -> Scripting Library` 运行 **SP - Submit Review**。路径、文件名、标签编号、格式转换和最终 QC 由平台处理。

## 不属于本目录

- 标签生命周期和人工审核政策；
- 训练数据准入；
- NIfTI/MHD 的通用读取器；
- Data Registry；
- 模型推理；
- Web Orchestrator 或任务队列。

标注流程见 [标注工作流](../../docs/domains/labeling/labeling_workflow.md)，版本特定 API 边界见 [Mimics 技术参考](../../docs/domains/labeling/mimics_reference.md)。
