const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, HeadingLevel, BorderStyle, WidthType,
  ShadingType, VerticalAlign, PageNumber, PageBreak, LevelFormat,
  TableOfContents, ExternalHyperlink
} = require('docx');
const fs = require('fs');

// ── Color Palette ──────────────────────────────────────────────────────────────
const C = {
  red:       "E53935",   // 小红书品牌红
  redLight:  "FFEBEE",   // 浅红背景
  redMid:    "FFCDD2",   // 中红背景
  darkGray:  "212121",   // 正文深灰
  midGray:   "616161",   // 次级文字
  lightGray: "F5F5F5",   // 表格斑马行
  border:    "E0E0E0",   // 边框色
  white:     "FFFFFF",
  blue:      "1565C0",   // 技术架构蓝
  blueLight: "E3F2FD",
  green:     "2E7D32",   // 成功/优势
  greenLight:"E8F5E9",
  orange:    "E65100",   // 警告/劣势
  orangeLight:"FFF3E0",
  purple:    "6A1B9A",
  purpleLight:"F3E5F5",
};

const border = { style: BorderStyle.SINGLE, size: 1, color: C.border };
const borders = { top: border, bottom: border, left: border, right: border };
const noBorders = {
  top:    { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  bottom: { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  left:   { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
  right:  { style: BorderStyle.NONE, size: 0, color: "FFFFFF" },
};

// ── Helpers ────────────────────────────────────────────────────────────────────

function h1(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_1,
    spacing: { before: 400, after: 160 },
    children: [new TextRun({ text, bold: true, size: 36, color: C.red, font: "Arial" })],
    border: { bottom: { style: BorderStyle.SINGLE, size: 8, color: C.red, space: 6 } },
  });
}

function h2(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_2,
    spacing: { before: 320, after: 120 },
    children: [new TextRun({ text, bold: true, size: 28, color: C.darkGray, font: "Arial" })],
  });
}

function h3(text) {
  return new Paragraph({
    heading: HeadingLevel.HEADING_3,
    spacing: { before: 240, after: 80 },
    children: [new TextRun({ text, bold: true, size: 24, color: C.blue, font: "Arial" })],
  });
}

function para(text, opts = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100 },
    children: [new TextRun({ text, size: 22, color: C.darkGray, font: "Arial", ...opts })],
  });
}

function paraRuns(runs, spacing = {}) {
  return new Paragraph({
    spacing: { before: 60, after: 100, ...spacing },
    children: runs.map(r =>
      typeof r === 'string'
        ? new TextRun({ text: r, size: 22, color: C.darkGray, font: "Arial" })
        : new TextRun({ size: 22, font: "Arial", color: C.darkGray, ...r })
    ),
  });
}

function bullet(text, opts = {}) {
  return new Paragraph({
    numbering: { reference: "bullets", level: 0 },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, size: 22, color: C.darkGray, font: "Arial", ...opts })],
  });
}

function bullet2(text) {
  return new Paragraph({
    numbering: { reference: "bullets2", level: 0 },
    spacing: { before: 30, after: 30 },
    children: [new TextRun({ text, size: 20, color: C.midGray, font: "Arial" })],
  });
}

function numbered(text) {
  return new Paragraph({
    numbering: { reference: "numbers", level: 0 },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, size: 22, color: C.darkGray, font: "Arial" })],
  });
}

function gap(pts = 120) {
  return new Paragraph({ spacing: { before: 0, after: pts }, children: [] });
}

function pageBreak() {
  return new Paragraph({ children: [new PageBreak()] });
}

function colorBox(text, fillColor, textColor = C.darkGray) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({ children: [new TableCell({
      borders: noBorders,
      width: { size: 9360, type: WidthType.DXA },
      shading: { fill: fillColor, type: ShadingType.CLEAR },
      margins: { top: 160, bottom: 160, left: 200, right: 200 },
      children: [new Paragraph({
        spacing: { before: 0, after: 0 },
        children: [new TextRun({ text, size: 22, color: textColor, font: "Arial" })],
      })],
    })]})],
  });
}

function infoBox(label, content, fillColor = C.blueLight, labelColor = C.blue) {
  return new Table({
    width: { size: 9360, type: WidthType.DXA },
    columnWidths: [9360],
    rows: [new TableRow({ children: [new TableCell({
      borders: { top: { style: BorderStyle.SINGLE, size: 6, color: labelColor }, bottom: border, left: { style: BorderStyle.SINGLE, size: 6, color: labelColor }, right: border },
      width: { size: 9360, type: WidthType.DXA },
      shading: { fill: fillColor, type: ShadingType.CLEAR },
      margins: { top: 140, bottom: 140, left: 200, right: 200 },
      children: [
        new Paragraph({ spacing: { before: 0, after: 60 }, children: [new TextRun({ text: label, bold: true, size: 22, color: labelColor, font: "Arial" })] }),
        new Paragraph({ spacing: { before: 0, after: 0 }, children: [new TextRun({ text: content, size: 21, color: C.darkGray, font: "Arial" })] }),
      ],
    })]})],
  });
}

function makeTable(headers, rows, colWidths) {
  const totalW = colWidths.reduce((a, b) => a + b, 0);
  const hRow = new TableRow({
    tableHeader: true,
    children: headers.map((h, i) => new TableCell({
      borders,
      width: { size: colWidths[i], type: WidthType.DXA },
      shading: { fill: C.red, type: ShadingType.CLEAR },
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      verticalAlign: VerticalAlign.CENTER,
      children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: h, bold: true, size: 20, color: C.white, font: "Arial" })]
      })],
    })),
  });
  const dataRows = rows.map((row, ri) =>
    new TableRow({ children: row.map((cell, ci) => new TableCell({
      borders,
      width: { size: colWidths[ci], type: WidthType.DXA },
      shading: { fill: ri % 2 === 0 ? C.white : C.lightGray, type: ShadingType.CLEAR },
      margins: { top: 80, bottom: 80, left: 120, right: 120 },
      children: [new Paragraph({
        spacing: { before: 0, after: 0 },
        children: [new TextRun({ text: String(cell), size: 20, color: C.darkGray, font: "Arial" })]
      })],
    })) })
  );
  return new Table({ width: { size: totalW, type: WidthType.DXA }, columnWidths: colWidths, rows: [hRow, ...dataRows] });
}

function sectionTag(num, title) {
  return new Paragraph({
    spacing: { before: 0, after: 80 },
    children: [
      new TextRun({ text: `  ${num}  `, bold: true, size: 22, color: C.white, font: "Arial", highlight: undefined,
        shading: { type: ShadingType.CLEAR, fill: C.red } }),
      new TextRun({ text: `  ${title}`, bold: true, size: 26, color: C.red, font: "Arial" }),
    ],
  });
}

// ── Document ───────────────────────────────────────────────────────────────────

const doc = new Document({
  numbering: {
    config: [
      { reference: "bullets",  levels: [{ level: 0, format: LevelFormat.BULLET,  text: "•", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
      { reference: "bullets2", levels: [{ level: 0, format: LevelFormat.BULLET,  text: "◦", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 960, hanging: 300 } } } }] },
      { reference: "numbers",  levels: [{ level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 600, hanging: 300 } } } }] },
    ],
  },
  styles: {
    default: { document: { run: { font: "Arial", size: 22, color: C.darkGray } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run:  { size: 36, bold: true, font: "Arial", color: C.red },
        paragraph: { spacing: { before: 400, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run:  { size: 28, bold: true, font: "Arial", color: C.darkGray },
        paragraph: { spacing: { before: 320, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run:  { size: 24, bold: true, font: "Arial", color: C.blue },
        paragraph: { spacing: { before: 240, after: 80 }, outlineLevel: 2 } },
    ],
  },

  sections: [{
    properties: {
      page: {
        size: { width: 11906, height: 16838 },
        margin: { top: 1440, right: 1260, bottom: 1440, left: 1260 },
      },
    },
    headers: {
      default: new Header({ children: [
        new Paragraph({
          alignment: AlignmentType.RIGHT,
          border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: C.red, space: 4 } },
          children: [new TextRun({ text: "小红书创作者智能诊断平台 · 产品需求文档 (PRD) v1.5", size: 18, color: C.midGray, font: "Arial" })],
        }),
      ]}),
    },
    footers: {
      default: new Footer({ children: [
        new Paragraph({
          alignment: AlignmentType.CENTER,
          border: { top: { style: BorderStyle.SINGLE, size: 4, color: C.border, space: 4 } },
          children: [
            new TextRun({ text: "机密文件 · 仅供内部使用    第 ", size: 18, color: C.midGray, font: "Arial" }),
            new TextRun({ children: [PageNumber.CURRENT], size: 18, color: C.midGray, font: "Arial" }),
            new TextRun({ text: " 页", size: 18, color: C.midGray, font: "Arial" }),
          ],
        }),
      ]}),
    },

    children: [
      // ══════════════════════════════════════════════════════════════════════════
      // COVER PAGE
      // ══════════════════════════════════════════════════════════════════════════
      gap(800),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "🌟 小红书创作者", bold: true, size: 72, color: C.red, font: "Arial" })],
      }),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "智能诊断与成长平台", bold: true, size: 64, color: C.darkGray, font: "Arial" })],
      }),
      gap(80),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "NoteAI Pro · 产品需求文档 (PRD)", size: 30, color: C.midGray, font: "Arial" })],
      }),
      gap(40),
      new Paragraph({
        alignment: AlignmentType.CENTER,
        children: [new TextRun({ text: "版本 v1.5  ·  保密等级：内部机密", size: 22, color: C.midGray, font: "Arial" })],
      }),
      gap(600),
      new Table({
        width: { size: 9386, type: WidthType.DXA },
        columnWidths: [2346, 2346, 2346, 2348],
        rows: [new TableRow({ children: [
          ...[["文档版本","v1.5"],["撰写日期","2026-05-06"],["文档状态","迭代中"],["保密等级","内部机密"]].map(([k,v]) =>
            new TableCell({
              borders: noBorders,
              width: { size: 2346, type: WidthType.DXA },
              shading: { fill: C.redLight, type: ShadingType.CLEAR },
              margins: { top: 120, bottom: 120, left: 120, right: 120 },
              children: [
                new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: k, size: 18, color: C.midGray, font: "Arial" })] }),
                new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ text: v, bold: true, size: 22, color: C.red, font: "Arial" })] }),
              ],
            })
          ),
        ]})],
      }),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // TABLE OF CONTENTS
      // ══════════════════════════════════════════════════════════════════════════
      h1("目录"),
      new TableOfContents("目录", { hyperlink: true, headingStyleRange: "1-3" }),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 1: 项目概述
      // ══════════════════════════════════════════════════════════════════════════
      h1("一、项目概述"),

      h2("1.1 产品定位"),
      para("NoteAI Pro 是一款面向小红书内容创作者的智能诊断与持续成长平台。区别于现有工具的「一次性诊断」模式，NoteAI Pro 的核心价值主张是："),
      gap(40),
      colorBox("越用越懂你的 AI 内容医生 —— 在了解你的创作风格、历史痛点、账号目标的基础上，给出个性化的、可执行的、持续优化的诊断方案。", C.redLight, C.red),
      gap(60),
      para("平台通过三大核心引擎实现这一目标："),
      bullet("量化基线引擎：基于真实数据建模，给出有统计依据的诊断，而非凭感觉打分"),
      bullet("多 Agent 深度辩论引擎：多专家角色并行诊断、交叉质疑、最终裁决"),
      bullet("持久记忆成长引擎：跨会话记住用户风格、历史诊断、目标偏好，形成「越用越准」的个性化体验"),
      gap(80),

      h2("1.2 核心问题陈述"),
      para("小红书上有 8000 万+ 创作者，绝大多数人不理解为什么同样质量的内容，有的爆款有的无人问津。现有的解决方案存在以下根本性问题："),
      gap(40),
      makeTable(
        ["问题维度", "现有工具的局限", "NoteAI Pro 的解法"],
        [
          ["诊断依据", "单次 LLM 调用，主观感受打分", "5 万+ 本地生活笔记回归分析，每日自动更新，实时反映平台最新规律"],
          ["诊断深度", "Generic 建议：「优化标题」", "数据支撑的具体建议 + 成功案例对比"],
          ["个性化", "每次从零开始，不记得用户", "持久记忆用户风格、目标、历史痛点"],
          ["视觉分析", "无或极浅层的规则判断", "多模态大模型语义视觉理解"],
          ["闭环验证", "用户自己猜测效果", "发布后真实数据反馈回流，持续校准模型"],
          ["覆盖范围", "单一平台", "小红书核心 + 多平台适配架构"],
        ],
        [2200, 3080, 4080]
      ),
      gap(80),

      h2("1.3 竞品对比分析"),
      para("主要竞品为 NoteRx（薯医）——一款 48 小时黑客松产品，其核心优劣势如下："),
      gap(40),
      makeTable(
        ["能力维度", "NoteRx（竞品）", "NoteAI Pro（本项目）"],
        [
          ["基线数据量", "874 篇（静态，一次性人工）", "全自动爬虫，30 天冷启动 5 万条，持续每日 2200+ 条增量，目标 10 万+"],
          ["Agent 架构", "5 Agent 串行辩论（UX 展示为主）", "真实并行推理 + 置信度 + 分歧暴露"],
          ["用户记忆", "无（每次从零开始）", "FTS5 全文索引 + 跨会话成长档案"],
          ["视觉分析", "OpenCV 规则（色彩/人脸检测）", "多模态 LLM 语义理解封面美感/构图"],
          ["评论预测", "6 画像模拟（静态模型）", "动态画像 + 真实评论数据持续训练（每日爬虫喂数据）"],
          ["平台覆盖", "仅小红书", "小红书 + 抖音/B站适配架构"],
          ["数据闭环", "无发布效果反馈", "授权用户数据回流，强化学习迭代"],
          ["优化交互", "一次性输出 3 版改写", "对话式共创，支持约束条件记忆"],
        ],
        [2600, 3080, 3680]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 2: 产品愿景与目标
      // ══════════════════════════════════════════════════════════════════════════
      h1("二、产品愿景与目标"),

      h2("2.1 产品愿景"),
      gap(40),
      colorBox("让每一位小红书创作者，都能像顶级 MCN 机构一样，获得专业的、数据驱动的、持续陪伴的内容成长服务。", C.redLight, C.red),
      gap(80),

      h2("2.2 阶段性目标"),
      h3("Phase 1（MVP，第 1-3 个月）"),
      bullet("上线核心诊断功能：截图上传 → 多 Agent 诊断 → 量化打分 → 改写建议"),
      bullet("【数据冷启动】30 天内全自动爬虫采集 5 万条小红书本地生活笔记，训练 Model A v1.0（目标品类：餐饮/美容/娱乐/健身/住宿/城市探索等全品类）"),
      bullet("【每日自动化】爬虫每日增量采集 2200+ 条，特征提取、模型漂移检测、每周自动重训全程无人值守"),
      bullet("实现基础用户记忆：历史诊断记录 + 用户风格 Tag 自动提炼（注意：用户记忆与基线训练数据完全独立，前者服务个性化，后者服务平台规律学习）"),
      bullet("完成注册/登录/用户中心基础功能"),
      bullet("目标：上线 30 天内获得 1000 名注册用户"),
      gap(60),
      h3("Phase 2（成长，第 4-6 个月）"),
      bullet("上线对话式迭代优化：支持用户对改写方案给出约束条件"),
      bullet("上线发布效果追踪：用户授权后，同步真实互动数据回流"),
      bullet("上线视觉深度分析：多模态 LLM 封面语义评分"),
      bullet("上线社区对标功能：找到同赛道爆款进行 diff 分析"),
      bullet("目标：月活 5000+，付费转化率 5%"),
      gap(60),
      h3("Phase 3（商业化，第 7-12 个月）"),
      bullet("上线数据飞轮：用户发布效果数据训练强化学习模型，系统自我进化"),
      bullet("上线 MCN/品牌端工作台：批量诊断、团队协作、账号矩阵管理"),
      bullet("适配抖音/B站诊断引擎，构建多平台内容策略统一视图"),
      bullet("API 开放接口，支持第三方工具接入"),
      bullet("目标：月收入 10 万 RMB，用户 50000+"),
      gap(100),

      h2("2.3 核心成功指标（OKR 框架）"),
      makeTable(
        ["指标类型", "具体指标", "Phase 1 目标", "Phase 2 目标", "Phase 3 目标"],
        [
          ["用户规模", "注册用户数", "1,000", "10,000", "50,000"],
          ["用户活跃", "月活跃用户 (MAU)", "500", "5,000", "25,000"],
          ["产品质量", "诊断用户满意度 (NPS)", ">30", ">50", ">65"],
          ["商业化", "月度营业收入", "0", "5 万 RMB", "10 万 RMB"],
          ["技术质量", "诊断完成率 (P95)", ">90%", ">95%", ">98%"],
          ["数据飞轮（基线库）", "爬虫采集笔记总量", "50,000（30天冷启动）", "200,000", "500,000+"],
          ["数据飞轮（每日更新）", "日均新增训练样本", "2,200 条/天", "3,000 条/天", "5,000 条/天"],
        ],
        [2000, 2600, 1700, 1700, 1360]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 3: 目标用户
      // ══════════════════════════════════════════════════════════════════════════
      h1("三、目标用户"),

      h2("3.1 用户画像"),
      h3("核心用户 A：成长期素人创作者"),
      makeTable(
        ["维度", "描述"],
        [
          ["基本特征", "粉丝 500~5 万，发布频次 1~3 次/周，有一定内容基础"],
          ["核心痛点", "笔记数据忽高忽低找不到规律，不知道哪个环节出了问题"],
          ["行为模式", "发完笔记焦虑等待数据，反复刷新，偶尔在社群里求互评"],
          ["决策动机", "渴望突破流量瓶颈，愿意为「有效」的提升方法付费（50~200 元/月）"],
          ["典型场景", "发完笔记 2 小时没到 100 赞，想知道哪里出了问题"],
        ],
        [2200, 7160]
      ),
      gap(60),

      h3("核心用户 B：内容变现型创作者"),
      makeTable(
        ["维度", "描述"],
        [
          ["基本特征", "粉丝 5~100 万，有固定品类（美妆/美食/穿搭等），有变现需求"],
          ["核心痛点", "种草效果下降，想系统性优化内容策略，保持竞争力"],
          ["行为模式", "定期复盘数据，关注同赛道爆款，有意识地做 A/B 测试"],
          ["决策动机", "内容即收入，愿为专业数据服务付费（200~500 元/月）"],
          ["典型场景", "品牌合作方要求提升笔记互动率，需要系统性改进方案"],
        ],
        [2200, 7160]
      ),
      gap(60),

      h3("次要用户 C：MCN 机构/品牌内容团队"),
      makeTable(
        ["维度", "描述"],
        [
          ["基本特征", "管理 5~50 个达人账号，需要批量内容质检和策略指导"],
          ["核心痛点", "人工审核效率低，缺乏标准化的内容评分体系"],
          ["决策动机", "降本增效，建立可量化的内容质量管控流程"],
          ["典型场景", "每周批量上传 50 篇笔记草稿，需要优先级排序和改进建议"],
        ],
        [2200, 7160]
      ),
      gap(100),

      h2("3.2 用户旅程地图"),
      makeTable(
        ["阶段", "用户行为", "情绪状态", "平台支持点"],
        [
          ["认知", "刷到 KOL 推荐或社群讨论 NoteAI Pro", "好奇/半信半疑", "清晰的价值主张展示，一键体验 Demo"],
          ["首次使用", "上传第一篇笔记截图，获得诊断报告", "期待→惊喜（看到 Agent 辩论动画）", "零门槛上传，<60s 出诊断，视觉震撼的 Agent 流程"],
          ["建立习惯", "每次发笔记前用 NoteAI Pro 预检，发完后追踪数据", "依赖感逐渐建立", "消息提醒、历史对比、个人成长曲线"],
          ["深度使用", "对话式迭代改写，调用多平台诊断", "专业感，获得感", "记忆系统展示「你的内容风格」，个性化建议"],
          ["付费转化", "功能触达免费上限，决定升级", "纠结→决定", "清晰的价值感知，合理的分级定价"],
          ["传播裂变", "分享诊断卡片到小红书/微信", "自豪/分享欲", "一键生成带品牌水印的诊断卡片"],
        ],
        [1400, 2500, 1800, 3660]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 4: 核心功能需求
      // ══════════════════════════════════════════════════════════════════════════
      h1("四、核心功能需求"),

      h2("4.1 功能模块总览"),
      makeTable(
        ["模块编号", "模块名称", "优先级", "Phase"],
        [
          ["F01", "多模态内容摄入（截图/视频/链接）", "P0", "1"],
          ["F02", "量化基线评分引擎（Model A）", "P0", "1"],
          ["F03", "多 Agent 深度辩论诊断引擎", "P0", "1"],
          ["F04", "5 维雷达图诊断报告", "P0", "1"],
          ["F05", "对话式改写优化器", "P0", "1"],
          ["F06", "用户记忆与成长档案系统", "P1", "1-2"],
          ["F07", "AI 评论区模拟与受众画像", "P1", "1"],
          ["F08", "深度视觉语义分析", "P1", "2"],
          ["F09", "爆款对标分析（竞品 Diff）", "P1", "2"],
          ["F10", "发布效果追踪与反馈回流", "P1", "2"],
          ["F11", "诊断卡片生成与社交分享", "P2", "1"],
          ["F12", "多平台内容策略适配", "P2", "3"],
          ["F13", "MCN/品牌批量工作台", "P2", "3"],
          ["F14", "API 开放接口", "P3", "3"],
        ],
        [1400, 4000, 1480, 2480]
      ),
      gap(80),

      h2("4.2 F01 · 多模态内容摄入"),
      h3("功能描述"),
      para("支持用户通过多种方式上传待诊断的小红书内容。系统自动解析提取关键信息（标题、正文、标签、封面图、互动数据等），作为后续诊断引擎的输入。"),
      gap(40),
      h3("输入方式"),
      makeTable(
        ["输入方式", "支持内容", "处理逻辑", "响应时间"],
        [
          ["截图上传/粘贴", "PNG/JPG，最大 10MB", "OCR 提取文本 + 视觉分析封面", "<5s"],
          ["视频上传", "MP4，最大 100MB", "ASR 转录标题/文案 + 关键帧抽取", "<30s"],
          ["笔记链接", "小红书 app 分享链接", "解析 URL，抓取公开元数据（合规范围内）", "<10s"],
          ["手动填写", "结构化表单输入", "用户直接填写标题/正文/标签/分类", "即时"],
        ],
        [2000, 2000, 3160, 1200]
      ),
      gap(60),
      h3("用户故事"),
      infoBox("US-F01-01", "作为一名创作者，我希望能直接 Ctrl+V 粘贴截图就能开始诊断，不需要先保存文件再上传，因为这样操作最快。", C.blueLight, C.blue),
      gap(40),
      infoBox("US-F01-02", "作为一名创作者，我希望系统能自动识别我笔记的品类（美食/美妆/穿搭等），这样诊断标准才能对口。", C.blueLight, C.blue),
      gap(40),
      h3("验收标准"),
      bullet("截图上传后，OCR 识别准确率 ≥ 90%（中文文本）"),
      bullet("品类自动识别准确率 ≥ 85%（基于标题+标签+视觉特征综合判断）"),
      bullet("上传界面支持拖拽、点击选择、Ctrl+V 粘贴三种方式"),
      bullet("文件格式不支持时给出明确的错误提示和支持格式说明"),
      gap(80),

      h2("4.3 F02 · 量化基线评分引擎（Model A）"),
      h3("功能描述"),
      para("基于 LightGBM 回归模型（10万+ 本地生活笔记训练），对笔记进行 <50ms 的即时量化评分。当前版本 Model A v0.3 采用 62 维特征（37 内容文本 + 3 语义情感 + 14 封面视觉 + 8 发布时机），验证集 RMSE = 12.30，±10 分准确率 82.34%。语义特征由 Kimi（moonshot-v1-8k）实时推理注入，每次诊断自动调用。模型每周自动重训，实时反映小红书平台当前的分发规律和热点偏好。"),
      gap(40),
      infoBox("核心设计原则", "Model A 的数据来源是平台公开笔记的每日爬虫采集，而非注册用户数据。用户数据专用于「越用越懂你」的个性化记忆系统，两套数据系统完全独立，不混用。", C.blueLight, C.blue),
      gap(40),
      infoBox("模型核心竞争力：内容 × 市场契合度", "NoteAI Pro 的 Model A 不只回答「内容质量如何」，而是回答「这篇内容在当前时间点、当前平台环境下能跑多远」。评分 = 内容质量分 × 市场时机系数。这是千瓜/新红等分析平台无法提供的前瞻性预测，也是产品最核心的护城河。", C.purpleLight, C.purple),
      gap(40),
      h3("5 维评分维度（本地生活专属权重）"),
      makeTable(
        ["维度", "权重（默认）", "核心特征信号", "本地生活专属逻辑"],
        [
          ["封面表现力", "28%", "色彩暖度/氛围感评分/人脸情绪/门店外观/食物特写/文字贴片", "本地生活封面首要目标是传递「氛围感」，暖色调 + 真实场景 > 精修图"],
          ["标题吸引力", "22%", "情绪词/负面避雷词/数字/城市名/新开信号词/疑问句", "「避雷」「新开」「人均 XX 元」等本地特征词 CTR 提升显著"],
          ["内容实用性", "22%", "地址/营业时间/人均价格/交通/预约提醒/必点推荐/对比评价", "种草转化依赖实用信息完整度，缺地址 = 收藏率下降 40%"],
          ["标签策略", "16%", "标签数量(6-10最优)/POI地理标签/大中小词梯度/话题聚合页", "POI 地理位置标签是本地生活必须项，直接影响本地搜索曝光"],
          ["发布时机", "12%", "周四/五晚 7-11 点(周末决策窗口)/午餐前/节假日前 1-3 天", "本地生活黄金时段与电商完全不同，周末出行计划决策期优先级最高"],
        ],
        [2200, 1600, 3000, 2560]
      ),
      gap(60),
      h3("本地生活目标品类（全覆盖）"),
      makeTable(
        ["一级品类", "二级品类", "爬取占比", "特殊权重说明"],
        [
          ["餐饮美食", "中餐/日韩料/咖啡馆/茶饮/下午茶/小吃夜市/酒吧", "35%", "封面食欲感权重最高，评论「地址」「还在吗」密度是转化信号"],
          ["美容美发", "美容院/医美/美甲美睫/美发/SPA/精油", "20%", "「前后对比」封面效果好，置信度词「终于」「坚持」种草力强"],
          ["休闲娱乐", "剧本杀/密室/KTV/演出/展览/轰趴馆", "15%", "「体验感」描述词和「适合」场景词（闺蜜/情侣/团建）权重高"],
          ["健身运动", "健身房/瑜伽/普拉提/舞蹈/搏击/攀岩", "10%", "「打卡」连续性内容和「效果展示」封面互动率更高"],
          ["住宿体验", "精品酒店/民宿/露营/温泉", "8%", "「出片」「氛围」词高权重，周五/节假日前发布窗口最优"],
          ["城市探索", "citywalk/公园/隐藏景点/夜游", "7%", "「路线」结构内容收藏率高，季节词和天气词有时效加成"],
          ["购物亲子宠物", "商场/集市/亲子餐厅/宠物友好", "5%", "场景标签（带娃/遛狗）精准触达垂类受众，互动率高但量小"],
        ],
        [2000, 2600, 1400, 3360]
      ),
      gap(60),
      h3("XHS 平台 CES 权重机制（Model A 标签计算依据）"),
      colorBox(
        "小红书内容互动质量分（CES）实测权重：\n" +
        "  新增关注 × 8  （最高权重，平台视为账号成长信号）\n" +
        "  评论      × 4  （内容引发讨论 = 高质量内容信号）\n" +
        "  转发      × 3  （传播意愿强）\n" +
        "  收藏      × 1  （种草信号，但算法权重低于评论）\n" +
        "  点赞      × 1  （最低权重，不刷量）\n\n" +
        "Model A 目标变量（engagement_score）= CES / 预估曝光量，品类内百分位归一化\n" +
        "关键推论：结尾引导评论的 CTA 对 CES 影响远大于引导点赞，特征工程须体现此权重",
        C.orangeLight, C.orange
      ),
      gap(60),
      h3("双维评分架构"),
      colorBox(
        "Model A v0.3 评分架构：timing 特征已内嵌模型，无需外部乘法\n\n" +
        "模型输入特征（62维）：\n" +
        "  内容文本特征（37）：标题 8 + 正文 8 + PLAD心理语言 13 + 标签/分类 4 + 发布时间 4\n" +
        "  语义情感特征（3）：情感强度 / 共情度 / 修辞水平（Kimi 实时推理）\n" +
        "  封面视觉特征（14）：亮度 / 暖度 / 饱和度 / 对比度 / 清晰度 / 构图 / 人脸 / 文字…\n" +
        "  时机嵌入特征（8）：发布时机模式，训练阶段内嵌，推理时中性填充\n\n" +
        "外部实时信号（不直接入模型，用于显示层）：\n" +
        "  市场时机系数（8维）：热词契合 / 品类竞争 / 搜索量 / 趋势动量（每6小时刷新）\n\n" +
        "用户界面展示：\n" +
        "  内容质量分：72分  （赛道内 Top 28%，含语义/视觉/时机综合预测）\n" +
        "  市场时机：0.89  （当前热词契合度高，可用于引导用户选词时机）\n\n" +
        "设计决策：timing 已内嵌模型权重，composite_score = ces_percentile（不再二次乘法），避免双重计算导致分数虚高",
        C.purpleLight, C.purple
      ),
      gap(60),
      h3("验收标准"),
      bullet("Model A 评分耗时 P95 < 50ms（LightGBM 纯 CPU 推理，不依赖 GPU）"),
      bullet("v0.3 已达成：验证集 RMSE = 12.2987，±10 分准确率 82.34%（目标 <15 分，已超越）"),
      bullet("语义特征（情感强度/共情度/修辞水平）实时由 Kimi 推理注入，/score /diagnose /analyze 三端点均已启用"),
      bullet("每周自动重训后，新模型验证通过才热更新线上 API，旧模型保留为回滚备份"),
      bullet("评分结果展示品类内百分位排名（如：美食探店赛道 Top 23%）"),
      bullet("市场时机系数每6小时更新一次，反映最新热词和品类竞争状态"),
      bullet("模型漂移检测：连续 3 天预测误差上升 >15% 自动触发紧急重训告警"),
      gap(80),

      h2("4.3.5 基线数据采集与自动化训练系统"),
      h3("系统定位"),
      para("基线采集系统是 Model A 的「数据供给引擎」，与用户记忆系统完全独立。其核心职责是：每天自动从小红书平台抓取本地生活类公开笔记，提取特征，动态维护训练数据库，驱动模型持续贴近平台最新规律。"),
      gap(40),
      infoBox("两套数据系统严格分离", "基线数据库（baseline_notes）：来源是小红书平台公开笔记爬虫，驱动 Model A 评分模型，反映平台普遍规律。用户记忆数据库（user_memory）：来源是注册用户行为，驱动个性化推荐，服务「越用越懂你」。两者数据不混用、模型不共享、存储不共表。", C.greenLight, C.green),
      gap(40),

      h3("冷启动目标与规模设计（修正版）"),
      makeTable(
        ["阶段", "时间", "目标数据量", "日均采集量", "模型状态"],
        [
          ["冷启动", "第 1-40 天", "5 万条", "1,200-1,500 条/天（10线程稳健并发）", "第 38-40 天训练 Model A v1.0"],
          ["稳定增长", "第 2-6 月", "20 万条", "1,500 条/天持续", "每周自动重训，每月精调"],
          ["规模化", "第 7-12 月", "50 万条+", "2,000-3,000 条/天", "分品类子模型 + 城市维度细分"],
        ],
        [1600, 1600, 2000, 2800, 1360]
      ),
      gap(40),
      infoBox("为何从20线程调整为10线程", "20线程同时运行会导致同时段流量集中，触发XHS IP段封禁，封禁恢复需24-72小时，实际采集量反而更少。10线程×每IP≤15请求/小时是实测安全阈值，稳定性优先于速度，冷启动周期从30天延长至40天是合理代价。", C.orangeLight, C.orange),
      gap(60),

      h3("双调度器架构（新）"),
      colorBox(
        "调度器 A：热点感知调度（每6小时）\n" +
        "  00:00 / 06:00 / 12:00 / 18:00 各执行一次\n" +
        "  ├── 抓取 XHS 搜索建议 API → 实时热词 Top100\n" +
        "  ├── 抓取 XHS 热搜榜 → 热搜词 Top50\n" +
        "  ├── 抓取发现页话题区 → 平台推荐话题列表\n" +
        "  └── 更新 hot_keywords 表 → 实时刷新市场时机系数\n\n" +
        "调度器 B：笔记采集调度（每日一次）\n" +
        "  01:00 笔记采集任务启动\n" +
        "  ├── 10 个 Playwright 实例，各自独立 IP + Cookie\n" +
        "  ├── 线程 1-4:  各品类笔记榜单 Top200（高质量正样本）\n" +
        "  ├── 线程 5-7:  搜索页按关键词采集（长尾内容覆盖）\n" +
        "  ├── 线程 8-9:  最新发布低互动笔记（负样本，7天+互动<50）\n" +
        "  └── 线程 10:   详情页补充（补抓互动数据 + 早期CES 2h速率）\n" +
        "  代理池：100 个住宅 IP，每 IP ≤15 请求/小时\n" +
        "  Cookie池：50 个 XHS 账号，每账号 ≤80 请求/天\n\n" +
        "  05:30 特征提取批处理\n" +
        "  ├── 文本特征：纯规则提取，<1ms/条\n" +
        "  ├── 封面图特征：Claude Haiku，$0.001/张\n" +
        "  └── 市场时机特征：关联当日 hot_keywords 表计算\n\n" +
        "  07:00 去重入库 + 品类百分位更新完成\n\n" +
        "  每周日 00:00 → 全量重训 LightGBM → 验证通过 → 热更新 Model A API",
        C.lightGray, C.darkGray
      ),
      gap(60),

      h3("热点感知机制与具体爬取目标"),
      para("小红书热点每天变化、平台分发规则定期调整，模型通过三级爬取目标实时感知并响应："),
      makeTable(
        ["优先级", "爬取目标", "入口 / 数据源", "获取内容", "调度频率", "驱动特征"],
        [
          ["P1 热点感知", "XHS 搜索建议 API", "search.xiaohongshu.com/suggest", "实时热词 Top100 + 搜索量相对指数", "每6小时", "keyword_search_vol / trend_momentum"],
          ["P1 热点感知", "XHS 热搜榜", "搜索页热榜接口", "实时热搜词 Top50 + 上升/下降趋势", "每6小时", "trend_peak_distance / is_trending_topic"],
          ["P1 热点感知", "发现页话题区", "/explore 话题标签区", "平台当日推荐话题 + 话题下笔记数", "每天 09:00 / 21:00", "is_trending_topic / content_freshness"],
          ["P2 训练样本", "各品类笔记榜单", "品类关键词搜索 → 按「最热」排序", "Top200 爆款笔记（高质量正样本）8品类×200条/天", "每天 01:00", "所有内容特征 + CES 标签"],
          ["P2 训练样本", "低互动笔记（负样本）", "品类关键词搜索 → 按「最新」排序，过滤7天+低互动", "互动<50 的笔记（确认失败案例）8品类×75条/天", "每天 01:00", "关键负样本，防止模型只见爆款"],
          ["P3 竞争环境", "品类发布密度统计", "各品类主标签页周新增笔记计数", "category_saturation（品类饱和度）", "每周日统计", "category_saturation"],
          ["P3 竞争环境", "达人分层采样", "达人搜索 + 粉丝量筛选", "各量级账号样本池（1k/1w/10w/100w+）", "每月更新", "训练集分层，剔除大号光环偏差"],
          ["清洗过滤", "品牌合作笔记识别", "笔记「合作」标签 + 品牌词规则匹配", "标注 is_sponsored=true，不纳入基准训练集", "采集时实时处理", "防止付费内容污染模型"],
        ],
        [1200, 1800, 2000, 2600, 1400, 1760]
      ),
      gap(40),
      makeTable(
        ["感知层次", "监测对象", "响应动作", "更新频率"],
        [
          ["词频热点", "热搜榜 + 搜索建议 API 词频变化", "新增高频词 → 扩大该关键词爬取配额 → 更新 hot_keywords 表", "每6小时自动执行"],
          ["品类互动均值", "各子品类 CES 均值趋势", "均值突变 >30% → 触发该品类子模型重训", "每日自动检测"],
          ["内容格式偏好", "图文 vs 视频比例、封面动态/静态比例", "格式权重特征动态调整", "每周统计更新"],
          ["平台算法变化", "模型预测误差持续上升", "连续 3 天 RMSE 上升 >15% → 告警 + 触发紧急全量重训", "实时监控"],
        ],
        [2000, 2200, 3160, 1500]
      ),
      gap(60),

      h3("特征工程（v0.3：70维特征输入 = 62维模型特征 + 8维实时市场信号）"),
      makeTable(
        ["特征组", "数量", "特征名称", "提取方式", "说明"],
        [
          ["标题特征", "8", "title_len / title_has_pos_emotion / title_has_neg_emotion / title_has_price / title_has_question / title_has_number / title_has_new_signal / title_has_city", "规则 + 情绪词库", "情绪词/数字/城市/新开信号，CTR 核心驱动"],
          ["正文特征", "8", "body_len / body_has_address / body_has_hours / body_has_price / body_has_transport / body_has_booking / body_has_must_order / body_cta_count", "正则匹配 + 关键词库", "实用信息完整度，缺地址收藏率下降 40%"],
          ["PLAD 心理语言特征 ★v0.3扩展", "13", "plad_word_freq_entropy / plad_phrasal_repetition / plad_punctuation_ratio / plad_interactive_stance / plad_ttr / plad_sentence_count / plad_avg_sentence_len / plad_sentence_burstiness / plad_emoji_density / plad_unique_emoji_ratio / plad_number_ratio / plad_word_burstiness / plad_immediate_repetition", "纯规则，<1ms/条", "基于 RedNote-Vibe 论文（arXiv 2509.22055）Table 2，从 4 个扩展至 13 个；词汇丰富度/句子节奏/数字密度等是爆款笔记的语言规律"],
          ["标签与分类特征", "4", "tag_count / tag_has_city / tag_has_food_travel / domain_encoded", "标签文本解析", "话题覆盖度和领域编码"],
          ["发布时间特征", "4", "time_hour / time_weekday / time_is_weekend / time_days_to_holiday", "时间规则计算", "发布窗口：周四/五晚 7-11 点本地生活 CES 是其他时段 2.3 倍"],
          ["语义情感特征 ★v0.3新增", "3", "semantic_emotional_intensity（情感强度）/ semantic_empathetic_engagement（共情度）/ semantic_rhetorical_score（修辞水平）", "Kimi moonshot-v1-8k 实时推理", "6 万条训练集由 Kimi 离线批量标注（batch=5，~12,033 次调用）；推理时实时单条调用，10s 超时，失败回退 0.5"],
          ["封面视觉特征", "14", "cover_brightness / cover_warmth / cover_saturation / cover_contrast / cover_sharpness / cover_aspect_ratio / cover_has_face / cover_face_count / cover_has_text / cover_text_prominence / cover_composition_score / cover_aesthetic_score / cover_emotion_intensity / cover_visual_clarity", "OpenCV 规则（确定性）+ Kimi Vision（深度分析）", "/score 和 /diagnose 用 OpenCV；/analyze 调用 Kimi Vision 获取语义视觉分"],
          ["时机嵌入特征", "8", "timing_features.parquet 中 8 个时机模式特征", "训练集预计算并缓存", "在训练阶段内嵌模型权重；推理时输入 0.0 作为中性值（时机偏好已通过训练集均值隐含编码）"],
          ["市场时机信号（展示层）", "8", "trend_momentum / trend_peak_distance / category_saturation / category_avg_ces / keyword_search_vol / keyword_competition / is_trending_topic / content_freshness", "关联 hot_keywords 表，每6小时刷新", "不直接入模型，用于前端显示市场时机系数；踩在热词上升期前2天发布 CES 比峰值后高 2.1 倍"],
        ],
        [2200, 600, 2600, 1600, 2360]
      ),
      gap(40),
      infoBox("市场时机特征的核心价值", "千瓜/新红告诉你「上周哪些笔记爆了」（回顾性分析）。NoteAI Pro 的市场时机特征告诉用户「你这篇笔记在当前市场环境下发出去能跑多远」+「把标题第3个词换成当前热词X，预测分可以提升N%」（前瞻性诊断）。这是产品最核心的不可复制竞争力。", C.purpleLight, C.purple),
      gap(60),

      h3("运营成本估算（月度）"),
      makeTable(
        ["成本项", "规格", "月度金额"],
        [
          ["住宅代理 IP 池", "100 个住宅 IP，每日轮换", "约 $80/月（¥580）"],
          ["封面图 AI 分析", "Claude Haiku，2200 张/天 × 30 天", "约 $66/月（¥480）"],
          ["服务器（爬虫+训练）", "4 核 16G，含存储", "约 $45/月（¥330）"],
          ["XHS 备用账号", "50 个账号池，月补充 5 个", "约 ¥10/月"],
          ["合计", "全自动运行，零人工干预", "约 ¥1,400/月"],
        ],
        [2800, 3800, 2760]
      ),
      gap(100),
      pageBreak(),

      h2("4.4 F03 · 多 Agent 深度辩论诊断引擎"),
      h3("系统架构"),
      para("多 Agent 辩论引擎是平台的核心差异化能力。5 个专家 Agent 真正并行运行，输出带置信度的诊断结论，仲裁者在处理分歧时会触发额外的证据查询步骤。"),
      gap(40),
      makeTable(
        ["Agent 角色", "专业职责", "分析维度", "输出格式"],
        [
          ["内容分析师 ContentAgent", "分析文案结构、信息密度、表达逻辑", "标题类型/正文结构/情绪密度/关键词", "结论 + 置信度 0-1 + 3 条证据"],
          ["视觉诊断师 VisualAgent", "封面美感、构图逻辑、视觉叙事力", "构图/色调/情绪/受众匹配度", "结论 + 置信度 0-1 + 3 条证据"],
          ["增长策略师 GrowthAgent", "标签策略、发布时机、赛道竞争", "标签热度/时段/竞品密度", "结论 + 置信度 0-1 + 3 条证据"],
          ["用户模拟器 UserAgent", "目标受众视角，预测互动行为", "受众画像匹配/评论情绪/分享动机", "结论 + 置信度 0-1 + 6 类评论样本"],
          ["仲裁者 ArbiterAgent", "综合各方，解决分歧，生成最终报告", "分歧检测/证据权衡/整合判断", "最终诊断报告 + 优先级行动清单"],
        ],
        [2600, 2400, 2000, 2360]
      ),
      gap(60),

      h3("三轮辩论流程"),
      makeTable(
        ["轮次", "名称", "参与者", "核心动作"],
        [
          ["Round 1", "独立诊断", "4 个专家 Agent（并行）", "各自独立输出诊断结论 + 置信度 + 证据，禁止互相参考"],
          ["Round 2", "交叉质疑", "4 个专家 Agent（串行质疑）", "每个 Agent 对其他 Agent 中置信度 <0.7 的结论提出质疑；系统自动查询基线数据库寻找支持证据"],
          ["Round 3", "仲裁综合", "ArbiterAgent", "当 2+ Agent 对同一维度存在分歧（置信度差 >0.3），触发「分歧暴露」模式向用户展示；最终整合输出行动优先级"],
        ],
        [1200, 2000, 2500, 3660]
      ),
      gap(60),

      h3("分歧暴露机制（核心创新）"),
      infoBox("设计原则", "Agent 之间的真实分歧本身就是有价值的信号，应该让用户看到，而不是被仲裁者强行统一。分歧暴露让用户理解「这个问题没有标准答案」，增强对诊断结果的信任感。", C.greenLight, C.green),
      gap(40),
      para("分歧展示格式示例："),
      gap(20),
      colorBox("⚡ 专家分歧提醒\n视觉诊断师（置信度 0.85）：封面构图优秀，人物情绪感染力强，预计点击率高于赛道均值 40%\n增长策略师（置信度 0.78）：该时段发布竞品封面质量普遍较高，视觉优势被稀释，实际提升可能仅 15%\n→ 建议关注：发布时段的竞品密度是影响最终效果的关键变量", C.orangeLight, C.orange),
      gap(80),

      h3("流式输出规范"),
      bullet("诊断过程通过 SSE（Server-Sent Events）实时流式推送到前端"),
      bullet("前端展示 11 步诊断时间线动画，每步对应实际 Agent 状态"),
      bullet("每个 Agent 的实时思考过程以「气泡对话」形式展示（模拟会诊讨论）"),
      bullet("用户可以在诊断进行中看到实时置信度变化"),
      gap(80),
      pageBreak(),

      h2("4.5 F06 · 用户记忆与成长档案系统"),
      para("这是 NoteAI Pro 超越所有竞品的核心能力——借鉴 Hermes Agent 的持久记忆架构，系统跨会话积累对用户的理解。"),
      gap(40),
      h3("记忆分层架构"),
      makeTable(
        ["记忆层次", "存储内容", "更新时机", "检索方式"],
        [
          ["用户档案层", "账号阶段/内容品类/变现目标/粉丝规模", "用户首次设置 + 自动检测更新", "每次诊断前自动加载"],
          ["风格画像层", "写作风格标签/高频词汇/擅长维度/弱点维度", "每次诊断后自动提炼", "FTS5 全文索引 + 语义相似度"],
          ["历史诊断层", "每次诊断的完整记录 + 采纳状态", "每次诊断完成后", "时间线检索 + 维度趋势分析"],
          ["效果反馈层", "采纳建议后的真实发布数据", "用户授权后自动同步", "关联分析（建议→效果相关性）"],
          ["技能知识层", "该用户品类的最佳实践规则", "积累足够样本后自动提炼", "RAG 检索增强生成"],
        ],
        [2200, 2800, 2200, 2160]
      ),
      gap(60),

      h3("个性化成长报告"),
      para("每月自动生成「内容成长报告」，包含："),
      bullet("本月 vs 上月各维度评分对比"),
      bullet("「你的强项」：哪些维度持续表现优异"),
      bullet("「持续踩坑」：哪些维度反复被扣分，附具体改进方向"),
      bullet("「成长轨迹」：关键节点的分数变化趋势图"),
      bullet("「下月建议」：基于历史模式，最值得突破的 1-2 个优化方向"),
      gap(40),

      h3("约束偏好记忆"),
      para("系统记住用户在对话式优化中表达过的约束条件，后续诊断自动遵守："),
      bullet("「我不想改标题，因为标题是领导定的」→ 后续不对标题提改写建议"),
      bullet("「我的封面固定用品牌模板，不能改」→ 视觉建议只聚焦可改变的元素"),
      bullet("「我只在工作日 18:00 发」→ 发布时间建议在该约束范围内给出"),
      gap(100),

      h2("4.6 F08 · 深度视觉语义分析"),
      para("使用多模态大模型（GPT-4o Vision / Claude 3.5 Sonnet）对封面图进行语义级别的理解，远超 OpenCV 规则引擎能达到的深度。"),
      gap(40),
      makeTable(
        ["分析维度", "评估内容", "输出结果"],
        [
          ["情绪吸引力", "封面传达的情绪类型（惊喜/温暖/专业/有趣等）与目标受众匹配度", "情绪标签 + 匹配分 0-10"],
          ["视觉层次", "前景/中景/背景的层次感，主体是否突出", "层次评分 + 具体改进点"],
          ["文案封面配合", "封面文案与图片内容的呼应程度，是否形成视觉合力", "配合评分 + 优化建议"],
          ["赛道风格匹配", "封面视觉风格与该品类爆款的风格偏好匹配度", "风格匹配分 + 参考案例"],
          ["点击意愿预测", "综合以上维度，预测封面点击意愿", "预测点击率区间 + 置信度"],
        ],
        [2400, 3800, 3160]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 5: 技术架构
      // ══════════════════════════════════════════════════════════════════════════
      h1("五、技术架构"),

      h2("5.1 整体架构概览"),
      colorBox(
        "用户层（Web / 移动 H5 / 微信小程序）\n" +
        "          ↓\n" +
        "API 网关层（FastAPI · 认证 · 限流 · 路由）\n" +
        "          ↓\n" +
        "┌──────────────────────────────────────┐\n" +
        "│          核心引擎层                    │\n" +
        "│  ┌──────────┐  ┌──────────────────┐  │\n" +
        "│  │ Model A  │  │ Multi-Agent Orche│  │\n" +
        "│  │ 量化评分  │  │ strator 编排引擎  │  │\n" +
        "│  └──────────┘  └──────────────────┘  │\n" +
        "│  ┌──────────────────────────────────┐ │\n" +
        "│  │     Memory Engine 记忆引擎        │ │\n" +
        "│  └──────────────────────────────────┘ │\n" +
        "└──────────────────────────────────────┘\n" +
        "          ↓\n" +
        "数据层（PostgreSQL · Redis · Vector DB · S3）\n" +
        "          ↓\n" +
        "外部服务（LLM APIs · 多模态模型 · 小红书数据爬取）",
        C.lightGray, C.darkGray
      ),
      gap(80),

      h2("5.2 技术栈选型"),
      h3("前端技术栈"),
      makeTable(
        ["技术", "版本/规格", "选型理由"],
        [
          ["React", "19.x", "最新并发渲染特性，适合 SSE 流式数据展示"],
          ["TypeScript", "5.x", "类型安全，大型项目必备"],
          ["Vite", "Latest", "极速开发构建，热更新体验最佳"],
          ["Tailwind CSS", "v4", "原子化 CSS，高效实现设计系统"],
          ["Framer Motion", "Latest", "声明式动画库，实现 Agent 辩论流程动画"],
          ["ECharts", "5.x", "雷达图等可视化组件，小红书风格定制性强"],
          ["React Query", "v5", "服务端状态管理，支持流式数据订阅"],
          ["Zustand", "Latest", "轻量客户端状态管理，替代 Redux"],
        ],
        [2000, 2200, 5160]
      ),
      gap(60),

      h3("后端技术栈"),
      makeTable(
        ["技术", "版本/规格", "选型理由"],
        [
          ["Python", "3.12+", "AI/ML 生态最完整，FastAPI 原生支持"],
          ["FastAPI", "0.115+", "高性能异步框架，原生 SSE 支持，自动 OpenAPI 文档"],
          ["PostgreSQL", "16+", "主数据库，支持 JSONB/全文索引/向量扩展"],
          ["pgvector", "Latest", "PostgreSQL 向量搜索扩展，替代独立 Vector DB"],
          ["Redis", "7.x", "会话缓存、任务队列、SSE 事件总线"],
          ["Celery", "5.x", "异步任务队列，处理长时间 Agent 诊断任务"],
          ["SQLAlchemy", "2.x", "异步 ORM，支持 PostgreSQL 全特性"],
          ["Pydantic", "v2", "数据验证和序列化，与 FastAPI 深度集成"],
        ],
        [2000, 2200, 5160]
      ),
      gap(60),

      h3("AI/ML 技术栈"),
      makeTable(
        ["技术/模型", "用途", "说明"],
        [
          ["GPT-4o / Claude 3.5 Sonnet", "主力 Agent 推理", "函数调用 + 结构化输出，支持多轮对话"],
          ["Claude Haiku 4.5", "诊断文案生成 + /analyze 端点", "结构化 XML 输出（diagnosis/titles/plan/body），max_tokens=2048"],
          ["Kimi moonshot-v1-8k", "语义特征实时推理 + 批量标注", "/score /diagnose /analyze 三端点实时调用；6 万条训练集批量标注（batch=5，max_tokens=120）"],
          ["Kimi moonshot-v1-8k-vision-preview", "封面深度视觉分析（/analyze）", "封面美感/构图/情绪强度 6 维语义评分，timeout=20s"],
          ["GPT-4o Vision / Claude Sonnet", "深度视觉语义分析（F08 规划）", "诊断时封面情绪/构图/受众匹配度深度分析"],
          ["Qwen-VL / MiMo-v2-Omni", "快速 OCR + 品类识别", "成本更低，适合高频调用"],
          ["Kimi K2.5（kimi-k2.5）", "笔记生成主力模型（P3仲裁 + P3.5处理）", "支持thinking推理模式（256K上下文）；P3仲裁使用thinking模式（max_tokens=16000）；read timeout=600s（streaming per-chunk timeout）；P3.5 Trim/Burst快速处理使用非thinking fast模式"],
          ["LightGBM v0.3", "Model A 评分模型（62维特征）", "RMSE=12.2987，±10分准确率82.34%；62维特征（37内容+3语义+14视觉+8时机）；<50ms CPU 推理；MLflow 版本管理"],
          ["jieba + 自建本地生活情绪词库", "中文文本特征提取", "分词/情绪词/地名识别/实用信息提取，13个PLAD心理语言特征（RedNote-Vibe论文扩展）"],
          ["Atropos / 自研 RL", "效果反馈强化学习", "Phase 3 数据飞轮核心"],
        ],
        [2800, 2400, 4160]
      ),
      gap(60),

      h3("基线数据采集技术栈"),
      makeTable(
        ["技术", "版本/规格", "用途说明"],
        [
          ["Playwright", "Latest（Python）", "无头浏览器爬虫，处理 XHS JavaScript 渲染页面，支持反指纹配置"],
          ["scrapy-playwright", "Latest", "Scrapy + Playwright 整合，支持 20 线程并发采集"],
          ["住宅代理（IPRoyal/快代理）", "100 IP 池", "真实住宅 IP 轮换，规避速率限制，每 IP ≤30 请求/小时"],
          ["APScheduler", "3.x", "双调度器：调度器A（热点感知，每6小时）抓热词/热搜/话题；调度器B（笔记采集，每日01:00）抓榜单正样本+低互动负样本；05:30特征提取；07:00入库；周日重训"],
          ["MinIO / 阿里云 OSS", "S3 兼容", "封面图片存储，批量下载后供 Claude Haiku 分析"],
          ["MLflow", "Latest", "模型版本管理，训练指标追踪，Model A 各版本对比"],
          ["Prometheus + Grafana", "Latest", "爬虫健康监控（成功率/失败率）+ 模型漂移实时告警"],
        ],
        [2800, 2200, 4360]
      ),
      gap(60),

      h3("基础设施"),
      makeTable(
        ["组件", "选型", "说明"],
        [
          ["容器化", "Docker + Docker Compose", "开发环境一键启动，生产 K8s 部署"],
          ["CI/CD", "GitHub Actions", "自动测试/构建/部署流水线"],
          ["文件存储", "阿里云 OSS / AWS S3", "用户上传的截图/视频存储"],
          ["CDN", "CloudFront / 阿里云 CDN", "前端静态资源加速"],
          ["监控", "Prometheus + Grafana", "系统监控，Agent 诊断耗时追踪"],
          ["日志", "ELK Stack", "结构化日志，诊断链路追踪"],
        ],
        [2000, 2800, 4560]
      ),
      gap(100),
      pageBreak(),

      h2("5.3 多 Agent 编排架构（详细设计）"),

      h3("Agent 通信协议"),
      para("每个 Agent 的输入/输出遵循统一的结构化协议："),
      gap(40),
      colorBox(
        "// Agent 输出标准格式（TypedDict）\n" +
        "{\n" +
        "  agent_id: str,                    # agent 标识\n" +
        "  diagnosis: str,                   # 核心诊断结论\n" +
        "  confidence: float,               # 置信度 0.0~1.0\n" +
        "  evidence: List[Evidence],         # 支撑证据列表（最多 3 条）\n" +
        "  dimension_scores: Dict[str, float],  # 各维度分数\n" +
        "  suggestions: List[Suggestion],   # 具体改进建议\n" +
        "  disputes: List[Dispute]           # 对其他 Agent 的质疑（Round 2）\n" +
        "}",
        C.lightGray, C.darkGray
      ),
      gap(60),

      h3("Orchestrator 编排器设计"),
      makeTable(
        ["阶段", "并发/串行", "超时设置", "降级策略"],
        [
          ["Phase 0: Model A 预评估", "同步", "50ms", "无（必须完成）"],
          ["Phase 1: 4 Agent 并行诊断", "并发 asyncio.gather", "30s", "单 Agent 超时→使用默认值继续"],
          ["Phase 2: 交叉质疑", "串行（依赖 Phase 1 结果）", "20s", "超时→跳过，不影响 Phase 3"],
          ["Phase 3: 仲裁综合", "同步", "30s", "超时→直接聚合，不触发分歧暴露"],
          ["Phase 4: 改写生成", "并发（3 个版本）", "45s", "生成 1 个版本即可返回"],
        ],
        [2600, 2400, 1600, 2760]
      ),
      gap(80),

      h2("5.4 记忆引擎架构（借鉴 Hermes Agent）"),
      h3("存储层设计"),
      makeTable(
        ["存储类型", "技术实现", "用途"],
        [
          ["关系型存储", "PostgreSQL", "用户账号/诊断记录/订阅状态"],
          ["全文索引", "PostgreSQL FTS5 / Meilisearch", "历史诊断快速检索"],
          ["向量存储", "pgvector（PostgreSQL 扩展）", "语义相似诊断检索，风格画像向量化"],
          ["KV 缓存", "Redis", "活跃用户记忆热数据缓存（TTL 24h）"],
          ["冷存储", "PostgreSQL JSONB 压缩", "超过 90 天的历史诊断归档"],
        ],
        [2400, 3000, 4160]
      ),
      gap(60),
      h3("记忆检索流程"),
      numbered("用户发起新诊断请求"),
      numbered("Memory Engine 查询 Redis：用户档案热数据（<5ms）"),
      numbered("Cache Miss → 查询 PostgreSQL 用户画像表（<20ms）"),
      numbered("FTS5 检索历史诊断：匹配品类 + 近期 30 天（<30ms）"),
      numbered("pgvector 语义检索：找到风格最相似的历史诊断（<50ms）"),
      numbered("组装 Context Prompt：「这位用户是 [档案摘要]，历史弱点是 [弱点标签]，本次诊断请特别关注……」"),
      numbered("注入到 Agent System Prompt，开始诊断"),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 6: 数据架构
      // ══════════════════════════════════════════════════════════════════════════
      h1("六、数据架构"),

      h2("6.1 核心数据模型"),
      h3("用户表（users）"),
      makeTable(
        ["字段名", "类型", "说明"],
        [
          ["id", "UUID PK", "用户唯一标识"],
          ["email", "VARCHAR(255) UNIQUE", "登录邮箱"],
          ["phone", "VARCHAR(20)", "手机号（中国）"],
          ["plan", "ENUM（free/pro/enterprise）", "订阅计划"],
          ["xhs_account_stage", "ENUM（cold/growth/mature）", "账号阶段"],
          ["primary_category", "VARCHAR(50)", "主要内容品类"],
          ["creator_goal", "ENUM（fans/monetize/brand）", "创作目标"],
          ["created_at", "TIMESTAMPTZ", "注册时间"],
          ["memory_summary", "TEXT", "AI 生成的用户画像摘要（定期更新）"],
          ["style_vector", "VECTOR(1536)", "内容风格向量（pgvector）"],
        ],
        [2800, 3000, 3560]
      ),
      gap(60),

      h3("诊断记录表（diagnoses）"),
      makeTable(
        ["字段名", "类型", "说明"],
        [
          ["id", "UUID PK", "诊断记录 ID"],
          ["user_id", "UUID FK", "关联用户"],
          ["input_type", "ENUM（screenshot/video/link/manual）", "输入方式"],
          ["raw_content", "JSONB", "解析后的原始内容（标题/正文/标签等）"],
          ["model_a_scores", "JSONB", "Model A 5 维量化评分"],
          ["agent_reports", "JSONB", "4 个专家 Agent 的完整诊断报告"],
          ["final_report", "JSONB", "仲裁者最终报告 + 行动优先级"],
          ["rewrite_variants", "JSONB[]", "改写版本列表"],
          ["user_constraints", "JSONB", "用户在此次对话中声明的约束"],
          ["feedback_status", "ENUM（pending/published/no_action）", "用户是否采纳并发布"],
          ["actual_performance", "JSONB", "发布后真实互动数据（授权后回流）"],
          ["created_at", "TIMESTAMPTZ", "诊断时间"],
        ],
        [2800, 3000, 3560]
      ),
      gap(60),

      h3("基线数据表（baseline_notes）— 本地生活专属设计"),
      makeTable(
        ["字段名", "类型", "说明"],
        [
          ["id", "UUID PK", "笔记 ID"],
          ["category_l1", "VARCHAR(50)", "一级品类：餐饮/美容/娱乐/健身/住宿/城市探索/购物亲子"],
          ["category_l2", "VARCHAR(80)", "二级品类：咖啡馆/医美/剧本杀/瑜伽/民宿/citywalk 等"],
          ["city", "VARCHAR(50)", "发布城市（北京/上海/成都等，来自 POI 标签解析）"],
          ["title", "TEXT", "原始标题"],
          ["body_length", "INT", "正文字数"],
          ["image_count", "SMALLINT", "图片数量（1-9）"],
          ["is_video", "BOOL", "是否为视频笔记"],
          ["tag_count", "SMALLINT", "标签总数"],
          ["has_poi_tag", "BOOL", "是否有 POI 地理位置标签"],
          ["tag_tier_score", "SMALLINT", "标签梯度完整度（0-3，大中小词各占1分）"],
          ["publish_hour", "SMALLINT", "发布小时（0-23）"],
          ["publish_weekday", "SMALLINT", "发布星期（0=周一）"],
          ["likes", "INT", "点赞数"],
          ["comments", "INT", "评论数"],
          ["saves", "INT", "收藏数"],
          ["shares", "INT", "转发数"],
          ["ces_score", "FLOAT", "计算字段：赞×1+评×4+藏×1+转×3，基于 XHS CES 公式"],
          ["engagement_score", "FLOAT", "目标变量：CES/预估曝光，品类内百分位归一化（0-100）"],
          ["cover_warmth", "SMALLINT", "封面色温：1=冷 2=中性 3=暖（Claude Haiku 分析）"],
          ["cover_saturation", "SMALLINT", "封面饱和度：1=低 2=中 3=高"],
          ["cover_face_count", "SMALLINT", "封面人脸数量（0/1/2/3+）"],
          ["cover_has_food", "BOOL", "封面是否有食物特写"],
          ["cover_has_storefront", "BOOL", "封面是否有门店外景"],
          ["cover_has_text_sticker", "BOOL", "封面是否有文字贴片"],
          ["title_pos_emotion", "SMALLINT", "正向情绪词数量（绝了/yyds/天花板等）"],
          ["title_neg_emotion", "SMALLINT", "负向避雷词数量（避雷/踩雷/失望等，同样高流量）"],
          ["title_has_price", "BOOL", "标题是否含价格信息"],
          ["title_has_new_open", "BOOL", "标题是否含新开/首店信号"],
          ["body_has_address", "BOOL", "正文是否含地址信息"],
          ["body_has_price_detail", "BOOL", "正文是否含人均/价格详情"],
          ["body_has_cta", "BOOL", "正文是否有引导评论的 CTA（影响 CES 评论权重）"],
          ["trending_score", "FLOAT", "采集时命中热词的匹配分（每日动态计算）"],
          ["— 市场时机特征组（8个）★新增 —", "", "采集时关联 hot_keywords 表实时计算，每6小时刷新"],
          ["trend_momentum", "FLOAT", "标题/标签命中热词的趋势斜率（+为上升/-为下降/0为平稳）"],
          ["trend_peak_distance", "SMALLINT", "距该热词搜索量峰值的天数（负数=未到峰值，正数=已过峰值）"],
          ["category_saturation", "INT", "同品类本周新发笔记总数（越高竞争越激烈）"],
          ["category_avg_ces", "FLOAT", "同品类本周平均 CES 分（归一化基准线）"],
          ["keyword_search_vol", "SMALLINT", "主标签当前搜索量指数（1-100，来自搜索建议 API）"],
          ["keyword_competition", "INT", "同标签下存量笔记总数（搜索页竞争密度）"],
          ["is_trending_topic", "BOOL", "发布时是否命中平台当周推荐话题"],
          ["content_freshness", "SMALLINT", "该话题从首次出现至今的天数（越小越处于红利期）"],
          ["— 系统字段 —", "", ""],
          ["is_sponsored", "BOOL", "是否为品牌合作笔记（true=不纳入基准训练）"],
          ["cluster_id", "SMALLINT", "LightGBM 聚类 ID（内容模式分类）"],
          ["model_version", "VARCHAR(20)", "该条数据参与训练的模型版本"],
          ["source", "ENUM（scraped）", "数据来源：本表仅存爬虫数据，用户数据存 user_memory"],
          ["collected_at", "TIMESTAMPTZ", "采集时间（用于滚动窗口：保留最近 90 天高权重数据）"],
          ["is_active", "BOOL", "是否参与当前训练集（过期数据降权后标记 false）"],
        ],
        [2800, 2600, 3960]
      ),
      gap(40),
      infoBox("数据保鲜策略", "最近 30 天数据：训练权重 1.0（全量参与）；30-90 天数据：训练权重 0.5（降权参与，保留历史规律）；90 天以上数据：is_active=false，不参与训练（平台规律已过时）。每周重训自动执行此窗口策略。", C.orangeLight, C.orange),
      gap(100),

      h2("6.2 数据飞轮设计（Phase 3 核心）"),
      para("数据飞轮是 NoteAI Pro 建立竞争护城河的核心机制："),
      gap(40),
      colorBox(
        "用户上传笔记\n" +
        "     ↓\n" +
        "NoteAI Pro 诊断 + 改写建议\n" +
        "     ↓\n" +
        "用户采纳建议，在小红书发布\n" +
        "     ↓（用户授权后）\n" +
        "真实互动数据回流（点赞/评论/收藏/曝光）\n" +
        "     ↓\n" +
        "「建议 → 效果」关联分析\n" +
        "     ↓\n" +
        "高效建议权重上调，低效建议降权 / 剔除\n" +
        "     ↓\n" +
        "下一次诊断更准确 → 用户更信任 → 更多用户授权数据\n" +
        "     ↓（循环）",
        C.greenLight, C.green
      ),
      gap(80),
      infoBox("隐私设计原则", "所有数据回流均需用户主动授权。用户数据仅用于训练通用模型，不向其他用户暴露个人数据。平台遵守《个人信息保护法》相关规定，提供完整的数据删除请求机制。", C.blueLight, C.blue),
      gap(80),

      h2("6.3 双数据系统架构（核心设计原则）"),
      para("NoteAI Pro 运行两套完全独立的数据系统，混用两套数据是系统设计的最大禁忌："),
      gap(40),
      makeTable(
        ["维度", "基线数据系统（Platform Intelligence）", "用户记忆系统（User Memory）"],
        [
          ["数据来源", "小红书平台公开笔记，每日爬虫自动采集", "注册用户使用行为、诊断历史、约束偏好"],
          ["存储表", "baseline_notes（专用表，不可混入用户数据）", "users / diagnoses / user_style_profiles"],
          ["更新频率", "每日自动采集 2200 条，每周自动重训", "每次用户交互实时更新"],
          ["服务对象", "Model A 评分模型，反映平台当前规律", "个性化诊断 Context，反映这个人的风格"],
          ["解决问题", "「小红书现在流行什么」「当前平台怎么分发」", "「这个用户是谁」「他的历史痛点是什么」"],
          ["隐私属性", "公开内容，无个人隐私", "用户私有数据，严格 PIPL 合规"],
          ["典型应用", "评分维度权重、品类百分位、热点词加分", "诊断时注入用户档案、记住约束条件"],
        ],
        [2000, 3500, 3860]
      ),
      gap(40),
      colorBox(
        "错误示范（严禁）：用注册用户的笔记数据训练 Model A\n" +
        "原因：用户数据有选择偏差（只上传问题笔记），会污染基线模型，导致评分系统性偏低\n\n" +
        "正确做法：Model A 只用平台公开笔记的全量随机抽样训练，用户数据只用于 Hermes 记忆层",
        C.redLight, C.red
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 7: API 设计
      // ══════════════════════════════════════════════════════════════════════════
      h1("七、API 接口设计"),

      h2("7.1 核心 API 端点"),
      makeTable(
        ["端点", "方法", "功能描述", "认证"],
        [
          ["POST /api/v1/diagnoses", "POST", "创建新诊断任务，返回 task_id", "Bearer JWT"],
          ["GET /api/v1/diagnoses/{id}/stream", "GET (SSE)", "订阅诊断进度实时流", "Bearer JWT"],
          ["GET /api/v1/diagnoses/{id}", "GET", "获取诊断完整结果", "Bearer JWT"],
          ["POST /api/v1/diagnoses/{id}/rewrite", "POST", "触发对话式改写（传入约束条件）", "Bearer JWT"],
          ["GET /api/v1/users/me/profile", "GET", "获取用户成长档案和记忆摘要", "Bearer JWT"],
          ["GET /api/v1/users/me/diagnoses", "GET", "获取历史诊断列表（分页）", "Bearer JWT"],
          ["POST /api/v1/users/me/feedback", "POST", "提交发布效果数据（数据回流）", "Bearer JWT"],
          ["GET /api/v1/baseline/categories", "GET", "获取各品类基线统计数据", "Public"],
          ["POST /api/v1/auth/register", "POST", "用户注册", "无"],
          ["POST /api/v1/auth/login", "POST", "用户登录，返回 JWT", "无"],
          ["GET /api/v1/crawler/status", "GET", "查看爬虫运行状态（今日采集量/成功率/模型版本）", "Admin JWT"],
          ["POST /api/v1/crawler/trigger", "POST", "手动触发一次采集任务（指定品类和数量）", "Admin JWT"],
          ["GET /api/v1/model/versions", "GET", "查看 Model A 历史版本及验证集 RMSE", "Admin JWT"],
          ["POST /api/v1/model/rollback", "POST", "回滚到指定版本的 Model A", "Admin JWT"],
        ],
        [3200, 1200, 3200, 1760]
      ),
      gap(60),

      h2("7.2 关键 API 数据结构"),
      h3("POST /api/v1/diagnoses 请求体"),
      colorBox(
        '{\n' +
        '  "input_type": "screenshot",           // screenshot | video | link | manual\n' +
        '  "file_key": "uploads/uuid/img.jpg",   // 预上传后的 OSS Key\n' +
        '  "category_hint": "美食",               // 可选，系统自动识别时忽略\n' +
        '  "user_goal": "increase_engagement",   // 本次诊断重点\n' +
        '  "constraints": [                       // 用户约束（可选）\n' +
        '    {"type": "no_edit", "target": "title"},\n' +
        '    {"type": "no_edit", "target": "cover"}\n' +
        '  ]\n' +
        '}',
        C.lightGray, C.darkGray
      ),
      gap(60),

      h3("SSE 流式事件格式"),
      colorBox(
        '// 事件类型枚举\n' +
        'event: model_a_complete       data: {"scores": {...}, "percentiles": {...}}\n' +
        'event: agent_thinking         data: {"agent": "ContentAgent", "thought": "...", "confidence": 0.82}\n' +
        'event: agent_complete         data: {"agent": "VisualAgent", "diagnosis": "...", "confidence": 0.91}\n' +
        'event: dispute_detected       data: {"agents": ["ContentAgent", "GrowthAgent"], "dimension": "engagement", "details": "..."}\n' +
        'event: arbiter_synthesizing   data: {"progress": 0.7, "message": "正在解决分歧..."}\n' +
        'event: diagnosis_complete     data: {"report_id": "uuid", "summary": "..."}\n' +
        'event: error                  data: {"code": "TIMEOUT", "message": "部分 Agent 超时，已使用降级方案"}',
        C.lightGray, C.darkGray
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 8: 前端设计规范
      // ══════════════════════════════════════════════════════════════════════════
      h1("八、前端设计规范"),

      h2("8.1 设计系统"),
      makeTable(
        ["设计元素", "规范"],
        [
          ["主色调", "#E53935（小红书红）/ #212121（深灰文字）/ #F5F5F5（背景）"],
          ["辅助色", "#1565C0（信息蓝）/ #2E7D32（成功绿）/ #E65100（警告橙）"],
          ["字体", "PingFang SC（中文）/ Inter（英文）/ JetBrains Mono（代码）"],
          ["圆角", "卡片 12px / 按钮 8px / 小标签 4px"],
          ["阴影", "主卡片 0 4px 20px rgba(0,0,0,0.08) / 悬浮 0 8px 32px rgba(0,0,0,0.12)"],
          ["动画时长", "微交互 150ms / 页面转场 300ms / Agent 动画 800ms-2000ms"],
        ],
        [2000, 7360]
      ),
      gap(80),

      h2("8.2 核心页面"),
      makeTable(
        ["页面", "路径", "核心功能", "关键交互"],
        [
          ["首页/落地页", "/", "产品价值展示 + 一键试用 Demo", "「立即诊断」CTA 按钮，无需注册即可体验一次"],
          ["诊断上传页", "/diagnose", "多模态内容上传", "拖拽上传区 + 粘贴区 + 约束条件设置"],
          ["实时诊断页", "/diagnose/{id}/live", "Agent 辩论过程可视化", "11 步时间线 + Agent 气泡对话 + 实时置信度"],
          ["诊断报告页", "/diagnose/{id}/report", "完整诊断结果展示", "5 维雷达图 + 分歧暴露卡片 + 改写对比"],
          ["成长档案页", "/profile/growth", "用户历史诊断分析", "成长曲线 + 风格画像 + 月度报告"],
          ["历史记录页", "/history", "过往诊断列表", "按品类/时间筛选 + 效果追踪标记"],
          ["设置页", "/settings", "账号信息 + 记忆管理 + 数据授权", "记忆内容查看/删除 + 授权开关"],
        ],
        [2000, 2000, 2400, 3160]
      ),
      gap(80),

      h2("8.3 Agent 辩论动画规范"),
      para("这是产品最核心的差异化体验，动画设计需传达「专业的 AI 会诊」感，而不是「炫技」感。"),
      gap(40),
      makeTable(
        ["动画阶段", "时长", "视觉表现", "情绪目标"],
        [
          ["Agent 集合", "0.8s", "5 个 Agent 图标从四角飞入，在会诊台就位", "仪式感，用户感知诊断即将开始"],
          ["Model A 扫描", "1.2s", "进度条 + 量化数字跳动，5 维评分逐个亮起", "快速、精准的科技感"],
          ["并行诊断", "3-8s", "4 Agent 同时出现思考气泡，气泡内文字流式输出", "忙碌的专家团，认真对待"],
          ["交叉质疑", "2-4s", "Agent 之间连线高亮，质疑气泡弹出，被质疑者「思考」动画", "智识冲突，真实辩论感"],
          ["分歧暴露", "1s", "橙色警告卡片展开，两方置信度对比显示", "信息透明，增强信任"],
          ["仲裁综合", "2s", "Arbiter 图标居中发光，其他 Agent 退场，最终报告渐入", "权威总结，诊断完成"],
        ],
        [2000, 1200, 3200, 2960]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 9: 非功能需求
      // ══════════════════════════════════════════════════════════════════════════
      h1("九、非功能需求"),

      h2("9.1 性能需求"),
      makeTable(
        ["指标", "目标值", "测量方式"],
        [
          ["Model A 评分延迟", "P99 < 100ms", "Prometheus 端点监控"],
          ["首个 SSE 事件推送延迟", "P90 < 3s（用户上传后）", "前端打点 + 后端日志"],
          ["完整诊断耗时", "P90 < 60s", "从上传到诊断完成计时"],
          ["改写生成耗时", "P90 < 30s（3 个版本并发）", "Celery 任务耗时监控"],
          ["页面首屏加载（FCP）", "< 1.5s", "Lighthouse CI 检测"],
          ["API 可用性", "> 99.5% 月均", "外部 Uptime 监控"],
          ["并发诊断支持", "≥ 100 并发任务", "压测（Locust）验证"],
        ],
        [2600, 2400, 4360]
      ),
      gap(80),

      h2("9.2 安全需求"),
      makeTable(
        ["安全维度", "要求"],
        [
          ["身份认证", "JWT（RS256）+ Refresh Token，Access Token 有效期 1h"],
          ["API 限流", "未登录：10 次/分钟；免费用户：30 次/小时；Pro 用户：200 次/小时"],
          ["数据加密", "传输层 TLS 1.3；数据库存储字段级加密（手机号/邮箱）"],
          ["文件安全", "上传文件病毒扫描（ClamAV）；文件类型白名单校验"],
          ["LLM 注入防御", "Prompt 注入检测；用户输入沙箱化处理后再拼入 System Prompt"],
          ["隐私合规", "符合《个人信息保护法》；明示数据使用范围；支持用户数据导出/删除"],
          ["审计日志", "所有 API 调用记录（用户 ID/端点/时间/IP）；敏感操作二次确认"],
        ],
        [2400, 6960]
      ),
      gap(80),

      h2("9.3 可扩展性设计"),
      bullet("多 Agent 引擎设计为插件化：新增 Agent 类型无需修改编排器核心逻辑"),
      bullet("平台适配层（小红书/抖音/B站）通过接口统一，各平台基线数据和权重独立配置"),
      bullet("LLM 提供商抽象层：支持切换 OpenAI / Anthropic / 国产模型（通义/文心），不影响上层逻辑"),
      bullet("数据库读写分离：写主库，读从库，支持横向扩展读节点"),
      bullet("Celery 任务队列支持动态扩容 Worker 节点"),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 10: 商业化方案
      // ══════════════════════════════════════════════════════════════════════════
      h1("十、商业化方案"),

      h2("10.1 定价策略"),
      makeTable(
        ["方案", "价格", "核心权益", "目标用户"],
        [
          ["免费版 Free", "¥0/月", "每月 5 次诊断；基础 5 维评分；诊断记录保留 7 天；无记忆功能", "体验用户，转化漏斗顶端"],
          ["专业版 Pro", "¥98/月\n¥888/年", "每月 100 次诊断；完整 Agent 辩论；视觉语义分析；用户成长档案；历史记录永久保留；月度成长报告；优先客服", "成长期创作者"],
          ["旗舰版 Max", "¥299/月\n¥2599/年", "无限次诊断；批量上传（最多 20 条/次）；对话式迭代优化；发布效果追踪；API 调用额度（1000 次/月）", "内容变现创作者"],
          ["企业版 Enterprise", "面议\n（≥¥5000/月）", "无限次诊断；MCN 工作台（多账号管理）；团队协作；私有化部署选项；专属客户成功经理", "MCN 机构/品牌团队"],
        ],
        [2000, 2000, 3560, 1800]
      ),
      gap(80),

      h2("10.2 增长策略"),
      h3("病毒式传播设计"),
      bullet("诊断完成后一键生成「诊断卡片」，带品牌水印，用户愿意分享到小红书/微信（反向引流）"),
      bullet("免费版用户分享诊断卡片，可获得额外 2 次诊断机会（邀请机制）"),
      bullet("平台统计「小红书今日最佳笔记」，每日在官方社媒发布，吸引创作者注意"),
      gap(60),
      h3("内容营销"),
      bullet("「为什么你的笔记没爆」系列文章，植入 NoteAI Pro 诊断截图"),
      bullet("联合头部内容创作者做「AI 诊断实测」，内容在 B站/公众号/小红书传播"),
      bullet("开放 API 让创作者工具（蒲公英/新红等）接入，批量带来行业流量"),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 11: 开发路线图
      // ══════════════════════════════════════════════════════════════════════════
      h1("十一、开发路线图"),

      h2("11.1 详细里程碑"),
      makeTable(
        ["里程碑", "时间", "核心交付物", "验收标准"],
        [
          ["M0: 环境搭建", "第 1 周", "项目脚手架/CI/CD/数据库 Schema（含 baseline_notes 完整表结构）/开发规范文档", "本地一键启动，PR 自动测试通过，双数据系统分库配置完成"],
          ["M1-A: 爬虫基础设施", "第 1-2 周（与 M0 并行）", "10 线程爬虫框架/代理池/Cookie 池/双调度器（热点每6h+笔记每日）/hot_keywords 表/特征提取 Pipeline（含市场时机8特征）", "每日稳定采集 1200-1500 条，热点数据每6小时更新，成功率 >85%，特征提取全自动"],
          ["M1-B: 冷启动采集", "第 2-4 周（持续运行）", "全自动运行，累计采集 5 万条本地生活笔记，覆盖 8 大品类 × 12 主要城市", "第 26 天达到 5 万条，品类分布均匀，封面特征提取完整"],
          ["M1-C: Model A 训练上线", "第 4-5 周", "LightGBM 模型训练/MLflow 版本管理/Model A API 接口/每周自动重训 Pipeline", "验证集 RMSE < 15 分，API P95 < 50ms，自动重训流程完整验证"],
          ["M2: Agent 引擎", "第 4-6 周", "4 个专家 Agent + 仲裁者实现、编排器、SSE 流式输出", "完整诊断 P90<60s，分歧暴露功能验证"],
          ["M3: 前端核心", "第 5-8 周", "上传页、实时诊断动画页、诊断报告页", "Agent 动画流畅（60fps），报告数据完整展示"],
          ["M4: 用户系统", "第 7-9 周", "注册/登录、用户档案、基础记忆系统（无 RL）", "记忆跨会话持久化，历史诊断可检索"],
          ["M5: MVP 上线", "第 10 周", "完整 MVP 部署上线，免费版开放注册", "压测通过（100 并发），安全审计通过"],
          ["M6: 效果追踪", "第 12-14 周", "发布效果数据回流、成长报告、月度报告自动生成", "数据回流链路端到端测试通过"],
          ["M7: 视觉增强", "第 15-17 周", "多模态视觉语义分析集成、对话式改写优化", "视觉评分与人工评分相关性 >0.75"],
          ["M8: 商业化", "第 18-20 周", "付费订阅系统、Pro/Max 功能隔离、支付集成", "支付链路测试通过，计量计费准确"],
        ],
        [2000, 1400, 3200, 2760]
      ),
      gap(100),

      h2("11.2 风险与应对"),
      makeTable(
        ["风险", "等级", "影响", "应对策略"],
        [
          ["LLM API 成本超预算", "高", "影响盈利模型", "混合模型策略：快速任务用国产低成本模型（Qwen/文心），深度推理用 GPT-4o"],
          ["小红书平台反爬", "高", "基线数据采集中断，Model A 无法按时完成冷启动", "分布式策略：20 线程 × 100 个住宅 IP 轮换，每 IP ≤30 请求/小时；50 个 XHS Cookie 账号池，随机 UA + 请求间隔；仅采集公开内容，法律边界清晰；单 IP 封禁时自动降级至其他代理，不中断整体采集；同时维护 15% 缓冲容量，确保封禁不影响每日 2200 条目标"],
          ["Agent 诊断质量不稳定", "中", "用户信任受损", "建立人工评分飞轮（前 1000 名用户邀请评分），快速迭代 Prompt"],
          ["竞品快速跟进", "中", "差异化竞争优势削弱", "加速建立数据飞轮护城河，持久记忆功能作为最大差异化壁垒"],
          ["用户数据隐私合规", "中", "法律风险", "第一天起严格遵守 PIPL，聘请合规顾问审查数据采集链路"],
        ],
        [2400, 1000, 2200, 3760]
      ),
      gap(100),
      pageBreak(),

      // ══════════════════════════════════════════════════════════════════════════
      // SECTION 12: 附录
      // ══════════════════════════════════════════════════════════════════════════
      h1("十二、附录"),

      h2("12.1 与 Hermes Agent 架构对比分析"),
      para("Hermes Agent（NousResearch）是一个通用型自进化 AI Agent 框架，其核心价值是「越用越聪明的个人助理」。NoteAI Pro 在以下方面借鉴其设计哲学："),
      gap(40),
      makeTable(
        ["架构特性", "Hermes Agent 实现", "NoteAI Pro 借鉴方式", "差异化定制"],
        [
          ["持久记忆", "FTS5 全文搜索 + LLM 摘要跨会话记忆", "直接借鉴：用户风格档案、历史诊断记忆、约束偏好记忆", "专注内容创作领域，记忆结构为「创作者档案」而非通用助理档案"],
          ["技能自提炼", "复杂任务完成后自动提炼可复用技能", "借鉴理念：样本积累后自动提炼「品类爆款规律」", "规则存入基线知识库而非代码技能库，适合内容诊断场景"],
          ["RL 训练回路", "Atropos 框架，用交互结果做强化学习", "Phase 3 实现：发布效果→建议权重→模型迭代", "以「建议采纳率+真实互动数据」为 reward 信号，垂域化训练"],
          ["多平台网关", "15+ 消息平台接入（Slack/Telegram 等）", "不借鉴：对内容诊断场景过度通用化", "聚焦 Web+小程序，不分散成通用 Chatbot"],
        ],
        [2000, 2600, 2600, 2160]
      ),
      gap(60),

      infoBox("结论", "NoteAI Pro 应该是「领域专精的 Hermes Agent」：用 Hermes 的持久记忆架构和数据飞轮理念，但不照搬其通用助理的产品形态。核心差异在于：Hermes 记住的是「你作为人的偏好」，NoteAI Pro 记住的是「你作为内容创作者的风格和成长轨迹」。", C.purpleLight, C.purple),
      gap(80),

      h2("12.2 术语表"),
      makeTable(
        ["术语", "定义"],
        [
          ["Model A", "基于 LightGBM 回归的量化评分模型，无 LLM 调用，<50ms CPU 推理，每周自动重训"],
          ["LightGBM", "Light Gradient Boosting Machine，微软开源的梯度提升树框架，支持增量训练，推理速度比随机森林快 10 倍以上，是 Model A 的核心算法"],
          ["CES（内容互动质量分）", "Content Engagement Score，小红书平台内容质量综合指标。公式：关注×8 + 评论×4 + 转发×3 + 收藏×1 ≈ 点赞×1。评论率是最重要优化目标"],
          ["baseline_notes", "基线数据表，仅存储平台爬虫采集的公开笔记数据，驱动 Model A 训练，不混入任何用户上传数据"],
          ["user_memory", "用户记忆表，存储注册用户的行为偏好、风格档案、历史诊断，驱动个性化推荐层，与 baseline_notes 严格隔离"],
          ["APScheduler", "Advanced Python Scheduler，Python 定时任务库，用于编排每日爬虫（01:00）→ 特征提取（05:30）→ 数据库更新（07:00）→ 周日重训的自动化 Pipeline"],
          ["MLflow", "开源机器学习实验管理平台，用于 Model A 的版本追踪、训练指标记录、模型回滚和 A/B 对比"],
          ["热点感知系统", "每6小时抓取 XHS 搜索建议/热搜榜/发现页话题，更新 hot_keywords 表，实时刷新市场时机系数，驱动 Model A 的市场时机特征组"],
          ["市场时机系数", "Model A 双维评分中的市场维度，基于8个市场特征计算（热词趋势/品类饱和度/搜索需求/话题新鲜度等），与内容质量分相乘得到最终综合评分"],
          ["内容市场契合度（CMF）", "Content-Market Fit，NoteAI Pro 的核心评分理念：内容质量好 + 发布时机对 = 最大化爆款概率，缺一不可"],
          ["hot_keywords 表", "存储每6小时更新的平台热词数据，包含热词、搜索量指数、趋势方向、话题类型，是市场时机特征组的数据来源"],
          ["数据保鲜策略", "Model A 训练数据按时间加权：30 天内权重 1.0，30-90 天权重 0.5，90 天以上数据排除训练集，保持模型对平台当前规则的敏感性"],
          ["Agent", "具有独立专业职责的 AI 推理单元，有明确的输入输出协议"],
          ["置信度（Confidence）", "Agent 对自身诊断结论的确定性估计，0.0~1.0 浮点数"],
          ["分歧暴露", "当 2+ Agent 对同一维度判断差异 >0.3 时，向用户展示分歧而非强制统一"],
          ["数据飞轮", "用户真实发布数据回流 → 模型迭代 → 诊断更准 → 更多用户 → 更多数据的正反馈循环"],
          ["SSE", "Server-Sent Events，服务端向客户端单向推送实时事件的协议"],
          ["pgvector", "PostgreSQL 的向量扩展，支持向量相似度搜索，用于语义记忆检索"],
          ["FTS5", "Full-Text Search 5，SQLite/PostgreSQL 全文索引引擎，用于历史诊断快速检索"],
          ["Atropos", "Nous Research 开源的强化学习训练框架，Hermes Agent 的自进化基础"],
          ["RAG", "Retrieval-Augmented Generation，检索增强生成，用于将知识库内容注入 LLM 上下文"],
        ],
        [2400, 6960]
      ),
      gap(80),

      h2("12.3 文档修订历史"),
      makeTable(
        ["版本", "日期", "修改内容", "修改人"],
        [
          ["v1.0", "2026-04-15", "初稿创建，覆盖完整 PRD 结构", "产品团队"],
          ["v1.1", "2026-04-20", "新增基线数据采集与自动化训练系统完整方案（章节 4.3、4.3.5、5.2、6.1、6.3、7、11.1、11.2、12.2）：①明确本地生活 8 大品类为核心训练目标；②设计 20 线程分布式爬虫架构，30 天冷启动 5 万条；③Model A 算法从线性回归升级为 LightGBM；④建立 baseline_notes/user_memory 双数据系统严格分离原则；⑤制定热点感知、数据保鲜、模型漂移告警完整 Pipeline；⑥里程碑 M1 拆分为 M1-A/B/C 三阶段", "产品团队"],
          ["v1.2", "2026-04-22", "模型训练层重大升级（章节 4.3、4.3.5、6.1、5.2、11.1）：①Model A 架构从「内容评分」升级为「内容质量 × 市场时机」双维模型；②特征工程从35个升级至43个（新增市场时机特征组8个）；③爬虫架构修正（20线程→10线程，30天→40天冷启动，稳定性优先）；④新增三级爬取目标体系（P1热点感知每6h / P2训练样本每日 / P3竞争环境每周）；⑤APScheduler 拆分为双调度器架构；⑥新增 hot_keywords 表和 baseline_notes 8个市场时机字段；⑦新增品牌合作笔记过滤（is_sponsored）", "产品团队"],
          ["v1.3", "2026-05-05", "Model A v0.3 升级（62特征）：①PLAD 特征从4个扩展至13个（新增 ttr/sentence_count/avg_sentence_len/sentence_burstiness/emoji_density/unique_emoji_ratio/number_ratio/word_burstiness/immediate_repetition）；②新增3个语义特征（emotional_intensity/empathetic_engagement/rhetorical_score，Kimi moonshot-v1-8k 批量标注60,161条）；③修复emoji正则 CJK误判bug；④前端新增「技术引擎」第6个导航Tab（62维特征卡片 + Top-15重要性图）；⑤/score /diagnose 接入实时语义特征，Val RMSE 12.2987 / Acc ±10pt 82.34%", "产品团队"],
          ["v1.4", "2026-05-05", "对话式笔记优化全链路上线：①修复三个关键Bug（DOMAIN_MAP缺少餐饮别名 / _get_dk别名归一化 / pre-P3模型评分注入），/generate 评分突破70分（实测71.1分）；②新增/chat/start · /chat/message（SSE流式）· /chat/ui三个端点；③generate_context桥接机制：/generate完整响应（专家意见/特征命中/封面分析/备选标题）注入对话system prompt；④「越用越懂你」SQLite user_learn表，按user_id存储偏好，拒绝/认可信号自动学习；⑤思考链动画SSE协议（thinking_start/chunk/end → 折叠展开动画）；⑥Framer前端新增💬对话优化第7个导航Tab、生成结果页对话入口横幅、#page-chat暗色主题双栏页面（左栏笔记预览+评分仪表盘，右栏多轮对话+快捷操作）", "产品团队"],
          ["v1.5", "2026-05-06", "全品类生成质量突破 + P3 Thinking修复：①修复P3 thinking 100% fallback bug（read timeout 90s→600s，max_tokens 32768→16000，模型kimi-k2.6→kimi-k2.5），/generate实测74.2分；②全品类（7个）Domain Knowledge基于v0.3模型训练数据全面重写；③新增P3.5程序化后处理层：穿搭trim≤280字（80.6分）/ 美妆trim≤300字（70.1分）/ 健身sentence burst注入；④修复家居domain encoding错误（education→career），新增_TIMING_ALIASES（美妆→穿搭/家居→职场/健身→运动/母婴→健康），解决4个品类category_saturation默认0.5的惩罚问题；⑤_build_fix_instructions增强：新增sentence_burstiness / phrasal_repetition / 品类字数超标三项检查；⑥7品类实测结果：美食73.1 / 旅行72.9 / 穿搭80.6 / 美妆70.1 / 家居74.7 / 母婴82.7 / 健身67.1（进行中）", "产品团队"],
        ],
        [1200, 2000, 4400, 1760]
      ),
      gap(80),

      new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { before: 400, after: 0 },
        children: [new TextRun({ text: "— 文档结束 —", size: 20, color: C.midGray, font: "Arial", italics: true })],
      }),
    ],
  }],
});

Packer.toBuffer(doc).then(buffer => {
  fs.writeFileSync("/Users/samyu/Desktop/projects/noteai/NoteAI_Pro_PRD_v1.5.docx", buffer);
  console.log("✅ PRD 文档生成成功！");
}).catch(err => {
  console.error("❌ 生成失败:", err);
  process.exit(1);
});
