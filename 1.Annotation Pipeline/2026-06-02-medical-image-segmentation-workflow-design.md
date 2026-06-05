# 医学图像多器官分割标注数据管线设计文档

日期: 2026-06-02

## 1. 设计概览

本设计面向多器官分割数据集构建。系统自动完成图像标准化、模型分割、来源标签归一化、草稿融合、标注包生成、人工结果导回、自动校验、差异记录和数据集导出。

人工只参与标注审核环节：在标注工具中检查、必要时修正，并保存一次。保存导回后的标签是最终真值。

设计目标：

- 将多来源分割结果组织成可复现、可追溯的数据生产流程。
- 将人工操作压缩到标注工具内的检查、修正和保存。
- 明确区分自动生成草稿与人工确认真值，防止未审核标签进入最终数据集。
- 通过配置文件管理器官、来源和融合策略，降低新增器官或模型来源的成本。

设计理由：

- 模型分割结果不直接作为真值，只作为人工审核草稿。
- 人工确认不采用 checklist 或逐器官表单，避免增加标注负担。
- 所有自动步骤通过状态流转和 metadata 记录，保证批量处理时仍可追溯。
- 标注工具通过适配器接入，避免管线绑定具体工具。

核心标签对象：

| 对象 | 含义 |
|---|---|
| `draft_label.nii.gz` | 自动生成的待审核草稿 |
| `verified_label.nii.gz` | 人工检查并保存后的最终真值 |
| `metadata.json` | 系统自动维护的处理记录 |

## 2. 总体架构

```text
┌──────────────────────────────────────────────────────────────┐
│                    organ_config.yaml                         │
│        器官定义 / 来源 ID 映射 / 融合策略 / 颜色              │
└──────────────────────────────┬───────────────────────────────┘
                               │
┌──────────────────────────────▼───────────────────────────────┐
│                    Pipeline Orchestrator                      │
│              状态推进 / 任务调度 / metadata 追加              │
└───────┬──────────────┬──────────────┬──────────────┬─────────┘
        │              │              │              │
┌───────▼──────┐ ┌─────▼──────┐ ┌─────▼──────┐ ┌─────▼────────┐
│   Acquire    │ │ Fuse Draft │ │   Review   │ │    Export    │
│ 图像与来源获取 │ │ 草稿融合     │ │ 人工导入导出 │ │ 标准数据导出  │
└───────┬──────┘ └─────┬──────┘ └─────┬──────┘ └─────┬────────┘
        │              │              │              │
┌───────▼──────────────▼──────────────▼──────────────▼─────────┐
│                         Filesystem                           │
│ sources/* / ct.nii.gz / draft_label / verified_label / metadata│
└──────────────────────────────────────────────────────────────┘
```

端到端流程：

```text
原始病例
  ↓
Acquire
  生成 ct.nii.gz
  调用模型脚本
  导入已有来源标签
  ↓
Fuse Draft
  来源标签重采样到 CT 网格
  来源 ID 映射为统一 ID
  融合生成 draft_label.nii.gz
  ↓
Review
  系统生成标注包
  人工检查、修正、保存一次
  系统导回 verified_label.nii.gz
  ↓
Validate
  自动比较 draft 与 verified
  自动记录变化和异常
  ↓
Export
  基于 verified 导出标准数据集
```

## 3. 数据对象

### 3.1 病例工作目录

```text
{case_id}/
├── ct.nii.gz
├── draft_label.nii.gz
├── verified_label.nii.gz
├── metadata.json
└── review_workspace/
```

| 文件 | 阶段 | 说明 |
|---|---|---|
| `ct.nii.gz` | Acquire | 标准化后的 CT 图像 |
| `draft_label.nii.gz` | Fuse Draft | 自动融合草稿 |
| `verified_label.nii.gz` | Review | 人工保存后的最终真值 |
| `metadata.json` | 全流程 | 处理记录、来源、差异和异常 |
| `review_workspace/` | Review | 标注工具工作区 |

### 3.2 来源标签目录

```text
sources/{source_name}/{case_id}.nii.gz
```

来源标签保留对应来源的原始 ID 体系，在 Fuse Draft 阶段统一映射。

### 3.3 输出数据集目录

```text
output_dataset/
├── dataset.json
├── case_001/
│   ├── ct.nii.gz
│   ├── liver.nii.gz
│   ├── spleen.nii.gz
│   └── metadata.json
└── ...
```

## 4. 状态流转

```text
new
  ↓
normalized
  ↓
sources_ready
  ↓
draft_ready
  ↓
reviewing
  ↓ 人工保存一次
verified
  ↓
validated ───────────────→ exported
  │
  └──→ needs_attention
```

| 状态 | 含义 |
|---|---|
| `new` | 病例已登记 |
| `normalized` | 已生成 `ct.nii.gz` |
| `sources_ready` | 来源标签已收集 |
| `draft_ready` | 已生成 `draft_label.nii.gz` |
| `reviewing` | 标注包已生成，等待人工保存 |
| `verified` | 已导回 `verified_label.nii.gz` |
| `validated` | 自动校验通过 |
| `needs_attention` | 存在需处理异常 |
| `exported` | 已导出标准数据集 |

## 5. 配置文件

系统使用单一 `organ_config.yaml`。

```yaml
version: "1.0"

defaults:
  strategy: fill_missing
  source_priority:
    - manual
    - totalsegmentator
    - nnunet

organs:
  liver:
    id: 1
    color: [221, 75, 57]
    synonyms: [liver, hepar]
    sources:
      totalsegmentator: 1
      nnunet: 1
      manual: 1

  liver_vessel:
    id: 2
    color: [0, 150, 130]
    synonyms: [liver_vessel, hepatic_vessel]
    sources:
      totalsegmentator: null
      nnunet: 2
      manual: 2

  aorta:
    id: 4
    color: [200, 50, 50]
    synonyms: [aorta, aortic]
    sources:
      totalsegmentator: 3
      nnunet: 4
      manual: 4
    override_strategy: highest_available
    override_priority: [totalsegmentator, nnunet, manual]
```

字段规则：

| 字段 | 说明 |
|---|---|
| `version` | 配置版本 |
| `defaults.strategy` | 默认融合策略 |
| `defaults.source_priority` | 默认来源优先级，从高到低 |
| `organs.{key}` | 器官 key，使用 snake_case |
| `organs.{key}.id` | 管线内部统一标签 ID |
| `organs.{key}.color` | RGB 颜色 |
| `organs.{key}.sources` | 各来源中的原始标签 ID |
| `override_strategy` | 器官级融合策略覆盖 |
| `override_priority` | 器官级来源优先级覆盖 |

器官 key 必须以小写字母开头，后续只能使用小写字母、数字或下划线。

## 6. 模块设计

### 6.1 Acquire

职责：

- 接收 DICOM、mhd 或 nii.gz 原始图像。
- 生成标准化 `ct.nii.gz`。
- 导入已有标签来源。
- 调用外部模型脚本生成模型来源标签。
- 写入 `metadata.json`。

输出：

```text
{case_id}/ct.nii.gz
sources/manual/{case_id}.nii.gz
sources/{model}/{case_id}.nii.gz
```

图像标准化规则：

- 输出格式为 nii.gz。
- 统一方向为 RAS。
- 记录 spacing、origin、direction、shape。
- 输入已是 nii.gz 时仍校验方向和空间信息。

模型脚本接口：

```bash
./scripts/run_{source_name}.sh \
  /path/to/{case_id}/ct.nii.gz \
  /path/to/sources/{source_name}/{case_id}.nii.gz
```

脚本约定：

- 参数 1 是只读输入图像。
- 参数 2 是来源标签输出路径。
- 输出标签保留来源原始 ID。
- 退出码 `0` 表示成功，非 `0` 表示失败。
- 失败来源写入 `metadata.json`。
- 默认超时 2 小时，可通过 `LABELSTD_MODEL_TIMEOUT` 覆盖。

### 6.2 Fuse Draft

职责：

- 将来源标签重采样到 `ct.nii.gz` 网格。
- 将来源 ID 映射为统一 ID。
- 按配置融合生成 `draft_label.nii.gz`。
- 记录融合过程。

输入：

```text
ct.nii.gz
sources/*/{case_id}.nii.gz
organ_config.yaml
```

输出：

```text
draft_label.nii.gz
metadata.json
```

空间与标签规则：

- 来源标签重采样到 CT 的 spacing、origin、direction 和 shape。
- 标签重采样使用 nearest-neighbor 插值。
- CT 网格外区域丢弃。
- CT 网格内缺失区域填充 0。
- 未在配置中声明的标签 ID 记录为异常并忽略。

融合策略：

| 策略 | 语义 |
|---|---|
| `fill_missing` | 按优先级选择第一个实际包含该器官的来源，整器官写入草稿 |
| `hard_constraint` | 高优先级来源先写入并锁定非 0 voxel，低优先级来源只能补空 voxel |
| `highest_available` | 只使用优先级最高且实际包含该器官的来源 |

融合记录：

- 配置版本和 hash。
- 输入来源文件 hash。
- 每个器官采用的来源。
- 每个来源缺失的器官。
- 重采样参数。
- 忽略的未知标签。

### 6.3 Review

职责：

- 生成标注工具可打开的 review package。
- 等待人工检查、修正并保存一次。
- 导回 `verified_label.nii.gz`。
- 触发 Validate。

人工动作：

| 动作 | 要求 |
|---|---|
| 打开标注包 | 是 |
| 检查标签 | 是 |
| 必要时修正 | 是 |
| 保存一次 | 是 |
| 填写 checklist | 否 |
| 逐器官确认 | 否 |

review package：

```text
review_workspace/{case_id}/
├── ct.nii.gz
├── draft_label_for_tool.*
├── color_table.*
└── tool_metadata.*
```

工具导出位置：

```text
review_workspace/{case_id}/verified_from_tool.*
```

导回适配器接口：

```bash
./adapters/{tool_name}/ingest.sh \
  /path/to/review_workspace/{case_id}/verified_from_tool.* \
  /path/to/{case_id}/ct.nii.gz \
  /path/to/organ_config.yaml \
  /path/to/{case_id}/verified_label.nii.gz
```

导回适配器职责：

- 读取工具保存结果。
- 映射回统一 ID。
- 校验或重采样到 CT 网格。
- 输出单个多标签 `verified_label.nii.gz`。
- 输出导回摘要到 stdout。

### 6.4 Validate

职责：

- 比较 `draft_label.nii.gz` 与 `verified_label.nii.gz`。
- 记录人工修改造成的变化。
- 判断是否进入 Export。

记录内容：

- 新增器官。
- 删除器官。
- 发生变化的器官。
- 每个器官的体积变化比例。
- 每个器官的 Dice 或 voxel overlap。
- 未知标签 ID。
- 空间网格一致性。

异常处理：

| 异常 | 等级 | 处理 |
|---|---|---|
| `verified_label.nii.gz` 不存在 | error | 保持 `reviewing` |
| 文件为空或全 0 | error | 进入 `needs_attention` |
| 空间信息与 CT 不一致且无法重采样 | error | 进入 `needs_attention` |
| 出现未知 label ID | warning | 忽略未知 ID，并记录 warning |
| 草稿中存在的器官消失 | warning | 记录 warning，可配置为阻断 |
| 器官体积变化超过阈值 | warning | 记录 warning，可配置为阻断 |

默认规则：error 阻断导出，warning 不阻断导出。

### 6.5 Export

职责：

- 从 `verified_label.nii.gz` 生成最终数据集。
- 将多标签文件拆分为每器官独立二值 mask。
- 输出 TotalSegmentator 风格目录。

导出规则：

- `draft_label.nii.gz` 不允许导出。
- 每个器官导出为独立二值 mask，值为 1。
- 文件名等于器官 key。
- `dataset.json` 包含器官列表、统一 ID、颜色和配置版本。
- 每个病例保留对应 `metadata.json`。

## 7. metadata 结构

```json
{
  "case_id": "case_001",
  "status": "validated",
  "config_version": "1.0",
  "config_hash": "sha256:...",
  "image": {
    "spacing": [1.0, 0.75, 0.75],
    "shape": [512, 512, 300],
    "orientation": "RAS"
  },
  "history": [
    {
      "step": "normalize",
      "timestamp": "2026-06-02T10:00:00",
      "input_hash": "sha256:...",
      "output_hash": "sha256:..."
    },
    {
      "step": "acquire",
      "source": "totalsegmentator",
      "timestamp": "2026-06-02T10:05:00",
      "status": "ok",
      "command": "./scripts/run_totalsegmentator.sh ...",
      "output_hash": "sha256:..."
    },
    {
      "step": "fuse_draft",
      "timestamp": "2026-06-02T10:12:00",
      "output": "draft_label.nii.gz",
      "output_hash": "sha256:...",
      "organ_sources": {
        "liver": "totalsegmentator",
        "spleen": "totalsegmentator",
        "liver_vessel": "nnunet"
      }
    },
    {
      "step": "review_ingest",
      "timestamp": "2026-06-02T12:00:00",
      "tool": "3D_Slicer",
      "output": "verified_label.nii.gz",
      "output_hash": "sha256:..."
    },
    {
      "step": "validate",
      "timestamp": "2026-06-02T12:02:00",
      "changed_organs": ["liver"],
      "added_organs": ["pancreas"],
      "removed_organs": [],
      "warnings": []
    }
  ],
  "final_organs": ["liver", "spleen", "liver_vessel", "pancreas"]
}
```

## 8. 已验证标签更新规则

人工确认结果不得被模型自动覆盖。

已审核病例追加新模型或新器官时：

1. 当前 `verified_label.nii.gz` 作为最高优先级 `manual` 来源。
2. 新模型只用于补充缺失器官或生成新的 `draft_label.nii.gz`。
3. 新草稿重新进入 Review。
4. 人工再次保存后生成新的 `verified_label.nii.gz`。

任何自动 re-fuse 只能生成草稿，不能直接改写真值。

## 9. 关键设计决策

| 决策 | 当前设计 | 理由 |
|---|---|---|
| 真值来源 | `verified_label.nii.gz` | 只有人工检查并保存后的结果才进入最终数据集 |
| 自动融合产物 | `draft_label.nii.gz` | 自动结果只作为待审核草稿 |
| 人工确认方式 | 标注工具中保存一次 | 减少人工流程，不引入额外表单 |
| 人工参与点 | 仅 Review | Acquire、Fuse、Validate、Export 均自动化 |
| 配置方式 | 单一 `organ_config.yaml` | 器官定义、来源 ID 和融合策略集中管理 |
| 模型调用 | 外部脚本 | 隔离模型运行环境 |
| 标注工具接入 | 适配器 | 支持 3D Slicer、Mimics、ITK-SNAP 等工具切换 |
| 空间统一 | RAS + CT 网格 | 保证多来源标签可以正确融合 |
| 标签插值 | nearest-neighbor | 避免重采样产生非法标签值 |
| 导出来源 | 只导出 verified | 防止草稿标签进入标准数据集 |
