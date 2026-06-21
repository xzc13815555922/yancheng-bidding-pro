#!/usr/bin/env python3
"""
盐开招标公告月报生成器
数据源：data/unified.db -> tender 表，std_district IN ('盐南','经开')
用法：python3 generate_tender_report.py [YYYY-MM]   默认当月
"""

import os, sys, re, sqlite3
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle,
    Paragraph, Spacer, PageBreak
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

UNIFIED_DB = Path(__file__).parent / "data" / "unified.db"
OUTPUT_DIR = Path(__file__).parent / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

SITE_ORDER = [
    "盐城政府网",
    "苏服务",
    "盐南高新区",
    "盐城开发区",
    "盐城公共资源交易",
    "大数据平台",
    "都市招标",
    "东方招标",
    "江苏城南",
    "盐城经开区",
    "悦达",
    "江苏招标采购服务平台",
]

SITE_FILTER = {
    "盐城政府网":       "区域关键词筛选（盐南高新区、经开区）",
    "苏服务":           "选择区域（经开区、盐南高新区）",
    "盐南高新区":       "全量采集（标记为盐南高新区，无需筛选）",
    "盐城开发区":       "全量采集（标记为经开区，无需筛选）",
    "盐城公共资源交易": "areaCode=320941(盐南)/320991(经开区)分类接口",
    "大数据平台":       "全量采集（标记为区域内，无需筛选）",
    "都市招标":         "全量采集（标记为经开区，无需筛选）",
    "东方招标":         "关键词筛选（盐南高新区、经开区）",
    "江苏城南":         "全量采集（标记为盐南高新区，无需筛选）",
    "盐城经开区":       "全量采集（标记为经开区，无需筛选）",
    "悦达":             "关键词筛选；排除横山/雅海项目",
    "江苏招标采购服务平台": "regionCode=3209 + 保留亭湖/盐都/盐城市级",
}

DARK_BLUE  = colors.HexColor("#1f4e79")
LIGHT_BLUE = colors.HexColor("#dce6f1")
ROW_ALT    = colors.HexColor("#f5f8fc")


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


def _fmt_amount(budget: Optional[float]) -> str:
    if budget is None:
        return "—"
    wan = budget / 10_000
    if wan >= 10000:
        return f"{wan/10000:.2f}亿"
    if wan >= 1:
        return f"{wan:.1f}"
    return f"<{budget:.0f}元"


def _style(f: str, name: str, **kw) -> ParagraphStyle:
    base = kw.pop("parent", "Normal")
    return ParagraphStyle(name, parent=getSampleStyleSheet()[base], fontName=f, **kw)


# ---------- DB 查询 ----------

def _query(sql: str, params=()):
    conn = sqlite3.connect(str(UNIFIED_DB))
    conn.row_factory = sqlite3.Row
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def site_count_unclassified(site: str, date: str) -> int:
    """当日/前一日 未分类数"""
    rows = _query(
        "SELECT COUNT(*) AS n FROM tender "
        "WHERE site_name=? AND publish_date=? "
        "  AND std_district IN ('盐南','经开') "
        "  AND proj_major_cat IS NULL",
        (site, date)
    )
    return rows[0]["n"]


def month_records(first: str, last: str) -> List[dict]:
    """当月全量（含分类/未分类），用于汇总统计"""
    return _query(
        "SELECT site_name, publish_date, project_name, purchaser, "
        "budget, open_date, detail_url, proj_major_cat, proj_minor_cat "
        "FROM tender "
        "WHERE std_district IN ('盐南','经开') "
        "  AND publish_date BETWEEN ? AND ? "
        "ORDER BY publish_date DESC, site_name, project_name",
        (first, last)
    )


# ---------- 页面构建 ----------

def page1_summary(f: str, report_month: str, first: str, last: str,
                  today: str, yesterday: str, all_records: List[dict]) -> list:
    """第1页：招标公告汇总表"""
    story = []

    t1 = _style(f, "T1", parent="Heading1", fontSize=20, textColor=DARK_BLUE,
                alignment=TA_CENTER, spaceAfter=0.2*cm)
    t2 = _style(f, "T2", fontSize=11, alignment=TA_CENTER,
                textColor=colors.HexColor("#2e74b5"), spaceAfter=0.5*cm)

    story.append(Paragraph("盐开招标公告月报", t1))
    story.append(Paragraph(
        f"{report_month}　　统计范围：{first} 至 {last}　　"
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}",
        t2
    ))

    h  = _style(f, "SH",  fontSize=8.5, alignment=TA_CENTER,
                textColor=colors.white, leading=12)
    cv = _style(f, "SV",  fontSize=9,   alignment=TA_CENTER, leading=12)
    cl = _style(f, "SL",  fontSize=8,   alignment=TA_LEFT,   leading=11)

    # 按网站统计当月未分类 / 已分类
    month_unclassified = defaultdict(int)
    month_classified   = defaultdict(int)
    for r in all_records:
        if r["proj_major_cat"] is None:
            month_unclassified[r["site_name"]] += 1
        else:
            month_classified[r["site_name"]] += 1

    tbl_data = [[
        Paragraph("网站名称", h),
        Paragraph(f"当日/前一日\n发布数（未分类）\n今:{today[5:]} 昨:{yesterday[5:]}", h),
        Paragraph(f"当月发布数\n（未分类）\n{report_month}", h),
        Paragraph(f"当月发布数\n（已分类）\n{report_month}", h),
        Paragraph("数据筛选逻辑", h),
    ]]

    total_td = total_yd = total_unc = total_cls = 0

    for site in SITE_ORDER:
        td  = site_count_unclassified(site, today)
        yd  = site_count_unclassified(site, yesterday)
        unc = month_unclassified.get(site, 0)
        cls = month_classified.get(site, 0)
        total_td  += td
        total_yd  += yd
        total_unc += unc
        total_cls += cls

        td_yd_str = f"{td} / {yd}" if (td or yd) else "—"
        tbl_data.append([
            Paragraph(site, _style(f, f"sn{site}", fontSize=9, alignment=TA_LEFT, leading=12)),
            Paragraph(td_yd_str, cv),
            Paragraph(str(unc) if unc else "—", cv),
            Paragraph(str(cls) if cls else "—", cv),
            Paragraph(SITE_FILTER.get(site, "—"), cl),
        ])

    tbl_data.append([
        Paragraph("合计", _style(f, "tot", fontSize=9, alignment=TA_CENTER, leading=12)),
        Paragraph(f"{total_td} / {total_yd}" if (total_td or total_yd) else "—", cv),
        Paragraph(str(total_unc) if total_unc else "—", cv),
        Paragraph(str(total_cls) if total_cls else "—", cv),
        Paragraph("—", cv),
    ])

    tbl = Table(tbl_data, colWidths=[3.5*cm, 2.8*cm, 2.3*cm, 2.3*cm, 6.6*cm], repeatRows=1)
    tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  DARK_BLUE),
        ("BACKGROUND",    (0, -1), (-1, -1), LIGHT_BLUE),
        ("ROWBACKGROUNDS",(0, 1),  (-1, -2), [colors.white, ROW_ALT]),
        ("GRID",          (0, 0),  (-1, -1), 0.3, colors.grey),
        ("VALIGN",        (0, 0),  (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 5),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 4),
    ]))
    story.append(tbl)

    note = _style(f, "NOTE", fontSize=8.5, textColor=colors.HexColor("#444444"),
                  leading=13, spaceBefore=0.35*cm)
    story.append(Paragraph(
        '【分类说明】“当月已分类”项目已通过关键词规则标注标准大类/小类'
        '（如：建设工程、物业服务、法律服务、车辆采购、IT设备、'
        '设计服务、垃圾与环卫、电梯服务等），'
        '表示该类项目与公司业务方向不相关，已从商机池中剖除，仅作统计留存。'
        '明细清单页仅展示“已分类”项目供参考；“未分类”项目为待人工研判的潜在商机。',
        note
    ))
    return story


def detail_pages(f: str, all_records: List[dict]) -> list:
    """第2页起：每个网站一页，只显示已分类项目"""
    story = []

    by_site: Dict[str, List[dict]] = defaultdict(list)
    for r in all_records:
        if r["proj_major_cat"] is None:  # 只显示未分类（潜在商机）
            by_site[r["site_name"]].append(r)

    if not by_site:
        return story

    sorted_sites = sorted(by_site.keys(),
                          key=lambda s: SITE_ORDER.index(s) if s in SITE_ORDER else 99)

    h   = _style(f, "DH",  fontSize=9,   alignment=TA_CENTER, textColor=colors.white, leading=12)
    cn  = _style(f, "DCN", fontSize=8.5, alignment=TA_LEFT,   leading=11)
    cc  = _style(f, "DCC", fontSize=8.5, alignment=TA_CENTER, leading=11)
    lnk = _style(f, "DLK", fontSize=7.5, textColor=colors.blue, alignment=TA_CENTER, leading=10)

    for site in sorted_sites:
        story.append(PageBreak())
        rows = by_site[site]

        sec = _style(f, f"sec{site}", fontSize=13, textColor=DARK_BLUE,
                     spaceAfter=0.3*cm, spaceBefore=0.1*cm)
        story.append(Paragraph(f"▌ {site}　招标公告清单（共{len(rows)}条）", sec))

        tbl_data = [[
            Paragraph("项目名称", h),
            Paragraph("发布日期", h),
            Paragraph("发包人", h),
            Paragraph("项目金额\n（万元）", h),
            Paragraph("开标时间", h),
            Paragraph("链接", h),
        ]]

        for r in rows:
            name = re.sub(r'^【[^】]{2,10}】', '', r["project_name"] or "").strip() or r["project_name"] or "—"
            url  = r["detail_url"] or ""
            link_cell = (
                Paragraph(f"<link href='{url}' color='blue'><u>详情</u></link>", lnk)
                if url else Paragraph("—", cc)
            )
            pub_dt  = (r["publish_date"] or "")[:10] or "—"
            open_dt = (r["open_date"] or "")[:10] or "—"
            tbl_data.append([
                Paragraph(name, cn),
                Paragraph(pub_dt, cc),
                Paragraph((r["purchaser"] or "—").strip(), cn),
                Paragraph(_fmt_amount(r["budget"]), cc),
                Paragraph(open_dt, cc),
                link_cell,
            ])

        tbl = Table(
            tbl_data,
            colWidths=[6.5*cm, 1.8*cm, 3.2*cm, 1.8*cm, 2.0*cm, 1.2*cm],
            repeatRows=1
        )
        tbl.setStyle(TableStyle([
            ("BACKGROUND",    (0, 0), (-1, 0),  DARK_BLUE),
            ("ROWBACKGROUNDS",(0, 1), (-1, -1), [colors.white, ROW_ALT]),
            ("GRID",          (0, 0), (-1, -1), 0.3, colors.grey),
            ("VALIGN",        (0, 0), (-1, -1), "TOP"),
            ("TOPPADDING",    (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("LEFTPADDING",   (0, 0), (-1, -1), 4),
            ("RIGHTPADDING",  (0, 0), (-1, -1), 3),
        ]))
        story.append(tbl)

    return story


# ---------- 主入口 ----------

def generate(year: int, month: int) -> str:
    first = f"{year}-{month:02d}-01"
    if month == 12:
        last = f"{year+1}-01-01"
    else:
        last = f"{year}-{month+1:02d}-01"
    last = (datetime.strptime(last, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")

    today     = datetime.now().strftime("%Y-%m-%d")
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    report_month = f"{year}年{month}月"

    all_records = month_records(first, last)
    if not all_records:
        print(f"[WARN] {report_month} 无盐南/经开数据")
        return ""

    font  = _register_font()
    fname = OUTPUT_DIR / f"盐开招标公告_{year}{month:02d}.pdf"

    doc = SimpleDocTemplate(
        str(fname), pagesize=A4,
        leftMargin=1.5*cm, rightMargin=1.5*cm,
        topMargin=1.5*cm, bottomMargin=1.5*cm,
        title=f"盐开招标公告月报 {report_month}",
        author="盐城招标信息采集系统 Pro v1.5",
    )

    story = []
    story.extend(page1_summary(font, report_month, first, last, today, yesterday, all_records))
    story.extend(detail_pages(font, all_records))

    doc.build(story)
    unclassified = sum(1 for r in all_records if r["proj_major_cat"] is None)
    classified   = sum(1 for r in all_records if r["proj_major_cat"] is not None)
    print(f"✅ {fname}（总{len(all_records)}条：已分类{classified} / 未分类{unclassified}）")
    return str(fname)


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        ym = sys.argv[1]
        y, m = int(ym[:4]), int(ym[5:7])
    else:
        n = datetime.now()
        y, m = n.year, n.month
    path = generate(y, m)
    if path:
        print(path)
