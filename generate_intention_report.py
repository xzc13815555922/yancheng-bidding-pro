#!/usr/bin/env python3
"""
generate_intention_report.py — 盐开采购意向 PDF 报告 (2026-06-25 P2-2 新增)
=========================================================================
清单 1: 当月新发布采购意向 (盐南+经开, 标NULL, 最新在前)
清单 2: 前期发布未挂招标公告 (盐南+经开, 标NULL, 最旧在前)
        剔除规则: purchaser + project_name 前 15 字 模糊匹配 tender 表

用法: python3 generate_intention_report.py [YYYY-MM]   # 默认当月
"""
import os, sys, sqlite3
import calendar
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, PageBreak, HRFlowable
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# P1-2026-07-07: per-section try/except
from pdf_safe_section import safe_section, SafeSectionTracker

UNIFIED_DB = Path(__file__).parent / "data" / "unified.db"
OUTPUT_DIR = Path(__file__).parent / "output"
LOGS_DIR   = Path(__file__).parent / "logs"
OUTPUT_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)

# ── 颜色 ────────────────────────────────────────────────────
DARK_BLUE   = colors.HexColor("#1f4e79")
MID_BLUE    = colors.HexColor("#2e74b5")
LIGHT_BLUE  = colors.HexColor("#dce6f1")
ROW_ALT     = colors.HexColor("#f5f8fc")
ORANGE      = colors.HexColor("#c55a11")
ORANGE_FILL = colors.HexColor("#fce4d6")
LINK_COLOR  = colors.HexColor("#0563c1")

PAGE_W, PAGE_H = landscape(A4)
MARGIN = 1.2 * cm


# ── 复用样式 (来自 generate_countdown_report_pdf.py) ────────
def _register_font() -> str:
    for p in [
        "/System/Library/Fonts/PingFang.ttc",
        "/System/Library/Fonts/STHeiti Light.ttc",
        "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "C:/Windows/Fonts/msyh.ttc",
    ]:
        if os.path.exists(p):
            pdfmetrics.registerFont(TTFont("CF", p))
            return "CF"
    return "Helvetica"


def _style(f: str, name: str, **kw) -> ParagraphStyle:
    base = kw.pop("parent", "Normal")
    return ParagraphStyle(name, parent=getSampleStyleSheet()[base],
                          fontName=f, **kw)


def _fmt_budget(budget) -> str:
    if budget is None:
        return "—"
    wan = budget / 10_000
    if wan >= 10000:
        return f"{wan/10000:.2f}亿"
    if wan >= 1:
        return f"{wan:.1f}"
    return f"<{budget:.0f}元"


def _fmt_pub(s: str) -> str:
    if not s:
        return "—"
    try:
        return datetime.strptime(s[:10], "%Y-%m-%d").strftime("%Y-%m-%d")
    except Exception:
        return s[:10] if s else "—"


# ── 核心查询 ────────────────────────────────────────────────
DISTRICTS = ("盐南", "经开")


def _query_month_intentions(year_month: str) -> List[dict]:
    """清单 1: 当月新发布采购意向, 按发布日期降序."""
    first = year_month + "-01"
    last_day = calendar.monthrange(int(year_month[:4]), int(year_month[5:7]))[1]
    last = f"{year_month}-{last_day:02d}"
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, site_name, project_name, publish_date,
               purchaser, budget, detail_url, sme_target
        FROM intention
        WHERE std_district IN (?, ?)
          AND proj_major_cat IS NULL
          AND proj_minor_cat IS NULL
          AND publish_date >= ? AND publish_date <= ?
        ORDER BY publish_date DESC, project_name ASC
    """, (*DISTRICTS, first, last)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _query_preexisting_intentions(year_month: str) -> List[dict]:
    """清单 2 候选: 前期发布采购意向 (publish_date < 当月第一天)."""
    first = year_month + "-01"
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT id, site_name, project_name, publish_date,
               purchaser, budget, detail_url, sme_target
        FROM intention
        WHERE std_district IN (?, ?)
          AND proj_major_cat IS NULL
          AND proj_minor_cat IS NULL
          AND publish_date < ?
        ORDER BY publish_date ASC, project_name ASC
    """, (*DISTRICTS, first)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _load_tender_pool() -> List[dict]:
    """加载 tender 表里所有盐南+经开 记录, 用于清单 2 剔除.

    2026-06-25 修复: 移除 proj_major_cat/proj_minor_cat IS NULL 过滤.
    原因: 清单 2 意图是剔除'所有已挂的招标', 不论是否已分类.
          原过滤导致 357 条 tender 被排除, 漏剔除 已分类的招标 (如大吉发电厂加固/恒纬商务港).
    """
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute("""
        SELECT purchaser, project_name, detail_url, publish_date
        FROM tender
        WHERE std_district IN (?, ?)
    """, DISTRICTS).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _dedup_against_tender(intentions: List[dict],
                          tenders: List[dict]) -> Tuple[List[dict], List[dict]]:
    """
    剔除规则: 
      - intention 项目的 purchaser == tender 某条 purchaser
      - 且 intention project_name 前 15 字 和 tender project_name 有重叠
        (任一 substring 包含另一)
    返回: (保留, 剔除明细)
    """
    # 建 purchaser -> tenders 索引
    by_purchaser = {}
    for t in tenders:
        p = (t.get("purchaser") or "").strip()
        if p:
            by_purchaser.setdefault(p, []).append(t)

    kept = []
    dedup_log = []
    for it in intentions:
        ip = (it.get("purchaser") or "").strip()
        iname = (it.get("project_name") or "").strip()
        iname_head = iname[:15]
        match_tender = None
        match_reason = None
        if ip in by_purchaser:
            for t in by_purchaser[ip]:
                tname = (t.get("project_name") or "").strip()
                # 名称重叠判定: 任一 substring 包含另一 (15 字内)
                if iname_head and tname:
                    # 用 intention 的 15 字头去 tender 名里查
                    if iname_head in tname or tname[:15] in iname_head:
                        match_tender = t
                        match_reason = f"purchaser+name 匹配 (proj_head={iname_head!r}, tender={tname!r})"
                        break
        if match_tender:
            dedup_log.append({
                "intention_id":   it["id"],
                "intention_name": iname,
                "intention_pub":  it.get("publish_date"),
                "purchaser":      ip,
                "matched_tender_id": match_tender.get("detail_url") or "",
                "matched_tender_name": match_tender.get("project_name", ""),
                "matched_tender_pub":  match_tender.get("publish_date", ""),
                "reason":         match_reason,
            })
        else:
            kept.append(it)
    return kept, dedup_log


# ── 表格构建 ────────────────────────────────────────────────
def _build_table(f: str, rows: List[dict]) -> Table:
    """| 序号 | 项目名称 | 发包人 | 发布时间 | 预算 | 中小微 | 详情链接 |"""
    header = ["序号", "项目名称", "发包人", "发布时间", "预算", "中小微", "详情"]
    body = [header]
    for i, r in enumerate(rows, 1):
        url = r.get("detail_url") or ""
        # 详情列: 短链接或 "—"
        if url:
            # 用 url 最后 30 字符做显示
            display = url[-30:] if len(url) > 30 else url
            # PDF 蓝色超链接
            link_p = Paragraph(
                f'<link href="{url}"><font color="{LINK_COLOR.hexval()}">查看</font></link>',
                ParagraphStyle("Lk", parent=getSampleStyleSheet()["Normal"],
                               fontName=f, fontSize=7.5, alignment=TA_CENTER)
            )
        else:
            link_p = Paragraph("—", ParagraphStyle("Lk", parent=getSampleStyleSheet()["Normal"],
                                                   fontName=f, fontSize=7.5, alignment=TA_CENTER))
        # 中小微列 (P1-2026-07-06)
        sme = r.get("sme_target") or "不涉及"
        if sme == "专门面向":
            sme_p = Paragraph("<font color='#2e7d32'><b>● 专门面向</b></font>",
                              ParagraphStyle("Sme1", parent=getSampleStyleSheet()["Normal"],
                                             fontName=f, fontSize=7, alignment=TA_CENTER))
        elif sme == "非专门但优惠":
            sme_p = Paragraph("<font color='#f57c00'><b>● 优惠</b></font>",
                              ParagraphStyle("Sme2", parent=getSampleStyleSheet()["Normal"],
                                             fontName=f, fontSize=7, alignment=TA_CENTER))
        else:
            sme_p = Paragraph("",
                              ParagraphStyle("Sme3", parent=getSampleStyleSheet()["Normal"],
                                             fontName=f, fontSize=7, alignment=TA_CENTER))
        body.append([
            str(i),
            Paragraph(r.get("project_name") or "—",
                      ParagraphStyle("PN", parent=getSampleStyleSheet()["Normal"],
                                     fontName=f, fontSize=7.5)),
            Paragraph(r.get("purchaser") or "—",
                      ParagraphStyle("PU", parent=getSampleStyleSheet()["Normal"],
                                     fontName=f, fontSize=7.5)),
            Paragraph(_fmt_pub(r.get("publish_date")),
                      ParagraphStyle("PD", parent=getSampleStyleSheet()["Normal"],
                                     fontName=f, fontSize=7.5, alignment=TA_CENTER)),
            Paragraph(_fmt_budget(r.get("budget")),
                      ParagraphStyle("BG", parent=getSampleStyleSheet()["Normal"],
                                     fontName=f, fontSize=7.5, alignment=TA_CENTER)),
            sme_p,
            link_p,
        ])

    col_widths = [1.0*cm, 7.5*cm, 4.5*cm, 2.0*cm, 1.8*cm, 1.8*cm, 1.6*cm]
    t = Table(body, colWidths=col_widths, repeatRows=1)

    style_cmds = [
        ("FONT", (0, 0), (-1, -1), f, 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), DARK_BLUE),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONT", (0, 0), (-1, 0), f, 8.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (3, 1), (4, -1), "CENTER"),
        ("GRID", (0, 0), (-1, -1), 0.3, MID_BLUE),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    # 斑马纹
    for i in range(1, len(body)):
        if i % 2 == 0:
            style_cmds.append(("BACKGROUND", (0, i), (-1, i), ROW_ALT))
    t.setStyle(TableStyle(style_cmds))
    return t


# ── 主流程 ──────────────────────────────────────────────────
def build(year_month: Optional[str] = None):
    ym = year_month or date.today().strftime("%Y-%m")
    first = ym + "-01"

    # 1. 清单 1: 当月新发布
    month_rows = _query_month_intentions(ym)

    # 2. 清单 2 候选: 前期发布
    pre_rows = _query_preexisting_intentions(ym)

    # 3. 加载 tender 池 + 剔除
    tenders = _load_tender_pool()
    pre_kept, dedup_log = _dedup_against_tender(pre_rows, tenders)

    # 4. 写日志 (samples + dedup)
    samples_path = LOGS_DIR / "intention_report_samples.txt"
    dedup_path   = LOGS_DIR / "intention_report_dedup.txt"
    with open(samples_path, "w", encoding="utf-8") as f:
        f.write(f"=== 清单 1 样例 (前 5 条, {ym} 当月新发布, 共 {len(month_rows)} 条) ===\n")
        for r in month_rows[:5]:
            f.write(f"  {r['id'][:8]}  {r.get('publish_date','')}  {r.get('project_name','')[:40]}\n")
            f.write(f"    发包人={r.get('purchaser','')[:30]}  预算={r.get('budget','')}  链接={r.get('detail_url','')}\n")
        f.write(f"\n=== 清单 2 样例 (前 10 条, {ym} 之前发布且未挂招标, 候选 {len(pre_rows)} 条 / 剔除 {len(dedup_log)} 条 / 最终 {len(pre_kept)} 条) ===\n")
        for r in pre_kept[:10]:
            f.write(f"  {r['id'][:8]}  {r.get('publish_date','')}  {r.get('project_name','')[:40]}\n")
            f.write(f"    发包人={r.get('purchaser','')[:30]}  预算={r.get('budget','')}  链接={r.get('detail_url','')}\n")

    with open(dedup_path, "w", encoding="utf-8") as f:
        f.write(f"=== 清单 2 剔除明细 ({ym} 之前发布但已挂招标, 共 {len(dedup_log)} 条) ===\n\n")
        for d in dedup_log:
            f.write(f"--- 剔除: {d['intention_id'][:8]}\n")
            f.write(f"  intention  : {d['intention_name']}\n")
            f.write(f"  发布日期   : {d['intention_pub']}\n")
            f.write(f"  发包人     : {d['purchaser']}\n")
            f.write(f"  匹配到招标 : {d['matched_tender_name']}\n")
            f.write(f"  招标发布日期: {d['matched_tender_pub']}\n")
            f.write(f"  招标链接   : {d['matched_tender_id']}\n")
            f.write(f"  原因       : {d['reason']}\n\n")

    # 5. PDF
    f_pdf = _register_font()
    s_title  = _style(f_pdf, "Title",  fontSize=17, textColor=DARK_BLUE,
                      alignment=TA_CENTER, spaceAfter=0.15*cm)
    s_sub    = _style(f_pdf, "Sub",    fontSize=9,  textColor=MID_BLUE,
                      alignment=TA_CENTER, spaceAfter=0.4*cm)
    s_sec    = _style(f_pdf, "Sec",    fontSize=11, textColor=colors.white,
                      alignment=TA_LEFT, spaceAfter=0, spaceBefore=0,
                      backColor=DARK_BLUE, leftIndent=8)
    s_note   = _style(f_pdf, "Note",   fontSize=7.5, textColor=colors.HexColor("#595959"),
                      alignment=TA_LEFT, spaceAfter=0.2*cm)
    s_desc   = _style(f_pdf, "Desc",   fontSize=9, textColor=colors.HexColor("#333333"),
                      alignment=TA_LEFT, spaceAfter=0.3*cm, leading=12)

    # P1-2026-07-07: 跨 2 个清单的 tracker
    tracker = SafeSectionTracker()

    story = []

    # ── 第 1 页: 标题 + 说明 ──
    story.append(Paragraph("盐开 · 采购意向报告（未分类项目）", s_title))
    story.append(Paragraph(
        f"统计月份：{ym}　　生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        s_sub
    ))
    story.append(HRFlowable(width="100%", thickness=1,
                             color=MID_BLUE, spaceAfter=0.3*cm))

    story.append(Paragraph("■ 报告范围", s_sec))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"区县：盐南、经开　　项目分类：未分类（proj_major_cat/proj_minor_cat 为空）",
        s_desc
    ))

    story.append(Paragraph("■ 清单说明", s_sec))
    story.append(Spacer(1, 0.2*cm))
    story.append(Paragraph(
        f"<b>清单 1　当月新发布采购意向</b>：{ym}-01 ~ {ym}-{calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1]:02d}　共 <b>{len(month_rows)}</b> 条，按发布日期降序（最新在前）",
        s_desc
    ))
    story.append(Paragraph(
        f"<b>清单 2　前期发布未挂招标公告</b>：{ym}-01 之前发布，已剔除已挂招标的 <b>{len(dedup_log)}</b> 条，剩余 <b>{len(pre_kept)}</b> 条，按发布日期升序（最旧在前）",
        s_desc
    ))

    # ── 第 2 页: 清单 1 ──
    # P1-2026-07-07: 清单1 整体（标题+表格+说明）包 safe_section
    story.append(PageBreak())
    story.append(Paragraph(
        f"  清单一　{ym} 当月新发布采购意向（共 {len(month_rows)} 条，最新在前）",
        s_sec
    ))
    story.append(Spacer(1, 0.2*cm))

    def _build_list1():
        blocks = []
        if month_rows:
            blocks.append(Paragraph(
                "⬛ 按 publish_date 降序排序，最新发布在前；项目名相同时按字典序",
                s_note
            ))
            blocks.append(_build_table(f_pdf, month_rows))
        else:
            blocks.append(Paragraph("　　本期暂无当月新发布的采购意向。", s_note))
        return blocks

    list1_block = safe_section("清单 1 · 当月新发布采购意向", _build_list1, tracker=tracker)
    story.extend(list1_block)

    # ── 第 3 页: 清单 2 ──
    # P1-2026-07-07: 清单2 整体（标题+表格+说明）包 safe_section
    story.append(PageBreak())
    story.append(Paragraph(
        f"  清单二　{ym} 之前发布未挂招标公告（共 {len(pre_kept)} 条，最旧在前）",
        s_sec
    ))
    story.append(Spacer(1, 0.2*cm))

    def _build_list2():
        blocks = []
        if pre_kept:
            blocks.append(Paragraph(
                f"⬛ 候选 {len(pre_rows)} 条，已剔除已挂招标 {len(dedup_log)} 条，按 publish_date 升序排序，最旧在前",
                s_note
            ))
            blocks.append(_build_table(f_pdf, pre_kept))
        else:
            blocks.append(Paragraph("　　本期暂无前期发布未挂招标的采购意向。", s_note))
        return blocks

    list2_block = safe_section("清单 2 · 前期未挂招标采购意向", _build_list2, tracker=tracker)
    story.extend(list2_block)

    # P1-2026-07-07: 末尾加 tracker summary
    story.extend(tracker.summary_paragraph("本次采购意向报告"))

    # ── 页脚页眉 ──
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(f_pdf, 7.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(MARGIN, 0.7*cm,
                          f"盐开采购意向报告 · {ym} · 数据来源：盐开招标公告数据库")
        canvas.drawRightString(
            PAGE_W - MARGIN, 0.7*cm,
            f"第 {doc.page} 页"
        )
        canvas.restoreState()

    # ── 输出 ──
    out = OUTPUT_DIR / f"盐开采购意向报告_{ym.replace('-','')}.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.0*cm, bottomMargin=1.2*cm,
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    print(f"✓ {out}")
    print(f"  清单 1: {len(month_rows)} 条 (当月新发布)")
    print(f"  清单 2 候选: {len(pre_rows)} 条 / 剔除: {len(dedup_log)} 条 / 最终: {len(pre_kept)} 条")
    print(f"  样本文档: {samples_path}")
    print(f"  剔除明细: {dedup_path}")
    return out


if __name__ == "__main__":
    ym = sys.argv[1] if len(sys.argv) > 1 else None
    build(ym)
