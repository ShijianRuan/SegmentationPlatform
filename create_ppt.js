const fs = require("fs");
const path = require("path");
const pptxgen = require("pptxgenjs");

const pptx = new pptxgen();
pptx.layout = "LAYOUT_16x9";
pptx.author = "SegmentationPlatform";
pptx.subject = "Medical image segmentation platform architecture";
pptx.title = "Segmentation Platform Architecture";
pptx.company = "SegmentationPlatform";
pptx.lang = "zh-CN";
pptx.theme = {
  headFontFace: "Arial",
  bodyFontFace: "Arial",
  lang: "zh-CN",
};

const OUT_ROOT = "/Users/ruanshijian/SegmentationPlatform/SegmentationPlatform_Architecture.pptx";
const OUT_WORKSPACE =
  "/Users/ruanshijian/SegmentationPlatform/outputs/019e9b11-9a8a-7ec2-9e1e-1448f3387af2/presentations/segmentation-platform-redesign/output/segmentation-platform-architecture-redesign.pptx";

const C = {
  bone: "F7F2EA",
  paper: "FFFCF7",
  ink: "172026",
  muted: "5F6872",
  hair: "D8D0C6",
  pale: "ECE7DE",
  teal: "1F9D8A",
  tealDark: "106B70",
  blue: "315F9F",
  blueSoft: "E7EEF8",
  green: "20805D",
  greenSoft: "E7F2EC",
  red: "BC4749",
  redSoft: "F6E4E2",
  amber: "B98520",
  amberSoft: "F5EBD6",
  violet: "6656A8",
  violetSoft: "EAE7F4",
  dark: "101820",
  dark2: "1C2934",
  white: "FFFFFF",
};

const F = {
  title: "Arial",
  body: "Arial",
  mono: "Courier New",
};

function bg(slide, color = C.bone) {
  slide.background = { color };
  slide.addShape(pptx.ShapeType.rect, {
    x: 0,
    y: 0,
    w: 10,
    h: 5.625,
    fill: { color },
    line: { color },
  });
}

function text(slide, value, x, y, w, h, opts = {}) {
  slide.addText(value, {
    x,
    y,
    w,
    h,
    fontFace: opts.mono ? F.mono : opts.title ? F.title : F.body,
    fontSize: opts.size ?? 12,
    bold: opts.bold ?? false,
    italic: opts.italic ?? false,
    color: opts.color ?? C.ink,
    align: opts.align ?? "left",
    valign: opts.valign ?? "mid",
    margin: opts.margin ?? 0.02,
    breakLine: false,
    fit: "shrink",
  });
}

function title(slide, eyebrow, headline, note) {
  text(slide, eyebrow, 0.55, 0.33, 2.4, 0.18, {
    size: 7.5,
    bold: true,
    color: C.tealDark,
    margin: 0,
  });
  text(slide, headline, 0.55, 0.58, 8.35, 0.48, {
    size: 22,
    bold: true,
    color: C.ink,
    margin: 0,
  });
  if (note) {
    text(slide, note, 0.58, 1.03, 7.6, 0.22, {
      size: 9,
      color: C.muted,
      margin: 0,
    });
  }
}

function footer(slide, n) {
  slide.addShape(pptx.ShapeType.line, {
    x: 0.55,
    y: 5.28,
    w: 8.9,
    h: 0,
    line: { color: C.hair, width: 0.6 },
  });
  text(slide, `Segmentation Platform | ${String(n).padStart(2, "0")}`, 0.55, 5.36, 8.9, 0.14, {
    size: 7,
    color: "8B8175",
    margin: 0,
  });
}

function rect(slide, x, y, w, h, fill = C.paper, line = C.hair, radius = 0.06) {
  slide.addShape(pptx.ShapeType.roundRect, {
    x,
    y,
    w,
    h,
    rectRadius: radius,
    fill: { color: fill },
    line: { color: line, width: 0.8 },
  });
}

function tag(slide, label, x, y, w, color, fill) {
  rect(slide, x, y, w, 0.24, fill ?? C.paper, color, 0.08);
  text(slide, label, x, y + 0.035, w, 0.13, {
    size: 7.2,
    bold: true,
    color,
    align: "center",
    margin: 0,
  });
}

function node(slide, label, sub, x, y, w, h, color, opts = {}) {
  rect(slide, x, y, w, h, opts.fill ?? C.paper, color, 0.08);
  if (opts.band) {
    slide.addShape(pptx.ShapeType.rect, {
      x,
      y,
      w: 0.08,
      h,
      fill: { color },
      line: { color },
    });
  }
  text(slide, label, x + 0.12, y + 0.12, w - 0.24, 0.22, {
    size: opts.titleSize ?? 11,
    bold: true,
    color: opts.titleColor ?? C.ink,
    margin: 0,
    align: opts.align ?? "left",
  });
  if (sub) {
    text(slide, sub, x + 0.12, y + 0.46, w - 0.24, h - 0.55, {
      size: opts.bodySize ?? 8.1,
      color: opts.bodyColor ?? C.muted,
      margin: 0,
      valign: "top",
      align: opts.align ?? "left",
    });
  }
}

function arrow(slide, x1, y1, x2, y2, color = C.hair, width = 1.1) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color, width, endArrowType: "triangle" },
  });
}

function line(slide, x1, y1, x2, y2, color = C.hair, width = 1) {
  slide.addShape(pptx.ShapeType.line, {
    x: x1,
    y: y1,
    w: x2 - x1,
    h: y2 - y1,
    line: { color, width },
  });
}

function miniTable(slide, rows, x, y, colW, rowH = 0.32, accent = C.dark2) {
  const body = rows.map((row, ri) =>
    row.map((cell, ci) => ({
      text: String(cell),
      options: {
        fontFace: ci === 0 && ri > 0 ? F.mono : F.body,
        fontSize: ri === 0 ? 7.8 : 7.3,
        bold: ri === 0 || (ci === 0 && ri > 0),
        color: ri === 0 ? C.white : C.ink,
        fill: { color: ri === 0 ? accent : ri % 2 ? C.paper : "F1EEE7" },
        margin: 0.05,
        valign: "mid",
        fit: "shrink",
      },
    }))
  );
  slide.addTable(body, {
    x,
    y,
    w: colW.reduce((a, b) => a + b, 0),
    colW,
    rowH,
    border: { pt: 0.35, color: C.hair },
  });
}

function ctSlice(slide, x, y, scale = 1) {
  const w = 2.6 * scale;
  const h = 2.6 * scale;
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y,
    w,
    h,
    fill: { color: "24313D" },
    line: { color: "EBE7DF", width: 1.2 },
  });
  slide.addShape(pptx.ShapeType.ellipse, {
    x: x + 0.22 * scale,
    y: y + 0.2 * scale,
    w: w - 0.44 * scale,
    h: h - 0.42 * scale,
    fill: { color: "2E3D49" },
    line: { color: "97A4AF", width: 0.5 },
  });
  slide.addShape(pptx.ShapeType.arc, {
    x: x + 0.42 * scale,
    y: y + 0.42 * scale,
    w: 1.75 * scale,
    h: 1.5 * scale,
    adjustPoint: 0.25,
    line: { color: "CAD2D9", width: 0.6, transparency: 25 },
  });
  slide.addShape(pptx.ShapeType.ellipse, {
    x: x + 0.83 * scale,
    y: y + 0.88 * scale,
    w: 0.58 * scale,
    h: 0.72 * scale,
    fill: { color: C.red },
    line: { color: C.red },
  });
  slide.addShape(pptx.ShapeType.ellipse, {
    x: x + 1.35 * scale,
    y: y + 0.92 * scale,
    w: 0.45 * scale,
    h: 0.58 * scale,
    fill: { color: C.teal },
    line: { color: C.teal },
  });
  slide.addShape(pptx.ShapeType.ellipse, {
    x: x + 1.05 * scale,
    y: y + 1.47 * scale,
    w: 0.55 * scale,
    h: 0.32 * scale,
    fill: { color: C.amber },
    line: { color: C.amber },
  });
}

function slide1() {
  const s = pptx.addSlide();
  bg(s, C.dark);
  s.addShape(pptx.ShapeType.rect, { x: 0, y: 0, w: 4.35, h: 5.625, fill: { color: "131F28" }, line: { color: "131F28" } });
  text(s, "SEGMENTATION PLATFORM", 0.62, 0.56, 2.6, 0.18, { size: 7.2, bold: true, color: "8EDAD5", margin: 0 });
  text(s, "分割平台\n不是三条管线", 0.62, 1.2, 3.6, 1.05, { size: 25, bold: true, color: C.white, margin: 0, valign: "top" });
  text(s, "而是一套标签生命周期治理系统", 0.62, 2.5, 3.35, 0.3, { size: 13.5, color: "D9E1E7", margin: 0 });
  text(s, "标注、训练、候选标签回流，都围绕同一组稳定对象发生。", 0.64, 3.92, 3.0, 0.45, { size: 9.5, color: "AEBBC5", margin: 0, valign: "top" });
  text(s, "2026-06-08", 0.64, 4.9, 2.2, 0.18, { size: 8.5, color: "8997A3", margin: 0 });

  ctSlice(s, 5.65, 0.68, 1.3);
  const labels = [
    ["labeling", 5.02, 4.18, C.blue],
    ["training", 6.55, 4.18, C.green],
    ["label_generation", 8.08, 4.18, C.amber],
  ];
  labels.forEach(([l, x, y, c]) => tag(s, l, x, y, 1.18, c, "172533"));
  text(s, "Case  /  Image  /  Label  /  Snapshot  /  Model", 5.02, 4.7, 3.98, 0.18, {
    size: 8,
    color: "BBC6CE",
    align: "center",
    margin: 0,
  });
}

function slide2() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "WHY CHANGE", "现在的问题不是缺一条 pipeline，而是边界会互相污染", "如果架构只按“标注 / 训练 / 伪标签脚本”拆，后面很快会找不到责任归属。");
  text(s, "三类变化会同时发生", 0.65, 1.55, 2.2, 0.35, { size: 17, bold: true, color: C.ink, margin: 0 });
  const symptoms = [
    ["数据区域变化", "CT/MR、全身/局部、不同模型组合，不能假设每个任务看到同一组器官。", C.blue],
    ["训练任务变化", "同一套数据可给肺任务、肝胆任务、全身组合任务使用，label id 必须任务级定义。", C.green],
    ["标签来源变化", "人工 confirmed、公开数据、自训模型、候选伪标签都可能进入闭环，但来源不能被抹平。", C.amber],
  ];
  symptoms.forEach(([h, b, c], i) => {
    const y = 1.47 + i * 1.05;
    slideNumberBlob(s, i + 1, 3.52, y + 0.1, c);
    node(s, h, b, 4.0, y, 5.15, 0.78, c, { fill: C.paper, band: true, bodySize: 8.2 });
  });
  node(s, "架构判断", "先稳定对象关系和责任边界，再讨论具体工具。Mimics 与 nnUNet 都应该被 Adapter 包住。", 0.7, 4.35, 8.65, 0.58, C.red, { fill: C.redSoft, titleSize: 10.5, bodySize: 8.2 });
  footer(s, 2);
}

function slideNumberBlob(slide, n, x, y, color) {
  slide.addShape(pptx.ShapeType.ellipse, {
    x,
    y,
    w: 0.42,
    h: 0.42,
    fill: { color },
    line: { color },
  });
  text(slide, String(n), x, y + 0.06, 0.42, 0.18, { size: 10.5, bold: true, color: C.white, align: "center", margin: 0 });
}

function slide3() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "OBJECT MAP", "平台中心：五类对象，而不是某个工具", "每个后续模块都应该能回答：它读写哪个对象？改变哪个状态？留下什么证据？");
  const centerX = 4.05;
  const centerY = 2.05;
  node(s, "LabelArtifact", "标签文件 + 状态 + 来源 + QC 证据", centerX, centerY, 2.15, 0.95, C.teal, { fill: "E7F6F5", titleSize: 13, bodySize: 8.6, align: "center" });
  const surrounding = [
    ["Case", "病例身份与元数据", 0.78, 1.25, C.blue],
    ["ImageArtifact", "CT/MR 图像与空间几何", 0.78, 3.45, C.blue],
    ["DatasetSnapshot", "冻结训练视图", 7.0, 1.25, C.green],
    ["TrainingTask", "任务级 label map 和策略", 7.0, 3.45, C.green],
    ["ModelRecord", "训练产物与推理来源", 4.05, 4.15, C.violet],
  ];
  surrounding.forEach(([h, b, x, y, c]) => node(s, h, b, x, y, 2.05, 0.78, c, { fill: C.paper, titleSize: 11, bodySize: 7.8 }));
  arrow(s, 2.83, 1.64, centerX, centerY + 0.25, C.blue);
  arrow(s, 2.83, 3.84, centerX, centerY + 0.62, C.blue);
  arrow(s, centerX + 2.15, centerY + 0.25, 7.0, 1.64, C.green);
  arrow(s, centerX + 2.15, centerY + 0.62, 7.0, 3.84, C.green);
  arrow(s, 5.12, 4.15, 5.12, 3.0, C.violet);
  text(s, "工具只能接入对象，不能重新定义对象", 2.65, 1.48, 4.0, 0.22, { size: 10, bold: true, color: C.tealDark, align: "center", margin: 0 });
  footer(s, 3);
}

function slide4() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "DOMAIN BOUNDARY", "三大域的名字不是为了对称，而是为了防止误放代码", "每个域都有明确的输入、输出和不负责事项。");
  const lanes = [
    ["labeling", "生产 / 审核 / 导回标签", "Case Package\nMimics import/export\ngeometry check\nverified_label", "不决定训练编号", 0.62, C.blue, C.blueSoft],
    ["training", "消费标签并产出模型", "Dataset Snapshot\nTaskLabelMap\nnnUNet Adapter\nModel Record", "不治理标签来源", 3.65, C.green, C.greenSoft],
    ["label_generation", "生成候选并回流", "offline inference\ncandidate_label\nQC report\naccepted/rejected", "不等于伪标签脚本", 6.68, C.amber, C.amberSoft],
  ];
  lanes.forEach(([name, claim, body, not, x, c, fill]) => {
    rect(s, x, 1.28, 2.72, 3.62, fill, c, 0.1);
    text(s, name, x + 0.18, 1.5, 2.3, 0.25, { size: 15, bold: true, color: c, margin: 0 });
    text(s, claim, x + 0.18, 1.9, 2.3, 0.22, { size: 9.5, bold: true, color: C.ink, margin: 0 });
    line(s, x + 0.18, 2.25, x + 2.5, 2.25, c, 1.2);
    text(s, body, x + 0.18, 2.55, 2.3, 1.12, { size: 9, color: C.ink, margin: 0, valign: "top" });
    tag(s, not, x + 0.18, 4.26, 2.1, C.red, C.redSoft);
  });
  footer(s, 4);
}

function slide5() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "LABEL LIFECYCLE", "QC 是闸门，不是标签状态", "标签状态描述“它现在是什么”，QC 描述“它为什么能或不能进入下一步”。");
  const y = 2.02;
  const states = [
    ["source_label", 0.55, C.blue],
    ["candidate_label", 2.42, C.amber],
    ["draft_label", 4.38, C.teal],
    ["verified_label", 6.26, C.green],
  ];
  states.forEach(([label, x, c]) => {
    node(s, label, "", x, y, 1.45, 0.52, c, { fill: C.paper, titleSize: 8.4, align: "center" });
  });
  arrow(s, 2.0, y + 0.26, 2.42, y + 0.26, C.blue);
  arrow(s, 3.87, y + 0.26, 4.38, y + 0.26, C.amber);
  arrow(s, 5.83, y + 0.26, 6.26, y + 0.26, C.teal);
  node(s, "accepted_pseudo_label", "", 6.26, 3.25, 2.0, 0.52, C.green, { fill: C.greenSoft, titleSize: 7.7, align: "center" });
  node(s, "rejected_label", "", 2.42, 3.25, 1.45, 0.52, C.red, { fill: C.redSoft, titleSize: 8.4, align: "center" });
  arrow(s, 3.15, y + 0.52, 3.15, 3.25, C.red);
  arrow(s, 4.06, y + 0.52, 6.26, 3.25, C.green);
  const gates = [
    ["空间 QC", "shape / spacing / origin / direction / affine", 0.72],
    ["内容 QC", "空标签、越界、器官覆盖、异常体积", 3.44],
    ["准入 QC", "allow_status、trusted_sources、任务策略", 6.15],
  ];
  gates.forEach(([h, b, x], i) => {
    rect(s, x, 4.28, 2.35, 0.55, i === 0 ? C.blueSoft : i === 1 ? C.amberSoft : C.greenSoft, i === 0 ? C.blue : i === 1 ? C.amber : C.green, 0.08);
    text(s, h, x + 0.12, 4.36, 0.7, 0.16, { size: 8, bold: true, color: i === 0 ? C.blue : i === 1 ? C.amber : C.green, margin: 0 });
    text(s, b, x + 0.92, 4.34, 1.25, 0.2, { size: 6.8, color: C.ink, margin: 0, fit: "shrink" });
  });
  footer(s, 5);
}

function slide6() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "LABEL SPACE", "统一器官名称，不等于统一 label id", "这个设计的价值是：同一套病例数据可以被多个任务复用。");
  const levels = [
    ["anatomy_vocabulary", "语义层", "liver = 肝脏\n全平台稳定，无数字", 1.28, C.blue, C.blueSoft],
    ["review_label_map", "工具层", "Mimics 中 liver = 10\n服务人工审核，可换工具", 2.6, C.amber, C.amberSoft],
    ["task_label_maps", "训练层", "CT5_Liver: liver = 2\nCT_All: liver 可为另一个编号", 3.92, C.green, C.greenSoft],
  ];
  levels.forEach(([name, level, body, y, c, fill], i) => {
    rect(s, 0.92, y, 8.2, 0.78, fill, c, 0.1);
    text(s, level, 1.15, y + 0.18, 0.85, 0.22, { size: 10, bold: true, color: c, margin: 0 });
    text(s, name, 2.2, y + 0.16, 2.35, 0.24, { size: 11, bold: true, color: C.ink, mono: true, margin: 0 });
    text(s, body, 5.05, y + 0.12, 3.55, 0.42, { size: 8.4, color: C.ink, margin: 0, valign: "mid" });
    if (i < levels.length - 1) arrow(s, 5.0, y + 0.78, 5.0, y + 1.0, c);
  });
  text(s, "Case Package 只带 anatomy + review；task label map 在 Dataset Snapshot 中冻结。", 1.08, 4.98, 7.9, 0.18, {
    size: 9.2,
    bold: true,
    color: C.tealDark,
    align: "center",
    margin: 0,
  });
  footer(s, 6);
}

function slide7() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "CASE PACKAGE", "Case Package 是标注交换契约，不是训练数据集", "它让文件阶段可搬运、自包含；训练阶段另行冻结 Dataset Snapshot。");
  rect(s, 0.7, 1.3, 3.45, 3.55, C.dark2, C.dark2, 0.08);
  text(
    s,
    "case_package/\n├─ manifest.json\n├─ images/image.nii.gz\n├─ labels/\n│  ├─ draft_label.nii.gz\n│  ├─ verified_label.nii.gz\n│  └─ masks/liver.nii.gz\n├─ config/\n│  ├─ anatomy_vocabulary.yaml\n│  └─ review_label_map.yaml\n├─ reports/\n└─ provenance/",
    0.93,
    1.55,
    3.0,
    2.9,
    { size: 8.0, color: "EDF3F7", mono: true, margin: 0, valign: "top" }
  );
  node(s, "Registry", "病例、图像、标签来源、审计记录。\n第一阶段可后置，但概念不能丢。", 4.78, 2.0, 1.8, 1.05, C.teal, { fill: "E8F5F4", titleSize: 12, bodySize: 7.7, align: "center" });
  node(s, "Dataset Snapshot", "按任务冻结：样本、标签准入、task_label_map、训练配置。", 7.25, 2.0, 1.95, 1.05, C.green, { fill: C.greenSoft, titleSize: 11.5, bodySize: 7.7, align: "center" });
  arrow(s, 4.15, 2.53, 4.78, 2.53, C.teal);
  arrow(s, 6.58, 2.53, 7.25, 2.53, C.green);
  tag(s, "不放 task_label_maps.yaml", 5.0, 3.68, 2.5, C.red, C.redSoft);
  text(s, "否则同一病例会被某个训练任务的编号锁死。", 5.04, 4.03, 2.55, 0.26, { size: 8.5, color: C.muted, margin: 0, align: "center" });
  footer(s, 7);
}

function slide8() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "ADAPTERS", "工具适配层让平台不绑定 Mimics 或 nnUNet", "稳定对象在中间，工具只通过 Adapter 读写对象。");
  node(s, "Platform Contract", "Case / ImageArtifact / LabelArtifact\nDatasetSnapshot / ModelRecord\nlabel_policy / provenance", 3.35, 1.88, 3.0, 1.25, C.teal, { fill: "E8F5F4", titleSize: 14, bodySize: 8.4, align: "center" });
  const ports = [
    ["Mimics Adapter", "导入/导出 review package", 0.72, 1.16, C.blue, C.blueSoft],
    ["nnUNet Adapter", "现有训练管线的第一落点", 6.95, 1.16, C.green, C.greenSoft],
    ["label_generation Adapter", "离线推理与 candidate 回流", 0.72, 3.65, C.amber, C.amberSoft],
    ["FewShot Adapter", "实验验证后再生产化", 6.95, 3.65, C.violet, C.violetSoft],
  ];
  ports.forEach(([h, b, x, y, c, fill]) => {
    node(s, h, b, x, y, 2.2, 0.85, c, { fill, titleSize: 10.5, bodySize: 7.8 });
    arrow(s, x < 3 ? x + 2.2 : x, y + 0.42, x < 3 ? 3.35 : 6.35, 2.5, c);
  });
  text(s, "新工具 = 新 Adapter；平台数据契约不变。", 3.05, 4.45, 3.6, 0.24, { size: 12, bold: true, color: C.tealDark, align: "center", margin: 0 });
  footer(s, 8);
}

function slide9() {
  const s = pptx.addSlide();
  bg(s);
  title(s, "MATURITY", "Mimics 和 FewShot 是两种不同成熟度的工作", "一个是标注工具集成 POC，一个是研究能力到生产 Adapter 的验证路线。");
  rect(s, 0.72, 1.35, 4.05, 3.62, C.blueSoft, C.blue, 0.1);
  text(s, "Mimics POC", 1.0, 1.72, 2.2, 0.28, { size: 17, bold: true, color: C.blue, margin: 0 });
  text(s, "目标：证明导入、人工修正、导出、几何一致，能登记为 verified_label。", 1.0, 2.28, 3.35, 0.38, { size: 9.2, color: C.ink, margin: 0, valign: "top" });
  miniTable(
    s,
    [
      ["检查", "判断"],
      ["shape mismatch", "硬失败"],
      ["affine / spacing", "可检测，条件满足时修复"],
      ["API / license", "启动 POC 前确认"],
    ],
    1.0,
    3.05,
    [1.65, 2.35],
    0.35,
    C.blue
  );
  rect(s, 5.23, 1.35, 4.05, 3.62, C.violetSoft, C.violet, 0.1);
  text(s, "FewShot path", 5.52, 1.72, 2.2, 0.28, { size: 17, bold: true, color: C.violet, margin: 0 });
  text(s, "目标：验证少样本是否能成为 training 域的新 Adapter，而不是现在就承诺生产可用。", 5.52, 2.28, 3.35, 0.38, { size: 9.2, color: C.ink, margin: 0, valign: "top" });
  miniTable(
    s,
    [
      ["实验", "要求"],
      ["N-shot", "1 / 3 / 5 / 10 / 20"],
      ["对照", "全监督 / 同数据量 / 微调"],
      ["准入", "Dice >= 90% full baseline"],
    ],
    5.52,
    3.05,
    [1.55, 2.45],
    0.35,
    C.violet
  );
  footer(s, 9);
}

function slide10() {
  const s = pptx.addSlide();
  bg(s, C.dark);
  text(s, "FIRST MILESTONE", 0.7, 0.54, 2.0, 0.16, { size: 7.5, bold: true, color: "8EDAD5", margin: 0 });
  text(s, "第一阶段只做一件事：离线文件包闭环", 0.7, 0.9, 7.5, 0.45, { size: 25, bold: true, color: C.white, margin: 0 });
  text(s, "从 candidate_label 到人工确认，再到 Dataset Snapshot 和 nnUNet 训练。先让链路真实跑通，再补 Registry、Web UI 和统一调度。", 0.72, 1.48, 7.6, 0.38, {
    size: 10.2,
    color: "C8D3DC",
    margin: 0,
    valign: "top",
  });
  const steps = [
    ["1", "package_case", "生成可审阅病例包"],
    ["2", "Mimics review", "导入、保存、导回"],
    ["3", "check_geometry", "shape/affine 证据"],
    ["4", "snapshot", "冻结任务级标签视图"],
    ["5", "nnUNet train", "跑通训练与模型记录"],
  ];
  steps.forEach(([n, h, b], i) => {
    const x = 0.72 + i * 1.78;
    slideNumberBlob(s, n, x, 2.65, [C.teal, C.blue, C.amber, C.green, C.violet][i]);
    text(s, h, x, 3.22, 1.28, 0.2, { size: 9.5, bold: true, color: C.white, align: "center", margin: 0 });
    text(s, b, x - 0.12, 3.56, 1.55, 0.28, { size: 7.5, color: "AEBBC5", align: "center", margin: 0 });
    if (i < steps.length - 1) arrow(s, x + 0.5, 2.86, x + 1.55, 2.86, "6F7D88", 1.0);
  });
  rect(s, 1.15, 4.55, 7.7, 0.55, "172633", "42515E", 0.08);
  text(s, "开发落点：adapters/mimics、adapters/label_generation、adapters/nnunet、pipelines/nnunet、scripts", 1.3, 4.75, 7.4, 0.16, {
    size: 8.5,
    color: "DCE6EC",
    align: "center",
    margin: 0,
  });
}

[
  slide1,
  slide2,
  slide3,
  slide4,
  slide5,
  slide6,
  slide7,
  slide8,
  slide9,
  slide10,
].forEach((fn) => fn());

fs.mkdirSync(path.dirname(OUT_WORKSPACE), { recursive: true });

pptx.writeFile({ fileName: OUT_ROOT }).then(() => {
  fs.copyFileSync(OUT_ROOT, OUT_WORKSPACE);
});
