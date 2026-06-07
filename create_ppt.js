const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "ShijianRuan";
pres.title = "Segmentation Platform Architecture";

// Color palette
const C = {
  bg:       "0F172A",
  card:     "1E293B",
  white:    "FFFFFF",
  teal:     "2DD4BF",
  blue:     "38BDF8",
  green:    "4ADE80",
  amber:    "FBBF24",
  red:      "F87171",
  text:     "F8FAFC",
  sub:      "94A3B8",
  muted:    "64748B",
  lightBg:  "F1F5F9",
  dkText:   "0F172A",
  dkSub:    "475569",
  border:   "CBD5E1",
  tBlue:    "0284C7",
  tGreen:   "059669",
  tAmber:   "D97706",
  tableBg:  "F8FAFC",
};
const F = { title: "Arial", body: "Arial", mono: "Courier New" };

// Helpers
function slideTitle(s, text) {
  s.addText(text, { x: 0.6, y: 0.25, w: 8.8, h: 0.55, fontSize: 26, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.82, w: 1.0, h: 0.04, fill: { color: C.tBlue } });
}

function card(s, x, y, w, h, title, body, accent) {
  const fill = C.white;
  s.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fill }, shadow: { type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.08 } });
  s.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color: accent } });
  s.addText(title, { x: x + 0.2, y: y + 0.12, w: w - 0.3, h: 0.3, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  if (body) {
    s.addText(body, { x: x + 0.2, y: y + 0.48, w: w - 0.3, h: h - 0.56, fontSize: 10, fontFace: F.body, color: C.dkSub, margin: 0, valign: "top" });
  }
}

function row(s, y, label, desc, color) {
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y, w: 0.06, h: 0.4, fill: { color } });
  s.addText(label, { x: 0.7, y, w: 2.3, h: 0.4, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, valign: "middle", margin: 0 });
  s.addText(desc, { x: 3.1, y, w: 6.5, h: 0.4, fontSize: 10, fontFace: F.body, color: C.dkSub, valign: "middle", margin: 0 });
}

function tableHeader(fill) {
  return { bold: true, fill: { color: fill || C.dkText }, color: C.white, fontSize: 10, fontFace: F.body };
}

// ============================================================
// S1: Title
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("医学图像分割平台架构设计", { x: 0.8, y: 1.3, w: 8.4, h: 0.8, fontSize: 38, fontFace: F.title, bold: true, color: C.white, align: "center", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 3.8, y: 2.2, w: 2.4, h: 0.04, fill: { color: C.teal } });
  s.addText("Segmentation Platform Architecture", { x: 0.8, y: 2.45, w: 8.4, h: 0.5, fontSize: 16, fontFace: F.title, color: C.sub, align: "center", margin: 0 });
  s.addText("2026-06-07", { x: 0.8, y: 4.5, w: 8.4, h: 0.35, fontSize: 13, fontFace: F.body, color: C.muted, align: "center", margin: 0 });
})();

// ============================================================
// S2: Core Positioning — clean central node diagram
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "平台核心定位");

  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 3.9, w: 9.2, h: 1.25, fill: { color: C.tableBg } });
  s.addText([
    { text: "平台中心 ≠ 某个训练框架或标注软件", options: { bold: true, breakLine: true, fontSize: 14 } },
    { text: "平台中心 = 病例、图像、标签、训练任务、模型版本之间的关系", options: { fontSize: 13, breakLine: true } },
    { text: "标注、训练、伪标签、离线推理都围绕这些关系发生", options: { fontSize: 11, color: C.dkSub } },
  ], { x: 0.7, y: 4.05, w: 8.6, h: 0.95, margin: 0, valign: "top" });

  // 5-node visual: 5 columns
  const nodes = [
    { label: "病例\nCase", x: 0.3 },
    { label: "图像\nImage", x: 2.15 },
    { label: "标签\nLabel", x: 4.0 },
    { label: "训练任务\nTask", x: 5.85 },
    { label: "模型版本\nModel", x: 7.7 },
  ];
  const nw = 1.7, nh = 1.5;
  nodes.forEach((n, i) => {
    const y = 1.4;
    s.addShape(pres.shapes.RECTANGLE, { x: n.x, y, w: nw, h: nh, fill: { color: C.white }, shadow: { type: "outer", blur: 6, offset: 2, angle: 135, color: "000000", opacity: 0.08 }, line: { color: C.border, width: 0.5 } });
    s.addText(n.label, { x: n.x, y, w: nw, h: nh, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
    if (i < nodes.length - 1) {
      s.addText("⟷", { x: n.x + nw - 0.15, y: y + 0.5, w: 0.8, h: 0.5, fontSize: 20, fontFace: F.body, color: C.tBlue, align: "center", valign: "middle", margin: 0 });
    }
  });

  // Arrow shapes between nodes
  s.addShape(pres.shapes.LINE, { x: 2.0, y: 2.88, w: 0.3, h: 0, line: { color: C.tBlue, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: 3.85, y: 2.88, w: 0.3, h: 0, line: { color: C.tBlue, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: 5.7, y: 2.88, w: 0.3, h: 0, line: { color: C.tBlue, width: 1.5 } });
  s.addShape(pres.shapes.LINE, { x: 7.55, y: 2.88, w: 0.3, h: 0, line: { color: C.tBlue, width: 1.5 } });
})();

// ============================================================
// S3: Three Domains — 3 cards
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "三大实现域");

  const domains = [
    { title: "labeling  标注域", sub: "标签生产与导回", items: "导出 Case Package\nMimics 修正 + 保存\n几何校验\n注册 verified_label", color: C.tBlue, x: 0.3 },
    { title: "training  训练域", sub: "任务消费标签 → 模型", items: "TaskLabelMap\nDataset Snapshot\nnnUNet Adapter\nModel Record", color: C.tGreen, x: 3.55 },
    { title: "label_generation  标签生成域", sub: "候选标签生成与回流治理", items: "公开算法 / 自训模型推理\ncandidate_label\nQC + 准入策略\n回流到标注或训练", color: C.tAmber, x: 6.8 },
  ];

  domains.forEach((d) => {
    card(s, d.x, 1.2, 3.05, 4.0, d.title, null, d.color);
    s.addText(d.sub, { x: d.x + 0.35, y: 1.88, w: 2.55, h: 0.28, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
    s.addText(d.items, { x: d.x + 0.35, y: 2.25, w: 2.55, h: 2.7, fontSize: 10, fontFace: F.body, color: C.dkSub, margin: 0, valign: "top" });
  });

  s.addText("三个域按「不同责任」划分，不是按 pipeline 顺序。故意不用 annotation_pipeline / pseudo_labeling 等对称命名", { x: 0.4, y: 5.35, w: 9.2, h: 0.25, fontSize: 9, fontFace: F.body, italic: true, color: C.muted, margin: 0 });
})();

// ============================================================
// S4: Closed Loop Flow
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "闭环流程");

  // 8 nodes in an oval loop arrangement
  const nodes = [
    { label: "病例数据", x: 4.2, y: 0.85, w: 1.4 },
    { label: "标签来源", x: 7.0, y: 0.85, w: 1.6 },
    { label: "标注审核", x: 8.2, y: 2.1, w: 1.4 },
    { label: "数据快照", x: 8.2, y: 3.4, w: 1.4 },
    { label: "训练", x: 7.0, y: 4.65, w: 1.6 },
    { label: "模型", x: 4.2, y: 4.65, w: 1.4 },
    { label: "批量推理", x: 0.4, y: 3.4, w: 1.5 },
    { label: "候选标签", x: 0.4, y: 2.1, w: 1.5 },
  ];

  nodes.forEach((n) => {
    s.addShape(pres.shapes.RECTANGLE, { x: n.x, y: n.y, w: n.w, h: 0.65, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: C.border, width: 0.5 } });
    s.addText(n.label, { x: n.x, y: n.y, w: n.w, h: 0.65, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
  });

  // Domain labels (dashed boxes)
  s.addShape(pres.shapes.RECTANGLE, { x: 0.1, y: 1.7, w: 2.2, h: 2.65, fill: { color: "FFFFFF", transparency: 60 }, line: { color: C.tAmber, width: 1, dashType: "dash" } });
  s.addText("label_\ngeneration", { x: 0.15, y: 2.65, w: 1.9, h: 0.6, fontSize: 8, fontFace: F.body, color: C.tAmber, align: "center", valign: "middle", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, { x: 7.7, y: 1.7, w: 2.2, h: 2.65, fill: { color: "FFFFFF", transparency: 60 }, line: { color: C.tBlue, width: 1, dashType: "dash" } });
  s.addText("labeling", { x: 7.85, y: 2.65, w: 1.9, h: 0.6, fontSize: 8, fontFace: F.body, color: C.tBlue, align: "center", valign: "middle", margin: 0 });

  s.addShape(pres.shapes.RECTANGLE, { x: 5.8, y: 3.8, w: 3.8, h: 1.8, fill: { color: "FFFFFF", transparency: 60 }, line: { color: C.tGreen, width: 1, dashType: "dash" } });
  s.addText("training", { x: 5.85, y: 4.45, w: 3.5, h: 0.5, fontSize: 8, fontFace: F.body, color: C.tGreen, align: "center", valign: "middle", margin: 0 });
})();

// ============================================================
// S5: Six Label States
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "六种标签状态");

  // State machine diagram: simplified boxes + arrows
  const srcX = 0.4, candX = 2.8, row2y = 1.4, row3y = 2.85;
  // Source boxes
  s.addShape(pres.shapes.RECTANGLE, { x: srcX, y: row2y, w: 1.4, h: 0.5, fill: { color: C.tableBg }, line: { color: C.tBlue, width: 1 } });
  s.addText("source_label", { x: srcX, y: row2y, w: 1.4, h: 0.5, fontSize: 9, fontFace: F.mono, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: candX, y: row2y, w: 1.5, h: 0.5, fill: { color: C.tableBg }, line: { color: C.tAmber, width: 1 } });
  s.addText("candidate_label", { x: candX, y: row2y, w: 1.5, h: 0.5, fontSize: 9, fontFace: F.mono, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });

  // Downstream states
  const states = [
    { label: "draft_label", x: 5.0, color: C.blue },
    { label: "accepted_pseudo", x: 6.6, color: C.green },
    { label: "verified_label", x: 8.2, color: C.tGreen },
    { label: "rejected_label", x: 0.4, color: C.red },
  ];
  states.forEach((st) => {
    s.addShape(pres.shapes.RECTANGLE, { x: st.x, y: row3y, w: 1.4, h: 0.5, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: st.color, width: 1.5 } });
    s.addText(st.label, { x: st.x, y: row3y, w: 1.4, h: 0.5, fontSize: 9, fontFace: F.mono, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
  });

  // Arrow labels
  s.addText("→", { x: 1.8, y: row2y + 0.08, w: 0.6, h: 0.4, fontSize: 16, fontFace: F.body, color: C.tBlue, align: "center", valign: "middle", margin: 0 });
  s.addText("QC 通过 →", { x: 3.5, y: row2y + 0.08, w: 1.0, h: 0.4, fontSize: 9, fontFace: F.body, color: C.tGreen, valign: "middle", margin: 0 });
  s.addText("失败 →", { x: 1.3, y: row2y + 0.08, w: 0.8, h: 0.4, fontSize: 9, fontFace: F.body, color: C.red, valign: "middle", margin: 0 });

  // Label state table
  const stateTable = [
    [{ text: "状态", options: tableHeader(C.dkText) }, { text: "含义", options: tableHeader(C.dkText) }, { text: "默认可训练", options: tableHeader(C.dkText) }],
    ["source_label", "外部数据集自带标签，未经平台判断", "视来源质量"],
    ["candidate_label", "模型/算法生成候选结果", "默认否，策略可纳入"],
    ["draft_label", "专门准备给人修正的起点", "否"],
    ["accepted_pseudo_label", "经 QC + 策略接受的伪标签", "任务策略决定"],
    ["verified_label", "人工确认标签（单人保存即 verified）", "是"],
    ["rejected_label", "已判定不可用", "否"],
  ].map((r, ri) => r.map((c, ci) => typeof c === 'string' ? ({
    text: c,
    options: { fontSize: 10, fontFace: ci === 0 ? F.mono : F.body, bold: ri === 0, fill: { color: ri === 0 ? C.dkText : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(stateTable, { x: 0.4, y: 3.7, w: 9.2, colW: [2.5, 4.5, 2.2], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.35, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3] });
})();

// ============================================================
// S6: 3-Layer Label Map
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "三层 Label Map 设计");

  const layers = [
    {
      title: "anatomy_vocabulary", sub: "这是什么器官？", eg: "liver = 肝脏", eg2: "纯语义，无数字，全平台唯一", x: 0.3, color: C.tBlue, label: "语义层",
    },
    {
      title: "review_label_map", sub: "工具里是几号？", eg: "liver = 10 (Mimics)", eg2: "受标注软件限制，可随工具换", x: 3.55, color: C.tAmber, label: "工具层",
    },
    {
      title: "task_label_maps", sub: "训练时是几号？", eg: "liver = 2 (CT5_Liver)", eg2: "nnUNet 要求类内连续整数", x: 6.8, color: C.tGreen, label: "训练层",
    },
  ];

  layers.forEach((l) => {
    card(s, l.x, 1.15, 3.05, 2.15, l.title, null, l.color);
    s.addShape(pres.shapes.RECTANGLE, { x: l.x + 1.7, y: 1.22, w: 1.1, h: 0.26, fill: { color: l.color, transparency: 85 } });
    s.addText(l.label, { x: l.x + 1.7, y: 1.22, w: 1.1, h: 0.26, fontSize: 9, fontFace: F.body, color: l.color, align: "center", valign: "middle", margin: 0 });
    s.addText(l.sub, { x: l.x + 0.35, y: 1.72, w: 2.5, h: 0.3, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
    s.addText([{ text: l.eg, options: { breakLine: true, bold: true, fontSize: 12 } }, { text: l.eg2, options: { fontSize: 10, color: C.dkSub } }], { x: l.x + 0.35, y: 2.1, w: 2.5, h: 1.0, margin: 0, valign: "top" });
  });

  // Key insight
  s.addText("同一个 liver：review 文件里 = 10，CT5_Liver 任务里 = 2，CT_Combine 展示 = 37。不是数字冲突，是层级分工。", { x: 0.4, y: 3.55, w: 9.2, h: 0.3, fontSize: 10, fontFace: F.body, color: C.dkSub, margin: 0 });

  // Table: why cannot merge
  const mergeTable = [
    [{ text: "尝试合并", options: tableHeader(C.dkText) }, { text: "为什么不行", options: tableHeader(C.dkText) }],
    ["合并 anatomy + review", "换标注工具就要改器官名称表；器官名称应是全平台稳定引用"],
    ["合并 review + task", "同一 liver 在不同任务编号不同 (CT5=2, CT_All_Coarse=5)，没有唯一编号"],
    ["全合并成一张表", "语义层、工具层、训练层的约束来源各不相同，修改会互相拉扯"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri === 0, fill: { color: ri === 0 ? C.dkText : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(mergeTable, { x: 0.4, y: 4.05, w: 9.2, colW: [3.0, 6.2], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.35, 0.32, 0.32, 0.32] });
})();

// ============================================================
// S7: Case Package Contract
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "Case Package 契约");

  // Left: directory tree
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 1.15, w: 3.8, h: 3.5, fill: { color: C.dkText } });
  s.addText([
    { text: "case_package/", options: { bold: true, color: C.teal, fontSize: 12, fontFace: F.mono, breakLine: true } },
    { text: "├── manifest.json", options: { color: C.white, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "├── images/image.nii.gz", options: { color: C.sub, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "├── labels/", options: { color: C.white, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "│   ├── draft_label.nii.gz", options: { color: C.sub, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "│   ├── verified_label.nii.gz", options: { color: C.green, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "│   └── masks/liver.nii.gz", options: { color: C.sub, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "├── config/", options: { color: C.white, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "│   ├── anatomy_vocabulary.yaml", options: { color: C.sub, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "│   └── review_label_map.yaml", options: { color: C.sub, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "├── reports/", options: { color: C.white, fontSize: 11, fontFace: F.mono, breakLine: true } },
    { text: "└── provenance/", options: { color: C.white, fontSize: 11, fontFace: F.mono } },
  ], { x: 0.55, y: 1.25, w: 3.5, h: 3.3, valign: "top", margin: 0 });

  // Right: validation rules
  const validTable = [
    [{ text: "校验规则", options: { ...tableHeader(C.dkText), colSpan: 3 } }, { text: "", options: { fill: { color: C.dkText } } }, { text: "", options: { fill: { color: C.dkText } } }],
    [{ text: "校验项", options: tableHeader(C.tBlue) }, { text: "级别", options: tableHeader(C.tBlue) }, { text: "处理", options: tableHeader(C.tBlue) }],
    ["图像 sha256 不一致", "Error", "拒绝导入"],
    ["标签 shape 不一致", "Error", "不可修复，拒绝"],
    ["spacing/affine 不一致", "Warning", "check_geometry.py 自动修复"],
    ["label id 不合法", "Error", "拒绝"],
    ["只有 draft 无 verified", "Warning", "标记，不阻塞"],
    ["必需器官缺失", "Warning", "记录在报告中"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri <= 1, fill: { color: ri === 0 ? C.dkText : (ri === 1 ? C.tableBg : (ri % 2 === 0 ? C.tableBg : C.white)) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(validTable, { x: 4.5, y: 1.15, w: 5.1, colW: [2.4, 1.0, 1.7], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.35, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3, 0.3] });

  s.addText("一个病例一个包，自包含可搬运。nnUNet 不直接读 Case Package → 经 Registry + Snapshot 导出", { x: 0.4, y: 4.85, w: 9.2, h: 0.3, fontSize: 10, fontFace: F.body, italic: true, color: C.dkSub, margin: 0 });
})();

// ============================================================
// S8: nnUNet Pipeline
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "训练管线 — nnUNet 五阶段");

  // Framework box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 1.15, w: 9.2, h: 0.5, fill: { color: C.dkText } });
  s.addText("Config.toml  +  ModelMap.toml  →  AutoSegmentationFramework（编排器）", { x: 0.4, y: 1.15, w: 9.2, h: 0.5, fontSize: 14, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  // 5 Action cards
  const actions = [
    { n: "1", title: "数据转换", sub: "标注数据 → nnUNet 格式\n重采样 + 合并 + 划分", x: 0.3 },
    { n: "2", title: "预处理", sub: "指纹提取 + 实验规划\n支持手动覆盖参数", x: 2.1 },
    { n: "3", title: "训练", sub: "GPU 管理 + 5 折交叉\nDDP 多卡支持", x: 3.9 },
    { n: "4", title: "推理", sub: "预插值加速\n多模型共享分辨率", x: 5.7 },
    { n: "5", title: "评估", sub: "Dice + Surface Dice\n多格式报告 + 聚合", x: 7.5 },
  ];

  actions.forEach((a, i) => {
    s.addShape(pres.shapes.RECTANGLE, { x: a.x, y: 2.1, w: 1.65, h: 1.8, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: C.border, width: 0.5 } });
    // Number circle
    s.addShape(pres.shapes.OVAL, { x: a.x + 0.6, y: 2.2, w: 0.4, h: 0.4, fill: { color: C.tBlue } });
    s.addText(a.n, { x: a.x + 0.6, y: 2.2, w: 0.4, h: 0.4, fontSize: 14, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(a.title, { x: a.x + 0.1, y: 2.7, w: 1.45, h: 0.35, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
    s.addText(a.sub, { x: a.x + 0.08, y: 3.15, w: 1.5, h: 0.65, fontSize: 9, fontFace: F.body, color: C.dkSub, align: "center", valign: "top", margin: 0 });
    if (i < actions.length - 1) {
      s.addText("→", { x: a.x + 1.55, y: 2.65, w: 0.35, h: 0.35, fontSize: 16, fontFace: F.body, color: C.tBlue, align: "center", valign: "middle", margin: 0 });
    }
  });

  // Bottom notes
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.2, w: 9.2, h: 0.7, fill: { color: C.tableBg } });
  s.addText("ModelMap.toml 已是 TaskLabelMap 雏形：每模型独立从 1 编号，支持扁平格式（细粒度）和分组格式（粗分割）", { x: 0.6, y: 4.3, w: 8.8, h: 0.5, fontSize: 10, fontFace: F.body, color: C.dkText, valign: "middle", margin: 0 });
  s.addText("多 GPU 调度：不同 GPU 并行 + 同 GPU 串行 → 自动生成 gpu{0,1,2,3}.sh", { x: 0.4, y: 5.05, w: 9.2, h: 0.3, fontSize: 10, fontFace: F.body, italic: true, color: C.dkSub, margin: 0 });
})();

// ============================================================
// S9: Adapter Architecture
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "Adapter 架构 — 可扩展性核心");

  // Dataset Snapshot
  s.addShape(pres.shapes.RECTANGLE, { x: 3.5, y: 1.15, w: 3, h: 0.55, fill: { color: C.dkText } });
  s.addText("Dataset Snapshot  冻结的数据视图", { x: 3.5, y: 1.15, w: 3, h: 0.55, fontSize: 12, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  // 4 parallel adapters
  const adapters = [
    { name: "nnUNet\nAdapter", sub: "全监督\n生产级", x: 0.25, col: C.tGreen, tag: "已完成" },
    { name: "FewShot\nAdapter", sub: "预训练+微调\n少样本", x: 2.6, col: C.tBlue, tag: "架构已定" },
    { name: "MONAI\nAdapter", sub: "Transformer\n模型", x: 4.95, col: C.tAmber, tag: "预留" },
    { name: "其他\nAdapter", sub: "SAM / 新框架\n...", x: 7.3, col: C.muted, tag: "可扩展" },
  ];

  adapters.forEach((a) => {
    const y = 2.05;
    s.addShape(pres.shapes.RECTANGLE, { x: a.x, y, w: 2.2, h: 1.15, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: a.col, width: 1.5 } });
    s.addText(a.name, { x: a.x, y, w: 2.2, h: 0.6, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
    s.addText(a.sub, { x: a.x, y: y + 0.6, w: 2.2, h: 0.45, fontSize: 9, fontFace: F.body, color: C.dkSub, align: "center", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: a.x + 1.1, y: y + 0.05, w: 0.95, h: 0.22, fill: { color: a.col, transparency: 85 } });
    s.addText(a.tag, { x: a.x + 1.1, y: y + 0.05, w: 0.95, h: 0.22, fontSize: 8, fontFace: F.body, color: a.col, align: "center", valign: "middle", margin: 0 });

    // Each → Model Record
    s.addShape(pres.shapes.RECTANGLE, { x: a.x + 0.2, y: 3.6, w: 1.8, h: 0.42, fill: { color: C.tableBg }, line: { color: C.border, width: 0.5 } });
    s.addText("Model Record", { x: a.x + 0.2, y: 3.6, w: 1.8, h: 0.42, fontSize: 10, fontFace: F.title, bold: true, color: C.tGreen, align: "center", valign: "middle", margin: 0 });
  });

  // Key message
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.3, w: 9.2, h: 1.1, fill: { color: C.tableBg } });
  s.addText([
    { text: "不变层（数据契约）", options: { bold: true, breakLine: true, fontSize: 14 } },
    { text: "Case / Image Artifact / Label Artifact / Dataset Snapshot / label_policy", options: { breakLine: true, fontSize: 11 } },
    { text: "可变层（Adapter 封装）：nnUNet / MONAI / FewShot / SAM / ...", options: { breakLine: true, fontSize: 11 } },
    { text: "新框架 = 新 Adapter，不动数据契约。就像 USB 协议：设备可换，接口不变。", options: { breakLine: true, fontSize: 10, italic: true, color: C.dkSub } },
  ], { x: 0.6, y: 4.4, w: 8.8, h: 0.9, color: C.dkText, margin: 0, valign: "top" });
})();

// ============================================================
// S10: FewShot Learning
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "少样本学习 — FewShot Adapter");

  // Left: architecture position
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 1.2, w: 3.3, h: 0.5, fill: { color: C.dkText } });
  s.addText("Dataset Snapshot", { x: 0.4, y: 1.2, w: 3.3, h: 0.5, fontSize: 12, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  // nnUNet
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 2.1, w: 3.3, h: 1.2, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: C.tGreen, width: 1.5 } });
  s.addText("nnUNet Adapter\n全监督训练", { x: 0.4, y: 2.2, w: 3.3, h: 0.55, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, align: "center", margin: 0 });
  s.addText("生产级 · 已完成", { x: 0.4, y: 2.8, w: 3.3, h: 0.3, fontSize: 9, fontFace: F.body, color: C.tGreen, align: "center", margin: 0 });

  // FewShot
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 3.65, w: 3.3, h: 1.2, fill: { color: C.white }, shadow: { type: "outer", blur: 4, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: C.tBlue, width: 1.5 } });
  s.addText("FewShot Adapter\n少样本训练", { x: 0.4, y: 3.75, w: 3.3, h: 0.55, fontSize: 11, fontFace: F.title, bold: true, color: C.dkText, align: "center", margin: 0 });
  s.addText("架构已定 · 待生产级验证", { x: 0.4, y: 4.35, w: 3.3, h: 0.3, fontSize: 9, fontFace: F.body, color: C.tBlue, align: "center", margin: 0 });

  // Right: experiment protocol
  s.addText("生产级实验协议", { x: 4.2, y: 1.2, w: 5.4, h: 0.35, fontSize: 15, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  const steps = [
    "选定器官 → verified 病例 → 患者级别冻结划分",
    "构建 N-shot Snapshot（N=1, 3, 5, 10, 20）",
    "三对照组：A.全监督上界 / B.同数据量基线 / C.微调实验组",
    "冻结测试集上计算 Dice, Surface Dice, Hausdorff",
    "结果登记 Model Registry → 达准入标准 → 升级为 Adapter",
  ];
  steps.forEach((st, i) => {
    s.addShape(pres.shapes.OVAL, { x: 4.2, y: 1.75 + i * 0.5, w: 0.3, h: 0.3, fill: { color: C.tBlue } });
    s.addText(String(i + 1), { x: 4.2, y: 1.75 + i * 0.5, w: 0.3, h: 0.3, fontSize: 10, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(st, { x: 4.6, y: 1.75 + i * 0.5, w: 5.0, h: 0.3, fontSize: 10, fontFace: F.body, color: C.dkText, valign: "middle", margin: 0 });
  });

  // Criteria table
  s.addText("准入标准", { x: 4.2, y: 4.35, w: 5.4, h: 0.3, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  const criteria = [
    [{ text: "条件", options: tableHeader(C.dkText) }, { text: "阈值", options: tableHeader(C.dkText) }],
    ["独立复现", "每器官 ≥ 3 次"],
    ["Dice vs 全监督", "≥ 全监督的 90%"],
    ["跨扫描协议差距", "≤ 0.05 Dice"],
    ["失败率 (Dice<0.3)", "< 5%"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri === 0, fill: { color: ri === 0 ? C.dkText : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(criteria, { x: 4.2, y: 4.7, w: 5.4, colW: [2.4, 3.0], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.3, 0.25, 0.25, 0.25, 0.25] });
})();

// ============================================================
// S11: Mimics Integration
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "Mimics 集成方案");

  // Flow: Platform → Mimics → Platform
  const flowSteps = [
    { label: "平台\nsplit / merge", x: 0.2 },
    { label: "Case\nPackage", x: 2.4 },
    { label: "Mimics\n导入 masks", x: 4.6 },
    { label: "人工\n修正", x: 6.8 },
    { label: "Mimics\n导出 masks", x: 8.5 },
  ];
  flowSteps.forEach((f) => {
    s.addShape(pres.shapes.RECTANGLE, { x: f.x, y: 1.15, w: 1.55, h: 0.75, fill: { color: C.white }, shadow: { type: "outer", blur: 3, offset: 1, angle: 135, color: "000000", opacity: 0.06 }, line: { color: C.tBlue, width: 1 } });
    s.addText(f.label, { x: f.x, y: 1.15, w: 1.55, h: 0.75, fontSize: 10, fontFace: F.title, bold: true, color: C.dkText, align: "center", valign: "middle", margin: 0 });
  });
  [1.75, 3.95, 6.15, 8.35].forEach((x) => { s.addText("→", { x, y: 1.3, w: 0.4, h: 0.4, fontSize: 16, fontFace: F.body, color: C.tBlue, align: "center", valign: "middle", margin: 0 }); });

  // Key APIs table
  s.addText("关键 API（已确认存在）", { x: 0.4, y: 2.2, w: 9.2, h: 0.35, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  const apiTable = [
    [{ text: "API", options: tableHeader(C.dkText) }, { text: "用途", options: tableHeader(C.dkText) }, { text: "来源", options: tableHeader(C.dkText) }],
    [{ text: "mimics.data.masks.find(name=...)", options: { fontFace: F.mono } }, "查找指定名称 Mask", "社区代码"],
    [{ text: "mask.get_voxel_buffer()", options: { fontFace: F.mono } }, "获取 Mask 体素（numpy 数组）", "社区代码"],
    [{ text: "mask.set_voxel_buffer(arr)", options: { fontFace: F.mono } }, "导入 numpy 数组到 Mask", "官方员工确认"],
    [{ text: "NIfTI 导入导出 (2025 GUI)", options: { fontFace: F.mono } }, "官方原生功能，替代手工 affine", "产品更新页"],
    [{ text: "Help → Scripting Guide", options: { fontFace: F.mono } }, "完整 API 文档，内置在 Mimics 中", "随软件安装"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 9, fontFace: ci === 0 ? F.mono : F.body, bold: ri === 0, fill: { color: ri === 0 ? C.dkText : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(apiTable, { x: 0.4, y: 2.6, w: 9.2, colW: [3.2, 3.6, 2.4], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.32, 0.3, 0.3, 0.3, 0.3, 0.3] });

  // Risk
  s.addText("风险与应对", { x: 0.4, y: 4.45, w: 9.2, h: 0.3, fontSize: 14, fontFace: F.title, bold: true, color: C.dkText, margin: 0 });
  const riskTable = [
    [{ text: "风险", options: tableHeader(C.dkText) }, { text: "影响", options: tableHeader(C.dkText) }, { text: "应对", options: tableHeader(C.dkText) }],
    ["set_voxel_buffer 空间对齐", "标签与 CT 错位", "check_geometry.py 检测 + 修复"],
    ["Scripting API 不足以覆盖所有步骤", "自动化降低", "GUI 手动 + 平台脚本补偿"],
    ["Mimics 完全不可用", "阻塞标注流程", "切换 3D Slicer / ITK-SNAP"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri === 0, fill: { color: ri === 0 ? C.dkText : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(riskTable, { x: 0.4, y: 4.8, w: 9.2, colW: [3.0, 2.4, 3.8], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.3, 0.28, 0.28, 0.28] });
})();

// ============================================================
// S12: Phased Implementation
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "分阶段实施路线");

  const phases = [
    { phase: "A", title: "文件包闭环", desc: "一个病例从候选标签到人工保存，再进入训练快照", status: "👈 当前", fill: true, col: C.tGreen },
    { phase: "B", title: "注册中心 + 快照", desc: "Data Registry、Dataset Snapshot → 多任务复用、训练可复现", status: "设计已定", fill: false },
    { phase: "C", title: "Adapter 稳定", desc: "nnUNet Adapter 跑通，预留 MONAI / FewShot 接口", status: "设计已定", fill: false },
    { phase: "D", title: "离线批量推理", desc: "模型版本 + 批量任务 + candidate_label 回流", status: "后期", fill: false },
    { phase: "E", title: "统一调度", desc: "Web UI、任务队列、权限、审计 → 数据契约稳定后", status: "后期", fill: false },
  ];

  const phaseData = [
    [{ text: "", options: tableHeader(C.dkText) }, { text: "阶段", options: tableHeader(C.dkText) }, { text: "目标", options: tableHeader(C.dkText) }, { text: "状态", options: tableHeader(C.dkText) }],
    ...phases.map((p) => [
      { text: p.phase, options: { fontSize: 16, bold: true, color: p.col, align: "center", fill: { color: p.fill ? "ECFDF5" : C.white } } },
      { text: p.title, options: { fontSize: 11, bold: true, fill: { color: p.fill ? "ECFDF5" : C.white } } },
      { text: p.desc, options: { fontSize: 10, fill: { color: p.fill ? "ECFDF5" : C.white } } },
      { text: p.status, options: { fontSize: 10, bold: true, color: p.col, fill: { color: p.fill ? "ECFDF5" : C.white } } },
    ]),
  ];
  s.addTable(phaseData, { x: 0.4, y: 1.15, w: 9.2, colW: [0.5, 2.0, 4.5, 2.2], border: { pt: 0.5, color: C.border }, fontFace: F.body, color: C.dkText, rowH: [0.4, 0.6, 0.55, 0.55, 0.55, 0.55] });
})();

// ============================================================
// S13: Key Decisions
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "已确认的关键决策");

  const decisions = [
    { label: "伪标签准入", desc: "默认允许，取决于器官/任务/模型。默认允许 + 特定排除，provenance 永不造假", col: C.tBlue },
    { label: "器官范围", desc: "v500 全部模型（CT1-16、MR1-8），涵盖全身多处器官", col: C.tGreen },
    { label: "全身模型方案", desc: "保持多模型组合（已验证），后期有条件再实验统一模型", col: C.tAmber },
    { label: "Mimics POC", desc: "先做调研准备（确认 Scripting Guide API），再启动 POC", col: C.tBlue },
    { label: "少样本学习", desc: "training 域新 Adapter，与 nnUNet 平级，需先过生产级实验协议", col: C.tGreen },
    { label: "label_policy", desc: "candidate_label 可通过 allow_status 直接纳入训练", col: C.tAmber },
    { label: "Data Registry", desc: "先不实现但必记——可追溯和可插拔的前提，闭环跑通后补", col: C.muted },
  ];

  decisions.forEach((d, i) => {
    row(s, 1.3 + i * 0.58, d.label, d.desc, d.col);
  });
})();

// ============================================================
// S14: Pre-implementation Checklist
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  slideTitle(s, "实现前待确认清单");

  s.addText("阻塞项（必须确认）", { x: 0.4, y: 1.1, w: 9.2, h: 0.35, fontSize: 14, fontFace: F.title, bold: true, color: C.red, margin: 0 });
  const blocking = [
    [{ text: "#", options: tableHeader(C.red) }, { text: "事项", options: tableHeader(C.red) }, { text: "状态", options: tableHeader(C.red) }],
    ["A1", "Mimics 版本 + 许可证类型", "未确认"],
    ["A2", "Scripting Guide 中 mask 相关 API 清单", "需在 Mimics Help 中查看"],
    ["A3", "Mimics 能否运行 Python 脚本", "取决于许可证"],
    ["A4", "第一批 3-5 个病例", "数据不是瓶颈"],
    ["A5", "训练服务器环境（GPU、路径）", "未确认"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri === 0 || ci === 0, fill: { color: ri === 0 ? C.red : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(blocking, { x: 0.4, y: 1.5, w: 9.2, colW: [0.5, 5.7, 3.0], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.3, 0.28, 0.28, 0.28, 0.28, 0.28] });

  s.addText("非阻塞项（可立即实现）", { x: 0.4, y: 3.4, w: 9.2, h: 0.35, fontSize: 14, fontFace: F.title, bold: true, color: C.tGreen, margin: 0 });
  const nonBlock = [
    [{ text: "#", options: tableHeader(C.tGreen) }, { text: "模块", options: tableHeader(C.tGreen) }, { text: "用途", options: tableHeader(C.tGreen) }],
    ["B1", "split_multilabel_to_masks.py", "多标签 NIfTI → 逐器官二值 mask"],
    ["B2", "merge_masks_to_multilabel.py", "逐器官 mask → 多标签 NIfTI"],
    ["B3", "check_geometry.py", "shape/spacing/affine 校验 + 自动修复"],
    ["B4", "package_case.py", "生成 Case Package 目录"],
    ["B5", "import_case_package.py", "读 masks → numpy → set_voxel_buffer"],
    ["B6", "export_review_package.py", "get_voxel_buffer → numpy → 保存 masks"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: ci === 1 ? F.mono : F.body, bold: ri === 0 || ci === 0, fill: { color: ri === 0 ? C.tGreen : (ri % 2 === 1 ? C.tableBg : C.white) }, color: ri === 0 ? C.white : C.dkText },
  }) : c));

  s.addTable(nonBlock, { x: 0.4, y: 3.8, w: 9.2, colW: [0.5, 4.0, 4.7], border: { pt: 0.5, color: C.border }, fontFace: F.body, rowH: [0.3, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28] });
})();

// ============================================================
// S15: Time Estimate
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.bg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("时间估算", { x: 0.6, y: 0.25, w: 8.8, h: 0.55, fontSize: 26, fontFace: F.title, bold: true, color: C.white, margin: 0 });

  // 3 scenario cards
  const scenarios = [
    { title: "顺利", time: "3-4 周", desc: "A1-A3 秒确认\nAPI 全有，几何无问题", col: C.green },
    { title: "正常", time: "5-6 周", desc: "1-2 个 Mimics 弯路\n1-2 轮几何调试", col: C.amber },
    { title: "Mimics 受限", time: "+2-3 周", desc: "降级 GUI 手动\n或切 3D Slicer", col: C.red },
  ];

  scenarios.forEach((sc, i) => {
    const x = 0.4 + i * 3.2;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.2, w: 2.9, h: 2.5, fill: { color: C.card } });
    s.addText(sc.title, { x, y: 1.35, w: 2.9, h: 0.4, fontSize: 14, fontFace: F.title, bold: true, color: sc.col, align: "center", margin: 0 });
    s.addText(sc.time, { x, y: 1.85, w: 2.9, h: 0.7, fontSize: 34, fontFace: F.title, bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.6, y: 2.6, w: 1.7, h: 0.03, fill: { color: sc.col } });
    s.addText(sc.desc, { x, y: 2.8, w: 2.9, h: 0.7, fontSize: 10, fontFace: F.body, color: C.sub, align: "center", valign: "top", margin: 0 });
  });

  // Breakdown
  const breakdown = [
    [{ text: "模块", options: tableHeader(C.card) }, { text: "工时", options: tableHeader(C.card) }, { text: "信心", options: tableHeader(C.card) }],
    ["平台脚本 B1-B4", "4-5 天", "高"],
    ["Mimics Adapter B5-B6", "乐观 2 天 / 悲观 2 周", "中低（依赖 A1-A3）"],
    ["闭环测试 + 调试", "1-2 周", "—"],
    ["3-5 病例验证", "1 周", "—"],
  ].map((r, ri) => r.map((c, ci) => typeof c === "string" ? ({
    text: c,
    options: { fontSize: 10, fontFace: F.body, bold: ri === 0, fill: { color: ri === 0 ? C.card : C.bg }, color: ri === 0 ? C.white : C.text },
  }) : c));

  s.addTable(breakdown, { x: 0.4, y: 3.95, w: 9.2, colW: [3.5, 3.5, 2.2], border: { pt: 0.5, color: "334155" }, fontFace: F.body, rowH: [0.32, 0.28, 0.28, 0.28, 0.28] });

  s.addText("最大减速带不是代码量，是 Mimics 确认和几何对齐调试", { x: 0.6, y: 5.35, w: 8.8, h: 0.2, fontSize: 10, fontFace: F.body, italic: true, color: C.muted, margin: 0 });
})();

// Write
pres.writeFile({ fileName: "/Users/ruanshijian/SegmentationPlatform/SegmentationPlatform_Architecture.pptx" })
  .then(() => console.log("PPT saved"))
  .catch(err => console.error(err));
