# SegmentationPlatform

医学影像分割平台的架构与实现仓库。项目要把数据导入、人工标注、模型训练、评估和候选标签回流连成一条可重复执行的流程，同时允许后续更换 nnUNet、Mimics 或其他具体工具。

## 从这里开始

1. 阅读[文档入口](docs/README.md)，找到与你当前工作有关的文档。
2. 阅读[平台蓝图](docs/architecture/platform_blueprint.md)，理解平台完整流程和三大实现域。
3. 遇到固定英文名称或缩写时查看[常用词说明](docs/glossary.md)。
4. 准备开发时先看[阶段 A 开发执行说明](docs/plans/development_execution_guide.md)，再查看[近期任务清单](docs/plans/implementation_backlog.md)。
5. 修改现有训练管线前先看 [`pipelines/nnunet/README.md`](pipelines/nnunet/README.md)。
6. 开发或试用 Mimics 接入时直接看[Mimics 适配器设计与开发流程](docs/domains/labeling/mimics_adapter_design.md)。

## 项目结构

```text
adapters/   把平台标准数据转换成具体工具所需格式的适配代码
config/     平台级配置；当前有统一器官名称表 anatomy_vocabulary.yaml
docs/       现行架构、实现域文档、计划、研究和外部参考
pipelines/  已有可运行管线；当前主要是 nnUNet
registry/   资产登记册；当前有核心记录的格式定义 schemas/（JSON Schema）
scripts/    与具体工具无关的校验和文件包脚本
```

## 当前状态

| 部分 | 状态 |
| --- | --- |
| nnUNet 管线 | 已有转换、预处理、训练、预测和评估代码 |
| 病例包校验 | 已有 v0.5 提交前检查和可选的目录校验值工具 |
| 统一器官名称表 | 已从 ModelMap 生成 `config/anatomy_vocabulary.yaml`（120 个器官） |
| 记录格式定义 | `registry/schemas/` 已定义核心记录的 JSON Schema，作为字段唯一事实源 |
| Mimics 工具适配器 | 双运行时、代码任务和标注者流程已定义；诊断、探针和生产脚本尚未实现 |
| 候选标签生成适配器 | 只有输入输出边界，尚未实现 |
| 数据导入、登记册和训练数据快照 | 异构数据入口和核心记录格式已定义，运行时代码、服务和数据库尚未实现 |

仓库当前还不是一个可以一键启动的完整平台。现阶段目标是先跑通离线文件包闭环，文档中的后期服务能力不能当作已经实现。

## 目录规则

- 当前有效的平台设计写入 `docs/architecture/` 或 `docs/domains/`。
- 实施安排写入 `docs/plans/`。
- 尚未进入实现的算法研究写入 `docs/research/`。
- 外部手册只放在 `docs/references/`，不直接定义平台行为。
- 自动生成输出、临时运行脚本和本地素材不提交到仓库。
