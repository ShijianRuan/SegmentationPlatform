-- Create Keynote presentation for Segmentation Platform Architecture
-- Run: osascript create_ppt.applescript

tell application "Keynote"
  activate
  
  -- Check if a document is already open, if not create one
  set targetDoc to missing value
  try
    set targetDoc to front document
  on error
    set targetDoc to missing value
  end try
  
  if targetDoc is missing value then
    set targetDoc to make new document with properties {document theme:theme "White"}
  end if
  
  tell targetDoc
    -- Use White theme for clean start
    
    -- ============================================================
    -- Slide 1: Title
    -- ============================================================
    set slide1 to make new slide with properties {base slide:master slide "Title & Subtitle"}
    tell slide1
      set titleText to "医学图像分割平台架构设计"
      set bodyText to "Segmentation Platform Architecture Design" & return & "2026-06-07"
    end tell
    
    -- ============================================================
    -- Slide 2: Core Positioning
    -- ============================================================
    set slide2 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide2
      set titleText to "平台核心定位"
      set bodyText to "平台中心不是某个训练框架或标注软件" & return & ¬
        "平台中心 = 病例、图像、标签、训练任务、模型版本之间的关系" & return & ¬
        "标注、训练、伪标签、离线推理都围绕这些关系发生"
    end tell
    
    -- ============================================================
    -- Slide 3: Three Domains
    -- ============================================================
    set slide3 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide3
      set titleText to "三大实现域"
      set bodyText to "labeling（标注域）— 标签生产与安全导回" & return & ¬
        "　→ Case Package / Mimics 修正 / 几何校验 / verified_label" & return & ¬
        "training（训练域）— 任务消费标签产出模型" & return & ¬
        "　→ TaskLabelMap / Dataset Snapshot / nnUNet Adapter / Model Record" & return & ¬
        "label_generation（标签生成域）— 候选标签生成与回流治理" & return & ¬
        "　→ candidate_label / accepted_pseudo_label / QC / 回流"
    end tell
    
    -- ============================================================
    -- Slide 4: Closed Loop
    -- ============================================================
    set slide4 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide4
      set titleText to "闭环流程"
      set bodyText to "病例数据 → 标签来源（人工 / 模型 / 公开算法）" & return & ¬
        "　↓" & return & ¬
        "标注审核（labeling 域）" & return & ¬
        "　↓" & return & ¬
        "数据集快照（Dataset Snapshot）" & return & ¬
        "　↓" & return & ¬
        "训练 → 模型（training 域）" & return & ¬
        "　↓" & return & ¬
        "离线批量推理" & return & ¬
        "　↓" & return & ¬
        "候选标签 → 回流到标签来源（label_generation 域）"
    end tell
    
    -- ============================================================
    -- Slide 5: Six Label States
    -- ============================================================
    set slide5 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide5
      set titleText to "六种标签状态"
      set bodyText to "source_label → verified_label（可信源直接确认）" & return & ¬
        "candidate_label → draft_label → 人工修正 → verified_label" & return & ¬
        "candidate_label →（QC 通过）→ accepted_pseudo_label" & return & ¬
        "candidate_label →（QC 失败）→ rejected_label" & return & ¬
        "" & return & ¬
        "设计原则：不强迫人在流程中被跳过，但允许高质量伪标签绕开人工" & return & ¬
        "candidate_label 可通过 allow_status 直接纳入训练（provenance 永不造假）"
    end tell
    
    -- ============================================================
    -- Slide 6: 3-Layer Label Map
    -- ============================================================
    set slide6 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide6
      set titleText to "三层 Label Map 设计"
      set bodyText to "anatomy_vocabulary — 这是什么器官？" & return & ¬
        "　语义层，纯名称，无数字。liver = 肝脏" & return & ¬
        "" & return & ¬
        "review_label_map — 工具里是几号？" & return & ¬
        "　标注工具层，受软件限制。liver = 10（Mimics）" & return & ¬
        "" & return & ¬
        "task_label_maps — 训练时是几号？" & return & ¬
        "　训练框架层，nnUNet 要求连续整数。liver = 2（CT5_Liver）" & return & ¬
        "" & return & ¬
        "核心：同一 liver，review=10，训练=2，展示=37 — 不是冲突，是层级分工"
    end tell
    
    -- ============================================================
    -- Slide 7: Case Package
    -- ============================================================
    set slide7 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide7
      set titleText to "Case Package 契约"
      set bodyText to "目录结构：" & return & ¬
        "├── manifest.json（sha256 / shape / spacing）" & return & ¬
        "├── images/image.nii.gz" & return & ¬
        "├── labels/{draft,verified}_label.nii.gz + masks/" & return & ¬
        "├── config/{anatomy_vocabulary, review_label_map}.yaml" & return & ¬
        "├── reports/{geometry_check, review_report}.json" & return & ¬
        "└── provenance/{source_labels, tool_export}.json" & return & ¬
        "" & return & ¬
        "一个病例一个包，自包含可搬运" & return & ¬
        "nnUNet 不直接读 Case Package → 经 Data Registry + Snapshot 导出"
    end tell
    
    -- ============================================================
    -- Slide 8: nnUNet Pipeline
    -- ============================================================
    set slide8 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide8
      set titleText to "训练管线 — nnUNet 五阶段"
      set bodyText to "Config.toml + ModelMap.toml → AutoSegmentationFramework（编排器）" & return & ¬
        "" & return & ¬
        "Action1 数据转换 — 标注数据 → nnUNet 格式，重采样 + 合并" & return & ¬
        "Action2 预处理 — 指纹提取 + 实验规划，支持手动覆盖参数" & return & ¬
        "Action3 训练 — GPU 管理，5 折交叉，DDP 多卡" & return & ¬
        "Action4 推理 — 预插值加速，多模型共享分辨率" & return & ¬
        "Action5 评估 — Dice + Surface Dice，多格式报告 + 聚合" & return & ¬
        "" & return & ¬
        "ModelMap.toml 已是 TaskLabelMap 雏形 — 每模型独立从 1 编号"
    end tell
    
    -- ============================================================
    -- Slide 9: Adapter Architecture
    -- ============================================================
    set slide9 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide9
      set titleText to "Adapter 架构 — 可扩展性核心"
      set bodyText to "Dataset Snapshot（冻结的数据视图）" & return & ¬
        "　├── nnUNet Adapter（全监督，已完成）→ Model Record" & return & ¬
        "　├── FewShot Adapter（少样本，架构已定）→ Model Record" & return & ¬
        "　├── MONAI Adapter（Transformer，预留）→ Model Record" & return & ¬
        "　└── 其他 Adapter（SAM / 新框架，可扩展）→ Model Record" & return & ¬
        "" & return & ¬
        "不变层（数据契约）：Case / Image / Label / Snapshot / label_policy" & return & ¬
        "可变层（Adapter 封装）：nnUNet / MONAI / FewShot / SAM" & return & ¬
        "新框架 = 新 Adapter，不动数据契约。USB 协议：设备可换，接口不变"
    end tell
    
    -- ============================================================
    -- Slide 10: FewShot Learning
    -- ============================================================
    set slide10 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide10
      set titleText to "少样本学习 — FewShot Adapter"
      set bodyText to "架构定位：training 域 Adapter，与 nnUNet 平级" & return & ¬
        "" & return & ¬
        "生产级实验协议：" & return & ¬
        "1. 选定器官 → verified 病例 → 患者级别冻结划分" & return & ¬
        "2. N-shot Snapshot（N=1/3/5/10/20）" & return & ¬
        "3. 三对照组：全监督上界 / 同数据量基线 / 微调实验组" & return & ¬
        "4. 冻结测试集计算 Dice, Surface Dice, Hausdorff" & return & ¬
        "5. 登记 Model Registry → 达准入标准 → 升级为 Adapter" & return & ¬
        "" & return & ¬
        "准入标准：≥3 次复现 / Dice ≥ 全监督 90% / 跨扫描协议 ≤0.05 / 失败率 <5%"
    end tell
    
    -- ============================================================
    -- Slide 11: Mimics Integration
    -- ============================================================
    set slide11 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide11
      set titleText to "Mimics 集成方案"
      set bodyText to "流程：平台 split/merge → Case Package → Mimics 导入 → 人工修正 → Mimics 导出 → 校验" & return & ¬
        "" & return & ¬
        "关键 API（已确认存在）：" & return & ¬
        "　mimics.data.masks.find(name=...) — 查找 Mask" & return & ¬
        "　mask.get_voxel_buffer() — 获取体素（numpy 数组）" & return & ¬
        "　mask.set_voxel_buffer(arr) — 导入外部 numpy 数组" & return & ¬
        "　NIfTI 导入导出（2025 GUI 原生支持）" & return & ¬
        "　Help → Scripting Guide — 完整 API 文档，内置在软件中" & return & ¬
        "" & return & ¬
        "风险：空间对齐需实测 / API 不足可 GUI 补偿 / 最坏切换 3D Slicer"
    end tell
    
    -- ============================================================
    -- Slide 12: Implementation Phases
    -- ============================================================
    set slide12 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide12
      set titleText to "分阶段实施路线"
      set bodyText to "A. 文件包闭环 👈 当前" & return & ¬
        "　　一个病例从候选标签到人工保存，再进入训练快照" & return & ¬
        "" & return & ¬
        "B. 注册中心 + 快照（设计已定）" & return & ¬
        "　　Data Registry + Dataset Snapshot，多任务复用，训练可复现" & return & ¬
        "" & return & ¬
        "C. Adapter 稳定（设计已定）" & return & ¬
        "　　nnUNet Adapter 跑通，预留 MONAI / FewShot 接口" & return & ¬
        "" & return & ¬
        "D. 离线批量推理（后期）" & return & ¬
        "　　模型版本 + 批量任务 + candidate_label 回流" & return & ¬
        "" & return & ¬
        "E. 统一调度（后期）" & return & ¬
        "　　Web UI、任务队列、权限、审计"
    end tell
    
    -- ============================================================
    -- Slide 13: Key Decisions
    -- ============================================================
    set slide13 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide13
      set titleText to "已确认的关键决策"
      set bodyText to "伪标签准入 — 默认允许，取决于器官/任务/模型" & return & ¬
        "器官范围 — v500 全部模型（CT1-16、MR1-8），全身覆盖" & return & ¬
        "全身模型 — 保持多模型组合，后期再实验统一模型" & return & ¬
        "Mimics POC — 先调研准备，确认 API 后再启动" & return & ¬
        "少样本学习 — training 域新 Adapter，需先过实验协议" & return & ¬
        "label_policy — candidate_label 可直入训练，provenance 不造假" & return & ¬
        "Data Registry — 先不实现但必记，闭环跑通后补"
    end tell
    
    -- ============================================================
    -- Slide 14: Checklist
    -- ============================================================
    set slide14 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide14
      set titleText to "实现前待确认清单"
      set bodyText to "阻塞项（必须确认）：" & return & ¬
        "　A1. Mimics 版本 + 许可证类型" & return & ¬
        "　A2. Scripting Guide 中 mask API 清单" & return & ¬
        "　A3. Mimics 能否运行 Python 脚本" & return & ¬
        "　A4. 第一批 3-5 个病例" & return & ¬
        "　A5. 训练服务器环境（GPU、路径）" & return & ¬
        "" & return & ¬
        "非阻塞项（可立即实现）：" & return & ¬
        "　B1-B4 平台脚本（split/merge/geometry/package）" & return & ¬
        "　B5-B6 Mimics Adapter（import/export）" & return & ¬
        "" & return & ¬
        "后置项（不阻塞闭环）：" & return & ¬
        "　Data Registry / Dataset Snapshot / Adapter 接口 / FewShot"
    end tell
    
    -- ============================================================
    -- Slide 15: Time Estimate
    -- ============================================================
    set slide15 to make new slide with properties {base slide:master slide "Title & Bullets"}
    tell slide15
      set titleText to "时间估算"
      set bodyText to "平台脚本（B1-B4）：4-5 天（信心高）" & return & ¬
        "Mimics Adapter（B5-B6）：乐观 2 天 / 悲观 2 周（依赖 A1-A3）" & return & ¬
        "闭环测试 + 调试：1-2 周" & return & ¬
        "3-5 病例验证：1 周" & return & ¬
        "" & return & ¬
        "一切顺利：3-4 周" & return & ¬
        "正常（1-2 个弯路）：5-6 周" & return & ¬
        "Mimics API 受限：额外 +2-3 周（切换 3D Slicer）" & return & ¬
        "" & return & ¬
        "最大减速带：Mimics 确认和几何对齐调试，不是代码量"
    end tell
    
  end tell
  
  return "Done: " & (count of slides of front document) & " slides created"
end tell
