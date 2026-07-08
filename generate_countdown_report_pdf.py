#!/usr/bin/env python3
"""
generate_countdown_report_pdf.py — 盐开开标倒计时报告（PDF版）

用法：python3 generate_countdown_report_pdf.py [YYYY-MM-DD]   默认今日
"""

import os, sys, sqlite3
import logging
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional

from pdf_safe_section import safe_section, SafeSectionTracker

logger = logging.getLogger(__name__)

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

UNIFIED_DB = Path(__file__).parent / "data" / "unified.db"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

# ── 颜色 ────────────────────────────────────────────────────
DARK_BLUE   = colors.HexColor("#1f4e79")
MID_BLUE    = colors.HexColor("#2e74b5")
LIGHT_BLUE  = colors.HexColor("#dce6f1")
ROW_ALT     = colors.HexColor("#f5f8fc")
ORANGE      = colors.HexColor("#c55a11")
ORANGE_FILL = colors.HexColor("#fce4d6")
LINK_COLOR  = colors.HexColor("#0563c1")

# A4 横向，左右各1.2cm页边距
PAGE_W, PAGE_H = landscape(A4)
MARGIN = 1.2 * cm
USABLE_W = PAGE_W - 2 * MARGIN   # ~25.3cm


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


def _fmt_open(s: str) -> str:
    if not s:
        return "—"
    try:
        dt = datetime.strptime(s, "%Y-%m-%d %H:%M:%S")
        return dt.strftime("%m-%d\n%H:%M")
    except ValueError:
        return s[:16]


def _fmt_pub(s: str) -> str:
    return (s or "")[:10].replace("-", "/")


def _query(sql: str, params=()):
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def _countdown(open_date_str: str, today: date) -> Optional[int]:
    if not open_date_str:
        return None
    try:
        return (datetime.strptime(open_date_str[:10], "%Y-%m-%d").date() - today).days
    except ValueError:
        return None


# ── 列宽（横向A4，总可用宽约25.3cm） ──────────────────────────
#   网站 | 项目名称 | 发布时间 | 发包人 | 预算(万元) | 开标时间 | 项目链接
COL_WIDTHS = [
    3.6 * cm,   # 网站
    8.8 * cm,   # 项目名称
    1.9 * cm,   # 发布时间
    5.0 * cm,   # 发包人
    2.2 * cm,   # 预算
    2.2 * cm,   # 开标时间
    1.8 * cm,   # 项目链接
]
HEADERS = ["网站", "项目名称", "发布时间", "发包人",
           "预算(万元)", "开标时间", "链接"]


def _build_table(f: str, rows: List[dict], today: date,
                 future: bool) -> Table:
    """构建数据表格。future=True 为未来清单（倒计时着色），False 为已开标。"""
    p_cell   = _style(f, f"c_{id(rows)}_n", fontSize=8,  alignment=TA_LEFT,
                      leading=10, wordWrap="CJK")
    p_center = _style(f, f"c_{id(rows)}_c", fontSize=8,  alignment=TA_CENTER,
                      leading=10, wordWrap="CJK")
    p_link   = _style(f, f"c_{id(rows)}_l", fontSize=7.5, alignment=TA_CENTER,
                      textColor=LINK_COLOR, leading=10)
    p_head   = _style(f, f"c_{id(rows)}_h", fontSize=8.5, alignment=TA_CENTER,
                      textColor=colors.white, leading=11)

    # 表头
    data = [[Paragraph(h, p_head) for h in HEADERS]]

    for r in rows:
        cd  = _countdown(r["open_date"], today)
        url = r.get("detail_url") or ""

        link_para = (
            Paragraph(f'<a href="{url}" color="#0563c1">查看</a>', p_link)
            if url else Paragraph("—", p_center)
        )

        data.append([
            Paragraph(r["site_name"]    or "—", p_cell),
            Paragraph(r["project_name"] or "—", p_cell),
            Paragraph(_fmt_pub(r["publish_date"]), p_center),
            Paragraph(r["purchaser"]    or "—", p_cell),
            Paragraph(_fmt_budget(r["budget"]),   p_center),
            Paragraph(_fmt_open(r["open_date"]),  p_center),
            link_para,
        ])

    tbl = Table(data, colWidths=COL_WIDTHS, repeatRows=1)

    # 基础样式
    style_cmds = [
        ("BACKGROUND",  (0, 0), (-1, 0),  DARK_BLUE),
        ("FONTNAME",    (0, 0), (-1, 0),  f),
        ("FONTSIZE",    (0, 0), (-1, 0),  8.5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, ROW_ALT]),
        ("GRID",        (0, 0), (-1, -1), 0.4, colors.HexColor("#c0c0c0")),
        ("VALIGN",      (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",  (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING",(0,0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING",(0, 0), (-1, -1), 4),
    ]

    # 未来清单：今日开标行橙色高亮，3天内橙字
    if future:
        for i, r in enumerate(rows, start=1):
            cd = _countdown(r["open_date"], today)
            if cd == 0:
                style_cmds.append(("BACKGROUND", (0, i), (-1, i), ORANGE_FILL))
                style_cmds.append(("FONTNAME",   (0, i), (-1, i), f))
            elif cd is not None and 1 <= cd <= 3:
                style_cmds.append(("TEXTCOLOR", (0, i), (-1, i), ORANGE))

    tbl.setStyle(TableStyle(style_cmds))
    return tbl


def build(run_date: Optional[date] = None):
    today      = run_date or date.today()
    today_str  = today.strftime("%Y-%m-%d")
    yesterday  = today - timedelta(days=1)
    yest_str   = yesterday.strftime("%Y-%m-%d")
    month_start = today_str[:7] + "-01"

    # ── 查询 ────────────────────────────────────────────────
    BASE = """
        SELECT site_name, project_name, publish_date,
               purchaser, budget, open_date, detail_url
        FROM tender
        WHERE proj_major_cat IS NULL
          AND proj_minor_cat IS NULL
          AND std_district IN ('盐南','经开')
    """
    future_rows = _query(
        BASE + "AND open_date >= ? ORDER BY open_date ASC",
        (today_str,)
    )
    past_rows = _query(
        BASE + "AND open_date >= ? AND open_date < ? ORDER BY open_date DESC",
        (month_start, today_str)
    )

    f = _register_font()

    # ── 样式 ────────────────────────────────────────────────
    s_title  = _style(f, "Title",  fontSize=17, textColor=DARK_BLUE,
                      alignment=TA_CENTER, spaceAfter=0.15*cm)
    s_sub    = _style(f, "Sub",    fontSize=9,  textColor=MID_BLUE,
                      alignment=TA_CENTER, spaceAfter=0.4*cm)
    s_sec    = _style(f, "Sec",    fontSize=11, textColor=colors.white,
                      alignment=TA_LEFT, spaceAfter=0, spaceBefore=0,
                      backColor=DARK_BLUE, leftIndent=8)
    s_note   = _style(f, "Note",   fontSize=7.5, textColor=colors.HexColor("#595959"),
                      alignment=TA_LEFT, spaceAfter=0.2*cm)

    # ── 构建 story ──────────────────────────────────────────
    story = []
    tracker = SafeSectionTracker()  # P1-2026-07-07

    # 总标题
    story.append(Paragraph("盐开 · 开标倒计时报告（未分类项目）", s_title))
    story.append(Paragraph(
        f"统计范围：{month_start} ~ {today_str}　　"
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        s_sub
    ))
    # P0-2 警告已于 2026-06-25 移除（reenrich_jszbcg_open_date.py 已修复 1683 条 open_date 从 openBidTime→真开标时间）
    story.append(HRFlowable(width="100%", thickness=1,
                             color=MID_BLUE, spaceAfter=0.3*cm))

    # ── 清单页1：未来开标 ────────────────────────────────────
    story.append(Paragraph(
        f"  清单一　未来开标清单（{today_str} 及以后，共 {len(future_rows)} 条）",
        s_sec
    ))
    story.append(Spacer(1, 0.2*cm))

    if future_rows:
        today_cnt  = sum(1 for r in future_rows
                         if (r["open_date"] or "").startswith(today_str))
        story.append(Paragraph(
            f"⬛ 今日开标 {today_cnt} 条　▶ 橙底=今日开标，橙字=3天内开标",
            s_note
        ))
        # P1-2026-07-07: 表体包 safe_section，表头/标题不被中断
        future_block = safe_section(
            "清单一未来开标表体",
            lambda: _build_table(f, future_rows, today, future=True),
            tracker=tracker,
        )
        story.extend(future_block)
    else:
        story.append(Paragraph("　　本期暂无即将开标的未分类项目。", s_note))

    # ── 清单页2：已开标 ──────────────────────────────────────
    story.append(PageBreak())
    story.append(Paragraph(
        f"  清单二　本月已开标清单（{month_start} ~ {yest_str}，共 {len(past_rows)} 条）",
        s_sec
    ))
    story.append(Spacer(1, 0.2*cm))

    if past_rows:
        story.append(Paragraph(
            f"⬛ 按开标时间倒序排列，最近开标在前",
            s_note
        ))
        # P1-2026-07-07
        past_block = safe_section(
            "清单二已开标表体",
            lambda: _build_table(f, past_rows, today, future=False),
            tracker=tracker,
        )
        story.extend(past_block)
    else:
        story.append(Paragraph("　　本月暂无已开标的未分类项目。", s_note))

    # ── 页脚页眉 ──────────────────────────────────────────────
    def on_page(canvas, doc):
        canvas.saveState()
        canvas.setFont(f, 7.5)
        canvas.setFillColor(colors.HexColor("#888888"))
        canvas.drawString(MARGIN, 0.7*cm,
                          f"盐开开标倒计时报告 · {today_str} · 数据来源：盐开招标公告数据库")
        canvas.drawRightString(
            PAGE_W - MARGIN, 0.7*cm,
            f"第 {doc.page} 页"
        )
        canvas.restoreState()

    # ── 输出 ─────────────────────────────────────────────────
    out = OUTPUT_DIR / f"盐开开标倒计时报告_{today.strftime('%Y%m%d')}.pdf"
    doc = SimpleDocTemplate(
        str(out),
        pagesize=landscape(A4),
        leftMargin=MARGIN, rightMargin=MARGIN,
        topMargin=1.0*cm, bottomMargin=1.2*cm,
    )
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)
    # P1-2026-07-07: 末尾统计行已在 doc.build 前 append
    print(f"✓ {out}  (未来{len(future_rows)}条 / 已开标{len(past_rows)}条)  "
          f"[{tracker.ok_count}段成功 / {tracker.fail_count}段异常]")
    return out


if __name__ == "__main__":
    d = None
    if len(sys.argv) > 1:
        d = date.fromisoformat(sys.argv[1])
    build(d)
