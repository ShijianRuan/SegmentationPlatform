# CADS 伪标签参考

> 文档状态：资料参考，已按公开来源重新核查。  
> 当前主设计以 `docs/architecture/platform_blueprint.md` 为准；本文只说明 CADS 对平台伪标签和全身分割数据建设的启发，不把 CADS 流程直接当成本项目流程。

## 1. 先读结论

CADS 对本项目有价值，但它不是一个可以直接照搬的“答案”。

可以从 CADS 学到三件事：

1. 全身 CT 分割不一定要等所有病例都有人工全量标注后才开始训练。
2. 大规模数据可以由公开数据、项目自建数据、模型伪标签和质量控制共同形成。
3. 标签进入训练前必须记录来源、空间一致性和质量状态；许可应由平台治理层记录和判断，不归 label_generation 域负责。

不能从 CADS 推出三件事：

1. CADS 的伪标签可以自动变成本项目的金标准。
2. CADS 的标签编号可以直接作为本项目的训练标签编号。
3. CADS 的质量控制和模型性能可以不经检查直接用于本项目。

## 2. 已核实事实

以下内容来自公开页面，当前可以作为文档事实使用。

| 事实 | 来源 | 对本项目的意义 |
| --- | --- | --- |
| CADS 论文为 arXiv:2507.22953，题名为 *CADS: A Comprehensive Anatomical Dataset and Segmentation for Whole-Body Anatomy in Computed Tomography* | arXiv | 可以作为外部参考来源 |
| CADS 摘要称其数据集包含 22,022 个 CT volumes | arXiv、Hugging Face | 说明大规模全身 CT 数据建设有公开案例 |
| CADS 摘要称其覆盖 167 个解剖结构 | arXiv、Hugging Face | 说明统一器官名称和任务级 label map 是必要问题 |
| CADS 摘要称其相比既有集合有 18 倍扫描量、60% 更多解剖目标 | arXiv | 只能作为 CADS 自述的规模比较，不应写成项目承诺 |
| CADS 数据页称数据来自公开数据和项目新增数据，覆盖 100+ 影像中心、16 个国家 | Hugging Face | 数据来源异质性会带来扫描协议、空间一致性和质量差异；许可问题由平台治理层单独处理 |
| CADS 数据页称构建过程包含 pseudo-labeling 和 unsupervised quality control | Hugging Face | 支持“伪标签可成为候选训练标签”的方向 |
| CADS 数据页要求用户检查各子数据集 README 和许可 | Hugging Face | 平台需要记录许可信息，但 label_generation 域不负责做许可裁决 |
| CADS 数据页说明图像和分割以 NIfTI 组织，并按数据源分目录 | Hugging Face | 可作为 Case Package / Dataset Snapshot 的参考，但不能直接套用 |
| CADS 数据页有 affine/intensity 修正历史 | Hugging Face 更新记录 | 空间方向、强度和重采样不能只靠文件存在来判断正确 |

## 3. 对平台的架构启发

CADS 最重要的启发不是某个具体模型，而是“标签来源要分层”。

本平台应该把标签分成这些状态：

| 状态 | 含义 | 是否可训练 |
| --- | --- | --- |
| `source_label` | 外部数据集自带标签 | 需要检查标签定义和空间一致性 |
| `candidate_label` | 算法直接生成的候选标签 | 默认不可直接训练，但任务策略可显式纳入 |
| `accepted_pseudo_label` | 通过平台策略接收的伪标签 | 可按任务策略进入训练 |
| `verified_label` | 人工审核并保存的标签 | 默认可进入训练 |
| `rejected_label` | 被拒绝或发现问题的标签 | 不可训练 |

用户已经明确：高质量伪标签可以直接当训练标签。因此文档里不应写“只有人工审核才是金标准”。更合适的说法是：

> 金标准是最终允许进入训练的标签；它可能来自人工审核，也可能来自经过策略接收的高质量伪标签。

这句话里的关键是“经过策略接收”。否则后续无法解释某个模型到底是用人工标签、外部标签，还是伪标签训练出来的。

## 4. 与标签设计的关系

CADS 覆盖结构多，但本平台不应该把 CADS 的整数 label id 当作全局训练编号。

推荐关系是：

```text
CADS label name / mask
        ↓ 名称映射
平台 anatomy_vocabulary
        ↓ 任务选择
task_label_map
        ↓ 导出
nnUNet labelsTr 整数 mask
```

这样同一套 CADS 来源数据可以服务多个任务：

| 任务 | 可能使用的数据 |
| --- | --- |
| 肺任务 | 只抽取肺、肺叶或气道相关标签 |
| 腹部任务 | 只抽取肝、脾、肾、胰腺等标签 |
| 全身粗分割任务 | 抽取一组覆盖面更广的器官和组织 |
| 放疗危及器官任务 | 抽取与 OAR 相关的结构 |

这也回答了“同一套数据是否可以给多个任务使用”：可以，但前提是每个任务都有自己的 `task_label_map`，并且每个 case 对每个目标器官的标签状态清楚。

## 5. CADS 不能直接变成训练集的原因

CADS 的公开资料明确提醒用户检查子数据集许可，但本平台不将许可裁决纳入 label_generation 域的职责。对本域而言，标签进入训练前需判断的是：

| 检查项 | 为什么重要 |
| --- | --- |
| 标签来源 | 原始人工标签、混合标签和伪标签的可靠性不同 |
| 标签定义 | 同名器官可能有不同边界习惯，例如血管、腔体、左右结构 |
| 空间一致性 | NIfTI 文件存在不代表 affine、方向、spacing 一定可训练 |
| 任务覆盖 | 一个 case 没有某器官标签，不等于这个器官不存在 |
| 质量状态 | 不能把所有来源统一写成 `verified_label` |

因此 CADS 在本平台中的合理位置是：

```text
外部数据源 / 外部模型输出
        ↓
导入平台为 source_label 或 candidate_label
        ↓
经过名称映射、空间检查、质量检查
        ↓
必要时人工审核
        ↓
成为 accepted_pseudo_label 或 verified_label
        ↓
被某个 task_label_map 导出到训练任务
```

## 6. 可以落地到平台的规则

### 6.1 数据导入规则

导入 CADS 或类似数据时，平台至少需要记录：

| 字段 | 示例 |
| --- | --- |
| `source_dataset` | `CADS/0037_totalsegmentator` |
| `source_case_id` | 外部 case id |
| `image_format` | `NIfTI` |
| `label_format` | 单 mask 或多 mask |
| `source_label_map` | 外部标签名称和 id |
| `spatial_check` | spacing、shape、affine、方向是否通过 |
| `admission_status` | `source_label` / `accepted_pseudo_label` / `verified_label` |

### 6.2 质量检查规则

第一阶段不用把 CADS 的质量控制算法完整复现出来，但平台要保留最基本的检查：

| 检查 | 第一阶段做法 |
| --- | --- |
| 文件可读 | 能否被 SimpleITK/Nibabel 读取 |
| 图像-标签一致 | shape、spacing、direction/affine 是否一致 |
| 标签值合法 | 是否能映射到平台器官名称 |
| 空标签 | 标签为空时记录为问题，不静默通过 |
| 标签越界 | 标签是否超出图像范围或出现异常几何 |
| 器官覆盖 | 当前任务需要的器官是否存在可训练标签 |

### 6.3 训练准入规则

训练快照生成时，平台不直接问“这个标签是不是 CADS 来的”，而是问：

1. 这个标签的状态是否允许进入当前任务？
2. 这个标签的来源是否在当前任务的可信来源范围内？
3. 这个标签是否通过了空间和名称映射检查？
4. 当前任务是否明确允许 `accepted_pseudo_label`？

通过这些条件后，CADS 标签才可以成为 nnUNet 训练数据的一部分。

## 7. 不再保留的旧说法

| 旧说法 | 问题 | 当前写法 |
| --- | --- | --- |
| “CADS 伪标签可直接作为金标准” | 抹掉来源和准入策略 | “CADS 可作为候选伪标签来源，是否进入训练由 label policy 决定” |
| “CADS 流程可直接复刻” | 公开页面不足以支撑完整流程细节 | “CADS 证明这条路线可行，但本平台需要自己的最小闭环” |
| “所有 CADS 标签都是完整可靠标签” | 来源、质量和更新历史更复杂 | “导入后必须记录来源、空间检查和状态” |
| “CADS 的 label id 可直接用于训练” | nnUNet 要求任务内连续整数编号 | “先映射到平台器官名称，再由 task label map 导出” |
| “性能数字可以直接写进平台设计” | 没有逐表核查前容易错配 | “性能指标需要回到论文表格单独核查后再引用” |

## 8. 对当前平台的建议

第一阶段可以把 CADS 当作两类输入：

1. 作为公开算法/数据路线的参考，帮助设计 label policy。
2. 作为未来外部数据导入的 POC 样例，测试名称映射、空间校验和 task label map 导出。

不建议第一阶段做这些事：

1. 直接把 CADS 数据批量混入训练集。
2. 直接采用 CADS 的标签编号作为平台编号。
3. 在没有空间检查前，把 CADS mask 标成 `verified_label`。
4. 在没有逐表核查前，把 CADS 论文里的性能数字写成平台设计依据。

## 9. 来源

- [CADS arXiv paper](https://arxiv.org/abs/2507.22953)
- [CADS Hugging Face dataset page](https://huggingface.co/datasets/mrmrx/CADS-dataset)
- [CADS 3D Slicer plugin repository](https://github.com/murong-xu/SlicerCADSWholeBodyCTSeg)
- [nnU-Net dataset format](https://github.com/MIC-DKFZ/nnUNet/blob/master/documentation/dataset_format.md)
