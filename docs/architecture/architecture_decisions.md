# 架构决策记录

> 日期：2026-06-06  
> 状态：保留关键讨论结论；主文档以 `docs/architecture/platform_blueprint.md` 为准。

## 1. 为什么保留这个文档

之前的架构讨论很长，里面既有结论，也有推理过程和未定问题。为了让主蓝图更容易读，这里只保留已经形成方向的决策。后续如果某个决策改变，应先改这里，再同步主蓝图。

## 2. 已形成的决策

| 编号 | 决策 | 理由 | 影响 |
| --- | --- | --- | --- |
| ADR-001 | 平台中心是病例、图像、标签、训练任务和模型版本，不是某个管线 | 标注、训练、伪标签、部署都会围绕这些对象发生 | 文档和实现都应先保证数据关系清楚 |
| ADR-002 | 采用统一器官名称 + 任务级 label map | nnUNet 要求任务内标签从 0/1 连续编号，现有 ModelMap 已采用这种方式 | 不设计全平台唯一训练 label id |
| ADR-003 | 同一套数据可以给多个任务使用 | 真实场景会同时有局部任务、粗分割任务和全身任务 | 通过 Dataset Snapshot 冻结不同任务视图 |
| ADR-004 | 高质量伪标签可以进入训练，但必须保留来源状态 | 用户明确允许高质量伪标签直接作为训练标签 | 用 label policy 控制准入，不能默认混入 |
| ADR-005 | 第一阶段单人保存即可视为 `verified_label` | 先跑通闭环比设计复杂审核更重要 | 多人审核后置 |
| ADR-006 | nnUNet 先跑通，但抽象为 Adapter | 当前训练管线已有可复用基础 | 后续可接 MONAI、Transformer、少样本训练 |
| ADR-007 | Mimics 是优先 POC 工具候选，不是平台唯一底座 | 公开资料支持高层能力，但导入导出闭环需本机验证 | Mimics 相关结论必须区分已核实和待 POC |
| ADR-008 | 早期使用文件包手动串联 | 标注在 Windows，本地/远程训练可能分离 | 不急着做统一调度服务 |
| ADR-009 | 部署管线先按离线批量推理设计 | 当前目标是数据闭环，不是在线服务 | 推理结果作为候选标签回流 |
| ADR-010 | Orchestrator 后置 | 调度层依赖稳定的数据契约 | 不在主蓝图里过早指定 FastAPI、Celery 等实现 |
| ADR-011 | 文档和后续实现按 `labeling`、`training`、`label_generation` 三大域组织 | 既保留平台全局视角，也让后续代码和文档更容易定位 | 不再把第三个域硬叫 `pseudo_labeling` |
| ADR-012 | QC 是检查层，不是标签状态 | 标签状态记录来源和生命周期，QC 记录是否满足几何、内容和准入规则 | `candidate_label` 可按策略进入训练，但来源和状态不能被改写 |
| ADR-013 | Case Package 自包含，但不携带任务级 label map | 标注包服务人工 review，训练编号属于 Dataset Snapshot | `anatomy_vocabulary.yaml` 和 `review_label_map.yaml` 放入包内，`task_label_maps.yaml` 后置到训练快照 |
| ADR-014 | FewShot 是 training 域的实验型 Adapter | 少样本学习消费 Dataset Snapshot 并产出 Model Record，和 nnUNet Adapter 平行 | 先定义实验协议，生产级验证后再实现正式 Adapter |
| ADR-015 | label_generation 不负责许可裁决 | 候选标签域关注生成、映射、QC 和回流；数据许可是平台治理问题 | CADS/公开算法文档只记录许可需求，不把许可判断写进本域准入逻辑 |

## 3. 标签决策的解释

“统一 label space”容易误解。平台不应该把所有器官强行分配一个全局训练编号，因为训练框架通常要求一个任务内部的类别从 0 开始连续编号。

平台真正需要统一的是器官名称。例如 `liver` 在平台里永远表示肝脏。至于它在某个训练任务里是 label 2，还是在某个合并 mask 里是 label 37，由 TaskLabelMap 或 CombineMap 决定。

这也解释了为什么现有 nnUNet 管线不需要立刻大改：现有 `ModelMap.toml` 已经把 `CT3_Lung`、`CT5_Liver` 等任务分开编号。平台后续要做的是让这些 map 来自更清晰的数据注册和任务定义。

## 4. 伪标签决策的解释

伪标签的细节可以后置，但状态必须现在设计清楚。

推荐把标签分为：

| 状态 | 进入训练的默认态度 |
| --- | --- |
| `candidate_label` | 不进入训练 |
| `draft_label` | 不进入训练，只给人工修正 |
| `accepted_pseudo_label` | 可按任务策略进入训练 |
| `verified_label` | 可进入训练 |
| `rejected_label` | 不进入训练 |

用户所说“金标准是最终用于训练的标签”可以成立，但文档里更推荐写成“训练准入标签”。原因是同样进入训练的标签，人工 verified 和 accepted pseudo 的风险不同，后续评估、回溯和模型发布必须能区分。

## 5. Mimics 决策的解释

Mimics 的调研要以“现在就要使用是否可行”为前提。当前结论是：可以试，但不能假设闭环已经成立。

必须 POC 的点：

1. DICOM/NIfTI 图像能否稳定导入。
2. 草稿标签能否以可编辑 mask 的形式导入。
3. 人工修改后能否导出逐器官 mask 或单多标签文件。
4. 导出标签与原始 CT 的 shape 是否一致；spacing、origin、direction、affine 不一致时能否被平台侧检测和修复。
5. Python scripting 能否覆盖必要的批量步骤。

如果 POC 失败，平台仍然可以使用 Mimics 做人工修正，但导入导出需要更保守的中间格式，或改用 3D Slicer/ITK-SNAP/MONAI Label 等工具作为补充。

## 6. 仍未决的问题

| 问题 | 为什么还不能定 |
| --- | --- |
| 哪些具体器官或任务排除伪标签直接训练 | 默认允许 `accepted_pseudo_label`，但排除规则需要按任务沉淀 |
| 是否只用 verified 标签做正式评估 | 会议判断第一阶段考虑太早，后续评估设计再收敛 |
| Mimics 是否能作为主要标注工具 | 需要本机版本和真实病例 POC |
| 数据许可如何落地 | 公开数据、公开算法、内部产品训练的边界需要单独确认 |

## 7. 文档维护规则

1. `docs/architecture/platform_blueprint.md` 是主蓝图，优先更新。
2. 本文只记录架构决策，不再保存长篇讨论。
3. 具体文件包格式写入 `docs/domains/labeling/case_package_contract.md`。
4. Mimics 的事实核查和 POC 判断写入 `docs/domains/labeling/mimics_feasibility.md`。
5. 执行计划、任务拆分、脚本 backlog 不应反向污染架构蓝图。
