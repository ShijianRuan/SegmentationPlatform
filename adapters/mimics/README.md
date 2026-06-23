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
    Start_Labeling.py
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
| `adapters/mimics/scripting_library/` | Mimics Scripting Library | 标注者日常可见入口，只放 `Start_Labeling.py` |
| `adapters/mimics/runtime_py35/` | Mimics Python 3.5.2 | 内部实现脚本，调用 Mimics API、管理 image set 和 Mask、保存 `.mcs`、导出提交缓冲区 |
| `adapters/mimics/probes/` | Mimics Python 3.5.2 | 单次会话验证 API、图像绑定、轴顺序、空间往返和选择性导出 |

Mimics 内脚本不实现 Registry、标签生命周期、训练准入或医学格式长期存储。保存 `.mcs` 也不等于提交或验证标签。

## 当前可用代码

1. `scripting_library/Start_Labeling.py`：Mimics 菜单中给标注者使用的唯一入口。
2. `runtime_py35/sp_review_console.py`：任务领取、保存 recovery backup、提交和可选 finalize 的内部控制台。
3. `runtime_py35/sp_diagnostics.py`：工作站 API 诊断。
4. `runtime_py35/sp_open_review.py`：导入或恢复任务、匹配 image set、创建 Mask 和保存 `.mcs`。
5. `runtime_py35/sp_save_checkpoint.py`：保存不依赖 `.mcs` 内部结构的 Mask 恢复快照。
6. `runtime_py35/sp_submit_review.py`：组合选择目标组、提交前预检、批量处理空 Mask。
7. `probes/`：执行 P01、P02、P04、P05、P06。
8. `src/segplatform/adapters/mimics/`：外部 `doctor/probe/prepare/prebuild/open/finalize` 和 buffer bridge。

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

日常入口是 Mimics 内的 `Script -> Scripting Library -> Start Labeling`。管理员把
`adapters/mimics/scripting_library/` 配置为 Scripting Library 目录，并把
`config/mimics_review_console.example.json` 复制为
`adapters/mimics/scripting_library/sp_review_console.local.json`。

标注者只做三件事：

1. 打开 Mimics。
2. 运行 **Start Labeling**，选择 **Start Next Case**。
3. 编辑 Mask，并在同一 Console 中选择 **Complete**、**Needs Review**、**Report Problem**、**Skip Case**、**Task List** 或 **Save Recovery Backup**。

**Task List** 是当前稳定的非阻塞任务清单入口：它在 Mimics 弹窗内分页显示当前病例、目标器官统计和受管 Mask 状态，并支持按 Missing、Ready、With Initial、Known Absent 筛选。Project Tree 常驻注释对象仍需 Mimics 21 实机 POC 证明，不能作为生产依赖。

`prepare`、`prebuild`、`open`、`finalize` 仍保留为平台/管理员命令，用于批量准备、预生成 `.mcs`、调试和后台收尾，不作为标注者日常步骤。`prebuild` 通过 Mimics `-background_mode` 调用 `sp_open_review.py --background-prebuild`，成功后写入 `working/prebuilt_workspace.json`；已有普通 `.mcs` 默认跳过，避免覆盖标注者现场。路径、文件名、标签编号、格式转换、Registry 写入和最终 QC 由平台处理。

多工作站无共享盘时，平台侧使用 `sp review export-worklist` 为每个标注者导出本地工作包；标注完成后使用 `sp mimics collect-submissions` 把 `submissions/` 收回中央病例包，再运行 `sp mimics finalize-many`。标注者仍只在 Mimics 内使用 **Start Labeling**。

## 不属于本目录

- 标签生命周期和人工审核政策；
- 训练数据准入；
- NIfTI/MHD 的通用读取器；
- Data Registry；
- 模型推理；
- Web Orchestrator 或任务队列。

标注流程见 [标注工作流](../../docs/domains/labeling/labeling_workflow.md)，版本特定 API 边界见 [Mimics 技术参考](../../docs/domains/labeling/mimics_reference.md)。
安装、命令和完整运行步骤见[标注闭环实现与运行指南](../../docs/domains/labeling/labeling_implementation_guide.md)；Windows 机器上的逐步操作见 [Mimics Research 21 Windows 工作站操作手册](../../docs/domains/labeling/mimics_windows_runbook.md)。
