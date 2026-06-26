#!/usr/bin/env python3
"""HTML类站通用工具：notice_type推断、分页URL生成、列表条目解析。"""
import re
from pathlib import Path

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
    # 异常结果公告（流标/终止等）优先于中标判断，避免误归 award
    if any(k in text for k in ("流标", "废标", "终止公告", "暂停公告", "更正公告", "澄清公告", "补充公告")):
        return "other"
    if any(k in text for k in ("中标", "成交", "候选", "结果公告", "结果公示", "评审结果", "合同", "中选")):
        return "award"
    if any(k in text for k in ("采购意向", "意向公告", "预算公告")):
        return "intention"
    if any(k in text for k in ("终止", "更正", "澄清", "废标")):
        return "other"
    return "tender"


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
