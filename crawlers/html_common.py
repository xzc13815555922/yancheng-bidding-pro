#!/usr/bin/env python3
"""HTML类站通用工具：notice_type推断、分页URL生成、列表条目解析。"""
import re
from pathlib import Path
from typing import Optional

import html2text as _h2t_mod
import requests
from bs4 import BeautifulSoup

# ── Markdown 转换器 ──
_h2t = _h2t_mod.HTML2Text()
_h2t.ignore_links  = False
_h2t.ignore_images = True
_h2t.body_width    = 0
_h2t.single_line_break = True

_ILLEGAL = re.compile(r'[/\\:*?"<>|]')
_MULTI   = re.compile(r'_+')

PAGE_DIR = Path(__file__).parent.parent / "data" / "pages"


def _html_to_md(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for sel in [".TRS_Editor", ".article-content", ".detail-content",
                "#vsb_content", ".content_box", ".art-content", "article",
                ".main-content", "#content"]:
        el = soup.select_one(sel)
        if el and len(el.get_text(strip=True)) > 50:
            return _h2t.handle(str(el)).strip()
    return _h2t.handle(html).strip()


def _safe_name(title: str) -> str:
    t = title.strip()[:60]
    t = _ILLEGAL.sub("_", t)
    t = _MULTI.sub("_", t).strip("_")
    return t or "unnamed"


def save_page_md(html: str, url: str, site_key: str, title: str) -> str:
    """HTML → Markdown，保存到 data/pages/{site_key}/{safe_title}.md。返回绝对路径，失败返回空字符串。"""
    try:
        site_dir = PAGE_DIR / site_key
        site_dir.mkdir(parents=True, exist_ok=True)
        base     = _safe_name(title)
        md_path  = site_dir / f"{base}.md"
        if md_path.exists():
            md_path = site_dir / f"{base}_{abs(hash(url)) % 9999 + 1:04d}.md"
        md = _html_to_md(html)
        if len(md.strip()) < 30:
            return ""
        md_path.write_text(f"# {url}\n\n{md}", encoding="utf-8")
        return str(md_path)
    except Exception:
        return ""


def infer_notice_type(text: str) -> str:
    # P2-2 修复（2026-07-07）：异常/合同变更等精确关键词须先于 award 通用兜底
    # 否则「异常结果公告」「合同变更公告」会被「结果公告」「合同」误命中 award。
    # 第一段：精确「异常类」关键词，覆盖流标/终止/更正/异常结果/合同变更/补充澄清等
    if any(k in text for k in (
        "异常结果",       # BUG-17：异常结果公告（流标结果公告等），否则命中 award
        "流标", "废标",   # 招标失败
        "终止公告", "暂停公告",  # 项目终止/暂停
        "更正公告", "澄清公告", "补充公告",  # 纠错类
        "合同变更",       # 变更公告但带「合同」一词，award 会误命中
    )):
        return "other"
    # 第二段：award 通用兜底
    if any(k in text for k in ("中标", "成交", "候选", "结果公告", "结果公示", "评审结果", "合同", "中选")):
        return "award"
    # 第三段：意向类
    if any(k in text for k in ("采购意向", "意向公告", "预算公告")):
        return "intention"
    # 第四段：兜底终止/更正/澄清/废标
    if any(k in text for k in ("终止", "更正", "澄清", "废标")):
        return "other"
    return "tender"


_SUBTYPE_RULES = [
    ("流标废标", ("流标", "废标", "招标失败", "采购失败", "意向废止", "招标失败公告", "失败公告")),
    ("终止暂停", ("终止", "暂停", "撤销", "中止")),
    ("更正变更", ("更正", "变更", "补充公告", "澄清", "答疑", "延期", "二次公告", "修正", "修改")),
    ("合同履约", ("合同", "履约")),
    ("候选公示", ("候选", "竞价结果", "单一来源", "入围遴选", "入围公告", "不招标")),
]


def classify_other_subtype(name: str, type_hint: str = "") -> str:
    """将 notice_type='other' 的记录细分为可报告的子类型。
    type_hint: 可选的原始 typeName/type 字段（从 raw_json 提取），辅助识别项目名无明确关键词的情况。
    """
    text = name + " " + type_hint
    for subtype, keywords in _SUBTYPE_RULES:
        if any(k in text for k in keywords):
            return subtype
    return "其他"


def parse_datetime(raw: str) -> Optional[str]:
    """归一化各种日期时间格式为 'YYYY-MM-DD HH:MM:SS'。"""
    if not raw:
        return None
    raw = re.sub(r'[*_~`]', '', raw)
    raw = re.sub(r'\s+', '', raw)
    raw = raw.replace('：', ':')
    patterns = [
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:点](\d{1,2})分?(\d{1,2})?秒?',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})[时:点](\d{1,2})',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})日?(\d{1,2})时',
        r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})',
    ]
    for pat in patterns:
        m = re.search(pat, raw)
        if m:
            g = m.groups()
            y, mo, d = g[0], g[1], g[2]
            hh = g[3] if len(g) > 3 and g[3] else "00"
            mm = g[4] if len(g) > 4 and g[4] else "00"
            ss = g[5] if len(g) > 5 and g[5] else "00"
            return f"{int(y):04d}-{int(mo):02d}-{int(d):02d} {int(hh):02d}:{int(mm):02d}:{int(ss):02d}"
    return None


def parse_date_only(raw: str) -> Optional[str]:
    """解析日期为 'YYYY-MM-DD'。"""
    if not raw:
        return None
    raw = re.sub(r'\s+', '', raw)
    m = re.search(r'(\d{4})[年\-/.](\d{1,2})[月\-/.](\d{1,2})', raw)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return None


def extract_date(text: str) -> str:
    """从字符串中提取 YYYY-MM-DD，优先标准格式。"""
    m = re.search(r'(\d{4})[.\-](\d{1,2})[.\-](\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    # 中文格式: 2026年6月16日
    m = re.search(r'(\d{4})年(\d{1,2})月(\d{1,2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2).zfill(2)}-{m.group(3).zfill(2)}"
    # yyyymmdd
    m = re.search(r'(\d{4})(\d{2})(\d{2})', text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return ""


SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
})


def get_html(url: str, timeout: int = 15) -> str:
    r = SESSION.get(url, timeout=timeout)
    if r.encoding and r.encoding.upper() in ("ISO-8859-1", "GB2312", "GBK"):
        r.encoding = "utf-8"
    return r.text
