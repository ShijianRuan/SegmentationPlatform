# Mimics 适配器

> 状态：外部适配器、Python 3.5 正式脚本和关键探针已实现；等待 Mimics Research 21.0 本机 Gate A/B/C 验收

本目录只保存必须在 Mimics 内置 Python 3.5.2 中运行的脚本、能力探针和标注员说明。平台侧的现代 Python 代码放在 `src/segplatform/adapters/mimics/`，不能混用两个运行环境的依赖。

完整设计见 [Mimics 适配器设计与开发流程](../../docs/domains/labeling/mimics_adapter_design.md)。在独立 Windows 工作站安装和操作时，直接按 [Mimics Research 21 Windows 工作站操作手册](../../docs/domains/labeling/mimics_windows_runbook.md) 执行。

## 目标结构

```text
src/segplatform/adapters/mimics/
  doctor.py
  prepare.py
  launcher.py
  bridge.py
  probes.py
  finalize.py

adapters/mimics/
  scripting_library/
    Labeling_Open_Next_Case.py
    Labeling_Case_Navigation.py
    Labeling_Submit_Complete.py
    Labeling_Submit_or_Report_Issue.py
    Labeling_View_Task_List.py
    Labeling_Save_Recovery_Backup.py
  runtime_py35/
    sp_review_console.py
    sp_common.py
    sp_diagnostics.py
    sp_open_review.py
    sp_save_checkpoint.py
    sp_submit_review.py
  probes/
    sp_probe_suite.py
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
| `adapters/mimics/scripting_library/` | Mimics Scripting Library | 放置语义明确的 `Labeling_*.py` 标注入口和独立工具入口 `nnInteractive.py` |
| `adapters/mimics/runtime_py35/` | Mimics Python 3.5.2 | 调用 Mimics API；平台脚本和独立工具在运行时不互相依赖 |
| `adapters/mimics/probes/` | Mimics Python 3.5.2 | 单次会话验证 API、图像绑定、轴顺序、空间往返和选择性导出 |

Mimics 内脚本不实现 Registry、标签生命周期、训练准入或医学格式长期存储。保存 `.mcs` 也不等于提交或验证标签。

## 当前可用代码

1. `scripting_library/Labeling_*.py`：打开、继续、选择、提交、查看、跳过和恢复备份的直接入口。
2. `runtime_py35/sp_review_console.py`：这些入口共享的工作包状态和动作分发实现，不显示功能总菜单。
3. `runtime_py35/sp_diagnostics.py`：工作站 API 诊断。
4. `runtime_py35/sp_open_review.py`：导入或恢复任务、匹配 image set、创建 Mask 和保存 `.mcs`。
5. `runtime_py35/sp_save_checkpoint.py`：保存不依赖 `.mcs` 内部结构的 Mask 恢复快照。
6. `runtime_py35/sp_submit_review.py`：组合选择目标组、提交前预检、批量处理空 Mask。
7. `scripting_library/nnInteractive.py`：任意 Mimics 项目可用的独立 nnInteractive 入口。
8. `runtime_py35/nninteractive_mimics.py` 与 `nninteractive_bridge.py`：提示采集和外部推理桥接，不读取平台任务数据。
9. `probes/`：执行 P01、P02、P04、P05、P06。
10. `src/segplatform/adapters/mimics/`：外部 `doctor/probe/prepare/prebuild/open/finalize` 和 buffer bridge。

代码存在不代表 Mimics 已通过准入。`sp mimics probe-run` 在一个 Mimics 会话内收集 P01/P02/P04/P05/P06，`sp mimics probe-evaluate` 自动比较 DICOM LPS 几何并生成工作站 verified 配置。初始 Mask 注入和提交回收要求默认 `buffer_mapping.status=verified`；若 P05 证明个别 `image_id` 需要不同轴映射，可在 `buffer_mapping_by_image_id` 中加入同样 verified 的覆盖项。

## Case Package 边界

适配器必须直接消费 Case Package v0.5：

- 从 `manifest.json.image_sets` 读取一个或多个平等图像集，不假设 primary/reference；
- 从 `labels/{image_id}/` 读取该图像的初始标签；
- 一个 `.mcs` 第一阶段只承载一个 `review_id`；
- 结果写入 `submissions/{review_id}/` 和 `reports/`；
- 提交 buffer 路径相对 Case Package 保存，可迁移回持有主 Registry 的平台机器；
- 调用 Mimics 前后运行病例包和空间检查；
- 不恢复旧版扁平 `labels/` 目录，也不根据当前 active image 猜测标签归属。

## 标注者入口

平台导出的每个工作包根目录都自带一组 `Labeling_*.py` 和 `runtime_py35/`。建议把工作包根目录设置为 Scripting Library；也可以使用 `Script -> Run Script` 直接选择对应脚本。

标注机不需要安装平台 Python，不需要 Registry、工作站 YAML、assignee 配置或本机 JSON。

标注者运行的脚本名就是动作含义，例如：

- `Labeling_Open_Next_Case.py`
- `Labeling_Case_Navigation.py`
- `Labeling_Submit_Complete.py`
- `Labeling_Submit_or_Report_Issue.py`
- `Labeling_View_Task_List.py`
- `Labeling_Save_Recovery_Backup.py`

高频入口 Open Next、Submit Complete、Task List 和 Recovery Backup 直接执行。Case Navigation 只收纳继续、选择和跳过；Submit or Report Issue 只收纳 Needs Review 和 Report Problem。没有全功能总菜单。

`prepare` 和 `finalize` 只在平台准备/QC 机器运行。导出工作包前必须完成 `prepare`；`prebuild` 是可选加速。没有预生成 `.mcs` 时，Console 会在标注机的 Mimics 内直接导入工作包 DICOM、创建 Mask 并保存项目，仍不调用外部 Python。Console 不会自动 finalize。

平台侧使用 `sp review export-worklist` 导出可移动工作包。`--assignee` 只是可选的中央筛选和分发提示，不参与标注端运行。标注完成后使用 `sp mimics collect-submissions` 收回提交，再运行 `sp mimics finalize-many`。

## 不属于本目录

- 标签生命周期和人工审核政策；
- 训练数据准入；
- NIfTI/MHD 的通用读取器；
- Data Registry；
- 模型推理；
- Web Orchestrator 或任务队列。

标注流程见 [标注工作流](../../docs/domains/labeling/labeling_workflow.md)，版本特定 API 边界见 [Mimics 技术参考](../../docs/domains/labeling/mimics_reference.md)。
安装、命令和完整运行步骤见[标注闭环实现与运行指南](../../docs/domains/labeling/labeling_implementation_guide.md)；Windows 机器上的逐步操作见 [Mimics Research 21 Windows 工作站操作手册](../../docs/domains/labeling/mimics_windows_runbook.md)。
