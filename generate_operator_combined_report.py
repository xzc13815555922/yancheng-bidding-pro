#!/usr/bin/env python3
"""
generate_operator_combined_report.py — 盐城通信运营商中标报告

数据来源：
  1. data/unified.db  → award 表（盐城各招标平台，运营商作为中标方）
  2. data/tyc.db      → tyc_awards 表（本项目天眼查采集，盐城项目）
  3. operator-bid-monitor database.db → bid_records（已有天眼查历史数据）

三源按"项目名前25字 + 发布日期"去重，以 unified.db 为主。
tyc.db 为空时自动使用 operator-bid-monitor 的数据。

报告结构（参照 operator-bid-monitor PDF 格式）：
  第1页  汇总表（集团 × 中标数 / 中标金额 / 数据来源分布）
  第2页  移动系清单
  第3页  电信系清单
  第4页  联通系清单
  第5页  广电系清单
  第6页  铁塔系清单

用法：
    python3 generate_operator_combined_report.py
    python3 generate_operator_combined_report.py --month 2026-06
    python3 generate_operator_combined_report.py --all      # 不限月份，全量
    python3 generate_operator_combined_report.py --dry-run
"""

import argparse
import os
import re
import sqlite3
import sys
from datetime import datetime

PROJ_DIR   = os.path.dirname(os.path.abspath(__file__))
UDB_PATH   = os.path.join(PROJ_DIR, "data", "unified.db")
TYC_PATH   = os.path.join(PROJ_DIR, "data", "tyc.db")
OBM_PATH   = os.path.expanduser("~/.openclaw/plugin-skills/operator-bid-monitor/data/database.db")
REPORT_DIR = os.path.join(PROJ_DIR, "output")
os.makedirs(REPORT_DIR, exist_ok=True)

GROUP_ORDER = ["移动", "电信", "联通", "广电", "铁塔"]

# 13 家运营商匹配规则（unified.db winner 字段 → group/short）
# 顺序：具体 > 模糊
COMPANIES = [
    ("移动", "苏移集成", ["江苏移动信息系统集成"], []),
    ("移动", "中移集成", ["中移系统集成"],          []),
    ("移动", "盐城移动", ["移动", "盐城"],           ["集成"]),
    ("移动", "江苏移动", ["移动"],                  ["盐城", "集成"]),
    ("电信", "中电鸿信", ["中电鸿信"],              []),
    ("电信", "盐城电信", ["电信", "盐城"],           ["鸿信"]),
    ("电信", "江苏电信", ["电信"],                  ["盐城", "鸿信"]),
    ("联通", "盐城联通", ["联通", "盐城"],           []),
    ("联通", "江苏联通", ["联通"],                  ["盐城"]),
    ("广电", "盐城广电", ["广电", "盐城"],           ["设计研究院", "广播电影"]),
    ("广电", "江苏广电", ["广电有线"],              ["盐城"]),
    ("铁塔", "盐城铁塔", ["铁塔", "盐城"],           []),
    ("铁塔", "江苏铁塔", ["铁塔"],                  ["盐城"]),
]


def classify_winner(winner: str):
    if not winner:
        return None, None
    for group, short, inc, exc in COMPANIES:
        if all(k in winner for k in inc) and not any(k in winner for k in exc):
            return group, short
    return None, None


def normalize_name(name: str) -> str:
    """剥除前缀标签，取前25字作去重键"""
    name = re.sub(r'^[【\[].{2,10}[】\]]\s*', '', name or "")
    name = re.sub(r'^关于\s*', '', name)
    return name.strip()[:25]


# ══════════════════════════════════════════════════════════════════════════
#  数据加载
# ══════════════════════════════════════════════════════════════════════════

def load_unified(month_str=None) -> list:
    conn = sqlite3.connect(UDB_PATH)
    if month_str:
        y, m = int(month_str[:4]), int(month_str[5:7])
        start = f"{y}-{m:02d}-01"
        end   = f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01"
        rows = conn.execute("""
            SELECT publish_date, project_name, purchaser, winner, winning_amount, detail_url
            FROM award
            WHERE publish_date >= ? AND publish_date < ?
              AND winner IS NOT NULL AND winner != ''
        """, (start, end)).fetchall()
    else:
        rows = conn.execute("""
            SELECT publish_date, project_name, purchaser, winner, winning_amount, detail_url
            FROM award
            WHERE winner IS NOT NULL AND winner != ''
        """).fetchall()
    conn.close()

    records = []
    for pub_date, proj_name, purchaser, winner, amount, url in rows:
        group, short = classify_winner(winner or "")
        if group is None:
            continue
        records.append({
            "publish_date":    pub_date or "",
            "project_name":    proj_name or "",
            "purchaser":       purchaser or "",
            "winner":          winner or "",
            "winner_short":    short,
            "group":           group,
            "amount":          amount,
            "detail_url":      url or "",
            "source":          "ybp",
        })
    return records


def load_tyc(month_str=None) -> list:
    if not os.path.exists(TYC_PATH):
        return []
    conn = sqlite3.connect(TYC_PATH)
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
    if "tyc_awards" not in tables:
        conn.close()
        return []

    if month_str:
        y, m = int(month_str[:4]), int(month_str[5:7])
        start = f"{y}-{m:02d}-01"
        end   = f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01"
        rows = conn.execute("""
            SELECT publish_date, project_name, procuring_entity,
                   company_short, company_group, bid_amount, detail_url
            FROM tyc_awards
            WHERE project_location LIKE '盐城%'
              AND publish_date >= ? AND publish_date < ?
        """, (start, end)).fetchall()
    else:
        rows = conn.execute("""
            SELECT publish_date, project_name, procuring_entity,
                   company_short, company_group, bid_amount, detail_url
            FROM tyc_awards
            WHERE project_location LIKE '盐城%'
        """).fetchall()
    conn.close()

    records = []
    for pub_date, proj_name, purchaser, short, group, amount, url in rows:
        records.append({
            "publish_date": pub_date or "",
            "project_name": proj_name or "",
            "purchaser":    purchaser or "",
            "winner":       "",          # tyc 的 winner 字段是采集时的原始文本，不需要展示
            "winner_short": short or "",
            "group":        group or "",
            "amount":       amount,
            "detail_url":   url or "",
            "source":       "tyc",
        })
    return records


def load_obm(month_str=None) -> list:
    """从 operator-bid-monitor database.db 加载盐城天眼查数据"""
    if not os.path.exists(OBM_PATH):
        return []
    conn = sqlite3.connect(OBM_PATH)
    try:
        if month_str:
            y, m = int(month_str[:4]), int(month_str[5:7])
            start = f"{y}-{m:02d}-01"
            end   = f"{y+1}-01-01" if m == 12 else f"{y}-{m+1:02d}-01"
            rows = conn.execute("""
                SELECT br.publish_date, br.project_name, br.procuring_entity,
                       e.short_name, e.parent_group, br.bid_amount, br.detail_url
                FROM bid_records br
                JOIN enterprises e ON br.source_enterprise_id = e.id
                WHERE e.is_active=1 AND br.project_location LIKE '盐城%'
                  AND br.publish_date >= ? AND br.publish_date < ?
            """, (start, end)).fetchall()
        else:
            rows = conn.execute("""
                SELECT br.publish_date, br.project_name, br.procuring_entity,
                       e.short_name, e.parent_group, br.bid_amount, br.detail_url
                FROM bid_records br
                JOIN enterprises e ON br.source_enterprise_id = e.id
                WHERE e.is_active=1 AND br.project_location LIKE '盐城%'
            """).fetchall()
    except Exception:
        conn.close()
        return []
    conn.close()

    records = []
    for pub_date, proj_name, purchaser, short, group, amount, url in rows:
        # bid_amount 在 obm 里是万元单位
        records.append({
            "publish_date": pub_date or "",
            "project_name": proj_name or "",
            "purchaser":    purchaser or "",
            "winner":       "",
            "winner_short": short or "",
            "group":        group or "",
            "amount":       amount * 10000 if amount else None,  # 万→元，统一单位
            "detail_url":   url or "",
            "source":       "tyc",
        })
    return records


def merge_and_dedup(ybp: list, tyc: list) -> tuple:
    """
    合并三源去重：key = normalize(project_name)[:25] + publish_date
    优先级：ybp > tyc（本地）= obm（已合并进 tyc 参数）
    """
    seen = {}
    merged = []

    for r in ybp:
        key = normalize_name(r["project_name"]) + "|" + r["publish_date"]
        seen[key] = len(merged)
        merged.append(dict(r))

    tyc_only = 0
    for r in tyc:
        key = normalize_name(r["project_name"]) + "|" + r["publish_date"]
        if key in seen:
            merged[seen[key]]["source"] = "both"
        else:
            seen[key] = len(merged)
            merged.append(dict(r))
            tyc_only += 1

    return merged, tyc_only


# ══════════════════════════════════════════════════════════════════════════
#  PDF 生成
# ══════════════════════════════════════════════════════════════════════════

def build_pdf(records: list, output_path: str, month_str: str, stats: dict):
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
        "sub":     ParagraphStyle("s",  fontName="CF", fontSize=9,  alignment=TA_CENTER, leading=12, spaceAfter=6, textColor=colors.grey),
        "section": ParagraphStyle("sc", fontName="CF", fontSize=13, alignment=TA_LEFT,   leading=18, spaceBefore=4, spaceAfter=4, textColor=colors.HexColor("#1f4e79")),
        "hdr":     ParagraphStyle("h",  fontName="CF", fontSize=9,  alignment=TA_CENTER, leading=11, textColor=colors.white, wordWrap="CJK"),
        "cc":      ParagraphStyle("cc", fontName="CF", fontSize=8,  alignment=TA_CENTER, leading=10, wordWrap="CJK"),
        "cl":      ParagraphStyle("cl", fontName="CF", fontSize=8,  alignment=TA_LEFT,   leading=10, wordWrap="CJK"),
        "bold":    ParagraphStyle("b",  fontName="CF", fontSize=8,  alignment=TA_CENTER, leading=10, wordWrap="CJK"),
        "note":    ParagraphStyle("n",  fontName="CF", fontSize=7,  alignment=TA_LEFT,   leading=9,  textColor=colors.grey),
    }

    def P(text, skey="cl"):
        return Paragraph(str(text) if text is not None else "", S[skey])

    HEADER_BG = colors.HexColor("#1f4e79")
    SUBTOT_BG = colors.HexColor("#bdd7ee")
    TOTAL_BG  = colors.HexColor("#2e75b6")
    ROW_ALT   = colors.HexColor("#f5f8fc")
    SRC_YBP   = colors.HexColor("#e8f4e8")  # 浅绿：盐城招标平台
    SRC_TYC   = colors.HexColor("#fff3e0")  # 浅橙：天眼查
    SRC_BOTH  = colors.HexColor("#f3e5f5")  # 浅紫：双源

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
        return f"{int(v)}元"

    def src_label(s):
        return {"ybp": "招标平台", "tyc": "天眼查", "both": "双源"}.get(s, s)

    elements = []
    period = month_str if month_str else "全量"

    # ══════════════════════════════════════════════════════════════════════
    #  第1页：汇总
    # ══════════════════════════════════════════════════════════════════════
    elements.append(P("盐城通信运营商中标报告", "title"))
    elements.append(P(
        f"统计期间：{period}　　"
        f"招标平台 {stats['ybp_total']} 条｜天眼查 {stats['tyc_total']} 条"
        f"（本地{stats.get('tyc_local',0)}+obm{stats.get('tyc_obm',0)}）｜"
        f"去重后 {stats['merged_total']} 条（重叠 {stats['overlap']} 条）", "sub"
    ))
    elements.append(P(
        "数据来源：unified.db（盐城12站招标平台）+ data/tyc.db（天眼查）　　"
        "■招标平台  ■天眼查  ■双源", "sub"
    ))
    elements.append(Spacer(1, 3*mm))
    elements.append(P("汇总总览", "section"))

    # 按集团统计
    from collections import defaultdict
    grp_stats = defaultdict(lambda: {"count": 0, "amount": 0.0, "ybp": 0, "tyc": 0, "both": 0})
    short_stats = defaultdict(lambda: {"count": 0, "amount": 0.0})

    for r in records:
        g, sh = r["group"], r["winner_short"]
        grp_stats[g]["count"] += 1
        grp_stats[g]["amount"] += r["amount"] or 0
        grp_stats[g][r["source"]] += 1
        short_stats[(g, sh)]["count"] += 1
        short_stats[(g, sh)]["amount"] += r["amount"] or 0

    COL_W = [W*0.22, W*0.13, W*0.13, W*0.13, W*0.13, W*0.13, W*0.13]
    hdr = [P(h, "hdr") for h in ["企业简称", "中标数", "中标金额", "招标平台", "天眼查", "双源", "集团小计"]]
    tbl_data = [hdr]
    tbl_style = base_style()
    row_idx = 1
    grand_count = grand_amt = 0

    for group in GROUP_ORDER:
        gs = grp_stats.get(group)
        if not gs or gs["count"] == 0:
            continue

        # 各企业行
        for grp2, sh in [(g, s) for (g, s) in short_stats if g == group]:
            ss = short_stats[(grp2, sh)]
            tbl_data.append([
                P(sh, "cl"),
                P(str(ss["count"]), "cc"),
                P(fmt_amt(ss["amount"]), "cc"),
                P("", "cc"), P("", "cc"), P("", "cc"),
                P("", "cc"),
            ])
            bg = colors.white if row_idx % 2 else ROW_ALT
            tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), bg))
            row_idx += 1

        # 集团汇总行
        tbl_data.append([
            P(f"【{group}系】", "bold"),
            P(str(gs["count"]), "bold"),
            P(fmt_amt(gs["amount"]), "bold"),
            P(str(gs["ybp"]), "bold"),
            P(str(gs["tyc"]), "bold"),
            P(str(gs["both"]), "bold"),
            P(str(gs["count"]), "bold"),
        ])
        tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), SUBTOT_BG))
        row_idx += 1
        grand_count += gs["count"]
        grand_amt   += gs["amount"]

    # 总计行
    total_ybp  = sum(grp_stats[g]["ybp"]  for g in GROUP_ORDER)
    total_tyc  = sum(grp_stats[g]["tyc"]  for g in GROUP_ORDER)
    total_both = sum(grp_stats[g]["both"] for g in GROUP_ORDER)
    tbl_data.append([
        P("总计", "bold"),
        P(str(grand_count), "bold"),
        P(fmt_amt(grand_amt), "bold"),
        P(str(total_ybp), "bold"),
        P(str(total_tyc), "bold"),
        P(str(total_both), "bold"),
        P(str(grand_count), "bold"),
    ])
    tbl_style.append(("BACKGROUND", (0, row_idx), (-1, row_idx), TOTAL_BG))
    tbl_style.append(("TEXTCOLOR", (0, row_idx), (-1, row_idx), colors.white))

    t = Table(tbl_data, colWidths=COL_W, repeatRows=1)
    t.setStyle(TableStyle(tbl_style))
    elements.append(t)
    elements.append(Spacer(1, 3*mm))
    elements.append(P("■ 招标平台=仅来自盐城12站招标平台  ■ 天眼查=仅来自天眼查  ■ 双源=两源均有（以招标平台为准）", "note"))

    # ══════════════════════════════════════════════════════════════════════
    #  第2-6页：各集团清单
    # ══════════════════════════════════════════════════════════════════════
    LIST_COL_W = [W*0.18, W*0.09, W*0.34, W*0.10, W*0.17, W*0.12]
    LIST_HDR   = ["发包单位", "发布日期", "项目名称", "中标金额", "中标单位", "来源"]

    # 来源颜色映射
    SRC_COLORS = {"ybp": SRC_YBP, "tyc": SRC_TYC, "both": SRC_BOTH}

    def build_list_page(title: str, recs: list):
        elements.append(PageBreak())
        elements.append(P(title, "section"))
        elements.append(Spacer(1, 2*mm))
        if not recs:
            elements.append(P("本期暂无数据", "cl"))
            return

        recs_sorted = sorted(recs, key=lambda r: r["publish_date"], reverse=True)
        hdr_row = [P(h, "hdr") for h in LIST_HDR]
        rows = [hdr_row]
        row_src = []

        for r in recs_sorted:
            winner_display = r["winner_short"] or r["winner"][:18] if r["winner"] else r["winner_short"]
            rows.append([
                P(r["purchaser"][:20], "cl"),
                P(r["publish_date"], "cc"),
                P(r["project_name"][:52], "cl"),
                P(fmt_amt(r["amount"]), "cc"),
                P(winner_display[:18], "cl"),
                P(src_label(r["source"]), "cc"),
            ])
            row_src.append(r["source"])

        st = base_style()
        for i, src in enumerate(row_src, 1):
            bg = SRC_COLORS.get(src, ROW_ALT) if i % 2 == 0 else (
                colors.HexColor("#f0f8f0") if src == "ybp" else
                colors.HexColor("#fffaf0") if src == "tyc" else
                colors.HexColor("#faf0ff")
            )
            st.append(("BACKGROUND", (0, i), (-1, i), bg))

        t = Table(rows, colWidths=LIST_COL_W, repeatRows=1)
        t.setStyle(TableStyle(st))
        elements.append(t)
        elements.append(Spacer(1, 2*mm))
        elements.append(P(f"共 {len(recs)} 条", "sub"))

    for group in GROUP_ORDER:
        grp_recs = [r for r in records if r["group"] == group]
        build_list_page(f"{group}系中标清单　{period}", grp_recs)

    doc.build(elements)
    print(f"✅ PDF 已生成: {output_path}")


# ══════════════════════════════════════════════════════════════════════════
#  Main
# ══════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--month", default=None, help="统计月份 YYYY-MM，默认当月")
    parser.add_argument("--all",   action="store_true", help="不限月份，全量数据")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    month_str = None if args.all else (args.month or datetime.now().strftime("%Y-%m"))

    ybp_records = load_unified(month_str)

    # 天眼查：优先用本地 tyc.db，为空时用 obm database.db
    local_tyc = load_tyc(month_str)
    obm_tyc   = load_obm(month_str)
    # 合并两个天眼查来源（obm 作为补充，local_tyc 优先）
    tyc_seen = set()
    tyc_records = []
    for r in local_tyc:
        key = normalize_name(r["project_name"]) + "|" + r["publish_date"]
        tyc_seen.add(key)
        tyc_records.append(r)
    for r in obm_tyc:
        key = normalize_name(r["project_name"]) + "|" + r["publish_date"]
        if key not in tyc_seen:
            tyc_records.append(r)

    merged, tyc_only = merge_and_dedup(ybp_records, tyc_records)

    stats = {
        "ybp_total":    len(ybp_records),
        "tyc_total":    len(tyc_records),
        "merged_total": len(merged),
        "overlap":      len(tyc_records) - tyc_only,
        "tyc_local":    len(local_tyc),
        "tyc_obm":      len(obm_tyc),
    }

    for g in GROUP_ORDER:
        cnt = sum(1 for r in merged if r["group"] == g)
        print(f"  {g}系: {cnt} 条")
    print(f"  合计: {len(merged)} 条（ybp={stats['ybp_total']} tyc={stats['tyc_total']} 去重后={stats['merged_total']} 重叠={stats['overlap']}）")

    if args.dry_run:
        return

    suffix = month_str or "全量"
    output_path = os.path.join(REPORT_DIR, f"盐城通信运营商中标报告_{suffix}.pdf")
    build_pdf(merged, output_path, month_str or "全量", stats)


if __name__ == "__main__":
    main()
