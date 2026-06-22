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
    "盐城市政府采购网",
    "苏服务",
    "江苏省盐南高新区公共资源交易电子化服务平台",
    "盐城经济技术开发区行政审批局公共资源交易服务平台",
    "盐城市公共资源交易平台",
    "盐城市大数据集团",
    "盐城市都市建设投资集团有限公司",
    "盐东方产业投资集团有限公司",
    "江苏世纪新城投资控股集团有限公司",
    "盐城经开城市发展投资集团有限公司",
    "悦达集团阳光采购平台",
    "江苏招标采购服务平台",
]

SITE_FILTER = {
    "盐城市政府采购网":                      "区域关键词筛选（盐南高新区、经开区）",
    "苏服务":                               "选择区域（经开区、盐南高新区）",
    "江苏省盐南高新区公共资源交易电子化服务平台": "全量采集（盐南高新区专属平台）",
    "盐城经济技术开发区行政审批局公共资源交易服务平台": "全量采集（经开区专属平台）",
    "盐城市公共资源交易平台":               "areaCode=320971(盐南)/320941(经开)分类接口",
    "盐城市大数据集团":                     "全量采集（盐南高新区大数据产业集团）",
    "盐城市都市建设投资集团有限公司":       "全量采集（盐南高新区都市集团）",
    "盐东方产业投资集团有限公司":           "全量采集（经开区东方集团）",
    "江苏世纪新城投资控股集团有限公司":     "全量采集（盐南高新区城南集团）",
    "盐城经开城市发展投资集团有限公司":      "全量采集（经开区城发平台）",
    "悦达集团阳光采购平台":                 "关键词筛选；排除横山/雅海项目",
    "江苏招标采购服务平台":                 "全域盐城（purchaser含盐南/经开关键词筛选）",
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
        Paragraph(f"当日/前一日\n重点招标发布数\n今:{today[5:]} 昨:{yesterday[5:]}", h),
        Paragraph(f"当月\n重点招标发布数\n{report_month}", h),
        Paragraph(f"当月\n非相关招标发布数\n{report_month}", h),
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
        '【分类说明】”非相关招标”指已通过关键词规则归类为与公司业务无关的项目'
        '（如：建设工程、物业服务、法律服务、车辆采购、IT设备、'
        '设计服务、垃圾与环卫、电梯服务等），仅作统计留存，不进入商机池。'
        '”重点招标”为尚未归类、需人工研判的潜在商机，明细清单页逐网站展示。',
        note
    ))
    return story


LARGE_SITE_THRESHOLD = 8  # 记录数 >= 此值则单独占一页


def _site_section(f: str, site: str, rows: List[dict]) -> list:
    """渲染单个网站的标题 + 清单（或暂无提示）"""
    items = []
    sec = _style(f, f"sec{site}", fontSize=12, textColor=DARK_BLUE,
                 spaceAfter=0.2*cm, spaceBefore=0.25*cm)
    items.append(Paragraph(f"▌ {site}　重点招标清单（共{len(rows)}条）", sec))

    if not rows:
        empty = _style(f, f"emp{site}", fontSize=9,
                       textColor=colors.HexColor("#888888"), leading=13, spaceAfter=0.2*cm)
        items.append(Paragraph("本月暂无未分类项目", empty))
        return items

    h   = _style(f, f"DH{site}",  fontSize=9,   alignment=TA_CENTER, textColor=colors.white, leading=12)
    cn  = _style(f, f"DCN{site}", fontSize=8.5, alignment=TA_LEFT,   leading=11)
    cc  = _style(f, f"DCC{site}", fontSize=8.5, alignment=TA_CENTER, leading=11)
    lnk = _style(f, f"DLK{site}", fontSize=7.5, textColor=colors.blue, alignment=TA_CENTER, leading=10)

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
    items.append(tbl)
    return items


def detail_pages(f: str, all_records: List[dict]) -> list:
    """第2页起：
    - 12个网站全部显示（无数据显示暂无提示）
    - 记录数 >= LARGE_SITE_THRESHOLD 的网站单独一页
    - 其余网站连续排列，ReportLab自动续页
    """
    story = []

    by_site: Dict[str, List[dict]] = defaultdict(list)
    for r in all_records:
        if r["proj_major_cat"] is None:
            by_site[r["site_name"]].append(r)

    # 有数据的网站按 SITE_ORDER 排列；0条的网站统一放最后合并显示
    sites_with_data = [s for s in SITE_ORDER if by_site.get(s)]
    sites_no_data   = [s for s in SITE_ORDER if not by_site.get(s)]

    prev_was_large = False
    first = True

    for site in sites_with_data:
        rows = by_site[site]
        is_large = len(rows) >= LARGE_SITE_THRESHOLD

        if first or is_large or prev_was_large:
            story.append(PageBreak())
            first = False

        story.extend(_site_section(f, site, rows))
        prev_was_large = is_large

    # 0条网站合并到最后一页（接续上一段或另起）
    if sites_no_data:
        story.append(PageBreak())
        for site in sites_no_data:
            story.extend(_site_section(f, site, []))

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
