#!/usr/bin/env python3
"""
generate_operator_award_report.py — 盐城运营商中标报告生成器

数据源：data/unified.db → award 表（中标/成交记录）
中标主体：13 家运营商（移动/电信/联通/广电/铁塔系）

页面结构：
  第1页  汇总表（集团 × 中标数 / 中标金额）
  第2页  移动系当月清单
  第3页  电信系当月清单
  第4页  联通系当月清单
  第5页  广电系当月清单
  第6页  铁塔系当月清单

用法：
    python3 generate_operator_award_report.py
    python3 generate_operator_award_report.py --month 2026-06
    python3 generate_operator_award_report.py --dry-run
"""

import argparse
import os
import sys
from datetime import datetime

PROJ_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(PROJ_DIR, "data", "unified.db")
REPORT_DIR = os.path.join(PROJ_DIR, "output")
os.makedirs(REPORT_DIR, exist_ok=True)

GROUP_ORDER = ["移动", "电信", "联通", "广电", "铁塔"]

# ══════════════════════════════════════════════════════════════════════════
#  13 家运营商定义 — (group, short_name, include_keywords, exclude_keywords)
#  include_keywords: winner 中必须全部包含
#  exclude_keywords: winner 中不能包含任意一个
# ══════════════════════════════════════════════════════════════════════════
COMPANIES = [
    # ── 移动 ──
    ("移动", "苏移集成", ["江苏移动信息系统集成"], []),
    ("移动", "中移集成", ["中移系统集成"],          []),
    ("移动", "盐城移动", ["移动", "盐城"],           ["集成"]),
    ("移动", "江苏移动", ["移动"],                  ["盐城", "集成"]),
    # ── 电信 ──
    ("电信", "中电鸿信", ["中电鸿信"],              []),
    ("电信", "盐城电信", ["电信", "盐城"],           ["鸿信"]),
    ("电信", "江苏电信", ["电信"],                  ["盐城", "鸿信"]),
    # ── 联通 ──
    ("联通", "盐城联通", ["联通", "盐城"],           []),
    ("联通", "江苏联通", ["联通"],                  ["盐城"]),
    # ── 广电 ──
    ("广电", "盐城广电", ["广电", "盐城"],           ["设计研究院", "广播电影"]),
    ("广电", "江苏广电", ["广电有线"],              ["盐城"]),
    # ── 铁塔 ──
    ("铁塔", "盐城铁塔", ["铁塔", "盐城"],           []),
    ("铁塔", "江苏铁塔", ["铁塔"],                  ["盐城"]),
]


def classify_winner(winner: str):
    """返回 (group, short_name) 或 (None, None)"""
    if not winner:
        return None, None
    for group, short_name, inc, exc in COMPANIES:
        if all(k in winner for k in inc) and not any(k in winner for k in exc):
            return group, short_name
    return None, None


# ══════════════════════════════════════════════════════════════════════════
#  数据查询
# ══════════════════════════════════════════════════════════════════════════

def query_data(conn, month_str: str) -> dict:
    """month_str: 'YYYY-MM'"""
    month_start = month_str + "-01"
    # 月末：取下月1日之前（用字符串比较即可）
    y, m = int(month_str[:4]), int(month_str[5:7])
    if m == 12:
        month_end = f"{y+1}-01-01"
    else:
        month_end = f"{y}-{m+1:02d}-01"

    rows = conn.execute("""
        SELECT purchaser, publish_date, project_name, winning_amount, winner, std_district
        FROM award
        WHERE publish_date >= ? AND publish_date < ?
          AND winner IS NOT NULL AND winner != ''
    """, (month_start, month_end)).fetchall()

    # 分类
    records = []
    for purchaser, pub_date, proj_name, amount, winner, district in rows:
        group, short_name = classify_winner(winner or "")
        if group is None:
            continue
        records.append({
            "purchaser": purchaser or "",
            "publish_date": pub_date or "",
            "project_name": proj_name or "",
            "winning_amount": amount,
            "winner": winner or "",
            "winner_short": short_name,
            "group": group,
            "std_district": district or "",
        })

    data = {"records": records, "month_str": month_str}

    # 汇总（按集团 × 企业）
    from collections import defaultdict
    summary = defaultdict(lambda: {"count": 0, "amount": 0.0})
    for r in records:
        key = (r["group"], r["winner_short"])
        summary[key]["count"] += 1
        summary[key]["amount"] += r["winning_amount"] or 0.0

    data["summary"] = dict(summary)

    # 按集团分组清单
    for g in GROUP_ORDER:
        data[f"{g}_list"] = [r for r in records if r["group"] == g]
        data[f"{g}_list"].sort(key=lambda r: r["publish_date"], reverse=True)

    return data


# ══════════════════════════════════════════════════════════════════════════
#  PDF 生成
# ══════════════════════════════════════════════════════════════════════════

def build_pdf(data: dict, output_path: str):
    try:
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
        )
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.ttfonts import TTFont
    except ImportError:
        print("❌ 需要 ReportLab: pip install reportlab")
        sys.exit(1)

    for fp in ["/System/Library/Fonts/PingFang.ttc",
               "/System/Library/Fonts/STHeiti Light.ttc",
               "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf"]:
        if os.path.exists(fp):
            pdfmetrics.registerFont(TTFont("CF", fp))
            break
    else:
        pdfmetrics.registerFont(TTFont("CF", "/System/Library/Fonts/Supplemental/Arial.ttf"))

    doc = SimpleDocTemplate(
        output_path, pagesize=A4,
        topMargin=18*mm, bottomMargin=12*mm,
        leftMargin=15*mm, rightMargin=15*mm,
    )
    W = doc.width

    S = {
        "title":   ParagraphStyle("t",  fontName="CF", fontSize=16, alignment=TA_CENTER, leading=22, spaceAfter=4),
        "sub":     ParagraphStyle("s",  fontName="CF", fontSize=9,  alignment=TA_CENTER, leading=12, spaceAfter=8, textColor=colors.grey),
        "section": ParagraphStyle("sc", fontName="CF", fontSize=13, alignment=TA_LEFT,   leading=18, spaceBefore=4, spaceAfter=4, textColor=colors.HexColor("#1f4e79")),
        "hdr":     ParagraphStyle("h",  fontName="CF", fontSize=9,  alignment=TA_CENTER, leading=11, textColor=colors.white, wordWrap="CJK"),
        "cc":      ParagraphStyle("cc", fontName="CF", fontSize=8,  alignment=TA_CENTER, leading=10, wordWrap="CJK"),
        "cl":      ParagraphStyle("cl", fontName="CF", fontSize=8,  alignment=TA_LEFT,   leading=10, wordWrap="CJK"),
        "bold":    ParagraphStyle("b",  fontName="CF", fontSize=8,  alignment=TA_CENTER, leading=10, wordWrap="CJK"),
    }

    def P(text, skey="cl"):
        return Paragraph(str(text) if text is not None else "", S[skey])

    HEADER_BG = colors.HexColor("#1f4e79")
    GROUP_BG  = colors.HexColor("#d6e4f0")
    SUBTOT_BG = colors.HexColor("#bdd7ee")
    TOTAL_BG  = colors.HexColor("#2e75b6")
    ROW_ALT   = colors.HexColor("#f5f8fc")

    def base_style():
        return [
            ("VALIGN",        (0,0), (-1,-1), "TOP"),
            ("TOPPADDING",    (0,0), (-1,-1), 2),
            ("BOTTOMPADDING", (0,0), (-1,-1), 2),
            ("LEFTPADDING",   (0,0), (-1,-1), 4),
            ("RIGHTPADDING",  (0,0), (-1,-1), 4),
            ("GRID",          (0,0), (-1,-1), 0.4, colors.HexColor("#cccccc")),
            ("BACKGROUND",    (0,0), (-1,0),  HEADER_BG),
        ]

    def fmt_amt(v):
        if v is None or v == 0:
            return "-"
        if v >= 1e8:
            return f"{v/1e8:.2f}亿"
        if v >= 1e4:
            return f"{v/1e4:.1f}万"
        return f"{v:.0f}元"

    month_str = data["month_str"]
    records_total = len(data["records"])
    elements = []

    # ══════════════════════════════════════════════════════════════════════
    #  第1页：汇总
    # ══════════════════════════════════════════════════════════════════════
    elements.append(P("盐城运营商中标报告", "title"))
    elements.append(P(f"统计月份：{month_str}　　数据来源：yancheng-bidding-pro unified.db", "sub"))
    elements.append(Spacer(1, 4*mm))
    elements.append(P("汇总总览", "section"))

    COL_W = [W*0.30, W*0.35, W*0.35]
    hdr_row = [P("企业", "hdr"), P("中标数（条）", "hdr"), P("中标金额", "hdr")]
    tbl_data = [hdr_row]
    tbl_style = base_style()
    row_idx = 1

    summary = data["summary"]
    grand_count = grand_amt = 0

    for group in GROUP_ORDER:
        # 找出该集团下有数据的企业（按 COMPANIES 顺序）
        g_entries = [(sn, summary[(group, sn)]) for _, sn, _, _ in COMPANIES
                     if _ == group and (group, sn) in summary]
        # 补全 COMPANIES 顺序
        g_entries = []
        for grp, sn, _, _ in COMPANIES:
            if grp == group and (group, sn) in summary:
                g_entries.append((sn, summary[(group, sn)]))
        if not g_entries:
            continue

        g_count = g_amt = 0
        for sn, s in g_entries:
            tbl_data.append([
                P(sn, "cl"),
                P(str(s["count"]), "cc"),
                P(fmt_amt(s["amount"]), "cc"),
            ])
            bg = colors.white if row_idx % 2 else ROW_ALT
            tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
            row_idx += 1
            g_count += s["count"]; g_amt += s["amount"]

        tbl_data.append([
            P(f"【{group}系汇总】", "bold"),
            P(str(g_count), "bold"),
            P(fmt_amt(g_amt), "bold"),
        ])
        tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), SUBTOT_BG))
        row_idx += 1
        grand_count += g_count; grand_amt += g_amt

    tbl_data.append([
        P("总计", "bold"),
        P(str(grand_count), "bold"),
        P(fmt_amt(grand_amt), "bold"),
    ])
    tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), TOTAL_BG))
    tbl_style.append(("TEXTCOLOR", (0, row_idx), (-1, row_idx), colors.white))

    t = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    t.setStyle(TableStyle(tbl_style))
    elements.append(t)

    # ══════════════════════════════════════════════════════════════════════
    #  第2-6页：各集团清单
    # ══════════════════════════════════════════════════════════════════════
    LIST_COL_W = [W*0.20, W*0.09, W*0.36, W*0.11, W*0.24]
    LIST_HDR   = ["发包单位", "发布日期", "项目名称", "中标金额", "中标单位"]

    def build_list_page(title: str, recs: list):
        elements.append(PageBreak())
        elements.append(P(title, "section"))
        elements.append(Spacer(1, 2*mm))
        if not recs:
            elements.append(P("本月暂无数据", "cl"))
            return

        hdr = [P(h, "hdr") for h in LIST_HDR]
        rows = [hdr]
        for i, r in enumerate(recs):
            rows.append([
                P(r["purchaser"][:22], "cl"),
                P(r["publish_date"], "cc"),
                P(r["project_name"][:55], "cl"),
                P(fmt_amt(r["winning_amount"]), "cc"),
                P(r["winner"][:22], "cl"),
            ])

        st = base_style()
        for i in range(1, len(rows)):
            st.append(("BACKGROUND", (0, i), (-1, i), colors.white if i % 2 else ROW_ALT))

        t = Table(rows, colWidths=LIST_COL_W, repeatRows=1)
        t.setStyle(TableStyle(st))
        elements.append(t)
        elements.append(Spacer(1, 2*mm))
        elements.append(P(f"共 {len(recs)} 条", "sub"))

    for group in GROUP_ORDER:
        build_list_page(
            f"{group}系中标清单　{month_str}",
            data[f"{group}_list"],
        )

    doc.build(elements)
    print(f"✅ PDF 已生成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════
#  主入口
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="统计月份 YYYY-MM，默认当月")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    month_str = args.month or datetime.now().strftime("%Y-%m")

    import sqlite3
    conn = sqlite3.connect(DB_PATH)
    try:
        data = query_data(conn, month_str)
    finally:
        conn.close()

    for g in GROUP_ORDER:
        print(f"  {g}系: {len(data[f'{g}_list'])} 条")
    print(f"  合计: {len(data['records'])} 条")

    if args.dry_run:
        return

    output_path = os.path.join(REPORT_DIR, f"盐城运营商中标报告_{month_str}.pdf")
    build_pdf(data, output_path)


if __name__ == "__main__":
    main()
