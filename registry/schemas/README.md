# 记录格式定义（registry schemas）

> 状态：核心记录的机器可读格式定义。这些 JSON Schema 文件是字段形状的**唯一事实源**。
> 关系：[平台数据模型](../../docs/architecture/platform_data_model.md)用示例解释“为什么这样设计”；本目录的 schema 规定“字段、类型和取值到底是什么”。两者不一致时，以 schema 为准。

## 1. 为什么需要它

`schema_version`（如 `label_artifact.v1`）原本只是清单里的一个字符串标签，背后没有可校验的定义；校验逻辑散落在手写代码里。记录种类一多、共享字段（`usage_constraints`、`hash`、`lineage`、`geometry`）反复出现时，多份手写校验必然互相对不上。

把形状集中成 schema 后：

- 共享结构只定义一次（见 `_defs.schema.json`），各记录用 `$ref` 引用，不重复。
- 校验程序从同一份定义派生，而不是各写一套。
- `schema_version` 有了真实可执行的含义。

## 2. schema_version 与文件对应

| schema_version | 文件 | 对应记录 |
| --- | --- | --- |
| `anatomy_vocabulary.v1` | `anatomy_vocabulary.schema.json` | 器官名称表（规范文件 `config/anatomy_vocabulary.yaml`） |
| `case_manifest.v1` | `case_manifest.schema.json` | 病例 Case |
| `image_artifact.v1` | `image_artifact.schema.json` | 图像记录；支持单文件、DICOM/MHD 文件组和不完整空间信息 |
| `label_artifact.v1` | `label_artifact.schema.json` | 标签记录（含按 segment 的 `lineage`） |
| `dataset_snapshot.v1` | `dataset_snapshot.schema.json` | 训练数据快照 |
| `review_task.v1` | `review_task.schema.json` | 离线人工标注任务、目标组状态和事件 |
| —（共享） | `_defs.schema.json` | 被各 schema 引用的共享 `$defs`，本身不对应单条记录 |

## 3. 还没有 schema 的记录（按需补，不提前写）

以下记录在数据模型里已有字段示例，但目前**没有任何代码创建它们**。为避免“设计跑在代码前面”，等对应实现落地时再按本目录的写法补 schema：

- `review_task.v1`（标注任务）
- `model_record.v1`（模型记录）
- `evaluation_record.v1`（评估记录）
- `candidate_generation_job.v1`（候选标签生成批次）
- `generator_metadata.v1`（外部算法说明）

病例包契约 `case_package.v0.5` 是另一份独立交换契约，目前由 `scripts/check_case_package.py` 直接校验；后续可考虑迁移成 schema，但不在本批改动范围内。

## 4. 校验程序怎样使用（待实现）

schema 之间用相对 `$ref`（如 `_defs.schema.json#/$defs/segment`）引用，解析基准目录就是本目录。Python 侧可用 `jsonschema`：把本目录所有 `*.schema.json` 注册进 `referencing.Registry`，再按记录的 `schema_version` 取对应 schema 校验。

本批改动**只提供定义，不新建 CLI 或校验器**。数据模型 §13 规划的 `sp validate` 应当加载这些 schema，而不是另写一套字段检查。

JSON Schema 只检查结构。下面这些跨记录或文件语义仍必须由运行时校验器完成：

- `bundle_manifest` 摘要是否与实际文件组一致；
- DICOM、NIfTI、MHD+RAW 或 RAW 是否真的能解码；
- `geometry_status`、空间字段证据和 `usability` 是否相互一致；
- Image Artifact 与 Label Artifact 是否实际对齐；
- 低可信度防泄漏分组是否被错误放入正式验证或测试。
