# 对话问题处理清单

> 来源：`docs/conversations/chat_conversation_cleaned.md`（共 19 轮、23 个问题）
> 目的：把对话中用户提出的疑问收敛为当前项目的明确结论、实现状态和剩余边界。
> 立场：这份清单不是照搬原回复，而是基于**当前代码现状**重新核对后的独立判断。原回复里有几处在用户已经明确表态后仍然退缩的结论，本文予以纠正（见第 3 节）。
> 更新原则：能落地且可测的补代码；依赖 Mimics 实机才能验证的说明路径和前置条件，不把无法测试的调用写死；不把阶段 B/E 的服务化能力提前塞进阶段 A。
> 冲突处理：本文不直接定义平台行为。若与 `docs/architecture/` 和 `docs/domains/` 冲突，以那里为准；本文负责把冲突点指出来。

## 0. 代码现状速查（已逐文件核对）

| 能力 | 代码位置 | 现状 |
| --- | --- | --- |
| 扫描支持 DICOM/NIfTI/MetaImage | `ingest.py:scan_source` | ✅ DICOM 按头分组；NIfTI/MHD 按文件发现、按父目录归 Case；RAW 无 sidecar 跳过 |
| 复杂数据集描述导入 | `dataset_descriptions.py` / `sp ingest from-description` | ✅ 支持正则发现和 CSV 配对，生成标准 `case_package_request.v1` |
| 初始标签显式声明 | `case_packages.py:_write_initial_labels` | ✅ 单器官 `organ` / 多标签 `label_map`，强制几何校验 |
| 三步导入（scan/build-requests/package create） | `ingest.py` / `case_packages.py` | ✅ |
| 批量 prepare / finalize / review stats | `cli.py` | ✅ `prepare-many`、`finalize-many`、`review stats` |
| 离线工作包分发 / 提交收集 | `distribution.py` / `cli.py` | ✅ `review export-worklist`、`mimics collect-submissions` |
| Snapshot 请求草稿生成 | `snapshots.py` / `cli.py` | ✅ `snapshot build-request` 可从 Registry 批量生成草稿 |
| 追加器官 / 返修 review | `review_updates.py` / `sp review create-followup` | ✅ 新建 follow-up package，不覆盖旧提交 |
| 临时跳过任务 | `reviews.py` / `sp review defer/reactivate` / `Start Labeling` | ✅ `deferred` 状态区别于 blocked |
| 提交半截崩溃隔离 | `sp_submit_review.py` | ✅ staging 目录发布，半成品不进入正式 `submissions/` |
| 旧标签退休 | `finalize.py` / Registry label index | ✅ complete 新版本会把 base 标记为 `superseded` |
| Submit 目标组 toggle（2–5）/ 空 Mask outcome | `sp_submit_review.py` | ✅ |
| Save Recovery Backup / Submit 区分 | `sp_save_checkpoint.py` / `sp_submit_review.py` | ✅ |
| Task List（主动重看任务） | `sp_review_console.py:show_current_summary` | ✅ |
| 初始分割导入 + 无初标建空 Mask | `sp_open_review.py:102–148` | ✅ |
| **Mimics 路径支持 NIfTI/MHD** | `case_packages.py` / `imaging.py` / `prepare.py` | ✅ 外部转派生 DICOM 后走 Mimics 导入；需 Windows 实机验证 |
| **prepare 阶段预导入（background_mode）** | `launcher.py:prebuild_workspace` / `sp_open_review.py --background-prebuild` | ✅ 已实现调用链；需 Windows 实机验证 |
| **known_absent 跳过预创建空 Mask** | `prepare.py` / `sp_open_review.py` | ✅ 已落地；仅用于来源已有明确事实 |
| **open 摘要每次弹** | `sp_open_review.py:181` | ⚠️ 无条件弹，本次优化为 resume 不弹 |
| FileRegistry 文件锁 | `registry.py:put` | ❌ 原子写但无进程锁，阶段 A 单写者约束 |
| Snapshot `latest_verified` 自动选 | `snapshots.py` | ✅ `snapshot build-request` 生成草稿；`snapshot create` 仍要求唯一 active label 或显式 `label_id` |

## 1. 本次已做的实质优化

| 问题簇 | 本次处理 |
| --- | --- |
| 预创建所有目标 Mask（含已知缺失器官）造成标注者困扰 | 新增 `known_absent`：request/manifest 的 target 可声明已知缺失器官，prepare 不为其生成 Mask，open 不创建，submit/finalize 不检查也不为其生成 segment。见第 4 节 Q20。 |
| resume 同一病例反复弹任务摘要 | `sp_open_review.py` 改为 resume 模式不弹摘要（new 模式仍弹，作首次核对）；主动查看已有 Task List。见 Q11/Q12。 |
| 文档把 NIfTI 进入 Mimics 列为"不做" | 修正 `mimics_feasibility.md` 与本文件：保留"原生 NIfTI scripting API 未证实"的调研事实，但把"任意格式进入标注流程"提升为既定目标。当前代码已在病例包创建阶段为 Mimics review 生成派生 DICOM，并用 `dicom_sha256` 单独校验；仍需 Windows Mimics 21 实机验证导入方向、灰度和 Mask 往返。见 Q17–Q19。 |

扫描多格式、批量命令、Task List、目标组 toggle 等在上一轮已落地，本次仅核对确认，未重复改动。

## 2. 逐问题回应

### Q1–Q3　扫描范围、标准与初始标签扫入

| 问题 | 我的判断 | 状态 |
| --- | --- | --- |
| 扫描只支持 DICOM 目录吗？其他格式？缺分组信息怎么办？ | 现在不只 DICOM。`scan_source` 已发现 NIfTI/MetaImage（按文件、按父目录归 Case）。DICOM 仍按 `PatientID×StudyUID×SeriesUID` 分组；非 DICOM 没有这些头，靠父目录做保守分组，`leakage_group_confidence=low`。RAW 无 sidecar 不猜，记 `skipped`。 | ✅ 已改代码 |
| scan 适应不了所有数据集，要否沉淀标准/规则提前整理？ | 要，但分两层：标准 DICOM 自动分组；复杂/非标准布局走显式 `dataset_description.yaml`，由 `sp ingest from-description` 生成请求，不让 scan 猜医学语义。 | ✅ 已补基础引擎 |
| scan 时初始 Label Artifact 怎么扫入？ | scan 不扫标签。标签语义必须由 request 的 `initial_labels` 显式给出（`organ` 或 `label_map`）。文件名和像素值不能可靠表达器官含义，自动猜标签会造成更大错误。 | ✅ 设计如此 |

### Q4–Q6　目录结构、标签发现、值→器官映射

| 问题 | 我的判断 | 状态 |
| --- | --- | --- |
| scan 前应整理成什么结构？ | DICOM 不必整理成单 Series 目录，scan 按头拆分。NIfTI/MHD 建议按 `case/study/image` 目录整理，同一父目录默认归同一 Case（与代码 `_case_seed_for_file` 一致）。复杂情况必须人工审阅/修改 request。 | ✅ 已改文档 |
| 初始 mask 可能和图像混放或独立路径，每数据集规则不同，没考虑这个设计？ | scan 仍不自动猜标签，但现在增加 `dataset_description`：用正则或 CSV 显式描述标签在哪、怎样匹配 image、值怎样映射器官，再生成带 `initial_labels` 的 request。 | ✅ 已补基础引擎 |
| 拆逐器官 NIfTI的逻辑？怎么知道每个值对应哪个器官？ | 单器官 mask 校验只含 0/1；多标签 mask 按 `label_map` 逐值拆，且 `label_map` 必须覆盖 array 中所有非零值，否则阻断。**值→器官的语义代码不知道，也不应知道**——由人或 adapter 在 `label_map` 里显式给出。`vocabulary.py` 只做名称规范化，不做语义推理。 | ✅ 已有代码 |

### Q7　三步设计的意义与"隐形步骤"

三步（scan → build-requests → package create）的本质是**把数据集的多样性消灭在边界**：scan 回答"有什么图像可读"，build-requests 回答"要标什么"，package create 执行校验和登记。多样性在前两步和它们之间被消化掉，第三步只剩标准操作。

用户点出的"隐形关键步骤"确实存在且必须明说：**build-requests 只填目标器官列表（`--organs`），`initial_labels` 留空；在 `package create` 之前，人或 import adapter 要把数据集特有的标签路径和值→器官映射填进 request YAML。** 这一步当前完全交给外部（`initial_labels: []` 硬编码）。结论：保持"build-requests 只生成模板"的定位，但在文档里把这条隐形步骤显式化，避免给人"scan 能搞定一切"的错觉。

### Q8–Q9　import adapter 的契约，以及它是否是最佳方式

Q8：adapter 没有目标和指导手册。Q9：输入端 adapter 是不是多来源数据集的最佳方式。

我的判断：

1. **adapter 是对的，但粒度要切对。** 按"每个数据集写一个完整 adapter 脚本"大概率不是最优——80% 代码在重复构造 request YAML，真正每个数据集不同的只有"标签在哪 + 值怎么映射"。
2. **更优的抽象是"声明式数据集描述 + 通用引擎"，而非每数据集一份脚本。** 一份 `dataset_description.yaml`（图像来源 pattern/grouping + 标签来源 path/index + 标签映射 label_map/文件名约定 + 标注目标 + 治理），由 `sp ingest from-description` 转成一组 `case_package_request.v1`。
3. **最佳是混合模式**：数据集太特殊、参数化表达不了时，adapter 只做"理解这个数据集 → 输出 `dataset_description.yaml`"，再交给通用引擎。adapter 不直接拼 YAML、不碰 Registry，边界清晰。
4. **当前仍不急着建 `adapters/import/` 目录。** 阶段 A 先用 `dataset_description` 覆盖常见规则；只有当某个数据集无法用正则/CSV 描述时，再写专用 adapter，且 adapter 的输出仍应是 `dataset_description.yaml` 或标准 request。

这与原回复一致，且与"简单优先"准则吻合：不为还没出现的需求搭通用框架。

### Q10　prepare 做什么；平台运行 vs 标注者运行

prepare 把不可变病例包翻译成 Mimics 可直接打开的工作目录：再校验病例包 → 读工作站 buffer_mapping → 把逐器官 NIfTI mask 转成 `.u8`（按 P05 校准的轴映射）→ 恢复 checkpoint buffer → 生成 `mimics_runtime.json` → 写 buffer manifest。**首次 DICOM 导入仍发生在 Mimics 内 `open`，不在 prepare。**

平台/admin 负责 scan、package、prepare-many、finalize-many、stats；标注者只在 Mimics 内运行 Start Labeling，从不直接运行 prepare。`sp_review_console.open_review` 会在后台按需调用 prepare。✅ 已实现。

### Q11–Q12　每次弹摘要 / 频繁弹窗是消耗

原回复确认 `sp_open_review.py` 的 `message_box` 无条件弹（new 和 resume 都弹）。我的判断：

- **new 模式弹摘要有信息量**——标注者核对"病例对不对、要标几个器官"，是必要的确认步骤。
- **resume 模式弹摘要是纯摩擦**——续标同一个已打开过的病例，标注者已经知道任务范围；反复打开关闭同一病例时，每次都点 OK 是肌肉记忆负担。

本次优化：**resume 模式（`mode==resume` 且 `.mcs` 存在）不再弹摘要；new 模式仍弹。** 标注者遗忘时用 Start Labeling 的 Task List 主动重看。这比"全部关掉"安全——首次打开的核对手续保留。

更彻底的"批量模式跳过流程性确认"（`workflow_mode: batch`、`Submit & Open Next`）方向正确，但涉及多个对话框联动且需实机验证标注者体验，列为后续，不在本次硬塞。

### Q13　Save Recovery Backup vs Submit；四种提交动作；目标组组合

| 概念 | 结论 |
| --- | --- |
| Save Recovery Backup | 灾备快照，gzip 写 `working/checkpoints/`，不创建 Label、不触发 QC，可被 prepare 恢复 |
| Complete / Needs Review / Report Problem | 从 Start Labeling 直接选择业务结果，导出选定目标组 buffer 或记录阻塞原因；finalize 通过后才生成 Label |
| Complete | 声明全部标完且准确；finalize 全 QC → `verified_label`；不能有 `uncertain` 空 Mask |
| Needs Review | 标了但不确定；→ `draft_label`，状态 `needs_review`，不能直接进训练 Snapshot |
| Report Problem | 无法标注；不导出、不创建标签、不做 preflight；状态 `blocked` + reason_code |
| Cancel | 什么都不做 |
| 2–5 目标组 toggle | 一个 Review 可有多个 target（如静脉期腹部器官、动脉期血管各一组），可勾选任意组合一次提交；>5 回退列表选择；==1 跳过选择 |

✅ 均已实现，代码与原回复描述一致。

### Q14–Q16　耗时、逐病例导入慢、NIfTI 慢吗

| 步骤 | 典型耗时 | 谁等 |
| --- | --- | --- |
| 首次 DICOM 导入（new） | 1–5 分钟 | 标注者，且无平台可控加速 |
| 打开 .mcs（resume） | 10–30 秒 | 标注者 |
| Save Recovery Backup（4 器官） | 45–90 秒 | 标注者主动触发 |
| Submit（4 器官） | 30–60 秒 | 标注者主动触发 |

瓶颈本质都是全量体素读写，没有 O(n²)。**真正的痛点是"每打开一个新病例都要再等一次 DICOM 导入"——线性累加。** Mimics 的 `import_dicom_images` 是它自己的 API，平台无法绕过其内部解析。NIfTI 当前不是"慢"，而是**在 Mimics 路径直接被阻断**（prepare.py:124）。

这组问题的解不在"让单次导入更快"，而在"把导入从标注者在场时移走"——见 Q17–Q19。

### Q17–Q19　NIfTI 必须支持、别死板依赖 API、prepare 预导入

**这是与原回复/feasibility 分歧最大的一组，也是用户态度最明确的一组。** 用户原话："支持 Mimics 的 NIfTI 等其他常用医学图像格式的导入 API 是必须实现的，这个没有商量的余地"，以及"导入为什么要完全依赖本身的导入 api 呢……你能不能不要那么的死板"。

原回复在 Q19 之后其实已经想通了正确架构，但 `mimics_feasibility.md` 和上一版 resolution 仍把它列为"不做（Mimics 21 API 证据不足）"。**这是退缩，本文纠正。**

我的判断：

1. **区分两件事。** "Mimics 21 是否有原生 NIfTI scripting API"——未证实，feasibility 的调研可信，保留。"'NIfTI 数据能否进入标注流程'"——用户诉求，可实现，且必须实现。原回复把前者未证实当成了后者不可行，这是偷换。
2. **不依赖原生 NIfTI API 的实现路径**（代码链路已实现，实机验证仍需要）：
   - 平台侧现代 Python（nibabel/pydicom/SimpleITK）把任意格式读成 3D array；
   - 用 pydicom 写出一个最小可用 DICOM 序列（十几个必需 tag 即可，这是 Mimics `import_dicom_images` 本就接受的输入，不是破解）；
   - **在 prepare 阶段用 Mimics `-background_mode` 启动预生成流程**，完成 import + 创建所有目标 Mask + 注入初始 buffer + `save_project(.mcs)`，然后退出；
   - 标注者打开时只剩 `open_project(.mcs)`（10–30 秒），**永远不等任何格式的导入**。
3. **`-background_mode` 不是新东西**，探针代码（`probes/`）已经用过；现在已经接到正式 CLI：`sp mimics prebuild-workspace` 和 `sp mimics prebuild-many`。
4. **前置条件仍是 Mimics Gate 验证**：background mode 下能否无 UI 运行 `import_dicom_images` + `create_mask` + `set_voxel_buffer` + `save_project`，必须在 Windows Mimics 21 实机上证明。
5. **本次代码处理**：`prepare.py` 生成 `mimics_runtime.json` 和 import buffers；`launcher.py` 用 `-background_mode` 调用 `sp_open_review.py --background-prebuild`；成功后写入 `working/prebuilt_workspace.json`。再次批量 prebuild 时，已有预生成 `.mcs` 会跳过；已有普通 `.mcs` 也会跳过，避免后台覆盖标注者工作，只有 `--rebuild-workspace` 才重建。

**结论：从"不做"改为"既定目标，路径已定，前置 Mimics Gate 验证"。** 这是对用户"没有商量余地"的正面回应。

### Q19（子问题）初始分割导入与无初标器官

已实现：Open 时为每个 target organ 创建 Mask；有初始标签则注入 buffer，无初始标签则建空 Mask，标注者不用手工建 Mask。✅

但"无初标就建空 Mask"和 Q20 的"预创建所有 Mask"是同一处代码。Q20 的结论会修正这里的"每个 target organ 都建"。

### Q20　预创建所有目标 Mask 不合理

用户原话："每个目标器官都预先创建了 Mask 我觉得是不不合理，因为这是默认了每套数据都有对应的器官……这会造成困扰。"

我的判断：**用户对。** "标注目标"（这批要处理什么）和"解剖存在"（这个病人有没有）是两回事，原代码把它们混在一起，把存在性判断的负担转嫁给标注者（每个空 Mask 都要确认 absent）。

上一版 resolution 说"保留预创建，known_absent 列为后续"。**这是退缩，本次落地纠正：**

- request/manifest 的 target 增加 `known_absent: [organ, ...]`（`organs` 的子集，声明该病例已知缺失的器官）；
- prepare 不为 `known_absent` 器官生成 Mask 条目，checkpoint 校验的 `expected_keys` 也跳过它们；
- sp_open_review 因基于 `target["masks"]` 列表，天然不创建这些 Mask（无需改）；
- sp_submit_review 的 preflight 和 organ_outcomes 同样基于 `masks` 列表，天然跳过（无需改）；
- finalize 两处 `for organ in target["organs"]` 跳过 `known_absent`，不为它们报 `missing_mask`、不写 segment。

**谁填 `known_absent`？** 准备者在 request 阶段填（"一人准备"场景里，准备者掌握临床信息时）。不知道就不填，标注者仍可能遇到空 Mask，用提交时的 outcome `confirmed_absent` 处理——这是另一条既有路径，不变。`known_absent` 是可选优化，不强制。

注意命名：用 `known_absent`（target 级，预先声明、不建 Mask）而非 `confirmed_absent`（后者是提交时 organ_outcome 的值，标注者对空 Mask 的确认，语义不同，不能混用）。

### Q21　Start Labeling 是否常驻

非常驻。它是 Mimics Scripting Library 下的瞬态动作入口：弹对话框 → 执行 → 脚本结束 → 回到纯 Mimics 界面。Mimics 21 Scripting API 不提供非阻塞 UI 组件（无侧边栏/浮动条/持久状态栏），常驻面板成本高且依赖未证实的 API。当前用 **Task List**（主动重看目标清单）替代常驻提醒。✅ 已实现。

### Q22　规模化运营：分发、合并、少阻塞

已有：批量 scan/build-requests/create-many/prepare-many/finalize-many/review stats/next(start)/Registry label index/leakage 校验。

仍需注意：

| 缺失 | 影响 | 处理 |
| --- | --- | --- |
| FileRegistry 无锁 | 多进程/多机并发写同 Registry 可能竞态 | 阶段 A 单写者约束；阶段 B 加 lockfile 或迁 SQLite |
| 无集中仪表盘 | 管理员靠 `review stats` 文本 | 阶段 A 够用 |
| finalize 同步 | `auto_finalize=true` 时标注者多等 30–60 秒 | 默认 `auto_finalize=false`，中央批量 finalize |
| 无标注者负载均衡 | next_review 只按时间 FIFO | 阶段 A 不需要（见 Q23） |

最大瓶颈是批量 prepare 时的 Mimics 许可数（决定 background_mode 并发数），其次才是文件式 Registry。

### Q23　多标注者只标不同病例、一人准备、各自本机

用户明确了最简场景：不对比、不仲裁、不合并；一人扫描注册，标注者各自本机标注。这把 Q22 里"仲裁/合并工具""负载均衡"都取消了——不需要。

这个场景下真正缺的是**传输胶水**：

| 能力 | 现状 | 需要 |
| --- | --- | --- |
| 中央机批量扫描+注册 | ✅ | — |
| 病例包按标注者拆分下发 | ✅ | `sp review export-worklist` 或共享盘 |
| 标注者读取队列 | ✅ | 共享盘 Registry 或导出的本地轻量 Registry |
| 标注者查询自己队列 | ✅ `next_review(assignee=...)` | — |
| 提交产出收回中央 | ✅ | `sp mimics collect-submissions` 后中央 `finalize-many` |

两条路线：
- **共享网络盘（推荐，最简）**：Registry 和病例包放共享盘，中央写、标注者只读查询 + 各自写自己的 submissions 子目录，中央跑 `finalize-many`。冲突面极小（只有 `mark_review_started` 更新 review 状态），阶段 A 可接受无锁。
- **离线拷贝（无共享盘）**：`sp review export-worklist` 把分配给某标注者的病例包 + 轻量 Registry 打包；标注者本地标注后用 `sp mimics collect-submissions` 收回中央病例包，再由中央 `finalize-many` 追加标签记录。

`build-requests` 已支持 `--assignee`，可按标注者分批生成请求。✅

新增病例进入已有本地队列时，用 `sp review export-worklist --merge`，不要覆盖标注者本地工作包。只想先给 N 例时用 `--limit N`。标注者在 Mimics 中暂时跳过病例时使用 **Skip Case**，review 进入 `deferred`；管理员可用 `sp review reactivate` 放回队列。

标注中追加器官或返修时，用 `sp review create-followup`。它创建新的 review package，引用当前 active label 作为 base；Finalize complete 后新 Label Artifact carry-forward 未重标器官，并把旧 base 标记为 `superseded`。这样不会删除旧 `submissions/`、`reports/` 或历史 label 文件。

## 3. 与原回复/feasibility 的关键分歧（纠正）

| 原结论 | 为何退缩 | 我的纠正 |
| --- | --- | --- |
| NIfTI 进入 Mimics"不做"（API 证据不足） | 把"原生 NIfTI scripting API 未证实"等同于"NIfTI 不能进入标注流程" | 用户诉求是后者。当前路径=病例包创建阶段外部转最小 DICOM，prepare 使用 `dicom_path`，不依赖原生 API。仍需 Mimics Gate 验证。 |
| 保留预创建所有目标 Mask，known_absent 列后续 | 担心取消预创建要新增"目标清单与 Mask 创建状态"机制 | 用 `known_absent` 在 target 级声明，链路基于既有 `masks` 列表自洽，无需新机制。本次落地。 |
| 导入必须走 Mimics `import_dicom_images` API | 默认"打开流程必经导入" | 用 `-background_mode` 把导入提前到 prepare（标注者不在场），打开只剩 `open_project`。思路已在探针验证过。 |

其余原回复的判断（scan 不自动猜标签、不每个数据集写 adapter、prepare 不暴露给标注者、单 .mcs 单病例、阶段 A 不上数据库）我都认同，保留。

## 4. 当前仍不做的事

| 不做 | 原因 | 替代 |
| --- | --- | --- |
| 一个 `.mcs` 多病例 | 放大误绑定、损坏恢复、部分提交、多人分派风险 | 一 review/case 一个 `.mcs`；批量 prepare/finalize + 队列领取降摩擦；预导入消除逐病例等待 |
| Mimics 原生 NIfTI API 作为前提 | 未证实 | 病例包创建阶段转派生 DICOM；background mode 预生成 `.mcs` 已接入代码，仍需实机验证（见 Q17–Q19） |
| scan 自动识别标签语义 | 文件名/像素值不可靠 | request 的 `initial_labels` 显式声明 |
| 常驻 Mimics 任务面板 | 需未证实 API 且干扰视野 | Task List |
| 阶段 A 引入数据库/权限/锁 | 离线闭环复杂化 | 文件式 Registry + 标签索引 + 单写者；阶段 B/E 升级 |
| 自动仲裁/合并多标注者标签 | 用户明确不需要（只标不同病例） | 不做 |
| 跨病例包图像去重 | 会改变病例包自包含假设和 Windows 迁移方式 | 阶段 A 先接受复制；数据量成为瓶颈后再引入 content-addressed image store 或硬链接模式 |

## 5. 开发者后续优先级

1. **Windows Mimics 21 实机 Gate**：验证 background mode 下 `import_dicom_images` + `create_mask` + `set_voxel_buffer` + `save_project` 可无 UI 串行完成。这是把预生成 `.mcs` 批量交给标注者前的硬前置。
2. **预生成 `.mcs` 实机验收**：在真实病例包上运行 `sp mimics prebuild-workspace` 和 `sp mimics prebuild-many`，确认生成 `working/prebuilt_workspace.json`、`reports/mimics_prebuild.log`、`reports/mimics_open_report.json`，并确认标注者首次 Start Labeling 只打开 `.mcs`。
3. **Registry 写锁或轻量数据库**：多工作站并发 finalize 成为常态时再做（Q22）。
4. **Snapshot build-request 继续增强**：支持更复杂的 split 规则、抽样和任务模板复用。
