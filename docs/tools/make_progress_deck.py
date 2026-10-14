#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段进展汇报版 PPT（面向集团检查工作进展）：进度·结果·困难·计划。
系统介绍压缩至 2 页；口径只陈述事实与已验证数据，不做预测性承诺。"""
import os
from pptx import Presentation
from pptx.util import Inches, Pt
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE
from pathlib import Path

NAVY = RGBColor(0x1F, 0x4E, 0x79); BLUE = RGBColor(0x2E, 0x75, 0xB6); LIGHT = RGBColor(0xDD, 0xEB, 0xF7)
GREEN = RGBColor(0x54, 0x82, 0x35); LGREEN = RGBColor(0xE2, 0xEF, 0xDA); AMBER = RGBColor(0xBF, 0x8F, 0x00)
YELL = RGBColor(0xFF, 0xD9, 0x66); BG = RGBColor(0xF4, 0xF6, 0xFA); DARK = RGBColor(0x33, 0x33, 0x33); GRAY = RGBColor(0x88, 0x88, 0x88)
RED = RGBColor(0xC0, 0x50, 0x4D)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
FONT = "微软雅黑"

prs = Presentation(); prs.slide_width = Inches(13.333); prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]
W, H = 13.333, 7.5
total = [0]

def slide():
    s = prs.slides.add_slide(BLANK); total[0] += 1
    r = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    r.fill.solid(); r.fill.fore_color.rgb = BG; r.line.fill.background(); r.shadow.inherit = False
    return s

def box(s, x, y, w, h, fill=None, line=None, round_=False):
    shp = s.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE if round_ else MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    if round_:
        try: shp.adjustments[0] = 0.08
        except Exception: pass
    if fill is None: shp.fill.background()
    else: shp.fill.solid(); shp.fill.fore_color.rgb = fill
    if line is None: shp.line.fill.background()
    else: shp.line.color.rgb = line; shp.line.width = Pt(1.5)
    shp.shadow.inherit = False
    return shp

def text(s, x, y, w, h, runs, size=18, color=DARK, bold=False, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, leading=1.15):
    tb = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h)); tf = tb.text_frame
    tf.word_wrap = True; tf.vertical_anchor = anchor
    if isinstance(runs, str): runs = [runs]
    for i, ln in enumerate(runs):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.alignment = align; para.line_spacing = leading
        parts = ln if isinstance(ln, list) else [(ln, {})]
        for t, st in parts:
            r = para.add_run(); r.text = t
            r.font.name = FONT; r.font.size = Pt(st.get("size", size))
            r.font.bold = st.get("bold", bold); r.font.color.rgb = st.get("color", color)
    return tb

def header(s, title, sub=None, chapter=None):
    box(s, 0, 0, W, 1.05, fill=NAVY)
    box(s, 0, 1.05, W, 0.06, fill=YELL)
    text(s, 0.55, 0.16, 9.6, 0.8, title, size=27, color=WHITE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    if chapter:
        text(s, 10.2, 0.16, 2.7, 0.8, chapter, size=13, color=LIGHT, align=PP_ALIGN.RIGHT, anchor=MSO_ANCHOR.MIDDLE)
    if sub:
        text(s, 0.55, 1.25, 12.2, 0.5, sub, size=14, color=GRAY)
    text(s, 0.55, 7.05, 6, 0.4, "小罡 AI · 物料集团码智能匹配平台 · 阶段进展汇报", size=10, color=GRAY)

def table(s, rows, x, y, col_w, header_fill=NAVY, size=13, hsize=14, last_bold=False):
    gtab = s.shapes.add_table(len(rows), len(rows[0]), Inches(x), Inches(y), Inches(sum(col_w)), Inches(0.42 * len(rows))).table
    for ci, cw in enumerate(col_w): gtab.columns[ci].width = Inches(cw)
    for ri, row in enumerate(rows):
        for ci, val in enumerate(row):
            cell = gtab.cell(ri, ci); cell.text = str(val)
            for pr in cell.text_frame.paragraphs:
                for r in pr.runs:
                    r.font.name = FONT; r.font.size = Pt(hsize if ri == 0 else size)
                    r.font.bold = (ri == 0 or (last_bold and ri == len(rows) - 1))
                    r.font.color.rgb = WHITE if ri == 0 else DARK
            cell.fill.solid()
            cell.fill.fore_color.rgb = header_fill if ri == 0 else (LIGHT if (last_bold and ri == len(rows) - 1) else (WHITE if ri % 2 else RGBColor(0xEF, 0xF4, 0xFA)))
            cell.margin_left = Inches(0.12); cell.margin_top = Inches(0.03); cell.margin_bottom = Inches(0.03)
    return gtab

# ============ 1 封面 ============
s = slide()
box(s, 0, 0, W, H, fill=NAVY)
box(s, 0, 4.9, W, 0.07, fill=YELL)
text(s, 0.9, 1.9, 11.5, 1.2, "物料集团码智能匹配平台", size=50, color=WHITE, bold=True)
text(s, 0.95, 3.15, 11.5, 0.7, "阶段进展汇报：匹配结果 · 存在困难 · 下一步计划", size=24, color=YELL)
text(s, 0.95, 5.5, 8, 0.5, "SAP 物料与集团编码批量匹配 · 离线内网部署 · 数据不出域", size=15, color=LIGHT)
text(s, 0.95, 6.1, 8, 0.5, "2026 年 10 月", size=15, color=LIGHT)

# ============ 2 汇报要点 ============
s = slide(); header(s, "汇报要点", None, None)
points = [
    ("已完成", "匹配平台在集团内网部署并投入实际批次使用；首批 6 大类物料共 71,478 行完成自动匹配初筛，其中 16,795 行由系统直接给出匹配结论。", GREEN),
    ("当前困难", "同一物料在型号规格、供应商、质量等级上的信息差异，导致系统无法认定为同一物料；以 SAP元器件为例自动匹配率约 12%，其余需人工核对候选。", AMBER),
    ("下一步", "业务侧整理供应商对照表等基础数据入库；约 5.5 万行候选由业务员在系统内分批核对确认；约束规则按类别逐步推广。", NAVY),
]
y = 1.7
for t, d, c in points:
    box(s, 0.8, y, 11.7, 1.55, fill=WHITE, line=LIGHT, round_=True)
    box(s, 0.8, y, 0.14, 1.55, fill=c)
    text(s, 1.25, y + 0.12, 2.2, 1.3, t, size=20, color=c, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 3.6, y + 0.12, 8.7, 1.35, d, size=14.5, color=DARK, anchor=MSO_ANCHOR.MIDDLE, leading=1.3)
    y += 1.78

# ============ 3 系统与方法（一页） ============
s = slide(); header(s, "系统与方法", "离线部署的匹配工具：AI 语义召回 + 业务规则约束 + 人工复核闭环", None)
steps = [
    ("① 配置方案", "字段映射、值映射（同义词）、匹配方式与权重、自动通过阈值；方案一次配置、多批复用"),
    ("② 批量匹配", "对全量集团标准库（10 万～百万级）做语义相似度召回，按规则逐字段打分，输出 Top5 候选与相似度"),
    ("③ 人工复核", "自动阈值以上直接通过；其余在系统内或 Excel 工作簿按「候选1～5 / 均不匹配」批量确认"),
    ("④ 结果输出", "正式 Excel：逐行结论 + 依据字段 + 操作留痕，结果版本可追溯、可回退"),
]
x = 0.7
for t, d in steps:
    box(s, x, 1.9, 2.85, 3.3, fill=WHITE, line=LIGHT, round_=True)
    text(s, x + 0.18, 2.1, 2.5, 0.6, t, size=17, color=NAVY, bold=True)
    text(s, x + 0.18, 2.75, 2.5, 2.3, d, size=12.5, color=DARK, leading=1.3)
    x += 3.02
text(s, 0.7, 5.6, 11.9, 1.2, [
    [("规则约束示例：", {"bold": True, "color": NAVY}),
     ("SAP元器件已启用「质量等级不一致即否决」——语义相似度再高，质量等级不同则不自动匹配；供应商、型号规格、封装形式同场比对。", {})],
    [("运行环境：", {"bold": True, "color": NAVY}), ("集团内网离线运行，物料数据不出域；浏览器访问，支持既有内网终端。", {})],
], size=13.5, leading=1.45)

# ============ 4 已完成的工作 ============
s = slide(); header(s, "已完成的工作", "从平台交付到首批数据实跑，全部在集团内网闭环完成", None)
done_rows = [
    ("平台交付与部署", "离线介质制作与内网部署（服务器 + 业务终端浏览器访问）；数据全程不出域；已完成三轮现场升级（9/24、9/28、10/14），当前版本 v1.3.24"),
    ("匹配方案体系", "按物料类别建立 6 套标准匹配方案（元器件/标准件/金属材料/非金属材料/复合材料/物资类其它），字段映射、值映射、同义词库、阈值全部按业务口径配置并版本化留痕"),
    ("引擎能力落地", "AI 语义召回（10 万～百万级集团标准库）+ 逐字段规则打分 + 拼接比对 + 一票否决约束；SAP元器件已实装「质量等级不一致即否决」，并同步比对供应商、型号规格、封装形式"),
    ("人工复核闭环", "第三步批量复核 + Excel 工作簿导出/回填；操作留痕、结果版本可追溯可回退；同义词支持 Excel 批量导入与批量维护"),
    ("首批实际数据验证", "6 大类 71,478 行真实物料完成匹配初筛，16,795 行自动给出结论，其余输出 Top5 候选进入人工复核队列"),
]
y = 1.85
for t, d in done_rows:
    box(s, 0.7, y, 11.9, 0.9, fill=WHITE, line=LIGHT, round_=True)
    box(s, 0.7, y, 0.14, 0.9, fill=GREEN)
    text(s, 1.1, y + 0.04, 2.75, 0.82, t, size=14, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE, leading=1.12)
    text(s, 4.0, y + 0.04, 8.45, 0.82, d, size=11.5, color=DARK, anchor=MSO_ANCHOR.MIDDLE, leading=1.2)
    y += 0.98
text(s, 0.72, 6.72, 11.9, 0.3, "以上能力均已在现场环境经真实数据验证可用。", size=12.5, color=GREEN, bold=True)

# ============ 5 初步匹配结果 ============
s = slide(); header(s, "初步匹配结果（首批实际数据）", "自动匹配为系统直接给出结论的行；其余系统输出最相似候选，交人工复核", None)
res_rows = [("物料类别", "自动匹配", "总条数", "自动匹配占比"),
            ("SAP元器件", "4,968", "40,888", "12.2%"),
            ("标准件", "4,100", "4,417", "92.8%"),
            ("金属材料", "4,975", "6,655", "74.8%"),
            ("非金属材料", "2,180", "3,750", "58.1%"),
            ("复合材料", "336", "519", "64.7%"),
            ("物资类其它", "236", "15,249", "1.5%"),
            ("合计", "16,795", "71,478", "23.5%")]
table(s, res_rows, 0.7, 1.8, [2.6, 1.9, 1.9, 1.9], last_bold=True)
box(s, 9.35, 1.8, 3.3, 2.1, fill=WHITE, line=LIGHT, round_=True)
text(s, 9.45, 2.05, 3.1, 0.75, "16,795", size=34, color=NAVY, bold=True, align=PP_ALIGN.CENTER)
text(s, 9.45, 2.85, 3.1, 0.45, "行自动匹配 / 共 71,478 行", size=13, color=DARK, align=PP_ALIGN.CENTER)
text(s, 9.45, 3.3, 3.1, 0.45, "其余输出最相似候选供人工复核", size=11, color=GRAY, align=PP_ALIGN.CENTER)
text(s, 0.75, 5.7, 11.9, 0.5, [[("说明：", {"bold": True, "color": NAVY}), ("① SAP元器件的匹配以质量等级一致为必要条件（不一致即否决），并同步比对供应商、型号规格、封装形式；其余类别未启用该项约束。", {})]], size=12, leading=1.2)
text(s, 0.75, 6.25, 11.9, 0.5, "② 各类别占比取决于该批源数据与集团标准库的重叠程度，占比高低不代表匹配质量差异。", size=12, leading=1.2)

# ============ 5 存在的困难 ============
s = slide(); header(s, "存在的困难", "困难主要来自物料基础信息本身的差异，而非计算能力", None)
diffs = [
    ("物料信息天然不一致", "同一物料在两家清单中的型号规格写法、供应商名称、质量等级存在差异；按业务口径，关键属性不一致即不能认定为同一物料——这部分系统不能替业务拍板。", RED),
    ("AI 语义识别的能力边界", "已采用 AI 语义识别做候选召回与相似度评分，能找到最接近的候选；但对属性有实际差异的行，语义模型无法判断该差异业务上是否可接受。以 SAP元器件为例，自动匹配率约 12%，其余行需要人工确认。", AMBER),
    ("人工核对工作量大", "首批约 5.5 万行未自动匹配，需业务员逐批核对候选并给出结论；核对质量直接决定最终映射准确率。", AMBER),
    ("基础对照数据缺失", "供应商曾用名 / 简称、厂家与品牌对应关系等基础对照表尚未系统整理，同类差异目前只能逐行人工判断。", NAVY),
]
y = 1.85
for t, d, c in diffs:
    box(s, 0.7, y, 11.9, 1.08, fill=WHITE, line=LIGHT, round_=True)
    box(s, 0.7, y, 0.14, 1.08, fill=c)
    text(s, 1.1, y + 0.05, 3.15, 0.96, t, size=14, color=c, bold=True, anchor=MSO_ANCHOR.MIDDLE, leading=1.12)
    text(s, 4.4, y + 0.05, 8.0, 0.98, d, size=11, color=DARK, anchor=MSO_ANCHOR.MIDDLE, leading=1.2)
    y += 1.17
text(s, 0.72, 6.58, 11.9, 0.4, "结论：系统已完成「能自动判定的全部自动判定」，剩余差异需要业务数据治理与人工核对共同解决。", size=13, color=NAVY, bold=True)

# ============ 6 下一步计划 ============
s = slide(); header(s, "下一步计划", "两条线并行：基础数据治理（提升自动率）+ 人工核对（保证准确率）", None)
plans = [
    ("整理供应商对照表", "业务梳理供应商曾用名 / 简称 / 品牌对应关系，批量导入系统值映射；此后同类差异自动对齐，直接提升自动匹配率", "业务 + 系统管理员"),
    ("候选分批人工核对", "约 5.5 万行按类别分批：业务员在第三步按「候选1～5 / 均不匹配」批量确认，核对结果形成新版本记录，可追溯", "业务人员"),
    ("约束规则按类别推广", "参照 SAP元器件「质量等级一票否决」实践，其余类别由业务确定关键属性与约束后配置", "业务 + 实施"),
    ("方案固化与后续批次", "首批核对完成后的方案作为标准版本，后续新到物料直接复用；匹配率与工作量数据按批汇报", "实施"),
]
y = 1.85
for i, (t, d, who) in enumerate(plans):
    box(s, 0.7, y, 11.9, 1.05, fill=WHITE, line=LIGHT, round_=True)
    text(s, 0.95, y + 0.06, 0.8, 0.92, str(i + 1), size=24, color=BLUE, bold=True, anchor=MSO_ANCHOR.MIDDLE)
    text(s, 1.75, y + 0.06, 2.95, 0.92, t, size=14, color=NAVY, bold=True, anchor=MSO_ANCHOR.MIDDLE, leading=1.12)
    text(s, 4.8, y + 0.05, 6.1, 0.94, d, size=11, color=DARK, anchor=MSO_ANCHOR.MIDDLE, leading=1.2)
    text(s, 11.0, y + 0.06, 1.5, 0.92, who, size=11, color=GRAY, anchor=MSO_ANCHOR.MIDDLE, leading=1.2)
    y += 1.15
text(s, 0.72, 6.52, 11.9, 0.4, "近期以供应商对照表整理与首批候选核对为重点，进展按批次同步。", size=13, color=NAVY, bold=True)

# ============ 7 结束 ============
s = slide()
box(s, 0, 0, W, H, fill=NAVY)
box(s, 0, 4.3, W, 0.06, fill=YELL)
text(s, 0.9, 2.5, 11.5, 1.2, "自动判定能判的 · 人工确认该认的 · 全程留痕", size=34, color=WHITE, bold=True)
text(s, 0.92, 4.7, 11.5, 0.6, "小罡 AI · 物料集团码智能匹配平台 v1.3.24", size=18, color=LIGHT)
text(s, 0.92, 5.5, 7.5, 0.5, "谢谢", size=22, color=YELL, bold=True)

out = Path(os.environ.get("DECK_OUT", "/oracle/codex/work/MATERIAL/media/物料集团码智能匹配平台-阶段进展汇报-202610.pptx"))
prs.save(out)
print("SLIDES:", total[0], "->", out)
