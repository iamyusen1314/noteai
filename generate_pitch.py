from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN
from pptx.util import Inches, Pt
import copy

# ─── Color Palette ───────────────────────────────────────────────────────────
INDIGO     = RGBColor(0x4F, 0x46, 0xE5)   # #4F46E5 primary
INDIGO_D   = RGBColor(0x31, 0x27, 0xAE)   # #3127AE dark indigo
INDIGO_L   = RGBColor(0xE0, 0xE7, 0xFF)   # #E0E7FF light indigo
EMERALD    = RGBColor(0x10, 0xB9, 0x81)   # #10B981 CTA/accent
EMERALD_L  = RGBColor(0xD1, 0xFA, 0xE5)   # #D1FAE5 light emerald
PURPLE     = RGBColor(0x7C, 0x3A, 0xED)   # #7C3AED purple
PURPLE_L   = RGBColor(0xED, 0xE9, 0xFE)   # #EDE9FE light purple
ORANGE     = RGBColor(0xF5, 0x9E, 0x0B)   # #F59E0B warning
ORANGE_L   = RGBColor(0xFE, 0xF3, 0xC7)   # #FEF3C7 light orange
RED        = RGBColor(0xEF, 0x44, 0x44)   # #EF4444 red
RED_L      = RGBColor(0xFE, 0xE2, 0xE2)   # #FEE2E2 light red
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)
BG         = RGBColor(0xF8, 0xF7, 0xFF)   # near-white with indigo tint
DARK       = RGBColor(0x1E, 0x1B, 0x4B)   # #1E1B4B deep navy
GRAY       = RGBColor(0x6B, 0x72, 0x80)
GRAY_L     = RGBColor(0xF3, 0xF4, 0xF6)
GRAY_M     = RGBColor(0xE5, 0xE7, 0xEB)
SLATE      = RGBColor(0x64, 0x74, 0x8B)

# ─── Slide dimensions (widescreen 16:9) ──────────────────────────────────────
W = Inches(13.33)
H = Inches(7.5)

prs = Presentation()
prs.slide_width  = W
prs.slide_height = H

BLANK = prs.slide_layouts[6]  # completely blank

# ─── Helper: add shape ───────────────────────────────────────────────────────
def rect(slide, l, t, w, h, fill=None, line=None, line_w=Pt(0)):
    from pptx.util import Emu
    s = slide.shapes.add_shape(1, l, t, w, h)  # MSO_SHAPE_TYPE.RECTANGLE=1
    s.line.fill.background()
    if fill:
        s.fill.solid(); s.fill.fore_color.rgb = fill
    else:
        s.fill.background()
    if line:
        s.line.color.rgb = line
        s.line.width = line_w
    else:
        s.line.fill.background()
    return s

def txt(slide, text, l, t, w, h,
        size=18, bold=False, color=DARK, align=PP_ALIGN.LEFT,
        italic=False, wrap=True, font="Calibri"):
    tb = slide.shapes.add_textbox(l, t, w, h)
    tb.word_wrap = wrap
    tf = tb.text_frame
    tf.word_wrap = wrap
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.bold = bold
    run.font.italic = italic
    run.font.color.rgb = color
    run.font.name = font
    return tb

def badge(slide, label, l, t, bg=INDIGO_L, fg=INDIGO):
    rect(slide, l, t, Inches(1.6), Inches(0.32), fill=bg)
    txt(slide, label, l+Inches(0.12), t+Inches(0.04),
        Inches(1.4), Inches(0.28), size=10, bold=True, color=fg, align=PP_ALIGN.CENTER)

def divider(slide, y, color=GRAY_M, thickness=Pt(0.75)):
    ln = slide.shapes.add_connector(1, Inches(0.5), y, Inches(12.83), y)
    ln.line.color.rgb = color
    ln.line.width = thickness

# ─── SLIDE BUILDER ───────────────────────────────────────────────────────────

def new_slide():
    slide = prs.slides.add_slide(BLANK)
    rect(slide, 0, 0, W, H, fill=WHITE)
    return slide

def slide_with_header(title, subtitle=None, tag=None, tag_color=INDIGO, tag_bg=INDIGO_L):
    slide = new_slide()
    # left accent bar
    rect(slide, 0, 0, Inches(0.06), H, fill=INDIGO)
    # title
    txt(slide, title, Inches(0.5), Inches(0.32), Inches(12.5), Inches(0.6),
        size=28, bold=True, color=DARK)
    if subtitle:
        txt(slide, subtitle, Inches(0.5), Inches(0.92), Inches(9), Inches(0.38),
            size=14, color=SLATE)
    if tag:
        badge(slide, tag, Inches(0.5), Inches(0.93) if not subtitle else Inches(1.32),
              bg=tag_bg, fg=tag_color)
    divider(slide, Inches(1.6))
    return slide

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 01 — COVER
# ══════════════════════════════════════════════════════════════════════════════
slide = new_slide()
rect(slide, 0, 0, W, H, fill=DARK)
# indigo gradient overlay (top strip)
rect(slide, 0, 0, W, Inches(0.08), fill=INDIGO)
# large background circle decoration
s = slide.shapes.add_shape(9, Inches(8.5), Inches(-1.5), Inches(7), Inches(7))  # oval
s.fill.solid(); s.fill.fore_color.rgb = RGBColor(0x31, 0x27, 0xAE)
s.line.fill.background()
s2 = slide.shapes.add_shape(9, Inches(10), Inches(3.5), Inches(4), Inches(4))
s2.fill.solid(); s2.fill.fore_color.rgb = RGBColor(0x4F, 0x46, 0xE5)
s2.line.fill.background()

# Tag
b = rect(slide, Inches(0.9), Inches(1.6), Inches(2.1), Inches(0.36), fill=INDIGO)
txt(slide, "投资人简报  2026", Inches(0.9), Inches(1.63), Inches(2.1), Inches(0.3),
    size=11, bold=True, color=WHITE, align=PP_ALIGN.CENTER)

txt(slide, "NoteAI Pro", Inches(0.9), Inches(2.1), Inches(9), Inches(1.2),
    size=64, bold=True, color=WHITE, font="Calibri")
txt(slide, "小红书创作者的 AI 内容医生", Inches(0.9), Inches(3.25), Inches(9), Inches(0.7),
    size=28, bold=False, color=RGBColor(0xA5, 0xB4, 0xFC))

divider(slide, Inches(4.15), color=RGBColor(0x4F, 0x46, 0xE5), thickness=Pt(1.5))

txt(slide, "越用越懂你  ·  数据驱动  ·  持续成长",
    Inches(0.9), Inches(4.35), Inches(8), Inches(0.45),
    size=16, color=RGBColor(0xC7, 0xD2, 0xFE))

# bottom meta
txt(slide, "机密文件 · 仅供内部使用", Inches(0.9), Inches(6.85), Inches(5), Inches(0.35),
    size=11, color=RGBColor(0x6B, 0x72, 0x80))
txt(slide, "2026.04", Inches(11.8), Inches(6.85), Inches(1.3), Inches(0.35),
    size=11, color=RGBColor(0x6B, 0x72, 0x80), align=PP_ALIGN.RIGHT)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 02 — AGENDA
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("今日议程", "本次汇报覆盖市场机会、产品价值、技术壁垒与商业路径")

items = [
    ("01", "市场机会",      "8000万创作者，一个被低估的需求"),
    ("02", "产品定位",      "越用越懂你的 AI 内容医生"),
    ("03", "核心技术壁垒",  "内容质量 × 市场时机的双维预测引擎"),
    ("04", "竞争格局",      "与竞品的本质差异"),
    ("05", "商业模式",      "用户分层定价与收入路径"),
    ("06", "增长路径",      "三阶段里程碑与关键指标"),
    ("07", "融资需求",      "资金用途与预期回报"),
]
for i, (num, title, sub) in enumerate(items):
    row = i // 1
    col = i % 1
    lx = Inches(0.5)
    ly = Inches(1.75) + Inches(0.72) * i
    rect(slide, lx, ly, Inches(0.42), Inches(0.42), fill=INDIGO)
    txt(slide, num, lx, ly+Inches(0.04), Inches(0.42), Inches(0.38),
        size=13, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    txt(slide, title, lx+Inches(0.55), ly+Inches(0.0), Inches(2.8), Inches(0.25),
        size=14, bold=True, color=DARK)
    txt(slide, sub,   lx+Inches(0.55), ly+Inches(0.23), Inches(9), Inches(0.22),
        size=11, color=SLATE)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 03 — MARKET OPPORTUNITY
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("市场机会", "小红书内容创作者的系统性痛点从未被真正解决")

stats = [
    ("8,000万+", "小红书活跃创作者", INDIGO, INDIGO_L),
    ("95%+",     "创作者无系统内容分析工具", RED, RED_L),
    ("50-500元", "创作者月均付费意愿", EMERALD, EMERALD_L),
    ("¥120亿+",  "内容工具潜在市场规模 TAM", PURPLE, PURPLE_L),
]
for i, (val, label, fg, bg) in enumerate(stats):
    lx = Inches(0.5) + Inches(3.2) * i
    rect(slide, lx, Inches(1.75), Inches(2.95), Inches(1.85), fill=bg)
    txt(slide, val, lx+Inches(0.18), Inches(1.95), Inches(2.6), Inches(0.85),
        size=34, bold=True, color=fg, align=PP_ALIGN.CENTER)
    txt(slide, label, lx+Inches(0.1), Inches(2.85), Inches(2.75), Inches(0.55),
        size=12, color=DARK, align=PP_ALIGN.CENTER)

# Pain points
txt(slide, "创作者的核心痛点", Inches(0.5), Inches(3.85), Inches(5), Inches(0.35),
    size=14, bold=True, color=DARK)
pains = [
    "笔记数据忽高忽低，找不到规律，不知道哪个环节出了问题",
    "现有工具给出「优化标题」等空泛建议，无法落地执行",
    "内容诊断每次从零开始，没有任何工具记住我的风格和历史",
    "不知道当前发布的时机是否合适，热点是否踩准",
]
for i, p in enumerate(pains):
    lx = Inches(0.5)
    ly = Inches(4.3) + Inches(0.55) * i
    rect(slide, lx, ly+Inches(0.1), Inches(0.08), Inches(0.2), fill=INDIGO)
    txt(slide, p, lx+Inches(0.22), ly, Inches(12.3), Inches(0.42),
        size=13, color=DARK)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 04 — PRODUCT POSITIONING
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("产品定位", "三大引擎构建「越用越懂你」的 AI 内容医生")

# Vision box
rect(slide, Inches(0.5), Inches(1.75), Inches(12.33), Inches(0.75), fill=INDIGO)
txt(slide, "让每一位小红书创作者，都能像顶级 MCN 机构一样，获得专业的、数据驱动的、持续陪伴的内容成长服务",
    Inches(0.7), Inches(1.85), Inches(11.9), Inches(0.55),
    size=14, bold=False, color=WHITE, align=PP_ALIGN.CENTER)

engines = [
    ("量化基线引擎",    INDIGO, INDIGO_L,
     "Model A",
     "5万+本地生活笔记训练\nLightGBM <50ms推理\n内容质量客观评分\n每周自动重训"),
    ("多Agent辩论引擎", PURPLE, PURPLE_L,
     "5 Expert Agents",
     "封面/标题/内容/标签/时机\n5大Agent并行诊断\n置信度+分歧暴露\n仲裁整合行动清单"),
    ("持久记忆引擎",    EMERALD, EMERALD_L,
     "User Memory",
     "跨会话记住你的风格\n历史痛点积累\n越用越懂你\nHermes架构借鉴"),
]
for i, (name, fg, bg, tag, desc) in enumerate(engines):
    lx = Inches(0.5) + Inches(4.12) * i
    rect(slide, lx, Inches(2.7), Inches(3.9), Inches(4.35), fill=bg)
    rect(slide, lx, Inches(2.7), Inches(3.9), Inches(0.55), fill=fg)
    txt(slide, name, lx+Inches(0.15), Inches(2.75), Inches(3.6), Inches(0.45),
        size=14, bold=True, color=WHITE)
    txt(slide, tag, lx+Inches(0.15), Inches(3.4), Inches(3.6), Inches(0.35),
        size=11, bold=True, color=fg)
    for j, line in enumerate(desc.split('\n')):
        ldy = Inches(3.8) + Inches(0.45) * j
        rect(slide, lx+Inches(0.15), ldy+Inches(0.14), Inches(0.1), Inches(0.1), fill=fg)
        txt(slide, line, lx+Inches(0.35), ldy, Inches(3.4), Inches(0.4),
            size=12, color=DARK)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 05 — CORE TECH MOAT
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("核心技术壁垒", "内容质量 × 市场时机 — 全球首个面向中文创作者的双维预测模型",
                          tag="技术护城河", tag_color=PURPLE, tag_bg=PURPLE_L)

# Formula
rect(slide, Inches(0.5), Inches(1.75), Inches(12.33), Inches(1.0), fill=INDIGO_L)
txt(slide, "综合评分  =  内容质量分（Content Score）×  市场时机系数（Market Timing）",
    Inches(0.7), Inches(1.9), Inches(11.9), Inches(0.7),
    size=18, bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

# Two columns
cols = [
    ("内容质量分  35个特征", INDIGO, INDIGO_L, [
        "封面表现力 · 28%权重（色温/人脸/食物/文字贴片）",
        "标题吸引力 · 22%权重（情绪词/价格/城市/热词）",
        "内容实用性 · 22%权重（地址/价格/交通/CTA引导）",
        "标签策略   · 16%权重（POI标签/大中小词梯度）",
        "发布时机   · 12%权重（决策窗口/节假日前）",
    ]),
    ("市场时机系数  8个特征  ★护城河", PURPLE, PURPLE_L, [
        "trend_momentum：热词趋势斜率（上升/下降/平稳）",
        "trend_peak_distance：距热词峰值天数",
        "category_saturation：品类本周新发笔记数",
        "keyword_search_vol：主标签实时搜索量指数",
        "is_trending_topic：是否命中平台推荐话题",
        "content_freshness：话题从首次出现至今天数",
    ]),
]
for i, (title, fg, bg, items) in enumerate(cols):
    lx = Inches(0.5) + Inches(6.35) * i
    rect(slide, lx, Inches(2.9), Inches(6.1), Inches(0.42), fill=fg)
    txt(slide, title, lx+Inches(0.15), Inches(2.95), Inches(5.8), Inches(0.34),
        size=12, bold=True, color=WHITE)
    for j, item in enumerate(items):
        ly = Inches(3.42) + Inches(0.52) * j
        rect(slide, lx+Inches(0.15), ly+Inches(0.17), Inches(0.1), Inches(0.1), fill=fg)
        txt(slide, item, lx+Inches(0.35), ly, Inches(5.6), Inches(0.45),
            size=11, color=DARK)

# vs competitors note
rect(slide, Inches(0.5), Inches(6.6), Inches(12.33), Inches(0.55), fill=ORANGE_L)
txt(slide, "千瓜/新红：回顾性分析「上周哪些笔记爆了」    NoteAI Pro：前瞻性预测「你这篇笔记当前能跑多远 + 把哪个词换成热词X可提升N%」",
    Inches(0.7), Inches(6.68), Inches(11.9), Inches(0.4),
    size=11, bold=False, color=RGBColor(0x92, 0x40, 0x0E), align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 06 — DATA FLYWHEEL
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("数据飞轮 — 时间越长壁垒越深", "两套数据系统驱动模型持续进化")

# Flywheel diagram (simplified as boxes + arrows)
steps = [
    (Inches(1.0),  Inches(2.0),  "每日爬虫采集",      "1,200-1,500条/天\n本地生活8大品类",    INDIGO,  INDIGO_L),
    (Inches(4.3),  Inches(2.0),  "特征工程提取",      "43个特征自动计算\n市场时机每6小时更新", PURPLE,  PURPLE_L),
    (Inches(7.6),  Inches(2.0),  "LightGBM训练",      "每周自动重训\nMLflow版本管理",          EMERALD, EMERALD_L),
    (Inches(10.3), Inches(3.5),  "用户获得诊断",      "双维评分+可解释建议\n<50ms推理",         ORANGE,  ORANGE_L),
    (Inches(7.0),  Inches(5.0),  "用户发布笔记",      "采纳建议后实际发布",                     RED,     RED_L),
    (Inches(3.2),  Inches(5.0),  "真实数据回流",      "互动数据校准模型\n建议有效性验证",        INDIGO,  INDIGO_L),
]
for (lx, ly, title, desc, fg, bg) in steps:
    rect(slide, lx, ly, Inches(2.8), Inches(1.15), fill=bg)
    rect(slide, lx, ly, Inches(2.8), Inches(0.38), fill=fg)
    txt(slide, title, lx+Inches(0.1), ly+Inches(0.05), Inches(2.6), Inches(0.3),
        size=12, bold=True, color=WHITE)
    for j, line in enumerate(desc.split('\n')):
        txt(slide, line, lx+Inches(0.1), ly+Inches(0.46)+Inches(0.28)*j,
            Inches(2.6), Inches(0.26), size=10, color=DARK)

txt(slide, "护城河：模型随用户数据积累越来越准，竞品无法复制已积累的校准数据",
    Inches(0.5), Inches(6.7), Inches(12.33), Inches(0.4),
    size=12, bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 07 — COMPETITIVE LANDSCAPE
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("竞争格局", "市场上尚无真正的数据驱动型小红书内容诊断平台")

headers = ["能力维度", "千瓜/新红数据", "通用AI写作工具", "NoteRx（薯医）", "NoteAI Pro ★"]
rows = [
    ["训练数据量",   "海量（分析用）",  "无专项训练",   "874条（静态）",   "5万+持续每日更新"],
    ["预测 vs 分析", "回顾性分析",      "无",           "简单评分",        "前瞻性双维预测"],
    ["本地生活专项", "泛品类",          "无",           "无专项",          "8大品类深度优化"],
    ["用户记忆",     "无",              "无",           "无",              "跨会话持久记忆"],
    ["市场时机感知", "部分热词报告",    "无",           "无",              "每6小时实时更新"],
    ["数据闭环",     "无",              "无",           "无",              "发布结果→模型校准"],
    ["商业定位",     "分析平台",        "写作辅助",     "黑客松Demo",      "AI成长陪伴平台"],
]
col_w = [Inches(2.1), Inches(2.0), Inches(2.1), Inches(2.0), Inches(2.45)]
col_colors = [GRAY_L, GRAY_L, GRAY_L, GRAY_L, INDIGO_L]
hdr_colors = [DARK,   GRAY,   GRAY,   GRAY,   INDIGO]

# header row
lx = Inches(0.35)
for j, (h, cw, hc) in enumerate(zip(headers, col_w, hdr_colors)):
    bg = INDIGO if j == 4 else DARK if j == 0 else RGBColor(0x6B, 0x72, 0x80)
    rect(slide, lx, Inches(1.75), cw, Inches(0.45), fill=bg)
    txt(slide, h, lx+Inches(0.08), Inches(1.8), cw-Inches(0.1), Inches(0.35),
        size=11, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    lx += cw

for i, row in enumerate(rows):
    lx = Inches(0.35)
    ly = Inches(2.3) + Inches(0.62) * i
    for j, (cell, cw, cbg) in enumerate(zip(row, col_w, col_colors)):
        bg = INDIGO_L if j == 4 else (GRAY_L if i % 2 == 0 else WHITE)
        rect(slide, lx, ly, cw, Inches(0.55), fill=bg)
        c = INDIGO if j == 4 else DARK if j == 0 else GRAY
        b = True if j in [0, 4] else False
        txt(slide, cell, lx+Inches(0.08), ly+Inches(0.08),
            cw-Inches(0.1), Inches(0.4),
            size=10, bold=b, color=c, align=PP_ALIGN.CENTER)
        lx += cw

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 08 — TARGET USERS
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("目标用户", "三类付费意愿明确的用户群，覆盖从素人到机构的完整链条")

users = [
    ("用户A  成长期素人创作者", INDIGO, INDIGO_L,
     "粉丝 500~5万，发帖 1-3次/周",
     ["笔记数据忽高忽低，找不到规律", "发完笔记焦虑等数据，偶尔求互评"],
     "50~200 元/月",
     "数量最大，付费意愿强"),
    ("用户B  内容变现型创作者", PURPLE, PURPLE_L,
     "粉丝 5~100万，有固定品类",
     ["种草效果下降，系统性优化需求", "品牌合作要求提升互动率"],
     "200~500 元/月",
     "ARPU最高，粘性最强"),
    ("用户C  MCN机构/品牌团队", EMERALD, EMERALD_L,
     "管理 5~50个达人账号",
     ["批量内容质检效率低", "缺乏标准化内容评分体系"],
     "企业定制报价",
     "客单价最高，B端扩展"),
]
for i, (name, fg, bg, profile, pains, price, note) in enumerate(users):
    lx = Inches(0.4) + Inches(4.22) * i
    rect(slide, lx, Inches(1.75), Inches(4.0), Inches(5.35), fill=bg)
    rect(slide, lx, Inches(1.75), Inches(4.0), Inches(0.48), fill=fg)
    txt(slide, name, lx+Inches(0.15), Inches(1.8), Inches(3.7), Inches(0.38),
        size=12, bold=True, color=WHITE)
    txt(slide, profile, lx+Inches(0.15), Inches(2.35), Inches(3.7), Inches(0.3),
        size=11, color=SLATE, italic=True)
    txt(slide, "核心痛点", lx+Inches(0.15), Inches(2.75), Inches(3.7), Inches(0.28),
        size=11, bold=True, color=fg)
    for j, p in enumerate(pains):
        ly = Inches(3.08) + Inches(0.42) * j
        rect(slide, lx+Inches(0.15), ly+Inches(0.14), Inches(0.09), Inches(0.09), fill=fg)
        txt(slide, p, lx+Inches(0.32), ly, Inches(3.5), Inches(0.38), size=11, color=DARK)
    rect(slide, lx+Inches(0.15), Inches(4.1), Inches(3.7), Inches(0.42), fill=fg)
    txt(slide, "月付费意愿：" + price, lx+Inches(0.2), Inches(4.15),
        Inches(3.5), Inches(0.34), size=12, bold=True, color=WHITE)
    txt(slide, note, lx+Inches(0.15), Inches(4.65), Inches(3.7), Inches(0.3),
        size=11, color=fg, italic=True)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 09 — BUSINESS MODEL
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("商业模式", "分层订阅制 + 企业定制，覆盖不同规模创作者需求")

plans = [
    ("免费版", "0元/月", GRAY,   GRAY_L,  WHITE, [
        "每月 3 次完整诊断",
        "基础量化评分（3维）",
        "7天历史记忆",
    ], "获客漏斗入口"),
    ("成长版", "99元/月", INDIGO, INDIGO_L, WHITE, [
        "无限次诊断",
        "完整 5 维评分 + 市场时机",
        "无限历史记忆",
        "A/B 改写方案",
    ], "核心付费用户"),
    ("专业版", "299元/月", PURPLE, PURPLE_L, WHITE, [
        "成长版全部功能",
        "爆款对标竞品分析",
        "发布效果追踪回流",
        "优先 Agent 推理队列",
    ], "变现型创作者"),
    ("企业版", "定制报价", DARK,   DARK,   WHITE, [
        "批量账号管理",
        "API 接口调用",
        "专属数据看板",
        "SLA 服务保障",
    ], "MCN/品牌团队"),
]
for i, (name, price, fg, bg, tc, features, note) in enumerate(plans):
    lx = Inches(0.35) + Inches(3.2) * i
    rect(slide, lx, Inches(1.75), Inches(3.0), Inches(5.0), fill=bg)
    rect(slide, lx, Inches(1.75), Inches(3.0), Inches(1.0), fill=fg)
    txt(slide, name,  lx+Inches(0.15), Inches(1.82), Inches(2.7), Inches(0.35),
        size=14, bold=True, color=WHITE)
    txt(slide, price, lx+Inches(0.15), Inches(2.17), Inches(2.7), Inches(0.5),
        size=22, bold=True, color=WHITE)
    for j, feat in enumerate(features):
        ly = Inches(2.9) + Inches(0.48) * j
        rect(slide, lx+Inches(0.15), ly+Inches(0.17), Inches(0.09), Inches(0.09), fill=fg if fg != DARK else EMERALD)
        txt(slide, feat, lx+Inches(0.32), ly, Inches(2.55), Inches(0.42),
            size=11, color=DARK if bg != DARK else WHITE)
    rect(slide, lx+Inches(0.12), Inches(6.2), Inches(2.76), Inches(0.35), fill=fg if fg != GRAY else RGBColor(0xE5,0xE7,0xEB))
    txt(slide, note, lx+Inches(0.15), Inches(6.25), Inches(2.7), Inches(0.28),
        size=10, bold=True, color=WHITE if fg != GRAY else GRAY, align=PP_ALIGN.CENTER)

# Revenue projection note
txt(slide, "Phase 3 目标：月收入 10万 RMB  ·  注册用户 50,000  ·  付费转化率 5%",
    Inches(0.35), Inches(6.75), Inches(12.5), Inches(0.38),
    size=12, bold=True, color=INDIGO, align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 10 — ROADMAP
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("增长路径", "三阶段里程碑，从冷启动到商业化闭环")

phases = [
    ("Phase 1", "第1-3个月", "MVP 上线", INDIGO, INDIGO_L, [
        "爬虫冷启动：40天采集5万条",
        "Model A v1.0 训练上线",
        "5 Agent 诊断引擎",
        "用户记忆基础版",
        "目标：注册用户 1,000",
    ]),
    ("Phase 2", "第4-6个月", "成长与验证", PURPLE, PURPLE_L, [
        "对话式迭代优化上线",
        "发布效果追踪回流",
        "爆款对标分析功能",
        "模型校准第一轮",
        "目标：MAU 5,000 / 月收入5万",
    ]),
    ("Phase 3", "第7-12个月", "商业化规模", EMERALD, EMERALD_L, [
        "数据飞轮完整闭环",
        "企业版/API开放",
        "多平台扩展（抖音/B站）",
        "RL强化学习迭代",
        "目标：用户5万 / 月收入10万",
    ]),
]
for i, (phase, period, title, fg, bg, milestones) in enumerate(phases):
    lx = Inches(0.4) + Inches(4.25) * i
    rect(slide, lx, Inches(1.75), Inches(4.0), Inches(5.2), fill=bg)
    rect(slide, lx, Inches(1.75), Inches(4.0), Inches(0.85), fill=fg)
    txt(slide, phase,  lx+Inches(0.15), Inches(1.8),  Inches(3.7), Inches(0.35),
        size=14, bold=True, color=WHITE)
    txt(slide, period, lx+Inches(0.15), Inches(2.18), Inches(3.7), Inches(0.28),
        size=11, color=RGBColor(0xC7,0xD2,0xFC) if fg==INDIGO else WHITE)
    txt(slide, title,  lx+Inches(0.15), Inches(2.6),  Inches(3.7), Inches(0.3),
        size=12, bold=True, color=fg)
    for j, m in enumerate(milestones):
        ly = Inches(3.0) + Inches(0.46) * j
        rect(slide, lx+Inches(0.15), ly+Inches(0.16), Inches(0.09), Inches(0.09), fill=fg)
        txt(slide, m, lx+Inches(0.32), ly, Inches(3.5), Inches(0.4),
            size=11, color=DARK)

# OKR table
txt(slide, "关键指标", Inches(0.4), Inches(7.05), Inches(2), Inches(0.28),
    size=11, bold=True, color=DARK)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 11 — KEY METRICS
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("核心成功指标", "三阶段量化目标，清晰可追踪")

metrics = [
    ("注册用户数",    "1,000",  "10,000",  "50,000"),
    ("月活跃用户MAU", "500",    "5,000",   "25,000"),
    ("月度收入",      "0",      "5万 RMB", "10万 RMB"),
    ("诊断满意度NPS", ">30",    ">50",     ">65"),
    ("训练笔记总量",  "5万条",  "20万条",  "50万条+"),
    ("日均新增样本",  "1,200+", "2,000+",  "5,000+"),
    ("付费转化率",    "—",      "3%+",     "5%+"),
]
hdrs = ["指标", "Phase 1（1-3月）", "Phase 2（4-6月）", "Phase 3（7-12月）"]
col_w2 = [Inches(3.2), Inches(2.8), Inches(2.8), Inches(2.8)]
col_fg2 = [DARK, INDIGO, PURPLE, EMERALD]

lx = Inches(0.6)
for j, (h, cw, fg) in enumerate(zip(hdrs, col_w2, col_fg2)):
    rect(slide, lx, Inches(1.75), cw, Inches(0.45), fill=fg)
    txt(slide, h, lx+Inches(0.1), Inches(1.8), cw-Inches(0.15), Inches(0.35),
        size=12, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
    lx += cw

for i, (metric, p1, p2, p3) in enumerate(metrics):
    ly = Inches(2.3) + Inches(0.6) * i
    lx = Inches(0.6)
    bg_row = GRAY_L if i % 2 == 0 else WHITE
    for j, (val, cw) in enumerate(zip([metric, p1, p2, p3], col_w2)):
        bg = INDIGO_L if j==1 else PURPLE_L if j==2 else EMERALD_L if j==3 else bg_row
        rect(slide, lx, ly, cw, Inches(0.54), fill=bg)
        c = col_fg2[j] if j > 0 else DARK
        b = True if j > 0 else False
        txt(slide, val, lx+Inches(0.1), ly+Inches(0.1),
            cw-Inches(0.15), Inches(0.38),
            size=12, bold=b, color=c, align=PP_ALIGN.CENTER)
        lx += cw

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 12 — INVESTMENT ASK
# ══════════════════════════════════════════════════════════════════════════════
slide = slide_with_header("融资需求", "种子轮融资，加速技术壁垒建设与早期用户获取",
                          tag="融资计划", tag_color=EMERALD, tag_bg=EMERALD_L)

# Total ask
rect(slide, Inches(0.5), Inches(1.75), Inches(12.33), Inches(1.1), fill=INDIGO)
txt(slide, "寻求种子轮融资  ·  目标金额：200-500万 RMB",
    Inches(0.7), Inches(1.9), Inches(11.9), Inches(0.55),
    size=22, bold=True, color=WHITE, align=PP_ALIGN.CENTER)
txt(slide, "用途：12个月 Runway · 覆盖技术开发 + 数据采集 + 早期市场",
    Inches(0.7), Inches(2.5), Inches(11.9), Inches(0.28),
    size=13, color=RGBColor(0xC7,0xD2,0xFC), align=PP_ALIGN.CENTER)

uses = [
    ("40%", "技术研发",   "爬虫基础设施/Model A训练/\nAgent引擎/用户端产品", INDIGO, INDIGO_L),
    ("25%", "数据采集",   "住宅代理IP池/账号池/\nClaude Haiku图片分析",     PURPLE, PURPLE_L),
    ("20%", "市场推广",   "KOL种草/社群运营/\n早期用户激励计划",             EMERALD,EMERALD_L),
    ("15%", "运营与合规", "服务器/团队/\n法律合规咨询",                        ORANGE, ORANGE_L),
]
for i, (pct, name, desc, fg, bg) in enumerate(uses):
    lx = Inches(0.5) + Inches(3.1) * i
    rect(slide, lx, Inches(3.05), Inches(2.9), Inches(2.5), fill=bg)
    txt(slide, pct,  lx+Inches(0.15), Inches(3.15), Inches(2.6), Inches(0.7),
        size=36, bold=True, color=fg, align=PP_ALIGN.CENTER)
    txt(slide, name, lx+Inches(0.15), Inches(3.9),  Inches(2.6), Inches(0.35),
        size=13, bold=True, color=DARK, align=PP_ALIGN.CENTER)
    for j, line in enumerate(desc.split('\n')):
        txt(slide, line, lx+Inches(0.15), Inches(4.35)+Inches(0.28)*j,
            Inches(2.6), Inches(0.26), size=10, color=SLATE, align=PP_ALIGN.CENTER)

# Expected returns
rect(slide, Inches(0.5), Inches(5.75), Inches(12.33), Inches(0.6), fill=EMERALD_L)
txt(slide, "预期回报路径：12个月达 MAU 5,000 · 月收入 5万 RMB · 完成 Pre-A 融资条件 · 中期目标：内容创作者 SaaS 赛道标杆产品",
    Inches(0.7), Inches(5.85), Inches(11.9), Inches(0.4),
    size=12, color=RGBColor(0x06, 0x5F, 0x46), align=PP_ALIGN.CENTER)

# ══════════════════════════════════════════════════════════════════════════════
# SLIDE 13 — CLOSING
# ══════════════════════════════════════════════════════════════════════════════
slide = new_slide()
rect(slide, 0, 0, W, H, fill=DARK)
rect(slide, 0, 0, W, Inches(0.08), fill=INDIGO)
s = slide.shapes.add_shape(9, Inches(9), Inches(-1), Inches(6), Inches(6))
s.fill.solid(); s.fill.fore_color.rgb = RGBColor(0x31,0x27,0xAE)
s.line.fill.background()

txt(slide, "谢谢", Inches(1.0), Inches(1.8), Inches(8), Inches(1.3),
    size=72, bold=True, color=WHITE)
txt(slide, "让每一位创作者，都能用上顶级 MCN 的内容策略",
    Inches(1.0), Inches(3.1), Inches(9), Inches(0.6),
    size=20, color=RGBColor(0xA5,0xB4,0xFC))

divider(slide, Inches(3.9), color=INDIGO, thickness=Pt(1.5))

contacts = [
    ("产品演示", "NoteAI_Pro_Demo.html"),
    ("完整PRD",  "NoteAI_Pro_PRD_v1.2.docx"),
    ("联系方式", "iamyusen1314@gmail.com"),
]
for i, (label, val) in enumerate(contacts):
    ly = Inches(4.2) + Inches(0.6) * i
    txt(slide, label + "：", Inches(1.0), ly, Inches(1.8), Inches(0.4),
        size=13, color=RGBColor(0x6B,0x72,0x80))
    txt(slide, val, Inches(2.8), ly, Inches(7), Inches(0.4),
        size=13, bold=True, color=WHITE)

txt(slide, "NoteAI Pro  ·  Confidential  ·  2026",
    Inches(1.0), Inches(6.85), Inches(10), Inches(0.35),
    size=11, color=RGBColor(0x4B,0x55,0x63))

# ─── Save ────────────────────────────────────────────────────────────────────
out = "/Users/samyu/Desktop/projects/noteai/NoteAI_Pro_PitchDeck_2026.pptx"
prs.save(out)
print(f"✅ PPT 生成成功：{out}")
print(f"   共 {len(prs.slides)} 张幻灯片")
