const pptxgen = require("pptxgenjs");
const pres = new pptxgen();
pres.layout = "LAYOUT_16x9";
pres.author = "ShijianRuan";
pres.title = "医学图像分割平台架构设计";

// ============================================================
// Color Palette
// ============================================================
const C = {
  navy:      "1A2744",
  darkBg:    "0F1B2D",
  teal:      "0891B2",
  emerald:   "0D9488",
  lightBg:   "F1F5F9",
  white:     "FFFFFF",
  text:      "1E293B",
  subtext:   "64748B",
  border:    "CBD5E1",
  accent1:   "06B6D4",
  accent2:   "10B981",
  accent3:   "F59E0B",
  accent4:   "EF4444",
  rowAlt:    "F8FAFC",
  tagBg:     "E0F2FE",
  tagText:   "0369A1",
  greenBg:   "D1FAE5",
  greenText: "065F46",
  redBg:     "FEE2E2",
  redText:   "991B1B",
};

const makeShadow = () => ({ type: "outer", blur: 4, offset: 2, angle: 135, color: "000000", opacity: 0.08 });

// ============================================================
// Helper: add a simple "card" shape with text
// ============================================================
function addCard(slide, x, y, w, h, title, body, opts = {}) {
  const fillColor = opts.fill || C.white;
  slide.addShape(pres.shapes.RECTANGLE, { x, y, w, h, fill: { color: fillColor }, shadow: makeShadow() });
  if (opts.accentLeft) {
    slide.addShape(pres.shapes.RECTANGLE, { x, y, w: 0.06, h, fill: { color: opts.accentLeft } });
  }
  slide.addText(title, { x: x + 0.2, y: y + 0.1, w: w - 0.35, h: 0.35, fontSize: 13, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  if (body) {
    slide.addText(body, { x: x + 0.2, y: y + 0.45, w: w - 0.35, h: h - 0.55, fontSize: 10, fontFace: "Arial", color: C.subtext, margin: 0, valign: "top" });
  }
}

function addTag(slide, x, y, text, color) {
  slide.addShape(pres.shapes.ROUNDED_RECTANGLE, { x, y, w: text.length * 0.16 + 0.2, h: 0.28, fill: { color: C.tagBg }, rectRadius: 0.05 });
  slide.addText(text, { x, y, w: text.length * 0.16 + 0.2, h: 0.28, fontSize: 8, fontFace: "Arial", color: C.tagText, align: "center", valign: "middle", margin: 0 });
}

// ============================================================
// Slide 1: Title
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.darkBg };
  // Decorative top bar
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.08, fill: { color: C.teal } });
  s.addText("医学图像分割平台", { x: 1, y: 1.2, w: 8, h: 0.8, fontSize: 42, fontFace: "Arial", bold: true, color: C.white, align: "center", margin: 0 });
  s.addText("架构设计", { x: 1, y: 2.0, w: 8, h: 0.7, fontSize: 36, fontFace: "Arial", color: C.accent1, align: "center", margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 3.5, y: 2.85, w: 3, h: 0.04, fill: { color: C.teal } });
  s.addText("Segmentation Platform Architecture Design", { x: 1, y: 3.1, w: 8, h: 0.5, fontSize: 14, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
  s.addText("2026-06-07", { x: 1, y: 4.5, w: 8, h: 0.4, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
})();

// ============================================================
// Slide 2: 平台核心定位
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("平台核心定位", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Hub-and-spoke: center
  const cx = 5, cy = 3.2;
  s.addShape(pres.shapes.OVAL, { x: cx - 1.15, y: cy - 0.7, w: 2.3, h: 1.4, fill: { color: C.navy } });
  s.addText("数据关系", { x: cx - 1.15, y: cy - 0.7, w: 2.3, h: 0.8, fontSize: 14, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
  s.addText("平台中心", { x: cx - 1.15, y: cy - 0.2, w: 2.3, h: 0.7, fontSize: 11, fontFace: "Arial", color: C.accent1, align: "center", valign: "middle", margin: 0 });

  // Spoke items
  const items = [
    { label: "病例\nCase", angle: -Math.PI/2, r: 2.5 },
    { label: "图像\nImage", angle: -Math.PI/6, r: 2.6 },
    { label: "标签\nLabel", angle: Math.PI/6, r: 2.5 },
    { label: "训练任务\nTask", angle: Math.PI/2, r: 2.4 },
    { label: "模型版本\nModel", angle: Math.PI*5/6, r: 2.6 },
  ];

  items.forEach((item) => {
    const ix = cx + Math.cos(item.angle) * item.r - 0.55;
    const iy = cy + Math.sin(item.angle) * item.r - 0.35;
    s.addShape(pres.shapes.OVAL, { x: ix, y: iy, w: 1.1, h: 0.7, fill: { color: C.white }, shadow: makeShadow(), line: { color: C.teal, width: 1.5 } });
    s.addText(item.label, { x: ix, y: iy, w: 1.1, h: 0.7, fontSize: 9, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
    // Line from center to spoke
    const lx = cx + Math.cos(item.angle) * 1.18;
    const ly = cy + Math.sin(item.angle) * 0.73;
    const dx = (ix + 0.55 - lx);
    const dy = (iy + 0.35 - ly);
    s.addShape(pres.shapes.LINE, { x: lx, y: ly, w: dx, h: dy, line: { color: C.border, width: 1, dashType: "dash" } });
  });

  // Bottom note
  s.addText("平台中心不是某个训练框架或标注软件，而是数据对象之间的关系", { x: 0.6, y: 5, w: 9, h: 0.3, fontSize: 11, fontFace: "Arial", italic: true, color: C.subtext, align: "center", margin: 0 });
})();

// ============================================================
// Slide 3: 三大实现域
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("三大实现域", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Three domain cards
  const domains = [
    { title: "labeling\n标注域", sub: "标签生产与安全导回", items: "导出 Case Package\nMimics 人工修正\n几何校验 + 注册", color: C.teal, x: 0.4, accent: C.teal },
    { title: "training\n训练域", sub: "任务消费标签产出模型", items: "TaskLabelMap\nDataset Snapshot\nnnUNet Adapter\nModel Record", color: C.emerald, x: 3.55, accent: C.emerald },
    { title: "label_generation\n标签生成域", sub: "候选标签生成筛选回流", items: "candidate_label\naccepted_pseudo_label\nQC + 准入策略\n离线批量推理", color: C.accent3, x: 6.7, accent: C.accent3 },
  ];

  domains.forEach((d) => {
    addCard(s, d.x, 1.2, 3.05, 3.6, d.title, null, { fill: C.white, accentLeft: d.accent });
    s.addText(d.sub, { x: d.x + 0.35, y: 1.85, w: 2.6, h: 0.3, fontSize: 11, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
    s.addText(d.items, { x: d.x + 0.35, y: 2.2, w: 2.6, h: 2.4, fontSize: 10, fontFace: "Arial", color: C.subtext, margin: 0, valign: "top" });
  });

  // Bottom note
  s.addText("三个域按「三种不同责任」划分，不是按 pipeline 顺序划分", { x: 0.6, y: 5.1, w: 9, h: 0.3, fontSize: 10, fontFace: "Arial", italic: true, color: C.subtext, margin: 0 });
})();

// ============================================================
// Slide 4: 三大域闭环流程图
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("闭环流程", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Circular flow: 8 nodes arranged in a loop
  const nodes = [
    { label: "病例\n数据", x: 4.25, y: 0.85 },
    { label: "标签\n来源", x: 7.5, y: 0.85 },
    { label: "标注\n审核", x: 8.6, y: 2.3 },
    { label: "数据集\n快照", x: 8.6, y: 3.7 },
    { label: "训练", x: 7.5, y: 5.0 },
    { label: "模型", x: 4.25, y: 5.0 },
    { label: "批量\n推理", x: 1.0, y: 3.7 },
    { label: "候选\n标签", x: 1.0, y: 2.3 },
  ];

  nodes.forEach((n) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: n.x, y: n.y, w: 1.3, h: 0.75, fill: { color: C.white }, shadow: makeShadow(), line: { color: C.teal, width: 1 }, rectRadius: 0.08 });
    s.addText(n.label, { x: n.x, y: n.y, w: 1.3, h: 0.75, fontSize: 9, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
  });

  // Arrows - simplified with text-based arrows between nodes
  const arrows = [
    { x: 5.55, y: 1.1, t: "→" }, { x: 8.05, y: 1.3, t: "↓" }, { x: 8.35, y: 3.0, t: "↓" },
    { x: 7.95, y: 4.5, t: "↓" }, { x: 5.55, y: 5.25, t: "→" }, { x: 2.3, y: 4.5, t: "↓" },
    { x: 1.95, y: 3.0, t: "↓" }, { x: 1.5, y: 1.3, t: "↑" }, { x: 2.5, y: 1.1, t: "←" },
  ];
  arrows.forEach((a) => {
    s.addText(a.t, { x: a.x, y: a.y, w: 0.5, h: 0.4, fontSize: 20, fontFace: "Arial", color: C.teal, align: "center", valign: "middle", margin: 0 });
  });

  // Domain labels
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.3, y: 1.6, w: 2.7, h: 2.2, fill: { color: "000000", transparency: 95 }, line: { color: C.accent3, width: 1, dashType: "dash" }, rectRadius: 0.1 });
  s.addText("label_generation", { x: 0.3, y: 2.4, w: 2.7, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.accent3, align: "center", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 7.2, y: 1.6, w: 2.7, h: 2.2, fill: { color: "000000", transparency: 95 }, line: { color: C.teal, width: 1, dashType: "dash" }, rectRadius: 0.1 });
  s.addText("labeling", { x: 7.2, y: 2.4, w: 2.7, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.teal, align: "center", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 5.5, y: 3.8, w: 4.2, h: 2.0, fill: { color: "000000", transparency: 95 }, line: { color: C.emerald, width: 1, dashType: "dash" }, rectRadius: 0.1 });
  s.addText("training", { x: 5.5, y: 4.5, w: 4.2, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.emerald, align: "center", margin: 0 });
})();

// ============================================================
// Slide 5: 六种标签状态
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("六种标签状态", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // State machine: boxes connected by arrows
  // Row 1: sources
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 1.3, w: 1.15, h: 0.5, fill: { color: C.tagBg }, rectRadius: 0.05, line: { color: C.tagText, width: 1 } });
  s.addText("数据集标签", { x: 0.4, y: 1.3, w: 1.15, h: 0.5, fontSize: 8, fontFace: "Arial", color: C.tagText, align: "center", valign: "middle", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.1, y: 1.3, w: 1.15, h: 0.5, fill: { color: C.tagBg }, rectRadius: 0.05, line: { color: C.tagText, width: 1 } });
  s.addText("算法输出", { x: 2.1, y: 1.3, w: 1.15, h: 0.5, fontSize: 8, fontFace: "Arial", color: C.tagText, align: "center", valign: "middle", margin: 0 });

  // source_label
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 2.1, w: 1.15, h: 0.5, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.05, line: { color: C.teal, width: 1 } });
  s.addText("source_label", { x: 0.4, y: 2.1, w: 1.15, h: 0.5, fontSize: 7, fontFace: "Consolas", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });

  // candidate_label
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.1, y: 2.1, w: 1.15, h: 0.5, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.05, line: { color: C.accent3, width: 1 } });
  s.addText("candidate_label", { x: 2.1, y: 2.1, w: 1.15, h: 0.5, fontSize: 7, fontFace: "Consolas", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });

  // Row 2: downstream states
  const states = [
    { label: "draft_label", x: 0.2, w: 1.0, color: C.accent1 },
    { label: "accepted_pseudo", x: 1.5, w: 1.05, color: C.accent2 },
    { label: "verified_label", x: 2.8, w: 1.05, color: C.emerald },
    { label: "rejected_label", x: 4.1, w: 1.0, color: C.accent4 },
  ];
  states.forEach((st) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.8 + st.x, y: 3.0, w: st.w, h: 0.5, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.05, line: { color: st.color, width: 1.5 } });
    s.addText(st.label, { x: 3.8 + st.x, y: 3.0, w: st.w, h: 0.5, fontSize: 7, fontFace: "Consolas", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
  });

  // Arrows using text
  s.addText("↓", { x: 0.75, y: 1.85, w: 0.5, h: 0.3, fontSize: 14, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
  s.addText("↓", { x: 2.45, y: 1.85, w: 0.5, h: 0.3, fontSize: 14, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });

  // Main branch labels
  s.addText("QC→", { x: 2.8, y: 2.65, w: 0.5, h: 0.3, fontSize: 7, fontFace: "Arial", color: C.accent2, margin: 0 });
  s.addText("修正→", { x: 3.6, y: 2.65, w: 0.7, h: 0.3, fontSize: 7, fontFace: "Arial", color: C.accent1, margin: 0 });
  s.addText("失败→", { x: 6.3, y: 2.65, w: 0.5, h: 0.3, fontSize: 7, fontFace: "Arial", color: C.accent4, margin: 0 });

  // State table
  const stateTable = [
    [{ text: "状态", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "含义", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "默认可训练", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "source_label", options: { fontSize: 8 } }, { text: "外部数据集自带标签", options: { fontSize: 8 } }, { text: "由来源质量决定", options: { fontSize: 8 } }],
    [{ text: "candidate_label", options: { fontSize: 8 } }, { text: "模型/算法生成候选", options: { fontSize: 8 } }, { text: "默认否，策略可纳入", options: { fontSize: 8 } }],
    [{ text: "draft_label", options: { fontSize: 8 } }, { text: "给人修正的草稿起点", options: { fontSize: 8 } }, { text: "否", options: { fontSize: 8 } }],
    [{ text: "accepted_pseudo", options: { fontSize: 8 } }, { text: "策略准入的伪标签", options: { fontSize: 8 } }, { text: "由任务策略决定", options: { fontSize: 8 } }],
    [{ text: "verified_label", options: { fontSize: 8 } }, { text: "人工确认标签", options: { fontSize: 8 } }, { text: "是", options: { fontSize: 8 } }],
    [{ text: "rejected_label", options: { fontSize: 8 } }, { text: "判定不可用", options: { fontSize: 8 } }, { text: "否", options: { fontSize: 8 } }],
  ];
  s.addTable(stateTable, { x: 0.4, y: 4.0, w: 9.2, colW: [2.0, 5.2, 2.0], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.35, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28] });
})();

// ============================================================
// Slide 6: 三层 Label Map 设计
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("三层 Label Map 设计", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Three layer cards with example
  const layers = [
    { title: "anatomy_vocabulary", sub: "这是什么器官？", eg: "liver = 肝脏", eg2: "纯语义，无数字", x: 0.4, color: C.teal, tag: "平台语义层" },
    { title: "review_label_map", sub: "工具里是几号？", eg: "liver = 10 (Mimics)", eg2: "受标注软件限制", x: 3.55, color: C.accent3, tag: "标注工具层" },
    { title: "task_label_maps", sub: "训练时是几号？", eg: "liver = 2 (CT5_Liver)", eg2: "nnUNet 要求连续整数", x: 6.7, color: C.emerald, tag: "训练框架层" },
  ];

  layers.forEach((l) => {
    addCard(s, l.x, 1.1, 3.05, 2.0, l.title, null, { fill: C.white, accentLeft: l.color });
    addTag(s, l.x + 1.6, 1.18, l.tag, l.color);
    s.addText(l.sub, { x: l.x + 0.35, y: 1.55, w: 2.6, h: 0.3, fontSize: 13, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
    s.addText([{ text: l.eg, options: { breakLine: true } }, { text: l.eg2 }], { x: l.x + 0.35, y: 1.9, w: 2.6, h: 1.0, fontSize: 10, fontFace: "Arial", color: C.subtext, margin: 0 });
  });

  // Key insight box
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 3.4, w: 9.2, h: 0.8, fill: { color: C.tagBg } });
  s.addText("核心原则：同一个 liver 在 review 文件里是 10，在 CT5_Liver 任务里是 2，在 CT_Combine 里是 37。\n这不是数字冲突，而是不同层级的编号体系。每一层不能合并——因为约束来源不同。", { x: 0.6, y: 3.5, w: 8.8, h: 0.6, fontSize: 10, fontFace: "Arial", color: C.tagText, margin: 0 });

  // Cannot merge explanation
  const cantMerge = [
    [{ text: "尝试合并方案", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "后果", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "anatomy + review 合并", options: { fontSize: 9 } }, { text: "换标注工具就要改器官名称表（如 Mimics→3D Slicer）", options: { fontSize: 9 } }],
    [{ text: "review + task 合并（最诱人）", options: { fontSize: 9 } }, { text: "同一器官在不同任务编号不同，没有唯一编号", options: { fontSize: 9 } }],
    [{ text: "全合并成一张表", options: { fontSize: 9 } }, { text: "修改训练编号会连带影响标注工具，两个方向的约束互相拉扯", options: { fontSize: 9 } }],
  ];
  s.addTable(cantMerge, { x: 0.4, y: 4.4, w: 9.2, colW: [3.0, 6.2], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.33, 0.28, 0.28, 0.28] });
})();

// ============================================================
// Slide 7: Case Package 契约
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Case Package 契约", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Left: directory tree
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 1.1, w: 4.2, h: 4.4, fill: { color: C.navy } });
  s.addText([
    { text: "case_package/", options: { bold: true, color: C.accent1, fontSize: 11, fontFace: "Consolas", breakLine: true } },
    { text: "├── manifest.json", options: { color: C.white, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "├── images/", options: { color: C.white, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "│   ├── image.nii.gz", options: { color: C.subtext, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "│   └── dicom/", options: { color: C.subtext, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "├── labels/", options: { color: C.white, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "│   ├── draft_label.nii.gz", options: { color: C.subtext, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "│   ├── verified_label.nii.gz", options: { color: C.accent2, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "│   └── masks/", options: { color: C.subtext, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "├── config/", options: { color: C.white, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "├── reports/", options: { color: C.white, fontSize: 10, fontFace: "Consolas", breakLine: true } },
    { text: "└── provenance/", options: { color: C.white, fontSize: 10, fontFace: "Consolas" } },
  ], { x: 0.5, y: 1.2, w: 4, h: 4.2, valign: "top", margin: 0 });

  // Right: validation rules
  s.addText("Manifest 必填字段", { x: 5, y: 1.1, w: 4.6, h: 0.35, fontSize: 13, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const manifestFields = [
    [{ text: "字段", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "用途", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "package_id / case_id", options: { fontSize: 9 } }, { text: "包与病例唯一标识", options: { fontSize: 9 } }],
    [{ text: "image.sha256", options: { fontSize: 9 } }, { text: "图像文件指纹，导回时防篡改", options: { fontSize: 9 } }],
    [{ text: "image.shape / spacing", options: { fontSize: 9 } }, { text: "几何元数据，导回时校验对齐", options: { fontSize: 9 } }],
    [{ text: "label_policy", options: { fontSize: 9 } }, { text: "标签准入规则", options: { fontSize: 9 } }],
    [{ text: "review.tool", options: { fontSize: 9 } }, { text: "标注工具标识", options: { fontSize: 9 } }],
  ];
  s.addTable(manifestFields, { x: 5, y: 1.55, w: 4.6, colW: [2.0, 2.6], border: { pt: 0.5, color: C.border }, fontFace: "Arial" });

  s.addText("校验规则", { x: 5, y: 3.5, w: 4.6, h: 0.35, fontSize: 13, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const validationRules = [
    [{ text: "校验项", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "级别", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "图像 hash 不一致", options: { fontSize: 9 } }, { text: "🔴 Error", options: { fontSize: 9 } }],
    [{ text: "标签 shape 不一致", options: { fontSize: 9 } }, { text: "🔴 Error", options: { fontSize: 9 } }],
    [{ text: "spacing/affine 不一致", options: { fontSize: 9 } }, { text: "⚠ 自动修复后通过", options: { fontSize: 9 } }],
    [{ text: "label id 不合法", options: { fontSize: 9 } }, { text: "🔴 Error", options: { fontSize: 9 } }],
    [{ text: "只有 draft 没有 verified", options: { fontSize: 9 } }, { text: "⚠ Warning", options: { fontSize: 9 } }],
  ];
  s.addTable(validationRules, { x: 5, y: 3.9, w: 4.6, colW: [2.6, 2.0], border: { pt: 0.5, color: C.border }, fontFace: "Arial" });
})();

// ============================================================
// Slide 8: nnUNet 五阶段训练管线
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("训练管线 — nnUNet 五阶段", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Top: config inputs
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 1.1, w: 2.0, h: 0.5, fill: { color: C.navy }, rectRadius: 0.05 });
  s.addText("Config.toml", { x: 0.4, y: 1.1, w: 2.0, h: 0.5, fontSize: 10, fontFace: "Consolas", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 2.7, y: 1.1, w: 2.0, h: 0.5, fill: { color: C.navy }, rectRadius: 0.05 });
  s.addText("ModelMap.toml", { x: 2.7, y: 1.1, w: 2.0, h: 0.5, fontSize: 10, fontFace: "Consolas", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  s.addText("↓", { x: 1.2, y: 1.55, w: 0.5, h: 0.3, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
  s.addText("↓", { x: 3.5, y: 1.55, w: 0.5, h: 0.3, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });

  // Framework
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 1.85, w: 4.3, h: 0.5, fill: { color: C.emerald }, rectRadius: 0.05 });
  s.addText("AutoSegmentationFramework（编排器）", { x: 0.4, y: 1.85, w: 4.3, h: 0.5, fontSize: 11, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  // 5 Actions in a row
  const actions = [
    { title: "Action1\n数据转换", sub: "标注数据→\nnnUNet格式\n重采样+合并", x: 0.3 },
    { title: "Action2\n预处理", sub: "指纹提取\n实验规划\n参数覆盖", x: 2.1 },
    { title: "Action3\n训练", sub: "GPU管理\n5折交叉\nDDP支持", x: 3.9 },
    { title: "Action4\n推理", sub: "预插值加速\n多模型共享\n跨平台适配", x: 5.7 },
    { title: "Action5\n评估", sub: "Dice/Surface\n多格式报告\n多模型聚合", x: 7.5 },
  ];
  actions.forEach((a) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: a.x, y: 2.75, w: 1.65, h: 1.4, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.08, line: { color: C.teal, width: 1 } });
    s.addText(a.title, { x: a.x, y: 2.8, w: 1.65, h: 0.6, fontSize: 9, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
    s.addText(a.sub, { x: a.x + 0.1, y: 3.4, w: 1.45, h: 0.65, fontSize: 8, fontFace: "Arial", color: C.subtext, align: "center", valign: "top", margin: 0 });
  });

  // Arrows between actions
  [1.95, 3.75, 5.55, 7.35].forEach((x) => {
    s.addText("→", { x, y: 3.1, w: 0.3, h: 0.35, fontSize: 14, fontFace: "Arial", color: C.teal, align: "center", valign: "middle", margin: 0 });
  });

  // Key insights
  s.addText("ModelMap.toml 已是 TaskLabelMap 雏形：每个模型独立从 1 编号，CT_Combine/MR_Combine 只用于拼接展示", { x: 0.4, y: 4.4, w: 9.2, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.subtext, margin: 0 });
  s.addText('支持扁平格式（细粒度）和分组格式（粗分割），粗分割通过分组格式自然表达', { x: 0.4, y: 4.7, w: 9.2, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.subtext, margin: 0 });

  // GPU scheduling note
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 5.1, w: 9.2, h: 0.4, fill: { color: C.tagBg } });
  s.addText("多 GPU 调度：不同 GPU 并行 + 同 GPU 串行 → 自动生成 gpu{0,1,2,3}.sh 脚本，避免显存冲突", { x: 0.6, y: 5.1, w: 8.8, h: 0.4, fontSize: 9, fontFace: "Arial", color: C.tagText, valign: "middle", margin: 0 });
})();

// ============================================================
// Slide 9: Adapter 架构 — 可扩展性核心
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Adapter 架构 — 可扩展性核心", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Snapshot source
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 3.5, y: 1.1, w: 3, h: 0.6, fill: { color: C.navy }, rectRadius: 0.08 });
  s.addText("Dataset Snapshot\n（冻结的数据视图）", { x: 3.5, y: 1.1, w: 3, h: 0.6, fontSize: 10, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  // Diverging lines to adapters
  s.addText("↓", { x: 4.8, y: 1.65, w: 0.5, h: 0.3, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });

  // Adapter row
  const adapters = [
    { name: "nnUNet\nAdapter", sub: "全监督\n生产级", x: 0.3, color: C.emerald, tag: "已完成" },
    { name: "FewShot\nAdapter", sub: "少样本\n预训练+微调", x: 2.55, color: C.teal, tag: "架构已定" },
    { name: "MONAI\nAdapter", sub: "Transformer\n模型", x: 4.8, color: C.accent3, tag: "预留" },
    { name: "其他\nAdapter", sub: "SAM/新框架\n...", x: 7.05, color: C.subtext, tag: "可扩展" },
  ];

  adapters.forEach((a) => {
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: a.x, y: 2.0, w: 2.1, h: 1.0, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.08, line: { color: a.color, width: 1.5 } });
    s.addText(a.name, { x: a.x, y: 2.05, w: 2.1, h: 0.55, fontSize: 10, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
    s.addText(a.sub, { x: a.x, y: 2.55, w: 2.1, h: 0.35, fontSize: 8, fontFace: "Arial", color: C.subtext, align: "center", valign: "middle", margin: 0 });
    addTag(s, a.x + 1.15, 1.95, a.tag, a.color);
  });

  // Converging to Model Record
  adapters.forEach((a) => {
    s.addText("↓", { x: a.x + 0.8, y: 3.05, w: 0.5, h: 0.3, fontSize: 10, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: a.x + 0.15, y: 3.35, w: 1.8, h: 0.5, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.05, line: { color: C.emerald, width: 1 } });
    s.addText("Model Record", { x: a.x + 0.15, y: 3.35, w: 1.8, h: 0.5, fontSize: 8, fontFace: "Arial", bold: true, color: C.emerald, align: "center", valign: "middle", margin: 0 });
  });

  // Key message
  s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y: 4.2, w: 9.2, h: 1.2, fill: { color: C.tagBg } });
  s.addText([
    { text: "架构核心原则", options: { bold: true, fontSize: 13, breakLine: true } },
    { text: "不变层（数据契约）：Case / Image Artifact / Label Artifact / Dataset Snapshot / label_policy", options: { breakLine: true, fontSize: 10 } },
    { text: "可变层（Adapter 封装）：nnUNet / MONAI / FewShot / SAM / ...", options: { breakLine: true, fontSize: 10 } },
    { text: "新框架 = 新 Adapter，不改数据契约。就像 USB 协议：设备可换，接口不变。", options: { fontSize: 10, italic: true } },
  ], { x: 0.6, y: 4.3, w: 8.8, h: 1.0, color: C.tagText, margin: 0, valign: "top" });
})();

// ============================================================
// Slide 10: 少样本学习架构定位
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("少样本学习 — FewShot Adapter", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Architecture position: nnUNet and FewShot as peers
  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 1.1, w: 3.0, h: 0.5, fill: { color: C.navy }, rectRadius: 0.08 });
  s.addText("Dataset Snapshot", { x: 0.4, y: 1.1, w: 3.0, h: 0.5, fontSize: 12, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 2.0, w: 3.0, h: 1.2, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.08, line: { color: C.emerald, width: 1.5 } });
  s.addText("nnUNet Adapter\n全监督训练", { x: 0.4, y: 2.0, w: 3.0, h: 0.7, fontSize: 11, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
  s.addText("生产级 · 已完成", { x: 0.4, y: 2.7, w: 3.0, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.emerald, align: "center", margin: 0 });

  s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: 0.4, y: 3.6, w: 3.0, h: 1.2, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.08, line: { color: C.teal, width: 1.5 } });
  s.addText("FewShot Adapter\n少样本训练", { x: 0.4, y: 3.6, w: 3.0, h: 0.7, fontSize: 11, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
  s.addText("架构已定 · 待生产级验证", { x: 0.4, y: 4.3, w: 3.0, h: 0.3, fontSize: 8, fontFace: "Arial", color: C.teal, align: "center", margin: 0 });

  s.addText("↓", { x: 1.65, y: 1.6, w: 0.5, h: 0.3, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });
  s.addText("↓", { x: 1.65, y: 3.2, w: 0.5, h: 0.3, fontSize: 12, fontFace: "Arial", color: C.subtext, align: "center", margin: 0 });

  // Right: experiment protocol
  s.addText("生产级实验协议", { x: 4, y: 1.1, w: 5.6, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.text, margin: 0 });

  const protocolSteps = [
    { step: "1", text: "选定器官 → 选出 verified 病例 → 患者级别冻结划分" },
    { step: "2", text: "构建 N-shot Snapshot（N=1,3,5,10,20）" },
    { step: "3", text: "三对照组：A. nnUNet全监督上界 / B. 同数据量基线 / C. 预训练+微调实验组" },
    { step: "4", text: "冻结测试集上计算 Dice、Surface Dice、Hausdorff Distance" },
    { step: "5", text: "结果登记 Model Registry" },
  ];

  protocolSteps.forEach((ps, i) => {
    s.addShape(pres.shapes.OVAL, { x: 4.1, y: 1.6 + i * 0.5, w: 0.3, h: 0.3, fill: { color: C.teal } });
    s.addText(ps.step, { x: 4.1, y: 1.6 + i * 0.5, w: 0.3, h: 0.3, fontSize: 9, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addText(ps.text, { x: 4.5, y: 1.6 + i * 0.5, w: 5.1, h: 0.3, fontSize: 9, fontFace: "Arial", color: C.text, valign: "middle", margin: 0 });
  });

  // Admission criteria
  s.addText("生产级准入标准", { x: 4, y: 4.2, w: 5.6, h: 0.35, fontSize: 13, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const criteria = [
    [{ text: "条件", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "说明", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "≥ 3 次独立复现", options: { fontSize: 9 } }, { text: "每个器官不能只跑一次效果好就宣布成功", options: { fontSize: 9 } }],
    [{ text: "Dice ≥ 全监督 90%", options: { fontSize: 9 } }, { text: "冻结评估集上，少样本不低于全监督 Dice 的 90%", options: { fontSize: 9 } }],
    [{ text: "跨扫描协议 ≤ 0.05", options: { fontSize: 9 } }, { text: "不同医院/CT 的 Dice 最大差距不超过 0.05", options: { fontSize: 9 } }],
    [{ text: "失败率 < 5%", options: { fontSize: 9 } }, { text: "Dice < 0.3 的病例占比", options: { fontSize: 9 } }],
  ];
  s.addTable(criteria, { x: 4, y: 4.6, w: 5.6, colW: [2.0, 3.6], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.3, 0.25, 0.25, 0.25, 0.25] });
})();

// ============================================================
// Slide 11: Mimics 集成方案
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("Mimics 集成方案", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Flow: Platform ↔ Mimics
  const flowSteps = [
    { label: "平台侧\nsplit/merge\npackage", x: 0.3, color: C.navy },
    { label: "Case\nPackage", x: 2.7, color: C.teal },
    { label: "Mimics\nset_voxel\n_buffer", x: 5.1, color: C.accent3 },
    { label: "人工\n修正", x: 7.5, color: C.accent4 },
    { label: "Mimics\nget_voxel\n_buffer", x: 9.3, color: C.accent3 },
  ];

  flowSteps.forEach((f) => {
    if (f.x > 8) return; // last one off screen
    s.addShape(pres.shapes.ROUNDED_RECTANGLE, { x: f.x, y: 1.1, w: 1.8, h: 0.85, fill: { color: C.white }, shadow: makeShadow(), rectRadius: 0.08, line: { color: f.color, width: 1.5 } });
    s.addText(f.label, { x: f.x, y: 1.1, w: 1.8, h: 0.85, fontSize: 10, fontFace: "Arial", bold: true, color: C.text, align: "center", valign: "middle", margin: 0 });
  });
  [2.1, 4.5, 6.9].forEach((x) => { s.addText("→", { x, y: 1.25, w: 0.3, h: 0.4, fontSize: 16, fontFace: "Arial", color: C.teal, align: "center", valign: "middle", margin: 0 }); });

  // Key APIs
  s.addText("关键 API（已确认）", { x: 0.4, y: 2.2, w: 9.2, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const apiTable = [
    [{ text: "API", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "用途", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "来源", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "mimics.data.masks.find(name=...)", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "查找指定名称的 Mask", options: { fontSize: 9 } }, { text: "社区代码片段", options: { fontSize: 9 } }],
    [{ text: "mask.get_voxel_buffer()", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "获取 Mask 体素数据（numpy 数组）", options: { fontSize: 9 } }, { text: "社区代码片段", options: { fontSize: 9 } }],
    [{ text: "mask.set_voxel_buffer(arr)", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "导入外部 numpy 数组到 Mask", options: { fontSize: 9 } }, { text: "Materialise 员工确认 (2023)", options: { fontSize: 9 } }],
    [{ text: "NIfTI 导入导出 (GUI)", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "2025 原生功能，替代脚本手动写 affine", options: { fontSize: 9 } }, { text: "官方产品更新页", options: { fontSize: 9 } }],
    [{ text: "Scripting Guide", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "完整 API 文档（Help → Scripting Guide）", options: { fontSize: 9 } }, { text: "内置在 Mimics 中", options: { fontSize: 9 } }],
  ];
  s.addTable(apiTable, { x: 0.4, y: 2.6, w: 9.2, colW: [3.0, 3.8, 2.4], border: { pt: 0.5, color: C.border }, fontFace: "Arial" });

  // Risk and mitigation
  s.addText("风险与应对", { x: 0.4, y: 4.4, w: 9.2, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const riskTable = [
    [{ text: "风险", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "影响", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "应对", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "set_voxel_buffer 空间对齐", options: { fontSize: 9 } }, { text: "标签与 CT 错位 → 训练数据污染", options: { fontSize: 9 } }, { text: "check_geometry.py 检测 + 修复", options: { fontSize: 9 } }],
    [{ text: "Scripting Guide API 不足", options: { fontSize: 9 } }, { text: "自动化程度降低", options: { fontSize: 9 } }, { text: "GUI 手动操作 + 平台脚本补偿", options: { fontSize: 9 } }],
    [{ text: "Mimics 完全不可用", options: { fontSize: 9 } }, { text: "标注流程受阻", options: { fontSize: 9 } }, { text: "切换 3D Slicer / ITK-SNAP 备选", options: { fontSize: 9 } }],
  ];
  s.addTable(riskTable, { x: 0.4, y: 4.8, w: 9.2, colW: [2.8, 3.2, 3.2], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.3, 0.25, 0.25, 0.23] });
})();

// ============================================================
// Slide 12: 实施优先级
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("分阶段实施路线", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const phases = [
    { phase: "A", title: "文件包闭环", desc: "一个病例从候选标签到人工保存，再进入训练快照", status: "👈 当前", statusColor: C.emerald, bgColor: C.emerald, fillRow: true },
    { phase: "B", title: "注册中心 + 快照", desc: "Data Registry、Dataset Snapshot → 同一套数据多任务复用，训练可复现", status: "设计已定", statusColor: C.tagText, fillRow: false },
    { phase: "C", title: "Adapter 稳定", desc: "nnUNet Adapter 先跑通，预留 MONAI/FewShot 接口", status: "设计已定", statusColor: C.tagText, fillRow: false },
    { phase: "D", title: "离线批量推理", desc: "模型版本 + 批量任务 + 候选标签回流 → 闭环运转", status: "后期", statusColor: C.subtext, fillRow: false },
    { phase: "E", title: "统一调度", desc: "Web UI、任务队列、权限、审计 → 数据契约稳定后", status: "后期", statusColor: C.subtext, fillRow: false },
  ];

  const phaseTable = [
    [{ text: "", options: { fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "阶段", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 10 } },
     { text: "目标", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 10 } },
     { text: "状态", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 10 } }],
  ];

  phases.forEach((p) => {
    const bg = p.fillRow ? "EBF9F0" : C.white;
    phaseTable.push([
      { text: p.phase, options: { fill: { color: bg }, fontSize: 14, bold: true, color: p.bgColor, align: "center" } },
      { text: p.title, options: { fill: { color: bg }, fontSize: 11, bold: true } },
      { text: p.desc, options: { fill: { color: bg }, fontSize: 10 } },
      { text: p.status, options: { fill: { color: bg }, fontSize: 10, bold: true, color: p.statusColor } },
    ]);
  });

  s.addTable(phaseTable, { x: 0.4, y: 1.2, w: 9.2, colW: [0.5, 2.2, 4.5, 2.0], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.4, 0.65, 0.55, 0.55, 0.55, 0.55], color: C.text });

  // Current work items
  s.addText("当前阶段（A）具体任务", { x: 0.4, y: 4.35, w: 9.2, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.text, margin: 0 });
  const tasks = [
    [{ text: "任务", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "状态", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "scripts/split_multilabel_to_masks.py", options: { fontSize: 10 } }, { text: "待实现", options: { fontSize: 10 } }],
    [{ text: "scripts/merge_masks_to_multilabel.py", options: { fontSize: 10 } }, { text: "待实现", options: { fontSize: 10 } }],
    [{ text: "scripts/check_geometry.py", options: { fontSize: 10 } }, { text: "待实现", options: { fontSize: 10 } }],
    [{ text: "scripts/package_case.py", options: { fontSize: 10 } }, { text: "待实现", options: { fontSize: 10 } }],
    [{ text: "scripts/hash_package.py / check_case_package.py", options: { fontSize: 10 } }, { text: "✅ 已完成", options: { fontSize: 10, color: C.greenText } }],
  ];
  s.addTable(tasks, { x: 0.4, y: 4.75, w: 9.2, colW: [5.2, 4.0], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.28, 0.25, 0.25, 0.25, 0.25, 0.25] });
})();

// ============================================================
// Slide 13: 已确认的关键决策
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("已确认的关键决策", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  const decisions = [
    { title: "伪标签准入", desc: "默认允许 accepted_pseudo_label 进入训练。取决于器官/任务/模型，默认允许 + 特定排除，而非默认禁止 + 逐项审批" },
    { title: "器官范围", desc: "第一阶段 = v500 所有模型（CT1-16、MR1-8），涵盖全身多处器官，不缩小范围" },
    { title: "全身模型方案", desc: "保持现状：多模型组合（每个子模型独立从 1 编号），后期有条件再实验统一模型" },
    { title: "Mimics POC", desc: "先做调研和准备工作（Scripting Guide API 验证），确认后再启动 POC" },
    { title: "联合学习", desc: "少样本学习 = training 域新 Adapter，与 nnUNet Adapter 平级，需先过生产级实验协议验证" },
    { title: "label_policy 设计", desc: "candidate_label 可通过 allow_status 直接纳入训练，核心原则：provenance 永不造假" },
    { title: "Data Registry + Snapshot", desc: "先不实现但必须记住——这是可追溯和可插拔的前提。手动闭环跑通后再补" },
  ];

  decisions.forEach((d, i) => {
    const y = 1.2 + i * 0.6;
    const accentColor = [C.teal, C.emerald, C.accent3, C.accent1, C.accent2, C.navy, C.subtext][i % 7];
    s.addShape(pres.shapes.RECTANGLE, { x: 0.4, y, w: 0.08, h: 0.48, fill: { color: accentColor } });
    s.addText(d.title, { x: 0.7, y, w: 2.0, h: 0.48, fontSize: 11, fontFace: "Arial", bold: true, color: C.text, valign: "middle", margin: 0 });
    s.addText(d.desc, { x: 2.8, y, w: 6.8, h: 0.48, fontSize: 9, fontFace: "Arial", color: C.subtext, valign: "middle", margin: 0 });
  });
})();

// ============================================================
// Slide 14: 实现前待确认清单
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.lightBg };
  s.addText("实现前待确认清单", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.navy, margin: 0 });
  s.addShape(pres.shapes.RECTANGLE, { x: 0.6, y: 0.85, w: 1.2, h: 0.04, fill: { color: C.teal } });

  // Blocking items
  s.addText("阻塞项（必须确认才能开始）", { x: 0.4, y: 1.1, w: 9.2, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.accent4, margin: 0 });
  const blocking = [
    [{ text: "#", options: { bold: true, fill: { color: C.accent4 }, color: C.white, fontSize: 9 } },
     { text: "事项", options: { bold: true, fill: { color: C.accent4 }, color: C.white, fontSize: 9 } },
     { text: "状态", options: { bold: true, fill: { color: C.accent4 }, color: C.white, fontSize: 9 } }],
    [{ text: "A1", options: { fontSize: 9, bold: true } }, { text: "Mimics 版本 + 许可证类型", options: { fontSize: 9 } }, { text: "❓ 未确认", options: { fontSize: 9, color: C.accent4 } }],
    [{ text: "A2", options: { fontSize: 9, bold: true } }, { text: "Scripting Guide 中 mask 相关 API 清单", options: { fontSize: 9 } }, { text: "❓ 需在 Mimics Help 中查看", options: { fontSize: 9, color: C.accent4 } }],
    [{ text: "A3", options: { fontSize: 9, bold: true } }, { text: "Mimics 能否运行 Python 脚本", options: { fontSize: 9 } }, { text: "❓ 取决于许可证", options: { fontSize: 9, color: C.accent4 } }],
    [{ text: "A4", options: { fontSize: 9, bold: true } }, { text: "第一批 3-5 个病例", options: { fontSize: 9 } }, { text: "❓ 领导确认数据不是瓶颈", options: { fontSize: 9 } }],
    [{ text: "A5", options: { fontSize: 9, bold: true } }, { text: "训练服务器环境（GPU、路径）", options: { fontSize: 9 } }, { text: "❓ 未确认", options: { fontSize: 9 } }],
  ];
  s.addTable(blocking, { x: 0.4, y: 1.5, w: 9.2, colW: [0.5, 5.7, 3.0], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.3, 0.28, 0.28, 0.28, 0.28, 0.28] });

  // Non-blocking
  s.addText("非阻塞项（可立即实现）", { x: 0.4, y: 3.4, w: 9.2, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.emerald, margin: 0 });
  const nonBlocking = [
    [{ text: "#", options: { bold: true, fill: { color: C.emerald }, color: C.white, fontSize: 9 } },
     { text: "模块", options: { bold: true, fill: { color: C.emerald }, color: C.white, fontSize: 9 } },
     { text: "用途", options: { bold: true, fill: { color: C.emerald }, color: C.white, fontSize: 9 } }],
    [{ text: "B1", options: { fontSize: 9, bold: true } }, { text: "split_multilabel_to_masks.py", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "多标签 NIfTI → 逐器官二值 mask", options: { fontSize: 9 } }],
    [{ text: "B2", options: { fontSize: 9, bold: true } }, { text: "merge_masks_to_multilabel.py", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "逐器官 mask → 多标签 NIfTI", options: { fontSize: 9 } }],
    [{ text: "B3", options: { fontSize: 9, bold: true } }, { text: "check_geometry.py", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "shape/spacing/affine 校验 + 自动修复", options: { fontSize: 9 } }],
    [{ text: "B4", options: { fontSize: 9, bold: true } }, { text: "package_case.py", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "生成 Case Package 目录", options: { fontSize: 9 } }],
    [{ text: "B5", options: { fontSize: 9, bold: true } }, { text: "import_case_package.py (Mimics)", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "读 masks → numpy → set_voxel_buffer", options: { fontSize: 9 } }],
    [{ text: "B6", options: { fontSize: 9, bold: true } }, { text: "export_review_package.py (Mimics)", options: { fontSize: 9, fontFace: "Consolas" } }, { text: "get_voxel_buffer → numpy → masks", options: { fontSize: 9 } }],
  ];
  s.addTable(nonBlocking, { x: 0.4, y: 3.75, w: 9.2, colW: [0.5, 4.0, 4.7], border: { pt: 0.5, color: C.border }, fontFace: "Arial", rowH: [0.3, 0.28, 0.28, 0.28, 0.28, 0.28, 0.28] });
})();

// ============================================================
// Slide 15: 时间估算
// ============================================================
(() => {
  const s = pres.addSlide();
  s.background = { color: C.darkBg };
  s.addShape(pres.shapes.RECTANGLE, { x: 0, y: 0, w: 10, h: 0.06, fill: { color: C.teal } });
  s.addText("时间估算", { x: 0.6, y: 0.3, w: 9, h: 0.5, fontSize: 28, fontFace: "Arial", bold: true, color: C.white, margin: 0 });

  // Three scenario cards
  const scenarios = [
    { title: "一切顺利", time: "3-4 周", desc: "A1-A3 秒确认\nAPI 全有\n几何无问题", color: C.emerald },
    { title: "正常", time: "5-6 周", desc: "1-2 个 Mimics 弯路\n1-2 轮调试\n几何对齐需微调", color: C.accent3 },
    { title: "Mimics API 受限", time: "+2-3 周", desc: "降级为 GUI 手动\n或切换到 3D Slicer\n额外的工具适配", color: C.accent4 },
  ];

  scenarios.forEach((sc, i) => {
    const x = 0.4 + i * 3.2;
    s.addShape(pres.shapes.RECTANGLE, { x, y: 1.2, w: 2.9, h: 2.8, fill: { color: C.navy } });
    s.addText(sc.title, { x, y: 1.35, w: 2.9, h: 0.4, fontSize: 14, fontFace: "Arial", bold: true, color: sc.color, align: "center", margin: 0 });
    s.addText(sc.time, { x, y: 1.85, w: 2.9, h: 0.7, fontSize: 32, fontFace: "Arial", bold: true, color: C.white, align: "center", valign: "middle", margin: 0 });
    s.addShape(pres.shapes.RECTANGLE, { x: x + 0.5, y: 2.6, w: 1.9, h: 0.03, fill: { color: sc.color } });
    s.addText(sc.desc, { x, y: 2.8, w: 2.9, h: 1.0, fontSize: 10, fontFace: "Arial", color: C.subtext, align: "center", valign: "top", margin: 0 });
  });

  // Breakdown table
  s.addText("工作量拆解", { x: 0.6, y: 4.2, w: 9, h: 0.35, fontSize: 14, fontFace: "Arial", bold: true, color: C.white, margin: 0 });
  const breakdown = [
    [{ text: "模块", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "工时", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } },
     { text: "信心", options: { bold: true, fill: { color: C.navy }, color: C.white, fontSize: 9 } }],
    [{ text: "平台脚本（B1-B4）", options: { fontSize: 9 } }, { text: "4-5 天", options: { fontSize: 9 } }, { text: "高 — 纯 numpy/nibabel", options: { fontSize: 9 } }],
    [{ text: "Mimics Adapter（B5-B6）", options: { fontSize: 9 } }, { text: "乐观 2 天 / 悲观 2 周", options: { fontSize: 9 } }, { text: "中低 — 依赖 A1-A3", options: { fontSize: 9 } }],
    [{ text: "闭环测试 + 调试", options: { fontSize: 9 } }, { text: "1-2 周", options: { fontSize: 9 } }, { text: "—", options: { fontSize: 9 } }],
    [{ text: "3-5 病例验证", options: { fontSize: 9 } }, { text: "1 周", options: { fontSize: 9 } }, { text: "—", options: { fontSize: 9 } }],
  ];
  s.addTable(breakdown, { x: 0.4, y: 4.55, w: 9.2, colW: [3.5, 3.0, 2.7], border: { pt: 0.5, color: "334155" }, fontFace: "Arial", color: C.white, rowH: [0.3, 0.25, 0.25, 0.25, 0.25] });

  s.addText("最大减速带不是代码量，是 Mimics 确认和几何对齐调试", { x: 0.6, y: 5.35, w: 9, h: 0.2, fontSize: 9, fontFace: "Arial", italic: true, color: C.subtext, margin: 0 });
})();

// ============================================================
// Write file
// ============================================================
pres.writeFile({ fileName: "/Users/ruanshijian/SegmentationPlatform/SegmentationPlatform_Architecture.pptx" })
  .then(() => console.log("PPT saved"))
  .catch(err => console.error(err));
